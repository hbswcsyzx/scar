"""Declared-input superset from small manifests/reference collections, no payload scan."""
import gzip
import hashlib
import json
from pathlib import Path

OUT=Path(__file__).resolve().parent
ISO=OUT.parents[2]
MAIN=Path('/home/zyf/AAA/scar-worktrees/structured-program-model')
CAT=json.loads((OUT/'catalog.json').read_bytes())
IO=json.loads((OUT/'io_lower_bound.json').read_bytes())
inputs={};reads=[]
def sha(b):return hashlib.sha256(b).hexdigest()
def add(uri,s,d,h,dh=None,role='retained dependency'):
 p=Path(uri).resolve();st=p.stat()
 if p.is_symlink() or st.st_size!=s:raise ValueError('declared size/stat differs '+str(p))
 row=dict(uri=str(p),stored_bytes=s,decoded_bytes=d,stored_sha256=h,decoded_sha256=dh,role=role)
 if str(p) in inputs:
  old=inputs[str(p)]
  if any(old[k]!=row[k] for k in ('stored_bytes','decoded_bytes','stored_sha256')):raise ValueError('same logical URI has conflicting receipts')
 else:inputs[str(p)]=row
 return row
def meta(p):
 p=Path(p);b=p.read_bytes()
 if len(b)>1000000:raise ValueError('small metadata ceiling')
 reads.append(dict(uri=str(p),bytes=len(b),sha256=sha(b)))
 return json.loads(b)
def ref(base,r,role):
 p=Path(r['uri']) if r['external'] else base/r['uri']
 return add(p,r['physical_bytes'],r['decoded_bytes'],r['physical_sha256'],r['decoded_sha256'],role)
manifests=[MAIN/'artifacts/experiments'/r for r in [
 'source_frontend_remainder_publication_20261025/result/publication/manifest.json',
 'source_call_kwargs_publication_20261025/result/publication/manifest.json',
 'first_stage_source_body_revision_20261023/result/publication/manifest.json',
 'first_stage_source_publication_current_20261023/result/publication/manifest.json',
 'first_stage_full_inventory_restored_20261023/result/manifest.json']]
active=None
for index,p in enumerate(manifests):
 m=meta(p);b=p.read_bytes();add(p,len(b),len(b),sha(b),sha(b),'inventory manifest')
 for r in m['files']:ref(p.parent,r,'all source inventory shards, safe superset')
 for name,r in m['components'].items():ref(p.parent,r,'inventory component '+name)
 r=m['components']['structured'];q=Path(r['uri']) if r['external'] else p.parent/r['uri'];b=q.read_bytes();d=gzip.decompress(b)
 if len(b)>1000000 or len(d)>1000000 or sha(b)!=r['physical_sha256'] or sha(d)!=r['decoded_sha256']:raise ValueError('small structured reference collection differs')
 reads.append(dict(uri=str(q),stored_bytes=len(b),decoded_bytes=len(d),stored_sha256=sha(b),decoded_sha256=sha(d)))
 refs=json.loads(d)['value']
 if index==0:active=refs
 for r in refs:ref(p.parent,r,'active or historical construction checkpoint')
if len(active)!=858:raise ValueError('active858 references differ')
encoded=(json.dumps(active,sort_keys=True,ensure_ascii=False,separators=(',',':'))+'\n').encode()
(OUT/'ACTIVE_858_REFS.json').write_bytes(encoded)
for r in IO['lineage']:
 b=r['base_composition'];add(b['path'],b['raw_bytes'],b['decoded_bytes'],b['raw_sha256'],role='ancestor composition root')
for r in IO['required_old_source_program_receipts']:add(r['uri'],r['physical_bytes'],r['decoded_bytes'],r['physical_sha256'],r['decoded_sha256'],'required historical source-program5')
for s in CAT['subjects']:
 r=s['source_program']['receipt'];add(r['path'],r['bytes'],r['decoded_bytes'],r['sha256'],r['decoded_sha256'],'new accepted source-program5')
