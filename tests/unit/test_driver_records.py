"""Constructor contracts for resumable driver declarations and typed term."""
from dataclasses import FrozenInstanceError, fields, replace

import pytest

import scar.ir.program as program
from scar.ir.program.control import ProtocolValueKind
from scar.ir.program.drivers import (
    AsyncRequestCreate, BodyDrive, BodyDriveResult, BodyDriveSuccessor,
    BodyDriveTerminator, BodyResume, BodyResumeInput, BodyStart, BodyStateInput,
    CreationCapture, DriverInterface, DriverReceiverKind, DriverRule,
    DriverRuleProfile, FinalBodyGate, NormalResultPort, RawRequestDefinition,
    RawRequestKind, RequestAssociationRead, ResumableCreate,
)
from scar.ir.program.ids import BlockID, LocationID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.model import (
    AccessMode, Behavior, Block, CompletionResult, DataValue, ExitKind,
    ExitPort, Footprint, Operation, ProgramGraph, Region, StateAccess,
    StateLocation, Successor, Terminator, TerminatorKind, Use, UseRole,
)
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference


def fact():
    return ProviderFactReference(
        ProviderArtifact("unopened://driver/rule", "a" * 64, 0, "driver-rule.v1"),
        "/rules/python-resumption-v1",
    )


def rule():
    return DriverRule(DriverRuleProfile.PYTHON_RESUMPTION_V1, fact())


def test_public_exports_and_closed_rule_have_no_authority_flag():
    assert program.DriverRule is DriverRule
    assert program.BodyDriveTerminator is BodyDriveTerminator
    assert TerminatorKind.BODY_DRIVE.value == "BODY_DRIVE"
    assert ProtocolValueKind.RAW_DRIVER_REQUEST.value == "RAW_DRIVER_REQUEST"
    assert tuple(field.name for field in fields(DriverRule)) == ("profile", "implementation")
    assert not ({"verified", "runtime_verified", "transform_authorized"}
                & {field.name for field in fields(DriverRule)})
    with pytest.raises((FrozenInstanceError, AttributeError)):
        rule().profile = "PYTHON_RESUMPTION_V1"


@pytest.mark.parametrize("kind,operands", [
    (RawRequestKind.NEXT, ()),
    (RawRequestKind.CLOSE, ()),
    (RawRequestKind.SEND, (UseID("send"),)),
    (RawRequestKind.THROW, (UseID("exc"),)),
    (RawRequestKind.THROW, (UseID("exc"), UseID("tb"))),
    (RawRequestKind.THROW, (UseID("exc"), UseID("value"), UseID("tb"))),
])
def test_raw_request_accepts_only_protocol_arity(kind, operands):
    row = RawRequestDefinition(ValueID("request"), kind, operands)
    assert row.operands == operands


@pytest.mark.parametrize("kind,operands", [
    (RawRequestKind.NEXT, (UseID("x"),)),
    (RawRequestKind.CLOSE, (UseID("x"),)),
    (RawRequestKind.SEND, ()),
    (RawRequestKind.SEND, (UseID("x"), UseID("y"))),
    (RawRequestKind.THROW, ()),
    (RawRequestKind.THROW, tuple(UseID(f"u{i}") for i in range(4))),
    (RawRequestKind.SEND, (UseID("same"), UseID("same"))),
])
def test_raw_request_rejects_invalid_arity_or_duplicate_occurrence(kind, operands):
    with pytest.raises(ValueError):
        RawRequestDefinition(ValueID("request"), kind, operands)


@pytest.mark.parametrize("kind", ["SEND", True, 1, None])
def test_raw_request_rejects_untyped_kind(kind):
    with pytest.raises(TypeError):
        RawRequestDefinition(ValueID("request"), kind, ())


@pytest.mark.parametrize("index", [True, False, 1.0, "0", -1])
def test_normal_result_port_requires_nonnegative_exact_int(index):
    with pytest.raises((TypeError, ValueError)):
        NormalResultPort(index)


