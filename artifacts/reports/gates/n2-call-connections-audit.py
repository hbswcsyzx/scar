"""Coverage joins over an already replayed call report; no target execution."""
import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import resource
import time
from scar.ir.semantics_v2 import Opcode

p = argparse.ArgumentParser()
p.add_argument('report')
p.add_argument('inventory')
p.add_argument('out')
a = p.parse_args()
started = time.perf_counter()
with gzip.open(a.report, 'rt') as stream:
    report = json.load(stream)
with gzip.open(a.inventory, 'rt') as stream:
    inventory = json.load(stream)
model = report['analysis']['model']
wire = lambda value: value['wire'] if value is not None else None
baseline_calls = {}
definitions = {wire(definition['id']): definition for file in inventory['files']
               for definition in file['definitions']}
bodies = {wire(body['definition']): body for file in inventory['files'] for body in file['bodies']}
captured = {item['code']['key']: item['code'] for item in model['codes']}
code_links = {item['code']: item for item in model['code_links']}
for file in inventory['files']:
    for body in file['bodies']:
        if body['metadata'] is None:
            continue
        for link in body['metadata']['operation_links']:
            if link['opcode'] == Opcode.CALL.value:
                baseline_calls[wire(link['operation'])] = {'owner': wire(body['definition']),
                                                          'owner_qualname': definitions[wire(body['definition'])]['qualname'],
                                                          'source': link['source']}
observations = []
code_issues = Counter()
for link in model['code_links']:
    code_issues.update(issue['kind'] for issue in link['issues'])
for edge in model['edges']:
    for index, site in enumerate(edge['path']):
        if site['core_operation'] is not None:
            observations.append({'operation': wire(site['core_operation']), 'call': wire(site['call']),
                                 'direct': index == 0, 'invocation': edge['entry']['invocation'],
                                 'target_code': edge['entry']['code'], 'target_status': edge['target']['status'],
                                 'target_definition': wire(edge['target']['definition']),
                                 'target_body': wire(edge['target_body'])})
observed = {item['operation'] for item in observations}
joined = {item['operation'] for item in observations if item['target_body'] is not None}
identity = lambda value: tuple(value[name] for name in ('process_id', 'thread_id', 'invocation_id'))
edge_index = {identity(edge['entry']['invocation']): edge for edge in model['edges']}
runtime_bridges = []
for destination in model['edges']:
    if destination['target_body'] is None:
        continue
    cursor = destination
    chain = []
    visited = set()
    while cursor is not None and len(chain) < 128:
        key = identity(cursor['entry']['invocation'])
        if key in visited:
            raise AssertionError('verified parent cycle')
        visited.add(key)
        chain.append(cursor)
        for site in cursor['path']:
            if site['core_operation'] is not None:
                runtime_bridges.append({'core_operation': wire(site['core_operation']),
                                        'target_body': wire(destination['target_body']),
                                        'chain': [{'invocation': part['entry']['invocation'],
                                                   'target_code': part['entry']['code'],
                                                   'captured_path': [step['site'] for step in part['path']]}
                                                  for part in reversed(chain)],
                                        'intermediary_effects_established': False,
                                        'actual_formal_provenance_established': False})
        parent = (cursor['entry']['caller_invocation'] if cursor['caller_identity_verified'] else
                  cursor['entry']['ancestor_invocation'] if cursor['ancestor_identity_verified'] else None)
        cursor = edge_index.get(identity(parent)) if parent is not None else None
result = {'baseline_distinct_core_calls': len(baseline_calls),
          'observed_distinct_core_calls': len(observed),
          'core_calls_with_observed_target_body': len(joined),
          'core_calls_reaching_body_through_verified_runtime_parents': len({row['core_operation'] for row in runtime_bridges}),
          'runtime_body_bridges': runtime_bridges,
          'core_calls_without_observation': len(set(baseline_calls) - observed),
          'observed_calls_absent_from_inventory': sorted(observed - set(baseline_calls)),
          'distinct_source_call_sites': len({wire(site['call']) for edge in model['edges'] for site in edge['path']
                                              if site['call'] is not None}),
          'distinct_target_bodies': len({wire(edge['target_body']) for edge in model['edges'] if edge['target_body'] is not None}),
          'verified_code_definitions': len({wire(link['definition']) for link in model['code_links']
                                            if link['status'] == 'VERIFIED' and link['definition'] is not None}),
          'core_observation_target_statuses': dict(Counter(item['target_status'] for item in observations)),
          'code_issues': dict(code_issues),
          'reference_route_kinds': dict(Counter(route['kind'] for route in model['reference_routes'])),
          'core_target_details': [{'code': key, 'description': captured[key],
                                   'status': code_links[key]['status'],
                                   'definition': wire(code_links[key]['definition']),
                                   'issues': code_links[key]['issues'],
                                   'body_status': bodies[wire(code_links[key]['definition'])]['status']
                                                  if wire(code_links[key]['definition']) in bodies else None,
                                   'body_reason': bodies[wire(code_links[key]['definition'])]['reason']
                                                  if wire(code_links[key]['definition']) in bodies else None}
                                  for key in sorted({item['target_code'] for item in observations})],
          'operation_coverage': [{**baseline_calls[key], 'operation': key,
                                  'observation_count': sum(item['operation'] == key for item in observations),
                                  'target_codes': sorted({item['target_code'] for item in observations if item['operation'] == key}),
                                  'target_bodies': sorted({item['target_body'] for item in observations
                                                           if item['operation'] == key and item['target_body'] is not None})}
                                 for key in sorted(baseline_calls)],
          'analysis_wall_s': time.perf_counter() - started,
          'peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
          'actual_formal_provenance_established': False, 'transformation_authorized': False}
Path(a.out).write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({key: value for key, value in result.items()
                  if key not in ('operation_coverage', 'runtime_body_bridges', 'core_target_details')}))
