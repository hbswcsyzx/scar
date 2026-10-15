"""Compare automatic source interfaces without executing or naming a target."""
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


def first_blocker(body):
    gaps = body['metadata']['gaps'] if body and body.get('metadata') else ()
    return gaps[-1] if gaps else None


def main():
    p = argparse.ArgumentParser()
    p.add_argument('before', type=Path)
    p.add_argument('after', type=Path)
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    old, new = load(args.before), load(args.after)
    previous = {wire(b['definition']): b for f in old['files'] for b in f['bodies']}
    current = {wire(b['definition']): b for f in new['files'] for b in f['bodies']}
    anchors = {wire(a['definition']): a for a in new['runtime_scope']['definition_index']}
    observed = {wire(e['definition']) for e in old['expansion']['entries'] if e['kind'] == 'OBSERVED_CODE'}
    transitions = []
    for key in sorted(observed):
        a, b = previous[key], current[key]
        transitions.append({'definition': key, 'source': anchors[key]['source'],
            'qualname': anchors[key]['qualname'], 'before': a['status'], 'after': b['status'],
            'before_blocker': first_blocker(a), 'after_blocker': first_blocker(b),
            'reason': b['reason']})
    # A legacy generic diagnostic, not a workload identifier or optimization rule.
    signature_rows = [row for row in transitions if row['before_blocker'] and
        row['before_blocker']['detail'] == 'defaults, decorators, async and variadic/keyword-only interfaces need explicit binding rules']
    cores = []
    for key, anchor in anchors.items():
        if anchor['core_region'] is not None:
            links = [b for b in new['runtime_scope']['bindings'] if anchor['definition'] in b['candidate_definitions']]
            cores.append({'definition': key, 'qualname': anchor['qualname'],
                          'source': anchor['source'], 'code_statuses': [b['status'] for b in links]})
    overlay = new['interfaces']
    actuals = [a for b in overlay['bindings'] for a in b['arguments']]
    report = {
        'schema': 'scar.function-interface-comparison',
        'inputs': [{'path':str(path), 'compressed_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
                   for path in (args.before,args.after)],
        'before_summary': old['summary'], 'after_summary': new['summary'],
        'same_source_snapshots': old['discovery'] == new['discovery'],
        'same_runtime_raw_evidence': old['runtime_scope']['trace']['manifest'] == new['runtime_scope']['trace']['manifest'],
        'same_inventory_budget': old['budget'] == new['budget'],
        'observed_function_transitions': transitions,
        'observed_after_statuses': dict(Counter(row['after'] for row in transitions)),
        'previous_signature_blocker_transitions': signature_rows,
        'previous_signature_blocker_after_statuses': dict(Counter(row['after'] for row in signature_rows)),
        'observed_core_links': cores,
        'core_links_with_any_exact_code_witness': sum('VERIFIED' in row['code_statuses'] for row in cores),
        'bound_formal_ports': sum(len(b['parameters']) for b in overlay['bodies']),
        'binding_plan_actuals_with_core_use': sum(a['use'] is not None for a in actuals),
        'binding_plan_actuals': len(actuals),
        'binding_issues': dict(Counter(i['kind'] for b in overlay['bindings'] for i in b['issues'])),
        'default_state_routes': sum(r['origin'] == 'DEFAULT_STATE' for b in overlay['bindings'] for r in b['routes']),
        'target_executed':False, 'whole_program_model_established':False,
        'live_call_binding_established':False, 'transformation_authorized':False,
        'notes':[
            'Observed definition candidates are not necessarily verified runtime callable targets.',
            'A removed signature blocker can expose another unsupported operation; only the current first blocker is counted.',
            'Conditional formal routes do not establish function state, dispatch, binding effects or completion mapping.',
            'Counts are bounded analysis coverage, not transformation or workload speedup.',
        ],
    }
    args.out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in
        ('before_summary','after_summary','observed_function_transitions','previous_signature_blocker_transitions','observed_core_links')},indent=2))


if __name__ == '__main__':
    main()
