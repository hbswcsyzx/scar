"""Inspect failed static target receipts using validation's own contexts."""
from unittest.mock import patch
from scar.ir.program.validation import validate
from scar.ir.program.protocol_connection_flow import ConnectionContext
from scar.ir.program.protocol_await import await_connections
from scar.ir.program.copy_flow import inventory_flow
from tests.unit.test_execution_await_source_visits import _source_visit_program
from tests.unit.test_execution_await_pipeline_reexecution import _pipeline_program

for name, program in (('earlier', _source_visit_program('earlier')[0]),
                      ('pipeline', _pipeline_program('self', False, False)[0])):
    contexts = []
    original = ConnectionContext.__init__
    def capture(self, *args, **kwargs):
        original(self, *args, **kwargs)
        contexts.append(self)
    with patch.object(ConnectionContext, '__init__', capture):
        issues = validate(program)
    context, = tuple(row for row in contexts if row.graph is program)
    report = await_connections(context)
    print(name, 'ISSUES', len(issues))
    for row in report['outcomes']:
        if row['kind'] != 'RETURN_COMPLETION':
            continue
        print('OUTCOME', row['input_guard'], len(row['conversion_legs']), len(row['consumers']))
        for leg in row['conversion_legs']:
            print('CONVERSION', leg['role'], 'TERMINALS', len(leg['terminals']))
        for consumer in row['consumers']:
            for leg in consumer['legs']:
                for target, binding in zip(leg['targets'], leg['bindings']):
                    if binding['match'] is False:
                        membership = inventory_flow(context, leg['own_result'], leg['choices'])
                        print('FALSE', leg['own_result'], target, 'CHOICES', leg['choices'],
                              'CONDITIONAL', membership['conditional'], 'BEFORE NONE', membership['before'] is None,
                              'LOCAL', binding)
