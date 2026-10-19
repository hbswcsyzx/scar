"""Inspect exact current consumers versus conditional semantic requirements."""
from scar.ir.execution.query import ExecutionIndex
from tests.unit.test_execution_await_source_visits import _source_visit_execution, _BUDGET
from tests.unit.test_execution_await_pipeline_reexecution import _pipeline_capture, _index

def show(report, advances):
    for row in report['outcomes']:
        for actual in row['occurrences']:
            if actual['advance'].id not in advances or actual['selected'] is not True:
                continue
            definition = row['definition']
            print('ACTUAL', actual['advance'].id, definition['input_guard'], actual['selected'],
                  'GAPS', definition['gaps'])
            for consumer in actual['consumers']:
                own = consumer['definition']
                print('CONSUMER', own['actual'], 'REQUIRES', own['requires_final_extraction'],
                      'FINALROWS', len(own['final_rows']), 'SELECTED', consumer['selected'],
                      'MATCH', consumer['binding']['match'],
                      'IMPLEMENTATION', None if consumer['implementation'] is None else
                          consumer['implementation']['status'], 'GAPS', consumer['gaps'])
            print('DEFINITION CONSUMERS', len(definition['consumers']))

program, model, details = _source_visit_execution(iterator_origin='earlier')
report = ExecutionIndex(model, program).await_body_links(details['static']['acquisition_scope'], budget=_BUDGET)
print('EARLIER')
show(report, {details['advance']})
for raised in (False, True):
    program, model, details = _pipeline_capture('self', False, raised)
    report = _index(program, model, details).await_body_links(details['static']['acquisition_scope'], budget=_BUDGET)
    print('PIPELINE TWO RAISED', raised)
    show(report, {row['advance'] for row in details['rounds']})
