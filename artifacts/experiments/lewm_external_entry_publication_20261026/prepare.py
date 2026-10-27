"""Metadata-only gate preparation. No ordinary graph/factory/lower/target run."""
import hashlib
import json
from pathlib import Path
import subprocess

HERE=Path(__file__).resolve().parent
TREE=HERE.parents[2]
WORKER=TREE/'artifacts/experiments/lewm_external_source_entries_20261026'
PRIOR=Path('/home/zyf/AAA/scar-worktrees/source858-runtime/artifacts/experiments/first_stage_source858_current_20261026/inputs.json')

def canonical(x):
    return json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
def ref(p):
    p=Path(p);raw=p.read_bytes()
    return {'path':str(p),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
def save(name,x):
    with (HERE/name).open('xb') as f:f.write(canonical(x)+b'\n')

def main():
    cfg=json.loads((WORKER/'inputs.json').read_bytes())
    prior=json.loads(PRIOR.read_bytes())
    final=json.loads((WORKER/'worker/manifest.json').read_bytes())
    attempts=[json.loads(x) for x in (WORKER/'worker/attempts.jsonl').read_text().splitlines() if x]
    good=[x for x in attempts if x['status']=='SUCCEEDED']
    assert len(good)==26 and len(attempts)==33 and final['window']==50 and final['unattempted_window_entries']==17
    original={r['path']:r for r in prior['inputs']}
    plain=original[prior['published_composition_uri']]
    assert plain['bytes']==17109069 and plain['sha256']=='45569e930c3fe03a6d2cf4c26a93491c7ce9b496d25aab5fae09767deb91fe9b'
    # Only stat/header checks: no decoding of plain858, SP5 or parent graphs here.
    with Path(plain['path']).open('rb') as f:f.seek(-4,2);plain_declared_decoded=int.from_bytes(f.read(4),'little')
    allowed={
      'first_stage_current_source_gate_20261023','first_stage_full_inventory_plain_20261023',
      'first_stage_full_inventory_restored_20261023','first_stage_partitioned_composition_bindings_20261023',
      'first_stage_source_body_revision_20261023','first_stage_source_context_20261022',
      'first_stage_source_language_bodies_20261023','first_stage_source_language_bodies_attempt03_20261023',
      'first_stage_source_membership_ancestor_20261023','first_stage_source_publication_current_20261023',
      'first_stage_source_publication_current_attempt02_20261023','first_stage_source_publication_current_attempt03_20261023',
      'first_stage_source_publication_current_attempt04_20261023','first_stage_source_revision_current_20261025',
      'first_stage_tuple_key_bodies_20261023','first_stage_tuple_key_heap_attempt02_20261023',
      'source_call_kwargs_publication_20261025','source_frontend_remainder_attempt02_20261025',
      'source_frontend_remainder_composition_resume02_20261025','source_frontend_remainder_publication_20261025'}
    recovery=[]
    for row in prior['inputs']:
        p=Path(row['path'])
        if p.is_relative_to(TREE/'artifacts/experiments') and p.relative_to(TREE/'artifacts/experiments').parts[0] in allowed and not p.exists():
            recovery.append(row)
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=TREE,text=True).strip()
    # Check exact blob availability/size only; SHA256 is checked before O_EXCL restore at gate time.
    names=[head+':'+str(Path(x['path']).relative_to(TREE)) for x in recovery]
    if names:
        result=subprocess.run(['git','cat-file','--batch-check=%(objecttype) %(objectsize)'],cwd=TREE,
            input='\n'.join(names)+'\n',text=True,stdout=subprocess.PIPE,check=True)
        for row,line in zip(recovery,result.stdout.splitlines()):
            assert line==f"blob {row['bytes']}",(row['path'],line)
    limits={'input_stored_plus_decoded_bytes':8_000_000_000,'address_space_bytes':8*1024**3,
       'worker_seconds':1200,'outer_seconds':1260,'output_bytes':128_000_000,
       'max_record_bytes':128_000_000,'source_and_control_hash_bytes':64_000_000}
    config={'schema':'scar.lewm-external-entry-publication-gate-inputs/1','worker_root':str(WORKER),
       'continuation':cfg['continuation'],'archives':cfg['archives'],'project_root':cfg['project_root'],
       'plain858':plain,'plain858_inputs_receipt':ref(PRIOR),'recovery_commit':head,
       'missing_static_restoration_whitelist':recovery,'successes':good,'budgets':limits,
       'artifact_read_roots':[str(TREE/'artifacts'),'/home/zyf/AAA/scar-worktrees/source858-runtime/artifacts',
                              '/home/zyf/AAA/scar-worktrees/source-call-model/artifacts'],
       'source_qualification':{'historical_static_process':272038,'current369749_binding':'NOT_RUN',
          'window':50,'statuses':{'SUCCEEDED':26,'UNSUPPORTED':7,'NOT_ATTEMPTED':17},
          'original_groups':817,'original_calls':100438,'first_stage_complete':False}}
    save('inputs.json',config)
    s=sum(x['program']['physical_bytes'] for x in good);d=sum(x['program']['decoded_bytes'] for x in good)
    save('read-plan.json',{'schema':'scar.external-entry-publication-read-plan/1','status':'PREPARED_NOT_RUN',
       'budgets':limits,'successful_SP5_count':len(good),'SP5_stored_bytes':s,'SP5_decoded_bytes':d,
       'SP5_normal_reader_passes':2,'SP5_physical_hash_passes_per_normal_read':1,
       'SP5_minimum_actual_stored_plus_decoded':4*s+2*d,
       'plain858_declared_gzip_trailer_decoded_bytes':plain_declared_decoded,
       'plain858_ordinary_index_constructions':4,
       'plain858_minimum_stored_plus_decoded':4*(plain['bytes']+plain_declared_decoded),
       'missing_declared_static_files':len(recovery),'missing_static_stored_bytes':sum(x['bytes'] for x in recovery),
       'continuation_guard_one_pass_stored_plus_decoded':2*cfg['continuation']['bytes'],
       'variable_normal_reads':['original parent compositions/inventories/checkpoints and manifests',
          'SourceAttachments original graph/aux cache misses and readonly archive payloads',
          'every unchanged check of original continuation, including normal factory/query repetitions',
          'new CP2/root readback and normal query guards'],
       'variable_allowance_bytes':8_000_000_000-(4*s+2*d)-4*(plain['bytes']+plain_declared_decoded)-sum(x['bytes'] for x in recovery),
       'prediction':'minimums are not an actual IO claim or a promise the full gate fits; all delegated real reads are hard metered',
       'prepared_graph_decodes':0,'prepared_SP5_reads':0,'prepared_factory_calls':0,
       'excluded_separate_ceiling':'64MB source/control SHA; Python imports not payload; no raw capture reads authorized',
       'restoration':'only missing exact source858 declared static files; original URI, frozen HEAD blob and SHA/bytes, O_EXCL; no raw/physical roots',
       'publication_scope':'all26 stored successful programs; original50/817/100438 retained; historical call weights are not new body calls'})
    save('PREPARED.json',{'status':'PREPARED_NOT_RUN','worker_actual_terminal':{'root_session':40479,'exit_code':0,
       'whole_seconds':958.089,'worker_seconds':final['elapsed_s']},'normal_publication_version':3,
       'producer_tree':str(TREE),'production_revision_role':'a0f76b6b frozen production bytes; HEAD may also contain documentation',
       'recovery_commit':head,'main_source_count':len(list((TREE/'scar').rglob('*.py'))),
       'requests':len(good),'ordinary_queries':'body_reference + qualified_body_record for every successful original definition',
       'source_controls_separate':True,'lower_compile_target_current_binding':False})
    controls=[HERE/x for x in ('inputs.json','read-plan.json','PREPARED.json','run.py','run.sh','prepare.py')]
    controls += [PRIOR,WORKER/'inputs.json',WORKER/'result.json',WORKER/'worker/manifest.json',
       WORKER/'worker/attempts.jsonl',WORKER/'window-accounting.json',WORKER/'metadata-window.json',WORKER/'successful-programs.json']
    controls += [WORKER/f'worker/attempt-{i:05d}/result.json' for i in range(1,len(attempts)+1)]
    controls += [Path(x['manifest']['path']) for x in cfg['archives']]
    controls += [Path(cfg['continuation']['path']),TREE/'artifacts/experiments/first_stage_dependency_sources_20261023/result/admissions.json']
    sources=[ref(p) for p in sorted((TREE/'scar').rglob('*.py'))]
    for name in ('run.py','prepare.py'):
        compile((HERE/name).read_bytes(),str(HERE/name),'exec')
    frozen={'schema':'scar.external-entry-publication-frozen-inputs/1','producer_tree':str(TREE),
       'production_revision':'a0f76b6b','recovery_commit':head,'sources':sources,
       'control_inputs':[ref(p) for p in controls],
       'SP5_qualified_receipts':'inputs.json success program refs; ordinary reader verifies physical+decoded SHAs twice, no extra prep bulk hash',
       'static_original_receipts':'exact source858 inputs receipt and ordinary parent/manifest chain; original dependencies verified by normal readers'}
    save('freeze.json',frozen)
    save('freeze-receipt.json',{'freeze':ref(HERE/'freeze.json'),'source_count':len(sources),
       'source_bytes':sum(x['bytes'] for x in sources),'control_count':len(controls),
       'control_bytes':sum(x['bytes'] for x in frozen['control_inputs']),
       'preflight':'runner syntax only + small terminal reconciliation + declared receipt/blob-size metadata; no production factory/query/graph decode'})
    print(json.dumps({'freeze':ref(HERE/'freeze.json'),'sources':len(sources),'controls':len(controls),
       'restoration_files':len(recovery),'restoration_bytes':sum(x['bytes'] for x in recovery),
       'input_limit':limits['input_stored_plus_decoded_bytes'],'prepared_not_run':True}))

if __name__=='__main__':main()
