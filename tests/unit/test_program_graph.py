"""Whole-program structure and dependency checks on manually constructed IR."""
from dataclasses import replace

import pytest

from scar.ir.program.codec import dumps
from scar.ir.program.ids import LocationID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.model import (
    BlockArgument, ExitKind, Footprint, FootprintKind, OperationResult,
    OrderEdge, ReferenceValue, StateVersionValue, UseRole, ValueKind, ValueType,
)
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_graphs import (
    branch_state_program, loop_state_program, save_payload_program,
    shared_body_calls_program,
)


FIXTURES = (branch_state_program, loop_state_program, shared_body_calls_program, save_payload_program)


def get_operation(graph, name):
    return next(item for item in graph.operations if item.id == OperationID(name))


def replace_operation(graph, name, **changes):
    return replace(graph, operations=tuple(
        replace(item, **changes) if item.id == OperationID(name) else item
        for item in graph.operations))


def replace_use(graph, operation, use, value):
    current = get_operation(graph, operation)
    return replace_operation(graph, operation, uses=tuple(
        replace(item, value=ValueID(value)) if item.id == UseID(use) else item
        for item in current.uses))


def assert_rejected(graph):
    issues = validate(graph)
    assert isinstance(issues, tuple) and issues
    assert all(isinstance(item.code, str) and item.code for item in issues)
    assert all(isinstance(item.path, str) and item.path for item in issues)
    assert all(isinstance(item.message, str) and item.message for item in issues)
    with pytest.raises(ValueError):
        require_valid(graph)
    with pytest.raises(ValueError):
        dumps(graph)


@pytest.mark.parametrize("build", FIXTURES, ids=lambda function: function.__name__)
def test_complete_manual_programs_validate(build):
    graph = build()
    assert validate(graph) == ()
    assert require_valid(graph) is None


def test_branch_program_preserves_state_on_normal_and_exception_exits():
    graph = branch_state_program()
    index = ProgramIndex(graph)
    assert index.producer(ValueID("buffer.updated")) == OperationResult(OperationID("write"), 0)
    assert isinstance(index.producer(ValueID("buffer.failure")), BlockArgument)
    uses = index.consumers(ValueID("buffer.updated"))
    assert {(site.operation, site.use.id) for site in uses} == {(OperationID("done"), UseID("done.buffer"))}
    assert {port.kind for port in graph.regions[0].exits} == {ExitKind.NORMAL, ExitKind.RAISE}


def test_query_keeps_same_value_repeated_operands_and_call_sites_separate():
    graph = shared_body_calls_program()
    index = ProgramIndex(graph)
    body_uses = index.consumers(ValueID("body.input"))
    assert {(site.operation, site.use.id) for site in body_uses} == {
        (OperationID("twice"), UseID("twice.left")),
        (OperationID("twice"), UseID("twice.right")),
    }
    actual_uses = index.consumers(ValueID("caller.input"))
    assert {site.operation for site in actual_uses} == {OperationID("call1"), OperationID("call2")}
    assert index.producer(ValueID("call1.result")) != index.producer(ValueID("call2.result"))
    assert tuple(item.id for item in index.entry_arguments(RegionID("callee"))) == (
        ValueID("body.input"), ValueID("body.initial"))


def test_video_and_tensor_saves_use_identical_structural_rules():
    video, tensor = save_payload_program("save video"), save_payload_program("save tensor")
    require_valid(video)
    require_valid(tensor)
    assert replace(tensor, regions=video.regions, operations=video.operations) == video
    assert all(replace(left, label=right.label) == right
               for left, right in zip(video.operations, tensor.operations))
    assert ProgramIndex(video).producer(ValueID("encoded")) == ProgramIndex(tensor).producer(ValueID("encoded"))
    assert get_operation(video, "file.write").uses[1].role is UseRole.STATE_ORDER
    assert get_operation(video, "file.write").accesses[0].full_overwrite


