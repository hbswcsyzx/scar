import gc
import weakref

import numpy as np
import pytest
import torch

from scar.ir.v2 import ProvenanceRelation
from scar.trace.values_v2 import TensorObserver


def test_numpy_foreign_write_outside_prefix_advances_observed_version():
    array = np.arange(64, dtype=np.float32)
    tensor = torch.from_numpy(array)
    observer = TensorObserver(checkpoint_bytes=1024)
    checkpoint = observer.enroll(tensor)
    initial = observer.observe(tensor)
    array[-1] += 7
    result = observer.verify(checkpoint, tensor)
    assert result.version_advanced
    assert result.handle.version != initial.version
    assert result.handle.version.logical_value == initial.version.logical_value
    assert result.comparison.status.value == "DIFFERENT"
    assert observer.registry.graph.assert_valid()["valid"]
    observer.release(checkpoint)


def test_regular_observation_copies_no_values_or_proves_future_stability(monkeypatch):
    observer = TensorObserver()
    tensor = torch.arange(16)
    monkeypatch.setattr(observer.checkpoints, "enroll", lambda *_: pytest.fail("implicit checkpoint"))
    first = observer.observe(tensor)
    tensor[-1] += 1
    second = observer.observe(tensor)
    assert first == second
    assert observer.registry.guard(second).state.value == "NEEDS_VERIFICATION"


def test_inference_tensor_tracks_without_reading_torch_version():
    observer = TensorObserver(checkpoint_bytes=1024)
    with torch.inference_mode():
        tensor = torch.arange(16, dtype=torch.float32)
        checkpoint = observer.enroll(tensor)
        tensor[-1] += 1
        result = observer.verify(checkpoint, tensor)
    assert result.version_advanced


def test_expanded_view_retains_real_allocation_and_zero_strides():
    observer = TensorObserver()
    source = torch.arange(4).reshape(1, 4)
    output = source.expand(100, 4)
    parent = observer.observe(source)
    child = observer.view(source, output)
    graph = observer.registry.graph
    parent_region = graph.regions[graph.materializations[parent.materialization].region]
    child_region = graph.regions[graph.materializations[child.materialization].region]
    assert parent_region.allocation == child_region.allocation
    assert child_region.strides[0] == 0
    assert graph.allocations[child_region.allocation].nbytes == source.untyped_storage().nbytes()
    assert child.version.logical_value != parent.version.logical_value
    assert graph.provenance[graph.versions[child.version].provenance_id].relation is ProvenanceRelation.VIEW
    assert graph.assert_valid()["valid"]


def test_observer_and_checkpoint_do_not_retain_source_tensor():
    observer = TensorObserver(checkpoint_bytes=1024)
    tensor = torch.arange(16)
    reference = weakref.ref(tensor)
    checkpoint = observer.enroll(tensor)
    del tensor
    gc.collect()
    assert reference() is None
    observer.release(checkpoint)


def test_descriptor_rebinding_does_not_fabricate_old_allocation_write():
    observer = TensorObserver(checkpoint_bytes=1024)
    tensor = torch.arange(8)
    old = observer.observe(tensor)
    old_allocation = observer.registry.graph.regions[
        observer.registry.graph.materializations[old.materialization].region].allocation
    checkpoint = observer.enroll(tensor)
    tensor.set_(torch.ones(8, dtype=tensor.dtype))
    result = observer.verify(checkpoint, tensor)
    new_allocation = observer.registry.graph.regions[
        observer.registry.graph.materializations[result.handle.materialization].region].allocation
    assert old_allocation != new_allocation
    assert result.handle.version.logical_value != old.version.logical_value
    assert not result.version_advanced


def test_known_view_remains_allocation_witness_after_original_dies():
    observer = TensorObserver()
    base = torch.arange(16)
    view = base[2:]
    handle = observer.view(base, view)
    del base
    gc.collect()
    again = observer.observe(view)
    assert again == handle


def test_checkpoint_cannot_be_rebound_to_equal_but_distinct_object():
    observer = TensorObserver(checkpoint_bytes=1024)
    tensor = torch.arange(8)
    checkpoint = observer.enroll(tensor)
    with pytest.raises(ValueError, match="original live object"):
        observer.verify(checkpoint, tensor.clone())


def test_real_deepcopy_forks_mutable_lineage_and_preserves_source():
    observer = TensorObserver(checkpoint_bytes=1024)
    tensor = torch.arange(16, dtype=torch.float32)
    copied, copy_handle = observer.deepcopy(tensor)
    source = observer.observe(tensor)
    assert copied is not tensor
    assert copied.untyped_storage()._cdata != tensor.untyped_storage()._cdata
    assert copy_handle.version.logical_value != source.version.logical_value
    graph = observer.registry.graph
    record = graph.provenance[graph.versions[copy_handle.version].provenance_id]
    assert record.relation is ProvenanceRelation.COPY
    assert record.inputs == (source.version,)
    copied[-1] += 10
    region = graph.materializations[copy_handle.materialization].region
    changed = observer.registry.mutate(copy_handle, region, observer._evidence("observed copy write"))
    assert changed.version.logical_value == copy_handle.version.logical_value
    assert observer.registry.guard(source).state.value != "INVALID"
    assert tensor[-1].item() == 15
    assert observer.checkpoints.bytes_used == 0


@pytest.mark.skipif(not torch.cuda.is_available(), reason="G4 hardware gate requires CUDA")
def test_real_cuda_materializations_keep_value_until_copy_is_written():
    observer = TensorObserver(checkpoint_bytes=1024, allow_cuda=True)
    tensor = torch.arange(16, dtype=torch.float32)
    gpu, device_handle = observer.copy_to(tensor, "cuda")
    source = observer.observe(tensor)
    assert device_handle.version == source.version
    graph = observer.registry.graph
    assert graph.materializations[device_handle.materialization].device.startswith("cuda")
    assert graph.materializations[source.materialization].device == "cpu"
    gpu[-1] += 10
    torch.cuda.synchronize()
    region = graph.materializations[device_handle.materialization].region
    changed = observer.registry.mutate(device_handle, region, observer._evidence("observed CUDA write"))
    assert changed.version.logical_value != source.version.logical_value
    assert observer.registry.guard(source).state.value != "INVALID"
    host, host_handle = observer.copy_to(gpu, "cpu")
    assert host_handle.version == observer.observe(gpu).version
    assert torch.equal(host, gpu.cpu())
    assert observer.checkpoints.bytes_used == 0
    assert graph.assert_valid()["valid"]


def test_same_device_to_is_not_a_new_materialization():
    observer = TensorObserver(checkpoint_bytes=1024)
    tensor = torch.arange(8)
    result, result_handle = observer.copy_to(tensor, "cpu")
    assert result is tensor
    assert result_handle == observer.observe(tensor)
    graph = observer.registry.graph
    assert not any(record.relation is ProvenanceRelation.MATERIALIZE
                   for record in graph.provenance.values())


def test_same_shape_semantic_transform_is_a_new_value():
    observer = TensorObserver()
    tensor = torch.arange(8, dtype=torch.float32)
    source = observer.observe(tensor)
    output = tensor + 1
    captured = observer.observe(output)
    graph = observer.registry.graph
    region = graph.materializations[captured.materialization].region
    derived = observer.registry.transform((source,), captured.object_id, region,
                                          observer._evidence("observed add scalar"))
    assert derived.version.logical_value != source.version.logical_value
    assert graph.provenance[graph.versions[derived.version].provenance_id].relation is ProvenanceRelation.TRANSFORM
