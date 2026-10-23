"""Bounded read-only samples; no SCAR/provider import, whole raw scan or replay."""
import gzip
from hashlib import sha256
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
NATIVE = ROOT / 'artifacts/experiments/first_stage_joined_physical_20261023/result/native'
PARTS = NATIVE / 'bundle-partitions'
TRACE = ROOT / 'artifacts/experiments/first_stage_lewm_physical_20261023/trace'
manifest_path = PARTS / 'manifest.json'
manifest_bytes = manifest_path.read_bytes()
assert len(manifest_bytes) < 1000000
manifest = json.loads(manifest_bytes)
reads, samples = [], {}


def table(graph, name, count):
    declared = manifest['graphs'][graph]['tables'][name]['chunks'][0]
    path = PARTS / declared['uri']
    result, size = [], 0
    with gzip.open(path, 'rb') as stream:
        for line in range(1, count + 1):
            raw = stream.readline(500001)
            if not raw:
                break
            size += len(raw)
            assert len(raw) <= 500000 and size <= 2000000
            value = json.loads(raw)
            result.append((line, value['ordinal'], value['record'], sha256(raw).hexdigest()))
    reads.append({'path': str(path), 'declared_shard': declared,
        'prefix_decoded_bytes_read': size, 'prefix_rows_read': len(result),
        'full_shard_hash_revalidated_here': False})
    return result


definitions = table('semantic', 'definitions', 150)
instances = table('evidence', 'instances', 80)
provider_refs = table('evidence', 'provider_references', 5)
regions = table('values', 'regions', 12)
nodes = {1, 26, 27, 28, 29, 38, 39, 40, 41, 43, 50, 51, 52, 54}
instance_samples = [row for row in instances if row[2]['metadata'].get('raw_reference', '').rsplit('/', 1)[-1].isdigit()
                    and int(row[2]['metadata']['raw_reference'].rsplit('/', 1)[-1]) in nodes]
needed = {row[2]['definition']['wire'] for row in instance_samples}
samples['instances'] = instance_samples
samples['definitions'] = [row for row in definitions if row[2]['id']['wire'] in needed]
samples['provider_references'] = provider_refs
samples['regions'] = regions
eto = TRACE / 'execution-trace.369749.72816598bfa183a810428fe30a7873ff.json.gz'
with gzip.open(eto, 'rb') as stream:
    prefix = stream.read(196608)
text = prefix.decode('utf-8')
position = re.search(r'"nodes"\s*:\s*\[', text).end()
decoder, raw_nodes = json.JSONDecoder(), []
for index in range(58):
    while position < len(text) and text[position] in ' \r\n\t,':
        position += 1
    node, end = decoder.raw_decode(text, position)
    if index in nodes:
        raw_nodes.append({'pointer': '#/nodes/' + str(index), 'record': node,
            'source_prefix_start': position, 'source_prefix_end': end,
            'source_record_bytes_sha256': sha256(text[position:end].encode()).hexdigest()})
    position = end
reads.append({'path': str(eto), 'prefix_decoded_bytes_read': len(prefix),
    'full_raw_hash_revalidated_here': False, 'prefix_sha256': sha256(prefix).hexdigest()})
samples['original_eto_nodes'] = raw_nodes
dispatch = TRACE / 'dispatch-observations.369749.72816598bfa183a810428fe30a7873ff.jsonl.gz'
dispatch_rows, size = [], 0
with gzip.open(dispatch, 'rb') as stream:
    for line in range(1, 51):
        raw = stream.readline(500001)
        if not raw:
            break
        size += len(raw)
        assert len(raw) <= 500000 and size <= 2000000
        value = json.loads(raw)
        if value.get('sequence') in (5, 7, 8, 9):
            dispatch_rows.append({'line': line, 'raw_sha256': sha256(raw).hexdigest(), 'record': value})
reads.append({'path': str(dispatch), 'prefix_decoded_bytes_read': size,
    'prefix_rows_read': line, 'full_raw_hash_revalidated_here': False})
samples['original_dispatch_rows'] = dispatch_rows
report = {'schema': 'scar.native-value-chain-read-only-audit', 'schema_version': 1,
    'manifest': {'path': str(manifest_path), 'sha256': sha256(manifest_bytes).hexdigest(), 'bytes': len(manifest_bytes)},
    'counts': {key: value['counts'] for key, value in manifest['graphs'].items() if isinstance(value, dict)},
    'bounded_reads': reads, 'samples': samples, 'producer': {'path': str(Path(__file__).resolve()),
        'sha256': sha256(Path(__file__).read_bytes()).hexdigest()},
    'production_modified': False, 'full_bundle_or_raw_replayed': False,
    'source_prepared': False, 'code_compiled': False, 'target_executed': False,
    'new_value_records_created': False, 'first_stage_complete': False}
(HERE / 'audit.json').write_text(json.dumps(report, sort_keys=True, indent=2) + '\n')
print(json.dumps({'counts': report['counts'], 'sample_records': sum(map(len, samples.values())),
    'prefix_decoded_bytes_read': sum(row['prefix_decoded_bytes_read'] for row in reads),
    'output_bytes': (HERE / 'audit.json').stat().st_size}, sort_keys=True))
