"""Independent N1 counterexamples for edge bindings and explicit state SSA."""

from dataclasses import replace

import pytest

from scar.ir.program.codec import dumps, loads
from scar.ir.program.ids import BlockID, LocationID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.model import (
    AccessMode, Behavior, ExitKind, ExitPort, Footprint, FootprintKind,
    LiteralOrigin, ProgramGraph, ReferenceValue, Region, StateAccess,
    StateLocation, Successor, Terminator, TerminatorKind, UseRole,
    ValueKind, ValueType,
)
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_graphs import (
    argument, block, branch_state_program, data, operation, result,
    save_payload_program, shared_body_calls_program, state, successor, use,
)


def _operation(graph, name):
    return next(item for item in graph.operations if item.id == OperationID(name))


def _replace_operation(graph, name, **changes):
    return replace(graph, operations=tuple(
        replace(item, **changes) if item.id == OperationID(name) else item
        for item in graph.operations
    ))


def _replace_value(graph, name, **changes):
    return replace(graph, values=tuple(
        replace(item, **changes) if item.id == ValueID(name) else item
        for item in graph.values
    ))


def _assert_rejected(graph, expected_code=None):
    issues = validate(graph)
    assert issues, "validator accepted the malformed declared graph"
    if expected_code is not None:
        assert expected_code in {issue.code for issue in issues}, issues
    with pytest.raises(ValueError):
        require_valid(graph)
    with pytest.raises(ValueError):
        dumps(graph)


def _parallel_branch_program():
    """Both branch arms reach the same block, but select different arguments."""
    values = (
        data("condition", "parallel", argument("parallel.entry", 0), "builtins.bool"),
        data("left", "parallel", LiteralOrigin(1)),
        data("right", "parallel", LiteralOrigin(2)),
        data("selected", "parallel", argument("parallel.join", 0)),
    )
    choose = operation("parallel.choose", (Behavior.CONTROL,), (
        use("parallel.condition", "condition"),
        use("parallel.left", "left"),
        use("parallel.right", "right"),
    ), terminator=Terminator(
        TerminatorKind.BRANCH,
        (successor("parallel.join", "parallel.left"),
         successor("parallel.join", "parallel.right")),
        condition=UseID("parallel.condition"),
    ))
    done = operation("parallel.done", (Behavior.CONTROL,), (
        use("parallel.return", "selected"),
    ), terminator=Terminator(TerminatorKind.RETURN, exit="normal",
                            values=(UseID("parallel.return"),)))
    region = Region(RegionID("parallel"), "parallel CFG edges", BlockID("parallel.entry"), (
        block("parallel.entry", ("condition",), ("parallel.choose",)),
        block("parallel.join", ("selected",), ("parallel.done",)),
    ), (ExitPort("normal", ExitKind.NORMAL, (ValueType(ValueKind.DATA, "builtins.int"),)),))
    return ProgramGraph(region.id, (region,), (choose, done), values)


def _reference_binding_program(boundary, *, returns_reference=False):
    """Known references cross a CFG edge or a direct call without state access."""
    caller = RegionID("reference.caller")
    callee = RegionID("reference.callee")
    is_call = boundary == "call"
    actual = ReferenceValue(
        ValueID("actual.ref"), caller, argument("reference.entry", 0),
        "object-A", (LocationID("A"),), Footprint(FootprintKind.INTERVAL, 0, 4),
    )
    formal = replace(
        actual, id=ValueID("formal.ref"), region=callee if is_call else caller,
        origin=argument("reference.body", 0),
    )
    values = [actual, formal]
    result_ids = ()
    if returns_reference:
        assert is_call
        values.append(ReferenceValue(ValueID("returned.ref"), caller, result("reference.bind")))
        result_ids = ("returned.ref",)
    binding = operation("reference.bind", (Behavior.CONTROL,), (
        use("reference.actual", "actual.ref", UseRole.REFERENCE),
    ), result_ids, **(
        {"callee": callee, "call_arguments": (UseID("reference.actual"),)}
        if is_call else
        {"terminator": Terminator(TerminatorKind.JUMP, (
            successor("reference.body", "reference.actual"),
        ))}
    ))
    body_uses = ((use("reference.body.return", "formal.ref", UseRole.REFERENCE),)
                 if returns_reference else ())
    body_done = operation("reference.body.done", (Behavior.CONTROL,), body_uses,
        terminator=Terminator(TerminatorKind.RETURN, exit="normal",
                              values=tuple(item.id for item in body_uses)))
    return_types = (ValueType(ValueKind.REFERENCE),) if returns_reference else ()
    normal = (ExitPort("normal", ExitKind.NORMAL, return_types),)
    if is_call:
        caller_uses = ((use("reference.caller.return", "returned.ref", UseRole.REFERENCE),)
                       if returns_reference else ())
        caller_done = operation("reference.caller.done", (Behavior.CONTROL,), caller_uses,
            terminator=Terminator(TerminatorKind.RETURN, exit="normal",
                                  values=tuple(item.id for item in caller_uses)))
        regions = (
            Region(caller, "reference caller", BlockID("reference.entry"), (
                block("reference.entry", ("actual.ref",), ("reference.bind", "reference.caller.done")),
            ), normal),
            Region(callee, "reference body", BlockID("reference.body"), (
                block("reference.body", ("formal.ref",), ("reference.body.done",)),
            ), normal, parent=caller),
        )
        operations = (binding, caller_done, body_done)
    else:
        regions = (Region(caller, "reference CFG binding", BlockID("reference.entry"), (
            block("reference.entry", ("actual.ref",), ("reference.bind",)),
            block("reference.body", ("formal.ref",), ("reference.body.done",)),
        ), normal),)
        operations = (binding, body_done)
    return ProgramGraph(caller, regions, operations, tuple(values), (
        StateLocation(LocationID("A"), "first buffer", extent=8),
        StateLocation(LocationID("B"), "second buffer", extent=8),
    ))


