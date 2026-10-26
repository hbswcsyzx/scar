"""Freeze isolated code/original data and check all13 ordinary planner orders only."""
from pathlib import Path
from collections import Counter
import ast,hashlib,json
from run import HERE,ROOT,Driver,canonical,need

MAIN=Path('/home/zyf/AAA/scar-worktrees/structured-program-model')
OLD=MAIN/'artifacts/experiments/lewm_external_source_entries_20261026'
RUNTIME=Path('/home/zyf/AAA/scar-worktrees/source858-runtime/artifacts/experiments/lewm_archived_compiler_gate_20261026/freeze.json')

def receipt(path):
 path=Path(path);h=hashlib.sha256();n=0
 with path.open('rb')as stream:
  while raw:=stream.read(1_048_576):h.update(raw);n+=len(raw)
 return {'path':str(path.resolve()),'sha256':h.hexdigest(),'bytes':n}
def save(name,value):
 with(HERE/name).open('xb')as stream:stream.write(canonical(value)+b'\n')

def main():
 need(not(HERE/'freeze.json').exists()and not(HERE/'result').exists(),'prepare/gate output must be fresh')
 c=json.loads((HERE/'inputs.json').read_bytes());read_plan=json.loads(Path(c['read_plan']['path']).read_bytes());remaining=json.loads(Path(c['remaining_metadata']['path']).read_bytes())
 fixed=json.loads((OLD/'original-input-availability.json').read_bytes())['original_inputs'];inputs={r['path']:r for r in fixed};members={}
 for archive in c['archives']:
  directory=Path(archive['directory']);manifest=archive['manifest'];need(receipt(manifest['path'])==manifest,'original manifest SHA differs')
  document=json.loads(Path(manifest['path']).read_bytes());inputs[manifest['path']]=manifest
  expected={'manifest.json'}
  for section in ('sources','modules'):
   for record in document[section].values():
    a=record['artifact'];path=directory/a['path'];row=receipt(path)
    need(row['bytes']==a['bytes']and row['sha256']==a['sha256'],'original readonly payload SHA differs')
    inputs[row['path']]=row;expected.add(a['path'])
  actual=sorted(str(p)for p in directory.iterdir()if p.is_file())
  need({Path(p).name for p in actual}==expected,'original archive member set differs from manifest')
  members[str(directory)]=actual
 for ref in [c['read_plan'],c['remaining_metadata'],c['continuation']]+c['old_terminal_receipts']:
  need(receipt(ref['path'])==ref,'fixed original metadata changed');inputs[ref['path']]=ref
 graph={r['source_graph']['path']:r['source_graph']['declaration']for b in read_plan['batches']for r in b['file_groups']}
 need(len(graph)==99,'read-plan graph set differs')
 graphs=[{**a,'declaration_relative_path':a['path'],'path':p}for p,a in graph.items()]
 for row in graphs:need(Path(row['path']).stat().st_size==row['compressed_bytes'],'source graph declared size differs')
 for path in HERE.glob('*.py'):ast.parse(path.read_bytes(),filename=str(path))
 sources=[receipt(p)for p in sorted(set((ROOT/'scar').rglob('*.py'))|set(HERE.glob('*.py'))|{ROOT/'sitecustomize.py'})]
 runtime=[receipt(r['path'])for r in json.loads(RUNTIME.read_bytes())['runtime']]
 inputs[str(HERE/'inputs.json')]=receipt(HERE/'inputs.json')
 freeze={'schema':'scar.source209-isolated-driver-freeze/1','head_label':c['code_head_label'],'code_root':str(ROOT),'sources':sources,'runtime':runtime,'inputs':list(inputs.values()),'archive_members':members,'graph_declarations':graphs,'source_count':len(list((ROOT/'scar').rglob('*.py'))),'budgets':c['budgets'],'prepared_metadata_is_not_owned_model':True,'original_graph_payloads_hashed_or_decoded_during_prepare':False,'runtime_scope':'explicit file SHA list, not claim of all imported/executed or original capture execution bytes','data_URIs_and_namespace_not_relocated':True}
 # One metadata-only constructor in preparation; the real driver separately constructs once.
 driver=Driver(c,freeze);driver.output=HERE/'prepared-metadata';driver.output.mkdir()
 driver.install_readers()
 from scar.analysis.source_attachments import SourceAttachments
 from scar.analysis.code_witness import CodeWitnessStore
 from scar.analysis.source_frontend_worklist import SourceFrontendBudget,plan_source_entries
 from scar.ir.program.source_language import SourceLanguageCapability
 def forbidden(*args,**kw):raise AssertionError('prepare forbids graph/CodeType/compile/worker')
 SourceAttachments._view=forbidden;CodeWitnessStore.resolve=forbidden
 owner,archives,catalog=driver.build_catalog(read_plan,remaining)
 budget=SourceFrontendBudget(max_catalog_files=256,max_catalog_bodies=8192,max_catalog_groups=8192,max_dispatch_bodies=64,max_source_files=8,max_source_bytes=2_000_000,max_operations_per_body=10_000,max_total_operations=1_000_000,max_record_bytes=128_000_000,max_output_bytes=2_000_000_000,max_elapsed_seconds=900)
 caps=tuple(SourceLanguageCapability(x)for x in read_plan['old_producer_and_capabilities']['capabilities']);checks=[]
 for batch in read_plan['batches']:
  plan=plan_source_entries(catalog,budget=budget,capabilities=caps,eligible_entry_keys=tuple(batch['entry_keys']),dispatch_order='FILE_GROUPED_V1')
  need([r['entry_key']for r in plan.dispatch]==batch['entry_keys']and len(plan.entries)==243 and len(plan.groups)==817 and plan.document['summary']['current_calls']==100438,'normal planner order/keyset/full denominator differs from batch')
  checks.append({'batch':batch['batch'],'keys':batch['entry_keys'],'files':len({r['file_key']for r in plan.dispatch}),'plan_sha256':plan.digest})
 need(owner.measurements().get('graph_artifacts_read',0)==0 and all(all(v==0 for v in s.counts.values())for s in archives._stores.values()),'prepare loaded graph or CodeType')
 save('PREPARE_CHECK.json',{'status':'ALL13_NORMAL_PLANNER_ORDERS_METADATA_PASS_WORKER_NOT_RUN','original_groups':817,'original_calls':100438,'candidates':243,'remaining':209,'batches':checks,'preparation_IO_separate_from_future_real_gate':driver.io(),'graph_CodeType_compile_lower_worker':False,'preparation_normal_catalog_builds':1,'real_driver_will_build_normal_catalog_once':True})
 inputs[str(HERE/'PREPARE_CHECK.json')]=receipt(HERE/'PREPARE_CHECK.json');freeze['inputs']=list(inputs.values())
 for row in sources:need(receipt(row['path'])==row,'isolated producer changed during prepare')
 save('freeze.json',freeze)
 print(json.dumps({'status':'PREPARED_NOT_RUN','freeze':receipt(HERE/'freeze.json'),'runner':receipt(HERE/'run.py'),'sources':freeze['source_count'],'source_pins':len(sources),'runtime_files':len(runtime),'input_files':len(inputs),'input_unique_stored_bytes':sum(r['bytes']for r in inputs.values()),'graph_declarations':len(graphs),'all13_order_checks_pass':True,'preparation_metadata_IO':driver.io(),'worker_run':False},sort_keys=True),flush=True)

if __name__=='__main__':main()
