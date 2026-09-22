"""Explicit checkpoint evidence must detect mutations without version counters."""
import gc
import json
import weakref

import numpy as np
import pytest
import torch

from scar.trace.checkpoint import (
    CheckpointBudgetExceeded,
    CheckpointStore,
    CheckpointUnsupported,
    ComparisonStatus,
)


def test_numpy_alias_write_beyond_prefix_requires_full_comparison():
    array = np.arange(64, dtype=np.float32)
    tensor = torch.from_numpy(array)
    store = CheckpointStore(max_bytes=256, prefix_elements=4)
    identifier = store.enroll(tensor)
    initial = store.compare(identifier, tensor)
    assert initial.status is ComparisonStatus.EXACT
    assert initial.method == "bitwise_full" and initial.checked_bytes == 256
    array[-1] += 1
    changed = store.compare(identifier, tensor)
    assert changed.status is ComparisonStatus.DIFFERENT
    assert changed.method == "bitwise_full" and changed.checked_bytes > 16
    assert changed.duration_ns > 0


def test_prefix_is_only_a_rejection_filter_and_reports_no_values():
    tensor = torch.arange(32, dtype=torch.float32)
    store = CheckpointStore(max_bytes=128, prefix_elements=2)
    identifier = store.enroll(tensor)
    tensor[0] += 1
    rejected = store.compare(identifier, tensor)
    assert rejected.status is ComparisonStatus.DIFFERENT
    assert rejected.method == "prefix" and rejected.checked_bytes == 8
    report = rejected.as_dict()
    assert not any(isinstance(value, (list, dict, torch.Tensor)) for value in report.values())
    json.dumps(report)


def test_shape_and_dtype_filter_do_not_read_contents():
    tensor = torch.arange(12, dtype=torch.float32)
    store = CheckpointStore(max_bytes=48)
    identifier = store.enroll(tensor)
    for changed in (tensor.view(3, 4), tensor.to(torch.int32)):
        result = store.compare(identifier, changed)
        assert result.status is ComparisonStatus.DIFFERENT
        assert result.method == "shape_dtype" and result.checked_bytes == 0


def test_inference_tensors_need_no_torch_version_counter():
    with torch.inference_mode():
        tensor = torch.arange(16, dtype=torch.float32)
        store = CheckpointStore(max_bytes=64, prefix_elements=0)
        identifier = store.enroll(tensor)
        assert store.compare(identifier, tensor).status is ComparisonStatus.EXACT
        tensor[-1] += 1
        assert store.compare(identifier, tensor).status is ComparisonStatus.DIFFERENT


@pytest.mark.parametrize("make_view", (
    lambda base: base.t(),
    lambda base: base[::2, 1::2],
    lambda base: base[:1, :].expand(7, -1),
))
def test_noncontiguous_and_zero_stride_views_compare_in_logical_order(make_view):
    base = torch.arange(48, dtype=torch.float32).view(6, 8)
    view = make_view(base)
    store = CheckpointStore(max_bytes=1024, prefix_elements=2, chunk_bytes=128)
    identifier = store.enroll(view)
    assert store.compare(identifier, view.clone()).status is ComparisonStatus.EXACT
    base.add_(1)
    assert store.compare(identifier, view).status is ComparisonStatus.DIFFERENT


def test_strided_prefix_rejection_does_not_flatten_the_full_tensor(monkeypatch):
    base = torch.arange(4096, dtype=torch.float32).view(64, 64)
    view = base.t()
    store = CheckpointStore(max_bytes=16384, prefix_elements=3, chunk_bytes=128)
    identifier = store.enroll(view)
    original_chunk = store._chunk
    sizes = []

    def bounded_chunk(tensor, start, stop):
        sizes.append(stop - start)
        return original_chunk(tensor, start, stop)

    monkeypatch.setattr(store, "_chunk", bounded_chunk)
    base[0, 0] += 1
    result = store.compare(identifier, view)
    assert result.status is ComparisonStatus.DIFFERENT and result.method == "prefix"
    assert len(sizes) == 1 and sizes[0] <= 3


def test_equal_nan_payloads_match_but_changed_payload_and_signed_zero_do_not():
    bits = torch.tensor([0x7FC00001, -2147483648, 0x3F800000], dtype=torch.int32)
    tensor = bits.view(torch.float32)
    store = CheckpointStore(max_bytes=12, prefix_elements=0)
    identifier = store.enroll(tensor)
    assert store.compare(identifier, tensor.clone()).status is ComparisonStatus.EXACT
    bits[0] = 0x7FC00002
    assert store.compare(identifier, tensor).status is ComparisonStatus.DIFFERENT
    bits[0] = 0x7FC00001
    bits[1] = 0
    assert store.compare(identifier, tensor).status is ComparisonStatus.DIFFERENT


