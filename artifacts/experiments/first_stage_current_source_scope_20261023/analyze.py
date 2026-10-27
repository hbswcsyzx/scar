"""Small retained code/meta comparison only; no SCAR imports or event scan."""
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import time

BASE = Path(__file__).resolve().parent
REPO, EXPS = BASE.parents[2], BASE.parent
OLD = EXPS / 'first_stage_lewm_dispatch_20261023'
CURRENT = EXPS / 'first_stage_lewm_physical_20261023'
HISTORY = EXPS / 'first_stage_dependency_continuation_20261023/result/continuation.json'
BINDINGS = EXPS / 'first_stage_source_attachments_20261023/attempt02/bindings/bindings.json'
OLD_MODEL = EXPS / 'first_stage_full_inventory_restored_20261023/result/components/call_sources.json.gz'
COORDS = EXPS / 'first_stage_joined_physical_20261023/result/capture-coordinates.json'
START = time.monotonic()
inputs = []


def canonical(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()


def unique(pairs):
    out = {}
    for key, value in pairs:
        assert key not in out, ('duplicate field',key)
        out[key] = value
    return out


def load(path, *, max_bytes=16_000_000):
    assert path.is_file() and not path.is_symlink() and path.stat().st_size <= max_bytes
    stored = path.read_bytes()
    raw = gzip.decompress(stored) if path.suffix == '.gz' else stored
    assert len(raw) <= max_bytes
    record = {'path':str(path),'stored_bytes':len(stored),'stored_sha256':hashlib.sha256(stored).hexdigest(),
        'raw_bytes':len(raw),'raw_sha256':hashlib.sha256(raw).hexdigest()}
    inputs.append(record)
    return raw, record


def doc(path):
    raw, _ = load(path)
    return json.loads(raw,object_pairs_hook=unique)


def codes(path):
    raw, receipt = load(path,max_bytes=1_000_000)
    rows = [json.loads(line,object_pairs_hook=unique) for line in raw.splitlines()]
    assert len(rows) == 855
    assert all(set(row)=={'key','filename','qualname','first_line','flags','parameters'} for row in rows)
    indexed = {row['key']:row for row in rows}
    assert len(indexed)==len(rows)
    return indexed, receipt


old_codes, old_receipt = codes(OLD / 'trace/call-codes.272038.jsonl')
archive = doc(CURRENT / 'archive-index.json')
assert archive['schema']=='scar.lossless-capture-archive' and archive['schema_version']==1
assert archive['verified_roundtrip'] is True
logical_codes = CURRENT / 'trace/call-codes.369749.jsonl'
selected = [row for row in archive['files'] if row['logical_path']==str(logical_codes)]
assert len(selected)==1
retained_codes = Path(selected[0]['actual_path'])
assert retained_codes.is_relative_to(CURRENT) and retained_codes==logical_codes.with_suffix('.jsonl.gz')
current_codes, current_receipt = codes(retained_codes)
assert (current_receipt['stored_sha256'],current_receipt['stored_bytes'],
    current_receipt['raw_sha256'],current_receipt['raw_bytes']) == (
    selected[0]['gzip_sha256'],selected[0]['compressed_bytes'],selected[0]['raw_sha256'],selected[0]['raw_bytes'])
old_meta = doc(OLD / 'trace/call-meta.272038.json')
current_meta = doc(CURRENT / 'trace/call-meta.369749.json')
current_native = doc(CURRENT / 'trace/execution-evidence.369749.json')
coordinates = doc(COORDS)
assert current_native['pid']==current_meta['process_id']==369749
assert old_meta['process_id']==272038
assert old_meta['codes']==current_meta['codes']==len(current_codes)
assert current_meta['events']==200876 and current_meta['invocations']==100438
assert current_meta['dropped_events']==current_meta['dropped_codes']==0 and current_meta['errors']==[]
for family, path in (('codes',logical_codes),('meta',CURRENT / 'trace/call-meta.369749.json')):
    rows=[row for row in coordinates['membership'] if row['logical_path']==str(path)]
    assert len(rows)==1
    declared=rows[0]['artifact']
    retained=current_receipt if family=='codes' else inputs[-3]
    if family=='meta':
        raw=(CURRENT / 'trace/call-meta.369749.json').read_bytes()
        retained={'raw_sha256':hashlib.sha256(raw).hexdigest(),'raw_bytes':len(raw)}
    assert (declared['sha256'],declared['size_bytes']) == (retained['raw_sha256'],retained['raw_bytes'])
history = doc(HISTORY)
assert inputs[-1]['raw_sha256']=='c9ff2f87a0e90ee42297501d256d9d24aeeab60273c6172fe692c0323207173e'
binding_document = doc(BINDINGS)
assert binding_document['schema_version']==3
binding_rows = {row['code']:row for row in binding_document['bindings']}
assert len(binding_rows)==817
model = doc(OLD_MODEL)['value']['model']
original_links = {row['code']:row for row in model['code_links']}
common = set(old_codes)&set(current_codes)
exact = {key for key in common if old_codes[key]==current_codes[key]}
conflicts = common-exact
new, removed = set(current_codes)-set(old_codes),set(old_codes)-set(current_codes)
assert not conflicts
historical = {row['code']:row for row in history['admissions']}
potential = Counter()
new_rows = []
for key,row in current_codes.items():
    old = binding_rows.get(key) if key in exact else None
    if key not in exact:
        potential['NO_COMPLETE_HISTORICAL_DESCRIPTOR']+=1
        new_rows.append(row)
    elif old is None:
        potential['HISTORICAL_CAPTURED_NOT_ENTERED_NO_BINDING_RECORD']+=1
    elif old['definition'] is not None:
        potential['HISTORICAL_SOURCE_DEFINITION_AVAILABLE']+=1
    elif old.get('witness_status')=='VERIFIED':
        potential['HISTORICAL_VERIFIED_WITHOUT_DEFINITION']+=1
    else:
        potential['HISTORICAL_UNRESOLVED']+=1
hist_statuses = Counter()
current_external_exact = []
for key in sorted(exact):
    record=historical.get(key)
    if record is not None:
        hist_statuses[record['status']]+=1
        if record['status']=='SOURCE_VERIFIED': current_external_exact.append(key)
drift_files = {row['path']:row for row in history['source_guards'] if row['matches'] is False}
drift = []
for row in history['admissions']:
    if row['source_file'] in drift_files:
        drift.append({'code':row['code'],'source_file':row['source_file'],
            'historical_entered_invocations_not_current_count':row['entered_invocations'],
            'complete_descriptor_present_in_current_codes':row['code'] in exact,
            'historical_source_link':row['code_source_link'],
            'historical_guard':drift_files[row['source_file']],
            'current_entered_invocations':None,'current_guard_refreshed':False})
metadata_changes = {key:{'historical':old_meta.get(key),'current':current_meta.get(key)}
    for key in sorted(set(old_meta)|set(current_meta)) if old_meta.get(key)!=current_meta.get(key)}
result = {'schema':'scar.current-source-scope-design-evidence','schema_version':1,
    'scope':'complete retained code descriptors and small metadata only; current entries not scanned',
    'old_process_id':272038,'current_process_id':369749,
    'current_run':coordinates['run'],'old_captured_codes':len(old_codes),'current_captured_codes':len(current_codes),
    'complete_descriptor_equal':len(exact),'same_key_descriptor_conflicts':len(conflicts),
    'new_codes':len(new),'historical_codes_absent_current':len(removed),
    'new_code_descriptors':new_rows,'removed_code_descriptors':[old_codes[key] for key in sorted(removed)],
    'current_collector_metadata':current_meta,'metadata_changes':metadata_changes,
    'historical_source_availability_for_current_descriptors':dict(potential),
    'historical_dependency_statuses_for_exact_current_descriptors':dict(hist_statuses),
    'current_codes_matching_historical_external_verified':len(current_external_exact),
    'current_nonfile_descriptors':sum(row['filename'].startswith('<') for row in current_codes.values()),
    'old_nonfile_descriptors':sum(row['filename'].startswith('<') for row in old_codes.values()),
    'historical_guard_drift':drift,
    'historical_compile_profile':history['compilation_profile'],
    'recorded_python_build_equal':old_meta['python']==current_meta['python'],
    'recorded_python_build':current_meta['python'],
    'existing_original_source_link_statuses_for_current_exact_descriptors':dict(Counter(
        original_links[key]['status'] for key in exact if key in original_links)),
    'current_entered_code_groups':None,'current_per_code_invocations':None,
    'current_group_scope_frontier':'NO_SAVED_CURRENT_GROUP_METADATA_FOUND; full independent strict raw frame scan required',
    'current_event_bytes_read':0,'os_bytes_read':0,'source_bytes_read':0,
    'source_prepared':False,'source_compiled':False,'target_executed':False,
    'source_runtime_binding_established':False,'whole_model_established':False,
    'first_stage_complete':False,'transformation_authorized':False,
    'elapsed_seconds':time.monotonic()-START,'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
(BASE / 'result.json').write_bytes(canonical(result))
producer={'revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),
    'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'inputs':inputs,
    'stdlib_only':True,'scar_imported':False,'event_streams_read':False}
(BASE / 'producer.json').write_bytes(canonical(producer))
print(json.dumps({key:result[key] for key in ('old_captured_codes','current_captured_codes','complete_descriptor_equal',
    'new_codes','historical_codes_absent_current','historical_source_availability_for_current_descriptors',
    'current_codes_matching_historical_external_verified','current_nonfile_descriptors','recorded_python_build_equal')},sort_keys=True))