def test_capture_records_keep_occurrences_distinct_and_results_located():
    create = ResumableCreate(
        OperationID("create"), RegionID("body"), UseID("function"),
        (CreationCapture(ValueID("formal0"), UseID("arg0")),
         CreationCapture(ValueID("formal1"), UseID("arg1"))),
        NormalResultPort(0), rule(),
    )
    assert create.captures[0].formal != create.captures[1].formal
    assert create.captures[0].source != create.captures[1].source
    assert create.handle_result.index == 0
    with pytest.raises(ValueError, match="formals"):
        replace(create, captures=(create.captures[0],
                                  CreationCapture(ValueID("formal0"), UseID("arg1"))))
    with pytest.raises(ValueError, match="source Uses"):
        replace(create, captures=(create.captures[0],
                                  CreationCapture(ValueID("formal1"), UseID("arg0"))))


def test_async_request_ports_are_separate_and_association_results_are_distinct():
    request = AsyncRequestCreate(OperationID("request.create"), UseID("body"),
                                 UseID("latent"), NormalResultPort(0), rule())
    assert request.body != request.latent
    with pytest.raises(ValueError, match="distinct"):
        replace(request, latent=request.body)
    association = RequestAssociationRead(
        OperationID("association"), UseID("request"),
        NormalResultPort(0), NormalResultPort(1), rule(),
    )
    assert association.body_result.index != association.latent_result.index
    with pytest.raises(ValueError, match="distinct"):
        replace(association, latent_result=NormalResultPort(0))


def test_driver_interface_lifecycle_is_nonempty_unique_typed_state_locations():
    interface = DriverInterface(
        RegionID("driver"), RegionID("body"), DriverReceiverKind.ASYNC_REQUEST,
        ValueID("receiver"), ValueID("scheduler"),
        (LocationID("life"), LocationID("resource")), rule(),
    )
    assert interface.lifecycle == (LocationID("life"), LocationID("resource"))
    with pytest.raises(ValueError, match="nonempty"):
        replace(interface, lifecycle=())
    with pytest.raises(ValueError, match="unique"):
        replace(interface, lifecycle=(LocationID("life"), LocationID("life")))
    with pytest.raises(TypeError):
        replace(interface, lifecycle=("life",))


def test_body_targets_and_slot_records_reject_bool_or_wrong_ids():
    assert BodyStart(RegionID("body")).body == RegionID("body")
    assert BodyResume(OperationID("suspend"), 0).successor == 0
    assert BodyStateInput(LocationID("world"), UseID("world.use"))
    assert BodyResumeInput(1, UseID("sent"))
    with pytest.raises((TypeError, ValueError)):
        BodyResume(OperationID("suspend"), True)
    with pytest.raises(TypeError):
        BodyStateInput("world", UseID("world.use"))
    with pytest.raises((TypeError, ValueError)):
        BodyResumeInput(False, UseID("sent"))


def drive(target=None):
    return BodyDrive(
        OperationID("drive"), UseID("instance"), UseID("scheduler"), None,
        target or BodyStart(RegionID("body")),
        (BodyStateInput(LocationID("world"), UseID("world")),),
        (),
    )


def test_body_drive_exposes_canonical_role_uses_and_preserves_empty_frontier():
    row = BodyDrive(
        OperationID("drive"), UseID("instance"), UseID("scheduler"), UseID("session"),
        BodyResume(OperationID("suspend"), 1),
        (BodyStateInput(LocationID("world"), UseID("world")),),
        (BodyResumeInput(0, UseID("sent")),),
    )
    assert row.actual_uses == (
        UseID("instance"), UseID("scheduler"), UseID("session"),
        UseID("world"), UseID("sent"),
    )
    assert BodyDriveTerminator(()).successors == ()  # empty finite frontier is valid
    with pytest.raises(ValueError, match="unique"):
        replace(row, resume_inputs=(BodyResumeInput(0, UseID("world")),))
    with pytest.raises(TypeError, match="exact BodyStart or BodyResume"):
        replace(row, target=object())


