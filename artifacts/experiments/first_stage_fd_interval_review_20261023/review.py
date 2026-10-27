"""Metadata/public R1 review only; deliberately never calls a raw-reading loader."""
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import re
import resource
import time

from scar.ir.execution.resources import ResourceInstance, ImportedAt, RunRealm
from scar.ir.program.resources import ResourceRole
from scar.ir.record_codec import decode
from scar.trace.os_resource_refinement import OSResourceBase


HERE=Path(__file__).resolve().parent
EXP=HERE.parent
ROOT=EXP.parents[1]


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def canonical(value):return (json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)+'\n').encode()
def line(source):return int(re.fullmatch(r'#/lines/([1-9][0-9]*)',source['locator'])[1])
def write(name,value):
    with (HERE/name).open('x') as stream:json.dump(value,stream,indent=2,sort_keys=True,ensure_ascii=False);stream.write('\n')


def main():
    started=time.monotonic()
    r1=EXP/'first_stage_os_interface_work_20261023/result'
    fd=EXP/'first_stage_os_fd_source_projection_20261023/gate-attempt01'
    selected=EXP/'first_stage_os_source_lookup_20261023/gate-attempt01'
    paths={'base':r1/'interfaces/manifest.json','coords':r1/'capture-coordinates.json',
        'archive':EXP/'first_stage_lewm_physical_20261023/archive-index.json',
        'contexts':selected/'result/manifest.json','fd_manifest':fd/'result/manifest.json',
        'fd_summary':fd/'summary.json','fd_final_receipts':fd.parent/'gate-final-artifact-receipts.json',
        'events':EXP/'first_stage_fd_table_projection_20261023/context-events.json',
        'file_receipts':EXP/'first_stage_fd_table_projection_20261023/file-receipts.json',
        'birth_facts':fd/'birth-facts.json'}
    docs={name:json.loads(path.read_text()) for name,path in paths.items()}
    receipts={name:{'path':str(path),'sha256':sha(path),'bytes':path.stat().st_size} for name,path in paths.items()}
    write('inputs.json',receipts)
    base=OSResourceBase(paths['base'],cached_chunks=2)
    coords,context,fdm=docs['coords'],docs['contexts'],docs['fd_manifest']
    assert fdm['base']['sha256']==base.artifact.sha256 and fdm['selected_view']['sha256']==receipts['contexts']['sha256']
    assert context['base']['sha256']==base.artifact.sha256 and context['run']==coords['run']
    assert receipts['archive']['sha256']==coords['seed']['archive_sha256']
    assert docs['fd_summary']['manifest']['physical_sha256']==receipts['fd_manifest']['sha256']
    raw_artifacts={row['record']['uri']:row['record'] for row in base.reader.iter_records('artifacts')}
    entries={row['actual_path']:row for row in docs['archive']['files']}
    logical={row['logical_path']:row for row in docs['archive']['files']}
    resources={row['id']['wire']:decode(ResourceInstance,row) for row in context['context_resources']}
    intervals={p['interval']['artifact']['uri']:p for p in context['context_proofs']}
    retained={row['replacement']['id']['wire'] for row in context['handle_refinements']}
    threads={row['tid']:row for row in coords['threads']}
    known_birth={}
    for event in docs['events']:
        if event['syscall'] in ('clone','clone3','fork','vfork') and event['result']>0:
            known_birth[(event['source']['artifact']['uri'],line(event['source']))]={'flags':event['clone_flags'],'child':event['result']}
    for envelope in docs['birth_facts']:
        row=envelope['record'];known_birth[(row['source']['artifact']['uri'],line(row['source']))]={'flags':row['flags'],'child':row['child_thread']['tid']}
    proof_path=fd/'all-handle-field-proofs.jsonl.gz'
    proof_desc=docs['fd_summary']['proof_storage']['handles']
    assert sha(proof_path)==proof_desc['receipt']['sha256']
    with gzip.open(proof_path,'rb') as stream:payload=stream.read(10_000_001)
    assert len(payload)==proof_desc['decoded_bytes']<=10_000_000
    proofs={}
    for raw in payload.splitlines():
        envelope=json.loads(raw);proofs[envelope['ordinal']]=envelope['proof']
    assert len(proofs)==fdm['counts']['base_handles']
    full=Counter(base.manifest['summary']['interface_counts'])
    nonmain=Counter()
    for row in docs['file_receipts']:nonmain.update(row['calls'])
    assert full['execve']-nonmain['execve']==1
    assert all(full[name]==0 for name in ('execveat','unshare','close_range'))
    current=Counter();outside=Counter();by_actor=defaultdict(Counter);examples={};no_process=Counter();total=0
    for envelope in base.reader.iter_records('handles'):
        ordinal,row=envelope['ordinal'],envelope['record'];total+=1
        original_proof=proofs[ordinal]
        assert original_proof['id']==row['id'] and original_proof['original_canonical_record_sha256']==hashlib.sha256(canonical(row)).hexdigest()
        fact=row['source'];assert fact['artifact']==raw_artifacts[fact['artifact']['uri']]
        entry=entries[fact['artifact']['uri']];logical_uri=entry['logical_path'];at=line(fact)
        tid=int(re.fullmatch(r'syscalls\.([1-9][0-9]*)',Path(logical_uri).name)[1])
        assert row['start']['source']==fact and row['start']['run']==coords['run']['id']
        assert row['start']['process']==(threads[tid]['process'] if tid in threads else None)
        exact_interval=intervals.get(logical_uri)
        if row['id']['wire'] in retained:
            status='ALREADY_TYPED_CONTAINER';current[status]+=1
        elif exact_interval and exact_interval['interval']['first_selected_line']<=at<=exact_interval['interval']['last_selected_line']:
            proof=exact_interval;container=resources[proof['resource']['wire']]
            assert container.role is ResourceRole.HANDLE_TABLE and type(container.origin) is ImportedAt
            assert container.realm==RunRealm(base.run.id) and container.origin.point.run==base.run.id
            assert fact['artifact']=={'uri':container.source.artifact.uri,'sha256':container.source.artifact.sha256,
                'size_bytes':container.source.artifact.size_bytes,'schema':container.source.artifact.schema}
            assert line({'locator':container.origin.point.source.locator})==proof['interval']['first_selected_line']<=at
            assert container.origin.point.source==container.source
            assert proof['interval']['artifact']=={'uri':logical_uri,'sha256':entry['raw_sha256'],'size_bytes':entry['raw_bytes'],'schema':'strace.syscalls.text.v1'}
            switches=[event for event in docs['events'] if event['source']['artifact']['uri']==logical_uri
                and proof['interval']['first_selected_line']<=line(event['source'])<=proof['interval']['last_selected_line']
                and event['syscall'] in ('execve','execveat','unshare','close_range') and event['result']==0]
            assert not switches
            status='PROVIDER_INTERVAL_IDENTITY_APPLICABLE_CORE_AVAILABILITY_OPEN';current[status]+=1
        else:
            current['OUTSIDE_CURRENT_INTERVAL']+=1
            if exact_interval:
                import_line=line({'locator':resources[exact_interval['resource']['wire']].origin.point.source.locator})
                if at<import_line:status='BEFORE_EXISTING_IMPORTED_AT_OBSERVATION'
                else:
                    later_exec=[event for event in docs['events'] if event['source']['artifact']['uri']==logical_uri
                        and exact_interval['interval']['last_selected_line']<line(event['source'])<=at
                        and event['syscall'] in ('execve','execveat') and event['result']==0]
                    status='AFTER_INTERVAL_EXEC_COIDENTITY_OPEN' if later_exec else 'AFTER_INTERVAL_NO_CAPTURED_TABLE_SWITCH_EXTENSION_NEEDED'
            else:
                source=threads[tid]['source'];birth=known_birth.get((source['artifact']['uri'],line(source)))
                assert birth is not None and birth['child']==tid
                parent=intervals.get(source['artifact']['uri'])
                if 'CLONE_FILES' in birth['flags']:
                    if parent and parent['interval']['first_selected_line']<=line(source)<=parent['interval']['last_selected_line']:
                        status='SHARED_CHILD_OF_KNOWN_CONTEXT_BIRTH_CAUSAL_PROOF_NEEDED'
                    else:status='SHARED_CHILD_AFTER_PARENT_EXEC_IDENTITY_OPEN'
                else:status='OTHER_ACTOR_PRIVATE_BIRTH_EXEC_INTERVALS_NOT_MAPPED'
            outside[status]+=1
        by_actor[tid][status]+=1
        if row['start']['process'] is None:no_process[status]+=1
        examples.setdefault(status,{'ordinal':ordinal,'id':row['id'],'source':row['source'],'base_locator':envelope['locator']})
    report={'schema':'scar.fd-interval-read-only-review','schema_version':1,'status':'PROVIDER_INTERVAL_DERIVATION_ONLY',
        'handles':total,'current_and_applicable':dict(current),'outside_categories':dict(outside),
        'by_native_actor':{key:dict(value) for key,value in by_actor.items()},'process_none':dict(no_process),
        'examples':examples,'new_container_refinements_written':0,'new_raw_reads':0,
        'read_scope':{'r1_current_public_reader':True,'fd_projection_previous_public_gate_receipts':True,
            'fresh_fd_public_reader_not_called':'its selected loader replays raw; no bypass/fake view constructed'},
        'core_availability_order':'OPEN: EvidencePoint local order is not a core interpreted order relation',
        'full_execution_model_semantics':'OPEN','first_stage_complete':False,
        'elapsed_seconds':time.monotonic()-started,'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    write('summary.json',report)
    print(json.dumps({key:report[key] for key in ('handles','current_and_applicable','outside_categories','process_none','elapsed_seconds','peak_rss_kib')},sort_keys=True))


if __name__=='__main__':main()
