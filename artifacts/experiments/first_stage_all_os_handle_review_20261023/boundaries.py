"""Join the small audit catalog to already retained context facts, read only."""
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
EXP = HERE.parent
summary = json.loads((HERE / "summary.json").read_text())
coords = json.loads((EXP / "first_stage_os_interface_work_20261023/result/capture-coordinates.json").read_text())
events = json.loads((EXP / "first_stage_fd_table_projection_20261023/context-events.json").read_text())
automatic = json.loads((EXP / "first_stage_os_source_lookup_20261023/gate-attempt01/automatic-witness/lookup.json").read_text())
threads = {row['tid']: row for row in coords['threads']}
event_by_source = {(row['source']['artifact']['uri'], row['source']['locator']): row for row in events}
match_by_source = {(row['need']['birth_source']['artifact']['uri'], row['need']['birth_source']['locator']): row for row in automatic['matches']}
execs = defaultdict(list)
for event in events:
    if event['syscall'] in ('execve', 'execveat') and event['result'] == 0:
        execs[event['source']['artifact']['uri']].append(int(event['source']['locator'].rsplit('/',1)[1]))
fact = coords['seed']['target_exec'];execs[fact['artifact']['uri']].append(int(fact['locator'].rsplit('/',1)[1]))
raw_path=HERE/'handles.jsonl.gz'
assert hashlib.sha256(raw_path.read_bytes()).hexdigest() == summary['catalog']['receipt']['sha256']
with gzip.open(raw_path,'rb') as stream:
    payload=stream.read(20_000_001)
assert len(payload) == summary['catalog']['decoded_bytes'] <= 20_000_000
assert hashlib.sha256(payload).hexdigest() == summary['catalog']['decoded_sha256']
segments=Counter()
by_actor={row['native_tid']:row for row in summary['handles_by_actor']}
for raw in payload.splitlines():
    row=json.loads(raw);tid=row['native_actor'];logical=by_actor[tid]['logical_source'];line=row['source']['physical_line']
    segments[(tid, sum(boundary<line for boundary in execs[logical]))] += 1
result=[]
for tid, group in sorted(by_actor.items()):
    thread=threads.get(tid);birth=thread['source'] if thread else None
    known=None
    if birth:
        key=(birth['artifact']['uri'],birth['locator'])
        if key in event_by_source:
            event=event_by_source[key]
            assert event['result']==tid
            known={'provider':'EXISTING_NON_MAIN_RAW_PROJECTION','source':birth,'syscall':event['syscall'],'clone_flags':event['clone_flags']}
        elif key in match_by_source:
            match=match_by_source[key]
            assert match['record']['result']==tid
            known={'provider':'AUTOMATIC_PUBLIC_R1_POSITIVE_LOOKUP','source':birth,'syscall':match['record']['syscall'],'clone_flags':match['clone_flags']}
    result.append({'native_tid':tid,'handles':group['handles'],'birth_source':birth,'known_birth_contract':known,
        'birth_contract_frontier':'NONE_FOR_THIS_FACT' if known else ('NO_OWN_BIRTH_COORDINATE' if not birth else 'FLAGS_REQUIRE_AUTOMATIC_SOURCE_LOOKUP'),
        'successful_exec_lines_in_own_source':sorted(execs[group['logical_source']]),
        'handle_segments':[{'prior_successful_execs_in_own_source':n,'handles':count} for (actor,n),count in sorted(segments.items()) if actor==tid]})
report={'schema':'scar.all-os-handle-boundary-read-review','schema_version':1,'actors':result,
    'new_source_queries':0,'raw_files_read':0,'production_changed':False,'full_execution_model_semantics':'OPEN'}
with (HERE/'boundaries.json').open('x') as stream:json.dump(report,stream,indent=2,sort_keys=True);stream.write('\n')
print(json.dumps({'actors':len(result),'known_birth_contracts':sum(row['known_birth_contract'] is not None for row in result),'source_queries':0},sort_keys=True))
