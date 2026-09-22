from copy import deepcopy
from dataclasses import replace

import pytest

from scar.ir.provenance import (
    EventPoint, ExactContract, GuardState, MutationCoverage, Overlap,
    ProvenanceRegistry, region_overlap,
)
from scar.ir.v2 import (
    Completeness, EquivalenceClaim, EvidenceClaim, EvidenceGraph, EvidenceKind,
    ObjectID, ProofStatus, ProvenanceRelation, SemanticGraph, StorageRegionID,
    ValueObservation, ValueSlot, ValueSlotID,
)


OBSERVED = EvidenceClaim(EvidenceKind.OBSERVED, ("fixture:observed-event",), scope="run")


def physical(registry, token="buffer", device="cpu", size=32, offset=0, shape=(8,), strides=(1,), dtype="float32"):
    allocation = registry.allocation(device, size, token, token + ":lifetime")
    region = registry.region(allocation, offset, shape, strides, dtype)
    return allocation, region


def fixture(coverage=Completeness.COMPLETE):
    registry = ProvenanceRegistry()
    allocation, region = physical(registry)
    source = registry.origin(ObjectID("source"), region, OBSERVED, coverage=coverage)
    return registry, allocation, region, source


def contract(registry, source=None):
    return ExactContract("fixture:exact-copy", ProofStatus.PROVEN, registry.scope, OBSERVED,
        checked_versions=(source.version,) if source else (),
        checked_at=registry.current_event if source else None)


def test_registry_roundtrip_preserves_typed_ledgers_and_continues_identity_sequence():
    registry, _, region, source = fixture()
    registry.bind_slot(ValueSlotID("argument"), source, OBSERVED, scope="invocation:1")
    _, copy_region = physical(registry, token="copy")
    copied = registry.copy(source, ObjectID("copy"), copy_region, OBSERVED,
                           contract=contract(registry), coverage=Completeness.COMPLETE)
    registry.attach_observation("legacy:capture:1", source, OBSERVED)
    registry.mutate(source, region, OBSERVED)
    encoded = registry.to_json()
    restored = ProvenanceRegistry.from_json(encoded)
    assert restored.to_json() == encoded
    old_ids = set(restored.graph.allocations)
    allocation = restored.allocation("cpu", 32, "third", "third-life")
    assert allocation not in old_ids
    assert restored.guard(copied).state is GuardState.VALID
    assert restored.assert_valid()["valid"]


def test_address_reuse_requires_a_new_allocation_lifetime():
    registry, allocation, _, source = fixture()
    assert registry.allocation("cpu", 32, "buffer", "buffer:lifetime") == allocation
    registry.end_lifetime(allocation, OBSERVED)
    assert registry.guard(source).state is GuardState.INVALID
    with pytest.raises(ValueError, match="lifetime already ended"):
        registry.allocation("cpu", 32, "buffer", "buffer:lifetime")
    assert registry.allocation("cpu", 32, "buffer", "next-lifetime") != allocation
    assert registry.allocation("cpu", 32, "same-address") != registry.allocation("cpu", 32, "same-address")


def test_mutable_copy_forks_lineage_and_mutation_invalidates_only_its_allocation():
    registry, _, region, source = fixture()
    _, destination = physical(registry, "deepcopy")
    copied = registry.copy(source, ObjectID("copied"), destination, OBSERVED,
                           contract=contract(registry), coverage=Completeness.COMPLETE)
    assert copied.version.logical_value != source.version.logical_value
    assert registry.graph.ancestors(copied.version) == (source.version,)
    record = registry.graph.provenance[registry.graph.versions[copied.version].provenance_id]
    assert record.relation is ProvenanceRelation.COPY
    assert record.equivalence is EquivalenceClaim.EXACT_CONTENT_AT_TIME
    updated = registry.mutate(source, region, OBSERVED)
    assert updated.version.logical_value == source.version.logical_value
    assert updated.version.version == source.version.version + 1
    assert registry.guard(source).state is GuardState.INVALID
    assert registry.guard(copied).state is GuardState.VALID
    changed_copy = registry.mutate(copied, destination, OBSERVED)
    assert changed_copy.version.logical_value == copied.version.logical_value
    assert registry.guard(updated).state is GuardState.VALID


