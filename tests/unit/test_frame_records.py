"""Frame rules cannot turn a serialized condition into runtime authority."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, fields, replace

import pytest

from scar.ir.program.frames import (
    FrameBind, FrameCompletionRule, FrameCondition, FrameDiscard, FrameEnter,
    FrameExit, FrameFinalizerErrors, FrameFormal, FrameModel, FrameRelease,
    FrameRules, FrameTermination, FrameTransitionKind,
)
from scar.ir.program.ids import OperationID, RegionID, UseID, ValueID
from scar.ir.record_codec import decode, encode
from scar.ir.v2.common import Completeness, ProofStatus, SourceReference
from scar.ir.v2.ids import OperationDefinitionID, SourceAtomID, ValueSlotID


def model():
    source = SourceReference(SourceAtomID("function"), "/fixture.py", "sha256:" + "a" * 64,
                             1, 5, 0, 12)
    return FrameModel(OperationDefinitionID("function"), RegionID("body"), source, (
        FrameEnter(OperationID("enter"), source,
                   (FrameFormal(ValueSlotID("x"), UseID("enter.x")),)),
        FrameBind(OperationID("bind"), source, ValueSlotID("y"), UseID("bind.value")),
        FrameDiscard(OperationID("discard"), source, UseID("discard.value")),
        FrameExit(OperationID("exit"), source, OperationID("return"), UseID("exit.payload")),
    ))


def test_fixed_rules_distinguish_unknown_applicability_from_conditional_semantics():
    rules = FrameRules()
    assert rules.condition is FrameCondition.NO_FRAME_INTERPOSITION
    assert rules.condition_status is ProofStatus.UNKNOWN
    assert rules.completion is FrameCompletionRule.PRESERVE_PENDING_IF_COMPLETED
    assert rules.effects is Completeness.UNKNOWN
    assert rules.termination is FrameTermination.MAY_NOT_COMPLETE
    assert rules.finalizer_errors is FrameFinalizerErrors.UNRAISABLE
    assert rules.release is FrameRelease.NOT_GUARANTEED
    assert not any(type(getattr(rules, field.name)) is bool for field in fields(rules))
    with pytest.raises(FrozenInstanceError):
        rules.condition_status = ProofStatus.PROVEN


@pytest.mark.parametrize("field,value", [
    ("condition_status", ProofStatus.PROVEN), ("condition_status", ProofStatus.DISPROVEN),
    ("effects", Completeness.COMPLETE), ("effects", Completeness.PARTIAL),
    ("completion", "PRESERVE_PENDING_IF_COMPLETED"), ("termination", False),
    ("release", True), ("finalizer_errors", "RAISE"),
    ("condition", "NO_FRAME_INTERPOSITION"), ("version", "PYTHON_FRAME_V2"),
])
def test_direct_construction_cannot_raise_authority(field, value):
    with pytest.raises(ValueError):
        replace(FrameRules(), **{field: value})


@pytest.mark.parametrize("field,value", [
    ("condition_status", "PROVEN"), ("effects", "COMPLETE"),
    ("termination", "ALWAYS_COMPLETES"), ("release", "GUARANTEED"),
    ("finalizer_errors", "REPLACEMENT_RAISE"), ("condition", "PROVEN"),
    ("completion", True), ("version", "PYTHON_FRAME_V2"),
])
def test_wire_rules_cannot_raise_authority(field, value):
    wire = model().to_dict()
    wire["rules"][field] = value
    with pytest.raises(ValueError):
        FrameModel.from_dict(wire)


def test_transition_union_round_trip_uses_existing_ids_without_duplicate_dependency_fields():
    original = model()
    restored = FrameModel.from_dict(original.to_dict())
    assert restored == original
    assert [type(item) for item in restored.transitions] == [FrameEnter, FrameBind, FrameDiscard, FrameExit]
    assert [item.kind for item in restored.transitions] == list(FrameTransitionKind)
    assert decode(FrameModel, encode(original)) == original
    forbidden = {"before", "after", "world", "pending_kind", "payload_value", "effects_complete"}
    assert not any(forbidden & set(item) for item in original.to_dict()["transitions"])
    assert "kind" not in original.to_dict()["transitions"][0]


@pytest.mark.parametrize("mutation", ["extra", "missing", "mixed_variant", "wrong_id", "source_bool", "extra_rule"])
def test_strict_wire_records_reject_partial_and_ambiguous_variants(mutation):
    wire = model().to_dict()
    if mutation == "extra":
        wire["transitions"][0]["before"] = "made-up-state"
    elif mutation == "missing":
        del wire["transitions"][3]["payload"]
    elif mutation == "mixed_variant":
        wire["transitions"][2]["slot"] = wire["transitions"][1]["slot"]
    elif mutation == "wrong_id":
        wire["transitions"][3]["payload"] = encode(ValueID("exit.payload"))
    elif mutation == "source_bool":
        wire["source"]["start_line"] = True
    else:
        wire["rules"]["transformation_authorized"] = True
    with pytest.raises(ValueError):
        FrameModel.from_dict(wire)


def test_slots_and_owned_use_sites_cannot_be_deduplicated_or_reused():
    frame = model()
    enter = frame.transitions[0]
    formal = enter.formals[0]
    with pytest.raises(ValueError, match="distinct"):
        replace(enter, formals=(formal, replace(formal, use=UseID("another"))))
    with pytest.raises(ValueError, match="distinct"):
        replace(enter, formals=(formal, replace(formal, slot=ValueSlotID("another"))))
    with pytest.raises(TypeError):
        replace(enter, formals=list(enter.formals))
    with pytest.raises(TypeError):
        FrameFormal(ValueSlotID("x"), ValueID("not-a-use"))


@pytest.mark.parametrize("mutation", ["no_enter", "two_enters", "repeated_op", "repeated_exit", "self_exit"])
def test_local_model_cardinality_is_strict(mutation):
    frame = model()
    with pytest.raises(ValueError):
        if mutation == "no_enter":
            replace(frame, transitions=frame.transitions[1:])
        elif mutation == "two_enters":
            replace(frame, transitions=frame.transitions + (replace(frame.transitions[0], operation=OperationID("enter2")),))
        elif mutation == "repeated_op":
            replace(frame, transitions=frame.transitions + (frame.transitions[1],))
        elif mutation == "repeated_exit":
            replace(frame, transitions=frame.transitions + (replace(frame.transitions[-1], operation=OperationID("exit2")),))
        else:
            replace(frame.transitions[-1], completion=frame.transitions[-1].operation)


def test_encode_and_decode_recheck_even_frozen_records_modified_outside_constructors():
    frame = deepcopy(model())
    object.__setattr__(frame.rules, "effects", Completeness.COMPLETE)
    with pytest.raises(ValueError):
        frame.to_dict()
    with pytest.raises(ValueError):
        FrameModel.from_dict(encode(frame))
