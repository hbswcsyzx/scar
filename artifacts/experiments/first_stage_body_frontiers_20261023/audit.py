"""Project saved body metadata onto all observed calls; no graph reconstruction."""
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
MANIFEST = ROOT / 'artifacts/experiments/first_stage_full_inventory_restored_20261023/result/manifest.json'
BINDINGS = ROOT / 'artifacts/experiments/first_stage_partitioned_composition_bindings_20261023/bindings/bindings.json'


def load(path):
    raw = path.read_bytes()
    return json.loads(raw), {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def main():
    manifest, manifest_receipt = load(MANIFEST)
    bindings, binding_receipt = load(BINDINGS)
    assert manifest_receipt['sha256'] == '1443fedcbd8882e86dee392339a5ea51fd29ea102068a65d9e51e06b347de09e'
    assert manifest['schema'] == 'scar.partitioned-program-inventory'
    assert bindings['schema'] == 'scar.source-invocation-bindings' and bindings['schema_version'] == 2
    bodies, definitions, shard_receipts = {}, {}, []
    static_statuses = Counter()
    for file_index, receipt in enumerate(manifest['files']):
        path = MANIFEST.parent / receipt['uri']
        stored = path.read_bytes()
        assert len(stored) == receipt['physical_bytes']
        assert hashlib.sha256(stored).hexdigest() == receipt['physical_sha256']
        raw = gzip.decompress(stored)
        assert len(raw) == receipt['decoded_bytes'] and hashlib.sha256(raw).hexdigest() == receipt['decoded_sha256']
        document = json.loads(raw)
        assert document['file_index'] == file_index
        file = document['file']
        shard_receipts.append({'path': str(path), **receipt})
        for index, definition in enumerate(file['definitions']):
            key = file_index, definition['id']['wire']
            assert key not in definitions
            definitions[key] = definition
        for index, body in enumerate(file['bodies']):
            key = file_index, body['definition']['wire']
            assert key not in bodies
            bodies[key] = (body, {'artifact': receipt, 'pointer': f'#/file/bodies/{index}'})
            static_statuses[body['status']] += 1
    groups, calls = Counter(), Counter()
    reasons, reason_groups = Counter(), Counter()
    rows, seen = [], set()
    for binding in bindings['bindings']:
        key = binding['process_id'], binding['code']
        assert key not in seen
        seen.add(key)
        element = binding['definition']
        item = {'process_id': key[0], 'code': key[1], 'entered_invocations': binding['entered_invocations'],
                'source_binding_index': binding['binding_index'], 'source_status': binding['status'],
                'body_linked': binding['body'] is not None, 'source_frontiers': binding['frontiers']}
        if element is None:
            category = 'SOURCE_DEFINITION_UNRESOLVED'
        else:
            source_key = element['file_index'], element['identity']['wire']
            assert source_key in definitions
            definition = definitions[source_key]
            body, locator = bodies[source_key]
            category = 'BODY_LINKED' if item['body_linked'] else 'SOURCE_ONLY_' + body['status']
            item.update(definition_kind=definition['kind'], definition=element,
                        source=definition['source'], body_status=body['status'],
                        body_reason=body['reason'], body_locator=locator,
                        admission_reason=binding.get('admission_reason'))
            if not item['body_linked']:
                reasons[body['reason']] += binding['entered_invocations']
                reason_groups[body['reason']] += 1
        item['category'] = category
        groups[category] += 1
        calls[category] += binding['entered_invocations']
        rows.append(item)
    assert len(seen) == 817 and sum(calls.values()) == 100438
    assert len(manifest['files']) == 151 and len(definitions) == 2217
    assert dict(static_statuses) == {'NOT_ATTEMPTED': 590, 'UNSUPPORTED': 787, 'LOWERED_WITH_GAPS': 840}
    result = {'schema': 'scar.saved-body-frontier-audit', 'schema_version': 1,
              'scope': 'saved project source/body metadata joined to original 272038 source bindings',
              'inputs': [manifest_receipt, binding_receipt], 'source_files': len(shard_receipts),
              'definitions': len(definitions), 'static_body_statuses': dict(static_statuses),
              'entered_code_groups': len(seen), 'entered_invocations': sum(calls.values()),
              'groups': dict(groups), 'calls': dict(calls),
              'source_only_reasons': [{'reason': reason, 'groups': reason_groups[reason], 'calls': count}
                                      for reason, count in reasons.most_common()],
              'metadata_projection_verified': True, 'canonical_graphs_revalidated': False,
              'source_prepared': False, 'target_executed': False, 'first_stage_complete': False,
              'transformation_authorized': False}
    with (OUT / 'result.json').open('x') as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False)
        stream.write('\n')
    with gzip.open(OUT / 'groups.jsonl.gz', 'xb') as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True, separators=(',', ':')).encode() + b'\n')
    with (OUT / 'input-shards.json').open('x') as stream:
        json.dump(shard_receipts, stream, indent=2)
        stream.write('\n')
    print(json.dumps({'groups': dict(groups), 'calls': dict(calls),
                      'top_reasons': result['source_only_reasons'][:6]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