def _two_full_overwrites_program():
    graph = save_payload_program()
    write = operation("file.rewrite", (Behavior.WRITE,), (
        use("file.rewrite.data", "encoded"),
        use("file.rewrite.before", "file.after", UseRole.STATE_ORDER),
    ), ("file.final",), accesses=(StateAccess(
        LocationID("file"), UseID("file.rewrite.before"), AccessMode.WRITE,
        ValueID("file.final"), Footprint(FootprintKind.WHOLE), full_overwrite=True,
    ),), effects_complete=True)
    graph = _replace_operation(graph, "save.done", uses=(
        use("save.return", "file.final", UseRole.STATE_CONTENT),
    ))
    region = graph.regions[0]
    entry = region.blocks[0]
    return replace(
        graph,
        operations=(*graph.operations, write),
        values=(*graph.values, state("file.final", "save", result("file.rewrite"), "file")),
        regions=(replace(region, blocks=(replace(
            entry, operations=(*entry.operations[:-1], write.id, entry.operations[-1]),
        ),)),),
    )


def test_parallel_branch_edges_preserve_distinct_argument_bindings_and_uses():
    graph = _parallel_branch_program()
    require_valid(graph)
    restored = loads(dumps(graph))
    edges = _operation(restored, "parallel.choose").terminator.successors
    assert edges[0].block == edges[1].block
    assert edges[0].arguments == (UseID("parallel.left"),)
    assert edges[1].arguments == (UseID("parallel.right"),)
    index = ProgramIndex(restored)
    assert [site.use.id for site in index.consumers(ValueID("left"))] == [UseID("parallel.left")]
    assert [site.use.id for site in index.consumers(ValueID("right"))] == [UseID("parallel.right")]


def test_full_overwrite_preserves_current_order_input_without_claiming_content_read():
    graph = _two_full_overwrites_program()
    require_valid(graph)
    consumers = ProgramIndex(graph).consumers(ValueID("file.after"))
    assert [(site.operation, site.use.role) for site in consumers] == [
        (OperationID("file.rewrite"), UseRole.STATE_ORDER),
    ]


def test_full_overwrite_order_input_cannot_skip_an_intervening_write():
    graph = _two_full_overwrites_program()
    require_valid(graph)
    rewrite = _operation(graph, "file.rewrite")
    graph = _replace_operation(graph, "file.rewrite", uses=tuple(
        replace(item, value=ValueID("file.before")) if item.role is UseRole.STATE_ORDER else item
        for item in rewrite.uses
    ))
    _assert_rejected(graph, "stale_state")


@pytest.mark.parametrize("boundary", ("cfg", "call"))
@pytest.mark.parametrize("changes,code", (
    ({"targets": (LocationID("B"),)}, "reference_binding"),
    ({"selector": Footprint(FootprintKind.INTERVAL, 2, 6)}, "reference_selector"),
    ({"referent_identity": "different-object"}, "reference_identity"),
))
def test_reference_port_cannot_change_known_target_selector_or_identity(boundary, changes, code):
    graph = _reference_binding_program(boundary)
    require_valid(graph)
    _assert_rejected(_replace_value(graph, "formal.ref", **changes), code)


@pytest.mark.parametrize("boundary", ("cfg", "call"))
def test_reference_port_cannot_refine_unknown_targets_without_evidence(boundary):
    graph = _reference_binding_program(boundary)
    require_valid(graph)
    _assert_rejected(_replace_value(graph, "actual.ref", targets=None), "reference_binding")