def test_store_retains_only_owned_cpu_payload_and_releases_budget():
    tensor = torch.ones(16, requires_grad=True)
    reference = weakref.ref(tensor)
    store = CheckpointStore(max_bytes=64)
    identifier = store.enroll(tensor)
    assert store.bytes_used == 64 and store.count == 1
    del tensor
    gc.collect()
    assert reference() is None
    assert store.compare(identifier, torch.ones(16)).status is ComparisonStatus.EXACT
    with pytest.raises(CheckpointBudgetExceeded):
        store.enroll(torch.zeros(1))
    assert store.bytes_used == 64 and store.count == 1
    assert store.release(identifier)
    assert not store.release(identifier)
    assert store.bytes_used == store.count == 0
    assert store.compare(identifier, torch.ones(16)).status is ComparisonStatus.NEEDS_VERIFICATION
    assert store.enroll(torch.zeros(16)) != identifier


def test_empty_scalar_and_parameter_snapshots_have_explicit_budgets():
    store = CheckpointStore(max_bytes=4, max_entries=2)
    empty = torch.empty(0, 17)
    identifier = store.enroll(empty)
    result = store.compare(identifier, empty)
    assert result.status is ComparisonStatus.EXACT and result.checked_bytes == 0
    parameter = torch.nn.Parameter(torch.tensor(2.0))
    second = store.enroll(parameter)
    assert store.compare(second, torch.tensor(2.0)).status is ComparisonStatus.EXACT
    assert store.describe(second)["nbytes"] == 4
    with pytest.raises(CheckpointBudgetExceeded):
        store.enroll(torch.empty(0))


def test_checkpoint_ids_cannot_be_confused_between_stores():
    first, second = CheckpointStore(max_bytes=4), CheckpointStore(max_bytes=4)
    first_id = first.enroll(torch.tensor(1.0))
    second_id = second.enroll(torch.tensor(2.0))
    assert first_id != second_id
    assert second.compare(first_id, torch.tensor(2.0)).status is ComparisonStatus.NEEDS_VERIFICATION
    assert second.compare(second_id, torch.tensor(2.0)).status is ComparisonStatus.EXACT


def test_high_rank_minimum_working_set_cannot_exceed_chunk_budget():
    store = CheckpointStore(max_bytes=4, chunk_bytes=64)
    with pytest.raises(CheckpointUnsupported, match="chunk budget"):
        store.enroll(torch.ones((1,) * 8))
    assert store.bytes_used == store.count == 0


def test_sparse_quantized_meta_and_interpreted_views_need_verification():
    dense = torch.ones(2, 2)
    store = CheckpointStore(max_bytes=16)
    identifier = store.enroll(dense)
    unsupported = [dense.to_sparse(), torch.quantize_per_tensor(dense, 0.1, 0, torch.qint8),
                   torch.empty(2, 2, device="meta"), torch.ones(2, 2, dtype=torch.complex64).conj()]
    for tensor in unsupported:
        with pytest.raises(CheckpointUnsupported):
            store.enroll(tensor)
        result = store.compare(identifier, tensor)
        assert result.status is ComparisonStatus.NEEDS_VERIFICATION
        assert result.checked_bytes == 0
    assert store.bytes_used == 16


def test_exact_comparison_does_not_promise_future_stability():
    tensor = torch.ones(8)
    store = CheckpointStore(max_bytes=32)
    identifier = store.enroll(tensor)
    first = store.compare(identifier, tensor)
    assert first.status is ComparisonStatus.EXACT
    tensor[-1] += 1
    assert store.compare(identifier, tensor).status is ComparisonStatus.DIFFERENT
    assert "future validity unproven" in first.reason


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA device unavailable")
def test_cuda_is_explicit_and_sync_transfer_cost_is_measured():
    tensor = torch.arange(32, dtype=torch.float32, device="cuda")
    disabled = CheckpointStore(max_bytes=128)
    with pytest.raises(CheckpointUnsupported, match="allow_cuda"):
        disabled.enroll(tensor)
    cpu_identifier = disabled.enroll(tensor.cpu())
    assert disabled.compare(cpu_identifier, tensor).status is ComparisonStatus.NEEDS_VERIFICATION
    store = CheckpointStore(max_bytes=128, allow_cuda=True, prefix_elements=2)
    identifier = store.enroll(tensor)
    result = store.compare(identifier, tensor)
    assert result.status is ComparisonStatus.EXACT and result.checked_bytes == 128
    assert result.synchronized_cuda and result.duration_ns > 0
    assert store.describe(identifier)["storage_device"] == "cpu"
    tensor[-1] += 1
    changed = store.compare(identifier, tensor)
    assert changed.status is ComparisonStatus.DIFFERENT and changed.method == "bitwise_full"
