import json
from dataclasses import replace
from scar.ir.program.validation import validate
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.protocol_connection_flow import ConnectionContext
from scar.ir.program.protocol_continuations import continuation_connections
from scar.ir.execution.validity_budget import ValidityBudget
from tests.fixtures.program_continuation_graphs import continuation_initial_loop_program

graph, details = continuation_initial_loop_program()
issues = validate(graph)
print('FULL_ISSUES', [(i.code, i.path, i.message) for i in issues])
keys = {(r.scope, r.clause, r.operation, r.slot) for r in graph.protocol_operations}
for r in graph.protocol_result_consumers:
    key = (r.site.scope, r.site.clause, r.site.operation, r.site.slot)
    print('RESULT_CONSUMER', repr(r), 'SITE_EXISTS', key in keys)
index = ProgramIndex(graph)
ctx = ConnectionContext(graph, index=index, budget=ValidityBudget(131072))
view = continuation_connections(ctx)
print('CONTINUATION_ISSUES', view['issues'])
print('CONTINUATION_GAPS', view['gaps'])
