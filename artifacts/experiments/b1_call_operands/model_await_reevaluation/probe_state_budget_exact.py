"""Read exact false state joins without changing product answers or budgets."""
from unittest.mock import patch
from scar.ir.execution.query import ExecutionIndex
import scar.ir.program.await_outcome_flow as af
from tests.unit.test_execution_await_source_visits import _source_visit_execution, _BUDGET
program, model, details = _source_visit_execution(iterator_origin='earlier')
index = ExecutionIndex(model, program)
scope = details['static']['acquisition_scope']
full = index.await_body_links(scope, budget=_BUDGET)
original = af.case_binding

def observed(ctx, source, actual, choices):
    result = original(ctx, source, actual, choices)
    if result['match'] is False:
        port = ctx._ports.get(source)
        originals = ctx.selected_edges((*ctx._returns.guards, *choices))
        key = None if port is None else (port.operation, port.phase, port.edge, originals)
        print('FALSE', 'source', source, 'actual', actual, 'port', port)
        print('BUDGET', ctx.budget.used, ctx.budget.truncated, 'key', key)
        print('SCOPE', getattr(ctx, '_copy_inventory_scopes', {}).get(key))
        print('BINDING', result)
    return result
with patch.object(af, 'case_binding', observed):
    result = index.await_body_links(scope, budget=full['budget']['used'] // 2)
print('FINAL', result['status'], result['issues'])
