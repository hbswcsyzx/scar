"""Read the selected leaf paths without asserting acceptance."""
from tests.unit.test_execution_await_pipeline_reexecution import (
    _pipeline_capture, _consumer, _BUDGET,
)
from scar.ir.execution.query import ExecutionIndex

program, model, details = _pipeline_capture()
static = details['static']
index = ExecutionIndex(model, program)
report = index.await_body_links(static['acquisition_scope'], budget=_BUDGET)
for example in details['rounds']:
    _, consumer = _consumer(report, static, example)
    print('ROUND', example['number'], example['kind'])
    implementation = consumer['implementation']
    for stage in implementation['stages']:
        if stage['occurrence'].operation != static['primitive'].id:
            continue
        for leg in stage['legs']:
            if leg['selected'] is not True:
                continue
            for result in leg['results']:
                print('SLOT', result['definition']['slot'])
                for path in result['paths']:
                    print('PATH', path['selected'], path['binding'],
                          'CONTRIBUTION', path['contribution']['match'])
                    for target in path['targets']:
                        print('TARGET', target['definition'], target['selected'],
                              target['status'], target['binding'])
