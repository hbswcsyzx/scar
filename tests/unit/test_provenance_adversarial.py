"""Independent negative tests for provenance and at-time equality evidence."""
from __future__ import annotations

import copy

import numpy as np
import pytest
import torch

from scar.ir.provenance import (
    ExactContract, GuardState, Overlap, ProvenanceRegistry, region_overlap,
)
from scar.ir.v2 import Completeness, EvidenceClaim, EvidenceKind, ObjectID, ProofStatus
from scar.trace.checkpoint import CheckpointStore, ComparisonStatus
from scar.trace.values_v2 import TensorObserver


def observed():
    return EvidenceClaim(EvidenceKind.OBSERVED, references=("fixture:actual-event",), scope="run")


def make_source(registry, *, coverage=Completeness.COMPLETE):
    allocation = registry.allocation("cpu", 64, token="same-address", lifetime="generation:1")
    region = registry.region(allocation, 0, (16,), (1,), "float32")
    return registry.origin(ObjectID("source"), region, observed(), coverage=coverage), region


def make_destination(registry, *, device="cpu"):
    allocation = registry.allocation(device, 64, token="destination", lifetime="destination:1")
    return registry.region(allocation, 0, (16,), (1,), "float32")


def exact_contract(registry, **kwargs):
    return ExactContract("fixture:reviewed-exact-copy", ProofStatus.PROVEN,
                         registry.scope, observed(), **kwargs)


def test_late_enrollment_cannot_retroactively_prove_an_old_prefix_capture():
    array = np.arange(32, dtype=np.float32)
    tensor = torch.from_numpy(array)
    observer = TensorObserver(checkpoint_bytes=512)
    initial = observer.observe(tensor)
    historical_prefix = tensor[:4].clone()
    historical_full = tensor.clone()
    array[-1] += 9
    assert torch.equal(historical_prefix, tensor[:4])

    checkpoint = observer.enroll(tensor)
    result = observer.verify(checkpoint, tensor)
    assert result.comparison.status is ComparisonStatus.EXACT
    assert initial.version != result.handle.version
    assert observer.registry.guard(initial).state is GuardState.NEEDS_VERIFICATION
    assert observer.registry.guard(result.handle).state is GuardState.NEEDS_VERIFICATION
    assert observer.checkpoints.compare(checkpoint, historical_full).status is ComparisonStatus.DIFFERENT


def test_checkpoint_id_from_another_store_cannot_prove_equality():
    first = CheckpointStore(max_bytes=64)
    second = CheckpointStore(max_bytes=64)
    earlier = first.enroll(torch.zeros(8))
    later = second.enroll(torch.ones(8))
    assert earlier != later
    assert second.compare(earlier, torch.ones(8)).status is ComparisonStatus.NEEDS_VERIFICATION
    assert first.compare(later, torch.zeros(8)).status is ComparisonStatus.NEEDS_VERIFICATION


def test_strided_checkpoint_compares_only_its_logical_view():
    base = torch.arange(64, dtype=torch.float32)
    even, odd = base[::2], base[1::2]
    store = CheckpointStore(max_bytes=256, prefix_elements=2, chunk_bytes=128)
    checkpoint = store.enroll(even)
    odd.add_(100)
    assert store.compare(checkpoint, even).status is ComparisonStatus.EXACT
    even[-1] += 1
    result = store.compare(checkpoint, even)
    assert result.status is ComparisonStatus.DIFFERENT
    assert result.method == "bitwise_full"


def test_same_object_checkpoint_can_observe_current_bits_without_proving_future_stability():
    observer = TensorObserver(checkpoint_bytes=256)
    with torch.inference_mode():
        tensor = torch.arange(16, dtype=torch.float32)
        checkpoint = observer.enroll(tensor)
        verified = observer.verify(checkpoint, tensor)
        assert verified.comparison.status is ComparisonStatus.EXACT
        assert observer.registry.guard(verified.handle).state is GuardState.NEEDS_VERIFICATION
        tensor[-1] += 1
        changed = observer.verify(checkpoint, tensor)
    assert changed.comparison.status is ComparisonStatus.DIFFERENT
    assert changed.handle.version != verified.handle.version


def test_exact_copies_share_historical_value_but_branch_when_one_is_written():
    registry = ProvenanceRegistry()
    source, source_region = make_source(registry)
    destination = make_destination(registry)
    copied = registry.copy(source, ObjectID("independent"), destination, observed(),
                           contract=exact_contract(registry), mutable=False,
                           coverage=Completeness.COMPLETE)
    assert copied.version == source.version
    changed = registry.mutate(copied, destination, observed())
    assert changed.version.logical_value != source.version.logical_value
    assert registry.guard(copied).state is GuardState.INVALID
    assert registry.guard(source).state is GuardState.VALID
    assert source.version in registry.graph.ancestors(changed.version)
    source_changed = registry.mutate(source, source_region, observed())
    assert source_changed.version.logical_value == source.version.logical_value
    assert registry.guard(changed).state is GuardState.VALID
    registry.assert_valid()


