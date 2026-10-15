"""Structural demand records are not evidence of raw/source/body replay."""
from copy import deepcopy
from dataclasses import fields, replace

import pytest

from scar.ir.program.call_demand import (
    BodyExpansionV6, CallSourceAdmission, CallSourceAdmissionStatus, CallSourceScope,
    DemandOrigin, DemandOriginKind, EnteredCallCode, EntryRoot, ExpansionScheduleV6,
    LegacyObservation, Remainder, SourceCallCandidate,
)
from scar.ir.program.expansion import ContextStoreBudget, ContextUnavailable
from scar.ir.program.ids import OperationID, RegionID
from scar.ir.program.inventory import BodyStatus
from scar.ir.record_codec import decode, encode
from scar.ir.semantics_v2 import SourceSnapshot
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import OperationDefinitionID, SourceAtomID


KEY = "pycode-v2:" + "a" * 64
FINGERPRINT = "sha256:" + "b" * 64
SNAPSHOT = SourceSnapshot("/project/raw.py", FINGERPRINT, python_version="3.14")
SOURCE = SourceReference(SourceAtomID("atom"), SNAPSHOT.path, FINGERPRINT, 2, 4, 0, 12)
DEFINITION = OperationDefinitionID("function")
ORIGINS = (LegacyObservation(0), EnteredCallCode(7, KEY),
           SourceCallCandidate(OperationDefinitionID("call")), Remainder())


def body(**changes):
    return replace(BodyExpansionV6(DEFINITION, SOURCE, ORIGINS), **changes)


def root():
    return EntryRoot(SNAPSHOT, OperationDefinitionID("module-initializer"))


def admission(**changes):
    value = CallSourceAdmission(ORIGINS[1], CallSourceAdmissionStatus.CORE_LINKED,
                               SNAPSHOT, DEFINITION, SOURCE, RegionID("body"))
    return replace(value, **changes)


def schedule(**changes):
    value = ExpansionScheduleV6(ContextStoreBudget(), (body(),), (root(),),
                               (ContextUnavailable("/project/unavailable.py", "context store budget"),))
    return replace(value, **changes)


@pytest.mark.parametrize("origin", ORIGINS)
def test_origin_wire_union_preserves_the_distinct_anchor_family(origin):
    assert decode(DemandOrigin, encode(origin)) == origin
    assert type(decode(DemandOrigin, encode(origin))) is type(origin)
    assert type(origin).from_dict(origin.to_dict()) == origin
    assert "kind" in origin.to_dict()


@pytest.mark.parametrize("record", (*ORIGINS, body(), root(), schedule(), admission(),
                                   CallSourceScope((admission(),))))
def test_all_records_have_strict_roundtrip_and_reject_unknown_fields(record):
    wire = record.to_dict()
    assert type(record).from_dict(wire) == record
    assert decode(type(record), encode(record)) == record
    wire["transformation_authorized"] = False
    with pytest.raises(ValueError):
        type(record).from_dict(wire)


@pytest.mark.parametrize("record", (*ORIGINS, body(), root(), schedule(), admission(),
                                   CallSourceScope((admission(),))))
def test_even_defaulted_fields_are_required_in_wire_records(record):
    wire = record.to_dict()
    del wire[fields(record)[-1].name]
    with pytest.raises(ValueError):
        type(record).from_dict(wire)


@pytest.mark.parametrize("origin", ORIGINS)
def test_origin_kind_cannot_be_changed_or_replaced_by_an_untyped_string(origin):
    wrong = next(kind for kind in DemandOriginKind if kind is not origin.kind)
    with pytest.raises(ValueError):
        replace(origin, kind=wrong)
    with pytest.raises(ValueError):
        replace(origin, kind=origin.kind.value)
    wire = origin.to_dict()
    wire["kind"] = wrong.value
    with pytest.raises(ValueError):
        decode(DemandOrigin, wire)


