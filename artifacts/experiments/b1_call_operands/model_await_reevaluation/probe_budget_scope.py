"""Inspect midpoint state receipts and their exact conditional control keys."""
from unittest.mock import patch
from scar.ir.execution.query import ExecutionIndex
from scar.ir.program.protocol_connection_flow import ConnectionContext
from tests.unit.test_execution_await_source_visits import _source_visit_execution, _BUDGET

program, model, details = _source_visit_execution(iterator_origin='earlier')
index = ExecutionIndex(model, program)
scope = details['static']['acquisition_scope']
complete = index.await_body_links(scope, budget=_BUDGET)
contexts = []
original = ConnectionContext.__init__
def capture(self, *args, **kwargs):
    original(self, *args, **kwargs)
    contexts.append(self)
with patch.object(ConnectionContext, '__init__', capture):
    report = index.await_body_links(scope, budget=complete['budget']['used'] // 2)
context = contexts[-1]
print('STATUS', report['status'], 'ISSUES', report['issues'])
print('CONTROL SCOPES')
for key, receipt in getattr(context, '_copy_inventory_scopes', {}).items():
    print(key, receipt)
for definition in context._connection_reports['await']['outcomes']:
    for consumer in definition['consumers']:
        for leg in consumer['legs']:
            for state in leg['states']:
                if state['binding']['match'] is False:
                    print('FALSE STATE', state)
                    source = state['source']
                    port = context._ports.get(source)
                    print('PORT', port, 'CHOICES', leg['choices'])
