"""Summarize existing normal worker results; never load or lower a program."""
import json,hashlib,subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[3];base=Path(__file__).resolve().parent;new=base/'candidate02'
row=json.loads((new/'worker/attempt-00001/result.json').read_bytes());m=json.loads((new/'worker/attempt-00001/returned-metadata.json').read_bytes());recipe=json.loads((base/'READ_PLAN.json').read_bytes())
files=['scar/analysis/source_environment_validation.py','scar/analysis/source_frontend_worklist.py','scar/analysis/source_function_try_lowering.py','scar/analysis/source_function_try_validation.py','scar/analysis/source_heap_lowering.py','scar/ir/program/source_language.py']
def receipt(path):
 data=path.read_bytes();return {'path':str(path),'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
def save(path,data):path.write_text(json.dumps(data,sort_keys=True,indent=2)+'\n')
oldreceipt=json.loads((base/'candidate01/receipt.json').read_bytes());newreceipt=json.loads((new/'receipt.json').read_bytes())
assert newreceipt['source_unchanged'] and all(newreceipt['source_sha256'][name]==receipt(root/name)['sha256']for name in files)
source_receipts=[]
for name in files:
 original=subprocess.check_output(['git','show','c6e31a9a:'+name],cwd=root);source_receipts.append({'path':name,'base_sha256':hashlib.sha256(original).hexdigest(),'after':receipt(root/name)})
save(base/'SOURCE_RECEIPTS.json',{'base':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root).decode().strip(),'files':source_receipts,'producer_frozen_during_gate':True})
target_line=recipe['selected'][0]['frontier']['source']['start_line']
protocols=m['structured']['protocols'];inplace=[r for r in protocols if r['kind']=='FUNCTION_INPLACE_BINARY']
loads=[r for r in m['metadata']['operation_links'] if r['opcode']=='attribute' and r['source']['start_line']==target_line]
stores=[r for r in protocols if r['kind']=='STORE_ATTRIBUTE' and r['source']['start_line']==target_line]
assert len(inplace)==len(loads)==len(stores)==1
save(new/'ACTUAL_TERMINAL.json',{'schema':'scar.heap-augassign-actual-terminal','schema_version':1,'session_id':37462,'actual_exit_code':0,'runner_seconds':newreceipt['elapsed_seconds'],'gnu_time_wall_seconds':30.97,'body_seconds':row['elapsed_s'],'rss_kib':231780,'normal_reader':row['public_structure_reader'],'independent_code_reader':row['independent_code_reader'],'operation_count':row['operations_emitted'],'program':row['program'],'static_original_protocols':{'lhs_load':loads[0],'inplace':inplace[0],'storeback':stores[0]},'no_new_runtime_binding':True,'earlier_same_subject_window':{'session_id':17809,'actual_exit_code':0,'status':'UNSUPPORTED','operations_emitted':54,'program':None,'seconds':oldreceipt['elapsed_seconds']}})
entry={key:row[key]for key in ('entry_key','entry_reference','independent_code_reader','operations_emitted','program','public_structure_reader','source_calls','status')};entry['public_terminal']=str(new/'worker/attempt-00001/result.json')
save(base/'successful-programs-delta1.json',{'schema':'scar.source-program-success-delta','schema_version':1,'source_scope_run':272038,'currentRun_binding':0,'publication':0,'restore_live_owner':False,'historical_calls':row['source_calls'],'entries':[entry]})
patch=subprocess.check_output(['git','diff','--',*files],cwd=root);(base/'PRODUCTION.diff').write_bytes(patch)
artifacts=[receipt(p)for p in sorted(base.rglob('*'))if p.is_file() and p.name not in ('RETENTION.json','STAGE_PATHS.json','REPORT.md')]
save(base/'RETENTION.json',{'schema':'scar.heap-augassign-retention','schema_version':1,'artifacts':artifacts,'external_inputs_unchanged':recipe['all_four'],'bulk_not_in_git':[row['program']],'original_failure_preserved':True,'no_raw_or_target':True})
print(json.dumps({'program':row['program'],'sources':{r['path']:r['after']['sha256']for r in source_receipts}},indent=2))