def test_unknown_effects_remain_valid_input_without_optimization_authority():
    graph = replace_operation(save_payload_program(), "encode", effects_complete=False)
    assert validate(graph) == ()
    assert not get_operation(graph, "encode").effects_complete


@pytest.mark.parametrize("operation,use,value", (
    ("done", "done.buffer", "buffer.normal"),
    ("done", "done.log", "log.normal"),
    ("emit", "emit.state", "log.initial"),
))
def test_old_state_cannot_be_used_after_block_binding_or_write(operation, use, value):
    assert_rejected(replace_use(branch_state_program(), operation, use, value))


def test_loop_backedge_cannot_discard_updated_state():
    assert_rejected(replace_use(loop_state_program(), "backedge", "backedge.state", "body.state"))


def test_second_call_cannot_reuse_the_pre_first_call_state():
    assert_rejected(replace_use(shared_body_calls_program(), "call2", "call2.state", "caller.initial"))


def test_branch_local_value_is_unavailable_on_exception_path_even_if_types_match():
    graph = replace_use(branch_state_program(), "fail", "fail.error", "sum.value")
    root = graph.regions[0]
    graph = replace(graph, regions=(replace(root, exits=tuple(
        replace(port, types=(ValueType(ValueKind.DATA, "builtins.int"), *port.types[1:]))
        if port.name == "failure" else port for port in root.exits)),))
    assert_rejected(graph)


def test_value_definition_must_precede_same_block_use():
    assert_rejected(replace_use(branch_state_program(), "sum", "sum.left", "sum.value"))


def test_cross_region_value_cannot_bypass_formal_arguments():
    assert_rejected(replace_use(shared_body_calls_program(), "call1", "call1.input", "body.input"))


def test_explicit_reference_to_wrong_location_rejected():
    graph = branch_state_program()
    graph = replace(graph, values=tuple(
        replace(value, targets=(LocationID("log"),)) if value.id == ValueID("reference") else value
        for value in graph.values))
    assert_rejected(graph)


def test_disjoint_reference_selector_does_not_authorize_access():
    graph = branch_state_program()
    graph = replace(graph, values=tuple(
        replace(value, selector=Footprint(FootprintKind.INTERVAL, 2, 3))
        if value.id == ValueID("reference") else value for value in graph.values))
    assert_rejected(graph)


def test_unknown_reference_target_is_retained_as_unknown_not_claimed_disjoint():
    graph = branch_state_program()
    graph = replace(graph, values=tuple(
        replace(value, targets=None) if value.id == ValueID("reference") else value
        for value in graph.values))
    assert_rejected(graph)
    graph = replace_operation(graph, "read", effects_complete=False)
    graph = replace_operation(graph, "write", effects_complete=False)
    assert validate(graph) == ()
    assert next(value for value in graph.values if value.id == ValueID("reference")).targets is None


def test_access_after_value_must_version_the_same_location():
    graph = branch_state_program()
    graph = replace(graph, values=tuple(
        replace(value, location=LocationID("log")) if value.id == ValueID("buffer.updated") else value
        for value in graph.values))
    assert_rejected(graph)


def test_compute_cannot_read_state_without_declaring_access():
    graph = branch_state_program()
    add = get_operation(graph, "sum")
    graph = replace_operation(graph, "sum", uses=(
        replace(add.uses[0], value=ValueID("buffer.normal"), role=UseRole.STATE_CONTENT), add.uses[1]))
    assert_rejected(graph)


def test_compute_cannot_manufacture_unused_state_without_access_or_call():
    graph = branch_state_program()
    add = get_operation(graph, "sum")
    forged = StateVersionValue(ValueID("forged.state"), graph.root,
                               OperationResult(add.id, 1), LocationID("buffer"))
    graph = replace_operation(graph, "sum", results=(*add.results, forged.id))
    assert_rejected(replace(graph, values=(*graph.values, forged)))