def test_view_write_invalidates_overlapping_views_but_not_disjoint_or_empty_views():
    registry, allocation, _, source = fixture()
    first = registry.region(allocation, 0, (4,), (1,), "float32")
    second = registry.region(allocation, 4, (4,), (1,), "float32")
    empty = registry.region(allocation, 0, (0,), (1,), "float32")
    left = registry.view(source, ObjectID("left"), first, OBSERVED)
    right = registry.view(source, ObjectID("right"), second, OBSERVED)
    nothing = registry.view(source, ObjectID("empty"), empty, OBSERVED)
    changed = registry.mutate(left, first, OBSERVED)
    assert registry.guard(source).state is GuardState.INVALID
    assert registry.guard(left).state is GuardState.INVALID
    assert registry.guard(right).state is GuardState.VALID
    assert registry.guard(nothing).state is GuardState.VALID
    assert changed.version.logical_value == left.version.logical_value
    assert registry.graph.regions[first].allocation == registry.graph.regions[second].allocation


def test_overlap_uses_bytes_and_zero_stride_does_not_allocate_numel_bytes():
    registry = ProvenanceRegistry()
    allocation, region = physical(registry, size=4, shape=(1000000,), strides=(0,))
    bytes_view = registry.region(allocation, 3, (1,), (1,), "uint8")
    assert region_overlap(registry.graph.regions[region], registry.graph.regions[bytes_view]) is Overlap.OVERLAPS
    assert registry.graph.allocations[allocation].nbytes == 4


def test_transform_and_aggregate_never_merge_same_shape_outputs():
    registry, _, _, source = fixture()
    _, region = physical(registry, "output")
    transformed = registry.transform((source,), ObjectID("encoded"), region, OBSERVED)
    assert transformed.version.logical_value != source.version.logical_value
    _, summed_region = physical(registry, "sum")
    aggregate = registry.transform((source, transformed), ObjectID("sum"), summed_region, OBSERVED, aggregate=True)
    assert set(registry.graph.ancestors(aggregate.version)) == {source.version, transformed.version}


def test_unknown_write_coverage_cannot_be_upgraded_by_copy_operator_name():
    registry, _, _, source = fixture(Completeness.UNKNOWN)
    _, target = physical(registry, "target", device="cuda:0")
    result = registry.materialize(source, ObjectID("gpu"), target, OBSERVED,
                                  contract=contract(registry), coverage=Completeness.COMPLETE)
    assert result.version != source.version
    assert registry.guard(source).state is GuardState.NEEDS_VERIFICATION
    assert registry.guard(source).required_facts
    assert not registry.equalities


def test_materialization_shares_attested_version_and_branches_on_independent_write():
    registry, _, _, source = fixture(Completeness.UNKNOWN)
    _, target = physical(registry, "target", device="cuda:0")
    result = registry.materialize(source, ObjectID("gpu"), target, OBSERVED,
                                  contract=contract(registry, source), coverage=Completeness.COMPLETE)
    assert result.version == source.version
    assert result.materialization != source.materialization
    updated = registry.mutate(result, target, OBSERVED)
    assert updated.version.logical_value != source.version.logical_value
    assert source.version in registry.graph.ancestors(updated.version)
    assert registry.guard(source).state is GuardState.NEEDS_VERIFICATION
    assert registry.guard(result).state is GuardState.INVALID


