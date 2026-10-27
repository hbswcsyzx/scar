"""Inspect the exact unresolved static tuple; no tests or source mutation."""
import hashlib
import json
from pathlib import Path
import sys

from scar.ir.execution.validity_budget import ValidityBudget
from scar.ir.program.protocol_connection_flow import ConnectionContext
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.session_occupancy import occupancy_view
from scripts.run_gate import fingerprint
from tests.fixtures.program_async_competition_graphs import async_competition_program

before, sources = fingerprint()
graph, details = async_competition_program()
ctx = ConnectionContext(graph, index=ProgramIndex(graph), budget=ValidityBudget(32768))
view = occupancy_view(ctx, details['occupancy']['row'])


def binding(value):
    return {key: value.get(key) for key in ('match', 'gaps', 'cursor')}


rows = []
for row in view['associations']:
    rows.append({key: binding(row[key]) for key in
                 ('receiver', 'body_binding', 'source_binding', 'binding')})
    rows[-1].update(
        state_support=[{'binding': binding(value['binding']),
                        'keys': sorted(value)} for value in row['state_support']],
        projection_bindings=[binding(value) for value in row['projection_bindings']],
        projection_contexts=[binding(value['context']) for value in row['projections']],
        gaps=row['gaps'])
after, final_sources = fingerprint()
assert before == after and sources == final_sources
record = {'source_sha256_before': before, 'source_sha256_after': after,
    'source_count': len(sources), 'tests_started': 0,
    'command': [sys.executable, str(Path(__file__).relative_to(Path.cwd()))],
    'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'view': {'body_binding': binding(view['body_binding']), 'binding': binding(view['binding']),
             'gaps': view['gaps'], 'budget': view['budget']}, 'associations': rows}
destination = Path(__file__).with_name('static-tuple-probe.json')
assert not destination.exists()
destination.write_text(json.dumps(record, indent=2, default=str) + '\n')
print(json.dumps(record, indent=2, default=str))
