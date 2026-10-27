"""Prepare the approved whole missing192 compiler gate; never compile or decode graphs."""
from dataclasses import asdict
import ast,json
from pathlib import Path
from run import HERE, ROOT, canonical, receipt, need, save

META=ROOT/'artifacts/experiments/lewm_remaining_compiler_witnesses_20261026'
PRIOR=ROOT/'artifacts/experiments/lewm_external_source_entries_20261026'
FIRST=Path('/home/zyf/AAA/scar-worktrees/source858-runtime/artifacts/experiments/lewm_archived_compiler_gate_20261026')

def main():
 need(not(HERE/'workset.json').exists()and not(HERE/'freeze.json').exists(),'prepared outputs must be fresh')
 source=json.loads((META/'workset.json').read_bytes());oldplan=json.loads((META/'plan.json').read_bytes());config=json.loads((PRIOR/'inputs.json').read_bytes())
 meta_result=json.loads((META/'result.json').read_bytes())
 need(receipt(META/'workset.json')==meta_result['workset']and receipt(META/'plan.json')==meta_result['plan'],'original metadata plan/workset changed')
 from scar.analysis.source_attachments import SourceAttachments,SourceAttachmentBudget
 from scar.analysis.code_witness import CodeWitnessBudget,CodeWitnessStore
 from scar.analysis.compiler_witness_archives import CompilerArchiveBudget,CompilerWitnessArchives,ObservedAcquisitionBudget,plan_attachment_witness_acquisition
 from scar.ir.program.call_demand import EnteredCallCode
 from scar.ir.record_codec import decode
 def forbidden(*a,**k):raise AssertionError('prepare forbids graph/CodeType/compile')
 SourceAttachments._view=forbidden;CodeWitnessStore.resolve=forbidden
 for row in meta_result['fixed_inputs']:need(receipt(row['path'])==row,'original archive/continuation input changed')
 owner=SourceAttachments(config['continuation']['path'],expected_report_sha256=config['continuation']['sha256'],project_root=config['project_root'],budget=SourceAttachmentBudget())
 archive_budget=CodeWitnessBudget(max_compile_keys=64,max_source_files=64,max_source_bytes=8_000_000,max_module_bytes=16_000_000,max_archive_bytes=256_000_000,max_manifest_bytes=8_000_000)
 archives=CompilerWitnessArchives(tuple((r['directory'],r['manifest']['sha256'])for r in config['archives']),store_budget=archive_budget,budget=CompilerArchiveBudget(max_archives=3,max_total_modules=64,max_total_sources=64,max_declared_payload_bytes=256_000_000))
 origins=tuple(decode(EnteredCallCode,r['origin'])for r in source['selected_origins'])
 budget=ObservedAcquisitionBudget(max_definitions=256,max_requests=256,max_attempts=192,max_elapsed_seconds=900,max_record_bytes=16_000_000,max_report_bytes=64_000_000)
 plan=plan_attachment_witness_acquisition(owner,archives,origins=origins,budget=budget)
 need(canonical(plan)==canonical({**oldplan,'budget':asdict(budget)}),'ordinary full192 plan changed beyond approved explicit budget')
 need(len(origins)==len(plan['requests'])==192 and not plan['frontiers'],'original192 metadata scope changed')
 preferred={canonical(r['preferred_compile_key']):r['preferred_compile_key']for r in plan['requests']}
 need(len(preferred)==94 and len(source['source_texts'])==94,'full94 key/file scope changed')
 texts=[]
 for row in source['source_texts']:
  need(row['status']=='ORIGINAL_SNAPSHOT_NORMAL_OWNER_VERIFIED','source snapshot unavailable')
  texts.append({**row,'locator':row['snapshot_locator'],'owner':plan['source_attachment_inputs'],'encoding':row['original_encoding']})
 work={'schema':'scar.lewm-all-remaining-compiler-workset/1','original_metadata_workset':receipt(META/'workset.json'),'original_metadata_plan':receipt(META/'plan.json'),'origins':[r['origin']for r in source['selected_origins']],'normal_plan':plan,'source_texts':texts,'unique_preferred_compile_keys':[preferred[k]for k in sorted(preferred)],'original_groups':817,'original_calls':100438,'original_source_verified_candidates':243,'selected_missing_origins':192,'unique_preferred_keys':94,'raw_source_bytes':meta_result['raw_source_bytes'],'normalized_source_bytes':meta_result['normalized_source_bytes'],'captured_python_build_matches':plan['captured_python_build_matches'],'definition_membership_checked':False,'compile_run':False}
 save('workset.json',work)
 original_inputs=json.loads((PRIOR/'original-input-availability.json').read_bytes())['original_inputs']
 inputs={r['path']:r for r in original_inputs}
 stores={}
 for declaration in config['archives']:
  directory=Path(declaration['directory']);members=sorted(str(p)for p in directory.iterdir()if p.is_file());stores[str(directory)]=members
  for p in members:inputs[p]=receipt(p)
 for p in (META/'workset.json',META/'plan.json',META/'result.json',PRIOR/'inputs.json',HERE/'workset.json'):
  row=receipt(p);inputs[row['path']]=row
 for row in inputs.values():need(receipt(row['path'])==row,'original fixed bytes changed')
 sources=[receipt(p)for p in sorted(set((ROOT/'scar').rglob('*.py'))|set(HERE.glob('*.py'))|{ROOT/'sitecustomize.py'})]
 original_freeze=json.loads((FIRST/'freeze.json').read_bytes());runtime=[receipt(r['path'])for r in original_freeze['runtime']]
 for p in HERE.glob('*.py'):ast.parse(p.read_bytes(),filename=str(p))
 frozen={'schema':'scar.lewm-all-remaining-compiler-freeze/1','sources':sources,'source_count':len(list((ROOT/'scar').rglob('*.py'))),'runtime':runtime,'inputs':sorted(inputs.values(),key=lambda r:r['path']),'original_inputs':{'continuation':config['continuation'],'archives':config['archives'],'project_root':config['project_root']},'original_archive_directory_membership':stores,'workset':receipt(HERE/'workset.json'),'selection':'all192 original CODE_WITNESS_UNAVAILABLE candidates, no package/function filter','budgets':{'outer_seconds':1200,'acquisition':asdict(budget),'compile_keys':94,'source_files':94,'source_bytes':8_000_000,'module_bytes':16_000_000,'archive_bytes':256_000_000,'manifest_bytes':8_000_000,'metadata_stored_plus_decoded':3_000_000_000,'code_payload_stored_read':64_000_000,'post_stage_output_bytes':256_000_000,'AS_bytes':4*1024**3,'source_control_SHA_IO':'separate'},'producer_changed':False,'graph_decoded':False,'compile_run':False,'current369749_binding':'NOT_RUN','runtime_binary_execution_proof':'bounded by explicit runtime list, not proof of original272038 execution bytes'}
 save('freeze.json',frozen)
 need(owner.measurements().get('graph_artifacts_read',0)==0 and all(all(v==0 for v in s.counts.values())for s in archives._stores.values()),'prepare loaded graph or CodeType')
 print(json.dumps({'status':'PREPARED_NOT_RUN','freeze':receipt(HERE/'freeze.json'),'workset':receipt(HERE/'workset.json'),'scar_source_count':frozen['source_count'],'source_pins':len(sources),'runtime_files':len(runtime),'fixed_inputs':len(inputs),'unique_fixed_input_bytes':sum(r['bytes']for r in inputs.values()),'selected_origins':192,'unique_preferred_keys':94,'source_files':94,'compile_run':False},sort_keys=True))

if __name__=='__main__':main()