def test_async_readiness_and_same_device_noop_are_distinct():
    registry, _, region, source = fixture()
    before = len(registry.graph.materializations)
    assert registry.materialize(source, source.object_id, region, OBSERVED, contract=None) == source
    assert len(registry.graph.materializations) == before
    _, target = physical(registry, "gpu", device="cuda:0")
    pending = registry.materialize(source, ObjectID("gpu"), target, OBSERVED,
        contract=contract(registry), ready=False, coverage=Completeness.COMPLETE)
    assert pending.version == source.version
    assert registry.guard(pending).state is GuardState.NEEDS_VERIFICATION
    assert not registry.equalities  # completion has not happened yet
    registry.mark_ready(pending, OBSERVED)
    assert registry.guard(pending).state is GuardState.VALID


def test_escape_downgrades_aliases_without_inventing_mutation():
    registry, _, region, source = fixture()
    alias = registry.view(source, ObjectID("view"), region, OBSERVED)
    before = len(registry.graph.versions)
    registry.escape(source, "foreign callback", OBSERVED)
    assert registry.guard(source).state is GuardState.NEEDS_VERIFICATION
    assert registry.guard(alias).state is GuardState.NEEDS_VERIFICATION
    assert len(registry.graph.versions) == before
    with pytest.raises(ValueError, match="observed write"):
        registry.mutate(source, region, EvidenceClaim(EvidenceKind.UNKNOWN))


def test_binding_intervals_and_external_capture_correspondence_preserve_identity():
    registry, _, region, source = fixture()
    slot = ValueSlotID("input")
    registry.bind_slot(slot, source, OBSERVED, scope="call:1")
    updated = registry.mutate(source, region, OBSERVED)
    registry.bind_slot(slot, updated, OBSERVED, scope="call:1")
    assert registry.bindings[0].end_event == registry.bindings[1].start_event
    registry.attach_observation("old-capture", updated, OBSERVED)
    semantic = SemanticGraph()
    semantic.add_slot(ValueSlot(slot, "input", "input"))
    evidence = EvidenceGraph()
    observation = ValueObservation("old-capture", source.version)
    evidence.add_observation(observation)
    assert registry.validate_references(semantic, evidence) == []
    assert observation.version == source.version
    assert registry.attachments[0].handle.version == updated.version
    assert registry.validate_references(SemanticGraph(), EvidenceGraph())


@pytest.mark.parametrize("corruption", ["interval", "duplicate", "wrong-version", "unknown-field", "schema-bool", "binding-overlap", "coverage-evidence"])
def test_registry_decoder_rejects_malformed_ledgers(corruption):
    registry, _, _, source = fixture()
    registry.bind_slot(ValueSlotID("slot"), source, OBSERVED)
    document = deepcopy(registry.to_dict())
    if corruption == "interval":
        document["bindings"][0]["end_event"] = {"scope": "other", "ordinal": 0, "label": "bad"}
    elif corruption == "duplicate":
        document["validity"].append(deepcopy(document["validity"][0]))
    elif corruption == "wrong-version":
        document["validity"][0]["version"]["version"] = 1
        document["validity"][0]["version"]["wire"] = source.version.logical_value.wire + "@v1"
    elif corruption == "unknown-field":
        document["bindings"][0]["allow_reuse"] = True
    elif corruption == "schema-bool":
        document["schema_version"] = True
    elif corruption == "binding-overlap":
        document["bindings"].append(deepcopy(document["bindings"][0]))
    elif corruption == "coverage-evidence":
        document["coverage"][0]["coverage"]["evidence"] = []
    with pytest.raises(ValueError):
        ProvenanceRegistry.from_dict(document)


def test_invalid_requests_do_not_change_registry_or_event_clock():
    registry, _, region, source = fixture()
    before = registry.to_json()
    with pytest.raises(ValueError):
        registry.copy(source, ObjectID("bad"), region, OBSERVED, contract=contract(registry))
    assert registry.to_json() == before
    with pytest.raises(ValueError):
        registry.origin(ObjectID("bad"), StorageRegionID("missing"), OBSERVED)
    assert registry.to_json() == before
    with pytest.raises(ValueError):
        registry.bind_slot("wrong-type", source, OBSERVED)
    assert registry.to_json() == before


