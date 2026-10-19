"""Observe existing state-binding inventory return at budget boundary."""
from unittest.mock import patch
from scar.ir.execution.query import ExecutionIndex
import scar.ir.program.await_outcome_flow as af
from tests.unit.test_execution_await_source_visits import _source_visit_execution, _BUDGET
program, model, details = _source_visit_execution(iterator_origin='earlier')
index = ExecutionIndex(model, program)
scope = details['static']['acquisition_scope']
full = index.await_body_links(scope, budget=_BUDGET)
original = af.inventory_flow

def observed(ctx, source, choices=()):
    prior = ctx._ports.get(source)
    result = original(ctx, source, choices)
    if ctx.budget.truncated:
        print('MEMBERSHIP', source, 'PREPORT', prior, 'POSTPORT', ctx._ports.get(source))
        print({key: value if key not in ('before', 'guarded_flow') else
            None if value is None else {str(op): tuple(map(str, values)) for op, values in value.items()}
            for key, value in result.items()})
    return result
with patch.object(af, 'inventory_flow', observed):
    result = index.await_body_links(scope, budget=full['budget']['used'] // 2)
print('FINAL', result['status'], result['issues'])
