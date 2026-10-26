from pathlib import Path
from hashlib import sha256
import json,time,urllib.request
from scar.store.bundle_partitions import BundlePartitions
from scar.ir.record_codec import decode
from scar.ir.v2 import OperationInstance
OUT=Path(__file__).resolve().parent
started=time.monotonic()
manifest=Path('/home/zyf/AAA/scar-worktrees/structured-program-model/artifacts/experiments/first_stage_joined_physical_20261023/result/native/bundle-partitions/manifest.json')
reader=BundlePartitions(manifest)
assert reader.manifest_receipt['sha256']=='a7b23bdb385b50522e6401433a8308343a593a4080288f3502d6e338e1e4b1b6'
rows=reader.selected_records('evidence','instances',(17303,17304))
print('rows',list(rows),flush=True)
a,b=(decode(OperationInstance,rows[n]['record']) for n in (17303,17304))
assert a.id.value.endswith(':eto:20837') and b.id.value.endswith(':eto:20833')
assert a.parent==b.id
assert a.metadata['ctrl_deps']==20833 and a.metadata['node_id']==20837
assert a.metadata['parent_basis']=='ETO ctrl_deps collector stack only'
assert b.metadata['parent_basis']=='ETO ctrl_deps collector stack only'
assert a.metadata['raw_reference'].endswith('#/nodes/17303') and b.metadata['raw_reference'].endswith('#/nodes/17304')
assert a.process_id==b.process_id
url='https://raw.githubusercontent.com/pytorch/pytorch/cf30153c4c131c8164ee7798e5022d810682e2cb/torch/csrc/profiler/standalone/execution_trace_observer.cpp'
with urllib.request.urlopen(url,timeout=20) as response:
 code=response.read(200001)
assert len(code)<200001
(OUT/'execution_trace_observer.cpp').write_bytes(code)
chunk=rows[17303]['locator']['artifact'];assert chunk==rows[17304]['locator']['artifact']
result={'status':'TWO_ORIGINAL_EEG_RECORDS_PARENT_MATCH','elapsed_s':time.monotonic()-started,'root':reader.manifest_receipt,'rows':{str(k):v for k,v in rows.items()},'checks':{'exact_child_parent_id':True,'metadata_ctrl_deps_matches_parent_id':True,'parent_basis_collector_stack_only':True,'same_process':True,'source_source_witness_or_tensor_ports_established':False,'raw_eto_replayed':False,'all_parent_paths_replayed':False},'input':{'manifest_stored_bytes':manifest.stat().st_size,'selected_chunk_stored_bytes':chunk['physical_bytes'],'selected_chunk_decoded_bytes':chunk['decoded_bytes'],'selected_chunk_count':1,'selected_original_record_count':2,'actual_original_input_bytes':manifest.stat().st_size+chunk['physical_bytes']+chunk['decoded_bytes'],'extra_primary_source_bytes':len(code)},'provider_source':{'url':url,'bytes':len(code),'sha256':sha256(code).hexdigest(),'revision':'cf30153c4c131c8164ee7798e5022d810682e2cb','lines_1based':{'thread_stack':104,'parent_from_stack':707,'push_current':715,'exit_pop':812,'parent_to_writer':818,'ctrl_deps_json':264,'parent_json_argument':271}},'original_inputs_or_production_changed':False}
(OUT/'PARENT_SAMPLE.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
print(json.dumps({k:result[k] for k in ('status','elapsed_s','input','provider_source')},ensure_ascii=False))
