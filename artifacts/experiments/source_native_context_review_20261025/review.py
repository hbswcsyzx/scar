"""Independent stored-byte/root review plus one bounded derived source sample."""
from pathlib import Path
from hashlib import sha256
from collections import Counter
import gzip,json,time
B=Path(__file__).resolve().parents[3]
O=Path(__file__).resolve().parent
G=B/'artifacts/experiments/source_native_context_gate_20261025/attempt01'
NAV=G/'navigation';MP=NAV/'manifest.json'
START=time.monotonic();reads=Counter()
def read(path,kind='metadata'):
 raw=path.read_bytes();reads[kind]+=len(raw);return raw
def receipt(path,raw):return {'path':str(path),'bytes':len(raw),'sha256':sha256(raw).hexdigest()}
raw=read(MP);assert len(raw)==47237 and sha256(raw).hexdigest()=='8cef855ccfe081830a4548aaee80b4226d10aab22d4aa5e102cd1ebe18be8fa6'
m=json.loads(raw);assert m['status']=='PUBLISHED' and m['schema']=='scar.source-native-context-navigation' and m['schema_version']==1
root_ref={'uri':str(MP),'size_bytes':len(raw),'sha256':sha256(raw).hexdigest(),'schema':m['schema']}
R=json.loads(read(G/'result.json'));L=json.loads(read(G/'launch-result.json'))
assert L['exit_code']==0 and L['status']=='EXIT0_RETAINED_CONTEXT_MODEL_OPEN'
assert R['navigation']==root_ref and R['status']=='PUBLISHED_RETAINED_CONTEXT_SAMPLES_MODEL_OPEN'
assert R['navigation_counts']==m['counts'] and R['sample_queries']==5 and R['queries_are_samples']
assert R['object_identity_established'] is False and R['old_scope_obligations_closed'] is False and R['whole_program_model']=='OPEN'
assumption='HISTORICAL_SCAR_COLLECTOR_EXECUTION_SOURCE_UNRECORDED'
assert R['historical_collector_assumption_retained'] and m['historical_assumption']==assumption
assert m['counts']['source_associations']==79592 and m['counts']['native_sequences']==39796
assert m['counts']['classifications']=={'MODELED_COMPLETE_REFERENCE':37895,'MODELED_PARTIAL_REFERENCE':1901}
assert m['source_retention']['rows']==79592
scope=m['inputs']['scope_ledger_manifest'];scope_path=Path(scope['uri']);sr=read(scope_path)
assert len(sr)==scope['size_bytes'] and sha256(sr).hexdigest()==scope['sha256']
ledger=json.loads(sr)
assert m['inputs']['scope_revision'] in json.dumps(ledger['scope'],sort_keys=True)
# Equal coordinate bytes must retain both original URI identities.
sc,nc=(m['inputs'][k] for k in ['source_coordinates','native_coordinates'])
assert sc['sha256']==nc['sha256'] and sc['uri']!=nc['uri']
queries={i:json.loads(read(G/f'query-{i}.json')) for i in [1,4,244,2331,3182]}
query_summary=[]
for i,wrapped in queries.items():
 q=wrapped['result'];assert q['sequence']==i and wrapped['selection']['sequence']==i
 assert q['navigation']==root_ref and q['inputs']==m['inputs'] and q['scope_revision']==m['inputs']['scope_revision']
 assert assumption in q['assumptions'] and assumption in q['frontiers']
 assert q['status']==('CONTEXT_UNRESOLVED' if i==4 else 'RETAINED_CONTEXT')
 assert q['relationship']==(None if i==4 else 'RETAINED_SOURCE_CONTEXT')
 assert {x['phase'] for x in q['source_contexts']}=={'span','output'}
 if i==4:assert all(x['invocation'] is None and x['definition'] is None for x in q['source_contexts'])
 else:
  assert 'ACTUAL_FORMAL_ROUTING_UNVERIFIED' in q['frontiers'] and 'RETURN_VALUE_ROUTING_UNVERIFIED' in q['frontiers']
  assert 'FUNCTION_ENVIRONMENT_UNVERIFIED' in q['frontiers'] and 'STATE_EFFECTS_UNVERIFIED' in q['frontiers']
 for k in ['invoke','normal_return']:
  x=q[k];assert x is not None and x['occurrence']==x['binding']['operation']
 a,b=q['invoke'],q['normal_return']
 assert a['execution']==b['execution'] and a['binding']['legacy']==b['binding']['legacy']
 assert a['binding']['source']['artifact']==b['binding']['source']['artifact']
 assert b['binding']['source']['locator']==a['binding']['source']['locator']+'/outputs'
 assert a['binding']['source'] in q['native_facts'] and b['binding']['source'] in q['native_facts']
 assert a['occurrence']['value'].endswith(':'+str(i)+':invoke') and b['occurrence']['value'].endswith(':'+str(i)+':return')
 query_summary.append({'sequence':i,'status':q['status'],'relationship':q['relationship'],'roles':wrapped['selection']['roles'],
  'invoke_instance':a['binding']['legacy']['instance']['value'],'invoke_source':a['binding']['source'],'normal_return_source':b['binding']['source'],
  'source_phases':sorted(x['phase'] for x in q['source_contexts']),'namespace_fields':[x['namespace_field'] for x in q['source_contexts']],
  'frontiers':q['frontiers'],'root_binding_exact':True,'old_scope_binding_exact':True})
