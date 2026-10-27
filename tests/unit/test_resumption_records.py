"""Constructor and slot-resolution contracts, without driver/runtime claims."""
from dataclasses import FrozenInstanceError, fields, replace
from types import SimpleNamespace

import pytest

from scar.ir.program.ids import BlockID, LocationID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.resumption import (
    FrameContextAttach, FrameContextDetach, FrameContextInitial, ResumableBody,
    ResumableKind, ResumeInput, ResumeSlot, ResumeSlotKind, ResumeSuccessor,
    SavedInput, SavedRole, SavedSlot, SuspendTerminator, SuspensionFlavor,
    resume_slot_type, saved_actual_use,
)


def edge(name="resume", payload=ResumeSlotKind.SENT_VALUE):
    return ResumeSuccessor(
        (ResumeSlot(ResumeSlotKind.STATE, LocationID("world")), ResumeSlot(payload)),
        BlockID(name), (SavedInput(0), ResumeInput(1), ResumeInput(0)))


def suspension():
    return SuspendTerminator(
        SuspensionFlavor.YIELD, UseID("export"),
        (SavedSlot(SavedRole.FRAME_CONTEXT, UseID("frame")),
         SavedSlot(SavedRole.VALUE, UseID("live"))),
        (UseID("world"),),
        (edge(), edge("throw", ResumeSlotKind.THROWN_PACKET)))


def records():
    return (
        ResumableBody(RegionID("body"), ResumableKind.GENERATOR, LocationID("world")),
        FrameContextInitial(OperationID("initial"), ValueID("initial.frame")),
        FrameContextAttach(OperationID("attach"), UseID("frame"), ValueID("caller")),
        FrameContextDetach(OperationID("detach"), UseID("caller"), ValueID("frame")),
        SavedSlot(SavedRole.VALUE, UseID("live")), SavedInput(0), ResumeInput(0),
        ResumeSlot(ResumeSlotKind.STATE, LocationID("world")), edge(), suspension(),
    )


@pytest.mark.parametrize("record", records())
def test_records_are_frozen_slotted_and_have_no_authority_fields(record):
    assert not hasattr(record, "__dict__")
    assert not {"source", "verified", "authorized", "runtime", "instance", "generation"} & {
        field.name for field in fields(record)}
    name = fields(record)[0].name
    with pytest.raises(FrozenInstanceError):
        setattr(record, name, getattr(record, name))


@pytest.mark.parametrize("kind", tuple(ResumableKind))
def test_body_family_is_an_exact_declaration_without_source_or_driver_evidence(kind):
    body = replace(records()[0], kind=kind)
    assert body.kind is kind
    assert set(field.name for field in fields(body)) == {"region", "kind", "context_location"}


@pytest.mark.parametrize("record_index,field,value", [
    (0, "region", BlockID("body")), (0, "region", "body"),
    (0, "kind", "GENERATOR"), (0, "kind", SuspensionFlavor.YIELD),
    (0, "context_location", ValueID("world")),
    (1, "operation", RegionID("initial")), (1, "frame", UseID("frame")),
    (2, "operation", True), (2, "frame", ValueID("frame")),
    (2, "caller", UseID("caller")),
    (3, "operation", "detach"), (3, "caller", ValueID("caller")),
    (3, "frame", UseID("frame")),
    (4, "role", "VALUE"), (4, "role", ResumeSlotKind.SENT_VALUE),
    (4, "use", ValueID("live")),
    (7, "kind", "STATE"), (7, "location", "world"),
    (8, "block", RegionID("resume")),
    (9, "flavor", "YIELD"), (9, "flavor", ResumableKind.GENERATOR),
    (9, "exported", ValueID("export")),
])
def test_new_fields_reject_wrong_enum_id_namespace_and_untyped_values(record_index, field, value):
    with pytest.raises(TypeError):
        replace(records()[record_index], **{field: value})


@pytest.mark.parametrize("constructor", (SavedInput, ResumeInput))
@pytest.mark.parametrize("index", (True, False, 0.0, "0", None))
def test_slot_indices_require_exact_integers(constructor, index):
    with pytest.raises(TypeError):
        constructor(index)


@pytest.mark.parametrize("constructor", (SavedInput, ResumeInput))
def test_slot_indices_reject_negative_and_have_distinct_wire_fields(constructor):
    with pytest.raises(ValueError, match="nonnegative"):
        constructor(-1)
    assert {field.name for field in fields(SavedInput(0))} == {"saved_slot"}
    assert {field.name for field in fields(ResumeInput(0))} == {"resume_slot"}