@pytest.mark.parametrize("method", ["copy", "materialize"])
def test_exact_operation_contract_cannot_certify_unobserved_source_freshness(method):
    registry = ProvenanceRegistry()
    source, _ = make_source(registry, coverage=Completeness.UNKNOWN)
    destination = make_destination(registry)
    kwargs = {"mutable": False} if method == "copy" else {}
    result = getattr(registry, method)(source, ObjectID("result"), destination,
                                      observed(), contract=exact_contract(registry), **kwargs)
    assert result.version != source.version
    assert not registry.equalities
    assert registry.guard(source).state is GuardState.NEEDS_VERIFICATION


def test_at_time_source_equality_does_not_cover_a_later_registry_event():
    registry = ProvenanceRegistry()
    source, _ = make_source(registry, coverage=Completeness.UNKNOWN)
    destination = make_destination(registry)
    contract = exact_contract(registry, checked_versions=(source.version,),
                              checked_at=registry.current_event)
    registry.event("unobserved external code may have run")
    copied = registry.copy(source, ObjectID("copy"), destination, observed(),
                           contract=contract, mutable=False)
    assert copied.version != source.version
    assert not registry.equalities


def test_view_cannot_restore_a_stale_version_to_validity():
    registry = ProvenanceRegistry()
    source, region = make_source(registry)
    registry.mutate(source, region, observed())
    assert registry.guard(source).state is GuardState.INVALID
    with pytest.raises(ValueError):
        registry.view(source, ObjectID("stale-view"), region, observed())


def test_small_interleaved_regions_are_disjoint_but_large_unknown_overlap_is_retained():
    registry = ProvenanceRegistry()
    allocation = registry.allocation("cpu", 80000, token="buffer", lifetime="buffer:1")
    even = registry.region(allocation, 0, (16,), (2,), "float32")
    odd = registry.region(allocation, 1, (16,), (2,), "float32")
    assert region_overlap(registry.graph.regions[even], registry.graph.regions[odd]) is Overlap.DISJOINT
    first = registry.origin(ObjectID("even"), even, observed(), coverage=Completeness.COMPLETE)
    second = registry.origin(ObjectID("odd"), odd, observed(), coverage=Completeness.COMPLETE)
    registry.mutate(first, even, observed())
    assert registry.guard(second).state is GuardState.VALID
    large_even = registry.region(allocation, 0, (5000,), (2,), "float32")
    large_odd = registry.region(allocation, 1, (5000,), (2,), "float32")
    overlap = region_overlap(registry.graph.regions[large_even], registry.graph.regions[large_odd])
    # An implementation may prove these disjoint or stop at a conservative
    # budget.  It cannot claim actual overlapping elements from bounding boxes.
    assert overlap in (Overlap.DISJOINT, Overlap.POSSIBLE)
    large_first = registry.origin(ObjectID("large-even"), large_even, observed(),
                                  coverage=Completeness.COMPLETE)
    large_second = registry.origin(ObjectID("large-odd"), large_odd, observed(),
                                   coverage=Completeness.COMPLETE)
    registry.mutate(large_first, large_even, observed())
    if overlap is Overlap.POSSIBLE:
        assert registry.guard(large_second).state is not GuardState.VALID
    else:
        assert registry.guard(large_second).state is GuardState.VALID


def test_overlap_compares_byte_addresses_across_different_dtypes():
    registry = ProvenanceRegistry()
    allocation = registry.allocation("cpu", 16)
    wide = registry.region(allocation, 0, (1,), (1,), "float32")
    half_inside = registry.region(allocation, 1, (1,), (1,), "float16")
    half_after = registry.region(allocation, 2, (1,), (1,), "float16")
    assert region_overlap(registry.graph.regions[wide], registry.graph.regions[half_inside]) is Overlap.OVERLAPS
    assert region_overlap(registry.graph.regions[wide], registry.graph.regions[half_after]) is Overlap.DISJOINT


def test_ended_allocation_cannot_be_resurrected_by_reusing_its_address():
    registry = ProvenanceRegistry()
    source, region = make_source(registry)
    previous = registry.graph.regions[region].allocation
    registry.end_lifetime(previous, observed())
    assert registry.guard(source).state is GuardState.INVALID
    with pytest.raises(ValueError):
        registry.allocation("cpu", 64, token="same-address", lifetime="generation:1")
    replacement = registry.allocation("cpu", 64, token="same-address", lifetime="generation:2")
    assert replacement != previous
    with pytest.raises(ValueError):
        registry.region(previous, 0, (16,), (1,), "float32")


@pytest.mark.parametrize("corruption", ["duplicate_ledger", "wrong_scope", "rewound_serial", "typed_id"])
def test_registry_document_rejects_identity_or_execution_scope_corruption(corruption):
    registry = ProvenanceRegistry()
    make_source(registry)
    document = copy.deepcopy(registry.to_dict())
    if corruption == "duplicate_ledger":
        document["validity"].append(copy.deepcopy(document["validity"][0]))
    elif corruption == "wrong_scope":
        document["current_event"]["scope"] = "another-execution"
    elif corruption == "rewound_serial":
        document["serial"] = 0
    else:
        document["handles"][0]["object_id"]["kind"] = "alloc"
    with pytest.raises(ValueError):
        ProvenanceRegistry.from_dict(document)


def test_registry_json_rejects_duplicate_document_fields():
    registry = ProvenanceRegistry()
    make_source(registry)
    payload = registry.to_json()
    malformed = '{"scope":"forged",' + payload[1:]
    with pytest.raises(ValueError):
        ProvenanceRegistry.from_json(malformed)
