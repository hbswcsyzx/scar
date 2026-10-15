"""Manual counterexamples for completion validation, not source-recovery evidence."""

from dataclasses import replace

import pytest

from scar.ir.program import (
    Behavior, BlockID, CompletionResult, CompletionSignature, CompletionSuccessor,
    DataValue, ExitKind, ExitPort, Footprint, FootprintKind, LiteralOrigin,
    LocationID, OperationID, ProgramGraph, ReferenceValue, Region, RegionID,
    StateLocation, Terminator, TerminatorKind, UseID, UseRole, ValueID,
    ValueKind, ValueType, dumps, loads,
)
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_graphs import (
    argument, block, data, operation, state, state_type, successor, use,
)


def _op(graph, name="main.invoke"):
    return next(item for item in graph.operations if item.id == OperationID(name))


def _replace_op(graph, name="main.invoke", **changes):
    return replace(graph, operations=tuple(
        replace(item, **changes) if item.id == OperationID(name) else item
        for item in graph.operations
    ))


def _replace_value(graph, name, **changes):
    return replace(graph, values=tuple(
        replace(item, **changes) if item.id == ValueID(name) else item
        for item in graph.values
    ))


def _reject(graph, code):
    issues = validate(graph)
    assert issues, "validator accepted the malformed completion graph"
    assert code in {issue.code for issue in issues}, issues
    with pytest.raises(ValueError):
        require_valid(graph)
    with pytest.raises(ValueError):
        dumps(graph)


def _invoke_graph(prefix="main", *, domains=("world",), normal_data_type=None):
    """One opaque invocation, with a separate result and post-state per path."""
    region_id = RegionID(prefix)
    entry = f"{prefix}.entry"
    input_id = f"{prefix}.input"
    values = [ReferenceValue(ValueID(input_id), region_id, argument(entry, 0))]
    values.extend(state(f"{prefix}.before.{domain}", prefix,
                        argument(entry, index + 1), domain)
                  for index, domain in enumerate(domains))
    operands = (use(f"{prefix}.operand", input_id, UseRole.REFERENCE),) + tuple(
        use(f"{prefix}.state.{domain}", f"{prefix}.before.{domain}",
            UseRole.STATE_CONTENT) for domain in domains
    )
    blocks = [block(entry, (input_id, *(f"{prefix}.before.{d}" for d in domains)),
                    (f"{prefix}.invoke",))]
    signatures, edges, exits, terminals = [], [], [], []
    for kind in (ExitKind.NORMAL, ExitKind.RAISE):
        path = kind.value.lower()
        target = f"{prefix}.{path}"
        output_id = f"{target}.value"
        if kind is ExitKind.NORMAL and normal_data_type is not None:
            output = data(output_id, prefix, argument(target, 0), normal_data_type)
            output_type = ValueType(ValueKind.DATA, data_type=normal_data_type)
            role = UseRole.DATA
        else:
            output = ReferenceValue(ValueID(output_id), region_id, argument(target, 0))
            output_type = ValueType(ValueKind.REFERENCE)
            role = UseRole.REFERENCE
        values.append(output)
        values.extend(state(f"{target}.{domain}", prefix,
                            argument(target, index + 1), domain)
                      for index, domain in enumerate(domains))
        types = (output_type, *(state_type(domain) for domain in domains))
        signatures.append(CompletionSignature(kind, types))
        edges.append(CompletionSuccessor(kind, BlockID(target), tuple(
            CompletionResult(index) for index in range(len(types))
        )))
        exits.append(ExitPort(path, kind, types))
        final_uses = (use(f"{target}.return.value", output_id, role),) + tuple(
            use(f"{target}.return.{domain}", f"{target}.{domain}",
                UseRole.STATE_CONTENT) for domain in domains
        )
        terminals.append(operation(f"{target}.done", (Behavior.CONTROL,), final_uses,
            terminator=Terminator(
                TerminatorKind.RETURN if kind is ExitKind.NORMAL else TerminatorKind.RAISE,
                exit=path, values=tuple(item.id for item in final_uses),
            )))
        blocks.append(block(target, (output_id, *(f"{target}.{d}" for d in domains)),
                            (f"{target}.done",)))
    invoke = operation(f"{prefix}.invoke",
        (Behavior.CONTROL, Behavior.COMPUTE, Behavior.READ, Behavior.WRITE), operands,
        terminator=Terminator(TerminatorKind.INVOKE, tuple(edges)),
        completions=tuple(signatures), invoke_arguments=tuple(item.id for item in operands))
    region = Region(region_id, prefix, BlockID(entry), tuple(blocks), tuple(exits))
    graph = ProgramGraph(region_id, (region,), (invoke, *terminals), tuple(values), tuple(
        StateLocation(LocationID(domain), domain) for domain in domains
    ))
    require_valid(graph)
    return graph


