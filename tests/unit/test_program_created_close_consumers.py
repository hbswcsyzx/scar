"""Created-close must bind its own predicate and its current None host result."""
from dataclasses import replace

from scar.ir.literals import PythonLiteral
from scar.ir.program.drivers import RawRequestKind
from scar.ir.program.model import OperationResult, TerminatorKind
from scar.ir.program.protocols import ProtocolProfile
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_generator_admission_graphs import generator_admission_program


def _program():
    graph, details = generator_admission_program(stage='created', kind=RawRequestKind.CLOSE)
    scope = next(scope for scope in graph.protocol_scopes if scope.profile is ProtocolProfile.CREATED_CLOSE_V1)
    literal = next(row for row in graph.literal_evaluations if type(row.site) is OperationResult
                   and any(value.id == details['none'] and value.origin == row.site for value in graph.values))
    return graph, details, scope, literal


def _codes(graph):
    require_valid(replace(graph, protocol_scopes=(), protocol_operations=()))
    return {issue.code for issue in validate(graph)}


def test_created_close_derived_obligation_keeps_exact_test_finish_and_none_host_consumer():
    graph, details, scope, _ = _program()
    ledger = ProgramIndex(graph).protocol_obligations(scope.id)
    clause, = ledger['scopes'][0]['obligations']
    original, = clause['original']
    assert original['test'].operation == details['created_close_test'] == scope.subject.operation
    route, = original['routes']
    assert route['finish'].operation == details['finish']
    assert route['declared_none_result'] is True
    assert original['source_runtime_verified'] is original['transformation_authorized'] is False


def test_an_explicit_non_none_content_cannot_satisfy_created_close_host_result():
    graph, _, _, literal = _program()
    changed = replace(graph, literal_evaluations=tuple(replace(row,
        literal=PythonLiteral.from_python(7, exact=True)) if row == literal else row
        for row in graph.literal_evaluations))
    assert 'protocol_close_result' in _codes(changed)


def test_host_cannot_replace_current_none_with_its_bound_generator_receiver():
    graph, details, _, _ = _program()
    finish = next(row for row in graph.no_body_finishes if row.operation == details['finish'])
    mark = next(op for op in graph.operations if op.id == finish.operation)
    owner = next(use.value for use in mark.uses if use.id == finish.instance)
    terminal = next(op for op in graph.operations if op.terminator is not None
        and op.terminator.kind is TerminatorKind.RETURN
        and any(use.value == details['none'] for use in op.uses))
    changed = replace(graph, operations=tuple(replace(op, uses=tuple(
        replace(use, value=owner) if use.value == details['none'] else use for use in op.uses))
        if op.id == terminal.id else op for op in graph.operations))
    assert 'protocol_close_result' in _codes(changed)


def test_same_region_non_predicate_site_cannot_borrow_another_created_close_test():
    graph, _, scope, literal = _program()
    bad = replace(scope, subject=replace(scope.subject, operation=literal.site.operation))
    changed = replace(graph, protocol_scopes=tuple(bad if row == scope else row for row in graph.protocol_scopes))
    assert 'protocol_created_close_site' in _codes(changed)


def test_unknown_current_result_remains_a_specific_gap_instead_of_none_success():
    graph, _, scope, literal = _program()
    changed = replace(graph, literal_evaluations=tuple(row for row in graph.literal_evaluations if row != literal))
    ledger = ProgramIndex(changed).protocol_obligations(scope.id)
    clause, = ledger['scopes'][0]['obligations']
    assert clause['status'] == 'PARTIAL'
    assert 'created_close_none_result_unproved' in clause['gaps']
    assert clause['original'][0]['routes'][0]['declared_none_result'] is None
    assert ledger['transformation_authorized'] is False
