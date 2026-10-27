"""Small-metadata and source SHA preparation only; no profiling/normal owner creation."""
import hashlib
import json
from pathlib import Path
import subprocess

HERE=Path(__file__).resolve().parent
TREE=HERE.parents[2]
OLD=TREE/'artifacts/experiments/lewm_external_entry_publication_resume02_20261026'
WORKER=TREE/'artifacts/experiments/lewm_external_source_entries_20261026'
PRIOR=Path('/home/zyf/AAA/scar-worktrees/source858-runtime/artifacts/experiments/first_stage_source858_current_20261026/inputs.json')
def canonical(x):return json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()+b'\n'
def ref(p):
 p=Path(p);raw=p.read_bytes();return {'path':str(p),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
def save(name,value):
 with (HERE/name).open('xb') as f:f.write(canonical(value))
def main():
 old=json.loads((OLD/'inputs.json').read_bytes());prior=json.loads(PRIOR.read_bytes())
 attempts=[json.loads(x) for x in (WORKER/'worker/attempts.jsonl').read_text().splitlines() if x]
 good=[(i,row) for i,row in enumerate(attempts,1) if row['status']=='SUCCEEDED'];i,first=good[0]
 assert first==old['successes'][0] and json.loads((WORKER/f'worker/attempt-{i:05d}/result.json').read_bytes())==first
 sp5=Path(first['program']['uri']);assert sp5.is_file() and not sp5.is_symlink() and sp5.stat().st_size==first['program']['physical_bytes']
 closure=json.loads((OLD/'static-closure-preflight.json').read_bytes())
 for row in closure['bound_static_references']:
  p=Path(row['path']);s=p.stat()
  assert p.is_file() and not p.is_symlink() and p.resolve(strict=True)==p
  assert [s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns]==row['stat']
 limits={'input_stored_plus_decoded_bytes':8_000_000_000,'address_space_bytes':8*1024**3,
  'worker_seconds':480,'outer_seconds':540,'output_bytes':64_000_000,'max_record_bytes':128_000_000,
  'source_and_control_hash_bytes':64_000_000}
 config={'schema':'scar.external-entry-publication-bounded-profile-inputs/1','budgets':limits,
  'plain858':old['plain858'],'plain858_inputs_receipt':ref(PRIOR),'continuation':old['continuation'],
  'archives':old['archives'],'project_root':old['project_root'],'first_success':first,
  'selected_terminal':ref(WORKER/f'worker/attempt-{i:05d}/result.json'),
  'worker_attempts':ref(WORKER/'worker/attempts.jsonl'),'historical_SP5_paths':[x['source_program']['uri'] for x in prior['post843_programs']],
  'static_closure':ref(OLD/'static-closure-preflight.json'),'artifact_read_roots':old['artifact_read_roots'],
  'source_inputs_calls':2,'read_structure_calls':1,'normal_selected_SP5_reader_calls':1,
  'preparation_SP5_payload_bytes_read':0,'preparation_owner_or_profile_calls':0,'restoration_allowed':False}
 save('inputs.json',config)
 save('read-plan.json',{'schema':'scar.external-entry-publication-bounded-profile-read-plan/1','status':'PREPARED_NOT_RUN',
  'budgets':limits,'setup':'normal CompositionIndex of original plain858, exact continuation+three archives and catalog; resolve only mechanical first successful original SP5',
  'setup_cost':'measured separately at runtime; prior215.60s included all26 entry resolves and is not asserted for this different bounded setup',
  'source_inputs_profiles':2,'source_inputs_scope':'same genuine owned project called once in each separate cProfile; no fake dict benchmark',
  'read_structure_profiles':1,'first_SP5':first['program'],
  'selected_SP5_normal_reader_minimum_stored_plus_decoded_bytes':2*first['program']['physical_bytes']+first['program']['decoded_bytes'],
  'repeat_normal_work':'ancestor/old body revision verification remains intact; repeated reads/hashes/guards count every pass',
  'IO_families':{'metadata':'composition, inventory manifest/header/component, continuation/provider reports, archive manifest',
   'graph':'exact declared historical/selected SP5, CP1/CP2, original source graph artifacts',
   'code':'readonly compiler archive module/text payloads and archived source snapshot receipts'},
  'IO_phase_attribution':'setup;source_inputs_first;source_inputs_repeat;context_and_SP5_read;read_structure. Physical/plain and decoded-gzip views separately tagged in each family.',
  'source_control_IO':'both explicit SHA checks separately bounded64MB; Python runtime imports excluded from payload. Actual imported SCAR module paths must belong to frozen main source set.',
  'output':'function aggregates only, no locals/source/code payload/Tensor values; no raw .pstats with payload or model dumps',
  'no_graph_decode_during_prepare':True,'no_production_change':True,'no_target_compile_lower':True,
  'current369749_binding':'NOT_RUN','full26_time_fraction':'NOT_MEASURED_BY_SINGLE_ENTRY_PROFILE'})
 for name in ('run.py','prepare.py'):
  compile((HERE/name).read_bytes(),str(HERE/name),'exec')
 sources=[ref(p) for p in sorted((TREE/'scar').rglob('*.py'))]
 assert sources==json.loads((OLD/'freeze.json').read_bytes())['sources'],'production source bytes differ from last real publication gate'
 controls=[HERE/n for n in ('run.py','run.sh','prepare.py','inputs.json','read-plan.json','README.md')]
 controls += [PRIOR,WORKER/'inputs.json',WORKER/'worker/attempts.jsonl',WORKER/f'worker/attempt-{i:05d}/result.json',
  WORKER/'worker/manifest.json',OLD/'static-closure-preflight.json',OLD/'freeze.json',OLD/'failure.json',OLD/'ROOT_STOP_DECISION.json',
  TREE/'artifacts/analysis/lewm_entry_publication_performance_20261026/WORK_ORDER.md',Path(old['continuation']['path']),
  TREE/'artifacts/experiments/first_stage_dependency_sources_20261023/result/admissions.json']
 controls += [Path(x['manifest']['path']) for x in old['archives']]
 head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=TREE,text=True).strip()
 save('freeze.json',{'schema':'scar.external-entry-publication-bounded-profile-freeze/1','producer_tree':str(TREE),
  'prepared_main_HEAD':head,'production_source_bytes_equal_previous_resume02':True,
  'sources':sources,'control_inputs':[ref(p) for p in controls],
  'selected_original_SP5_receipt':'inputs.json; no extra preparation payload hash; the ordinary reader validates actual physical/decoded SHA once',
  'no_production_gate_started_by_prepare':True})
 save('freeze-receipt.json',{'freeze':ref(HERE/'freeze.json'),'sources':len(sources),
  'source_bytes':sum(x['bytes'] for x in sources),'controls':len(controls),
  'control_bytes':sum(p.stat().st_size for p in controls),'preflight':'only syntax, original small metadata/terminal selection, exact ancestor stat, source/control SHA'})
 print(json.dumps({'freeze':ref(HERE/'freeze.json'),'sources':len(sources),'controls':len(controls),
   'selected_program_stored':first['program']['physical_bytes'],'selected_program_decoded':first['program']['decoded_bytes'],
   'prepared_not_run':True}))
if __name__=='__main__':main()
