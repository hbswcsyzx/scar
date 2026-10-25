"""Pin original failure, code and measured SP7 without decoding its JSON/model."""
from pathlib import Path
import ast
import gzip
import hashlib
import io
import json
import run_postflight

BASE=Path(__file__).resolve().parent
ROOT=BASE.parents[3]
ORIGINAL=BASE.parent/'candidate02'

def raw(value):return (json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n').encode()
def sha(value):return hashlib.sha256(value).hexdigest()
def receipt(path):
    p=Path(path).resolve();data=p.read_bytes();return {'path':str(p),'bytes':len(data),'sha256':sha(data)}
def stat_row(path,stored_sha,decoded_bytes=None,decoded_sha=None):
    p=Path(path).resolve();s=p.stat()
    if p.is_symlink():raise ValueError('symlink input')
    return {'path':str(p),'size':s.st_size,'stored_bytes':s.st_size,'stored_sha256':stored_sha,
        'decoded_bytes':decoded_bytes,'decoded_sha256':decoded_sha,'mtime_ns':s.st_mtime_ns,
        'ctime_ns':s.st_ctime_ns,'inode':s.st_ino,'device':s.st_dev}

def main():
    if (BASE/'freeze.json').exists():raise ValueError('postflight must be a fresh immutable scope')
    original_bytes=(ORIGINAL/'freeze.json').read_bytes();original=json.loads(original_bytes)
    if sha(original_bytes)!='c488748534bd0a92763f7b80ac1d28e38ad345d2a6d35d4f0f8e728a76b3127c':raise ValueError('original approved freeze differs')
    for row in original['candidate_scar_sources']+original['runtime_sources']+original['small_frozen_files']:
        p=Path(row['path']);data=p.read_bytes()
        if len(data)!=row['bytes'] or sha(data)!=row['sha256']:raise ValueError('original code/dependency changed: '+str(p))
    selection=json.loads((ORIGINAL/'selection.json').read_bytes())
    artifact=ORIGINAL/'attempt01/sourceprogram7.json.gz'
    stored_parts=[];stored_bytes=0;stored_hash=hashlib.sha256()
    with artifact.open('rb') as stream:
        while chunk:=stream.read(65536):
            stored_bytes+=len(chunk)
            if stored_bytes>4_000_000:raise ValueError('SP7 stored4MB stream measurement cap')
            stored_hash.update(chunk);stored_parts.append(chunk)
    decoded_bytes=0;decoded_hash=hashlib.sha256()
    with gzip.GzipFile(fileobj=io.BytesIO(b''.join(stored_parts)),mode='rb') as stream:
        while chunk:=stream.read(65536):
            decoded_bytes+=len(chunk)
            if decoded_bytes>4_000_000:raise ValueError('SP7 decoded4MB stream measurement cap')
            decoded_hash.update(chunk)
    measurement={'uri':str(artifact),'stored_bytes':stored_bytes,'stored_sha256':stored_hash.hexdigest(),
        'decoded_bytes':decoded_bytes,'decoded_sha256':decoded_hash.hexdigest(),
        'measurement_origin':'NEW_POSTFLIGHT_PREPARATION_STREAM_HASH_NOT_ORIGINAL_WRITER_RECEIPT',
        'model_JSON_decoded':False,'measurement_physical_read_bytes':stored_bytes,
        'measurement_logical_decoded_bytes':decoded_bytes}
    (BASE/'ARTIFACT_MEASUREMENT.json').write_bytes(raw(measurement))
    selection.update(original_freeze=str(ORIGINAL/'freeze.json'),original_freeze_sha256=sha(original_bytes),
        original_result=str(ORIGINAL/'attempt01/result.json'),original_progress=str(ORIGINAL/'attempt01/progress.jsonl'),
        original_stderr=str(ORIGINAL/'attempt01/stderr.log'),sp7_postflight_measurement=measurement)
    (BASE/'selection.json').write_bytes(raw(selection))
    inputs=list(original['inputs'])
    inputs.append(stat_row(artifact,measurement['stored_sha256'],decoded_bytes,measurement['decoded_sha256']))
    for path in (ORIGINAL/'freeze.json',ORIGINAL/'attempt01/result.json',ORIGINAL/'attempt01/progress.jsonl',ORIGINAL/'attempt01/stderr.log'):
        r=receipt(path);inputs.append(stat_row(path,r['sha256'],r['bytes'],r['sha256']))
    # Keep every original dependency hash; union only adds this postflight's
    # actual dependency locations. No old activity/runtime list is recovered.
    runtime_by_path={row['path']:row for row in original['runtime_sources']}
    for path in sorted(run_postflight.preload()):runtime_by_path.setdefault(path,receipt(path))
    runtime=[runtime_by_path[name] for name in sorted(runtime_by_path)]
    own_small=[receipt(BASE/name) for name in ('run_postflight.py','gate_guards.py','prepare_postflight.py','selection.json','ARTIFACT_MEASUREMENT.json')]
    small_by_path={row['path']:row for row in original['small_frozen_files']+own_small}
    small=[small_by_path[name] for name in sorted(small_by_path)]
    guard_bytes=sum(row['bytes'] for row in original['candidate_scar_sources']+runtime+small)
    if guard_bytes>32_000_000:raise ValueError('postflight32MB source/runtime guard cap')
    freeze={'schema':'scar.module-import-prefix-postflight-freeze','schema_version':1,'status':'FROZEN_NOT_RUN',
        'attempt':str(BASE/'attempt01'),'production_sources':original['production_sources'],
        'candidate_scar_sources':original['candidate_scar_sources'],'runtime_sources':runtime,'small_frozen_files':small,
        'inputs':inputs,'limits':original['limits'],'target_namespace_roots':original['target_namespace_roots'],
        'allowed_composition_roots':original['allowed_composition_roots'],
        'internal_check_inputs':[{'path':str(BASE/'freeze.json'),'role':'ROOT_APPROVED_FREEZE_SHA256','max_bytes':1000000}],
        'original_freeze':{'path':str(ORIGINAL/'freeze.json'),'sha256':sha(original_bytes)},
        'original_window_exit_code':1,'original_activity_counts':'MISSING_OPEN','original_runtime_participant_list':'MISSING_OPEN',
        'old_SP6_and_three_negatives':'old phase/runner observations only; not reexecuted',
        'new_source_lowerings':0,'new_episode':False,'guard_bytes_per_pass':guard_bytes}
    data=raw(freeze);(BASE/'freeze.json').write_bytes(data)
    report={'status':'FROZEN_NOT_RUN','freeze_sha256':sha(data),'original_window_exit_code':1,
        'production4_unchanged':True,'scar_sources':len(original['candidate_scar_sources']),
        'runtime_file_pins':len(runtime),'input_roots':len(inputs),'guard_bytes_per_pass':guard_bytes,
        'artifact_stream_measurement':measurement,'source_context_payload_reads':0,'model_JSON_reads':0,
        'new_source_lowerings':0,'target_compile_exec_prepare':0,'old_missing_counts_not_recovered':True}
    (BASE/'PREPARATION_RECEIPT.json').write_bytes(raw(report));print(json.dumps(report,indent=2))
if __name__=='__main__':main()
