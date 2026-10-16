"""Protocol-only records: strict fields do not claim runtime binding authority."""
from dataclasses import fields, replace

import pytest

from scar.ir.program.call_edges import CallRecordAnchor, CallTraceFile, CapturedSite, InvocationKey
from scar.ir.program.call_operands import (
    CallOperandBudget, CallableKind, CallableShape, FunctionLayout, LoadNamespace, LoadObservation,
    OperandCallAttempt, OperandCollectionLimits, OperandCollectionMetadata, OperandEntryHandshake,
    OperandEventKind, OperandGap, OperandInstruction, operand_references,
)
from scar.ir.record_codec import decode, encode


CODE = "pycode-v2:" + "a" * 64


def shape():
    return CallableShape(CallableKind.EXACT_FUNCTION, "weak:7:1", CODE,
                         FunctionLayout(2, 0, 0, 3, ("left", "right")))


def common(index, kind, invocation=1):
    return dict(anchor=CallRecordAnchor("/trace/call-operands.7.jsonl", index, "b" * 64, index),
                index=index, kind=kind, process_id=7, thread_id=8, invocation_id=invocation,
                frame_index=1, hook_epoch=1)


def records():
    site = CapturedSite(CODE, 2, "LOAD_FAST_BORROW_LOAD_FAST_BORROW", (1, 1, 4, 5))
    item = CallableShape(CallableKind.OTHER, "operand-snapshot:7:1:1", None, None)
    loads = tuple(LoadObservation(index, LoadNamespace.FAST_LOCAL, "x", 0, item.reference, item)
                  for index in (0, 1))
    instruction = OperandInstruction(**common(1, OperandEventKind.INSTRUCTION), site=site, loads=loads)
    attempt = OperandCallAttempt(**common(2, OperandEventKind.CALL_ATTEMPT),
                                 site=replace(site, offset=4, opname="CALL"), dispatch=shape(),
                                 arg0="operand-snapshot:7:2:1", arg0_missing=False)
    handshake = OperandEntryHandshake(**{**common(3, OperandEventKind.ENTRY_HANDSHAKE, 2), "frame_index": 2},
                                      attempt_index=2, entry_index=2)
    gap = OperandGap(**common(4, OperandEventKind.GAP, None), reason="callback configuration changed")
    return instruction, attempt, handshake, gap


def metadata():
    manifest = tuple(CallTraceFile(f"/trace/call-{family}.7.{suffix}", family, 7, "c" * 64, 100, 1)
                     for family, suffix in (("codes", "jsonl"), ("events", "jsonl"), ("meta", "json")))
    return OperandCollectionMetadata(
        "scar.call-operands-trace", 1, 7, "/project", "CPython fixture", "cpython",
        "CPYTHON_LOAD_OCCURRENCES_V1", OperandCollectionLimits(100000, 32000000, 64, 4096, 8192),
        4, 4, 1, 1, 1, 1, 2, 6, 1000, 0, (), False, False, manifest, False, False, False,
    )


@pytest.mark.parametrize("record", [*records(), shape(), shape().layout, *records()[0].loads, metadata(), CallOperandBudget()])
def test_typed_records_have_strict_codec_roundtrip(record):
    assert decode(type(record), encode(record)) == record


def test_fused_same_reference_loads_keep_two_occurrences_and_charge_all_fields():
    instruction, attempt, handshake, gap = records()
    assert instruction.loads[0].reference == instruction.loads[1].reference
    assert [(instruction.key, load.suboperand) for load in instruction.loads] == [((7, 1), 0), ((7, 1), 1)]
    assert len(operand_references(instruction)) == 4
    assert len(operand_references(attempt)) == 2
    assert not operand_references(handshake) and not operand_references(gap)
    assert instruction.invocation == InvocationKey(7, 8, 1) and gap.invocation is None


@pytest.mark.parametrize("name", [field.name for field in fields(CallOperandBudget)])
@pytest.mark.parametrize("value", [True, 0, -1, 1.0])
def test_all_independent_budget_fields_require_positive_exact_integers(name, value):
    with pytest.raises(ValueError):
        replace(CallOperandBudget(), **{name: value})


@pytest.mark.parametrize("mutation", [
    {"argcount": True}, {"argcount": -1}, {"posonlyargcount": 3}, {"kwonlyargcount": 1},
    {"flags": 7}, {"parameters": ("left", "left")}, {"parameters": ("", "right")},
    {"parameters": ["left", "right"]}, {"parameters": ("left", 1)},
])
def test_function_layout_rejects_inconsistent_counts_and_parameter_types(mutation):
    with pytest.raises(ValueError):
        replace(shape().layout, **mutation)


