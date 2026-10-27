"""Find the exact unproved relation reported as a midpoint contradiction."""
from scar.ir.execution.query import ExecutionIndex
from tests.unit.test_execution_await_source_visits import _source_visit_execution, _BUDGET

program, model, details = _source_visit_execution(iterator_origin='earlier')
index = ExecutionIndex(model, program)
scope = details['static']['acquisition_scope']
complete = index.await_body_links(scope, budget=_BUDGET)
cost = complete['budget']['used']
print('FULL COST', cost)
for limit in (1, cost // 2):
    report = index.await_body_links(scope, budget=limit)
    print('LIMIT', limit, report['status'], report['budget'])
    print('ISSUES', report['issues'])
    def scan(row, path='root'):
        if type(row) is dict:
            if row.get('match') is False:
                print('FALSE', path, row.get('gaps'), row.get('source'), row.get('actual'))
            for key, child in row.items():
                if key not in ('definition', 'support', 'compatibility', 'preparation'):
                    scan(child, path + '.' + key)
        elif type(row) in (tuple, list):
            for slot, child in enumerate(row):
                scan(child, path + f'[{slot}]')
    scan(report)