@pytest.mark.parametrize("origin,field,value", [
    (ORIGINS[0], "index", True), (ORIGINS[0], "index", -1), (ORIGINS[0], "index", "0"),
    (ORIGINS[1], "process_id", True), (ORIGINS[1], "process_id", 0),
    (ORIGINS[1], "code", "pycode-v2:" + "A" * 64), (ORIGINS[1], "code", "filename:f"),
    (ORIGINS[2], "call", OperationID("call")), (ORIGINS[2], "call", "call"),
])
def test_origin_anchors_have_exact_types_and_canonical_code_identity(origin, field, value):
    with pytest.raises(ValueError):
        replace(origin, **{field: value})


def test_call_code_cannot_be_smuggled_through_a_legacy_observation_index():
    wire = ORIGINS[0].to_dict()
    wire["index"] = ORIGINS[1].to_dict()
    with pytest.raises(ValueError):
        LegacyObservation.from_dict(wire)
    wire = ORIGINS[1].to_dict()
    wire["index"] = 0
    with pytest.raises(ValueError):
        decode(DemandOrigin, wire)


def test_multiple_processes_and_causes_share_one_body_without_merging_code_observations():
    second_process = EnteredCallCode(8, KEY)
    task = body(origins=(*ORIGINS, second_process))
    result = ExpansionScheduleV6.from_dict(schedule(entries=(task,)).to_dict())
    assert len(result.entries) == 1
    assert tuple(origin.process_id for origin in result.entries[0].origins
                 if isinstance(origin, EnteredCallCode)) == (7, 8)


@pytest.mark.parametrize("origins", [(), list(ORIGINS), (ORIGINS[1], ORIGINS[1]),
                                     (root(),), ({"kind": "REMAINDER"},)])
def test_body_origins_are_nonempty_unique_and_never_entry_module_frontiers(origins):
    with pytest.raises(ValueError):
        body(origins=origins)


@pytest.mark.parametrize("changes", [
    {"attempted": 1}, {"construction_cost_known": 0}, {"construction_operations": True},
    {"operation_budget_charged": False}, {"construction_operations": -1},
    {"operation_budget_charged": -1}, {"status": "NOT_ATTEMPTED"},
    {"construction_operations": 1, "operation_budget_charged": 1},
    {"operation_budget_charged": 1}, {"construction_cost_known": False},
    {"status": BodyStatus.UNSUPPORTED}, {"attempted": True},
    {"attempted": True, "status": BodyStatus.UNSUPPORTED,
     "construction_operations": 2, "operation_budget_charged": 1},
    {"definition": RegionID("function")},
])
def test_body_work_cannot_be_refunded_or_assigned_to_an_unattempted_task(changes):
    with pytest.raises(ValueError):
        body(**changes)


def test_failed_attempt_retains_known_construction_and_conservative_unknown_charge():
    failed = body(attempted=True, status=BodyStatus.UNSUPPORTED, construction_operations=3,
                  operation_budget_charged=10, construction_cost_known=False)
    linked = body(attempted=True, status=BodyStatus.LOWERED_WITH_GAPS,
                  construction_operations=4, operation_budget_charged=4)
    assert BodyExpansionV6.from_dict(failed.to_dict()) == failed
    assert BodyExpansionV6.from_dict(linked.to_dict()) == linked
    # Whether 10 is the entire remaining budget is checked by the coordinator.
    assert failed.operation_budget_charged >= failed.construction_operations


@pytest.mark.parametrize("changes", [
    {"entries": (body(), body(origins=(Remainder(),)))},
    {"entries": [body()]}, {"entry_roots": [root()]},
    {"entry_roots": (root(), root())},
    {"entry_roots": (root(), replace(root(), initializer=OperationDefinitionID("other")))},
    {"unavailable_contexts": (ContextUnavailable("/project/lost.py", "a"),
                               ContextUnavailable("/project/lost.py", "b"))},
    {"unavailable_contexts": (ContextUnavailable("relative.py", "unavailable"),)},
    {"budget": {"max_compressed_bytes": 1, "max_record_bytes": 1}},
])
def test_schedule_rejects_duplicate_tasks_roots_or_context_boundaries(changes):
    with pytest.raises(ValueError):
        schedule(**changes)


