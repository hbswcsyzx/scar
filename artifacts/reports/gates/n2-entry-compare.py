"""Compare two persisted automatic inventories without importing either target."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path


def load(path):
    with gzip.open(path, 'rt') as stream:
        return json.load(stream)


def wire(value):
    return value['wire']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('before', type=Path)
    parser.add_argument('after', type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    before, after = load(args.before), load(args.after)
    old_paths = {f['snapshot']['path'] for f in before['discovery']['files']}
    new_paths = {f['snapshot']['path'] for f in after['discovery']['files']}
    bodies = {wire(b['definition']): b for f in after['files'] for b in f['bodies']}
    runtime = after['runtime_scope']
    anchors = {wire(a['definition']): a for a in runtime['definition_index']}
    last_gaps, observed_status, observed_deferred = Counter(), Counter(), Counter()
    observed_boundaries = []
    linked_cores = []
    for body in bodies.values():
        if body['status'] == 'UNSUPPORTED':
            gaps = body['metadata']['gaps']
            last = gaps[-1] if gaps else {'kind': 'MISSING', 'detail': 'no diagnostic'}
            last_gaps[(last['kind'], last['detail'])] += 1
    for anchor in anchors.values():
        body = bodies.get(wire(anchor['definition']))
        status = body['status'] if body else 'NO_BODY_INVENTORY'
        observed_status[status] += 1
        if body and status == 'NOT_ATTEMPTED':
            observed_deferred[body['reason']] += 1
        if body and status != 'LOWERED_WITH_GAPS':
            observed_boundaries.append({'definition': anchor['definition'],
                                       'path': anchor['source_snapshot']['path'],
                                       'qualname': anchor['qualname'], 'status': status,
                                       'reason': body['reason'],
                                       'final_gap': body['metadata']['gaps'][-1]
                                       if body.get('metadata') and body['metadata']['gaps'] else None})
        if anchor['core_region']:
            bindings = [b for b in runtime['bindings']
                        if anchor['definition'] in b['candidate_definitions']]
            linked_cores.append({'definition': anchor, 'body_status': status,
                                 'code_statuses': [b['status'] for b in bindings],
                                 'observation_indices': [b['observation_index'] for b in bindings]})
    report = {
        'schema': 'scar.inventory-comparison',
        'inputs': [{'path': str(path), 'compressed_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
                   for path in (args.before, args.after)],
        'before_summary': before['summary'], 'after_summary': after['summary'],
        'source_paths_added': sorted(new_paths - old_paths),
        'source_paths_removed': sorted(old_paths - new_paths),
        'observed_source_definition_body_status': dict(sorted(observed_status.items())),
        'observed_not_attempted_reasons': dict(sorted(observed_deferred.items())),
        'observed_definition_boundaries': observed_boundaries,
        'observed_core_links': linked_cores,
        'unsupported_body_final_diagnostics': [
            {'kind': kind, 'detail': detail, 'count': count}
            for (kind, detail), count in last_gaps.most_common()],
        'notes': [
            'Last diagnostic is the current first blocking lowering boundary, not all missing rules.',
            'Source definition index includes unverified filename/qualname candidates, not proven runtime callees.',
            'Core links are structural source links, not a proof of code, inputs, effects or optimization.',
            'Input scope grows automatically from observations; coverage denominators differ between reports.',
            'No target executed; no tensor payload or source graph patched by this script.',
        ],
        'target_executed': False, 'transformation_authorized': False,
    }
    args.out.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k:v for k,v in report.items() if k not in
                      ('before_summary','after_summary','observed_core_links','observed_definition_boundaries')}, indent=2))


if __name__ == '__main__':
    main()
