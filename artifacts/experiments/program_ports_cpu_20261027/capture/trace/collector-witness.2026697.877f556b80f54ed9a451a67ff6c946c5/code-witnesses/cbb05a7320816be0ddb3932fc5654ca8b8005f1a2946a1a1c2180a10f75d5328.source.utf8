"""One opt-in Linux proc/sys topology observation, not a second resource IR.

Names locate provider interfaces. Only retained facts establish relations.
Inventory, actual access, allocation, placement and readiness are independent.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import time

PROFILE = 'SCAR_RESOURCE_TOPOLOGY_V1'
SCHEMA = 'scar.resource-topology'
_LIMITS = {'source_bytes':16_000_000, 'facts':16_384, 'output_bytes':32_000_000,
           'manifest_bytes':1_000_000, 'seconds':10, 'cpus':512, 'blocks':512,
           'nodes':128, 'controllers':128, 'pci_entries':4096}


def _wire(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def _need(value, message):
    if not value:
        raise ValueError('resource topology: ' + message)


def _json(raw):
    def pairs(items):
        result={}
        for key,value in items:
            _need(key not in result,'duplicate JSON key')
            result[key]=value
        return result
    def constant(value):
        raise ValueError('resource topology: non-finite JSON ' + value)
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=constant)


class _Capture:
    def __init__(self):
        self.started = time.monotonic()
        self.facts = []
        self.total = 0
        self.frontiers = []
        self.keys = {}

    def _allowed(self):
        return (self.total < _LIMITS['source_bytes'] and len(self.facts) < _LIMITS['facts']
                and time.monotonic() - self.started <= _LIMITS['seconds'])

    def _fact(self, kind, uri, raw, status, before, **fields):
        if len(self.facts) >= _LIMITS['facts']:
            if 'FACT_BUDGET' not in self.frontiers:self.frontiers.append('FACT_BUDGET')
            return None
        row = {'ordinal':len(self.facts), 'kind':kind, 'uri':str(uri), 'status':status,
               'start_monotonic_ns':before, 'end_monotonic_ns':time.monotonic_ns(), **fields}
        if raw is not None:
            self.total += len(raw)
            row.update(raw_base64=base64.b64encode(raw).decode(), size_bytes=len(raw),
                       sha256=hashlib.sha256(raw).hexdigest())
        self.keys[(kind,str(uri))] = row['ordinal']
        self.facts.append(row)
        return row

    def _read(self, uri, maximum=16384):
        key = ('READ', str(uri))
        if key in self.keys:return self.facts[self.keys[key]]
        before = time.monotonic_ns()
        if not self._allowed():return self._fact('READ',uri,None,'UNAVAILABLE',before,reason='SOURCE_FACT_OR_WALL_BUDGET')
        bound = min(maximum, _LIMITS['source_bytes'] - self.total)
        try:
            with open(uri,'rb') as stream:raw=stream.read(bound)
            # A bounded prefix is explicitly incomplete; never parsed as a full fact.
            status = 'OBSERVED' if len(raw) < bound else 'INCOMPLETE_AT_READ_BOUND'
            return self._fact('READ',uri,raw,status,before,read_bound=bound)
        except OSError as error:
            return self._fact('READ',uri,None,'UNAVAILABLE',before,error_type=type(error).__name__,errno=error.errno)

    def _dir(self, uri, maximum):
        key = ('SCANDIR',str(uri))
        if key in self.keys:return self.facts[self.keys[key]]
        before=time.monotonic_ns()
        if not self._allowed():return self._fact('SCANDIR',uri,None,'UNAVAILABLE',before,reason='SOURCE_FACT_OR_WALL_BUDGET')
        names=[];complete=True
        try:
            with os.scandir(uri) as entries:
                for entry in entries:
                    if len(names)>=maximum:complete=False;break
                    names.append(entry.name)
            raw=_wire(sorted(names))
            if self.total+len(raw)>_LIMITS['source_bytes']:
                return self._fact('SCANDIR',uri,None,'UNAVAILABLE',before,reason='SOURCE_BYTE_BUDGET')
            return self._fact('SCANDIR',uri,raw,'OBSERVED' if complete else 'INCOMPLETE_ENTRY_BOUND',before,
                              representation='SCANDIR_NAMES_JSON_V1',entry_bound=maximum)
        except OSError as error:
            return self._fact('SCANDIR',uri,None,'UNAVAILABLE',before,error_type=type(error).__name__,errno=error.errno)

    def _link(self, uri):
        kind='READLINK' if str(uri).startswith('/proc/self/ns/') else 'REALPATH'
        key=(kind,str(uri))
        if key in self.keys:return self.facts[self.keys[key]]
        before=time.monotonic_ns()
        if not self._allowed():return self._fact(kind,uri,None,'UNAVAILABLE',before,reason='SOURCE_FACT_OR_WALL_BUDGET')
        try:
            extra={}
            if kind=='READLINK':
                a=os.stat(uri);value=os.readlink(uri);b=os.stat(uri)
                if (a.st_dev,a.st_ino)!=(b.st_dev,b.st_ino):raise ValueError('namespace link changed')
                extra={'namespace_dev':b.st_dev,'namespace_inode':b.st_ino}
            else:value=str(Path(uri).resolve(strict=True))
            raw=value.encode('utf8')
            if len(raw)>16384 or self.total+len(raw)>_LIMITS['source_bytes']:
                return self._fact(kind,uri,None,'UNAVAILABLE',before,reason='LINK_BYTE_BUDGET')
            return self._fact(kind,uri,raw,'OBSERVED',before,
                              representation='NAMESPACE_READLINK_STAT_V1' if kind=='READLINK' else 'PATH_RESOLVE_STRICT_V1',**extra)
        except (OSError,RuntimeError,ValueError) as error:
            return self._fact(kind,uri,None,'UNAVAILABLE',before,error_type=type(error).__name__,errno=getattr(error,'errno',None))


def _text(row):
    if row is None or row['status']!='OBSERVED':return None
    try:return base64.b64decode(row['raw_base64'],validate=True).decode('utf8').strip()
    except (UnicodeError,ValueError):return None


def _names(row):
    if row is None or row['status'] not in ('OBSERVED','INCOMPLETE_ENTRY_BOUND'):return []
    return _json(base64.b64decode(row['raw_base64'],validate=True))


def _mounts(text):
    result=[]
    if text is None:return result
    for ordinal,line in enumerate(text.splitlines(),1):
        try:
            left,right=line.split(' - ',1);a=left.split();b=right.split()
            if len(a)<6 or len(b)<3 or not re.fullmatch(r'\d+:\d+',a[2]):raise ValueError()
            result.append({'line':ordinal,'mount_id':int(a[0]),'parent_mount_id':int(a[1]),
                'fsdev':a[2],'root_encoded':a[3],'mountpoint_encoded':a[4],'options':a[5],
                'optional_fields':a[6:],'filesystem':b[0],'mount_source_encoded':b[1],'super_options':b[2:]})
        except (ValueError,IndexError):result.append({'line':ordinal,'status':'UNSUPPORTED_MOUNTINFO_LINE'})
    return result


def _derive(facts):
    index={(f['kind'],f['uri']):f for f in facts}
    def fact(kind,uri):return index.get((kind,str(uri)))
    def text(uri,kind='READ'):return _text(fact(kind,uri))
    def names(uri):return _names(fact('SCANDIR',uri))
    def source(kind,uri):
        f=fact(kind,uri)
        return None if f is None else {'facts_ordinal':f['ordinal'],'observed_uri':str(uri)}
    def fields(base,keys):return {k:{'value':text(str(base)+'/'+k),'source':source('READ',str(base)+'/'+k)} for k in keys}
    relations=[];frontiers=[]
    def relation(kind,left,right,support):
        relations.append({'kind':kind,'from_selector':left,'to_selector':right,'support':support})
    mounts=_mounts(text('/proc/self/mountinfo'))
    for m in mounts:
        if 'fsdev' not in m:continue
        relation('MOUNT_FILESYSTEM_DEVICE',{'mount_id':m['mount_id']},{'fsdev':m['fsdev']},
                 [{'facts_ordinal':fact('READ','/proc/self/mountinfo')['ordinal'],'raw_line':m['line']}])
        if m['filesystem'] in ('nfs','nfs4','cifs','smb3','9p'):
            frontiers.append({'code':'REMOTE_SERVER_BACKING_UNAVAILABLE','mount_id':m['mount_id'],'fsdev':m['fsdev']})
    blocks=[];by_name={};by_dev={}
    for name in names('/sys/class/block')[:_LIMITS['blocks']]:
        base='/sys/class/block/'+name;dev=text(base+'/dev');resolved=text(base,'REALPATH')
        alias=text('/sys/dev/block/'+str(dev),'REALPATH') if dev is not None else None
        row={'name':name,'dev':dev,'sysfs':resolved,'fields':fields(base,('partition','size','queue/logical_block_size','queue/physical_block_size','queue/rotational','device/model','device/vendor','device/type','dm/name','dm/uuid','loop/backing_file')),
             'source':source('READ',base+'/dev'),'slaves':names(base+'/slaves'),'holders':names(base+'/holders'),
             'media':{'status':'UNAVAILABLE','reason':'NO_EXPLICIT_MEDIA_PROPERTY'},
             'udev_advertised_properties':text('/run/udev/data/b'+str(dev)) if dev else None}
        blocks.append(row);by_name[name]=row
        if dev and re.fullmatch(r'\d+:\d+',dev) and alias==resolved and resolved is not None:
            by_dev[dev]=row
            relation('FILESYSTEM_DEVICE_BLOCK',{'fsdev':dev},{'block_dev':dev,'sysfs':resolved},
                     [source('READ',base+'/dev'),source('REALPATH',base),source('REALPATH','/sys/dev/block/'+dev)])
        elif dev:frontiers.append({'code':'BLOCK_DEV_ALIAS_UNAVAILABLE_OR_CHANGED','block':name,'dev':dev})
    for row in blocks:
        base='/sys/class/block/'+row['name'];partition=row['fields']['partition']['value']
        if partition and partition.isdecimal() and int(partition)>0 and row['sysfs']:
            parent_uri=str(Path(row['sysfs']).parent/'dev');parent=text(parent_uri)
            if parent in by_dev:
                relation('PARTITION_PARENT',{'block_dev':row['dev']},{'block_dev':parent},
                         [source('READ',base+'/partition'),source('REALPATH',base),source('READ',parent_uri)])
            else:frontiers.append({'code':'PARTITION_PARENT_UNAVAILABLE','block':row['name'],'parent_dev':parent})
        for slave in row['slaves']:
            target=by_name.get(slave)
            if target and target['dev']:
                relation('BLOCK_SLAVE',{'block_dev':row['dev']},{'block_dev':target['dev']},
                         [source('SCANDIR',base+'/slaves'),target['source']])
            else:frontiers.append({'code':'BLOCK_SLAVE_TARGET_UNAVAILABLE','block':row['name'],'slave':slave})
        if row['fields']['loop/backing_file']['value']:
            frontiers.append({'code':'LOOP_FILE_EXTENTS_AND_BACKING_UNRESOLVED','block':row['name']})
        if row['fields']['dm/uuid']['value']:
            frontiers.append({'code':'MAPPER_SEGMENT_EXTENTS_UNOBSERVED','block':row['name']})
    nvme=[]
    for name in names('/sys/class/nvme')[:_LIMITS['controllers']]:
        base='/sys/class/nvme/'+name;resolved=text(base,'REALPATH');pci=text(base+'/device','REALPATH')
        row={'name':name,'sysfs':resolved,'protocol':'NVME_KERNEL_CLASS','fields':fields(base,('model','serial','firmware_rev','transport','address','subsysnqn','state')),'pci_sysfs':pci,'media':'UNAVAILABLE_NO_EXPLICIT_MEDIA_PROPERTY'}
        nvme.append(row)
        if resolved:
            for block in blocks:
                if block['sysfs'] and str(Path(block['sysfs']).parent)==resolved:
                    relation('NAMESPACE_CONTROLLER',{'block_dev':block['dev']},{'nvme_controller_sysfs':resolved},
                             [source('REALPATH','/sys/class/block/'+block['name']),source('REALPATH',base)])
        if pci:relation('CONTROLLER_DEVICE',{'nvme_controller_sysfs':resolved},{'sysfs':pci},[source('REALPATH',base+'/device')])
    cpus=[]
    for name in names('/sys/devices/system/cpu'):
        if not re.fullmatch(r'cpu\d+',name):continue
        if len(cpus)>=_LIMITS['cpus']:break
        base='/sys/devices/system/cpu/'+name+'/topology';row={'cpu':int(name[3:]),'fields':fields(base,('physical_package_id','die_id','core_id','thread_siblings_list','core_siblings_list'))}
        cpus.append(row)
        package=row['fields']['physical_package_id']['value'];core=row['fields']['core_id']['value']
        die=row['fields']['die_id']['value']
        if package is not None and core is not None and die is not None and all(v.isdecimal() for v in (package,core,die)):
            relation('CPU_PACKAGE_CORE',{'cpu':row['cpu']},{'package':package,'core':core,'die':row['fields']['die_id']['value']},
                     [row['fields'][k]['source'] for k in ('physical_package_id','core_id','die_id')])
    nodes=[]
    for name in names('/sys/devices/system/node'):
        if not re.fullmatch(r'node\d+',name):continue
        if len(nodes)>=_LIMITS['nodes']:break
        base='/sys/devices/system/node/'+name
        node={'node':int(name[4:]),'fields':fields(base,('cpulist','meminfo','distance'))};nodes.append(node)
        cpulist=node['fields']['cpulist']['value']
        if cpulist and all(re.fullmatch(r'\d+(?:-\d+)?',token) for token in cpulist.split(',')):
            for cpu in cpus:
                for token in cpulist.split(','):
                    parts=token.split('-');low=int(parts[0]);high=int(parts[-1])
                    if low<=cpu['cpu']<=high:
                        relation('CPU_NUMA_MEMBERSHIP',{'cpu':cpu['cpu']},{'node':node['node']},[node['fields']['cpulist']['source']]);break
    edac=[]
    for name in names('/sys/devices/system/edac/mc'):
        if not re.fullmatch(r'mc\d+',name):continue
        base='/sys/devices/system/edac/mc/'+name;dimms=[]
        for dimm in names(base):
            if re.fullmatch(r'dimm\d+',dimm):
                dimms.append({'slot':dimm,'fields':fields(base+'/'+dimm,('dimm_mem_type','dimm_dev_type','size','dimm_label','dimm_location'))})
        edac.append({'controller':name,'fields':fields(base,('mc_name','size_mb')),'dimms':dimms})
    pci=[]
    for name in names('/sys/bus/pci/devices'):
        base='/sys/bus/pci/devices/'+name;kind=text(base+'/class')
        if kind is None:continue
        if not (kind.startswith('0x03') or kind.startswith('0x01')):continue
        pci.append({'address':name,'class':kind,'fields':fields(base,('vendor','device','subsystem_vendor','subsystem_device','numa_node','local_cpulist','modalias')),
                    'sysfs':text(base,'REALPATH'),'driver':text(base+'/driver','REALPATH'),
                    'device_memory_technology':'UNAVAILABLE','memory_category':'DEVICE_MEMORY' if kind.startswith('0x03') else None})
    for block in blocks:
        if not block['sysfs']:continue
        controllers=[p for p in pci if p['class'].startswith('0x01') and p['sysfs'] and block['sysfs'].startswith(p['sysfs']+'/')]
        if controllers:
            controller=max(controllers,key=lambda p:len(p['sysfs']))
            relation('BLOCK_CONTROLLER_PCI',{'block_dev':block['dev']},{'pci_address':controller['address']},
                     [source('REALPATH','/sys/class/block/'+block['name']),source('REALPATH','/sys/bus/pci/devices/'+controller['address']),source('READ','/sys/bus/pci/devices/'+controller['address']+'/class')])
    gpu=[]
    for name in names('/proc/driver/nvidia/gpus')[:_LIMITS['controllers']]:
        uri='/proc/driver/nvidia/gpus/'+name+'/information';info=text(uri);properties={}
        if info is not None:
            for line in info.splitlines():
                if ':' in line:
                    key,value=line.split(':',1);properties[key.strip()]=value.strip()
        gpu.append({'provider':'NVIDIA_PROC_INFORMATION','pci_address':name,'properties':properties,
                    'source':source('READ',uri),'memory_category':'DEVICE_MEMORY','memory_technology':'UNAVAILABLE'})
        if any(p['address']==name for p in pci):
            relation('GPU_PROVIDER_PCI',{'gpu_uuid':properties.get('GPU UUID'),'provider_proc_key':name},{'pci_address':name},
                     [source('READ',uri),source('READ','/sys/bus/pci/devices/'+name+'/class')])
    missing=[{'facts_ordinal':f['ordinal'],'uri':f['uri'],'status':f['status']} for f in facts if f['status']!='OBSERVED']
    frontiers.extend([{'code':'HARDWARE_INVENTORY_NOT_ACTUAL_PROGRAM_ACCESS'},
        {'code':'ALLOCATION_NUMA_DEVICE_PLACEMENT_UNPROVEN'}, {'code':'STORAGE_MEDIA_UNAVAILABLE_NOT_INFERRED_FROM_PROTOCOL_OR_ROTATIONAL'},
        {'code':'GPU_MEMORY_TECHNOLOGY_UNAVAILABLE_NOT_ASSUMED_HBM'}, {'code':'BOUNDARY_TOPOLOGY_NOT_CONTINUOUS_OR_ATOMIC'},
        {'code':'HIDDEN_NAMESPACE_REMOTE_BACKING_AND_PRIVILEGED_DETAILS_UNAVAILABLE'}])
    return {'mounts':mounts,'blocks':blocks,'nvme_controllers':nvme,'cpus':cpus,'numa_nodes':nodes,'edac_controllers':edac,
            'pci_devices':pci,'nvidia_provider_identities':gpu,'memory':fields('/proc',('meminfo',)),
            'cpu_sets':fields('/sys/devices/system/cpu',('online','present','possible','offline')),
            'process_observations':fields('/proc/self',('stat','status','cgroup')),
            'namespaces':{k:{'value':text('/proc/self/ns/'+k,'READLINK'),'source':source('READLINK','/proc/self/ns/'+k),
                            'namespace_dev':(fact('READLINK','/proc/self/ns/'+k) or {}).get('namespace_dev'),
                            'namespace_inode':(fact('READLINK','/proc/self/ns/'+k) or {}).get('namespace_inode')} for k in ('mnt','pid','user','net')},
            'enumerated_counts':{'cpu_names':sum(bool(re.fullmatch(r'cpu\d+',n)) for n in names('/sys/devices/system/cpu')),
                'block_names':len(names('/sys/class/block')),'pci_entries':len(names('/sys/bus/pci/devices'))},
            'relations':relations,'unavailable_or_incomplete_facts':missing,'frontiers':frontiers,
            'actual_resource_use_established':False,'allocation_established':False,'resource_readiness_established':False}


def _counts(observations):
    return {'mount_rows':len(observations['mounts']),'block_rows':len(observations['blocks']),
        'nvme_controllers':len(observations['nvme_controllers']),'cpu_rows':len(observations['cpus']),
        'numa_node_rows':len(observations['numa_nodes']),
        'edac_controller_rows':len(observations['edac_controllers']),
        'edac_dimm_rows':sum(len(c['dimms']) for c in observations['edac_controllers']),
        'pci_rows':len(observations['pci_devices']),'gpu_provider_rows':len(observations['nvidia_provider_identities']),
        'relations':len(observations['relations']),
        'unavailable_or_incomplete_facts':len(observations['unavailable_or_incomplete_facts'])}


def capture_resource_topology(root, issuer, incarnation):
    """Called once by the installing witness, never by tensor/event callbacks."""
    _need(type(issuer)is dict and issuer.get('process_id')==os.getpid(),'live issuer required')
    root=Path(root);root.mkdir(mode=0o700)
    c=_Capture()
    for name in ('mnt','pid','user','net'):c._link('/proc/self/ns/'+name)
    for uri in ('/proc/self/stat','/proc/self/status','/proc/self/cgroup','/proc/meminfo','/proc/cpuinfo','/proc/driver/nvidia/version'):
        c._read(uri,1_000_000 if uri.endswith('cpuinfo') else 65536)
    c._read('/proc/self/mountinfo',1_000_000)
    for key in ('online','present','possible','offline'):c._read('/sys/devices/system/cpu/'+key)
    cpu_names=[n for n in _names(c._dir('/sys/devices/system/cpu',_LIMITS['cpus']+128)) if re.fullmatch(r'cpu\d+',n)]
    if len(cpu_names)>_LIMITS['cpus']:c.frontiers.append('CPU_DETAIL_BUDGET')
    for name in cpu_names[:_LIMITS['cpus']]:
        for key in ('physical_package_id','die_id','core_id','thread_siblings_list','core_siblings_list'):
            c._read('/sys/devices/system/cpu/'+name+'/topology/'+key)
    node_names=[n for n in _names(c._dir('/sys/devices/system/node',_LIMITS['nodes']+64)) if re.fullmatch(r'node\d+',n)]
    if len(node_names)>_LIMITS['nodes']:c.frontiers.append('NODE_DETAIL_BUDGET')
    for name in node_names[:_LIMITS['nodes']]:
        for key in ('cpulist','meminfo','distance'):c._read('/sys/devices/system/node/'+name+'/'+key,65536)
    for name in _names(c._dir('/sys/devices/system/edac/mc',_LIMITS['controllers'])):
        if not re.fullmatch(r'mc\d+',name):continue
        base='/sys/devices/system/edac/mc/'+name
        for key in ('mc_name','size_mb'):c._read(base+'/'+key)
        for dimm in _names(c._dir(base,256)):
            if re.fullmatch(r'dimm\d+',dimm):
                for key in ('dimm_mem_type','dimm_dev_type','size','dimm_label','dimm_location'):c._read(base+'/'+dimm+'/'+key)
    c._dir('/sys/dev/block',_LIMITS['blocks'])
    for name in _names(c._dir('/sys/class/block',_LIMITS['blocks'])):
        base='/sys/class/block/'+name;resolved=_text(c._link(base));dev=_text(c._read(base+'/dev'))
        for key in ('partition','size','queue/logical_block_size','queue/physical_block_size','queue/rotational','device/model','device/vendor','device/type','dm/name','dm/uuid','loop/backing_file'):c._read(base+'/'+key)
        c._dir(base+'/slaves',_LIMITS['blocks']);c._dir(base+'/holders',_LIMITS['blocks'])
        if dev and re.fullmatch(r'\d+:\d+',dev):
            c._link('/sys/dev/block/'+dev);c._read('/run/udev/data/b'+dev,32768)
        if resolved and resolved.startswith('/sys/devices/') and _text(c._read(base+'/partition')):
            c._read(str(Path(resolved).parent/'dev'))
    for name in _names(c._dir('/sys/class/nvme',_LIMITS['controllers'])):
        base='/sys/class/nvme/'+name;c._link(base);c._link(base+'/device')
        for key in ('model','serial','firmware_rev','transport','address','subsysnqn','state'):c._read(base+'/'+key)
    for name in _names(c._dir('/sys/bus/pci/devices',_LIMITS['pci_entries'])):
        base='/sys/bus/pci/devices/'+name;kind=_text(c._read(base+'/class'))
        if kind is None or not (kind.startswith('0x03') or kind.startswith('0x01')):continue
        c._link(base);c._link(base+'/driver')
        for key in ('vendor','device','subsystem_vendor','subsystem_device','numa_node','local_cpulist','modalias'):c._read(base+'/'+key)
    for name in _names(c._dir('/proc/driver/nvidia/gpus',_LIMITS['controllers'])):
        c._read('/proc/driver/nvidia/gpus/'+name+'/information')
    observations=_derive(c.facts)
    payloads=[('facts.jsonl',b''.join(_wire(f) for f in c.facts),'scar.resource-topology-provider-fact/1'),
              ('observations.json',_wire(observations),'scar.resource-topology-observations/1')]
    artifacts=[];output=0
    for name,raw,schema in payloads:
        output+=len(raw);_need(output<=_LIMITS['output_bytes'],'output byte budget')
        with (root/name).open('xb') as stream:stream.write(raw)
        artifacts.append({'path':name,'sha256':hashlib.sha256(raw).hexdigest(),'size_bytes':len(raw),'schema':schema})
    doc={'schema':SCHEMA,'schema_version':1,'profile':PROFILE,'status':'CLOSED_WITH_EXPLICIT_FRONTIERS','issuer':dict(issuer),
         'incarnation':incarnation,'boundary':'REGISTRATION','facts':len(c.facts),'source_payload_bytes':c.total,
         'interface_file_bytes_read':sum(f.get('size_bytes',0) for f in c.facts if f['kind']=='READ'),
         'api_representation_bytes':sum(f.get('size_bytes',0) for f in c.facts if f['kind']!='READ'),
         'elapsed_seconds':time.monotonic()-c.started,'budgets':dict(_LIMITS),'artifacts':artifacts,
         'counts':_counts(observations),
         'producer_frontiers':c.frontiers,'source_scope':'target process namespace and visible proc/sys providers at registration; not prior Run',
         'source_build_established':False,'actual_resource_use_established':False,'allocation_established':False,'resource_readiness_established':False}
    raw=_wire(doc);_need(len(raw)<=_LIMITS['manifest_bytes'] and output+len(raw)<=_LIMITS['output_bytes'],'manifest/output budget')
    with (root/'manifest.json').open('xb') as stream:stream.write(raw)
    return {'uri':str(root/'manifest.json'),'sha256':hashlib.sha256(raw).hexdigest(),'size_bytes':len(raw),'schema':SCHEMA}


def read_resource_topology(path, *, expected_sha256):
    """Recompute every parsed observation/relation from the retained fact bytes."""
    path=Path(path)
    _need(path.resolve(strict=True)==path and not path.is_symlink() and path.stat().st_size<=_LIMITS['manifest_bytes'],'manifest path/budget')
    raw=path.read_bytes();_need(hashlib.sha256(raw).hexdigest()==expected_sha256,'manifest SHA')
    doc=_json(raw)
    _need(set(doc)==set('schema schema_version profile status issuer incarnation boundary facts source_payload_bytes interface_file_bytes_read api_representation_bytes elapsed_seconds budgets artifacts counts producer_frontiers source_scope source_build_established actual_resource_use_established allocation_established resource_readiness_established'.split()),'closed manifest fields')
    _need(doc['schema']==SCHEMA and type(doc['schema_version'])is int and doc['schema_version']==1 and doc['profile']==PROFILE
          and doc['status']=='CLOSED_WITH_EXPLICIT_FRONTIERS' and doc['boundary']=='REGISTRATION' and doc['budgets']==_LIMITS,'manifest contract')
    _need(type(doc['issuer'])is dict and type(doc['issuer']['process_id'])is int and type(doc['issuer']['generation'])is int
          and doc['issuer']['generation']==1 and doc['issuer']['process_id']>0
          and type(doc['issuer']['uuid'])is str and re.fullmatch(r'[0-9a-f]{32}',doc['issuer']['uuid'])is not None,'issuer')
    _need(type(doc['facts'])is int and type(doc['source_payload_bytes'])is int
          and type(doc['interface_file_bytes_read'])is int and type(doc['api_representation_bytes'])is int,'exact counts')
    _need(len(doc['artifacts'])==2 and [a['path'] for a in doc['artifacts']]==['facts.jsonl','observations.json'],'exact payload inventory')
    payloads=[];total=len(raw)
    for item in doc['artifacts']:
        _need(set(item)=={'path','sha256','size_bytes','schema'} and item['schema']==
              ('scar.resource-topology-provider-fact/1' if item['path']=='facts.jsonl' else 'scar.resource-topology-observations/1'),'exact artifact fields/schema')
        p=path.parent/item['path'];_need(not p.is_symlink() and p.resolve(strict=True)==p and type(item['size_bytes'])is int
            and 0<=item['size_bytes']<=_LIMITS['output_bytes'] and p.stat().st_size==item['size_bytes'],'payload path/size')
        total+=item['size_bytes'];_need(total<=_LIMITS['output_bytes'],'total output bytes')
        b=p.read_bytes();_need(len(b)==item['size_bytes'] and hashlib.sha256(b).hexdigest()==item['sha256'],'payload SHA')
        payloads.append(b)
    rows=payloads[0].splitlines(keepends=True);_need(len(rows)==doc['facts']<=_LIMITS['facts'],'fact count')
    facts=[];source_total=0;keys=set()
    for ordinal,line in enumerate(rows):
        _need(line.endswith(b'\n') and len(line)<=2_000_000,'complete bounded fact line')
        row=_json(line);_need(type(row['ordinal'])is int and row['ordinal']==ordinal and row['kind'] in ('READ','SCANDIR','REALPATH','READLINK')
             and row['status'] in ('OBSERVED','UNAVAILABLE','INCOMPLETE_AT_READ_BOUND','INCOMPLETE_ENTRY_BOUND')
             and type(row['uri'])is str and row['uri'].startswith(('/proc/','/sys/','/run/udev/data/')),'fact contract')
        _need(set(row)<=set('ordinal kind uri status start_monotonic_ns end_monotonic_ns raw_base64 size_bytes sha256 read_bound representation entry_bound namespace_dev namespace_inode error_type errno reason'.split()),'closed fact fields')
        key=(row['kind'],row['uri']);_need(key not in keys,'duplicate source capture');keys.add(key)
        _need(type(row['start_monotonic_ns'])is int and type(row['end_monotonic_ns'])is int
              and row['end_monotonic_ns']>=row['start_monotonic_ns'],'fact interval')
        if 'raw_base64' in row:
            b=base64.b64decode(row['raw_base64'],validate=True);source_total+=len(b)
            _need(type(row['size_bytes'])is int and len(b)==row['size_bytes'] and hashlib.sha256(b).hexdigest()==row['sha256'],'raw fact bytes/SHA')
            if row['kind']=='SCANDIR':
                ns=_json(b);_need(type(ns)is list and all(type(n)is str and n and '/' not in n and n not in ('.','..') for n in ns)
                    and ns==sorted(set(ns)),'directory names')
            if row['kind']=='READLINK':
                _need(row['uri'] in ['/proc/self/ns/'+k for k in ('mnt','pid','user','net')]
                      and type(row['namespace_dev'])is int and type(row['namespace_inode'])is int,'namespace link/stat facts')
        else:_need(row['status']=='UNAVAILABLE','missing raw bytes without frontier')
        facts.append(row)
    _need(source_total==doc['source_payload_bytes']<=_LIMITS['source_bytes']
          and doc['interface_file_bytes_read']==sum(f.get('size_bytes',0) for f in facts if f['kind']=='READ')
          and doc['api_representation_bytes']==sum(f.get('size_bytes',0) for f in facts if f['kind']!='READ'), 'source payload/read accounting')
    source_index={(r['kind'],r['uri']):r for r in facts}
    stat_text=_text(source_index.get(('READ','/proc/self/stat')))
    if stat_text is not None:
        tail=stat_text[stat_text.rfind(')')+2:].split()
        _need(int(stat_text.split(' ',1)[0])==doc['issuer']['process_id'],'observed stat PID differs from issuer')
        if doc['incarnation'].get('start_ticks') is not None:
            _need(int(tail[19])==doc['incarnation']['start_ticks'],'observed start ticks contradict image incarnation')
    pid_ns=source_index.get(('READLINK','/proc/self/ns/pid'));born_ns=doc['incarnation'].get('pid_namespace')
    if pid_ns and pid_ns['status']=='OBSERVED' and born_ns is not None:
        _need((pid_ns['namespace_dev'],pid_ns['namespace_inode'],_text(pid_ns))==
              (born_ns['device'],born_ns['inode'],born_ns['link']), 'topology namespace contradicts image incarnation')
    observations=_derive(facts)
    _need(_wire(observations)==payloads[1] and _counts(observations)==doc['counts'],'independent raw fact / relation/count derivation differs')
    _need(all(doc[k] is False for k in ('source_build_established','actual_resource_use_established','allocation_established','resource_readiness_established')),'retention cannot grant use/allocation/ready')
    return doc


def resource_topology_members(path, *, expected_sha256):
    path=Path(path);doc=read_resource_topology(path,expected_sha256=expected_sha256)
    members=[{'uri':str(path),'sha256':expected_sha256,'size_bytes':path.stat().st_size,'schema':SCHEMA}]
    members.extend({'uri':str(path.parent/a['path']),'sha256':a['sha256'],'size_bytes':a['size_bytes'],'schema':a['schema']} for a in doc['artifacts'])
    return doc,members


__all__=['PROFILE','SCHEMA','capture_resource_topology','read_resource_topology','resource_topology_members']