def test_empty_work_is_representable_without_inventing_a_module_body():
    empty = ExpansionScheduleV6(ContextStoreBudget(), (), ())
    assert ExpansionScheduleV6.from_dict(empty.to_dict()) == empty
    assert CallSourceScope.from_dict({"admissions": []}) == CallSourceScope(())
    with pytest.raises(ValueError):
        replace(root(), initializer=RegionID("fake-module-core"))


@pytest.mark.parametrize("status", (CallSourceAdmissionStatus.UNAVAILABLE, CallSourceAdmissionStatus.MISMATCH))
def test_failed_admission_retains_only_group_anchor_and_specific_boundary(status):
    failed = CallSourceAdmission(ORIGINS[1], status, reason="source not in final indexed scope")
    assert CallSourceAdmission.from_dict(failed.to_dict()) == failed
    with pytest.raises(ValueError):
        replace(failed, reason="")
    for field, value in (("snapshot", SNAPSHOT), ("definition", DEFINITION),
                         ("source", SOURCE), ("core_region", RegionID("stale"))):
        with pytest.raises(ValueError):
            replace(failed, **{field: value})


def test_indexed_without_body_preserves_exact_source_but_no_core_claim():
    indexed = admission(status=CallSourceAdmissionStatus.INDEXED_WITHOUT_BODY,
                        core_region=None, reason="body budget exhausted")
    assert CallSourceAdmission.from_dict(indexed.to_dict()) == indexed
    with pytest.raises(ValueError):
        replace(indexed, reason="")
    with pytest.raises(ValueError):
        replace(indexed, core_region=RegionID("fabricated"))


@pytest.mark.parametrize("field,value", [
    ("snapshot", None), ("definition", None), ("source", None), ("core_region", None),
    ("source", replace(SOURCE, path="/project/other.py")),
    ("source", replace(SOURCE, fingerprint="sha256:" + "c" * 64)),
    ("source", replace(SOURCE, path="/project/./raw.py")),
    ("source", replace(SOURCE, start_line=True)),
    ("snapshot", replace(SNAPSHOT, path="relative.py")),
    ("definition", OperationID("function")), ("core_region", OperationDefinitionID("body")),
    ("status", "CORE_LINKED"), ("reason", None), ("origin", ORIGINS[0]),
])
def test_successful_admission_needs_coherent_typed_source_and_core(field, value):
    with pytest.raises(ValueError):
        admission(**{field: value})


def test_admissions_are_unique_per_process_and_code_not_globally_per_code():
    left = admission()
    right = replace(left, origin=EnteredCallCode(8, KEY))
    scope = CallSourceScope((left, right))
    assert CallSourceScope.from_dict(scope.to_dict()) == scope
    with pytest.raises(ValueError):
        CallSourceScope((left, replace(left, reason="same group repeated")))
    with pytest.raises(ValueError):
        CallSourceScope([left])


def test_structure_accepts_unproved_anchors_without_claiming_seed_or_core_authority():
    # No filesystem access or raw proof is performed by these record codecs.
    result = CallSourceScope.from_dict(CallSourceScope((admission(),)).to_dict())
    assert result.admissions[0].definition == DEFINITION
    for record in (result, schedule()):
        names = {field.name for field in fields(record)}
        assert not names & {"verified", "trusted", "effects_established", "transformation_authorized", "report"}


def test_to_dict_rechecks_nested_records_instead_of_trusting_prior_construction():
    corrupt = deepcopy(admission())
    object.__setattr__(corrupt.origin, "process_id", True)
    with pytest.raises(ValueError):
        corrupt.to_dict()
    corrupt_task = deepcopy(body())
    object.__setattr__(corrupt_task.origins[2].call, "value", False)
    with pytest.raises(ValueError):
        corrupt_task.to_dict()


def test_v6_decoder_does_not_accept_the_old_single_origin_shape():
    wire = body().to_dict()
    del wire["origins"]
    wire.update(kind="OBSERVED_CODE", observation_indices=[0], via_call=None)
    with pytest.raises(ValueError):
        BodyExpansionV6.from_dict(wire)