def test_body_drive_successor_distinguishes_edge_uses_from_results():
    row = BodyDriveSuccessor(
        OperationID("source"), BlockID("landing"),
        (UseID("forward"), BodyDriveResult(0)),
    )
    term = BodyDriveTerminator((row,))
    assert term.kind is TerminatorKind.BODY_DRIVE
    assert term.values == () and term.condition is None and term.exit is None
    with pytest.raises((TypeError, ValueError)):
        BodyDriveSuccessor(OperationID("source"), BlockID("landing"), (True,))
    with pytest.raises(ValueError, match="sources"):
        BodyDriveTerminator((row, replace(row, block=BlockID("other"))))
    with pytest.raises(ValueError, match="blocks"):
        BodyDriveTerminator((row, replace(row, source=OperationID("other"))))


@pytest.mark.parametrize("fields", [
    {"body_argument": True},
    {"scheduler_argument": -1},
    {"session_argument": 1.0},
    {"delivery_arguments": (2, 2)},
    {"delivery_arguments": (False,)},
    {"body_argument": 0, "scheduler_argument": 1, "session_argument": 2,
     "delivery_arguments": (2,)},
])
def test_final_gate_checks_exact_distinct_argument_roles(fields):
    base = FinalBodyGate(OperationID("gate"), OperationID("drive"), 0, 1, None, ())
    with pytest.raises((TypeError, ValueError)):
        replace(base, **fields)


def test_program_graph_has_seven_exact_driver_tables_and_unique_keys():
    region = Region(RegionID("root"), "root", BlockID("entry"),
                    (Block(BlockID("entry"), (), ()),), ())
    request = RawRequestDefinition(ValueID("request"), RawRequestKind.NEXT, ())
    graph = ProgramGraph(region.id, (region,), (), (), raw_driver_requests=(request,))
    assert graph.raw_driver_requests == (request,)
    with pytest.raises(ValueError, match="raw_driver_requests keys"):
        replace(graph, raw_driver_requests=(request, request))
    with pytest.raises(TypeError, match="exact driver records"):
        replace(graph, body_drives=(object(),))


def test_driver_operation_role_cannot_be_reused_by_two_driver_tables():
    region = Region(RegionID("root"), "root", BlockID("entry"),
                    (Block(BlockID("entry"), (), ()),), ())
    create = ResumableCreate(OperationID("same"), RegionID("body"), UseID("fn"),
                             (), NormalResultPort(0), rule())
    association = RequestAssociationRead(OperationID("same"), UseID("req"),
                                         NormalResultPort(0), NormalResultPort(1), rule())
    with pytest.raises(ValueError, match="driver operation IDs"):
        ProgramGraph(region.id, (region,), (), (), resumable_creates=(create,),
                     request_association_reads=(association,))


def test_operation_accepts_typed_body_drive_and_rejects_regular_operation_fields():
    actual = (Use(UseID("instance"), ValueID("v.instance"), UseRole.REFERENCE),
              Use(UseID("scheduler"), ValueID("v.scheduler"), UseRole.PROTOCOL))
    term = BodyDriveTerminator(())
    op = Operation(OperationID("drive"), "body drive", (Behavior.CONTROL,),
                   uses=actual, terminator=term)
    assert op.terminator.kind is TerminatorKind.BODY_DRIVE

    for kwargs in (
        {"results": (ValueID("result"),)},
        {"callee": RegionID("callee")},
        {"call_arguments": (UseID("instance"),)},
        {"invoke_arguments": (UseID("instance"),)},
    ):
        with pytest.raises(ValueError):
            replace(op, **kwargs)

    state_use = Use(UseID("state"), ValueID("state.value"), UseRole.STATE_CONTENT)
    state_access = StateAccess(LocationID("world"), state_use.id, AccessMode.READ)
    with pytest.raises(ValueError, match="BODY_DRIVE cannot carry"):
        replace(op, uses=(*actual, state_use), accesses=(state_access,))

    with pytest.raises(ValueError):
        replace(op, terminator=Terminator(TerminatorKind.BODY_DRIVE))