@pytest.mark.parametrize("kind", tuple(ResumeSlotKind))
def test_resume_slot_location_shape_and_existing_core_type(kind):
    from scar.ir.program.control import ProtocolValueKind, ProtocolValueType
    from scar.ir.program.model import ValueKind, ValueType

    location = LocationID("world") if kind is ResumeSlotKind.STATE else None
    slot = ResumeSlot(kind, location)
    result = resume_slot_type(slot)
    if kind is ResumeSlotKind.STATE:
        assert result == ValueType(ValueKind.STATE, location=location)
        with pytest.raises(ValueError, match="needs a location"):
            ResumeSlot(kind)
    else:
        with pytest.raises(ValueError, match="only STATE"):
            ResumeSlot(kind, LocationID("world"))
        expected = (ValueType(ValueKind.REFERENCE)
                    if kind in (ResumeSlotKind.SENT_VALUE, ResumeSlotKind.DELEGATE_VALUE)
                    else ProtocolValueType(ProtocolValueKind.EXCEPTION_PACKET))
        assert result == expected


@pytest.mark.parametrize("invalid", [[], (True,), (SavedSlot(SavedRole.VALUE, UseID("x")),)])
def test_resume_inputs_are_exact_slot_tuples(invalid):
    with pytest.raises(TypeError):
        replace(edge(), inputs=invalid)


@pytest.mark.parametrize("arguments", [
    [], (UseID("ordinary"),), (0,), (True,), (None,),
])
def test_temporal_actuals_cannot_be_ordinary_uses_or_untyped_indices(arguments):
    with pytest.raises(TypeError):
        replace(edge(), arguments=arguments)


@pytest.mark.parametrize("arguments", [
    (SavedInput(0), ResumeInput(0)),
    (SavedInput(0), ResumeInput(0), ResumeInput(0), ResumeInput(1)),
    (SavedInput(0), ResumeInput(0), ResumeInput(2)),
])
def test_every_current_resume_input_is_bound_once_and_no_index_is_invented(arguments):
    with pytest.raises(ValueError, match="every resume input slot"):
        replace(edge(), arguments=arguments)


def test_each_case_needs_one_payload_and_distinct_state_locations():
    state = ResumeSlot(ResumeSlotKind.STATE, LocationID("world"))
    sent = ResumeSlot(ResumeSlotKind.SENT_VALUE)
    with pytest.raises(ValueError, match="exactly one delivered payload"):
        ResumeSuccessor((state,), BlockID("resume"), (ResumeInput(0),))
    with pytest.raises(ValueError, match="exactly one delivered payload"):
        ResumeSuccessor((state, sent, ResumeSlot(ResumeSlotKind.THROWN_PACKET)),
                        BlockID("resume"), tuple(ResumeInput(i) for i in range(3)))
    with pytest.raises(ValueError, match="state locations must be distinct"):
        ResumeSuccessor((state, state, sent), BlockID("resume"),
                        tuple(ResumeInput(i) for i in range(3)))


def test_saved_slots_may_be_unused_or_reused_and_parameter_order_is_explicit():
    item = suspension()
    # A value saved once may feed two parameters; another saved value need not
    # be consumed by this case. These are not duplicate canonical operation Uses.
    repeated = replace(edge(), arguments=(ResumeInput(1), SavedInput(0),
                                         SavedInput(0), ResumeInput(0)))
    item = replace(item, successors=(repeated,))
    assert item.successors[0].arguments[1:3] == (SavedInput(0), SavedInput(0))
    assert item.saved[1].use == UseID("live")


@pytest.mark.parametrize("flavor", tuple(SuspensionFlavor))
def test_suspend_properties_are_views_and_not_an_exit_or_second_actual_store(flavor):
    from scar.ir.program.model import TerminatorKind

    item = replace(suspension(), flavor=flavor)
    assert item.kind is TerminatorKind.SUSPEND
    assert item.exit is item.condition is None
    assert item.values == (UseID("export"), UseID("frame"), UseID("live"), UseID("world"))
    assert {field.name for field in fields(item)} == {
        "flavor", "exported", "saved", "handoff", "successors"}


@pytest.mark.parametrize("field,value", [
    ("saved", []), ("saved", (UseID("frame"),)),
    ("handoff", []), ("handoff", (ValueID("world"),)),
    ("successors", []), ("successors", (True,)),
])
def test_suspend_nested_containers_are_exact_tuples_and_records(field, value):
    with pytest.raises(TypeError):
        replace(suspension(), **{field: value})


