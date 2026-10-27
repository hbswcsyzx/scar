"""Root-owned bounded input-port design audit. No import/capture/OS replay."""
from collections import Counter, defaultdict
import gzip
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
CAPTURE = BASE / 'artifacts/experiments/native_input_membership_20261025/capture'
LIMIT = 64000000


def pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def parse(raw):
    def invalid(_value):
        raise ValueError('nonfinite JSON constant')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def audit(plan):
    for helper in plan['helper_sources']:
        source = (BASE / helper['path']).read_bytes()
        assert len(source) == helper['bytes'] and sha256(source).hexdigest() == helper['sha256']
    from scar.ir.execution.native_port_protocol import attributes, flat_native
    assert 'torch' not in sys.modules
    assert plan['capture_root'] == str(CAPTURE) and plan['budget']['stored_plus_decoded_bytes'] == LIMIT
    specs = {item['label']: item for item in plan['inputs']}
    assert len(specs) == len(plan['inputs'])
    assert sum(item['stored_bytes'] + item['raw_bytes'] + 2 for item in specs.values()) <= LIMIT
    opened, decoded, stored = [], {}, 0
    decoded_count = 0
    for label, item in specs.items():
        path, logical = Path(item['local_uri']), Path(item['logical_uri'])
        assert path.is_relative_to(CAPTURE) and logical.is_relative_to(CAPTURE)
        assert 'os' not in path.relative_to(CAPTURE).parts and 'os' not in logical.relative_to(CAPTURE).parts
        assert not path.is_symlink() and path.resolve().is_relative_to(CAPTURE.resolve())
        assert path.stat().st_size == item['stored_bytes']
        with path.open('rb') as source:
            data = source.read(item['stored_bytes'] + 1)
        stored += len(data)
        assert len(data) == item['stored_bytes'] and sha256(data).hexdigest() == item['stored_sha256']
        if item['encoding'] == 'gzip':
            with gzip.GzipFile(fileobj=BytesIO(data), mode='rb') as source:
                raw = source.read(item['raw_bytes'] + 1)
        else:
            assert item['encoding'] == 'plain'
            raw = data
        decoded_count += len(raw)
        assert stored + decoded_count <= LIMIT
        assert len(raw) == item['raw_bytes'] and sha256(raw).hexdigest() == item['raw_sha256']
        decoded[label] = raw
        opened.append({'label': label, 'stored_bytes': len(data), 'decoded_bytes': len(raw), 'reads': 1})

    coordinates, archive = parse(decoded['coordinates']), parse(decoded['archive_index'])
    native, dispatch, physical = [parse(decoded[label]) for label in ('native_manifest', 'dispatch_metadata', 'physical_metadata')]
    companion, eto, chrome = [parse(decoded[label]) for label in ('companion_manifest', 'ETO', 'Kineto')]
    cap = coordinates['native_tensor_input_membership']
    assert cap['capability'] == 'SCAR_NATIVE_TENSOR_INPUT_MEMBERSHIP_V1'
    assert coordinates['run']['id']['value'] == plan['expected_RunID']
    assert coordinates['target_process']['value'] == plan['expected_process']
    assert coordinates['seed']['archive_sha256'] == specs['archive_index']['raw_sha256']
    assert companion['profile'] == cap['profile'] == 'scar.native-tensor-input-event-tree-v1'
    assert companion['status'] == 'COMPLETE_RETENTION' and companion['omitted_visited_torch_ops'] == 0
    assert companion['provider_revision'] == native['provider']['torch_git_version'] == plan['provider_revision']
    pid, nonce = native['pid'], companion['nonce']
    assert pid == eto['pid'] == companion['process_id'] == dispatch['process_id'] == physical['process_id']
    assert native['status'] == 'CLOSED' and native['failures'] == [] and dispatch['mode_popped'] is True
    assert dispatch['nonce'] == physical['nonce'] == nonce
    members = {row['artifact']['uri']: row for row in coordinates['membership']}
    files = {row['logical_path']: row for row in archive['files']}
    request = native['configuration']['native_tensor_input_observations']
    assert request['profile'] == companion['profile'] and request['requested'] is True
    assert request['manifest'] == specs['companion_manifest']['logical_uri']
    for label in ('native_manifest', 'dispatch_metadata'):
        receipt, item = companion['inputs'][label], specs[label]
        assert (receipt['path'], receipt['raw_sha256'], receipt['raw_bytes']) == (item['logical_uri'], item['raw_sha256'], item['raw_bytes'])
    physical_receipt = companion['legacy_physical_metadata']
    assert (physical_receipt['path'], physical_receipt['raw_sha256'], physical_receipt['raw_bytes']) == (specs['physical_metadata']['logical_uri'], specs['physical_metadata']['raw_sha256'], specs['physical_metadata']['raw_bytes'])
    assert dispatch['native_manifest'] == companion['inputs']['native_manifest']
    assert physical['inputs'] == companion['inputs']
    dispatch_receipt = companion['inputs']['dispatch_observations']
    dispatch_artifact = members[dispatch_receipt['path']]['artifact']
    assert (dispatch_receipt['raw_sha256'], dispatch_receipt['raw_bytes']) == (dispatch_artifact['sha256'], dispatch_artifact['size_bytes'])
    assert dispatch['file'] == dispatch_receipt
    for label, item in specs.items():
        if label in ('coordinates', 'archive_index'):
            continue
        member = members[item['logical_uri']]
        assert member['process'] == coordinates['target_process']
        assert member['artifact']['sha256'] == item['raw_sha256'] and member['artifact']['size_bytes'] == item['raw_bytes']
        if item['encoding'] == 'gzip':
            entry = files[item['logical_uri']]
            assert entry['actual_path'] == item['local_uri'] and entry['gzip_sha256'] == item['stored_sha256']

    rows, row_facts = [], {}
    for number, chunk in enumerate(companion['chunks']):
        label = f'chunk_{number:06d}'
        item, member = specs[label], cap['chunks'][number]
        assert item['logical_uri'] == member['uri'] and item['raw_sha256'] == member['sha256']
        assert item['raw_bytes'] == member['size_bytes'] == chunk['raw_bytes']
        assert item['raw_sha256'] == chunk['raw_sha256']
        body = decoded[label].splitlines()
        assert len(body) == chunk['rows'] and chunk['first_index'] == len(rows) + 1
        for line, payload in enumerate(body, 1):
            row = parse(payload)
            assert row['index'] == len(rows) + 1 and row['process_id'] == pid and row['nonce'] == nonce
            row_facts[row['index']] = {'input': label, 'line': line}
            rows.append(row)
    assert len(rows) == companion['retained_rows'] == companion['visited_torch_ops']
    assert sum(specs[f'chunk_{i:06d}']['raw_bytes'] for i in range(len(companion['chunks']))) == companion['raw_bytes']
    cpu, rf, tree = defaultdict(list), defaultdict(list), defaultdict(list)
    for ordinal, event in enumerate(chrome['traceEvents']):
        key = event.get('args', {}).get('External id')
        if event.get('ph') == 'X' and event.get('cat') in ('cpu_op', 'user_annotation') and event.get('pid') == pid and type(key) is int and key > 0:
            cpu[key].append((ordinal, event))
    for ordinal, node in enumerate(eto['nodes']):
        key = attributes(node).get('rf_id')
        if type(key) is int and key > 0:
            rf[key].append((ordinal, node))
    for row in rows:
        tree[row['event']['correlation_id']].append(row['index'])
    counts, frontiers, contradictions = Counter(), Counter(), []
    outcomes, samples, source_schemas, allocation_observations = [], [], Counter(), Counter()
    matched = {}

    def problem(code, index):
        contradictions.append({'row': index, 'code': code})

    def fact(label, locator):
        item = specs[label]
        return {'artifact': {'uri': item['logical_uri'], 'sha256': item['raw_sha256'],
            'size_bytes': item['raw_bytes'], 'schema': item['schema']}, 'locator': locator}

    for row in rows:
        index, header = row['index'], row['event']
        result = dict(row_facts[index], row=index, disposition=None)
        retained = []
        for slot in row['inputs']['slots']:
            counts['slot_' + slot['kind']] += 1
            paths = ([slot['path']] if slot['kind'] == 'TENSOR' else
                [item['path'] for item in slot['items']] if slot['kind'] == 'TENSOR_LIST' else [])
            counts['all_retained_tensor_metadata'] += len(paths)
            if slot['kind'] == 'TENSOR_LIST':
                counts['empty_tensor_lists'] += not slot['items']
            retained.append({'ordinal': slot['ordinal'], 'kind': slot['kind'], 'tensor_paths': paths})
        result['retained_inputs'] = retained
        if row['inputs']['availability'] != 'OBSERVED':
            frontiers['PROVIDER_INPUT_STRUCTURE_UNAVAILABLE'] += 1
        outcomes.append(result)
        correlation = header['correlation_id']
        if type(correlation) is not int or correlation <= 0:
            result['disposition'] = 'TREE_CORRELATION_UNAVAILABLE'
        elif len(tree[correlation]) != 1:
            result['disposition'] = 'TREE_CORRELATION_AMBIGUOUS'
            problem(result['disposition'], index)
        elif len(cpu.get(correlation, [])) != 1:
            result['disposition'] = 'CPU_EXTERNAL_MISSING' if not cpu.get(correlation) else 'CPU_EXTERNAL_AMBIGUOUS'
            if cpu.get(correlation):
                problem(result['disposition'], index)
        else:
            ko, event = cpu[correlation][0]
            handle = event.get('args', {}).get('Record function id')
            candidates = rf.get(handle, []) if type(handle) is int and handle > 0 else []
            if len(candidates) != 1:
                result['disposition'] = 'ETO_RF_MISSING' if not candidates else 'ETO_RF_AMBIGUOUS'
                if candidates:
                    problem(result['disposition'], index)
            else:
                no, node = candidates[0]
                attrs = attributes(node)
                result.update(disposition='RAW_KEY_JOINED_CANONICAL_BINDING_NOT_SUPPLIED',
                    correlation=correlation, RF=handle, kineto_ordinal=ko, ETO_node=node['id'], ETO_original_ordinal=no,
                    tree_parent=header['parent_result_id'], ETO_parent=node['ctrl_deps'])
                matched[header['result_id']] = node['id']
                counts['raw_key_joins'] += 1
                if header['record_function_thread_token'] != attrs.get('tid'):
                    problem('RF_THREAD_CONTRADICTION', index)
                expected_cpu_name = row['name'] + ('.' + row['overload_name'] if row['overload_name'] else '')
                if node['name'] != row['name'] or event['name'] != expected_cpu_name:
                    problem('NAME_CONTRADICTION_AFTER_KEY_JOIN', index)
                if row['inputs']['availability'] == 'OBSERVED' and len(row['inputs']['slots']) != len(node['inputs']['values']):
                    problem('TOP_LEVEL_ARITY_CONTRADICTION', index)
                text = attrs.get('op_schema')
                schema_present = type(text) is str and bool(text)
                counts['schema_text_present' if schema_present else 'schema_text_absent'] += 1
                if schema_present:
                    source_schemas[text] += 1
                else:
                    frontiers['REGISTERED_SCHEMA_TEXT_UNAVAILABLE'] += 1
                try:
                    ports = flat_native(node['inputs'])
                except (ValueError, TypeError, KeyError) as error:
                    result.update(disposition='NATIVE_INPUT_STRUCTURE_UNSUPPORTED', detail=str(error)[:256])
                    frontiers[result['disposition']] += 1
                    continue
                tensor_ports = {tuple(port['path']): port for port in ports if port['tensor']}
                counts['original_ETO_tensor_input_paths'] += len(tensor_ports)
                leaves = []
                for slot in row['inputs']['slots']:
                    if slot['kind'] == 'TENSOR':
                        leaves.append((slot['path'], slot['metadata'], f"/inputs/slots/{slot['ordinal']}/metadata"))
                    elif slot['kind'] == 'TENSOR_LIST':
                        leaves.extend((item['path'], item['metadata'], f"/inputs/slots/{slot['ordinal']}/items/{item['ordinal']}/metadata") for item in slot['items'])
                seen = set()
                port_outcomes = []
                for path, metadata, locator in leaves:
                    key = tuple(path)
                    if key in seen:
                        problem('DUPLICATE_METADATA_PATH', index)
                    seen.add(key)
                    port = tensor_ports.get(key)
                    if port is None:
                        problem('METADATA_AT_NON_TENSOR_PATH', index)
                        continue
                    counts['metadata_at_exact_native_path'] += 1
                    counts['zero_dim_metadata'] += metadata['sizes'] == []
                    counts['metadata_with_schema_text' if schema_present else 'metadata_without_schema_text'] += 1
                    if metadata['sizes'] is None or metadata['strides'] is None or metadata['device'] is None:
                        frontiers['PARTIAL_PROVIDER_GEOMETRY'] += 1
                    elif metadata['sizes'] != port['shape'] or metadata['strides'] != port['strides'] or metadata['device']['text'] != port['value'][5]:
                        problem('GEOMETRY_CONTRADICTION_AFTER_PATH_JOIN', index)
                    epoch = metadata.get('provider_allocation_id')
                    if type(epoch) is int and epoch > 0 and metadata.get('device') is not None:
                        allocation_observations[metadata['device']['text'], epoch] += 1
                    port_outcomes.append({'path': path, 'status': 'CANDIDATE_ONLY_NO_CANONICAL_NATIVE_REF'})
                    if len(samples) < 4:
                        samples.append({'metadata': fact(row_facts[index]['input'], f"#/lines/{row_facts[index]['line']}" + locator),
                            'CPU_bridge': fact('Kineto', f'#/traceEvents/{ko}'),
                            'original_input': fact('ETO', '#/nodes/' + str(no) + '/inputs/values/' + '/'.join(map(str, path))),
                            'NativeInputRef': None, 'canonical_binding_frontier': 'Await supplied canonical execution; never construct a candidate reference'})
                missing = set(tensor_ports) - seen
                frontiers['NATIVE_TENSOR_WITHOUT_EXPOSED_METADATA'] += len(missing)
                port_outcomes.extend({'path': list(path), 'status': 'PROVIDER_METADATA_UNAVAILABLE'} for path in sorted(missing))
                result.update(schema_text_present=schema_present, input_paths=port_outcomes,
                    tree_parent=header['parent_result_id'], ETO_parent=node['ctrl_deps'])
        if result['disposition'] != 'RAW_KEY_JOINED_CANONICAL_BINDING_NOT_SUPPLIED':
            frontiers[result['disposition']] += 1
    for result in outcomes:
        if 'ETO_parent' in result:
            parent = result['tree_parent']
            if parent in matched:
                counts['mapped_parent_checks'] += 1
                if matched[parent] != result['ETO_parent']:
                    problem('MAPPED_PARENT_CONTRADICTION', result['row'])
            else:
                frontiers['PARENT_OUTSIDE_EXPORTED_TORCHOP_BOUNDARY'] += 1
    assert len(outcomes) == len(rows) and 'torch' not in sys.modules
    counts.update(tree_rows=len(rows), CPU_external_records=sum(map(len, cpu.values())),
        ETO_nodes=len(eto['nodes']), ETO_positive_RF_nodes=sum(map(len, rf.values())),
        canonical_NativeInputRef_created=0, ObjectID_created=0, logical_versions_created=0)
    return {'status': 'CANDIDATES_WITH_FRONTIERS' if not contradictions else 'CONTRADICTIONS_REJECT_PORT_PUBLICATION',
        'counts': dict(counts), 'frontiers': dict(frontiers), 'contradictions': contradictions,
        'duplicate_keys': {'tree': sum(len(v) > 1 for v in tree.values()), 'CPU_external': sum(len(v) > 1 for v in cpu.values()), 'ETO_RF': sum(len(v) > 1 for v in rf.values())},
        'raw_schema_text_inventory_not_formal_parse': dict(source_schemas), 'row_inventory': outcomes,
        'sample_existing_type_fact_references': samples,
        'same_provider_allocation_group_statistics_only': {'groups': len(allocation_observations), 'observed_at_multiple_ports': sum(v > 1 for v in allocation_observations.values()), 'logical_alias_or_C_established': False},
        'budget': {'actual_stored_bytes': stored, 'actual_decoded_bytes': decoded_count, 'sum': stored + decoded_count, 'limit': LIMIT, 'opened_payloads': opened},
        'Torch_imported': False, 'OS_payloads_opened': 0, 'target_capture_runs': 0,
        'old4GB_or_old1901_reads': 0, 'port_object_content_state_ready_qualified': False}


if __name__ == '__main__':
    path = HERE / 'PLAN.json'
    raw = path.read_bytes()
    plan = parse(raw)
    assert plan['status'] == 'PREPARED_NOT_RUN', 'do not overwrite a previous audit'
    start = time.monotonic()
    result = audit(plan)
    result.update(elapsed_seconds=time.monotonic() - start, prepared_plan_sha256=sha256(raw).hexdigest(),
        analyzer_sha256=sha256(Path(__file__).read_bytes()).hexdigest())
    plan['status'], plan['audit'] = 'AUDITED_CANDIDATES_ONLY', result
    temporary = path.with_suffix('.json.tmp')
    with temporary.open('x') as output:
        json.dump(plan, output, separators=(',', ':'), sort_keys=True, allow_nan=False)
        output.write('\n')
    temporary.replace(path)
    print(json.dumps({key: value for key, value in result.items() if key not in ('row_inventory', 'sample_existing_type_fact_references', 'raw_schema_text_inventory_not_formal_parse')}))
    if result['contradictions']:
        raise SystemExit(2)
