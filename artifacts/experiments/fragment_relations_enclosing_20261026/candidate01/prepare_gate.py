"""Only old small declarations, six exact root headers and current stat pins."""
from pathlib import Path
from dataclasses import fields
import hashlib,json
from run_gate import ROOT,BASE,preload,wire
from scar.store.fragment_relations import RelationBudgets
OLD=ROOT/'artifacts/experiments/fragment_relations_implementation_20261026/candidate02'
NEW=BASE.parent
reads=[]
def digest(b):return hashlib.sha256(b).hexdigest()
def read(path):
 b=path.read_bytes();reads.append({'path':str(path),'bytes':len(b),'sha256':digest(b)});return json.loads(b)
def record(path):
 b=path.read_bytes();return {'path':str(path),'bytes':len(b),'sha256':digest(b)}
def main():
 if (BASE/'freeze.json').exists():raise FileExistsError('freeze exists')
 old=read(OLD/'freeze.json');oldplan=read(OLD/'READ_PLAN.json');selection=read(OLD/'selection.json')
 for a in selection['inputs'].values():
  d=read(Path(a['uri']));r=reads[-1]
  if (r['bytes'],r['sha256'])!=(a['size_bytes'],a['sha256']):raise ValueError('exact original root changed '+a['uri'])
 selection.update(relation_transport_version=2,selection='COMPLETE_PHYSICAL_WORK; EXACT_NATIVE_AND_ENCLOSING_SEPARATELY')
 (BASE/'selection.json').write_bytes(wire(selection))
 inputs=[];missing=[]
 for oldrow in old['inputs']:
  p=Path(oldrow['path'])
  if not p.exists():missing.append(str(p));continue
  s=p.stat()
  if p.is_symlink() or p.resolve()!=p or s.st_size!=oldrow['bytes']:raise ValueError('exact path/stat differs '+str(p))
  inputs.append({**oldrow,'device':s.st_dev,'inode':s.st_ino,'mtime_ns':s.st_mtime_ns,'ctime_ns':s.st_ctime_ns})
 if missing:
  (BASE/'MISSING_INPUTS.json').write_bytes(wire({'missing':missing,'main_not_changed':True}));raise FileNotFoundError(str(missing[:5]))
 runtime=preload()
 source_runtime=[record(p) for p in sorted(set((ROOT/'scar').rglob('*.py'))|{Path(p) for p in runtime})]
 tools=[record(BASE/n) for n in ('run_gate.py','prepare_gate.py','selection.json')]
 budget=RelationBudgets(max_seconds=1500)
 limits={f.name:getattr(budget,f.name) for f in fields(budget)}
 guard=sum(r['bytes'] for r in source_runtime+tools)
 if guard>32_000_000:raise ValueError('per-pass guard32MB')
 freeze={'schema':'scar.fragment-relations-gate-freeze','schema_version':2,'attempt':str(BASE/'attempt01'),'source_and_runtime':source_runtime,'tools':tools,'inputs':inputs,'limits':limits,'raw_capture_paths':old['raw_capture_paths']}
 (BASE/'freeze.json').write_bytes(wire(freeze));fr=record(BASE/'freeze.json')
 grouped={}
 for row in oldplan['known_single_pass_rows']:
  v=grouped.setdefault(row['role'],{'stored_bytes':0,'decoded_bytes':0,'reads':0})
  v['stored_bytes']+=row['stored_bytes']*row['normal_reads'];v['decoded_bytes']+=row['decoded_bytes']*row['normal_reads'];v['reads']+=row['normal_reads']
 plan={'status':'FROZEN_NOT_RUN','relation_transport_version':2,'complete_work_denominator':selection['expected_work_count'],'independent_gpu_frontier_denominator':selection['expected_frontier_count'],'original_run':selection['root_run'],'known_core_single_pass_input_bytes':oldplan['known_core_single_pass_input_bytes'],'single_pass_stored_and_decoded_by_role':grouped,'exact_original_input_stats':len(inputs),'parent_proof_source':'Same fresh owned strict original EEG pass; actual fields plus ordinal/digest/namespace in fresh disposable index, no success bool/old-index input','additional_parent_original_input_bytes':0,'discarded_second_read_plan':'../PARENT_READ_PLAN.json (1,039,309,676B avoided, not executed)','normal_query_count_max':6,'normal_query_core_reserve':1_200_000_000,'selected_static_graph_reads_max':1,'static_graph_code_source_bound':64_000_000,'code_source_roots':oldplan['code_source_roots'],'core_input_cap':limits['max_core_input_bytes'],'code_source_input_cap':limits['max_code_source_bytes'],'all_input_cap':limits['max_input_bytes'],'source_runtime_guard_bytes_per_pass':guard,'guard_passes':3,'guard_bytes_upper':guard*3+fr['bytes']*3,'all_input_plus_three_guards_cap':limits['max_input_bytes']+guard*3+fr['bytes']*3,'sqlite_output_cap_is_included':True,'stored_output_cap':limits['max_output_bytes'],'worker_seconds':1500,'outer_seconds':1560,'rss_kib_cap':2097152,'time_basis':'Old full producer716.8s; v2 additionally validates23655 actual parent fields and attempts retained context/static-source bridge for up to12541 more work.1500 is a proposed ceiling, not measured completion/prediction.','preparation_metadata_reads':reads,'preparation_graph_work_eeg_raw_decodes':0,'main_or_old_artifacts_changed':False,'future_not_run':True}
 (BASE/'READ_PLAN.json').write_bytes(wire(plan))
 receipt={'status':'FROZEN_NOT_RUN','freeze':fr,'four_changed_production_sources':[record(ROOT/n) for n in ('scar/ir/execution/fragment_relations.py','scar/ir/execution/fragment_relations_codec.py','scar/store/fragment_relations.py','scar/analysis/fragment_relations.py')],'source_native_unchanged':record(ROOT/'scar/analysis/source_native_composition.py'),'input_stats':len(inputs),'runtime_files':len(runtime),'guard_bytes_per_pass':guard,'worker_seconds':1500,'outer_seconds':1560}
 (BASE/'PREPARATION_RECEIPT.json').write_bytes(wire(receipt))
 print(json.dumps(receipt,indent=2))
if __name__=='__main__':main()
