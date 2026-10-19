"""Budgets and output alternatives preserve the original extraction interface."""
from copy import deepcopy
from dataclasses import replace

from scar.ir.execution.validity_budget import ValidityBudget
from scar.ir.program.ids import OperationID, UseID, ValueID
from scar.ir.program.model import (
    Behavior, CompletionResult, ExitKind, InvokeLiteralResult, Operation,
    OperationResult, ReferenceValue, Use, UseRole,
)
from scar.ir.program.protocol_connection_flow import ConnectionContext
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.program.validation import require_valid
from tests.fixtures.program_await_final_region_graphs import await_final_region_program


QUERY_BUDGET = 1048576


def _index(program):
    require_valid(program)
    return ProgramIndex(program)


def _project(index, details, *, budget=QUERY_BUDGET):
    from scar.ir.program.region_implementation import region_implementation
    accounting = ValidityBudget(budget)
    context = ConnectionContext(index.graph, index=index, budget=accounting)
    report = region_implementation(context, details['root_source'],
                                   details['parent_call'])
    return report, accounting


def _raw_outputs(operation):
    signatures = {signature.kind: signature for signature in operation.completions}
    return {InvokeLiteralResult(ControlEdgeReference(operation.id, number),
                                CompletionResult(slot))
            for number, edge in enumerate(operation.terminator.successors)
            for slot in range(len(signatures[edge.kind].types))}


def _output_sources(report):
    return {row['source'] for row in report['outputs']}


def _public_implementation(index, details):
    report = index.protocol_obligations(details['acquisition_scope'],
        budget=QUERY_BUDGET)['connections']['families']['await']
    outcome, = tuple(row for row in report['outcomes']
        if row['source'] == details['source']
        and row['drive_outcome'] == details['drive_outcome']
        and row['advance_operation'] == details['advance_operation'])
    consumer, = tuple(row for row in outcome['consumers']
        if row['actual'] == details['extract_input']
        and row['requires_final_extraction'] is True)
    assert consumer['implementation'] is not None
    return consumer['implementation']


def _flags(report):
    for name in ('source_runtime_verified', 'runtime_identity_verified',
                 'value_identity_verified', 'transformation_authorized'):
        assert report[name] is False


def test_budget_one_keeps_all_original_parent_output_slots_and_unchecked_cursor():
    program, details = await_final_region_program(depth=2)
    index = _index(program)

    report, budget = _project(index, details, budget=1)

    assert _output_sources(report) == _raw_outputs(details['parent_call'])
    inventory = report['inventory']
    assert inventory['enumerated_outputs'] == len(report['outputs'])
    assert inventory['known_inventory_complete'] is False
    assert inventory['proofs_complete'] is False
    assert inventory['frames_total'] is None
    assert inventory['stages_total'] is None
    assert inventory['outputs_total'] is None
    assert inventory['cursor'] is not None
    assert report['cursor'] is not None
    assert report['status'] != 'DECLARED'
    assert budget.used <= 1 and budget.truncated is True
    _flags(report)


def test_late_budget_cannot_turn_a_partial_output_suffix_into_complete_proof():
    program, details = await_final_region_program(depth=2)
    index = _index(program)
    complete, complete_budget = _project(index, details)
    assert not complete_budget.truncated
    assert complete_budget.used > 1
    assert _output_sources(complete) == _raw_outputs(details['parent_call'])
    assert any(terminal['match'] is True for output in complete['outputs']
               for terminal in output['terminals'])

    limit = complete_budget.used - 1
    report, budget = _project(index, details, budget=limit)

    assert budget.used <= limit and budget.truncated is True
    assert _output_sources(report) == _output_sources(complete)
    assert report['inventory']['known_inventory_complete'] is False
    assert report['inventory']['proofs_complete'] is False
    assert report['inventory']['outputs_total'] is None
    assert report['inventory']['cursor'] is not None
    assert report['cursor'] is not None
    assert report['status'] != 'DECLARED'
    _flags(report)


def test_public_nested_region_results_and_hop_bindings_are_detached():
    program, details = await_final_region_program(depth=2)
    index = _index(program)
    first = _public_implementation(index, details)
    original = deepcopy(first)
    path = next(path for stage in first['stages'] for leg in stage['legs']
                for result in leg['results'] for path in result['paths']
                if path['hops'] and path['binding']['match'] is True)
    path['binding']['match'] = 'detached mutation'
    path['hops'][0]['binding']['match'] = 'detached hop mutation'
    first['inventory']['proofs_complete'] = 'detached inventory mutation'
    assert first != original

    repeated = _public_implementation(index, details)

    assert repeated == original
    assert index.graph == program
    _flags(repeated)


def _with_independent_reference_candidate(program, details):
    """A real unused same-type result is an alternative, not a required output."""
    leaf = details['stage_records'][-1]
    landing = leaf['landings'][ExitKind.NORMAL]
    values = {value.id: value for value in program.values}
    original_packet = values[landing.arguments[0]]
    identity = OperationID('await.final.independent.reference')
    result = ReferenceValue(ValueID('await.final.independent.reference.result'),
                            leaf['region'].id, OperationResult(identity, 0))
    input_use = Use(UseID('await.final.independent.reference.packet'),
                    original_packet.id, UseRole.PROTOCOL)
    candidate = Operation(identity, 'independent original packet consumer',
        (Behavior.COMPUTE,), (input_use,), (result.id,), effects_complete=True)
    changed_landing = replace(landing, operations=(candidate.id, *landing.operations))
    changed_region = replace(leaf['region'], blocks=tuple(
        changed_landing if block.id == landing.id else block
        for block in leaf['region'].blocks))
    changed = replace(program,
        regions=tuple(changed_region if region.id == changed_region.id else region
                      for region in program.regions),
        operations=(*program.operations, candidate), values=(*program.values, result))
    return changed, candidate, result.origin


def test_unused_same_type_output_candidate_does_not_poison_the_true_witness():
    program, details = await_final_region_program()
    before, before_budget = _project(_index(program), details)
    changed, candidate, candidate_result = _with_independent_reference_candidate(program, details)
    after, after_budget = _project(_index(changed), details)
    assert not before_budget.truncated and not after_budget.truncated
    assert _output_sources(before) == _output_sources(after)
    normal_index = next(number for number, edge in enumerate(
        details['parent_call'].terminator.successors) if edge.kind is ExitKind.NORMAL)
    required = InvokeLiteralResult(ControlEdgeReference(details['parent_call'].id, normal_index),
                                  CompletionResult(0))
    baseline, = tuple(output for output in before['outputs'] if output['source'] == required)
    actual, = tuple(output for output in after['outputs'] if output['source'] == required)
    assert actual['status'] == baseline['status']
    assert actual['status'] != 'CONTRADICTED'
    required_terminal = details['stage_records'][-1]['terminal_payloads'][ExitKind.NORMAL]
    terminal, = tuple(row for row in actual['terminals']
                      if row['terminal'] == required_terminal)
    assert terminal['match'] is True
    assert any(path['binding']['match'] is True for path in terminal['witnesses'])
    stage, = tuple(stage for stage in after['stages']
                   if getattr(stage['operation'], 'id', stage['operation']) == candidate.id)
    result, = tuple(result for leg in stage['legs'] for result in leg['results']
                    if result['source'] == candidate_result)
    assert any(path['binding']['match'] is False for path in result['paths'])
    _flags(after)