def test_reference_selector_and_access_cannot_exceed_known_location_extent():
    graph = branch_state_program()
    outside = Footprint(FootprintKind.INTERVAL, 5, 6)
    graph = replace(graph, values=tuple(
        replace(value, selector=outside) if value.id == ValueID("reference") else value
        for value in graph.values))
    for name in ("read", "write"):
        op = get_operation(graph, name)
        graph = replace_operation(graph, name, accesses=(replace(op.accesses[0], footprint=outside),))
    assert_rejected(graph)


def test_call_reference_result_cannot_invent_identity_or_target_precision():
    graph = shared_body_calls_program()
    result_ids = {ValueID("body.result"), ValueID("call1.result"), ValueID("call2.result")}
    graph = replace(graph, values=tuple(
        ReferenceValue(value.id, value.region, value.origin,
                       "invented-identity" if value.id == ValueID("call1.result") else None,
                       (LocationID("calls"),) if value.id == ValueID("call1.result") else None)
        if value.id in result_ids else value for value in graph.values))
    reference_type = ValueType(ValueKind.REFERENCE)
    caller, callee = graph.regions
    caller = replace(caller, exits=(replace(caller.exits[0], types=(
        reference_type, reference_type, caller.exits[0].types[-1])),))
    callee = replace(callee, exits=(replace(callee.exits[0], types=(
        reference_type, callee.exits[0].types[-1])),))
    graph = replace(graph, regions=(caller, callee))
    for name in ("caller.done", "callee.done"):
        op = get_operation(graph, name)
        graph = replace_operation(graph, name, uses=tuple(
            replace(item, role=UseRole.REFERENCE) if item.value in result_ids else item
            for item in op.uses))
    assert_rejected(graph)


def test_normal_exit_cannot_drop_log_state_even_with_matching_exit_arity():
    graph = branch_state_program()
    done = get_operation(graph, "done")
    graph = replace_operation(graph, "done", uses=done.uses[:-1],
                              terminator=replace(done.terminator, values=done.terminator.values[:-1]))
    root = graph.regions[0]
    graph = replace(graph, regions=(replace(root, exits=tuple(
        replace(port, types=port.types[:-1]) if port.name == "normal" else port for port in root.exits)),))
    assert_rejected(graph)


def test_call_arguments_are_positional_typed_bindings():
    graph = shared_body_calls_program()
    call = get_operation(graph, "call1")
    assert_rejected(replace_operation(graph, "call1", call_arguments=tuple(reversed(call.call_arguments))))


def test_plain_call_cannot_silently_ignore_callee_exception_exit():
    graph = shared_body_calls_program()
    caller, callee = graph.regions
    exceptional = replace(callee.exits[0], name="failure", kind=ExitKind.RAISE)
    assert_rejected(replace(graph, regions=(caller, replace(callee, exits=(*callee.exits, exceptional)))))


def test_use_ids_are_unique_across_distinct_operations():
    graph = branch_state_program()
    add = get_operation(graph, "sum")
    graph = replace_operation(graph, "sum", uses=(replace(add.uses[0], id=UseID("read.reference")), add.uses[1]))
    assert_rejected(graph)


def test_missing_value_and_inconsistent_result_origin_rejected():
    graph = branch_state_program()
    assert_rejected(replace_use(graph, "sum", "sum.left", "missing-value"))
    assert_rejected(replace(graph, values=tuple(
        replace(value, origin=OperationResult(OperationID("read"), 0))
        if value.id == ValueID("sum.value") else value for value in graph.values)))


@pytest.mark.parametrize("before,after", (("write", "read"), ("write", "fail"), ("missing", "done")))
def test_order_cannot_reverse_execution_or_join_mutually_exclusive_branches(before, after):
    graph = branch_state_program()
    assert_rejected(replace(graph, ordering=(OrderEdge(OperationID(before), OperationID(after)),)))


def test_non_boolean_branch_condition_rejected():
    assert_rejected(replace_use(branch_state_program(), "choose", "choose.condition", "input"))


def test_parent_region_cycle_rejected_without_rejecting_shared_calls():
    graph = shared_body_calls_program()
    caller, callee = graph.regions
    assert_rejected(replace(graph, regions=(replace(caller, parent=callee.id), callee)))
