"""Observe finite reported residuals without executing target code."""
import ast
import hashlib
import json
from pathlib import Path

from scripts.run_gate import fingerprint
from scar.ir.program.protocol_connection_flow import ConnectionContext
from scar.ir.program.protocol_packet_routes import completion_continuations
from scar.ir.program.protocols import DriveResult
from scar.ir.program.queries import ProgramIndex
from scar.ir.execution.validity_budget import ValidityBudget
from tests.fixtures.program_async_connections import async_driver_program

before, sources = fingerprint()
text = 'pass  # type: int\n'
observations = {}
for label, action in (
    ('ordinary_compile', lambda: compile(text, 'type-comment', 'exec', dont_inherit=True)),
    ('ordinary_ast', lambda: ast.parse(text)),
    ('type_comment_ast', lambda: ast.parse(text, type_comments=True))):
    try:
        action()
    except SyntaxError as error:
        observations[label] = {'accepted': False, 'message': error.msg}
    else:
        observations[label] = {'accepted': True}
program, details = async_driver_program(target='packet', helper=True)
index = ProgramIndex(program)
ctx = ConnectionContext(program, index=index, budget=ValidityBudget(262144))
report = completion_continuations(ctx, DriveResult(details['outcome'], 0), cross_resume=False)
rows = []
for row in report['terminals']:
    rows.append({'terminal': repr(row['terminal']), 'root_source': repr(row['root_source']),
        'current_source': repr(row['current_source']), 'match': row['binding']['match']})
after, final = fingerprint()
assert before == after and sources == final
result = {'source_sha256_before': before, 'source_sha256_after': after, 'sources': sources,
    'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'type_comment_text': text, 'type_comment_observations': observations,
    'completion': {'known_inventory_complete': report['known_inventory_complete'],
                   'gaps': repr(report['gaps']), 'terminals': rows},
    'target_bodies_executed': 0, 'tests_started': 0, 'transformation_authorized': False}
Path(__file__).with_name('residual-probe.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({key: value for key, value in result.items() if key != 'sources'}, indent=2))
