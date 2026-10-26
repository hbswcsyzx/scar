"""One offline transport/factory closeout of the original closed capture.

No target, subprocess, profiler, new capture, owner restoration or graph import.
The only changed original limit is archive transport max_files=4096.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback

HERE=Path(__file__).resolve().parent
TREE=HERE.parents[3]
CAPTURE=HERE.parent/'capture'
MAX_REPORT=8_000_000
MAX_COORDINATES=64_000_000


def need(value,message):
    if not value:raise ValueError(message)


def digest(path):
    h=hashlib.sha256();n=0
    with path.open('rb') as stream:
        while block:=stream.read(1_048_576):h.update(block);n+=len(block)
    return h.hexdigest(),n


def stamp(path):
    s=path.stat();return [s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns]


def dump(name,value):
    raw=(json.dumps(value,sort_keys=True,ensure_ascii=True,indent=2,allow_nan=False)+'\n').encode()
    need(len(raw)<=MAX_REPORT,'postflight report byte limit')
    with (HERE/name).open('xb') as stream:stream.write(raw)


def document(path,maximum=2_000_000):
    need(path.stat().st_size<=maximum,'small metadata byte limit: '+str(path))
    return json.loads(path.read_bytes())


def verify_rows(rows):
    total=0
    for row in rows:
        path=Path(row['uri']);actual,size=digest(path);total+=size
        need((actual,size)==(row['sha256'],row['size_bytes']),'frozen bytes changed: '+str(path))
    return total


def main():
    started=time.monotonic();phase='PREFLIGHT'
    result={'schema':'scar.joint-capture-offline-closeout','schema_version':1,'status':'STARTED',
        'original_root_pty':30453,'original_gate_exit':1,'original_target_returncode':0,
        'target_runs_added':0,'CPU_cases_added':0,'Torch_imported':False,
        'owner_restored_from_JSON':False,'whole_model_established':False}
    try:
        freeze=document(HERE/'freeze.json',4_000_000)
        need(Path.cwd()==TREE and os.environ.get('PYTHONPATH')==str(TREE),'exact main cwd/PYTHONPATH required')
        need(not (HERE/'STARTED.json').exists(),'offline gate already attempted; no retry in place')
        result['preflight_hash_bytes']=verify_rows(freeze['sources']+freeze['controls']+freeze['metadata_inputs'])
        need(sorted(str(p) for p in (TREE/'scar').rglob('*.py'))==[r['uri'] for r in freeze['sources']], 'source inventory changed')
        inventory=document(HERE/'DECLARED_PATHS.json',4_000_000)
        for row in inventory['files']:
            need(stamp(Path(row['uri']))==row['stat5'],'closed raw preimage changed: '+row['uri'])
        for group,pattern in [('OS','os/syscalls.*'),('TRACE_JSONL','trace/*.jsonl'),
                              ('ETO','trace/execution-trace.*.json'),('KINETO','trace/kineto.*.json')]:
            need({str(p) for p in CAPTURE.glob(pattern)}=={r['uri'] for r in inventory['files'] if r['group']==group},
                 'unexpected or missing original flat capture family: '+group)
        need(inventory['declared_files']==1935 and inventory['declared_raw_bytes']==1_747_584_780,'exact observed transport inventory differs')
        need(not (CAPTURE/'archive-index.json').exists() and not (CAPTURE/'capture-coordinates.json').exists(),'fresh offline derived outputs required')
        need(not list(CAPTURE.rglob('*.gz')),'original failed before compression; unexpected compressed member')
        dump('STARTED.json',{'pid':os.getpid(),'phase':phase,'original_gate_exit':1,
            'declared_files':inventory['declared_files'],'declared_raw_bytes':inventory['declared_raw_bytes'],
            'target_runs_added':0,'freeze_sha256':digest(HERE/'freeze.json')[0]})
        from scar.trace.os_capture_launch import OSCaptureBudgets,archive_owned_capture,publish_bytes
        from scar.trace.capture_coordinates import bind_capture_coordinates
        from scar.trace.collector_execution_witness import bind_collector_execution_witness
        from scar.ir.record_codec import encode,decode
        from scar.ir.program.providers import ProviderArtifact
        budgets=OSCaptureBudgets(max_files=4096,max_os_bytes=1_500_000_000,
            max_raw_bytes=4_000_000_000,max_stored_bytes=2_500_000_000,
            max_os_lines=6_000_000,max_metadata_bytes=2_000_000,max_seconds=3600)
        result['offline_archive_transport_budgets']=vars(budgets)
        phase='ORDINARY_LOSSLESS_ARCHIVE'
        archive_started=time.monotonic()
        receipt=archive_owned_capture(CAPTURE,budgets=budgets)
        result['archive_elapsed_seconds']=time.monotonic()-archive_started
        need(time.monotonic()-started<=900,'offline worker900s budget exceeded after archive')
        archive=document(CAPTURE/'archive-index.json')
        expected={r['uri'] for r in inventory['files']}
        actual={r['logical_path'] for r in archive['files']}
        need(len(archive['files'])==len(actual)==len(expected) and actual==expected,'normal archive omitted/added/duplicated a declared input')
        need(archive['verified_roundtrip'] is True,'normal lossless roundtrip missing')
        need(set(archive.get('retained_plain_members',[]))==set(inventory['collector_plain_members']),'retained exact witness plain inventory differs')
        result['archive_receipt']=receipt;result['archive_entries']=len(archive['files'])
        result['archive_io_accounting']=archive['io_accounting']
        dump('archive-terminal.json',{'phase':'ARCHIVE_COMPLETE','archive':receipt,'entries':len(archive['files']),
             'io_accounting':archive['io_accounting'],'elapsed_seconds':time.monotonic()-started})
        phase='NORMAL_PUBLIC_COORDINATES_FACTORY'
        binding_started=time.monotonic()
        coordinate_path=CAPTURE/'capture-coordinates.json'
        coordinates=bind_capture_coordinates(CAPTURE,max_bytes=4_000_000_000,max_lines=6_000_000,
            profile_uri=str(coordinate_path),publish_os_profile=True)
        need(len(coordinates.payload)<=MAX_COORDINATES,'derived coordinate output exceeds separate64MB report bound')
        publish_bytes(coordinate_path,coordinates.payload)
        need(digest(coordinate_path)==(coordinates.artifact.sha256,coordinates.artifact.size_bytes),'ordinary published coordinate bytes differ')
        result['coordinate_factory_elapsed_seconds']=time.monotonic()-binding_started
        need(time.monotonic()-started<=900,'offline worker900s budget exceeded after coordinate factory')
        phase='NORMAL_WITNESS_AND_TOPOLOGY_BINDER'
        membership=coordinates.report['collector_execution_membership']
        need(membership['capability']=='SCAR_COLLECTOR_EXECUTION_MEMBERSHIP_V2','V2 ordinary membership missing')
        witness=membership['manifest']
        joined=bind_collector_execution_witness(witness['uri'],expected_sha256=witness['sha256'],coordinates=coordinates)
        dump('collector-binding.local-only.json',encode(joined))
        topology_join=joined.get('resource_topology',{})
        need(topology_join.get('capability')=='SCAR_RESOURCE_TOPOLOGY_V1','explicit ordinary topology member chain missing')
        topology=document(Path(topology_join['manifest']['uri']),1_000_000)
        need(topology['issuer']==joined['issuer'],'topology issuer differs from real binder')
        native_inputs=coordinates.report['native_tensor_input_membership']
        need(native_inputs['capability']=='SCAR_NATIVE_TENSOR_INPUT_MEMBERSHIP_V1','ordinary native companion membership missing')
        for artifact in [native_inputs['manifest'],*native_inputs['chunks']]:
            need(coordinates.process_for(decode(ProviderArtifact,artifact),coordinates.target_process.pid)==coordinates.target_process,
                 'native companion artifact/target selector differs')
        joined_birth=joined.get('process_birth_join')
        result.update(status='ACTUAL_OFFLINE_ARCHIVE_AND_ORDINARY_BINDING_WITH_OPEN',phase='COMPLETE',
            coordinate_artifact=encode(coordinates.artifact),run=encode(coordinates.run.id),
            coordinate_counts=coordinates.report['counts'],
            coordinate_frontier_counts=dict(Counter(r.get('code','UNCLASSIFIED') for r in coordinates.report['open'])),
            collector_capability=membership['capability'],collector_members=membership['member_count'],
            collector_frontiers=joined['frontiers'],
            process_birth_status=None if joined_birth is None else joined_birth['status'],
            process_birth_qualification=None if joined_birth is None else joined_birth['qualification'],
            pid_reuse_excluded=joined['pid_reuse_excluded'],
            native_companion_retained_rows=native_inputs['retained_rows'],native_companion_chunks=len(native_inputs['chunks']),
            topology_summary={k:topology[k] for k in ('profile','boundary','counts','source_payload_bytes','interface_file_bytes_read','api_representation_bytes','producer_frontiers')},
            inventory_is_actual_use=False,physical_block_IO_proved=False,
            allocation_state_content_ready_established=False,whole_model_established=False)
        expected_sources={r['uri']:r for r in freeze['sources']};imports=[]
        for name,module in sorted(sys.modules.items()):
            if name!='scar' and not name.startswith('scar.'):continue
            filename=getattr(module,'__file__',None);need(filename is not None,'SCAR module has no concrete source')
            uri=str(Path(filename).resolve());need(uri in expected_sources,'SCAR import outside main freeze: '+uri)
            imports.append({'module':name,'uri':uri,'sha256':expected_sources[uri]['sha256']})
        result['main_imports']=imports;need('torch' not in sys.modules,'offline gate unexpectedly imported Torch')
        result['post_source_and_original_metadata_hash_bytes']=verify_rows(freeze['sources']+freeze['metadata_inputs'])
        need(time.monotonic()-started<=900,'offline worker900s budget exceeded after bindings')
    except BaseException as error:
        result.update(status='FAILED',phase=phase,error_type=type(error).__name__,error=str(error),traceback=traceback.format_exc())
        dump('FAILURE.json',result);traceback.print_exc();return 1
    finally:
        result['whole_elapsed_seconds']=time.monotonic()-started
        result['Torch_imported']='torch' in sys.modules
        dump('result.json',result)
    print(json.dumps({'status':result['status'],'whole_elapsed_seconds':result['whole_elapsed_seconds'],
                      'original_gate_exit':1,'target_runs_added':0,'whole_model_established':False}),flush=True)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
