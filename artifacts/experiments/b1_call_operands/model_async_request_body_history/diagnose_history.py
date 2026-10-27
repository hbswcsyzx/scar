"""One finite public-query diagnosis on the frozen prior supplied capture."""
import hashlib
import json
from pathlib import Path
import sys

from scripts.run_gate import fingerprint
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.validation import validate
from tests.fixtures.execution_async_finished_requests_graphs import async_finished_requests_execution

HERE = Path(__file__).resolve().parent


def pair(row):
    return {'match': row['match'], 'gaps': [str(item) for item in row.get('gaps', ())],
            'support_count': len(row.get('support', ())),
            'conditional_native_projection': row.get('conditional_native_projection', False)}


def chain(row):
    return None if row is None else {'supported': row['supported'],
        'gaps': [str(item) for item in row['gaps']], 'call_count': len(row['calls'])}


def support(row):
    if row is None:
        return None
    return {'supported': row['supported'], 'gaps': [str(item) for item in row['gaps']],
        'creation_binding': pair(row['creation_binding']),
        'owned_supported': row['owned_ports']['supported'],
        'driver_chain': chain(row['driver_chain']),
        'ports': [{'kind': item['kind'], 'match': item['binding']['match']}
                  for item in row['ports']]}


before, sources = fingerprint()
program, model, details = async_finished_requests_execution(terminal='return', request='throw',
                                                           retry=True, instances=2)
validation = validate(model, program)
assert validation.valid, validation.issues
index = ExecutionIndex(model, program)
example = details['instances'][0]
read = example['finished_requests'][0]['body_predicate']
view = index.body_state_history(read, budget=1048576)
rows = []
for row in view['terminal_candidates']:
    rows.append({'commit': str(row['commit'].operation), 'source': str(row['source'].id),
        'expected_bool': row['expected_bool'], 'post_established': row['post_established'],
        'status': row['status'], 'gaps': list(row['gaps']),
        'subject_binding': pair(row['subject_binding']),
        'source_subject_binding': None if row.get('source_subject_binding') is None else pair(row['source_subject_binding']),
        'drive_support': support(row['drive_support']),
        'source_chain': chain(row['source_chain']), 'read_chain': chain(row['read_chain']),
        'has_terminal_route': bool(row['terminal_route']),
        'content_preserved': row['content_preservation']['preserved']})
after, final = fingerprint()
assert before == after and sources == final
record = {'base_revision': '0bf37d2a422f51eec2955fb44611760ef75d868e',
    'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'python': sys.version, 'executable': sys.executable,
    'source_sha256_before': before, 'source_sha256_after': after, 'sources': sources,
    'observed_branch': view['observed_branch'], 'expected_bool': view['expected_bool'],
    'status': view['status'], 'gaps': list(view['gaps']), 'budget': view['budget'],
    'terminal_candidates': rows, 'read': str(read),
    'drive_sources': len(view['drive_inventory']), 'commit_sources': len(view['commit_inventory']),
    'new_detector': False, 'new_backend': False, 'native_target_executions': 0,
    'source_runtime_verified': False, 'transformation_authorized': False}
out = HERE / 'baseline-diagnosis.json'
assert not out.exists()
out.write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps({key: value for key, value in record.items() if key != 'sources'}, indent=2))