# Only the three changed source contexts can be requested by publisher/composer.
layer_path=MAIN/'artifacts/experiments/first_stage_source_context_20261022/result/source-layers/index.json';layers=meta(layer_path)
b=layer_path.read_bytes();add(layer_path,len(b),len(b),sha(b),sha(b),'source-layer index')
for s in CAT['subjects']:
 row=[r for r in layers['files'] if r['snapshot']==s['snapshot'] and r['context']==s['context']]
 if len(row)!=1:raise ValueError('exact changed context absent')
 r=row[0];p=layer_path.parent/r['archive'];st=p.stat()
 # Archive physical SHA was independently frozen by the originating successful gate.
 window=ISO/'artifacts/experiments'/('generator_expression_p0_20261025/candidate03' if s['static_graph_operations']==312 else 'string_hold_source_repair_20261025/candidate02')
 frozen=meta(window/'freeze.json');pins=[q for q in frozen['inputs'] if q['path']==str(p)]
 if len(pins)!=1:raise ValueError('original context physical receipt absent')
 q=pins[0];add(p,q['stored_bytes'],q['decoded_bytes'],q['stored_sha256'],q['decoded_sha256'],'changed source context')
store_dir=MAIN/'artifacts/experiments/first_stage_partitioned_operand_routes_20261023/result/code-witnesses';store_path=store_dir/'manifest.json';store=meta(store_path)
b=store_path.read_bytes();add(store_path,len(b),len(b),sha(b),sha(b),'readonly witness manifest')
for r in CAT['source_text_receipts']:add(r['uri'],r['bytes'],r['bytes'],r['sha256'],r['sha256'],'exact changed source text')
for snapshot in [s['snapshot'] for s in CAT['subjects']]:
 modules=[r for r in store['modules'].values() if r['snapshot']==snapshot]
 if len(modules)!=1:raise ValueError('module witness absent')
 a=modules[0]['artifact'];add(store_dir/a['path'],a['bytes'],a['bytes'],a['sha256'],a['sha256'],'readonly module witness')
summary={}
for r in inputs.values():summary[r['role']]=summary.get(r['role'],0)+r['stored_bytes']+r['decoded_bytes']
known=sum(r['stored_bytes']+r['decoded_bytes'] for r in inputs.values())
# Retain the 858 root decoded size as an explicit unknown, independently capped
# by the ordinary per-record input ceiling (96MB); do not read gzip ISIZE.
b=CAT['base']['composition'];add(b['path'],b['bytes'],96000000,b['sha256'],role='source858 root: decoded upper ceiling96MB, not measurement')
upper=sum(r['stored_bytes']+r['decoded_bytes'] for r in inputs.values())
# One owned output-artifact first read can at most consume the declared total
# written stored+decoded output cap; later normal reads are private-session hits.
result=dict(schema='scar.single-construction-read-plan',schema_version=1,status='DESIGN_ONLY_NOT_RUN',inputs=list(inputs.values()),
 declared_retained_input_upper_bytes=upper,unique_known_retained_bytes_before_858_root=known,role_bytes=summary,
 own_new_outputs_first_read_upper_bytes=256000000,metadata_guard_allowance_bytes=16000000,
 no_duplicate_read_total_upper_bytes=upper+256000000+16000000,
 required_session_contract='every exact URI is physically read/decompressed at most once; private in-session verification reuse only; sources/runtime guards separate',
 active_reference_count=858,active_reference_file=dict(uri=str(OUT/'ACTIVE_858_REFS.json'),bytes=len(encoded),sha256=sha(encoded)),
 complete_body_denominator=2217,metadata_reads=reads,graph_composition_context_payload_reads=0)
(OUT/'READ_PLAN.json').write_text(json.dumps(result,sort_keys=True,ensure_ascii=False,indent=2)+'\n')
cat={**CAT,'active_graph_references':result['active_reference_file']}
cat['base']={**cat['base'],'body_collection':{**cat['base']['body_collection'],'pointer':'#/files','nested_collection_field':'bodies'},'active_graph_reference_collection':{'artifact':dict(base_manifest=CAT['base']['inventory'],component='structured'),'pointer':'#/value','declared_count':858,'exact_preparation_copy':result['active_reference_file']}}
(OUT/'catalog.v2.json').write_text(json.dumps(cat,sort_keys=True,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(dict(unique_inputs=len(inputs),known_retained_upper=upper,total_once_upper=result['no_duplicate_read_total_upper_bytes'],roles=summary,active_refs=858)))
