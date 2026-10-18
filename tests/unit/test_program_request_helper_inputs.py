"""Raw/input provenance must cross exact original calls without fake RAW args."""
import pytest

from scar.ir.program.control import ProtocolValueKind
from scar.ir.program.model import ProtocolValue
from scar.ir.program.queries import ProgramIndex
from tests.fixtures.program_request_helper_graphs import helper_request_program


@pytest.mark.parametrize('arity', (1, 2, 3))
@pytest.mark.parametrize('depth', (1, 2))
def test_request_operands_reach_reference_only_helpers_through_the_exact_call_context(arity, depth):
    graph, details = helper_request_program(arity=arity, depth=depth)
    index = ProgramIndex(graph)
    for region in graph.regions[1:]:
        assert not any(isinstance(value, ProtocolValue) and value.region == region.id
                       and value.protocol is ProtocolValueKind.RAW_DRIVER_REQUEST for value in graph.values)
    for ordinal, target in enumerate(details['inputs']):
        report = index.request_input_binding(details['raw']['left'], target, ordinal, budget=50000)
        assert len(report['bindings']) == 1, report
        binding, = report['bindings']
        assert binding['ordinal'] == ordinal
        assert binding['caller_context'][0][0] == details['calls']['left'].id
        assert len(binding['caller_context']) == depth
        assert binding['raw_consumer_forward'] is None
        assert binding['source_runtime_verified'] is binding['transformation_authorized'] is False


def test_equal_none_from_another_ordinal_cannot_supply_the_helper_input():
    graph, details = helper_request_program()
    index = ProgramIndex(graph)
    report = index.request_input_binding(details['raw']['left'], details['inputs'][1], 0)
    assert report['bindings'] == ()


def test_pack_created_after_the_helper_call_is_not_a_current_request_source():
    graph, details = helper_request_program(late_pack=True)
    index = ProgramIndex(graph)
    report = index.request_input_binding(details['raw']['left'], details['inputs'][0], 0)
    assert report['bindings'] == ()


def test_same_original_operands_at_two_calls_keep_both_static_contexts_without_claiming_request_identity():
    graph, details = helper_request_program(shared_operands=True)
    index = ProgramIndex(graph)
    report = index.request_input_binding(details['raw']['left'], details['inputs'][0], 0)
    assert {binding['caller_context'][0][0] for binding in report['bindings']} == {
        details['calls']['left'].id, details['calls']['right'].id}
    assert report['caller_scope_complete'] is False
    assert report['source_runtime_verified'] is report['runtime_identity_verified'] is False


def test_helper_query_reuses_the_prepared_index_and_reports_real_truncation(monkeypatch):
    graph, details = helper_request_program(depth=2)
    index = ProgramIndex(graph)
    def no_revalidation(*args, **kwargs):
        raise AssertionError('the prepared helper query must not rebuild ProgramIndex')
    monkeypatch.setattr(ProgramIndex, '__init__', no_revalidation)
    limited = index.request_input_binding(details['raw']['left'], details['inputs'][0], budget=1)
    assert limited['status'] == 'TRUNCATED' and limited['cursor']
    assert limited['bindings'] == () and limited['budget']['used'] == 1
    report = index.request_input_binding(details['raw']['left'], details['inputs'][0], budget=50000)
    assert report['bindings'] and report['transformation_authorized'] is False