@pytest.mark.parametrize("boundary", ("cfg", "call"))
def test_reference_port_may_conservatively_forget_reference_precision(boundary):
    graph = _reference_binding_program(boundary)
    graph = _replace_value(graph, "formal.ref", targets=None, referent_identity=None,
                           selector=Footprint())
    assert validate(graph) == ()


@pytest.mark.parametrize("changes", (
    {"targets": (LocationID("A"),)},
    {"targets": ()},
    {"referent_identity": "object-A"},
    {"selector": Footprint(FootprintKind.INTERVAL, 0, 4)},
))
def test_call_reference_return_cannot_invent_precision_before_return_summary_support(changes):
    graph = _reference_binding_program("call", returns_reference=True)
    require_valid(graph)
    _assert_rejected(_replace_value(graph, "returned.ref", **changes),
                     "unsupported_call_reference_summary")


def test_distinct_state_argument_ids_cannot_hide_duplicate_entry_location():
    graph = save_payload_program()
    require_valid(graph)
    region = graph.regions[0]
    entry = region.blocks[0]
    duplicate = state("file.duplicate", "save", argument("save.entry", 2), "file")
    graph = replace(graph, values=(*graph.values, duplicate), regions=(replace(
        region, blocks=(replace(entry, arguments=(*entry.arguments, duplicate.id)),),
    ),))
    _assert_rejected(graph, "duplicate_state_parameter")


def test_distinct_state_argument_ids_cannot_hide_duplicate_nonentry_location():
    graph = branch_state_program()
    require_valid(graph)
    region = graph.regions[0]
    duplicate = state("buffer.normal.duplicate", "root", argument("normal", 2), "buffer")
    graph = replace(graph, values=(*graph.values, duplicate), regions=(replace(
        region, blocks=tuple(
            replace(item, arguments=(*item.arguments, duplicate.id))
            if item.id == BlockID("normal") else item for item in region.blocks
        ),
    ),))
    choose = _operation(graph, "choose")
    extra = use("choose.normal.duplicate", "buffer.initial", UseRole.STATE_CONTENT)
    first, second = choose.terminator.successors
    graph = _replace_operation(graph, "choose", uses=(*choose.uses, extra), terminator=replace(
        choose.terminator, successors=(replace(first, arguments=(*first.arguments, extra.id)), second),
    ))
    _assert_rejected(graph, "state_parameters")


def test_one_operation_cannot_sequence_duplicate_location_accesses_implicitly():
    graph = branch_state_program()
    require_valid(graph)
    read = _operation(graph, "read")
    extra = use("read.state.again", "buffer.normal", UseRole.STATE_CONTENT)
    graph = _replace_operation(graph, "read", uses=(*read.uses, extra), accesses=(
        read.accesses[0], replace(read.accesses[0], before=extra.id),
    ))
    _assert_rejected(graph, "duplicate_state_access")


def test_partially_overlapping_access_cannot_exceed_exact_reference_selector():
    graph = branch_state_program()
    graph = _replace_value(graph, "reference", selector=Footprint(FootprintKind.INTERVAL, 0, 2))
    read = _operation(graph, "read")
    graph = _replace_operation(graph, "read", accesses=(
        replace(read.accesses[0], footprint=Footprint(FootprintKind.INTERVAL, 1, 3)),
    ))
    _assert_rejected(graph, "alias_footprint")


def test_complete_access_cannot_ignore_another_possible_alias_target():
    graph = branch_state_program()
    graph = _replace_value(graph, "reference", targets=(LocationID("buffer"), LocationID("log")))
    _assert_rejected(graph, "incomplete_alias")


def test_reading_callee_cannot_be_declared_as_only_order_dependent_by_the_caller():
    graph = shared_body_calls_program()
    require_valid(graph)
    call = _operation(graph, "call1")
    graph = _replace_operation(graph, "call1", uses=tuple(
        replace(item, role=UseRole.STATE_ORDER) if item.id == UseID("call1.state") else item
        for item in call.uses
    ))
    _assert_rejected(graph)


def test_direct_call_cannot_claim_an_extra_use_that_is_not_bound_to_any_callee_port():
    graph = shared_body_calls_program()
    require_valid(graph)
    call = _operation(graph, "call1")
    graph = _replace_operation(graph, "call1", uses=(
        *call.uses, use("call1.unbound-input", "caller.input"),
    ))
    _assert_rejected(graph)


@pytest.mark.parametrize("name,use_id", (
    ("choose", "choose.normal.buffer"),
    ("done", "done.buffer"),
    ("fail", "fail.buffer"),
))
def test_control_interfaces_cannot_downgrade_state_content_to_only_order(name, use_id):
    graph = branch_state_program()
    op = _operation(graph, name)
    graph = _replace_operation(graph, name, uses=tuple(
        replace(item, role=UseRole.STATE_ORDER) if item.id == UseID(use_id) else item
        for item in op.uses
    ))
    _assert_rejected(graph, "control_state_role")
