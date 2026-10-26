"""Pin the original automatic G0 window/text/key set; never compile or graph-decode."""
from pathlib import Path
import ast
import gzip
import hashlib
import inspect
import json
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
DATA_ROOT=Path('/home/zyf/AAA/scar-worktrees/structured-program-model')
G0=DATA_ROOT/'artifacts/experiments/lewm_external_entry_g0_20261026'


def canonical(x):return json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
def sha(p):
 p=Path(p);h=hashlib.sha256();n=0
 with p.open('rb')as stream:
  while raw:=stream.read(1048576):h.update(raw);n+=len(raw)
 return {'path':str(p.resolve()),'sha256':h.hexdigest(),'bytes':n}
def save(name,x):
 with(HERE/name).open('xb')as stream:stream.write(canonical(x)+b'\n')
def need(x,msg):
 if not x:raise ValueError(msg)


def main():
 need(not(HERE/'workset.json').exists(),'prepare output must be fresh')
 f=json.loads((G0/'freeze.json').read_bytes());result=json.loads((G0/'result.json').read_bytes())
 transport=json.loads((G0/'catalog-transport.json').read_bytes())
 raw=(G0/'catalog.json.gz').read_bytes();need(sha(G0/'catalog.json.gz')==transport['stored_transport'],'original G0 transport changed')
 data=gzip.decompress(raw);need(len(data)==transport['logical_original']['bytes']and hashlib.sha256(data).hexdigest()==transport['logical_original']['sha256'],'original G0 catalog bytes differ')
 catalog=json.loads(data);window=result['missing_witness_acquisition_window'];keys=[r['entry_key']for r in window['entries']]
 need(len(keys)==len(set(keys))==16 and window['files']==8,'original automatic missing window changed')
 candidates={r['entry_key']:r for r in catalog['candidates']};groups={}
 for row in catalog['groups']:
  if row['entry_key']in keys:groups.setdefault(row['entry_key'],[]).append(row)
 need(all(len(groups.get(k,[]))==1 and not candidates[k]['archive_variants']for k in keys),'window lost its original unique missing-key origins')
 from scar.analysis.source_attachments import SourceAttachments,SourceAttachmentBudget
 from scar.analysis.compiler_witness_archives import CompilerWitnessArchives,CompilerArchiveBudget,ObservedAcquisitionBudget,plan_attachment_witness_acquisition
 from scar.analysis.code_witness import CodeWitnessBudget,CodeWitnessStore
 from scar.ir.program.call_demand import EnteredCallCode
 from scar.ir.record_codec import decode,encode
 from scar.ir.semantics_v2 import SourceSnapshot
 def forbidden(*a,**k):raise AssertionError('prepare forbids graph/CodeType/compile')
 SourceAttachments._view=forbidden;CodeWitnessStore.resolve=forbidden
 for row in f['inputs']:need(sha(row['path'])==row,'original G0 metadata input changed')
 owner=SourceAttachments(f['continuation']['path'],expected_report_sha256=f['continuation']['sha256'],project_root='/home/zyf/AAA/le-wm',budget=SourceAttachmentBudget())
 archives=CompilerWitnessArchives(tuple((r['directory'],r['manifest']['sha256'])for r in f['archives']),budget=CompilerArchiveBudget(max_archives=2))
 origins=tuple(EnteredCallCode(groups[k][0]['process_id'],groups[k][0]['code'])for k in keys)
 plan=plan_attachment_witness_acquisition(owner,archives,origins=origins,budget=ObservedAcquisitionBudget(max_definitions=16,max_requests=48,max_attempts=16,max_elapsed_seconds=180,max_record_bytes=8_000_000,max_report_bytes=8_000_000))
 need(len(plan['requests'])==16 and not plan['frontiers'],'normal attachment request plan has a frontier')
 texts=[]
 for source in plan['source_text_inputs']:
  snapshot=decode(SourceSnapshot,source['snapshot']);original=owner.archived_source(snapshot);text=original['text'].encode('utf-8')
  texts.append({'snapshot':encode(snapshot),'normalized_sha256':hashlib.sha256(text).hexdigest(),'normalized_bytes':len(text),'encoding':original['encoding'],'raw_sha256':original['raw_sha256'],'raw_bytes':original['raw_bytes'],'locator':encode(original['locator']),'declaration':encode(original['declaration']),'owner':original['owner']})
 allkeys={canonical(k):k for row in plan['requests']for k in row['recorded_compile_keys']};preferred={canonical(row['preferred_compile_key']):row['preferred_compile_key']for row in plan['requests']}
 need(len(texts)==8,'automatic window unique source count differs')
 need(owner.measurements().get('graph_artifacts_read',0)==0 and all(all(v==0 for v in s.counts.values())for s in archives._stores.values()),'prepare loaded graph or CodeType')
 workset={'schema':'scar.lewm-archived-compiler-workset/1','G0_root':sha(G0/'result.json'),'G0_catalog_transport':sha(G0/'catalog-transport.json'),'G0_window':window,'origins':[encode(x)for x in origins],'normal_plan':plan,'source_texts':texts,'unique_recorded_compile_keys':[allkeys[k]for k in sorted(allkeys)],'unique_preferred_compile_keys':[preferred[k]for k in sorted(preferred)],'original_groups':817,'original_calls':100438,'selected_entries':16,'unique_source_files':8,'raw_source_bytes':sum(x['raw_bytes']for x in texts),'normalized_source_bytes':sum(x['normalized_bytes']for x in texts),'preferred_compile_key_count':len(preferred),'recorded_compile_key_count':len(allkeys),'normal_owner_measurements':owner.measurements(),'graph_CodeType_compile_lower_target':False}
 save('workset.json',workset)
 for p in HERE.glob('*.py'):ast.parse(p.read_bytes(),filename=str(p))
 print(json.dumps({'status':'WORKSET_PREPARED_NOT_COMPILED','workset':sha(HERE/'workset.json'),'entries':16,'sources':8,'normalized_source_bytes':workset['normalized_source_bytes'],'raw_source_bytes':workset['raw_source_bytes'],'preferred_keys':len(preferred),'recorded_keys':len(allkeys),'owner_measurements':owner.measurements(),'target_imports':[x for x in ('torch','numpy','stable_worldmodel')if x in sys.modules]},sort_keys=True))

if __name__=='__main__':main()
