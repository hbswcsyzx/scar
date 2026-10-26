"""Small metadata/stat freeze only. Never decode EEG/work/program chunks."""
from pathlib import Path
import hashlib,json,subprocess
from run_gate import BASE,ROOT,preload,wire
from scar.analysis.fragment_relations import FragmentInputs,_static_locator
from scar.ir.record_codec import encode
from scar.ir.program.providers import ProviderArtifact,ProviderFactReference
from scar.store.fragment_relations import RelationBudgets
from dataclasses import fields
MAIN=Path('/home/zyf/AAA/scar-worktrees/structured-program-model')
NATIVE=Path('/home/zyf/AAA/scar-worktrees/native-scalar-model/artifacts/experiments/native_capture_batch_attempt03_20261025/result')
SOURCE=Path('/home/zyf/AAA/scar-worktrees/source858-runtime/artifacts/experiments/first_stage_source858_current_20261026/result/connections')
restored=[];metadata_reads=[]
def digest(data):return hashlib.sha256(data).hexdigest()
def record(p):
 p=Path(p).resolve();data=p.read_bytes();return {'path':str(p),'bytes':len(data),'sha256':digest(data)}
def materialize(p,expected=None,size=None):
 p=Path(p)
 if p.exists():return
 if not p.is_relative_to(MAIN/'artifacts'):raise FileNotFoundError('missing external/untracked input '+str(p))
 rel=str(p.relative_to(MAIN))
 found=subprocess.run(['git','cat-file','-e','HEAD:'+rel],cwd=MAIN,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 if found.returncode:raise FileNotFoundError('missing untracked input; no rerun or relocation: '+str(p))
 data=subprocess.check_output(['git','show','HEAD:'+rel],cwd=MAIN)
 if expected is None or digest(data)!=expected or (size is not None and len(data)!=size):raise ValueError('HEAD blob differs from exact original declaration '+str(p))
 p.parent.mkdir(parents=True,exist_ok=True)
 try:
  with p.open('xb') as f:f.write(data)
 except FileExistsError:
  if p.read_bytes()!=data:raise ValueError('concurrent materialization differs')
 restored.append({'path':str(p),'bytes':len(data),'sha256':digest(data),'source':'EXACT_MAIN_HEAD_BLOB_ORIGINAL_URI_NO_INDEX_EDIT'})
def artifact(p,schema):
 p=Path(p)
 if not p.exists() and p.is_relative_to(MAIN/'artifacts/experiments/native_activity_work_memset_main_20261026'):
  stage=json.loads(subprocess.check_output(['git','show','HEAD:artifacts/experiments/native_activity_work_memset_main_20261026/stage-receipts.json'],cwd=MAIN))
  wanted=next(row for row in stage['paths'] if row['path']==str(p.relative_to(MAIN)))
  materialize(p,wanted['sha256'],wanted['bytes'])
 if not p.exists() and schema=='scar.partitioned-ir-bundle':
  original=json.loads((MAIN/'artifacts/experiments/native_activity_work_memset_main_20261026/result/manifest.json').read_bytes())['original_eeg_manifest']
  if str(p)!=original['path']:raise ValueError('original EEG URI differs')
  materialize(p,original['physical_sha256'],original['physical_bytes'])
 if not p.exists() and schema=='scar.capture-coordinates':
  original=json.loads((SOURCE/'source/report.json').read_bytes())['coordinate_binding']
  if str(p)!=original['uri']:raise ValueError('original coordinates URI differs')
  materialize(p,original['sha256'],original['size_bytes'])
 r=record(p);metadata_reads.append(r)
 return ProviderArtifact(r['path'],r['sha256'],r['bytes'],schema)
def statrow(p,sha256=None,size=None,**extra):
 p=Path(p);materialize(p,sha256,size);s=p.stat()
 if p.is_symlink() or p.resolve()!=p or (size is not None and s.st_size!=size):raise ValueError('original path/stat differs '+str(p))
 return {'path':str(p),'sha256':sha256,'bytes':s.st_size,'device':s.st_dev,'inode':s.st_ino,'mtime_ns':s.st_mtime_ns,'ctime_ns':s.st_ctime_ns,**extra}
def main():
 if (BASE/'freeze.json').exists():raise FileExistsError('freeze exists')
 roots={
 'work_manifest':artifact(MAIN/'artifacts/experiments/native_activity_work_memset_main_20261026/result/manifest.json','scar.native-activity-work-report'),
 'original_eeg_manifest':artifact(MAIN/'artifacts/experiments/first_stage_joined_physical_20261023/result/native/bundle-partitions/manifest.json','scar.partitioned-ir-bundle'),
 'native_batch_report':artifact(NATIVE/'report.json','scar.native-capture-batch'),
 'source_report':artifact(SOURCE/'source/report.json','scar.source-invocations'),
 'dispatch_report':artifact(SOURCE/'dispatch/report.json','scar.dispatch-source-associations'),
 'coordinates':artifact(MAIN/'artifacts/experiments/first_stage_current_source_gate_20261023/result/capture-coordinates.json','scar.capture-coordinates')}
 docs={k:json.loads(Path(a.uri).read_bytes()) for k,a in roots.items()}
 entries={a.uri:statrow(a.uri,a.sha256,a.size_bytes,role='ROOT_METADATA') for a in roots.values()}
 planned=[]
 def add(p,sha,size,decoded=None,role='CORE',normal_reads=1):
  entries[str(p)]=statrow(p,sha,size,decoded_bytes=decoded if decoded is not None else size,role=role)
  if normal_reads:planned.append({'path':str(p),'role':role,'stored_bytes':size,'decoded_bytes':decoded if decoded is not None else size,'normal_reads':normal_reads})
 for table in ('instances','edges'):
  for d in docs['original_eeg_manifest']['graphs']['evidence']['tables'][table]['chunks']:
   add(Path(roots['original_eeg_manifest'].uri).parent/d['uri'],d['physical_sha256'],d['physical_bytes'],d['decoded_bytes'],role='ORIGINAL_EEG_'+table.upper())
 for d in docs['native_batch_report']['shards']:
  for field in ('execution','evidence_projection'):
   a=d[field];add(a['uri'],a['sha256'],a['size_bytes'],role='NATIVE_'+field.upper())
 shared=docs['native_batch_report']['shared_program'];add(shared['uri'],shared['sha256'],shared['size_bytes'],role='SHARED_NATIVE_PROGRAM')
 for shard in docs['work_manifest']['shards']:
  for key in ('work_records','evidence','source_receipts'):
   d=shard[key];add(d['uri'],d['stored_sha256'],d['stored_bytes'],d['decoded_bytes'],role='CURRENT_WORK_'+key.upper())
 binding=docs['source_report']['bindings'];binding_path=SOURCE/'source'/binding['path']
 add(binding_path,binding['raw_sha256'],binding['raw_bytes'],role='CURRENT_BINDINGS')
 raw=binding_path.read_bytes()
 if (len(raw),digest(raw))!=(binding['raw_bytes'],binding['raw_sha256']):raise ValueError('bindings metadata differs')
 metadata_reads.append({'path':str(binding_path),'bytes':len(raw),'sha256':digest(raw)})
 bindings=json.loads(raw)['bindings'];witnesses={};bodies={}
 ba=ProviderArtifact(str(binding_path),binding['raw_sha256'],binding['raw_bytes'],'scar.source-invocation-bindings')
 for row in bindings:
  attach=row.get('attachment_witness');attach=attach.get('static_witness',attach) if attach else {}
  for key,target in (('descriptor_witness_locator',row.get('descriptor_witness_locator') or attach.get('descriptor_locator')),('code_source_witness_locator',row.get('code_source_witness_locator') or attach.get('code_source_locator'))):
   if target is None:continue
   loc=_static_locator(target,ProviderFactReference(ba,'#/bindings/'+str(row['binding_index'])+'/'+key));a=loc.artifact
   witnesses[(a.uri,a.sha256)]=(a,loc.decoded_bytes)
  body=row.get('body')
  if body and body.get('canonical_locator'):
   loc=_static_locator(body['canonical_locator'],ProviderFactReference(ba,'#/bindings/'+str(row['binding_index'])+'/body/canonical_locator'));a=loc.artifact
   bodies[(a.uri,a.sha256)]=(a,loc.decoded_bytes)
 for a,decoded in witnesses.values():add(a.uri,a.sha256,a.size_bytes,decoded,role='CODE_SOURCE_WITNESS',normal_reads=0)
 for a,decoded in bodies.values():add(a.uri,a.sha256,a.size_bytes,decoded,role='OPTIONAL_SELECTED_STATIC_GRAPH',normal_reads=0)
 associations=docs['dispatch_report']['observations'];association_path=SOURCE/'dispatch'/associations['path'];association_size=association_path.stat().st_size
 add(association_path,None,association_size,associations['raw_bytes'],role='CURRENT_ASSOCIATIONS')
 inputs=FragmentInputs(**roots)
 (BASE/'selection.json').write_bytes(wire({'inputs':encode(inputs),'expected_work_count':docs['work_manifest']['qualified_single_activities'],'expected_frontier_count':sum(docs['work_manifest']['frontier_counts'].values()),'root_run':docs['work_manifest']['run'],'source_inventory':docs['source_report']['inventory'],'source_runtime_summary':docs['source_report']['summary']}))
 runtime=preload()
 source_and_runtime=[record(p) for p in sorted(set((ROOT/'scar').rglob('*.py'))|{Path(p) for p in runtime})]
 tools=[record(BASE/p) for p in ('run_gate.py','prepare_gate.py','selection.json')]
 limits={f.name:getattr(RelationBudgets(),f.name) for f in fields(RelationBudgets)}
 guard=sum(r['bytes'] for r in source_and_runtime+tools)
 if guard>32_000_000:raise ValueError('guard32MB')
 raw_paths=[m['artifact']['uri'] for m in docs['coordinates']['membership']]
 f={'schema':'scar.fragment-relations-gate-freeze','schema_version':1,'attempt':str(BASE/'attempt01'),'source_and_runtime':source_and_runtime,'tools':tools,'inputs':sorted(entries.values(),key=lambda r:r['path']),'limits':limits,'raw_capture_paths':raw_paths}
 (BASE/'freeze.json').write_bytes(wire(f));fr=record(BASE/'freeze.json')
 core=sum((r['stored_bytes']+r['decoded_bytes'])*r['normal_reads'] for r in planned)
 roots_bytes=2*sum(a.size_bytes for a in roots.values())
 plan={'status':'FROZEN_NOT_RUN','complete_work_denominator':docs['work_manifest']['qualified_single_activities'],'independent_gpu_frontier_denominator':sum(docs['work_manifest']['frontier_counts'].values()),'known_core_single_pass_input_bytes':core+roots_bytes+2*roots['original_eeg_manifest'].size_bytes,'known_single_pass_rows':planned,'core_input_cap':limits['max_core_input_bytes'],'code_source_input_cap':limits['max_code_source_bytes'],'all_input_cap':limits['max_input_bytes'],'unique_code_source_declared_upper':sum(a.size_bytes+d for a,d in witnesses.values()),'code_source_roots':[{'artifact':encode(a),'decoded_bytes':d} for a,d in witnesses.values()],'optional_static_graph_count':len(bodies),'normal_reader_shared_meter':True,'normal_reader_query_count_max':2,'selected_static_graph_reads_max':1,'normal_query_core_reserve':800_000_000,'source_runtime_guard_bytes_per_pass':guard,'guard_passes':3,'guard_input_upper':guard*3+fr['bytes']*3,'maximum_all_input_plus_three_guards':limits['max_input_bytes']+guard*3+fr['bytes']*3,'stored_output_including_sqlite_cap':limits['max_output_bytes'],'worker_seconds':900,'outer_seconds':960,'rss_kib_cap':2097152,'preparation_metadata_reads':metadata_reads,'restored_missing_original_inputs':restored,'no_graph_work_or_eeg_bodies_decoded_during_preparation':True,'future_not_run':True}
 (BASE/'READ_PLAN.json').write_bytes(wire(plan))
 (BASE/'PREPARATION_RECEIPT.json').write_bytes(wire({'status':'FROZEN_NOT_RUN','freeze':fr,'production_sources':[record(ROOT/p) for p in ('scar/ir/execution/fragment_relations.py','scar/ir/execution/fragment_relations_codec.py','scar/store/fragment_relations.py','scar/analysis/fragment_relations.py','scar/analysis/source_native_composition.py')],'source_runtime_guard_bytes_per_pass':guard,'input_stat_count':len(entries),'runtime_files':len(runtime),'known_core_single_pass_input_bytes':plan['known_core_single_pass_input_bytes'],'unique_code_source_declared_upper':plan['unique_code_source_declared_upper'],'restored_missing_original_inputs':restored}))
 print(json.dumps({'freeze':fr,'inputs':len(entries),'known_core':plan['known_core_single_pass_input_bytes'],'witness_unique':plan['unique_code_source_declared_upper'],'guards':guard,'restored':len(restored)}))
if __name__=='__main__':main()