assert 'ZERO_TENSOR_FROM_SAVED_NATIVE_DECLARATION' in queries[1]['selection']['roles']
assert 'NATIVE_ONLY_FROM_FINAL_GATE_NEGATIVE' in queries[3182]['selection']['roles']
# Choose one source data chunk covering both original source report phases of2331.
q=queries[2331]['result'];wanted={x['association']['line']:x for x in q['source_contexts']}
start=1;selected=None;selected_start=None
for c in m['chunks']['source']:
 if min(wanted)>=start and max(wanted)<start+c['rows']:
  selected=c;selected_start=start;break
 start+=c['rows']
assert selected is not None
chunks=[];chunk_bytes=None
for kind,descriptors in m['chunks'].items():
 for c in descriptors:
  rel=Path(c['uri']);assert not rel.is_absolute() and '..' not in rel.parts
  p=NAV/rel;raw=read(p,'stored_chunks')
  assert len(raw)==c['stored_bytes'] and sha256(raw).hexdigest()==c['stored_sha256'],p
  assert c['rows']<=1000
  chunks.append({'kind':kind,'uri':c['uri'],'stored_bytes':len(raw),'stored_sha256':sha256(raw).hexdigest(),'rows_declared':c['rows']})
  if kind=='source' and c['uri']==selected['uri']:chunk_bytes=raw
assert len(chunks)==160 and len({x['uri'] for x in chunks})==160
assert {p.relative_to(NAV).as_posix() for p in NAV.rglob('*.jsonl.gz')}=={x['uri'] for x in chunks}
assert {k:sum(c['rows'] for c in ds) for k,ds in m['chunks'].items()}=={'source':79592,'native':39796,'index':39796}
index=m['chunks']['index'];assert len(index)==40
next_seq=1
for c in index:
 assert c['first_sequence']==next_seq and c['last_sequence']-c['first_sequence']+1==c['rows'];next_seq=c['last_sequence']+1
assert next_seq==39797
# One decompression only. Derived source rows retain original serialized lines.
decoded=gzip.decompress(chunk_bytes);reads['one_derived_sample_decoded_bytes']+=len(decoded)
assert len(decoded)==selected['decoded_bytes'] and sha256(decoded).hexdigest()==selected['decoded_sha256']
lines=decoded.splitlines(keepends=True);assert len(lines)==selected['rows']
samples=[]
for number,context in sorted(wanted.items()):
 line=lines[number-selected_start];doc=json.loads(line)
 samples.append({'original_line':number,'local_row_zero_based':number-selected_start,'line_sha256_with_newline':sha256(line).hexdigest(),
  'line_sha256_without_newline':sha256(line.rstrip(b'\n')).hexdigest(),'expected_context':context,'retained_row':doc})
# Persist the one sample before final shape checks, so no second chunk decode is needed.
with (O/'sample.json').open('x') as f:json.dump({'chunk':selected,'original_first_line':selected_start,'samples':samples},f,indent=2,sort_keys=True);f.write('\n')
with (O/'stored-checks.json').open('x') as f:json.dump({'root':root_ref,'chunks':chunks,'counts':m['counts'],'declared_index_rows':39796,'query_summaries':query_summary,'reads':dict(reads)},f,indent=2,sort_keys=True);f.write('\n')
print(json.dumps({'status':'STORED_ROOT_AND160CHUNKS_PASS','stored_chunk_bytes':reads['stored_chunks'],'one_sample_decoded_bytes':len(decoded),
 'sample_chunk':selected['uri'],'sample_row_keys':[list(x['retained_row']) for x in samples],
 'sample_sequence_phase':[{k:s['retained_row'].get(k) for k in ['sequence','phase','marker','index','region_namespace']} for s in samples],
 'sample_hash_matches':[(x['line_sha256_with_newline']==x['expected_context']['association']['line_sha256'],x['line_sha256_without_newline']==x['expected_context']['association']['line_sha256']) for x in samples],
 'seconds':time.monotonic()-START},indent=2))
