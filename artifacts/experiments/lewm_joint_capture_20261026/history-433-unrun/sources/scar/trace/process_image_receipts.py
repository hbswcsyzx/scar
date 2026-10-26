"""Bounded self-process boundary observations; no source/build or page proof.

Kernel proc handles are preferred. A maps-path fallback is only a locator; its
opened regular FD must match the original dev/inode before any content read.
Hashes describe backing bytes, not loader reads or executed pages/children.
"""
from __future__ import annotations
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time

PROFILE = 'SCAR_PROCESS_IMAGE_RECEIPTS_V1'
SCHEMA = 'scar.process-image-receipts'
_MAP = re.compile(rb'^([0-9a-f]+)-([0-9a-f]+) ([r-][w-][x-][ps]) ([0-9a-f]+) ([0-9a-f]+):([0-9a-f]+) ([0-9]+)(?: +(.*))?$')
_DEFAULTS = {'max_maps_bytes':4_000_000,'max_rows':16384,'max_hash_file_bytes':64_000_000,
             'max_hash_bytes':256_000_000,'max_output_bytes':64_000_000,'max_backing_files':512,
             'max_hash_seconds':30}


def _wire(value):
    return (json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()


def _need(value, detail):
    if not value:raise ValueError(detail)


def _stamp(s):return [s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns]


def incarnation():
    """Read self at this boundary, never an analysis-machine replacement."""
    result={'pid':os.getpid(),'status':'UNAVAILABLE','start_ticks':None,'boot_id':None,'pid_namespace':None}
    raw={};errors=[]
    for name,path in (('stat','/proc/self/stat'),('boot_id','/proc/sys/kernel/random/boot_id')):
        try:
            with open(path,'rb') as stream:data=stream.read(65537)
            _need(len(data)<=65536,'proc incarnation input byte bound')
            raw[name]={'source':path,'base64':base64.b64encode(data).decode(),'sha256':hashlib.sha256(data).hexdigest()}
            if name=='stat':
                _need(int(data.split(b'(',1)[0])==result['pid'],'proc stat pid differs from live self')
                result['start_ticks']=int(data[data.rfind(b')')+2:].split()[19])
            else:result['boot_id']=data.decode('ascii').strip()
        except (OSError,ValueError,IndexError,UnicodeError) as error:errors.append(name+':'+type(error).__name__)
    try:
        path='/proc/self/ns/pid';s=os.stat(path);target=os.readlink(path)
        result['pid_namespace']={'device':s.st_dev,'inode':s.st_ino,'link':target,'source':path}
    except OSError as error:errors.append('pid_namespace:'+type(error).__name__)
    if not errors and result['start_ticks'] is not None and result['boot_id']:result['status']='OBSERVED'
    return {**result,'raw':raw,'errors':errors}


def incarnation_key(value):
    if value.get('status')!='OBSERVED':return None
    ns=value['pid_namespace']
    return value['pid'],value['start_ticks'],value['boot_id'],ns['device'],ns['inode']


def _lines(raw):
    parts=raw.split(b'\n')
    return [part+b'\n' for part in parts[:-1]]+([parts[-1]] if parts[-1] else [])


def _mapping(raw):
    m=_MAP.fullmatch(raw.rstrip(b'\n'))
    if m is None:return None
    return {'start':int(m[1],16),'end':int(m[2],16),'perms':m[3].decode(),
            'offset':int(m[4],16),'device_major':int(m[5],16),'device_minor':int(m[6],16),
            'inode':int(m[7]),'pathname_base64':base64.b64encode(m[8] or b'').decode()}


class ProcessImageReceipts:
    def __init__(self,root,issuer,*,budgets=None):
        self.root=Path(root);self.root.mkdir(mode=0o700)
        self.issuer=dict(issuer);self.limits=dict(_DEFAULTS if budgets is None else budgets)
        _need(set(self.limits)==set(_DEFAULTS) and all(type(n)is int and 0<n<=_DEFAULTS[k] for k,n in self.limits.items()),'invalid process-image budgets')
        self.hash_seconds=0.0;self.hash_bytes=0;self.output_bytes=0;self.snapshots=[];self.backings=[]
        self.artifacts=[];self.cache={};self.closed=False

    def _write(self,name,raw,schema):
        _need(self.output_bytes+len(raw)<=self.limits['max_output_bytes'],'process-image output byte budget')
        path=self.root/name
        with path.open('xb') as stream:stream.write(raw)
        self.output_bytes+=len(raw)
        row={'path':name,'sha256':hashlib.sha256(raw).hexdigest(),'size_bytes':len(raw),'schema':schema}
        self.artifacts.append(row);return row

    def _backing(self,path,mapping=None):
        started=time.monotonic()
        try:return self._backing_impl(path,mapping,started)
        finally:self.hash_seconds+=time.monotonic()-started

    def _backing_impl(self,path,mapping,started):
        result={'status':'UNAVAILABLE','kernel_source':path,'build_id':{'status':'UNAVAILABLE_NOT_COLLECTED'},
                'source_build_association':'UNVERIFIED','scope':'BACKING_FILE_BYTES_AT_BOUNDARY_NOT_EXECUTED_PAGES',
                'content_read_this_boundary':False,'source_method':'PROC_SELF_EXE' if mapping is None else 'PROC_MAP_FILES'}
        if self.hash_seconds+time.monotonic()-started>self.limits['max_hash_seconds']:
            return {**result,'reason':'HASH_WALL_BUDGET'}
        descriptor=None
        try:
            flags=os.O_RDONLY|os.O_CLOEXEC|os.O_NONBLOCK
            try:
                descriptor=os.open(path,flags)
            except OSError as error:
                if mapping is None:raise
                result['proc_map_files_frontier']={'status':'UNAVAILABLE','error_type':type(error).__name__,
                    'errno':error.errno,'source':path}
                name=base64.b64decode(mapping['pathname_base64'],validate=True)
                if not name.startswith(b'/') or name.endswith(b' (deleted)') or b'\\' in name:
                    return {**result,'reason':'MAPPED_PATH_DELETED_ANONYMOUS_OR_ESCAPING_UNSUPPORTED'}
                # This is only a locator. No content is read unless the opened
                # regular FD matches the ORIGINAL maps dev/inode below.
                if not stat.S_ISREG(os.stat(name).st_mode):
                    return {**result,'reason':'PATH_IS_NOT_REGULAR_NO_CONTENT_READ'}
                descriptor=os.open(name,flags)
                result.update(source_method='MAPPED_PATH_FSTAT_MATCH',opened_path_base64=mapping['pathname_base64'])
            with os.fdopen(descriptor,'rb',buffering=0) as stream:
                descriptor=None
                before=os.fstat(stream.fileno())
                _need(stat.S_ISREG(before.st_mode),'NOT_REGULAR_BACKING_NO_CONTENT_READ')
                if mapping is not None:
                    _need((os.major(before.st_dev),os.minor(before.st_dev),before.st_ino)==
                          (mapping['device_major'],mapping['device_minor'],mapping['inode']),'MAPPED_FD_IDENTITY_MISMATCH')
                key=tuple(_stamp(before))
                if key in self.cache:
                    index=self.cache[key]
                    return {**result,'status':'REUSED_SAME_BACKING_STAT','backing_index':index,
                            'observed_stat':list(key),'content_read_this_boundary':False,
                            'hash_source_boundary':self.backings[index]['observed_boundary'],
                            'scope':'HASH_FROM_EARLIER_RECEIPT_SAME_STAT_NOT_REHASHED_THIS_BOUNDARY'}
                if before.st_size>self.limits['max_hash_file_bytes']:return {**result,'reason':'FILE_HASH_BYTE_BUDGET','observed_stat':list(key)}
                if self.hash_bytes+before.st_size>self.limits['max_hash_bytes']:return {**result,'reason':'TOTAL_HASH_BYTE_BUDGET','observed_stat':list(key)}
                if len(self.backings)>=self.limits['max_backing_files']:return {**result,'reason':'BACKING_RECORD_BUDGET'}
                digest=hashlib.sha256();size=0
                while True:
                    if self.hash_seconds+time.monotonic()-started>self.limits['max_hash_seconds']:raise ValueError('HASH_WALL_BUDGET')
                    block=stream.read(min(1_048_576,before.st_size-size+1))
                    if not block:break
                    size+=len(block);self.hash_bytes+=len(block)
                    _need(size<=before.st_size and self.hash_bytes<=self.limits['max_hash_bytes'],'BACKING_GREW_OR_HASH_BUDGET')
                    digest.update(block)
                after=os.fstat(stream.fileno())
                _need(_stamp(before)==_stamp(after) and size==before.st_size,'BACKING_CHANGED_DURING_HASH')
                row={**result,'status':'OBSERVED','sha256':digest.hexdigest(),'size_bytes':size,
                     'before_stat':_stamp(before),'after_stat':_stamp(after),'content_read_this_boundary':True,
                     'observed_boundary':dict(self.current_boundary)}
                index=len(self.backings);self.backings.append(row);self.cache[key]=index
                return {**result,'status':'OBSERVED','backing_index':index,'observed_stat':list(key),
                        'content_read_this_boundary':True,'hash_source_boundary':dict(self.current_boundary)}
        except (OSError,ValueError) as error:
            return {**result,'reason':type(error).__name__+':'+str(error)[:256]}
        finally:
            if descriptor is not None:os.close(descriptor)

    def snapshot(self,phase):
        _need(not self.closed and os.getpid()==self.issuer['process_id'],'process-image owner/lifetime changed')
        _need(phase in ('REGISTRATION','NATIVE_START','NATIVE_CLOSE','COLLECTOR_CLOSE') and
              phase not in {x['phase'] for x in self.snapshots},'duplicate/unknown process-image phase')
        seq=len(self.snapshots);self.current_boundary={'sequence':seq,'phase':phase};born=incarnation()
        known=[incarnation_key(x['incarnation']) for x in self.snapshots if incarnation_key(x['incarnation']) is not None]
        if incarnation_key(born) is not None and known:_need(incarnation_key(born)==known[0],'live process incarnation contradicted')
        item={'sequence':seq,'phase':phase,'monotonic_ns':time.perf_counter_ns(),'incarnation':born,
              'maps_status':'UNAVAILABLE','maps_rows':None,'maps':None,'rows':None,
              'executable':self._backing('/proc/self/exe')}
        try:
            with open('/proc/self/maps','rb') as stream:raw=stream.read(self.limits['max_maps_bytes']+1)
            _need(len(raw)<=self.limits['max_maps_bytes'],'MAPS_BYTE_BUDGET')
            lines=_lines(raw);_need(len(lines)<=self.limits['max_rows'],'MAPS_ROW_BUDGET')
            item['maps']=self._write(f'maps-{seq:04d}.raw',raw,'text/vnd.linux.proc.maps')
            rows=[]
            for ordinal,line in enumerate(lines,1):
                mapping=_mapping(line)
                if mapping is None:backing={'status':'UNAVAILABLE','reason':'MAPS_ROW_FORMAT'}
                elif mapping['inode']==0:backing={'status':'UNAVAILABLE','reason':'ANONYMOUS_OR_JIT_NO_FILE_IDENTITY'}
                else:backing=self._backing('/proc/self/map_files/'+format(mapping['start'],'x')+'-'+format(mapping['end'],'x'),mapping)
                rows.append(_wire({'schema':'scar.process-image-map-row','schema_version':1,'sequence':seq,
                    'ordinal':ordinal,'raw_line_base64':base64.b64encode(line).decode(),'mapping':mapping,'backing':backing}))
            payload=b''.join(rows)
            item['rows']=self._write(f'maps-{seq:04d}.jsonl',payload,'scar.process-image-map-row/1')
            item.update(maps_status='ALL_ORIGINAL_ROWS_RETAINED',maps_rows=len(lines))
        except (OSError,ValueError) as error:item['maps_reason']=type(error).__name__+':'+str(error)[:256]
        self.snapshots.append(item)
        return item

    def close(self):
        _need(not self.closed,'process-image receipts already closed')
        self.closed=True
        doc={'schema':SCHEMA,'schema_version':1,'profile':PROFILE,'issuer':self.issuer,'snapshots':self.snapshots,
             'backings':self.backings,'artifacts':self.artifacts,'budgets':self.limits,
             'actual_backing_bytes_read':self.hash_bytes,'actual_backing_io_seconds':self.hash_seconds,'output_payload_bytes':self.output_bytes,
             'status':'CLOSED_WITH_EXPLICIT_FRONTIERS','source_build_association':'UNVERIFIED',
             'frontiers':['BOUNDARY_SNAPSHOTS_NOT_CONTINUOUS_MAP_LIFETIME','CHILD_PROCESS_IMAGES_UNAVAILABLE',
                          'EXECUTED_PAGES_AND_SOURCE_BUILD_UNVERIFIED','BUILD_ID_NOT_COLLECTED']}
        raw=_wire(doc);_need(len(raw)<=1_000_000,'process-image manifest byte budget')
        self._write('manifest.json',raw,SCHEMA)
        return {'uri':str(self.root/'manifest.json'),'sha256':hashlib.sha256(raw).hexdigest(),'size_bytes':len(raw),'schema':SCHEMA}


def _payload(path,limit):
    _need(not path.is_symlink() and path.is_file() and path.resolve(strict=True)==path and path.stat().st_size<=limit,'unsafe/oversize process-image payload')
    with path.open('rb') as stream:raw=stream.read(limit+1)
    _need(len(raw)<=limit,'process-image input grew beyond budget')
    return raw


def read_process_image_receipts(path,*,expected_sha256):
    """Check retained boundary facts only; never read current proc or binaries."""
    p=Path(path);raw=_payload(p,1_000_000)
    _need(not p.is_symlink() and len(raw)<=1_000_000 and hashlib.sha256(raw).hexdigest()==expected_sha256,'process-image manifest differs')
    d=json.loads(raw);_need(d.get('schema')==SCHEMA and d.get('schema_version')==1 and d.get('profile')==PROFILE,'process-image schema/profile')
    _need(d['status']=='CLOSED_WITH_EXPLICIT_FRONTIERS' and d['source_build_association']=='UNVERIFIED','process-image overstates scope')
    _need(set(d['budgets'])==set(_DEFAULTS) and all(type(n)is int and 0<n<=_DEFAULTS[k] for k,n in d['budgets'].items()),'process-image budgets exceed supported scope')
    _need(len(d['snapshots'])<=4 and len(d['artifacts'])<=8 and
          all(type(a['size_bytes'])is int and a['size_bytes']>=0 for a in d['artifacts']) and
          sum(a['size_bytes'] for a in d['artifacts'])<=d['budgets']['max_output_bytes'],
          'process-image aggregate record/output budget differs')
    artifacts={}
    for r in d['artifacts']:
        name=Path(r['path']);_need(name.name==r['path'] and r['path'] not in artifacts,'unsafe/duplicate process-image member')
        q=p.parent/name
        _need(type(r['size_bytes'])is int and 0<=r['size_bytes']<=d['budgets']['max_output_bytes'],'process-image declared payload bound')
        data=_payload(q,r['size_bytes'])
        _need(not q.is_symlink() and len(data)==r['size_bytes'] and hashlib.sha256(data).hexdigest()==r['sha256'],'process-image payload differs')
        artifacts[r['path']]=(r,data)
    known=[];phases=set()
    allowed=('REGISTRATION','NATIVE_START','NATIVE_CLOSE','COLLECTOR_CLOSE')
    for seq,item in enumerate(d['snapshots']):
        _need(item['sequence']==seq and item['phase'] in allowed and item['phase'] not in phases,'process-image phase/order differs');phases.add(item['phase'])
        born=item['incarnation']
        _need(born['status'] in ('OBSERVED','UNAVAILABLE'),'unknown incarnation status')
        _need(type(born['pid'])is int and born['pid']>0,'invalid observed process pid')
        if born['status']=='OBSERVED':
            _need(type(born['start_ticks'])is int and born['start_ticks']>=0 and type(born['boot_id'])is str and born['boot_id'],
                  'observed incarnation fields are not exact')
            _need(set(born['raw'])=={'stat','boot_id'} and born['pid_namespace'] is not None and not born['errors'],
                  'observed incarnation lacks its actual proc facts')
        for name,fact in born['raw'].items():
            raw=base64.b64decode(fact['base64'],validate=True)
            _need(hashlib.sha256(raw).hexdigest()==fact['sha256'],'incarnation raw receipt differs')
            if name=='stat':
                _need(fact['source']=='/proc/self/stat','unknown stat source')
                if born['start_ticks'] is not None:
                    _need(int(raw.split(b'(',1)[0])==born['pid'] and int(raw[raw.rfind(b')')+2:].split()[19])==born['start_ticks'],
                          'incarnation stat fields differ')
                else:_need(born['status']=='UNAVAILABLE' and born['errors'],'missing proc start ticks without frontier')
            elif name=='boot_id':
                _need(fact['source']=='/proc/sys/kernel/random/boot_id','unknown boot source')
                if born['boot_id'] is not None:_need(raw.decode('ascii').strip()==born['boot_id'],'boot identity differs')
                else:_need(born['status']=='UNAVAILABLE' and born['errors'],'missing boot identity without frontier')
            else:raise ValueError('unknown incarnation proc source')
        if born.get('pid_namespace') is not None:
            ns=born['pid_namespace'];_need(ns['source']=='/proc/self/ns/pid' and ns['link']=='pid:['+str(ns['inode'])+']','pid namespace observation differs')
        key=incarnation_key(born)
        if key is not None:known.append(key)
        _need(born['pid']==d['issuer']['process_id'],'process-image pid differs')
        executable=item['executable']
        _need(executable['kernel_source']=='/proc/self/exe','executable fact is not the kernel self handle')
        if executable.get('backing_index') is not None:
            index=executable['backing_index']
            _need(type(index)is int and 0<=index<len(d['backings']) and
                  executable['observed_stat']==d['backings'][index]['before_stat'],'executable backing reference differs')
            receipt=d['backings'][index]
            _need(executable['status'] in ('OBSERVED','REUSED_SAME_BACKING_STAT') and
                  executable['content_read_this_boundary']==(executable['status']=='OBSERVED') and
                  executable['hash_source_boundary']==receipt['observed_boundary'] and
                  receipt['observed_boundary']['sequence']<=seq,'executable cache/read boundary differs')
            if executable['status']=='OBSERVED':
                _need(receipt['observed_boundary']=={'sequence':seq,'phase':item['phase']},'old executable hash labeled as a fresh read')
        if item['maps_status']=='ALL_ORIGINAL_ROWS_RETAINED':
            _need(item['maps']==artifacts[item['maps']['path']][0] and item['rows']==artifacts[item['rows']['path']][0]
                  and item['maps']['schema']=='text/vnd.linux.proc.maps' and item['rows']['schema']=='scar.process-image-map-row/1',
                  'snapshot references another payload schema/receipt')
            source=_lines(artifacts[item['maps']['path']][1])
            rows=artifacts[item['rows']['path']][1].splitlines()
            _need(len(source)==len(rows)==item['maps_rows'],'process-image row inventory differs')
            for ordinal,(line,row) in enumerate(zip(source,rows),1):
                value=json.loads(row)
                _need(value['ordinal']==ordinal and value['sequence']==seq and
                      base64.b64decode(value['raw_line_base64'],validate=True)==line and value['mapping']==_mapping(line),
                      'original maps row/order/fields differ')
                index=value['backing'].get('backing_index')
                if index is not None:
                    _need(type(index)is int and 0<=index<len(d['backings']),'unknown backing receipt')
                    receipt=d['backings'][index];observed=value['backing']['observed_stat'];mapping=value['mapping']
                    expected='/proc/self/map_files/'+format(mapping['start'],'x')+'-'+format(mapping['end'],'x')
                    backing=value['backing']
                    _need(backing['source_method'] in ('PROC_MAP_FILES','MAPPED_PATH_FSTAT_MATCH') and
                          backing['content_read_this_boundary']==(backing['status']=='OBSERVED') and
                          backing['hash_source_boundary']==receipt['observed_boundary'], 'backing read/cache observation scope differs')
                    _need(backing['status'] in ('OBSERVED','REUSED_SAME_BACKING_STAT') and
                          receipt['observed_boundary']['sequence']<=seq, 'backing source is from an unavailable/future observation')
                    if backing['status']=='OBSERVED':
                        _need(receipt['observed_boundary']=={'sequence':seq,'phase':item['phase']}, 'old mapped hash labeled as a fresh read')
                    if backing['source_method']=='MAPPED_PATH_FSTAT_MATCH':
                        _need(backing['opened_path_base64']==mapping['pathname_base64'] and
                              backing['proc_map_files_frontier']['status']=='UNAVAILABLE', 'path fallback lost its original locator/permission frontier')
                    _need(value['backing']['kernel_source']==expected and observed==receipt['before_stat'] and
                          (os.major(observed[0]),os.minor(observed[0]),observed[1])==
                          (mapping['device_major'],mapping['device_minor'],mapping['inode']),
                          'mapped row borrows another backing identity/receipt')
        else:_need(item['maps_status']=='UNAVAILABLE' and 'maps_reason' in item,'unknown maps status')
    _need([allowed.index(x['phase']) for x in d['snapshots']]==sorted(allowed.index(x['phase']) for x in d['snapshots']),'process-image phase chronology differs')
    _need(d['snapshots'] and d['snapshots'][0]['phase']=='REGISTRATION' and d['snapshots'][-1]['phase']=='COLLECTOR_CLOSE','process-image lifecycle endpoints missing')
    _need(not known or all(x==known[0] for x in known),'process incarnation contradicted across boundaries')
    for r in d['backings']:
        _need(r['status']=='OBSERVED' and r['before_stat']==r['after_stat'] and
              r['size_bytes']==r['before_stat'][2] and re.fullmatch('[0-9a-f]{64}',r['sha256']) and
              r['build_id']=={'status':'UNAVAILABLE_NOT_COLLECTED'} and r['source_build_association']=='UNVERIFIED' and
              r['scope']=='BACKING_FILE_BYTES_AT_BOUNDARY_NOT_EXECUTED_PAGES' and r['content_read_this_boundary'] is True and
              r['source_method'] in ('PROC_MAP_FILES','MAPPED_PATH_FSTAT_MATCH','PROC_SELF_EXE') and
              (r['kernel_source']=='/proc/self/exe' or re.fullmatch('/proc/self/map_files/[0-9a-f]+-[0-9a-f]+',r['kernel_source'])),
              'backing receipt exceeds its observation contract')
    _need(0<=d['actual_backing_bytes_read']<=d['budgets']['max_hash_bytes'] and
          sum(x['size_bytes'] for x in d['backings'])<=d['actual_backing_bytes_read'], 'backing input budget/accounting differs')
    return d
