"""Prepare only; no SP5 read, source text load, baseline exec or benchmark."""
import hashlib,json,subprocess
from pathlib import Path
HERE=Path(__file__).resolve().parent;TREE=HERE.parents[2]
PREVIOUS=TREE/'artifacts/experiments/lewm_entry_publication_profile_20261026'
def ref(p):
 p=Path(p);r=p.read_bytes();return {'path':str(p),'sha256':hashlib.sha256(r).hexdigest(),'bytes':len(r)}
def save(n,v):
 with (HERE/n).open('x') as f:json.dump(v,f,sort_keys=True,separators=(',',':'));f.write('\n')
def main():
 original=json.loads((PREVIOUS/'inputs.json').read_bytes());first=original['first_success'];store=first['code_witness']['witness']['store']
 manifest=Path(store['path']);raw=manifest.read_bytes();assert hashlib.sha256(raw).hexdigest()==store['sha256'] and len(raw)==store['bytes']
 archive=json.loads(raw);snapshot=first['entry_reference']['snapshot']
 rows=[r for r in archive['sources'].values() if r['snapshot']==snapshot];assert len(rows)==1
 source_ref=rows[0]['artifact'];textpath=manifest.parent/source_ref['path']
 assert textpath.is_file() and textpath.stat().st_size==source_ref['bytes']
 p=Path(first['program']['uri']);assert p.is_file() and p.stat().st_size==first['program']['physical_bytes']
 baseline=ref(HERE/'baseline/_validation.py');assert baseline['sha256']=='f1c640101d6d9ffc8baa7a647cad2862353fcdcd196c698f1f97b7764be04ede'
 current=ref(TREE/'scar/ir/v2/_validation.py');assert current['sha256']!=baseline['sha256']
 head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=TREE,text=True).strip()
 gitold=subprocess.check_output(['git','show',head+':scar/ir/v2/_validation.py'],cwd=TREE)
 assert hashlib.sha256(gitold).hexdigest()==baseline['sha256']
 limits={'input_stored_plus_decoded_bytes':512_000_000,'address_space_bytes':8*1024**3,
  'worker_seconds':480,'outer_seconds':540,'output_bytes':32_000_000,'max_record_bytes':128_000_000}
 config={'schema':'scar.validation-primitive-same-SP5-comparison/1','budgets':limits,
  'baseline_source':baseline,'baseline_source_git':{'commit':head,'path':'scar/ir/v2/_validation.py'},
  'candidate_source':current,'program':first['program'],'snapshot':snapshot,'archive_store':store,
  'archive_directory':str(manifest.parent),'archived_source_receipt':{'path':str(textpath),'sha256':source_ref['sha256'],'bytes':source_ref['bytes']},
  'artifact_read_roots':[str(TREE/'artifacts'),'/home/zyf/AAA/scar-worktrees/source858-runtime/artifacts'],
  'modes':['baseline_clean','candidate_clean','candidate_profile'],'structure_calls_per_child':1,
  'normal_SP5_reads_per_child':1,'new_qualified_graph_runtime_or_CodeWitness':False,
  'baseline_profile_reference':ref(PREVIOUS/'read_structure.json')}
 save('inputs.json',config)
 save('read-plan.json',{'schema':'scar.validation-primitive-comparison-read-plan/1','status':'PREPARED_NOT_RUN','budgets':limits,
  'SP5_normal_reader_calls':3,'SP5_stored_bytes_each':first['program']['physical_bytes'],
  'SP5_decoded_bytes_each':first['program']['decoded_bytes'],
  'SP5_total_minimum_stored_plus_decoded':3*(2*first['program']['physical_bytes']+first['program']['decoded_bytes']),
  'archive_text_reads':3,'archive_text_stored_plus_decoded':6*source_ref['bytes'],
  'archive_manifest_reads':3,'archive_manifest_stored_plus_decoded':6*store['bytes'],
  'source_control_IO':'parent and each3 child hash all pins before/after, actual stored hash bytes included in512MB; child metadata reads included; Python import IO excluded',
  'payload_families':'metadata archive manifest, code exact archived text, graph original SP5, source_control pins',
  'no_project_catalog_or_CompositionIndex_constructor':True,'no_source_graph_or_capture_rescan':True,
  'baseline_override':'only benchmark replacement of _record_errors bytecode extracted from exact old SCAR module; current globals and ordinary validators unchanged',
  'timed_region':'SourceProgram.read_structure; cProfile only third child; same SHA observation of bytes made by normal internal canonical codec check, no extra to_dict/encode',
  'hash_observer':'hash CPU/wall included and separately recorded, not subtracted as an estimated speedup',
  'old_profile_comparison':'79.986s is heavy cProfile reference; clean baseline/new wall are compared only to each other',
  'prepare_reads_SP5_or_text':False,'qualification':'benchmark only, no runtime/CodeWitness/new graph qualification'})
 for name in ('run.py','prepare.py'):compile((HERE/name).read_bytes(),str(HERE/name),'exec')
 sources=[ref(p) for p in sorted((TREE/'scar').rglob('*.py'))]
 old=json.loads((PREVIOUS/'freeze.json').read_bytes())['sources'];d1={r['path']:r for r in old};d2={r['path']:r for r in sources}
 assert set(d1)==set(d2)
 changed=[p for p in d1 if d1[p]!=d2[p]]
 assert set(changed)=={str(TREE/'scar/ir/v2/_validation.py'),str(TREE/'scar/analysis/source_frontend_worklist.py')},changed
 controls=[HERE/n for n in ('run.py','run.sh','prepare.py','inputs.json','read-plan.json','README.md','baseline/_validation.py')]
 controls += [PREVIOUS/'inputs.json',PREVIOUS/'read_structure.json',manifest]
 save('freeze.json',{'schema':'scar.validation-primitive-same-SP5-freeze/1','prepared_main_HEAD':head,'sources':sources,
  'control_inputs':[ref(p) for p in controls],'source_changes_from_profile53184':changed,
  'comparison_implementation_change':str(TREE/'scar/ir/v2/_validation.py'),
  'unrelated_changed_module_forbidden_at_runtime':'scar.analysis.source_frontend_worklist',
  'baseline_original_SHA':baseline['sha256'],'candidate_SHA':current['sha256'],
  'SP5_text_payload_receipts':'inputs.json; ordinary readers verify each child; no extra preparation payload hash/read'})
 save('freeze-receipt.json',{'freeze':ref(HERE/'freeze.json'),'sources':len(sources),'source_bytes':sum(x['bytes'] for x in sources),
  'controls':len(controls),'control_bytes':sum(x.stat().st_size for x in controls),'prepared_not_run':True})
 print(json.dumps({'freeze':ref(HERE/'freeze.json'),'sources':len(sources),'controls':len(controls),'candidate':current,'baseline':baseline,'prepared_not_run':True}))
if __name__=='__main__':main()
