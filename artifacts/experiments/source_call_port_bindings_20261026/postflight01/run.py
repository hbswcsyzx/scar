"""Only retained27 mapping and missing final guards; no factory/raw/owner replay."""
from pathlib import Path
import gzip,hashlib,json,resource,signal,time,sys
from scar.ir.program.source_call_bindings import SourceCallPortModel
from scar.ir.program.call_operand_routes import ArgumentRoute,CompletionRoute
from scar.ir.record_codec import encode

HERE=Path(__file__).resolve().parent
CANDIDATE=HERE.parent/'candidate04'
ORIGINAL=Path('/home/zyf/AAA/scar-worktrees/source858-runtime/artifacts/experiments/first_stage_source858_current_20261026/result/analysis/manifest.json')
START=time.monotonic();READ=0
MAX=1_200_000_000


def need(v,s):
    if not v:raise ValueError('postflight: '+s)


def payload(path,limit):
    global READ
    path=Path(path);need(path.is_file() and not path.is_symlink() and path.resolve()==path,'noncanonical input '+str(path))
    need(path.stat().st_size<=limit,'input ceiling '+str(path))
    b=path.read_bytes();READ+=len(b);need(READ<=MAX,'cumulative stored+decoded ceiling')
    return b


def digest(path):
    global READ
    path=Path(path);need(path.is_file() and not path.is_symlink() and path.resolve()==path,'noncanonical input '+str(path))
    d=hashlib.sha256();n=0
    with path.open('rb') as stream:
        while b:=stream.read(1_048_576):
            READ+=len(b);need(READ<=MAX,'cumulative guard ceiling');n+=len(b);d.update(b)
    return {'path':str(path),'sha256':d.hexdigest(),'bytes':n}


def document(path,limit=16_000_000):return json.loads(payload(path,limit))


def table(manifest,name,kind):
    global READ
    t=manifest['tables'][name];rows=[]
    for ref in t['chunks']:
        b=payload(ref['path'],2_000_000)
        need((len(b),hashlib.sha256(b).hexdigest())==(ref['bytes'],ref['sha256']),'retained route stored receipt')
        raw=gzip.decompress(b);READ+=len(raw);need(READ<=MAX,'cumulative route decoded ceiling')
        need((len(raw),hashlib.sha256(raw).hexdigest())==(ref['decoded_bytes'],ref['decoded_sha256']),'retained route decoded receipt')
        records=[kind.from_dict(json.loads(x)) for x in raw.splitlines()]
        need(len(records)==ref['rows'],'retained route rows');rows.extend(records)
    need(len(rows)==t['rows'],'retained table denominator')
    return rows


