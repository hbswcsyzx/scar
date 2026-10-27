"""Navigation/budget preflight only; no raw SHA/session/IR authority granted."""
from pathlib import Path
import gzip,json,hashlib
from scar.ir.execution.native_port_protocol import replay_interfaces,canonical
from scar.trace.native_protocol import _prefix_lines,_closure_ordinals,_selected_chunks,NativeProtocolBudget
from scar.store.bundle_partitions import BundlePartitions
W=Path(__file__).resolve().parents[3]
root=W/'artifacts/experiments/first_stage_lewm_physical_20261023'
parent=W/'artifacts/experiments/first_stage_joined_physical_20261023/result'
coords=json.loads((parent/'capture-coordinates.json').read_bytes())
meta=json.loads(next((root/'trace').glob('dispatch-meta.*.json')).read_bytes())
physical=json.loads(next((root/'trace').glob('tensor-physical-meta.*.json')).read_bytes())
model=json.loads((parent/'capture-model.json').read_bytes())
source={'provider_revision':meta['provider_revision'],'pid':meta['process_id'],'nonce':meta['nonce'],
 'owner_native_tid':meta['owner_native_tid'],'owner_python_ident':meta['owner_python_ident'],
 'first_sequence':1,'max_sequences':16,'root_node':{'id':1,'ctrl_deps':1}}
reads=[]
for key,schema in [('eto','pytorch.execution-trace.v1'),('dispatch','scar.dispatch-observation.events.v1'),('physical','scar.tensor-physical-observation.v1')]:
 member=next(m for m in coords['membership'] if m['artifact']['schema']==schema)
 path=Path(member['local_path']); f=gzip.open(path,'rb');data=f.read(262144); stored=f.fileobj.tell();f.close()
 reads.append({'path':str(path),'decoded_prefix_bytes':len(data),'stored_bytes_read':stored,'complete_sha_verified':False})
 if key=='eto':
  text=data.decode();i=text.index('[',text.index('"nodes":'))+1;nodes=[];decoder=json.JSONDecoder()
  while i<len(text):
   while i<len(text) and text[i] in ' \n\r\t,':i+=1
   try:n,end=decoder.raw_decode(text,i)
   except json.JSONDecodeError:break
   nodes.append(n);i=end
   if n['name'].endswith(':17:span'):break
  source['nodes']=nodes
 else:source[key]=_prefix_lines(data,16,'scar.tensor-physical-observation',meta['process_id'],meta['nonce'] if key=='physical' else None)
interfaces,frontiers=replay_interfaces(source)
requests,hints=_closure_ordinals(source,interfaces,model)
p=BundlePartitions(parent/'native/bundle-partitions/manifest.json');chunks=_selected_chunks(p,requests,NativeProtocolBudget())
a=json.loads((root/'archive-index.json').read_bytes()); archived=a['files']; os=[r for r in archived if '/os/' in r['logical_path']]
plain=[q for q in (root/'trace').iterdir() if q.suffix=='.json' and not q.name.startswith(('kineto','execution-trace'))]
report={'status':'NAVIGATION_BUDGET_PREFLIGHT_ONLY','authoritative_source_validation_performed':False,
 'root_sentinel_navigation_hint_not_verified':True,'read_prefixes':reads,'prefix_raw_bytes':sum(r['decoded_prefix_bytes'] for r in reads),
 'declared_native_three_raw_bytes':sum(m['artifact']['size_bytes'] for m in coords['membership'] if m['artifact']['schema'] in ('pytorch.execution-trace.v1','scar.dispatch-observation.events.v1','scar.tensor-physical-observation.v1')),
 'native_source_raw_limit':600000000,'selected_sequences':16,'interfaces':[{k:i[k] for k in ('sequence','signature_id','signature','source_lines')} for i in interfaces],
 'frontiers':frontiers,'closure_requests':[{'graph':g,'table':t,'ordinals':list(ns)} for (g,t),ns in requests.items()],
 'chunks':chunks,'chunk_count':len(chunks),'chunk_decoded_bytes':sum(c['decoded_bytes'] for c in chunks),'chunk_stored_bytes':sum(c['physical_bytes'] for c in chunks),
 'coordinate_binder':{'max_bytes':1200000000,'max_lines':1100000,'unique_raw_declared_bytes':sum(r['raw_bytes'] for r in archived)+sum(q.stat().st_size for q in plain),
 'archived_stored_bytes':sum(r['compressed_bytes'] for r in archived),'os_second_decoded_bytes':sum(r['raw_bytes'] for r in os),'os_second_stored_bytes':sum(r['compressed_bytes'] for r in os),'decoded_budget':1270000000,'stored_budget':119000000},
 'compile_calls':0,'prepare_calls':0,'target_executions':0}
out=Path(__file__).with_name('preflight.json');out.write_bytes(canonical(report));print(json.dumps({'status':report['status'],'interfaces':len(interfaces),'frontiers':frontiers,'chunks':len(chunks),'chunk_decoded_bytes':report['chunk_decoded_bytes'],'sha256':hashlib.sha256(out.read_bytes()).hexdigest()}))
