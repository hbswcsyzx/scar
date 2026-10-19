"""Inspect dynamic NORMAL child return paths without upgrading identity gaps."""
from scar.ir.execution.query import ExecutionIndex
from tests.fixtures.execution_await_wrapper_final_graphs import await_wrapper_final_execution

program, model, details = await_wrapper_final_execution(zero_cut=True, depth=1, instances=1)
index = ExecutionIndex(model, program, evidence_graphs=details['evidence_graphs'])
report = index.await_body_links(details['static']['construction_scope'], budget=1048576)
row, = tuple(row for row in report['outcomes']
    if row['definition']['drive_outcome'] == details['drive_outcome']
    and row['definition']['advance_operation'] == details['static']['advance_operation'])
example = details['instances'][0]
occurrence, = tuple(row for row in row['occurrences'] if row['advance'] is not None
    and row['advance'].id == example['advance'] and row['drive'] is not None
    and row['drive'].id == example['body_drives'][-1].drive)
consumer, = tuple(row for row in occurrence['consumers']
    if row['definition']['actual'] == details['static']['extract_input']
    and row['definition']['requires_final_extraction'] is True)
implementation = consumer['implementation']
print('BUDGET', report.get('budget'))
for stage in implementation['stages']:
    print('STAGE', stage['occurrence'].operation, stage['input_support']['match'])
    for leg in stage['legs']:
        if leg['selected'] is not True:
            continue
        for result in leg['results']:
            print('RESULT', result['definition']['slot'], result['value'].id)
            for path in result['paths']:
                print('PATH', path['selected'], path['status'], path['gaps'],
                      'binding', path['binding']['match'], 'contribution', path['contribution']['match'])
                for hop in path['hops']:
                    print('HOP', hop['selected'], hop['status'], hop['gaps'],
                          'binding', hop['binding']['match'], hop['binding']['gaps'],
                          'post', hop['post_binding']['match'], hop['post_binding']['gaps'])
                for target in path['targets']:
                    print('TARGET', target['selected'], target['status'], target['gaps'],
                          target['binding']['match'], target['binding']['gaps'])
print('OUTPUTS', [(row['slot'], row['status'],
    [(terminal['selected'], terminal['match'], terminal['gaps']) for terminal in row['terminals']])
    for row in implementation['outputs'] if row['selected'] is True])