def _forward_slot(graph, kind, index, *, share_operand=False):
    """Replace a produced slot with an existing value; keep the slot map exact."""
    invoke = _op(graph)
    original = invoke.uses[index]
    forwarded = replace(original, id=UseID(f"main.forward.{kind.value}.{index}"))
    if share_operand:
        forwarded = original
    signatures = tuple(
        replace(signature, types=signature.types[:index] + signature.types[index + 1:])
        if signature.kind is kind else signature for signature in invoke.completions
    )
    edges = []
    for edge in invoke.terminator.successors:
        if edge.kind is kind:
            arguments = tuple(
                forwarded.id if item.index == index else
                CompletionResult(item.index - (item.index > index))
                for item in edge.arguments
            )
            edge = replace(edge, arguments=arguments)
        edges.append(edge)
    return _replace_op(graph,
        uses=invoke.uses if share_operand else (*invoke.uses, forwarded),
        completions=signatures,
        terminator=replace(invoke.terminator, successors=tuple(edges)))


def _with_callee(*, normal_data_type=None):
    caller = _invoke_graph()
    child = _invoke_graph("callee", normal_data_type=normal_data_type)
    child_region = replace(child.regions[0], parent=caller.root)
    graph = replace(caller, regions=(*caller.regions, child_region),
                    operations=(*caller.operations, *child.operations),
                    values=(*caller.values, *child.values))
    return _replace_op(graph, callee=child.root)


def _shared_private_target_graph():
    """An extra branch sends both edges to an INVOKE's normal private target."""
    graph = _invoke_graph()
    values = list(graph.values)
    blocks = list(graph.regions[0].blocks)
    for name in ("dispatch", "side"):
        values.extend((
            ReferenceValue(ValueID(f"{name}.input"), graph.root, argument(name, 0)),
            state(f"{name}.world", "main", argument(name, 1), "world"),
        ))
    values.append(data("condition", "main", LiteralOrigin(True), "builtins.bool"))
    operations = list(graph.operations)
    for name, targets in (("dispatch", ("main.entry", "side")),
                          ("side", ("main.normal", "main.normal"))):
        operands = [use(f"{name}.condition", "condition")]
        edges = []
        for index, target in enumerate(targets):
            reference = use(f"{name}.{index}.ref", f"{name}.input", UseRole.REFERENCE)
            world = use(f"{name}.{index}.world", f"{name}.world", UseRole.STATE_CONTENT)
            operands.extend((reference, world))
            edges.append(successor(target, reference.id.value, world.id.value))
        operations.append(operation(f"{name}.branch", (Behavior.CONTROL,), tuple(operands),
            terminator=Terminator(TerminatorKind.BRANCH, tuple(edges),
                                  condition=UseID(f"{name}.condition"))))
        blocks.append(block(name, (f"{name}.input", f"{name}.world"), (f"{name}.branch",)))
    region = replace(graph.regions[0], entry=BlockID("dispatch"), blocks=tuple(blocks))
    return replace(graph, regions=(region,), operations=tuple(operations), values=tuple(values))


def test_invoke_graph_roundtrips_real_validation_and_keeps_path_local_definitions():
    graph = _invoke_graph(domains=("world", "rng"))
    restored = loads(dumps(graph))
    assert restored == graph
    assert _op(restored).results == ()
    normal, raised = _op(restored).terminator.successors
    assert normal.arguments == raised.arguments == tuple(CompletionResult(i) for i in range(3))
    assert normal.block != raised.block
    assert ValueID("main.normal.world") != ValueID("main.raise.world")


@pytest.mark.parametrize("path,other", (("raise", "normal"), ("normal", "raise")))
def test_completion_result_is_unavailable_on_the_other_path(path, other):
    graph = _invoke_graph()
    terminal = _op(graph, f"main.{path}.done")
    graph = _replace_op(graph, f"main.{path}.done", uses=(
        replace(terminal.uses[0], value=ValueID(f"main.{other}.value")),
        *terminal.uses[1:],
    ))
    _reject(graph, "unavailable_value")


def test_completion_result_is_unavailable_before_its_invoke():
    graph = _invoke_graph()
    invoke = _op(graph)
    graph = _replace_op(graph, uses=(
        replace(invoke.uses[0], value=ValueID("main.normal.value")), *invoke.uses[1:],
    ))
    _reject(graph, "unavailable_value")


@pytest.mark.parametrize("path", ("normal", "raise"))
def test_completion_exit_cannot_roll_state_back_to_before_invocation(path):
    graph = _invoke_graph()
    terminal = _op(graph, f"main.{path}.done")
    graph = _replace_op(graph, f"main.{path}.done", uses=(terminal.uses[0],
        replace(terminal.uses[1], value=ValueID("main.before.world")),
    ))
    _reject(graph, "stale_state")


@pytest.mark.parametrize("kind", (ExitKind.NORMAL, ExitKind.RAISE))
@pytest.mark.parametrize("changes", (
    {"targets": ()},
    {"targets": (LocationID("world"),)},
    {"referent_identity": "invented-object"},
    {"selector": Footprint(FootprintKind.WHOLE)},
))
def test_produced_reference_cannot_invent_target_identity_or_selector(kind, changes):
    graph = _invoke_graph()
    graph = _replace_value(graph, f"main.{kind.value.lower()}.value", **changes)
    _reject(graph, "completion_reference_precision")


