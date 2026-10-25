"""After root confirms terminal: summarize saved metadata, never run a producer."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]

def read(path):
    return json.loads(Path(path).read_text())

def receipt(path):
    path = Path(path)
    raw = path.read_bytes()
    return {'path': str(path.resolve()), 'bytes': len(raw), 'sha256': sha256(raw).hexdigest()}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--exit-code', type=int, required=True, help='Actual terminal exit observed by root')
    args = parser.parse_args()
    output = HERE / 'delivery01'
    output.mkdir(exist_ok=False)
    selection = read(HERE/'selection.json')
    accounting = read(HERE/'window-accounting.json')
    rows = accounting['rows']
    assert len(rows) == len(selection['keys']) == 65 and sum(row['current_calls'] for row in rows) == 1713
    assert {row['body_key'] for row in rows} == set(selection['keys'])
    terminal = {}
    index = HERE/'worker/attempts.jsonl'
    if index.exists():
        for line in index.read_text().splitlines():
            row = json.loads(line)
            assert row['body_key'] not in terminal
            terminal[row['body_key']] = row
    states, calls, kinds, details, kind_calls, detail_calls = (Counter() for _ in range(6))
    graphs, evidence = [], []
    for row in rows:
        state = row['window_status']; states[state] += 1; calls[state] += row['current_calls']
        actual = terminal.get(row['body_key'])
        record = dict(row)
        if actual:
            assert actual['status'] == state
            folder = HERE/'worker'/f"attempt-{actual['sequence']:05d}"
            record.update(sequence=actual['sequence'], result=receipt(folder/'result.json'),
                operations_emitted=actual['operations_emitted'], graph_operations=actual['graph_operations'],
                code_type_verified=actual['code_type_verified'], error=actual.get('error'))
            metadata = folder/'returned-metadata.json'
            if metadata.exists() and state == 'UNSUPPORTED':
                gaps = read(metadata)['metadata']['gaps']
                if gaps:
                    gap = gaps[-1]
                    record['producer_next_frontier'] = gap
                    kinds[gap['kind']] += 1; kind_calls[gap['kind']] += row['current_calls']
                    details[gap['detail']] += 1; detail_calls[gap['detail']] += row['current_calls']
            if state == 'SUCCEEDED':
                assert actual['program'] is not None
                path = Path(actual['program']['uri'])
                assert path.stat().st_size == actual['program']['physical_bytes']
                graphs.append({'body_key': row['body_key'], 'current_calls_weight': row['current_calls'],
                    'original_worker_reference': actual['program'], 'graph_decoded_or_revalidated': False})
        evidence.append(record)
    report = {'schema': 'scar.source-frontend-window-delivery', 'schema_version': 1,
        'actual_terminal_exit_reported_by_root': args.exit_code,
        'scope': 'saved terminal/window metadata; no source or graph replay',
        'window_bodies': 65, 'window_call_weight': 1713, 'state_counts': dict(states),
        'state_call_weights': dict(calls), 'successful_graphs_created': len(graphs),
        'graphs': graphs, 'rows': evidence,
        'producer_next_frontier_kinds': dict(kinds), 'producer_next_frontier_kind_call_weights': dict(kind_calls),
        'producer_next_frontier_details': dict(details), 'producer_next_frontier_detail_call_weights': dict(detail_calls),
        'frontier_grouping_is_saved_producer_diagnostic_not_new_syntax_inference': True,
        'static_definitions': 2217, 'retained_run_groups': 817, 'retained_run_invocations': 100438,
        'planning_snapshot_bodies': 843, 'published_source_snapshot_bodies': 846,
        'latest_complete_runtime_snapshot_bodies': 843,
        'new_graphs_formally_published': False, 'new_graphs_runtime_integrated': False,
        'whole_first_stage_established': False, 'combined_decoded_and_stored_io_accounting': 'OPEN',
        'freeze': receipt(HERE/'freeze.json'), 'entry': receipt(HERE/'run.py'),
        'gate_result': read(HERE/'result.json') if (HERE/'result.json').exists() else None,
        'gate_failure': read(HERE/'failure.json') if (HERE/'failure.json').exists() else None}
    (output/'summary.json').write_text(json.dumps(report, sort_keys=True, ensure_ascii=False, indent=2)+'\n')
    small, retained = [], []
    for path in sorted(HERE.rglob('*')):
        if not path.is_file() or path.is_relative_to(output):
            continue
        # Program payloads remain local irrespective of compressed size. Keep
        # their exact worker receipts rather than silently publishing graphs.
        if path.name == 'source-program5.json.gz' or path.stat().st_size > 1_000_000:
            retained.append({'path': str(path.relative_to(ROOT)), 'bytes': path.stat().st_size,
                'reason': 'graph payload or above small-file limit; original worker reference retained'})
        else:
            small.append({'path': str(path.relative_to(ROOT)), **{k:v for k,v in receipt(path).items() if k!='path'}})
    (output/'small-file-list.json').write_text(json.dumps({'files': small, 'local_only': retained,
        'no_git_operations_performed': True}, sort_keys=True, ensure_ascii=False, indent=2)+'\n')
    (output/'small-file-list.txt').write_text(''.join(row['path']+'\n' for row in small))
    print(json.dumps({'exit': args.exit_code, 'states': dict(states), 'call_weights': dict(calls),
        'graphs_created': len(graphs), 'small_files': len(small), 'local_payloads': len(retained)}))

if __name__ == '__main__':
    main()
