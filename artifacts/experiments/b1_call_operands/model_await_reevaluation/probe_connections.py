"""Source diagnosis: inspect contexts prepared by normal validation itself."""
from unittest.mock import patch
from scar.ir.program.validation import validate
from scar.ir.program.protocol_connection_flow import ConnectionContext
from scar.ir.program.protocol_await import await_connections
from scar.ir.program.queries import ProgramIndex
from tests.unit.test_execution_await_source_visits import _source_visit_program
from tests.unit.test_execution_await_pipeline_reexecution import _pipeline_program

program, static = _source_visit_program('earlier')
context = ConnectionContext(program, index=ProgramIndex(program))
report = await_connections(context)
print('EARLIER', len(report['jobs']))
for job in report['jobs']:
    print('JOB', job['source'], job['advance'], job.get('input_guard'),
          job.get('choices'), None if job['binding'] is None else job['binding']['match'])

for kind in ('self', 'general', 'wrapper'):
    program, static = _pipeline_program(kind, False, False)
    contexts = []
    original = ConnectionContext.__init__
    def capture(self, *args, **kwargs):
        original(self, *args, **kwargs)
        contexts.append(self)
    with patch.object(ConnectionContext, '__init__', capture):
        issues = validate(program)
    context, = tuple(row for row in contexts if row.graph is program)
    report = await_connections(context)
    print('PIPELINE', kind, 'ISSUES', len(issues))
    for link in report['body_links']:
        if not any(row['match'] is False for row in link['bindings']):
            continue
        job = link['job']
        print('LINK', link['record'].advance, job['input_guard'], job['choices'])
        for row in link['bindings']:
            if row['match'] is False:
                print('BIND FALSE', row.get('gaps'),
                      tuple((route.get('source'), route.get('actual'), route.get('choices'))
                            for route in row['routes']))
