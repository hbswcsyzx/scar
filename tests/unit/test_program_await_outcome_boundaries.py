"""Selected parent completions constrain original await result projections."""
from dataclasses import replace

from scar.ir.execution.validity_budget import ValidityBudget
from scar.ir.program.await_outcome_flow import consumers, flow
from scar.ir.program.ids import UseID
from scar.ir.program.model import (
    CompletionResult, ExitKind, InvokeLiteralResult, StateVersionValue,
    TerminatorKind, ValueKind,
)
from scar.ir.program.protocol_await import _result_copy
from scar.ir.program.protocol_connection_flow import ConnectionContext
from scar.ir.program.protocols import OwnedUse
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.program.validation import require_valid
from tests.fixtures.program_await_general_graphs import await_general_program
from tests.fixtures.program_await_outcome_graphs import await_outcome_program


def _general_result_context():
    graph, details = await_general_program()
    # Preserve every original operation, producer, state and control edge.
    # Family annotations are unnecessary for this original-port helper check.
    core = replace(graph, protocol_scopes=(), protocol_operations=(),
        protocol_call_inputs=(), protocol_result_consumers=(), protocol_bindings=())
    require_valid(core)
    index = ProgramIndex(core)
    budget = ValidityBudget(65536)
    context = ConnectionContext(core, index=index, budget=budget)
    parent = details["get"]
    normal_index = next(index for index, edge in enumerate(parent.terminator.successors)
                        if edge.kind is ExitKind.NORMAL)
    raised_index = next(index for index, edge in enumerate(parent.terminator.successors)
                        if edge.kind is ExitKind.RAISE)
    normal_edge = ControlEdgeReference(parent.id, normal_index)
    raised_edge = ControlEdgeReference(parent.id, raised_index)
    result = InvokeLiteralResult(normal_edge, CompletionResult(0))
    terminal = details["helper_return"]
    source = OwnedUse(terminal.id, terminal.terminator.values[0])
    assert parent.callee == details["helper"].id == context.region_of[terminal.id]
    assert terminal.terminator.kind is TerminatorKind.RETURN
    assert normal_edge != raised_edge
    return context, budget, source, result, normal_edge, raised_edge


def test_callee_normal_terminal_cannot_project_to_normal_parent_under_raise_choice():
    context, budget, source, result, normal_edge, raised_edge = _general_result_context()
    assert _result_copy(context, source, result, choices=(normal_edge,))["match"] is True

    report = _result_copy(context, source, result, choices=(raised_edge,))

    assert not budget.truncated
    assert report["match"] is False


def test_identical_normal_result_cannot_bypass_the_parent_raise_choice():
    context, budget, _, result, normal_edge, raised_edge = _general_result_context()
    assert _result_copy(context, result, result, choices=(normal_edge,))["match"] is True

    report = _result_copy(context, result, result, choices=(raised_edge,))

    assert not budget.truncated
    assert report["match"] is False


def _qualification_reject(context, source):
    accepted = context.block_of[source.operation]
    branch = next(operation for operation in context.graph.operations
        if context.region_of[operation.id] == context.region_of[source.operation]
        and operation.terminator is not None
        and operation.terminator.kind is TerminatorKind.BRANCH
        and any(edge.block == accepted for edge in operation.terminator.successors))
    reject = next(index for index, edge in enumerate(branch.terminator.successors)
                  if edge.block != accepted)
    return ControlEdgeReference(branch.id, reject)


def test_callee_normal_source_reject_choice_is_false_instead_of_an_exception():
    context, budget, source, result, _, _ = _general_result_context()
    reject = _qualification_reject(context, source)

    report = _result_copy(context, source, result, choices=(reject,))

    assert not budget.truncated
    assert report["match"] is False


