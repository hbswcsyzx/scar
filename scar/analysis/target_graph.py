"""Build a compact target-resource graph from retained platform metadata.

This inventories capabilities and possible connections, not workload execution,
available allocation budgets, measured bandwidth, or actual buffer placement.
"""
import argparse
from collections import Counter
import gzip
from hashlib import sha256
import json
from pathlib import Path
import time

from scar.analysis import target_inventory
from scar.analysis.source_stage import _durable_bytes,_durable_mkdir
from scar.analysis.source_template_links import _json
from scar.ir.program import target_hardware as H
from scar.ir.program.providers import ProviderArtifact,ProviderFactReference
from scar.ir.record_codec import encode,decode


def _artifact(path,schema):
    raw=path.read_bytes();return ProviderArtifact(str(path),sha256(raw).hexdigest(),len(raw),schema)


def _table(path,records):
    raw=b''.join(_json(encode(row,record_tags=H.TARGET_RECORD_TAGS)) for row in records)
    payload=gzip.compress(raw,compresslevel=3,mtime=0);_durable_bytes(path,payload,replace=False)
    return dict(path=path.name,records=raw.count(b'\n'),bytes=len(payload),sha256=sha256(payload).hexdigest(),
        decoded_bytes=len(raw),decoded_sha256=sha256(raw).hexdigest())


def _resources(document,artifact):
    nodes=[];links=[];paths=[];cpus={};memory={}
    evidence=lambda pointer:ProviderFactReference(artifact,pointer)
    def connect(source,target,kind,pointer,locality=None,speed=None,width=None,conditions=(),bidirectional=False):
        links.append(H.ResourceConnection(source,target,kind,locality,None,None,speed,width,evidence(pointer),conditions,bidirectional))
    processors={p['cpu_id']:p for p in document['cpu']['processors']}
    numa=document['cpu']['numa_nodes']
    if not numa:
        numa=[dict(node_id=None,cpu_ids=document['cpu']['online_cpu_ids'],memory_total_bytes=document['dram']['memory_total_bytes'])]
    for i,row in enumerate(numa):
        nid=row['node_id'];name='host' if nid is None else 'numa'+str(nid);pointer='#/cpu/numa_nodes/'+str(i) if document['cpu']['numa_nodes'] else '#/cpu'
        if row['cpu_ids']:
            identity=H.TargetResourceID('cpu/'+name);cpus[nid]=identity
            core_ids={(processors[c]['package_id'],processors[c]['core_id']) for c in row['cpu_ids'] if c in processors}
            cores=len(core_ids) if len([c for c in row['cpu_ids'] if c in processors])==len(row['cpu_ids']) else None
            nodes.append(H.CpuExecutor(identity,nid,tuple(row['cpu_ids']),cores,tuple(document['cpu']['model_names']),evidence(pointer)))
        identity=H.TargetResourceID('memory/'+name);memory[nid]=identity
        nodes.append(H.MemoryDomain(identity,H.MemoryKind.HOST,cpus.get(nid),nid,row['memory_total_bytes'],None,None,evidence(pointer)))
    for nid,cpu in cpus.items():
        for mnid,domain in memory.items():
            connect(cpu,domain,H.ConnectionKind.MEMORY_ACCESS,'#/cpu',
                'local' if nid==mnid else 'remote',conditions=('TARGET_MEMORY_POLICY_PERMITS_ACCESS',))
    for i,row in enumerate(document['gpus']):
        pointer='#/gpus/'+str(i);identity=H.TargetResourceID('accelerator/'+row['uuid']);mem=H.TargetResourceID('memory/'+row['uuid'])
        nodes.append(H.Accelerator(identity,'cuda',row['name'],row['uuid'],row['index'],row['pci_bus_id'],
            row['numa_node'],row['compute_capability'],evidence(pointer)))
        nodes.append(H.MemoryDomain(mem,H.MemoryKind.DEVICE,identity,row['numa_node'],row['memory_total_bytes'],row['memory_technology'],None,evidence(pointer)))
        connect(mem,identity,H.ConnectionKind.MEMORY_ATTACHED,pointer,bidirectional=True)
        for nid,cpu in cpus.items():
            if row['numa_node'] is None or row['numa_node']<0 or nid==row['numa_node']:
                connect(cpu,identity,H.ConnectionKind.HOST_DEVICE_LINK,pointer,
                    'local' if nid==row['numa_node'] else None,row['max_link_speed'],row['max_link_width'],bidirectional=True)
    disks={}
    for i,row in enumerate(document['storage']['disks']):
        identity=H.TargetResourceID('storage/'+row['kname']);disks[row['kname']]=identity
        nodes.append(H.StorageDevice(identity,row['kname'],row['size_bytes'],row['transport'],row['media_kind'],evidence('#/storage/disks/'+str(i))))
    blocks={}
    def visit(rows):
        for row in rows:
            blocks[row['kname']]=row
            visit(row.get('children',()))
    visit(document['storage']['block_devices'])
    endpoints={}
    for i,row in enumerate(document['paths']):
        pointer='#/paths/'+str(i);mount=row['mount'];identity=None
        if mount is not None:
            key=(mount['target'],mount['source'],mount['fstype'])
            if key not in endpoints:
                identity=H.TargetResourceID('endpoint/'+sha256(_json(key)).hexdigest()[:24]);endpoints[key]=identity
                volume=[blocks[name]['size'] for name in row['block_devices'] if name in blocks]
                nodes.append(H.StorageEndpoint(identity,mount['target'],mount['source'],mount['fstype'],volume[0] if len(volume)==1 else None,evidence(pointer)))
                for cpu in cpus.values():
                    connect(cpu,identity,H.ConnectionKind.STORAGE_ACCESS,pointer,
                        conditions=('TARGET_FILESYSTEM_NAMESPACE_MATCHES','TARGET_PATH_ACCESS_PERMITTED'))
            identity=endpoints[key]
            for name in row['backing_disks']:
                if name in disks:connect(identity,disks[name],H.ConnectionKind.STORAGE_BACKING,pointer)
        paths.append(H.PathEndpoint(row['requested_path'],row['resolved_path'],identity,row['backing_status'],evidence(pointer)))
    return nodes,list(dict.fromkeys(links)),paths