def test_layout_preserves_real_positional_kwonly_varargs_varkw_order():
    layout = FunctionLayout(2, 1, 1, 15, ("a", "b", "c", "args", "kwargs"))
    assert decode(FunctionLayout, encode(layout)) == layout


@pytest.mark.parametrize("mutation", [
    {"kind": "EXACT_FUNCTION"}, {"reference": None}, {"code": None}, {"layout": None},
    {"code": "same-name"}, {"reference": "snapshot:7:1:1"}, {"reference": "weak:0:1"},
    {"kind": CallableKind.EXACT_METHOD}, {"kind": CallableKind.OTHER},
    {"kind": CallableKind.UNAVAILABLE},
])
def test_callable_shape_cannot_upgrade_other_kinds_or_reference_scopes(mutation):
    with pytest.raises(ValueError):
        replace(shape(), **mutation)


@pytest.mark.parametrize("mutation", [
    {"namespace": "FAST_LOCAL"}, {"slot": ""}, {"slot_index": True}, {"slot_index": None},
    {"namespace": LoadNamespace.GLOBAL}, {"reference": "weak:7:2"}, {"suboperand": False},
])
def test_load_fields_and_shape_reference_must_agree(mutation):
    with pytest.raises(ValueError):
        replace(records()[0].loads[0], **mutation)


@pytest.mark.parametrize("mutation", [
    {"index": True}, {"process_id": True}, {"thread_id": False}, {"frame_index": -1},
    {"hook_epoch": 0}, {"invocation_id": None}, {"kind": OperandEventKind.GAP},
    {"anchor": CallRecordAnchor("/trace/file", 1, "b" * 64, 7)},
])
def test_instruction_common_identity_and_anchor_are_strict(mutation):
    with pytest.raises(ValueError):
        replace(records()[0], **mutation)


@pytest.mark.parametrize("mode", ["duplicate", "reordered", "omitted_first"])
def test_fused_suboperands_cannot_be_deduplicated_or_reordered(mode):
    instruction = records()[0]
    first, second = instruction.loads
    loads = {"duplicate": (first, first), "reordered": (second, first), "omitted_first": (second,)}[mode]
    with pytest.raises(ValueError, match="suboperands"):
        replace(instruction, loads=loads)


@pytest.mark.parametrize("mutation", [
    {"arg0_missing": 1}, {"arg0_missing": True}, {"arg0": None}, {"arg0": "snapshot:7:2:1"},
])
def test_arg0_missing_is_distinct_from_an_observed_none_object(mutation):
    with pytest.raises(ValueError):
        replace(records()[1], **mutation)
    missing = replace(records()[1], arg0=None, arg0_missing=True)
    assert decode(OperandCallAttempt, encode(missing)) == missing


@pytest.mark.parametrize("mutation", [{"entry_index": 1}, {"attempt_index": 3}, {"attempt_index": True}])
def test_handshake_keeps_original_entry_index_separate_from_attempt_and_invocation(mutation):
    with pytest.raises(ValueError):
        replace(records()[2], **mutation)


@pytest.mark.parametrize("mutation", [
    {"schema_version": True}, {"schema_version": 2}, {"implementation": "other"}, {"rule": "trusted"},
    {"events": 3}, {"event_attempts": 3}, {"event_attempts": 5}, {"references": True},
    {"bytes": 32000001}, {"previous_profile": 0}, {"io_failed": 1},
    {"reference_contents_observed": True}, {"callable_environment_established": True},
    {"transformation_authorized": True}, {"errors": ("error",) * 17},
])
def test_metadata_counters_profiles_and_authority_cannot_be_forged(mutation):
    with pytest.raises(ValueError):
        replace(metadata(), **mutation)


def test_metadata_requires_exact_three_process_bound_base_files():
    meta = metadata()
    for manifest in (meta.base_manifest[:-1], meta.base_manifest + meta.base_manifest[:1],
                     (replace(meta.base_manifest[0], process_id=8), *meta.base_manifest[1:])):
        with pytest.raises(ValueError):
            replace(meta, base_manifest=manifest)


@pytest.mark.parametrize("record", [*records(), metadata()])
@pytest.mark.parametrize("mutation", ["extra", "missing", "boolean_integer"])
def test_wire_fields_are_exact_and_booleans_do_not_decode_as_integers(record, mutation):
    document = encode(record)
    if mutation == "extra":
        document["trusted"] = True
    elif mutation == "missing":
        document.pop("kind" if "kind" in document else "schema")
    else:
        document["index" if "index" in document else "schema_version"] = True
    with pytest.raises(ValueError):
        decode(type(record), document)