def test_private_completion_target_rejects_extra_parallel_incoming_edges():
    graph = _shared_private_target_graph()
    target = BlockID("main.normal")
    incoming = [op for op in graph.operations for edge in op.terminator.successors
                if edge.block == target]
    assert len(incoming) == 3
    assert len({op.id for op in incoming}) == 2
    _reject(graph, "completion_private_target")


@pytest.mark.parametrize("kind", (ExitKind.NORMAL, ExitKind.RAISE))
@pytest.mark.parametrize("defect,code", (
    ("missing", "completion_slots"),
    ("duplicate", "completion_slots"),
    ("out_of_range", "completion_index"),
))
def test_completion_result_slots_cannot_be_omitted_duplicated_or_out_of_range(kind, defect, code):
    graph = _invoke_graph()
    invoke = _op(graph)
    edges = []
    extra = use("replacement.forward", "main.input", UseRole.REFERENCE)
    for edge in invoke.terminator.successors:
        if edge.kind is kind:
            first = (extra.id if defect == "missing" else CompletionResult(
                1 if defect == "duplicate" else 2))
            edge = replace(edge, arguments=(first, edge.arguments[1]))
        edges.append(edge)
    graph = _replace_op(graph,
        uses=(*invoke.uses, extra) if defect == "missing" else invoke.uses,
        terminator=replace(invoke.terminator, successors=tuple(edges)))
    _reject(graph, code)


@pytest.mark.parametrize("kind", (ExitKind.NORMAL, ExitKind.RAISE))
def test_same_value_can_be_invoke_operand_and_forwarded_with_distinct_use_ids(kind):
    graph = _forward_slot(_invoke_graph(), kind, 0)
    require_valid(graph)
    assert loads(dumps(graph)) == graph


@pytest.mark.parametrize("kind", (ExitKind.NORMAL, ExitKind.RAISE))
def test_invoke_operand_and_forwarded_port_cannot_share_one_use_id(kind):
    graph = _forward_slot(_invoke_graph(), kind, 0, share_operand=True)
    _reject(graph, "control_binding")


@pytest.mark.parametrize("kind", (ExitKind.NORMAL, ExitKind.RAISE))
@pytest.mark.parametrize("index", (1, 2))
def test_unknown_effects_must_produce_every_state_domain_on_each_path(kind, index):
    graph = _forward_slot(_invoke_graph(domains=("world", "rng")), kind, index)
    _reject(graph, "completion_unknown_state")


@pytest.mark.parametrize("kind", (ExitKind.NORMAL, ExitKind.RAISE))
def test_declared_complete_effects_can_forward_an_unchanged_state_domain(kind):
    graph = _forward_slot(_invoke_graph(domains=("world", "rng")), kind, 2)
    graph = _replace_op(graph, effects_complete=True)
    require_valid(graph)
    assert loads(dumps(graph)) == graph


def test_produced_state_requires_a_current_state_invoke_operand():
    graph = _invoke_graph()
    invoke = _op(graph)
    graph = _replace_op(graph, uses=invoke.uses[:1], invoke_arguments=invoke.invoke_arguments[:1])
    _reject(graph, "completion_state_input")


def test_invoke_state_operand_cannot_downgrade_content_to_order():
    graph = _invoke_graph()
    invoke = _op(graph)
    graph = _replace_op(graph, uses=(invoke.uses[0],
        replace(invoke.uses[1], role=UseRole.STATE_ORDER),
    ))
    _reject(graph, "control_state_role")


def test_completion_slots_are_checked_against_their_own_kind_signature():
    graph = _invoke_graph(normal_data_type="builtins.bool")
    invoke = _op(graph)
    graph = _replace_op(graph, completions=tuple(
        replace(signature, types=invoke.completions[1 - index].types)
        for index, signature in enumerate(invoke.completions)
    ))
    _reject(graph, "completion_type")


def test_known_invoke_callee_with_matching_entry_and_both_exit_interfaces_is_valid():
    graph = _with_callee()
    require_valid(graph)
    assert loads(dumps(graph)) == graph


def test_known_invoke_callee_cannot_change_normal_completion_type():
    graph = _with_callee(normal_data_type="builtins.bool")
    _reject(graph, "invoke_callee_exits")


def test_known_invoke_callee_cannot_swap_entry_argument_types():
    graph = _with_callee()
    invoke = _op(graph)
    graph = _replace_op(graph, invoke_arguments=tuple(reversed(invoke.invoke_arguments)))
    _reject(graph, "invoke_callee_type")


def test_known_invoke_callee_cannot_have_an_extra_argument():
    graph = _with_callee()
    invoke = _op(graph)
    extra = use("main.extra.operand", "main.input", UseRole.REFERENCE)
    graph = _replace_op(graph, uses=(*invoke.uses, extra),
                        invoke_arguments=(*invoke.invoke_arguments, extra.id))
    _reject(graph, "invoke_callee_arity")
