"""Actual outer-body callback/reentry/handler/YIELD supplied-model connections."""
from dataclasses import replace

import pytest

from scar.ir.program.drivers import RawRequestKind
from scar.ir.program.ids import OperationID, ValueID
from scar.ir.program.model import OperationResult, StateVersionValue, TerminatorKind
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.resumption import SuspendTerminator
from scar.ir.program.state_addresses import ExistingAccess
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_generator_reentry_graphs import generator_reentry_program


def _op(graph, identity):
    return next(op for op in graph.operations if op.id == identity)


@pytest.mark.parametrize("kind", tuple(RawRequestKind))
def test_outer_body_really_calls_running_driver_catches_current_packet_and_yields_new_value(kind):
    graph, details = generator_reentry_program(kind=kind)
    require_valid(graph)
    index = ProgramIndex(graph)
    body, = graph.resumable_bodies
    assert body.region == index.values[details["holder"]].region
    call = _op(graph, details["inner_call"])
    assert call.callee == details["driver"] and call.callee != body.region
    assert call.id in {op for region in graph.regions if region.id == body.region
                       for block in region.blocks for op in block.operations}
    assert len(graph.resumable_bodies) == 1
    # All inner/outer drivers refer to this same canonical body definition.
    assert {interface.body for interface in graph.driver_interfaces} == {body.region}
    owner = next(use for use in call.uses if use.id == call.invoke_arguments[0])
    assert owner.value == details["loaded_owner"]
    assert index.values[owner.value].origin == OperationResult(details["read"], 0)
    raw = next(row for row in graph.raw_driver_requests if row.value == details["inner_raw"])
    assert raw.kind is kind
    assert next(use.value for use in call.uses if use.id == call.invoke_arguments[1]) == raw.value
    raised = next(edge for edge in call.terminator.successors if edge.kind.value == "RAISE")
    landing = next(block for region in graph.regions for block in region.blocks if block.id == raised.block)
    handler = next(_op(graph, identity) for identity in landing.operations if identity in details["handlers"])
    assert handler.id in details["handlers"]
    assert handler.uses[0].value == landing.arguments[0]
    assert handler.results[0] in details["continuations"]
    assert landing.operations[-1] == OperationID(landing.id.value + ".continue")
    branch = _op(graph, landing.operations[-1])
    assert branch.terminator.successors[0].block.value == "reentry.body.yield"
    yielded = _op(graph, OperationID("resume.suspend"))
    assert type(yielded.terminator) is SuspendTerminator
    exported = next(use for use in yielded.uses if use.id == yielded.terminator.exported)
    assert exported.value == details["join"][4]
    edge_uses = {use.id: use for use in branch.uses}
    assert edge_uses[branch.terminator.successors[0].arguments[4]].value == handler.results[0]
    install = _op(graph, landing.operations[0])
    assert install.id in details["context_installs"]
    assert any(use.value == landing.arguments[0] for use in install.uses)
    assert next(use.value for use in install.uses if use.id == install.accesses[0].before) == landing.arguments[2]
    assert edge_uses[branch.terminator.successors[0].arguments[2]].value == install.accesses[0].after
    join = next(block for region in graph.regions for block in region.blocks if block.id.value == "reentry.body.yield")
    assert join.operations == (OperationID("resume.detach"), yielded.id)
    # The frame token travels only in the CFG edge, never an opaque callee arg.
    assert details["join"][0] not in {use.value for use in call.uses if use.id in call.invoke_arguments}
    report = index.protocol_obligations(budget=131072)
    assert report["source_runtime_verified"] is False and report["transformation_authorized"] is False


def test_successful_create_handle_is_the_actual_holder_write_with_current_state_and_captured_holder():
    graph, details = generator_reentry_program()
    require_valid(graph)
    index = ProgramIndex(graph)
    create, = graph.resumable_creates
    source = _op(graph, create.operation)
    capture_use = next(use for use in source.uses if use.id == details["capture"].source)
    assert capture_use.value == details["holder_actual"]
    store, read = _op(graph, details["store"]), _op(graph, details["read"])
    assert {use.value for use in store.uses} >= {details["stored_handle"], details["holder_actual"]}
    assert store.accesses[0].after == details["stored_state"]
    assert next(use.value for use in _op(graph, details["call"]).uses
                if isinstance(index.values[use.value], StateVersionValue)
                and index.values[use.value].location == store.accesses[0].location) == details["stored_state"]
    for operation in (store, read):
        view = index.state_address(ExistingAccess(operation.id, 0))
        assert view["before"].use.value == next(use.value for use in operation.uses
                                               if use.id == operation.accesses[0].before)
        assert view["effects"][0]["effect"].path[0].name == "body"
        assert view["coarse_dependencies_retained"] is True
        assert view["source_runtime_verified"] is False
        assert view["address_interpretation_verified"] is False
    # Dependency declaration deliberately does not attach permanent object or
    # DataIdentity to the heap-load result to manufacture a read-from theorem.
    assert index.values[details["loaded_owner"]].referent_identity is None
    assert index.values[details["stored_handle"]].referent_identity is None


def test_inner_callback_cannot_receive_the_pre_attach_context_state():
    graph, details = generator_reentry_program(kind=RawRequestKind.THROW)
    require_valid(graph)
    call = _op(graph, details["inner_call"])
    index = ProgramIndex(graph)
    stale = ValueID("resume.context.0")
    location = index.values[stale].location
    graph = replace(graph, operations=tuple(replace(op, uses=tuple(replace(use, value=stale)
        if use.id in call.invoke_arguments and isinstance(index.values[use.value], StateVersionValue)
        and index.values[use.value].location == location else use for use in op.uses))
        if op.id == call.id else op for op in graph.operations))
    assert "stale_state" in {issue.code for issue in validate(graph)}


def test_outer_raise_handler_cannot_forward_pre_callback_world_state_to_its_real_yield():
    graph, details = generator_reentry_program()
    require_valid(graph)
    call = _op(graph, details["inner_call"])
    raised = next(edge for edge in call.terminator.successors if edge.kind.value == "RAISE")
    landing = next(block for region in graph.regions for block in region.blocks if block.id == raised.block)
    jump = _op(graph, landing.operations[-1])
    target = jump.terminator.successors[0].arguments[1]
    graph = replace(graph, operations=tuple(replace(op, uses=tuple(replace(use, value=ValueID("resume.world.0"))
        if use.id == target else use for use in op.uses)) if op.id == jump.id else op for op in graph.operations))
    assert "stale_state" in {issue.code for issue in validate(graph)}


def test_private_caller_token_is_not_an_argument_of_the_reentry_driver():
    graph, details = generator_reentry_program()
    require_valid(graph)
    call = _op(graph, details["inner_call"])
    forward = next(use for use in call.uses if use.value == ValueID("resume.attach.caller"))
    graph = replace(graph, operations=tuple(replace(op, invoke_arguments=(*op.invoke_arguments, forward.id))
        if op.id == call.id else op for op in graph.operations))
    # One original Use cannot be both a private CFG forward and a call actual.
    assert "control_binding" in {issue.code for issue in validate(graph)}
