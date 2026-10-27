"""Actual file API observations to existing resources and provider topology.

This is an evidence projection, not another IR. Shared/unknown FD tables do
not acquire identities. Queries read receipts; they never restore an owner.
"""
from __future__ import annotations

from collections import Counter
from bisect import bisect_right
from dataclasses import dataclass, replace
import gzip
import hashlib
import json
from pathlib import Path
import re
import time

from scar.ir.record_codec import encode, decode
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.program.resources import ResourceKind, ResourceRole
from scar.ir.execution.common import EvidencePoint, Unresolved
from scar.ir.execution.ids import ResourceInstanceID, ProviderResourceAccessID, WorkTicketID
from scar.ir.execution.resources import (ResourceInstance, RunRealm, ImportedAt, InstanceTarget,
    ProviderResourceAccess, ProviderAccessPurpose, ProviderRecordSelector)
from scar.trace.capture_coordinates import CaptureCoordinates
from scar.trace.collector_execution_witness import bind_collector_execution_witness
from scar.trace.resource_topology import read_resource_topology
from scar.trace.os_resources import import_os_resources, _READ, _WRITE, _number


def _wire(value):
    return (json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()


def _need(value,message):
    if not value:raise ValueError('OS file topology: '+message)


@dataclass(frozen=True)
class FileTopologyBudgets:
    os_bytes: int=1_500_000_000
    os_lines: int=6_000_000
    output_bytes: int=512_000_000
    chunk_rows: int=1000
    report_bytes: int=16_000_000


class _Tables:
    def __init__(self,root,limits,shared):
        self.root=root;self.limits=limits;self.total=0;self.tables={};self.shared=shared

    def write(self,table,rows):
        folder=self.root/table;folder.mkdir();chunks=[];batch=[];ordinal=0
        def flush():
            nonlocal ordinal,batch
            if not batch:return
            raw=b''.join(_wire({'ordinal':ordinal+i,'record':r}) for i,r in enumerate(batch))
            _need(len(raw)<=32_000_000,'decoded chunk bound')
            compressed=gzip.compress(raw,compresslevel=1,mtime=0)
            self.shared['bytes']+=len(compressed);self.total+=len(compressed)
            _need(self.shared['bytes']<=self.limits.output_bytes,'aggregate output byte budget')
            name=table+'/'+str(len(chunks)).zfill(6)+'.jsonl.gz'
            with (self.root/name).open('xb') as stream:stream.write(compressed)
            chunks.append({'path':name,'first_ordinal':ordinal,'last_ordinal':ordinal+len(batch)-1,
                'rows':len(batch),'raw_bytes':len(raw),'raw_sha256':hashlib.sha256(raw).hexdigest(),
                'size_bytes':len(compressed),'sha256':hashlib.sha256(compressed).hexdigest()})
            ordinal+=len(batch);batch=[]
        for row in rows:
            batch.append(row)
            if len(batch)>=self.limits.chunk_rows:flush()
        flush();self.tables[table]={'records':ordinal,'chunks':chunks}
        return self.tables[table]


def _publish(path,doc):
    raw=_wire(doc)
    with path.open('xb') as stream:stream.write(raw)
    return ProviderArtifact(str(path),hashlib.sha256(raw).hexdigest(),len(raw),doc['schema'])


def _stat_identity(context):
    a=context.arguments;n=context.syscall
    if context.result!=0:return None
    if n=='fstat' and len(a)>1:text=a[1]
    elif n=='newfstatat' and len(a)>3 and a[1]=='""' and 'AT_EMPTY_PATH' in a[3]:text=a[2]
    elif n=='statx' and len(a)>4 and a[1]=='""' and 'AT_EMPTY_PATH' in a[2]:text=a[4]
    else:return None
    if type(text)is not str or 'S_IFREG' not in text:return None
    if n=='statx':
        major=re.search(r'\bstx_dev_major=(0x[0-9a-fA-F]+|\d+)',text)
        minor=re.search(r'\bstx_dev_minor=(0x[0-9a-fA-F]+|\d+)',text)
        inode=re.search(r'\bstx_ino=(0x[0-9a-fA-F]+|\d+)',text)
        if not (major and minor and inode):return None
        parts=(major[1],minor[1],inode[1])
    else:
        device=re.search(r'\bst_dev=makedev\((0x[0-9a-fA-F]+|\d+),\s*(0x[0-9a-fA-F]+|\d+)\)',text)
        inode=re.search(r'\bst_ino=(0x[0-9a-fA-F]+|\d+)',text)
        if not (device and inode):return None
        parts=(device[1],device[2],inode[1])
    nums=[int(v,16 if v.startswith('0x') else 10) for v in parts]
    return {'fsdev':str(nums[0])+':'+str(nums[1]),'inode':nums[2],'source':encode(context.source)}


def connect_os_file_topology(coordinates,capture_dir,fresh_out,*,budgets=None,progress=None):
    """Use a live ordinary binder result; output original typed IR records.

    No JSON-to-CaptureCoordinates restoration is provided. The observer uses
    the unchanged OS replay's entry binding, not pathname/FD/time matching.
    """
    limits=budgets or FileTopologyBudgets();_need(type(limits)is FileTopologyBudgets,'budget type')
    _need(all(type(v)is int and v>0 for v in vars(limits).values()),'positive exact budgets')
    _need(type(coordinates)is CaptureCoordinates and hashlib.sha256(coordinates.payload).hexdigest()==coordinates.artifact.sha256,'ordinary coordinates required')
    capture=Path(capture_dir).resolve();out=Path(fresh_out).absolute();_need(not out.exists(),'fresh derived output required')
    _need(coordinates.report['original_root']==str(capture) and coordinates.report['local_root']==str(capture),'exact capture namespace required')
    membership=coordinates.report['collector_execution_membership'];w=membership['manifest']
    joined=bind_collector_execution_witness(w['uri'],expected_sha256=w['sha256'],coordinates=coordinates)
    topo_ref=joined['resource_topology']['manifest'];topo_path=Path(topo_ref['uri'])
    topo=read_resource_topology(topo_path,expected_sha256=topo_ref['sha256'])
    view_ref=next(a for a in topo['artifacts'] if a['path']=='observations.json')
    view_raw=(topo_path.parent/view_ref['path']).read_bytes()
    _need(hashlib.sha256(view_raw).hexdigest()==view_ref['sha256'] and len(view_raw)==view_ref['size_bytes'],'topology source changed')
    view=json.loads(view_raw);topology_artifact=ProviderArtifact(str(topo_path.parent/view_ref['path']),view_ref['sha256'],view_ref['size_bytes'],view_ref['schema'])
    contexts=[]
    def observed(context):contexts.append(context)
    if progress:progress({'phase':'NORMAL_OS_IMPORT','os_bytes_limit':limits.os_bytes,'os_lines_limit':limits.os_lines})
    fragment=import_os_resources(capture/'os',scope=coordinates.run.id.value,run=coordinates.run.id,
        root_tid=coordinates.target_process.pid,coordinates=coordinates,max_bytes=limits.os_bytes,
        max_lines=limits.os_lines,interface_work=True,file_observer=observed)
    out.mkdir(parents=True);source_out=out/'provider';source_out.mkdir();records_out=out/'records';records_out.mkdir()
    stats={};contradictions=set();uses=[];frontiers=Counter();bindings={};needed_resources=set()
    # Global ordinal follows normal importer order. A binding start and the
    # observer's same entry binding delimit the already-proven private interval.
    for c in contexts:
        if c.syscall in ('fstat','newfstatat','statx'):
            identity=_stat_identity(c)
            if identity is not None and c.binding is not None:
                key=c.binding.id.wire;previous=stats.get(key)
                if previous and (previous['fsdev'],previous['inode'])!=(identity['fsdev'],identity['inode']):contradictions.add(key)
                stats[key]=identity
            continue
        if c.syscall not in _READ|_WRITE|frozenset(('mmap','mmap2')):continue
        row=fragment.observations[c.ordinal]
        if c.binding is not None and c.syscall in _READ|_WRITE:
            _need(row.get('binding')==c.binding.id.wire,'normal IO binding and observer entry snapshot differ')
        record={'source_ordinal':c.ordinal,'observation':row,'binding':None if c.binding is None else c.binding.id.wire,
                'stat_identity':None,'status':None,'file_path_rendering':None,'resource_path':[],
                'fd_number':_number(c.arguments[4 if c.syscall in ('mmap','mmap2') else 0]) if len(c.arguments)>(4 if c.syscall in ('mmap','mmap2') else 0) else None}
        if c.result is None or c.result<0:record['status']='FAILED_OR_UNKNOWN_API_RETURN'
        elif not c.complete_entry:record['status']='INCOMPLETE_ENTRY_FD_SNAPSHOT'
        elif c.binding is None:record['status']='FD_BINDING_UNRESOLVED_SHARED_OR_UNKNOWN_TABLE'
        elif c.binding.id.wire in contradictions:record['status']='FD_STAT_IDENTITY_CONTRADICTION'
        elif c.binding.id.wire not in stats:record['status']='NO_EXACT_REGULAR_FD_STAT'
        else:
            record.update(status='OBSERVED_PRIVATE_FD_USE',stat_identity=dict(stats[c.binding.id.wire]))
            bindings[c.binding.id]=c.binding;needed_resources.add(c.binding.target.instance)
        uses.append(record)
    # A later contradiction invalidates the binding's entire selected subset.
    for r in uses:
        if r['binding'] in contradictions:r['status']='FD_STAT_IDENTITY_CONTRADICTION';r['stat_identity']=None
    opens={r.get('binding'):r.get('path_rendering') for r in fragment.observations if r.get('path_rendering') is not None}
    navigation={}
    for ordinal,row in enumerate(fragment.observations):
        if row.get('path_rendering') is not None and row.get('fd') is not None:
            navigation.setdefault((row['tid'],row['fd']),[]).append((ordinal,row))
    navigation_ordinals={k:[r[0] for r in v] for k,v in navigation.items()}
    mounts={}
    for i,m in enumerate(view['mounts']):
        if 'fsdev' in m:mounts.setdefault(m['fsdev'],[]).append((i,m))
    blocks={b['dev']:(i,b) for i,b in enumerate(view['blocks']) if b['dev'] is not None}
    successors={}
    for i,edge in enumerate(view['relations']):
        if edge['kind'] in ('BLOCK_SLAVE','PARTITION_PARENT','BLOCK_CONTROLLER_PCI','NAMESPACE_CONTROLLER','CONTROLLER_DEVICE'):
            key=edge['from_selector'].get('block_dev') or edge['from_selector'].get('nvme_controller_sysfs')
            successors.setdefault(key,[]).append((i,edge))
    resources={r.id:r for r in fragment.resources if r.id in needed_resources};hardware={}
    resource_ids={r.wire:r for r in resources}
    def hardware_node(selector,pointer):
        key=hashlib.sha256(_wire(selector)).hexdigest();identity=ResourceInstanceID(coordinates.run.id.value+':hardware:'+key)
        fact=ProviderFactReference(topology_artifact,pointer)
        resources.setdefault(identity,ResourceInstance(identity,ResourceKind.STORAGE,ResourceRole.STORAGE_ENDPOINT,
            RunRealm(coordinates.run.id),ImportedAt(EvidencePoint(coordinates.run.id,coordinates.target_process.id,fact)),fact))
        hardware[identity.wire]=selector
        resource_ids[identity.wire]=identity
        return identity
    def chain(dev):
        result=[];pending=[(dev,[])];visited=set()
        while pending:
            key,path=pending.pop(0)
            if key in visited:continue
            visited.add(key)
            if key in blocks:
                i,b=blocks[key];rid=hardware_node({'block_dev':key,'sysfs':b['sysfs']},'#/blocks/'+str(i))
                here=path+[{'resource':rid.wire,'selector':hardware[rid.wire],'source':encode(resources[rid].source)}]
            else:here=path
            edges=successors.get(key,[])
            if not edges:result.append(here)
            for i,e in edges:
                target=e['to_selector'];rid=hardware_node(target,'#/relations/'+str(i))
                step={'resource':rid.wire,'selector':target,'relation':e['kind'],
                      'source':encode(ProviderFactReference(topology_artifact,'#/relations/'+str(i)))}
                next_key=target.get('block_dev') or target.get('nvme_controller_sysfs')
                if next_key:pending.append((next_key,here+[step]))
                else:result.append(here+[step])
        return result
    chain_cache={}
    for r in uses:
        r['file_path_rendering']=opens.get(r['binding'])
        if r['file_path_rendering'] is None:
            candidates=navigation.get((r['observation']['tid'],r['fd_number']),[])
            position=bisect_right(navigation_ordinals.get((r['observation']['tid'],r['fd_number']),[]),r['source_ordinal'])-1
            if position>=0:
                candidate=candidates[position][1]
                r['path_navigation_candidate']={'rendering':candidate['path_rendering'],'source':candidate['source'],
                    'qualification':'SAME_TID_NUMERIC_FD_NAVIGATION_ONLY_NOT_FILE_COIDENTITY'}
        if r['status']=='OBSERVED_PRIVATE_FD_USE':
            dev=r['stat_identity']['fsdev'];ms=mounts.get(dev,[])
            if not ms:r['status']='FILESYSTEM_DEVICE_ABSENT_FROM_REGISTRATION_MOUNTS'
            elif dev not in blocks:r['status']='FILESYSTEM_USE_WITHOUT_VISIBLE_BLOCK_BACKING'
            else:
                i,m=ms[0];fs=hardware_node({'fsdev':dev},'#/mounts/'+str(i))
                r['filesystem_resource']=fs.wire;r['mount_views']=[{'mount_id':m['mount_id'],'mountpoint_encoded':m['mountpoint_encoded'],
                    'filesystem':m['filesystem'],'source':encode(ProviderFactReference(topology_artifact,'#/mounts/'+str(j)))} for j,m in ms]
                if dev not in chain_cache:chain_cache[dev]=chain(dev)
                r['resource_path']=chain_cache[dev];r['status']='OBSERVED_FILE_API_WITH_REGISTRATION_BACKING_CONDITIONAL'
        frontiers[r['status']]+=1
    output_total={'bytes':0};provider=_Tables(source_out,limits,output_total);provider.write('observations',uses)
    provider_manifest={'schema':'scar.os-file-observation-projection','schema_version':1,'tables':provider.tables,
        'run':encode(coordinates.run.id),'original_OS_scope':fragment.scope,'original_protocol':encode(fragment.protocol_artifact),
        'original_OS_summary':fragment.summary,'coordinate_artifact':encode(coordinates.artifact),'topology_artifact':encode(topology_artifact),
        'scope':'selected original normalized file operations; original ordinal/work/resource IDs and raw facts retained; not a new IR'}
    provider_artifact=_publish(source_out/'manifest.json',provider_manifest)
    access=[];qualified=[]
    chunk_starts=[c['first_ordinal'] for c in provider.tables['observations']['chunks']]
    process_ids={p.id.wire:p.id for p in fragment.processes}
    for ordinal,row in enumerate(uses):
        if not row['resource_path']:continue
        observation=row['observation'];qualified.append(observation)
        number=bisect_right(chunk_starts,ordinal)-1;chunk=(number,provider.tables['observations']['chunks'][number])
        selector=ProviderRecordSelector(ProviderFactReference(provider_artifact,'#/tables/observations/chunks/'+str(chunk[0])),
            'observations',ordinal,ordinal-chunk[1]['first_ordinal']+1,'/record')
        artifact=fragment.artifacts[observation['source']['artifact']];fact=ProviderFactReference(artifact,'#/lines/'+str(observation['source']['line']))
        process=process_ids.get(observation.get('process'))
        point=EvidencePoint(coordinates.run.id,process,fact)
        access.append(ProviderResourceAccess(ProviderResourceAccessID(observation['work_ticket']+':filesystem'),
            WorkTicketID(observation['work_ticket']),ProviderAccessPurpose.OUTPUT_SELECTOR if observation['syscall'] in _WRITE else ProviderAccessPurpose.INPUT_SELECTOR,
            InstanceTarget(resource_ids[row['filesystem_resource']]),
            Unresolved('provider FD has exact private HandleBinding; no canonical NativeHandle/ValueOccurrence is invented',point),point,selector,fact))
    selected=replace(fragment,observations=tuple(qualified));tables=_Tables(records_out,limits,output_total)
    tables.write('resources',(encode(r) for r in resources.values()));tables.write('handles',(encode(r) for r in fragment.handles if r.id in bindings))
    tables.write('submissions',(encode(r) for r in selected.iter_work_records('submissions')))
    tables.write('outcomes',(encode(r) for r in selected.iter_work_records('outcomes')))
    tables.write('provider_accesses',(encode(r) for r in access))
    with (out/'original-os-protocol.json').open('xb') as stream:stream.write(fragment.protocol_bytes)
    summary={'original_OS':fragment.summary,'selected_file_operations':len(uses),'status_counts':dict(frontiers),
        'qualified_backing_uses':len(access),'original_resource_ids_retained':True,'physical_block_IO_established':False,
        'hardware_inventory_is_usage':False,'state_content_ready_established':False,'whole_model_established':False}
    manifest={'schema':'scar.os-file-topology-connections','schema_version':1,'status':'PUBLISHED_WITH_OPEN',
        'tables':tables.tables,'provider':encode(provider_artifact),'topology':encode(topology_artifact),
        'coordinate_artifact':encode(coordinates.artifact),'summary':summary,'hardware_selectors':hardware,
        'scope':'original typed resource/work projection only; ProgramSnapshot/canonical source stage and effects remain OPEN',
        'qualification':'private FD replay + same binding regular-file stat; registration topology is not continuous identity or physical IO',
        'physical_block_IO_established':False,'whole_model_established':False}
    artifact=_publish(out/'manifest.json',manifest)
    if progress:progress({'phase':'PUBLISHED','summary':summary,'artifact':encode(artifact)})
    return {'artifact':encode(artifact),'summary':summary}


def _load(path,expected=None):
    path=Path(path).absolute();raw=path.read_bytes();_need(len(raw)<=16_000_000,'manifest read bound')
    if expected is not None:_need(hashlib.sha256(raw).hexdigest()==expected['sha256'] and len(raw)==expected['size_bytes'],'manifest receipt differs')
    return json.loads(raw),ProviderArtifact(str(path),hashlib.sha256(raw).hexdigest(),len(raw),json.loads(raw)['schema'])


def query_os_file_topology(manifest,*,path=None,syscall=None,limit=10,expected_sha256=None):
    """Ordinary receipt reader; returns original IDs and exact source paths."""
    _need(type(limit)is int and 1<=limit<=1000,'query bound')
    m,receipt=_load(manifest);_need(m['schema']=='scar.os-file-topology-connections' and m['status']=='PUBLISHED_WITH_OPEN','published connections required')
    if expected_sha256 is not None:_need(receipt.sha256==expected_sha256,'expected connection manifest SHA differs')
    _need(Path(m['provider']['uri']).resolve().is_relative_to(Path(manifest).absolute().parent),
          'provider receipt escapes the original connection namespace')
    p,_=_load(m['provider']['uri'],m['provider']);matches=[];visited=0
    for chunk in p['tables']['observations']['chunks']:
        _need(re.fullmatch(r'observations/[0-9]{6}\.jsonl\.gz',chunk['path']) is not None,'provider chunk path')
        _need(type(chunk['size_bytes'])is int and 0<=chunk['size_bytes']<=32_000_000 and
              type(chunk['raw_bytes'])is int and 0<=chunk['raw_bytes']<=32_000_000,'provider chunk size bound')
        q=Path(m['provider']['uri']).parent/chunk['path'];raw=q.read_bytes()
        _need(len(raw)==chunk['size_bytes'] and hashlib.sha256(raw).hexdigest()==chunk['sha256'],'provider chunk receipt differs')
        decoded=gzip.decompress(raw);_need(len(decoded)==chunk['raw_bytes'] and hashlib.sha256(decoded).hexdigest()==chunk['raw_sha256'],'provider decoded receipt differs')
        lines=decoded.splitlines();_need(len(lines)==chunk['rows'] and chunk['last_ordinal']==chunk['first_ordinal']+len(lines)-1,'provider chunk row/ordinal range')
        for line_number,line in enumerate(lines):
            envelope=json.loads(line);_need(envelope['ordinal']==chunk['first_ordinal']+line_number,'provider original ordinal differs')
            row=envelope['record'];visited+=1
            work=row['observation'].get('work_ticket')
            if work is not None:
                entry=row['observation']['entry_source']
                _need(work==p['original_OS_scope']+':syscall-work:'+str(entry['artifact'])+':'+str(entry['line']),
                      'call ID does not belong to original normalized provider namespace')
            for branch in row['resource_path']:
                for step in branch:_need(step['resource'] in m['hardware_selectors'],'resource ID outside result manifest')
            if path is not None and path not in (row['file_path_rendering'] or row.get('path_navigation_candidate',{}).get('rendering','')):continue
            if syscall is not None and row['observation']['syscall']!=syscall:continue
            matches.append(row)
            if len(matches)>=limit:return {'artifact':encode(receipt),'matches':matches,'visited':visited,'complete_scan':False,'summary':m['summary'],'physical_block_IO_established':False,'qualification':'receipt/transport read of published original IDs; producer raw inputs not revalidated by query; no owner restored'}
    return {'artifact':encode(receipt),'matches':matches,'visited':visited,'complete_scan':True,'summary':m['summary'],'physical_block_IO_established':False,'qualification':'receipt/transport read of published original IDs; producer raw inputs not revalidated by query; no owner restored'}