def test_suspend_needs_one_frame_context_and_unique_operand_use_sites():
    item = suspension()
    with pytest.raises(ValueError, match="exactly one FRAME_CONTEXT"):
        replace(item, saved=(item.saved[1],))
    with pytest.raises(ValueError, match="exactly one FRAME_CONTEXT"):
        replace(item, saved=(*item.saved, SavedSlot(SavedRole.FRAME_CONTEXT, UseID("other"))))
    for updated in (
            {"exported": item.saved[0].use},
            {"handoff": (item.exported,)},
            {"handoff": (item.handoff[0], item.handoff[0])},
            {"saved": (item.saved[0], replace(item.saved[1], use=item.saved[0].use))}):
        with pytest.raises(ValueError, match="owned operand UseIDs must be distinct"):
            replace(item, **updated)


def test_suspend_rejects_missing_shared_landings_and_out_of_range_saved_indices():
    item = suspension()
    with pytest.raises(ValueError, match="nonempty"):
        replace(item, successors=())
    with pytest.raises(ValueError, match="targets must be distinct"):
        replace(item, successors=(edge(), edge(payload=ResumeSlotKind.THROWN_PACKET)))
    bad = replace(edge(), arguments=(SavedInput(len(item.saved)), ResumeInput(0), ResumeInput(1)))
    with pytest.raises(ValueError, match="saved input index exceeds"):
        replace(item, successors=(bad,))


@pytest.mark.parametrize("record_index,field,value", [
    (4, "role", "FRAME_CONTEXT"), (5, "saved_slot", True),
    (6, "resume_slot", -1), (7, "location", None),
    (8, "arguments", (SavedInput(0), ResumeInput(0))),
])
def test_parents_recheck_nested_records_even_if_mutated_after_construction(record_index, field, value):
    bad = records()[record_index]
    object.__setattr__(bad, field, value)
    with pytest.raises((TypeError, ValueError)):
        if type(bad) is SavedSlot:
            replace(suspension(), saved=(bad,))
        elif type(bad) in (SavedInput, ResumeInput):
            replace(edge(), arguments=(bad, ResumeInput(0), ResumeInput(1)))
        elif type(bad) is ResumeSlot:
            replace(edge(), inputs=(bad, ResumeSlot(ResumeSlotKind.SENT_VALUE)))
        else:
            replace(suspension(), successors=(bad,))


def test_new_record_subclasses_cannot_enter_nested_wire_variants():
    for constructor, value in ((SavedInput, 0), (ResumeInput, 0)):
        subclass = type("Derived", (constructor,), {})
        with pytest.raises(TypeError):
            replace(edge(), arguments=(subclass(value), ResumeInput(0), ResumeInput(1)))
    slot = SavedSlot(SavedRole.VALUE, UseID("live"))
    derived_slot = type("DerivedSavedSlot", (SavedSlot,), {})(slot.role, slot.use)
    with pytest.raises(TypeError):
        replace(suspension(), saved=(suspension().saved[0], derived_slot))
    original = edge()
    derived_edge = type("DerivedResumeSuccessor", (ResumeSuccessor,), {})(
        original.inputs, original.block, original.arguments)
    with pytest.raises(TypeError):
        replace(suspension(), successors=(derived_edge,))


def test_actual_resolver_uses_the_owned_saved_port_without_normalizing_identifiers():
    operation = SimpleNamespace(terminator=suspension())
    assert saved_actual_use(operation, SavedInput(0)) is operation.terminator.saved[0].use
    assert saved_actual_use(operation, SavedInput(1)) is operation.terminator.saved[1].use
    subclass = type("HistoricUseID", (UseID,), {})
    for use in (UseID("ordinary"), subclass("ordinary")):
        assert saved_actual_use(operation, use) is use
        assert saved_actual_use(None, use) is use


def test_actual_resolver_does_not_invent_copy_sources_for_external_or_other_values():
    from scar.ir.program.control import PendingPayload
    from scar.ir.program.model import CompletionResult

    operation = SimpleNamespace(terminator=suspension())
    for argument in (ResumeInput(0), CompletionResult(0), PendingPayload(),
                     ValueID("frame"), 0, False, None, SimpleNamespace(value=UseID("frame"))):
        assert saved_actual_use(operation, argument) is None
    assert saved_actual_use(None, SavedInput(0)) is None
    bad = SavedInput(0)
    for index in (-1, True, 100):
        object.__setattr__(bad, "saved_slot", index)
        assert saved_actual_use(operation, bad) is None


def test_resume_slot_type_rechecks_exact_records_before_mapping():
    with pytest.raises(TypeError):
        resume_slot_type("SENT_VALUE")
    bad = ResumeSlot(ResumeSlotKind.SENT_VALUE)
    object.__setattr__(bad, "kind", "SENT_VALUE")
    with pytest.raises(TypeError):
        resume_slot_type(bad)