def main():
    global READ
    signal.signal(signal.SIGALRM,lambda *_:(_ for _ in ()).throw(TimeoutError('postflight180s')))
    signal.alarm(180);resource.setrlimit(resource.RLIMIT_AS,(4*1024**3,4*1024**3))
    source_freeze=document(CANDIDATE/'frozen/producer.json')
    model_manifest=document(CANDIDATE/'result/source-ports/manifest.json')
    model_ref=model_manifest['model'];b=payload(model_ref['path'],128_000_000)
    need((len(b),hashlib.sha256(b).hexdigest())==(model_ref['bytes'],model_ref['sha256']),'original model stored receipt')
    raw=gzip.decompress(b);READ+=len(raw);need(READ<=MAX,'cumulative model decoded ceiling')
    need((len(raw),hashlib.sha256(raw).hexdigest())==(model_ref['decoded_bytes'],model_ref['decoded_sha256']),'original model decoded receipt')
    model=SourceCallPortModel.loads(raw.decode('utf-8'));del b,raw
    need(model.summary()==model_manifest['summary'],'normal model summary')
    retained=document(ORIGINAL)
    arguments=table(retained,'routing.argument_routes',ArgumentRoute)
    completions=table(retained,'routing.completion_routes',CompletionRoute)
    by_attempt={b.attempt:b for b in model.bindings};issues={i.attempt:i for i in model.issues}
    old={r.attempt for r in (*arguments,*completions)};need(len(old)==27,'retained legacy27 call denominator')
    missing=[{'attempt':encode(a),'issue':encode(issues[a])} for a in old if a not in by_attempt]
    arg_mapped=0;completion_views=[]
    for r in arguments:
        b=by_attempt.get(r.attempt)
        if b is None:continue
        port=next((p for p in b.ports if p.index==r.actual_index),None)
        need(port is not None and (r.caller,r.callee,r.call,r.call_source,r.caller_definition,r.caller_region,r.operation)==(b.caller,b.callee,b.call.call,b.call.source,b.caller_body.definition,b.caller_body.region,b.call.core_operation),'retained argument call endpoints differ')
        need((r.actual_source,r.actual_use,r.actual_value,r.callee_definition,r.callee_region,r.formal_slot,r.formal_value,r.formal_name)==(port.actual_source,port.actual_use,port.actual_value,port.formal_body.definition,port.formal_body.region,port.formal_slot,port.formal_value,port.formal_name),'retained actual/formal port endpoints differ')
        arg_mapped+=1
    for r in completions:
        b=by_attempt.get(r.attempt)
        if b is None:continue
        need((r.caller,r.callee,r.call,r.call_source,r.caller_definition,r.caller_region,r.operation,r.callee_definition,r.callee_region)==(b.caller,b.callee,b.call.call,b.call.source,b.caller_body.definition,b.caller_body.region,b.call.core_operation,b.callee_body.definition,b.callee_body.region),'retained completion call endpoints differ')
        completion_views.append({'original_completion':encode(r),'caller_body':encode(b.caller_body),'callee_body':encode(b.callee_body),
            'authority':'qualified read-only view of original retained DIRECT_NORMAL_COMPLETION_V1; no newly inferred return relation'})
    progress=[json.loads(x) for x in payload(CANDIDATE/'progress.jsonl',2_000_000).splitlines()]
    current=next(r['summary'] for r in progress if r['event']=='OPERAND_ROUTES_BUILT')
    need(current['argument_routes']==len(arguments)==27 and current['completion_routes']==len(completions)==27,'fresh observed route counts differ from retained table counts')
    need(len(missing)==0 and arg_mapped==27 and len(completion_views)==27,'retained legacy route mapping incomplete')
    # Missing original final guard: original frozen sources/runtime and every
    # exact input. A retained report never reconstructs the old in-memory owner.
    need(digest(CANDIDATE/'inputs.json')==source_freeze['fixed_inputs'],'fixed input declaration changed')
    catalog=document(CANDIDATE/'inputs.json')
    for row in catalog['inputs']:need(digest(row['path'])==row,'final original input differs '+row['path'])
    for row in source_freeze['modules']+source_freeze['runtime']:need(digest(row['path'])==row,'original source/runtime differs '+row['path'])
    result={'status':'POSTFLIGHT_RETAINED27_MAPPING_AND_FINAL_GUARDS_PASS','original_window_exit':1,'factory_reexecuted':False,
        'raw_replayed':False,'live_owner_reconstructed':False,'model':model_ref,'summary':model.summary(),
        'legacy_scope':'exact retained source858 artifact route mapping; current fresh per-record route object was lost, only its summary was retained',
        'fresh_route_summary_observed':current,'retained_legacy_groups':27,'intersection_groups':27,'missing_groups':missing,
        'retained_argument_ports_mapped':arg_mapped,'retained_completion_views':len(completion_views),
        'dynamic_reference_identity_or_contents_state_ready_proved':False,'final_input_guards':len(catalog['inputs']),
        'final_source_runtime_guards':len(source_freeze['modules'])+len(source_freeze['runtime']),
        'actual_cumulative_stored_plus_decoded_bytes':READ,'input_ceiling':MAX,'elapsed_s':time.monotonic()-START,
        'max_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'first_stage_complete':False}
    with (HERE/'qualified-retained-completions.json').open('x') as f:json.dump({'routes':completion_views},f,indent=2);f.write('\n')
    with (HERE/'RESULT.json').open('x') as f:json.dump(result,f,indent=2);f.write('\n')
    print(json.dumps(result,sort_keys=True));signal.alarm(0)


if __name__=='__main__':main()
