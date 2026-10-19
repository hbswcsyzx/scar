"""Inspect the exact failing original source/terminal/own-result boundary."""
import json
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.protocol_connection_flow import ConnectionContext
from scar.ir.program.protocol_await import _result_copy
from scar.ir.program.await_outcome_flow import required_choices, selected
from tests.fixtures.program_await_cleanup_final_graphs import await_cleanup_final_program
from tests.fixtures.program_await_wrapper_final_graphs import await_wrapper_final_program


def binding(row):
    return {key: row.get(key) for key in ('match', 'gaps', 'projection', 'routes')}


for name, fixture, kwargs, scope in (
        ('wrapper', await_wrapper_final_program, {}, 'construction_scope'),
        ('cleanup-raise', await_cleanup_final_program, {'body_raised': True}, 'acquisition_scope')):
    program, details = fixture(**kwargs)
    index = ProgramIndex(program)
    report = index.protocol_obligations(details[scope], budget=1048576)['connections']['families']['await']
    row, = tuple(row for row in report['outcomes']
        if row['source'] == details['source']
        and row['advance_operation'] == details['advance_operation']
        and row['drive_outcome'] == details['drive_outcome'])
    print(name, 'expected', details['extract_input'])
    print('OUTCOME', row['kind'], row['status'], row['gaps'], row['choices'])
    for leg in row['conversion_legs']:
        print('CONVERSION', leg['operation'], leg['role'], binding(leg['input_binding']), leg['gaps'])
        for terminal in leg['terminals']:
            print('TERMINAL', terminal['terminal'], terminal['packet'], binding(terminal['binding']),
                  binding(terminal.get('delivery_binding', {})))
    for leg in row['advance_legs']:
        print('ADVANCE', leg['kind'], leg['own_result'], leg['status'], leg['gaps'],
              binding(leg.get('delivery_binding', {})))
        for alternative in leg.get('alternatives', ()):
            print('ALTERNATIVE', repr(alternative)[:1500])
    for consumer in row['consumers']:
        print('CONSUMER', consumer['actual'], consumer['requires_final_extraction'],
              binding(consumer['binding']), consumer['gaps'])
    if name == 'cleanup-raise':
        ctx = ConnectionContext(program, index=index)
        source = row['payload']
        required, complete = required_choices(ctx, source)
        print('SOURCE', source, ctx.port(source), 'PREFIX', complete, required)
        for leg in row['advance_legs']:
            choices = selected(ctx, row['choices'], required, leg['edge'])
            print('DIRECT', leg['own_result'], ctx.port(leg['own_result']),
                  binding(_result_copy(ctx, source, leg['own_result'], choices)))