def test_known_source_choice_conflict_has_an_explicit_empty_consumer_inventory():
    context, budget, source, _, _, _ = _general_result_context()
    reject = _qualification_reject(context, source)

    assert flow(context, source, (reject,)) == {}
    report = consumers(context, source, (reject,))

    assert not budget.truncated
    assert report["targets"] == ()
    assert report["support"] == ()
    assert "await_source_choice_conflict" in report["gaps"]


def test_final_extractor_keeps_forwarded_current_state_on_both_original_completions():
    graph, details = await_outcome_program(zero_cut=True)
    extractor = details["extract"]
    values = {value.id: value for value in graph.values}
    own = {use.id: use for use in extractor.uses}
    state_inputs = {values[own[identity].value].location: own[identity]
        for identity in extractor.invoke_arguments
        if isinstance(values[own[identity].value], StateVersionValue)}
    assert state_inputs
    signatures = {signature.kind: signature for signature in extractor.completions}
    edges, forwarded, expected = [], [], {}
    for number, edge in enumerate(extractor.terminator.successors):
        signature = signatures[edge.kind]
        arguments, expected_edge = [], {}
        for position, argument in enumerate(edge.arguments):
            assert type(argument) is CompletionResult
            type_ = signature.types[argument.index]
            if type_.kind is ValueKind.STATE:
                original = state_inputs[type_.location]
                # Every original edge port needs its own Use, even though
                # both completions preserve the same current state value.
                edge_use = replace(original,
                    id=UseID(f"{original.id.value}.forward.{number}"))
                forwarded.append(edge_use)
                arguments.append(edge_use.id)
                expected_edge[position] = edge_use
            else:
                assert argument.index == 0
                arguments.append(argument)
        edges.append(replace(edge, arguments=tuple(arguments)))
        expected[ControlEdgeReference(extractor.id, number)] = expected_edge
    extractor = replace(extractor, uses=(*extractor.uses, *forwarded),
        effects_complete=True,
        completions=tuple(replace(signature, types=tuple(type_ for type_ in signature.types
            if type_.kind is not ValueKind.STATE)) for signature in extractor.completions),
        terminator=replace(extractor.terminator, successors=tuple(edges)))
    graph = replace(graph, operations=tuple(extractor if operation.id == extractor.id
        else operation for operation in graph.operations))
    require_valid(graph)
    assert all(len(signature.types) == 1 for signature in extractor.completions)
    assert all(argument.index == 0 for edge in extractor.terminator.successors
        for argument in edge.arguments if type(argument) is CompletionResult)

    report = ProgramIndex(graph).protocol_obligations(details["acquisition_scope"],
        budget=524288)["connections"]["families"]["await"]
    outcome, = tuple(row for row in report["outcomes"]
        if row["source"] == details["source"]
        and row["advance_operation"] == details["advance_operation"]
        and row["drive_outcome"] == details["drive_outcome"])
    matching = tuple(consumer for consumer in outcome["consumers"]
        if consumer["actual"] == details["extract_input"]
        and consumer["requires_final_extraction"] is True)
    assert matching
    assert {edge.kind for edge in extractor.terminator.successors} == {
        ExitKind.NORMAL, ExitKind.RAISE}
    for consumer in matching:
        legs = {leg["edge"]: leg for leg in consumer["legs"]}
        assert set(legs) == set(expected)
        for edge, expected_edge in expected.items():
            states = legs[edge]["states"]
            assert len(states) == len(expected_edge)
            assert {state["position"] for state in states} == set(expected_edge)
            for state in states:
                forwarded_use = expected_edge[state["position"]]
                assert state["slot"] is None
                assert state["forwarded"] is True
                assert state["source"] == OwnedUse(extractor.id, forwarded_use.id)
                assert type(state["target"]) is OwnedUse
                terminal = next(operation for operation in graph.operations
                    if operation.id == state["target"].operation)
                target = next(use for use in terminal.uses
                    if use.id == state["target"].use)
                assert target.id in terminal.terminator.values
                assert values[target.value].location == values[forwarded_use.value].location
                assert state["binding"]["match"] is True
