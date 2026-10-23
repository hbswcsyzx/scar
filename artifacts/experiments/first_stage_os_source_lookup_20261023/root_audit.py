"""Independent stdlib audit of automatic positive OS source lookups.

Checks existing original chunk bytes, exact selected records and demand source
mapping. Does not re-run lookup, resources importer or whole-model validation.
"""
import gzip
from hashlib import sha256
import json
from pathlib import Path
import resource
import time


HERE = Path(__file__).resolve().parent
GATE = HERE / 'gate-attempt01'
started = time.monotonic()


def load(path):
    return json.loads(Path(path).read_bytes())


def file_receipt(path):
    raw = Path(path).read_bytes()
    return {'path': str(Path(path).resolve()), 'sha256': sha256(raw).hexdigest(), 'bytes': len(raw)}


def chunk(root, ref):
    path = root / ref['uri']
    raw = path.read_bytes()
    assert (sha256(raw).hexdigest(), len(raw)) == (ref['physical_sha256'], ref['physical_bytes'])
    decoded = gzip.decompress(raw) if ref['compression'] == 'gzip' else raw
    assert (sha256(decoded).hexdigest(), len(decoded)) == (ref['decoded_sha256'], ref['decoded_bytes'])
    rows = decoded.splitlines(keepends=True)
    assert len(rows) == ref['lines'] and all(row.endswith(b'\n') for row in rows)
    return rows


lookup_path = GATE / 'automatic-witness/lookup.json'
lookup = load(lookup_path)
base = lookup['base']
manifest_path = Path(base['uri'])
receipt = file_receipt(manifest_path)
assert (receipt['sha256'], receipt['bytes']) == (base['sha256'], base['size_bytes'])
manifest = load(manifest_path)
artifacts = []
for ref in manifest['tables']['artifacts']['chunks']:
    artifacts.extend(json.loads(row)['record'] for row in chunk(manifest_path.parent, ref))
archive = load(lookup['inputs']['archive']['path'])
retained = {row['logical_path']: row for row in archive['files']}
verified = []
for match in lookup['matches']:
    selector = match['selector']
    assert selector['chunk']['artifact'] == base and selector['table'] == 'observations'
    index = int(selector['chunk']['locator'].rsplit('/', 1)[1])
    ref = manifest['tables']['observations']['chunks'][index]
    rows = chunk(manifest_path.parent, ref)
    raw = rows[selector['line'] - 1]
    row = json.loads(raw)
    assert sha256(raw).hexdigest() == match['row_sha256']
    assert row['ordinal'] == match['ordinal'] == selector['ordinal']
    assert row['record'] == match['record']
    need, record = match['need'], row['record']
    logical = need['birth_source']['artifact']
    entry = retained[logical['uri']]
    original = artifacts[record['source']['artifact']]
    assert (original['uri'], original['sha256'], original['size_bytes'], original['schema']) == (
        entry['actual_path'], logical['sha256'], logical['size_bytes'], logical['schema'])
    assert (entry['raw_sha256'], entry['raw_bytes']) == (logical['sha256'], logical['size_bytes'])
    assert '#/lines/' + str(record['source']['line']) == need['birth_source']['locator']
    assert need['child_thread']['source'] == need['birth_source']
    assert record['syscall'] in ('clone', 'clone3', 'fork', 'vfork')
    assert record['result'] == need['child_thread']['tid'] and record['errno'] is None
    verified.append({'selector': selector, 'row_sha256': match['row_sha256'],
        'exact_original_source': need['birth_source'], 'child_thread': need['child_thread']['id']})
envelope = load(GATE / 'automatic-witness/context-evidence.json')
assert envelope['producer']['kind'] == lookup['producer'] == 'AUTOMATIC_SOURCE_LOOKUP'
required = [row for row in lookup['matches'] if row['need']['consumer_need'] == 'PRE_EXEC_BIRTH_REQUIRED']
assert len(required) == 1
assert envelope['child_birth_r1']['record'] == required[0]['record']
assert envelope['child_birth_coordinate'] == required[0]['need']['child_thread']
assert '\tExit status: 0\n' in (GATE / 'run.time.txt').read_text()
report = {'status': 'PASS_EXACT_POSITIVE_RECORDS', 'positive_records': verified,
    'lookup': file_receipt(lookup_path), 'context_evidence': file_receipt(GATE / 'automatic-witness/context-evidence.json'),
    'producer_source': file_receipt(__file__), 'elapsed_seconds': time.monotonic() - started,
    'peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    'source_order_or_global_uniqueness_proved': False,
    'full_resource_codec_or_execution_model_replayed': False,
    'first_stage_complete': False}
with (HERE / 'root-audit.json').open('x') as stream:
    json.dump(report, stream, sort_keys=True, indent=2)
    stream.write('\n')
print(json.dumps({key: report[key] for key in ('status', 'elapsed_seconds', 'peak_rss_kib')}, sort_keys=True))
