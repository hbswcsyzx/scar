"""Locate each original F19 subject gap; no source facts or runtime identities added."""
import hashlib
import json
from pathlib import Path
import sys
import time

from scripts.run_gate import fingerprint
from scar.ir.execution.query import ExecutionIndex
from tests.fixtures.execution_async_finished_requests_graphs import async_finished_requests_execution

HERE = Path(__file__).resolve().parent
OUT = HERE / 'baseline.json'
assert not OUT.exists()
before, sources = fingerprint()
start = time.monotonic()


def value(value):
    return None if value is None else value.id.wire


def binding(row):
    return None if row is None else {
        'match': row['match'], 'source': value(row['source_value']),
        'target': value(row['target_value']), 'kind': row.get('binding_kind'),
        'support_rules': [item['rule'] for item in row.get('support', ())],
        'gaps': [getattr(item, 'code', str(item)) for item in row.get('gaps', ())]}


rows = []
for terminal, request in (('return', 'throw'), ('raise', 'close')):
    graph, model, details = async_finished_requests_execution(terminal=terminal,
        request=request, retry=True, instances=1)
    example, = details['instances']
    definition = details['static']['finished_request']
    current = example['finished_requests'][0]
    index = ExecutionIndex(model, graph)
    view = index.body_state_history(current['body_predicate'], budget=2097152)
    candidate, = tuple(row for row in view['terminal_candidates']
                       if row['commit'] == definition['source_publication'])
    subject = candidate['subject_binding']
    pair = index.value_source_pair(subject['source_value'].id, subject['target_value'].id,
                                   budget=2097152)
    read_operation = next(row for row in graph.operations
                          if row.id == definition['association'].id)
    rows.append({'terminal': terminal, 'request': request,
        'expected_bool': view['expected_bool'], 'observed_branch': view['observed_branch'],
        'status': view['status'], 'budget': view['budget'],
        'original_read_inputs': [row.id.wire for row in read_operation.uses],
        'stored_read_count': len(graph.stored_value_reads),
        'stored_write_count': len(graph.stored_value_writes),
        'subject_binding': binding(subject), 'new_generic_source_binding': binding(pair),
        'source_subject_binding': binding(candidate.get('source_subject_binding')),
        'drive_supported': candidate['drive_support']['supported'],
        'drive_gaps': list(candidate['drive_support']['gaps']),
        'post_established': candidate['post_established'],
        'source_chain_supported': candidate['source_chain']['supported'],
        'read_chain_supported': candidate['read_chain']['supported'],
        'terminal_route_present': bool(candidate['terminal_route']),
        'candidate_gaps': list(candidate['gaps']),
        'all_drive_inventory_preserved': view['drive_inventory'] == graph.body_drives,
        'all_commit_inventory_preserved': view['commit_inventory'] == graph.body_outcome_commits})
    assert view['expected_bool'] is None and view['observed_branch'] is True
    assert not view['budget']['truncated']
    assert pair['match'] is None and not graph.stored_value_reads and not graph.stored_value_writes
after, final = fingerprint()
assert before == after and sources == final
record = {'base_revision': 'c02e973c151ecda8808c3cfa245339840edb9f24',
    'python': sys.version, 'source_sha256_before': before, 'source_sha256_after': after,
    'source_files': len(sources), 'sources': sources, 'cases': rows,
    'duration_seconds': time.monotonic() - start, 'native_target_executions': 0,
    'source_runtime_verified': False, 'transformation_authorized': False,
    'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
OUT.write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps({key: row for key, row in record.items() if key != 'sources'}))
