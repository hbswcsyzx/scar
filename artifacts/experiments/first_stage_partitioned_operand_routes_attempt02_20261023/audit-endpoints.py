"""Check archived positive endpoints, without source replay or SCAR imports."""
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import resource
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE / 'result/analysis'
CONDITIONS = ['CAPTURE_PRODUCER_TRUSTED', 'NO_FRAME_INTERPOSITION',
    'NO_NAMESPACE_MUTATION_BETWEEN_OBSERVATION_AND_LOAD', 'OBSERVER_AND_AUDIT_NONINTERFERENCE',
    'MONITORING_DELIVERY_CONTINUITY_UNVERIFIED', 'SOURCE_CORE_EXECUTION_PRECONDITIONS',
    'FUNCTION_ENVIRONMENT_UNVERIFIED', 'CONTENTS_EFFECTS_AND_WORLD_EQUIVALENCE_UNVERIFIED']


def checked(path, declaration):
    path = Path(path)
    assert path.is_file() and not path.is_symlink()
    size = declaration['physical_bytes'] if 'physical_bytes' in declaration else declaration['bytes']
    digest = declaration['physical_sha256'] if 'physical_sha256' in declaration else declaration['sha256']
    assert path.stat().st_size == size
    assert path.stat().st_size <= 128_000_000
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == digest
    with gzip.open(path, 'rb') as stream:
        decoded = stream.read(128_000_001)
    assert len(decoded) <= 128_000_000
    assert len(decoded) == declaration['decoded_bytes']
    assert hashlib.sha256(decoded).hexdigest() == declaration['decoded_sha256']
    return decoded


def wire(value):
    return value['wire']


def main():
    started = time.perf_counter()
    manifest_path = ROOT / 'manifest.json'
    manifest_raw = manifest_path.read_bytes()
    manifest = json.loads(manifest_raw)
    header = json.loads(checked(manifest['header']['path'], manifest['header']))
    namespaces = header['source_body_access']['namespaces']
    assert len(namespaces) == 74
    bodies, formal_owners, checked_sources = {}, defaultdict(list), []
    for definition, scope in namespaces.items():
        declaration = scope['graph_locator']['artifact']
        cp = json.loads(checked(declaration['uri'], declaration))
        graph, interface = cp['graph'], cp['interface']
        assert wire(interface['definition']) == definition
        assert interface['region'] == graph['root']
        assert scope['namespace']['body']['definition'] == interface['definition']
        assert scope['namespace']['body']['source'] == cp['source']
        assert scope['namespace']['artifact']['decoded_sha256'] == declaration['decoded_sha256']
        assert scope['graph_locator']['pointer'] == '#/graph'
        operations = {wire(row['id']): row for row in graph['operations']}
        values = {wire(row['id']): row for row in graph['values']}
        uses = {}
        for operation in graph['operations']:
            for use in operation['uses']:
                assert wire(use['id']) not in uses
                uses[wire(use['id'])] = (use, operation)
        sources = {wire(link['value']): link['source'] for link in cp['metadata']['value_links']
                   if link['role'] == 'PARAMETER'}
        for parameter in interface['parameters']:
            key = wire(parameter['value'])
            assert key in values and key in sources
            formal_owners[key].append((definition, sources[key]))
        bodies[definition] = {'scope': scope, 'root': graph['root'], 'parameters': interface['parameters'],
            'operations': operations, 'values': values, 'uses': uses,
            'environments': {wire(row['id']): row for row in graph.get('environments', ())}}
        checked_sources.append(scope['graph_locator'])
    assert all(len(owners) == 1 for owners in formal_owners.values())
    counts, examples, chunks = Counter(), {}, 0
    ports = 0
    for name, table in manifest['tables'].items():
        total = 0
        for chunk in table['chunks']:
            decoded = checked(chunk['path'], chunk)
            lines = decoded.splitlines()
            assert len(lines) == chunk['rows']
            chunks += 1
            for line_number, raw in enumerate(lines, 1):
                row = json.loads(raw)
                total += 1
                if name == 'entry_parameters':
                    assert row['role'] == 'PARAMETER' and row['core_use'] is None
                    assert row['owner'] == row['observed_in']
                    owners = formal_owners[wire(row['core_value'])]
                    assert len(owners) == 1 and owners[0][1] == row['source_reference']
                elif name in ('routing.argument_routes', 'routing.completion_routes'):
                    caller, callee = bodies[wire(row['caller_definition'])], bodies[wire(row['callee_definition'])]
                    assert row['caller_region'] == caller['root'] and row['callee_region'] == callee['root']
                    operation = caller['operations'][wire(row['operation'])]
                    assert row['conditions'] == CONDITIONS
                    if name == 'routing.argument_routes':
                        use, owner = caller['uses'][wire(row['actual_use'])]
                        assert owner['id'] == operation['id'] and use['value'] == row['actual_value']
                        assert operation['invoke_arguments'][row['actual_index'] + 1] == row['actual_use']
                        assert {'slot': row['formal_slot'], 'value': row['formal_value']} in callee['parameters']
                    else:
                        assert wire(row['normal_result']) in caller['values']
                        use, returning = callee['uses'][wire(row['payload_use'])]
                        assert use['value'] == row['payload_value']
                        completion = returning['terminator']
                        assert completion['kind'] == 'RETURN' and completion['values'][0] == row['payload_use']
                        state_use, _ = callee['uses'][wire(completion['values'][1])]
                        assert state_use['value'] == row['post_world']
                elif name == 'environments.bindings':
                    body = bodies[wire(row['definition'])]
                    assert row['body_namespace'] == body['scope']['namespace'] and row['region'] == body['root']
                    environment = body['environments'][wire(row['environment'])]
                    assert environment['code_definition'] == row['definition']
                    for port in row['ports']:
                        matching = [member for member in environment['members']
                                    if member['reference'] == port['reference_port'] and member['role'] == port['role']
                                    and member['cell_slot'] == port['cell_slot'] and member['cell_position'] == port['cell_position']]
                        assert len(matching) == 1
                        ports += 1
                else:
                    continue
                counts[name] += 1
                examples.setdefault(name, {'chunk': chunk, 'line': line_number,
                    'row_sha256': hashlib.sha256(raw).hexdigest(), 'original_body_locators':
                    [bodies[wire(row[key])]['scope']['graph_locator'] for key in ('caller_definition', 'callee_definition') if key in row]})
        assert total == table['rows']
    assert dict(counts) == {'entry_parameters': 13872, 'routing.argument_routes': 27,
                           'routing.completion_routes': 27, 'environments.bindings': 3347}
    assert ports == 10087
    report = {'status': 'PASS', 'scope': 'all report chunk receipts/counts and positive original endpoint IDs only',
        'original_cp_receipts': len(checked_sources), 'report_chunks_checked': chunks,
        'checked_records': dict(counts), 'environment_ports_checked': ports,
        'manifest_sha256': hashlib.sha256(manifest_raw).hexdigest(), 'manifest_bytes': len(manifest_raw),
        'original_body_locators': checked_sources, 'examples': examples,
        'canonical_graph_semantics_revalidated': False, 'full_report_codec_replayed': False,
        'raw_capture_rescanned': False, 'source_prepared': False, 'source_compiled': False,
        'target_executed': False, 'first_stage_complete': False, 'transformation_authorized': False,
        'elapsed_seconds': time.perf_counter() - started,
        'max_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    with (HERE / 'endpoint-audit.json').open('x') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print(json.dumps({key: value for key, value in report.items() if key not in ('original_body_locators', 'examples')}))


if __name__ == '__main__':
    main()
