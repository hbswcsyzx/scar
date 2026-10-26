"""Freeze restored bytes/stat and check8 normal metadata-only planner orders."""
from pathlib import Path
import ast,hashlib,json
from run import HERE,ROOT,Driver,canonical,need

def receipt(path):
 path=Path(path);h=hashlib.sha256();size=0
 with path.open('rb')as stream:
  while raw:=stream.read(1_048_576):h.update(raw);size+=len(raw)
 return {'path':str(path.resolve()),'sha256':h.hexdigest(),'bytes':size}
def save(name,value):
 with(HERE/name).open('xb')as stream:stream.write(canonical(value)+b'\n')
def main():
 need(not(HERE/'freeze.json').exists()and not(HERE/'result').exists(),'fresh preparation required')
 c=json.loads((HERE/'inputs.json').read_bytes());old=json.loads(Path(c['prior_freeze']['path']).read_bytes())
 read_plan=json.loads(Path(c['read_plan']['path']).read_bytes());remaining=json.loads(Path(c['remaining_metadata']['path']).read_bytes())
 # Old fixed inputs keep exact bytes; restored files get independent current stat.
 inputs={r['path']:r for r in old['inputs']}
 for ref in [c['read_plan'],c['remaining_metadata'],c['prior_driver_ledger'],c['prior_terminal'],c['prior_freeze'],c['recovery_receipt'],c['owner_full_recovery_receipt'],c['archive_mode_repair_receipt'],c['original209_remaining_metadata']]:inputs[ref['path']]=ref
 inputs[str(HERE/'inputs.json')]=receipt(HERE/'inputs.json')
 for ref in inputs.values():need(receipt(ref['path'])==ref,'restored/fixed metadata bytes differ: '+ref['path'])
 for directory,members in old['archive_members'].items():need(sorted(str(p)for p in Path(directory).iterdir()if p.is_file())==members,'readonly archive membership differs')
 for ref in old['sources']+old['runtime']:need(receipt(ref['path'])==ref,'original isolated code/runtime differs')
 graph={f['source_graph']['path']:f['source_graph']['declaration']for b in read_plan['batches']for f in b['file_groups']}
 need(len(graph)==58,'remaining graph declarations differ')
 graphs=[{**a,'declaration_relative_path':a['path'],'path':p}for p,a in graph.items()]
 for row in graphs:need(Path(row['path']).stat().st_size==row['compressed_bytes'],'restored graph declared size differs')
 for path in HERE.glob('*.py'):ast.parse(path.read_bytes(),filename=str(path))
 sources=old['sources']+[receipt(p)for p in sorted(HERE.glob('*.py'))]
 inputs[str(HERE/'README.md')]=receipt(HERE/'README.md')
 for name in ('prepare01.stdout.json','prepare01.stderr.txt','prepare01-missing-paths.json','prepare02.stdout.json','prepare02.stderr.txt','prepare02-archive-mode-frontier.json'):
  inputs[str(HERE/name)]=receipt(HERE/name)
 owner_document=json.loads(Path(c['continuation']['path']).read_bytes())
 owner_rows=owner_document['source_files'];owner_rows=owner_rows.values()if isinstance(owner_rows,dict)else owner_rows
 all_owner_graphs=[]
 for record in owner_rows:
  locator=record['source_graph_artifact'];base=Path(locator['parent_directory'])if locator['origin']=='PARENT'else Path(c['continuation']['path']).parent
  path=base/locator['artifact']['path'];need(path.is_file()and path.stat().st_size==locator['artifact']['compressed_bytes'],'owner graph availability/size differs: '+str(path));all_owner_graphs.append(str(path))
 need(len(set(all_owner_graphs))==106,'original owner106 graph path count differs')
 stat_paths=sorted(set(inputs)|set(all_owner_graphs))
 stats=[]
 for path in stat_paths:
  st=Path(path).stat();stats.append({'path':path,'size':st.st_size,'mtime_ns':st.st_mtime_ns,'ctime_ns':st.st_ctime_ns,'inode':st.st_ino,'device':st.st_dev,'mode':oct(st.st_mode & 0o777),'uid':st.st_uid,'gid':st.st_gid})
 freeze={'schema':'scar.source209-isolated-resume-freeze/1','head_label':old['head_label'],'code_root':str(ROOT),'sources':sources,'runtime':old['runtime'],'inputs':list(inputs.values()),'archive_members':old['archive_members'],'graph_declarations':graphs,'source_count':old['source_count'],'budgets':c['budgets'],'previous_failed_gate_freeze':c['prior_freeze'],'restored_input_current_stat':stats,'all106_owner_graph_paths_stat_only':sorted(set(all_owner_graphs)),'data_URIs_and_namespace_not_relocated':True,'original_graph_payloads_hashed_or_decoded_during_prepare':False,'runtime_scope':old['runtime_scope'],'prepared_metadata_is_not_owned_model':True}
 driver=Driver(c,freeze);driver.output=HERE/'prepared-metadata';driver.output.mkdir();driver.install_readers()
 from scar.analysis.source_attachments import SourceAttachments
 from scar.analysis.code_witness import CodeWitnessStore
 from scar.analysis.source_frontend_worklist import SourceFrontendBudget,plan_source_entries
 from scar.ir.program.source_language import SourceLanguageCapability
 def forbidden(*args,**kw):raise AssertionError('prepare forbids graph/CodeType/compile/worker')
 SourceAttachments._view=forbidden;CodeWitnessStore.resolve=forbidden
 owner,archives,catalog=driver.build_catalog(read_plan,remaining)
 budget=SourceFrontendBudget(max_catalog_files=256,max_catalog_bodies=8192,max_catalog_groups=8192,max_dispatch_bodies=64,max_source_files=8,max_source_bytes=2_000_000,max_operations_per_body=10_000,max_total_operations=1_000_000,max_record_bytes=128_000_000,max_output_bytes=2_000_000_000,max_elapsed_seconds=900)
 caps=tuple(SourceLanguageCapability(v)for v in read_plan['old_producer_and_capabilities']['capabilities']);checks=[]
 for batch in read_plan['batches']:
  plan=plan_source_entries(catalog,budget=budget,capabilities=caps,eligible_entry_keys=tuple(batch['entry_keys']),dispatch_order='FILE_GROUPED_V1')
  need([r['entry_key']for r in plan.dispatch]==batch['entry_keys']and len(plan.entries)==243 and len(plan.groups)==817 and plan.document['summary']['current_calls']==100438,'normal planner order/keyset/denominator differs')
  checks.append({'batch':batch['batch'],'keys':batch['entry_keys'],'files':len({r['file_key']for r in plan.dispatch}),'plan_sha256':plan.digest})
 need(owner.measurements().get('graph_artifacts_read',0)==0 and all(all(v==0 for v in s.counts.values())for s in archives._stores.values()),'prepare loaded graph or CodeType')
 save('PREPARE_CHECK.json',{'status':'ALL8_NORMAL_PLANNER_ORDERS_METADATA_PASS_WORKER_NOT_RUN','original_groups':817,'original_calls':100438,'candidates':243,'original209':209,'remaining':97,'retained_previous':{'SUCCEEDED':63,'UNSUPPORTED':49},'batches':checks,'preparation_IO_separate_from_future_gate':driver.io(),'graph_CodeType_compile_lower_worker':False,'normal_catalog_builds_in_preparation':1,'real_gate_normal_catalog_builds':1})
 inputs[str(HERE/'PREPARE_CHECK.json')]=receipt(HERE/'PREPARE_CHECK.json');freeze['inputs']=list(inputs.values())
 for ref in sources:need(receipt(ref['path'])==ref,'isolated producer changed during prepare')
 save('freeze.json',freeze)
 print(json.dumps({'status':'PREPARED_NOT_RUN','freeze':receipt(HERE/'freeze.json'),'runner':receipt(HERE/'run.py'),'source_count':freeze['source_count'],'source_pins':len(sources),'runtime_files':len(freeze['runtime']),'input_files':len(inputs),'graph_declarations':len(graphs),'all8_order_checks_pass':True,'preparation_metadata_IO':driver.io(),'worker_run':False},sort_keys=True),flush=True)
if __name__=='__main__':main()
