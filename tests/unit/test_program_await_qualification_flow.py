"""Native qualification constrains its own branch, preserving both paths."""
from dataclasses import replace

from scar.ir.program.model import TerminatorKind
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.resumption import ResumableKind
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_await_qualification_graphs import (
    bypass_qualification_program, predicate_literal_program, qualified_general_program,
    unknown_general_program,
    unqualified_general_program, wrong_bool_general_program,
)


def _core_valid(graph):
    require_valid(replace(graph, protocol_scopes=(), protocol_operations=(),
        protocol_call_inputs=(), protocol_result_consumers=(), protocol_bindings=()))


def _qualification_report(graph, details, *, index=None):
    index = ProgramIndex(graph) if index is None else index
    report = index.protocol_obligations(
        details['acquisition_scope'], budget=131072)['connections']['families']['await']
    qualification, = tuple(view for view in report['qualifications']
                           if view['record'] == details['qualification_row'])
    return report, qualification['feasibility']


def test_known_bad_candidate_keeps_complete_program_and_infeasible_acceptance():
    graph, details = qualified_general_program()
    require_valid(graph)
    index = ProgramIndex(graph)
    report, feasibility = _qualification_report(graph, details, index=index)
    assert feasibility['record'] == details['qualification_row']
    assert feasibility['acceptance'] is False
    assert feasibility['known_inventory_complete'] is True
    assert feasibility['cases']
    assert all(case['accepts'] is False for case in feasibility['cases'])
    assert feasibility['bool_binding']['match'] is True
    branch = details['qualification_branch']
    assert branch.terminator.kind is TerminatorKind.BRANCH
    assert len(branch.terminator.successors) == 2
    assert any(job['advance'] is not None for job in report['jobs'])
    assert feasibility['source_runtime_verified'] is False
    assert feasibility['transformation_authorized'] is False
    feasibility['acceptance'] = True
    feasibility['cases'][0]['accepts'] = True
    _, repeated = _qualification_report(graph, details, index=index)
    assert repeated['acceptance'] is False
    assert all(case['accepts'] is False for case in repeated['cases'])


def test_generator_candidate_keeps_the_same_check_and_can_accept():
    graph, details = qualified_general_program(result_kind=ResumableKind.GENERATOR)
    require_valid(graph)
    _, feasibility = _qualification_report(graph, details)
    assert feasibility['acceptance'] is True
    assert feasibility['cases'] and all(case['accepts'] is True for case in feasibility['cases'])
    assert feasibility['bool_binding']['match'] is True


def test_untyped_check_cannot_qualify_a_known_bad_general_return():
    graph, details = unqualified_general_program()
    _core_valid(graph)
    assert details['qualification'] in graph.operations
    assert details['call'] in graph.operations
    assert details['qualification_row'] not in graph.protocol_operations
    assert 'protocol_await_return_qualification' in {issue.code for issue in validate(graph)}


def test_an_unrelated_bool_cannot_supply_the_qualification_branch():
    graph, _ = wrong_bool_general_program()
    _core_valid(graph)
    assert 'protocol_await_qualification_branch' in {issue.code for issue in validate(graph)}


def test_a_side_check_cannot_qualify_the_path_that_bypasses_it():
    graph, details = bypass_qualification_program()
    _core_valid(graph)
    assert details['qualification_row'] in graph.protocol_operations
    assert details['bypass'].terminator.successors[0].block == (
        details['qualification_branch'].terminator.successors[0].block)
    assert 'protocol_await_return_qualification' in {issue.code for issue in validate(graph)}


def test_own_bool_literal_cannot_contradict_the_known_predicate_result():
    graph, details = predicate_literal_program()
    _core_valid(graph)
    assert details['predicate_literal'].site == details['qualification_row'].contract.result
    assert 'protocol_await_predicate_result' in {issue.code for issue in validate(graph)}


def test_unknown_method_result_does_not_make_its_accepting_path_infeasible():
    graph, details = unknown_general_program()
    require_valid(graph)
    assert details['helper_call'] in graph.operations
    assert details['helper_create'] not in graph.resumable_creates
    report, feasibility = _qualification_report(graph, details)
    assert feasibility['acceptance'] is None
    assert feasibility['cases']
    assert all(case['accepts'] is None for case in feasibility['cases'])
    assert feasibility['bool_binding']['match'] is True
    assert any(job['advance'] is not None for job in report['jobs'])
    assert feasibility['source_runtime_verified'] is False
    assert feasibility['transformation_authorized'] is False