def build_target_graph(out,paths=(),*,inventory=None):
    started=time.monotonic();out=Path(out).absolute()
    if out.exists():raise ValueError('fresh target output required')
    document=target_inventory.collect_inventory(tuple(paths)) if inventory is None else json.loads(Path(inventory).read_bytes())
    if document['schema']!='scar.target-inventory' or document['schema_version']!=1:raise ValueError('target inventory version differs')
    for source in document['sources']:
        if source['text'] is not None and sha256(source['text'].encode()).hexdigest()!=source['sha256']:raise ValueError('retained target source differs')
    _durable_mkdir(out);path=out/'inventory.json';_durable_bytes(path,_json(document),replace=False)
    artifact=_artifact(path,'scar.target-inventory');nodes,links,paths=_resources(document,artifact)
    families={}
    for row in nodes:families.setdefault(type(row).__name__,[]).append(row)
    tables={name:_table(out/(name+'.jsonl.gz'),rows) for name,rows in sorted(families.items())}
    edges=_table(out/'connections.jsonl.gz',links);locations=_table(out/'paths.jsonl.gz',paths)
    result=dict(schema='scar.target-hardware-graph',schema_version=1,status='TARGET_DESCRIPTION_BUILT',
        inventory=dict(uri=artifact.uri,sha256=artifact.sha256,size_bytes=artifact.size_bytes),
        nodes=tables,connections=edges,paths=locations,resource_count=len(nodes),connection_count=len(links),
        reported_host_memory_bytes=document['dram']['memory_total_bytes'],
        physical_use_established=False,allocation_budgets_established=False,bandwidth_measured=False,
        target_program_executed=False,first_stage_complete=False,diagnostics=document['diagnostics'],
        collector_sha256=sha256(Path(target_inventory.__file__).read_bytes()).hexdigest(),
        implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),types_sha256=sha256(Path(H.__file__).read_bytes()).hexdigest(),
        seconds=time.monotonic()-started)
    _durable_bytes(out/'result.json',_json(result),replace=False);return result


class TargetHardwareGraph:
    def __init__(self,path):
        self.path=Path(path).absolute();self.report=json.loads((self.path/'result.json').read_bytes())
        if self.report['schema']!='scar.target-hardware-graph' or self.report['schema_version']!=1:raise ValueError('target graph version differs')
        if self.report['types_sha256']!=sha256(Path(H.__file__).read_bytes()).hexdigest():raise ValueError('target types differ')
        if self.report['implementation_sha256']!=sha256(Path(__file__).read_bytes()).hexdigest():raise ValueError('target builder differs')
        receipt=self.report['inventory'];raw=Path(receipt['uri']).read_bytes()
        if len(raw)!=receipt['size_bytes'] or sha256(raw).hexdigest()!=receipt['sha256']:raise ValueError('target inventory receipt differs')
        self.inventory=json.loads(raw)

    def table(self,receipt,cls):
        payload=(self.path/receipt['path']).read_bytes()
        if len(payload)!=receipt['bytes'] or sha256(payload).hexdigest()!=receipt['sha256']:raise ValueError('target table differs')
        raw=gzip.decompress(payload)
        if len(raw)!=receipt['decoded_bytes'] or sha256(raw).hexdigest()!=receipt['decoded_sha256'] or raw.count(b'\n')!=receipt['records']:
            raise ValueError('decoded target table differs')
        return tuple(decode(cls,json.loads(line),record_tags=H.TARGET_RECORD_TAGS) for line in raw.splitlines())

    def resources(self):
        return tuple(row for table in self.report['nodes'].values() for row in self.table(table,H.TargetResource))

    def connections(self):return self.table(self.report['connections'],H.ResourceConnection)

    def paths(self):return self.table(self.report['paths'],H.PathEndpoint)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',required=True)
    parser.add_argument('--path',action='append',default=[]);parser.add_argument('--inventory');args=parser.parse_args()
    result=build_target_graph(args.out,args.path,inventory=args.inventory)
    print(json.dumps({k:result[k] for k in ('status','resource_count','connection_count','seconds','diagnostics')},indent=2))


if __name__=='__main__':main()