def test_exact_contract_cannot_attest_foreign_or_future_event():
    registry, _, _, source = fixture(Completeness.UNKNOWN)
    _, target = physical(registry, "target")
    for point in (EventPoint("other", 0), EventPoint("run", registry.current_event.ordinal + 100)):
        claim = ExactContract("checked-content", ProofStatus.PROVEN, "run", OBSERVED,
                              checked_versions=(source.version,), checked_at=point)
        before = registry.to_json()
        with pytest.raises(ValueError, match="check event"):
            registry.materialize(source, ObjectID("target"), target, OBSERVED, contract=claim)
        assert registry.to_json() == before


def test_recording_equality_does_not_prove_stability_after_check():
    registry, _, _, source = fixture(Completeness.UNKNOWN)
    _, target = physical(registry, "target")
    copied = registry.copy(source, ObjectID("copy"), target, OBSERVED)
    claim = contract(registry, source)
    registry.record_equality(source, copied, claim, "bitwise_snapshot_compare", OBSERVED)
    assert registry.equalities[-1].relation is EquivalenceClaim.EXACT_CONTENT_AT_TIME
    registry.event("later-unobserved-window")
    assert registry.guard(source).state is GuardState.NEEDS_VERIFICATION
    assert registry.guard(copied).state is GuardState.NEEDS_VERIFICATION


def test_cast_materialization_is_transform_even_with_same_shape_and_copy_contract():
    registry, _, _, source = fixture()
    _, target = physical(registry, "cast", size=64, dtype="float64")
    result = registry.materialize(source, ObjectID("cast"), target, OBSERVED, contract=contract(registry))
    assert result.version.logical_value != source.version.logical_value
    provenance = registry.graph.provenance[registry.graph.versions[result.version].provenance_id]
    assert provenance.relation is ProvenanceRelation.TRANSFORM


def test_complete_coverage_requires_evidence_and_foreign_aliases_still_block():
    registry, _, _, source = fixture(Completeness.UNKNOWN)
    with pytest.raises(ValueError, match="auditable evidence"):
        registry.set_coverage(source, MutationCoverage("run", Completeness.COMPLETE))
    registry.set_coverage(source, MutationCoverage("run", Completeness.COMPLETE,
        foreign_aliases=("numpy",), evidence=(OBSERVED,)))
    assert registry.guard(source).state is GuardState.NEEDS_VERIFICATION


def test_mutation_does_not_rescan_all_historical_versions():
    registry, _, region, source = fixture()
    for _ in range(20):
        source = registry.mutate(source, region, OBSERVED)

    class CountIterations(dict):
        scans = 0

        def __iter__(self):
            self.scans += 1
            return super().__iter__()

    registry.graph.versions = CountIterations(registry.graph.versions)
    updated = registry.mutate(source, region, OBSERVED)
    assert updated.version.version == source.version.version + 1
    assert registry.graph.versions.scans == 0
    restored = ProvenanceRegistry.from_json(registry.to_json())
    next_value = restored.mutate(updated, region, OBSERVED)
    assert next_value.version.version == updated.version.version + 1


def test_default_registries_reject_handles_from_another_capture():
    left, _, _, left_handle = fixture()
    right, _, _, right_handle = fixture()
    assert left_handle.object_id == right_handle.object_id
    assert left.namespace != right.namespace
    assert left_handle != right_handle
    with pytest.raises(ValueError, match="unknown or inconsistent"):
        right.guard(left_handle)


def test_explicit_registry_namespace_supports_deterministic_replay():
    documents = []
    for _ in range(2):
        registry = ProvenanceRegistry(namespace="isolated-replay-1")
        _, region = physical(registry)
        registry.origin(ObjectID("source"), region, OBSERVED)
        documents.append(registry.to_json())
    assert documents[0] == documents[1]
