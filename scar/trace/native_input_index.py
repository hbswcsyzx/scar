"""Streaming full-capture metadata association through existing native IR.

The private SQLite index is disposable authenticated navigation, not an IR or
loadable owner. Canonical associations reuse the original independent checker.
"""
from collections import Counter
from dataclasses import dataclass
import gzip
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import sqlite3
import time
import zlib

from scar.ir.record_codec import encode
from scar.ir.execution.native_port_protocol import attributes,flat_native
from scar.trace.native_tensor_inputs import (_association_members,_json,_canonical,_need,
    read_native_tensor_inputs,NativeInputMetadataSession,_INPUT_OWNER)

_INDEX_OWNER=object()
PROFILE='SCAR_NATIVE_INPUT_METADATA_ASSOCIATION_INDEX_V1'


@dataclass(frozen=True)
class NativeInputIndexBudget:
    max_source_raw_bytes:int=1_500_000_000
    max_index_bytes:int=1_500_000_000
    max_record_bytes:int=4_000_000
    max_rows:int=1_000_000
    max_wall_seconds:int=2400
    max_output_bytes:int=2_000_000_000
    chunk_rows:int=1000
    chunk_bytes:int=8_000_000


class NativeInputIndexSession:
    def __init__(self,key,coordinates,owner,out,budget,progress):
        _need(key is _INDEX_OWNER,'live input index factory required')
        self.coordinates=coordinates;self.owner=owner;self.out=Path(out);self.budget=budget;self.progress=progress
        self.started=time.monotonic();self._key=secrets.token_bytes(32);self.raw_returned=0;self.raw_receipts=[]
        self.counts=Counter();self.frontiers=Counter();self.total_output=0;self.ready=False
        self.out.mkdir();(self.out/'private').mkdir();self.path=self.out/'private/navigation.sqlite';self.db=sqlite3.connect(self.path)
        self.db.execute('PRAGMA journal_mode=OFF');self.db.execute('PRAGMA synchronous=OFF');self.db.execute('PRAGMA page_size=4096')
        _need(self.db.execute('PRAGMA max_page_count='+str(budget.max_index_bytes//4096)).fetchone()[0]==budget.max_index_bytes//4096,'index page cap')
        self.db.execute('CREATE TABLE raw_rows(idx INTEGER PRIMARY KEY,correlation INTEGER,result_id INTEGER,payload BLOB,mac BLOB)')
        self.db.execute('CREATE INDEX correlations ON raw_rows(correlation)')
        self.db.execute('CREATE TABLE cpu(external INTEGER,ordinal INTEGER,payload BLOB,mac BLOB,PRIMARY KEY(external,ordinal)) WITHOUT ROWID')
        self.db.execute('CREATE TABLE rows(idx INTEGER PRIMARY KEY,node INTEGER UNIQUE,result_id INTEGER,parent_result INTEGER,payload BLOB,mac BLOB)')
        self.db.execute('CREATE INDEX result_ids ON rows(result_id)')
        self.db.execute('CREATE TABLE canonical(node INTEGER PRIMARY KEY)')
        self.db.execute('CREATE TABLE associations(row_idx INTEGER,path TEXT,sort_key TEXT,payload BLOB,mac BLOB,PRIMARY KEY(row_idx,path)) WITHOUT ROWID')

    def emit(self,value):
        if self.progress:self.progress(dict(value,metadata_index_elapsed_seconds=time.monotonic()-self.started))

    def packed(self,kind,key,value):
        raw=_canonical(value);_need(len(raw)<=self.budget.max_record_bytes,'metadata index record bound')
        packed=zlib.compress(raw,1)
        return packed,hmac.digest(self._key,_canonical([kind,key])+b'\0'+packed,'sha256')

    def unpacked(self,kind,key,raw,mac):
        self.check();_need(hmac.compare_digest(mac,hmac.digest(self._key,_canonical([kind,key])+b'\0'+raw,'sha256')),'metadata navigation changed')
        decoder=zlib.decompressobj();decoded=decoder.decompress(raw,self.budget.max_record_bytes+1)
        _need(len(decoded)<=self.budget.max_record_bytes and decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail,'metadata navigation envelope bound/EOF')
        return _json(decoded)

    def observe(self,row):
        self.check();idx=row['index'];raw,mac=self.packed('raw',idx,row)
        self.db.execute('INSERT INTO raw_rows VALUES(?,?,?,?,?)',(idx,row['event']['correlation_id'],row['event']['result_id'],raw,mac))
        if idx%4096==0:self.db.commit()

    def _row(self,original,cpu,rf,ea,ka,chunk,line):
        index,event=original['index'],original['event'];leaves=[];retained=[]
        for slot in original['inputs']['slots']:
            self.counts['slot_'+slot['kind']]+=1
            if slot['kind']=='TENSOR':items=[(slot['path'],slot['metadata'],f"/inputs/slots/{slot['ordinal']}/metadata")]
            elif slot['kind']=='TENSOR_LIST':items=[(i['path'],i['metadata'],f"/inputs/slots/{slot['ordinal']}/items/{i['ordinal']}/metadata") for i in slot['items']]
            else:items=[]
            leaves.extend({'path':path,'metadata':meta,'source':{'artifact':chunk,'locator':f'#/lines/{line}'+pointer}} for path,meta,pointer in items)
            skeleton={'ordinal':slot['ordinal'],'kind':slot['kind']}
            if slot['kind'] in ('TENSOR','TENSOR_LIST'):skeleton['tensor_paths']=[i[0] for i in items]
            if slot['kind']=='OPAQUE':skeleton['reason']=slot['reason']
            if slot['kind']=='SCALAR_OPAQUE':skeleton['scalar_kind']=slot['scalar_kind']
            retained.append(skeleton)
        item={'index':index,'metadata':leaves,'node_id':None,'source':{'artifact':chunk,'locator':f'#/lines/{line}'},
            'tree_parent':event['parent_result_id'],'tree_result':event['result_id'],
            'input_availability':original['inputs']['availability'],'retained_inputs':retained}
        self.counts['metadata_paths']+=len(leaves)
        correlation=event['correlation_id']
        if type(correlation)is int and correlation>0:
            _need(self.db.execute('SELECT count(*) FROM raw_rows WHERE correlation=?',(correlation,)).fetchone()[0]==1,'ambiguous tree correlation')
        candidates=cpu(correlation) if type(correlation)is int and correlation>0 else []
        _need(len(candidates)<=1,'ambiguous CPU External id')
        if not candidates:item['frontier']='CPU_EXTERNAL_UNAVAILABLE'
        else:
            ordinal,observed=candidates[0];handle=observed.get('args',{}).get('Record function id')
            matches=rf(handle) if type(handle)is int and handle>0 else []
            _need(len(matches)<=1,'ambiguous ETO RecordFunction id')
            if not matches:item['frontier']='ETO_RF_MISSING'
            else:
                node_ordinal,node=matches[0];attrs=attributes(node)
                _need(attrs.get('tid')==event['record_function_thread_token'],'raw RF thread contradiction')
                name=original['name']+('.'+original['overload_name'] if original['overload_name'] else '')
                _need(node['name']==original['name'] and observed['name']==name,'name contradiction after exact key join')
                if original['inputs']['availability']=='OBSERVED':_need(len(original['inputs']['slots'])==len(node['inputs']['values']),'boxed input arity contradiction')
                item.update(node_id=node['id'],original_node={'artifact':encode(ea),'locator':f'#/nodes/{node_ordinal}'},
                    CPU_bridge={'artifact':encode(ka),'locator':f'#/traceEvents/{ordinal}'},ETO_parent=node['ctrl_deps'])
                self.counts['exact_raw_key_joins']+=1;item['schema_text_present']=bool(attrs.get('op_schema'))
                if not item['schema_text_present']:
                    item['schema_frontier']='REGISTERED_SCHEMA_TEXT_UNAVAILABLE';self.frontiers[item['schema_frontier']]+=1
                try:native_paths={tuple(p['path']):p for p in flat_native(node['inputs']) if p['tensor']}
                except ValueError:item['frontier']='NATIVE_INPUT_STRUCTURE_UNSUPPORTED';native_paths=None
                if native_paths is not None:
                    seen=set()
                    for leaf in leaves:
                        path=tuple(leaf['path']);_need(path not in seen and path in native_paths,'metadata original Tensor path contradiction');seen.add(path)
                        original=native_paths[path];metadata=leaf['metadata']
                        if metadata['sizes'] is not None and metadata['strides'] is not None and metadata['device'] is not None:
                            _need(metadata['sizes']==original['shape'] and metadata['strides']==original['strides']
                                  and metadata['device']['text']==original['value'][5],'metadata geometry contradiction after original path join')
                        self.counts['metadata_at_exact_native_path']+=1
                        epoch={'status':'UNAVAILABLE','reason':'NATIVE_INPUT_PROVIDER_EPOCH_UNAVAILABLE'}
                        if metadata['physical_epoch_reference_observed']:
                            key=(metadata['device']['text'],metadata['provider_allocation_id'])
                            births=self.owner.births.get(key,())
                            _need(len(births)<=1,'ambiguous positive birth for provider allocation epoch')
                            if births:
                                birth=self.owner.get('physical',next(iter(births)))
                                _need(birth['ptr']==metadata['storage_data_ptr'],'pointer contradicts exact provider allocation ID join')
                                epoch={'status':'OBSERVED_PROVIDER_EPOCH_REFERENCE','provider_allocation_id':key[1],
                                    'device':key[0],'source':{'artifact':self.owner.base['artifacts']['physical'],
                                    'locator':'#/lines/'+str(birth['index'])},
                                    'scope':'same owned profiler/result/process/device allocation ID; no offset/range/alias/content/ready claim'}
                                self.counts['provider_epoch_links']+=1
                            else:epoch={'status':'UNAVAILABLE','reason':'ORIGINAL_ALLOCATION_BIRTH_UNAVAILABLE'}
                        leaf['provider_epoch']=epoch
                        if epoch['status']=='UNAVAILABLE':self.frontiers[epoch['reason']]+=1
                    self.frontiers['NATIVE_TENSOR_WITHOUT_EXPOSED_METADATA']+=len(set(native_paths)-seen)
                    item['native_tensor_paths']=len(native_paths)
        if 'frontier' in item:self.frontiers[item['frontier']]+=1
        return item

    def prepare(self):
        from scar.trace.capture_coordinates import _Files
        from scar.trace.native_capture_batch import _RawReader,_JSONStream
        members=_association_members(self.coordinates);root=Path(self.coordinates.report['local_root'])
        archive_raw=(root/'archive-index.json').read_bytes();archive=_json(archive_raw)
        _need(hashlib.sha256(archive_raw).hexdigest()==self.coordinates.report['seed']['archive_sha256'],'archive root changed')
        files=_Files(root,Path(self.coordinates.report['original_root']),archive,self.budget.max_source_raw_bytes)
        capability=self.coordinates.report['native_tensor_input_membership'];manifest=capability['manifest']
        doc=_json(members[manifest['uri']][1].read_bytes());self.companion_manifest=manifest
        retention=read_native_tensor_inputs(manifest['uri'],expected_sha256=manifest['sha256'],
            max_bytes=self.budget.max_source_raw_bytes,max_rows=self.budget.max_rows,on_row=self.observe,_retained_files=files)
        self.db.commit();self.counts['retained_rows']=retention['retained_rows'];self.counts['companion_verified_raw_bytes']=files.total
        ea,ka=[next(v[0] for v in members.values() if v[0].schema==s) for s in ('pytorch.execution-trace.v1','pytorch.kineto.chrome-trace.v1')]
        self.ea=ea;self.ka=ka;reader=_RawReader(self,ka,members[ka.uri][1]);parser=_JSONStream(reader,self.budget.max_record_bytes)
        keys=set();ordinal=0
        try:
            parser.take('{')
            while parser.peek()!='}':
                key=parser.value();_need(type(key)is str and key not in keys,'duplicate Kineto document key');keys.add(key);parser.take(':')
                if key=='traceEvents':
                    parser.take('[')
                    while parser.peek()!=']':
                        event=parser.value();external=event.get('args',{}).get('External id')
                        if event.get('ph')=='X' and event.get('cat') in ('cpu_op','user_annotation') and event.get('pid')==self.coordinates.target_process.pid and type(external)is int and external>0:
                            raw,mac=self.packed('cpu',[external,ordinal],{'ordinal':ordinal,'event':event})
                            self.db.execute('INSERT INTO cpu VALUES(?,?,?,?)',(external,ordinal,raw,mac))
                        ordinal+=1
                        if ordinal%4096==0:self.db.commit()
                        if parser.peek()!=',':break
                        parser.take(',');_need(parser.peek()!=']','trailing Kineto event comma')
                    parser.take(']')
                else:parser.value()
                if parser.peek()!=',':break
                parser.take(',');_need(parser.peek()!='}','trailing Kineto document comma')
            parser.take('}');_need(parser.peek()=='','Kineto trailing data');reader.finish()
        finally:reader.close()
        _need('traceEvents' in keys,'Kineto traceEvents missing')
        def cpu(key):
            return [(ordinal,self.unpacked('cpu',[key,ordinal],raw,mac)['event']) for ordinal,raw,mac in self.db.execute('SELECT ordinal,payload,mac FROM cpu WHERE external=?',(key,)).fetchall()]
        def rf(key):
            return [(self.owner.node_ordinals[node],self.owner.get('node',node)) for node in self.owner.rf_nodes.get(key,())]
        chunks=doc['chunks'];arts=capability['chunks'];cursor=0
        for idx,raw,mac in self.db.execute('SELECT idx,payload,mac FROM raw_rows ORDER BY idx'):
            while idx>=chunks[cursor]['first_index']+chunks[cursor]['rows']:cursor+=1
            _need(chunks[cursor]['first_index']<=idx<chunks[cursor]['first_index']+chunks[cursor]['rows'],'companion index outside declared chunk')
            original=self.unpacked('raw',idx,raw,mac);chunk=chunks[cursor]
            row=self._row(original,cpu,rf,ea,ka,arts[cursor],idx-chunk['first_index']+1)
            packed,seal=self.packed('row',idx,row)
            self.db.execute('INSERT INTO rows VALUES(?,?,?,?,?,?)',(idx,row['node_id'],row['tree_result'],row['tree_parent'],packed,seal))
            if idx%4096==0:self.db.commit();self.emit({'phase':'INPUT_ROWS_JOINED','rows':idx})
        self.db.commit()
        # Parent comparison uses original result IDs only; missing parents stay frontier.
        for idx,node,parent,raw,mac in self.db.execute('SELECT idx,node,parent_result,payload,mac FROM rows WHERE node IS NOT NULL AND parent_result IS NOT NULL'):
            match=self.db.execute('SELECT node FROM rows WHERE result_id=?',(parent,)).fetchall()
            _need(len(match)<=1,'ambiguous metadata parent result')
            row=self.unpacked('row',idx,raw,mac)
            if match and match[0][0] is not None:
                _need(row['ETO_parent']==match[0][0],'event-tree/ETO parent contradiction');self.counts['exact_parent_checks']+=1
            else:self.frontiers['PARENT_OUTSIDE_RETAINED_NATIVE_INPUT_ROWS']+=1
        _need(files.total+retention['raw_bytes']+self.raw_returned<=self.budget.max_source_raw_bytes,'complete metadata raw pass budget')
        self.input_accounting={'companion_verification_raw':files.total,'companion_parse_raw':retention['raw_bytes'],
            'kineto_raw':self.raw_returned,'native_ETO':'reused verified owned acquisition records, no second ETO stream',
            'scope':'complete reader passes; not physical/kernel IO'}
        self.ready=True;self.emit({'phase':'INPUT_INDEX_READY','counts':dict(self.counts)})
        return self

    def _subset(self,shard):
        _need(self.ready,'input source not completely verified');self.check()
        nodes=set()
        for binding in shard.execution.evidence_bindings:
            instance=shard.evidence.instances.get(binding.legacy.instance)
            if instance is not None and instance.metadata.get('provider')=='ETO':nodes.add(instance.metadata['node_id'])
        rows=[]
        for node in nodes:
            found=self.db.execute('SELECT idx,payload,mac FROM rows WHERE node=?',(node,)).fetchone()
            if found:rows.append(self.unpacked('row',found[0],found[1],found[2]))
        return NativeInputMetadataSession(_INPUT_OWNER,{'run':self.coordinates.run.id.value,
            'process':self.coordinates.target_process.id.value,'rows':rows})

    def bind_shard(self,shard):
        subset=self._subset(shard);associations,nodes=subset._candidate(shard)
        for node in nodes:self.db.execute('INSERT INTO canonical VALUES(?)',(node,))
        for row in associations:
            original=self.db.execute('SELECT payload,mac FROM rows WHERE idx=?',(row['row'],)).fetchone()
            source=self.unpacked('row',row['row'],*original)
            leaf=next(x for x in source['metadata'] if x['path']==row['path'])
            row['provider_epoch']=leaf.get('provider_epoch',{'status':'UNAVAILABLE','reason':'NO_EXACT_NATIVE_PATH'})
            key=[row['row'],row['path']];raw,mac=self.packed('association',key,row)
            sort_key='/'.join(str(v).zfill(16) for v in row['path'])
            self.db.execute('INSERT INTO associations VALUES(?,?,?,?,?)',(row['row'],json.dumps(row['path']),sort_key,raw,mac))
        self.db.commit();self.counts['associated_metadata_paths']+=len(associations)
        self.check(shard,associations)
        return associations

    def check(self,shard=None,associations=None):
        # Also supplies the ordinary source-reader liveness/budget interface.
        self.owner.check();_need(time.monotonic()-self.started<=self.budget.max_wall_seconds,'metadata index wall budget')
        if shard is None:return True
        expected,_=self._subset(shard)._expected(shard)
        _need(type(associations)is list and len(associations)==len(expected),'association inventory differs')
        for actual,normal in zip(associations,expected,strict=True):
            base={k:v for k,v in actual.items() if k!='provider_epoch'}
            _need(_canonical(base)==_canonical(normal),'canonical input source/slot/value occurrence differs')
            raw,mac=self.db.execute('SELECT payload,mac FROM rows WHERE idx=?',(normal['row'],)).fetchone()
            source=self.unpacked('row',normal['row'],raw,mac)
            leaf=next(x for x in source['metadata'] if x['path']==normal['path'])
            _need(_canonical(actual['provider_epoch'])==_canonical(leaf.get('provider_epoch',{'status':'UNAVAILABLE','reason':'NO_EXACT_NATIVE_PATH'})),'provider epoch source differs')
        return True

    def finalize(self):
        _need(self.ready,'unverified input index');self.check();tables={};dispositions=Counter()
        def rows():
            for idx,node,raw,mac in self.db.execute('SELECT idx,node,payload,mac FROM rows ORDER BY idx'):
                row=self.unpacked('row',idx,raw,mac);canonical=self.db.execute('SELECT 1 FROM canonical WHERE node=?',(node,)).fetchone() is not None
                row['canonical_status']='CANONICAL_BOUNDARY_AVAILABLE' if canonical else 'CANONICAL_NATIVE_BOUNDARY_UNAVAILABLE'
                for leaf in row['metadata']:
                    associated=self.db.execute('SELECT 1 FROM associations WHERE row_idx=? AND path=?',(idx,json.dumps(leaf['path']))).fetchone() is not None
                    _need(associated or not canonical,'canonical Tensor metadata path lacks its actual port')
                    leaf['association']='ASSOCIATED' if associated else row['canonical_status'];dispositions[leaf['association']]+=1
                yield row
        def associations():
            for idx,path,raw,mac in self.db.execute('SELECT row_idx,path,payload,mac FROM associations ORDER BY row_idx,sort_key'):
                yield self.unpacked('association',[idx,json.loads(path)],raw,mac)
        for table,iterator in [('rows',rows()),('associations',associations())]:
            directory=self.out/table;directory.mkdir();chunks=[];batch=[];size=0;ordinal=0
            def flush():
                nonlocal batch,size,ordinal
                if not batch:return
                raw=b''.join(batch);compressed=gzip.compress(raw,compresslevel=1,mtime=0)
                self.total_output+=len(compressed);_need(self.total_output<=self.budget.max_output_bytes,'metadata output byte budget')
                name=table+'/'+str(len(chunks)).zfill(6)+'.jsonl.gz'
                with (self.out/name).open('xb') as stream:stream.write(compressed)
                chunks.append({'path':name,'first_ordinal':ordinal,'rows':len(batch),'raw_bytes':len(raw),
                    'raw_sha256':hashlib.sha256(raw).hexdigest(),'size_bytes':len(compressed),'sha256':hashlib.sha256(compressed).hexdigest(),
                    'first_row':_json(batch[0]).get('index',_json(batch[0]).get('row')),
                    'last_row':_json(batch[-1]).get('index',_json(batch[-1]).get('row'))})
                ordinal+=len(batch);batch=[];size=0
            for row in iterator:
                raw=_canonical(row)+b'\n';_need(len(raw)<=self.budget.max_record_bytes,'metadata output record bound')
                if batch and (len(batch)>=self.budget.chunk_rows or size+len(raw)>self.budget.chunk_bytes):flush()
                batch.append(raw);size+=len(raw)
            flush();tables[table]={'records':ordinal,'chunks':chunks}
        doc={'schema':'scar.native-input-association-index','schema_version':1,'profile':PROFILE,'status':'PUBLISHED_WITH_OPEN',
            'run':encode(self.coordinates.run.id),'process':encode(self.coordinates.target_process.id),
            'companion':self.companion_manifest,'tables':tables,'counts':{**self.counts,'metadata_dispositions':dict(dispositions),
                'canonical_nodes':self.db.execute('SELECT count(*) FROM canonical').fetchone()[0]},
            'frontiers':dict(self.frontiers),'input_accounting':self.input_accounting,'native_outputs':'UNAVAILABLE_IN_PINNED_API',
            'logical_content_established':False,'alias_established':False,'canonical_allocation_target_established':False,
            'provider_epoch_reference_observed':bool(self.counts.get('provider_epoch_links')),
            'state_effects_established':False,'resource_ready_established':False,'whole_model_established':False}
        raw=_canonical(doc)+b'\n';path=self.out/'manifest.json'
        with path.open('xb') as stream:stream.write(raw)
        return {'artifact':{'uri':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'size_bytes':len(raw),'schema':doc['schema']},'counts':doc['counts'],'frontiers':doc['frontiers']}


def prepare_native_input_metadata_index(coordinates,owner,out,*,budget=None,progress=None):
    from scar.trace.native_capture_batch import _SourceIndex
    limits=budget or NativeInputIndexBudget()
    _need(type(limits)is NativeInputIndexBudget and all(type(v)is int and v>0 for v in vars(limits).values()),'index budgets')
    _need(type(owner)is _SourceIndex and owner._closed_source and owner.base['run']==coordinates.run.id.value,'live verified source acquisition required')
    return NativeInputIndexSession(_INDEX_OWNER,coordinates,owner,out,limits,progress).prepare()


def query_native_input_associations(manifest,*,row=None,node_id=None,native_input=None,limit=10,expected_sha256=None,associations=False):
    path=Path(manifest).absolute();raw=path.read_bytes();_need(len(raw)<=16_000_000,'association manifest bound')
    if expected_sha256 is not None:_need(hashlib.sha256(raw).hexdigest()==expected_sha256,'association manifest SHA')
    doc=_json(raw);_need(doc['schema']=='scar.native-input-association-index' and doc['status']=='PUBLISHED_WITH_OPEN','published association result required')
    _need(type(limit)is int and 1<=limit<=1000,'query limit')
    table='associations' if native_input is not None or associations else 'rows';result=[];visited=0
    for chunk in doc['tables'][table]['chunks']:
        if row is not None and not chunk['first_row']<=row<=chunk['last_row']:continue
        _need(type(chunk['raw_bytes'])is int and 0<=chunk['raw_bytes']<=8_000_000,'association chunk bound')
        p=path.parent/chunk['path'];_need(not p.is_symlink() and p.resolve().is_relative_to(path.parent),'association chunk path')
        stored=p.read_bytes();_need(len(stored)==chunk['size_bytes'] and hashlib.sha256(stored).hexdigest()==chunk['sha256'],'association stored receipt')
        decoded=gzip.decompress(stored);_need(len(decoded)==chunk['raw_bytes'] and hashlib.sha256(decoded).hexdigest()==chunk['raw_sha256'],'association raw receipt')
        for line in decoded.splitlines():
            value=_json(line);visited+=1
            if row is not None and value.get('index',value.get('row'))!=row:continue
            if node_id is not None and value.get('node_id')!=node_id:continue
            if native_input is not None and value.get('native_input')!=native_input:continue
            result.append(value)
            if len(result)>=limit:return {'counts':doc['counts'],'matches':result,'visited':visited,'complete_scan':False,'scope':'published transport only; no owner restored','whole_model_established':False}
    return {'counts':doc['counts'],'matches':result,'visited':visited,'complete_scan':True,'scope':'published transport only; no owner restored','whole_model_established':False}
