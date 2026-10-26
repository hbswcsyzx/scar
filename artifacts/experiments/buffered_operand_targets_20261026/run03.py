import hashlib,json,os,sys,threading
from pathlib import Path
from scar.trace.call_edges import install as install_calls
from scar.trace.call_operands import install as install_operands
from scar.analysis.call_operands import link_call_operands
from scar.analysis.program_inventory import inventory_program
from scar.ir.program.functions import BodyLoweringProfile
from scar.ir.program.call_edges import CallEdgeBudget
from scar.ir.program.call_operands import CallOperandBudget
root=Path(__file__).resolve().parent
project=root/'project';out=root/'capture03'
sys.path.insert(0,str(project))
rec=install_calls(out,project)
obs=install_operands(rec,capture='windows',max_events=100000,max_bytes=64000000,python_targets=True)
counts={obs._fd:0,obs.python_targets.fd:0};write=os.write

def counted(fd,data):
    if fd in counts:counts[fd]+=1
    return write(fd,data)

os.write=counted
try:
    from sample import run
    result=run(200)
    obs.stop();sys.setprofile(None);threading.setprofile(None)
    rec.close();obs.close()
finally:
    os.write=write
assert result==40000
metadata=json.loads(obs._metadata_path.read_text())
assert not metadata['io_failed'] and not metadata['dropped_events']
target=obs.python_targets
meta=json.loads(target.meta.read_text());raw=target.path.read_bytes()
assert len(raw)==meta['file']['bytes'] and hashlib.sha256(raw).hexdigest()==meta['file']['sha256']
assert raw.count(b'\n')==sum(meta['counts'].values()) and not meta['stopped']
inventory=inventory_program(project/'sample.py',project_root=project,calls_trace=out,body_profile=BodyLoweringProfile.STRUCTURED_ENV)
report=link_call_operands(out,project,inventory,frame_budget=CallEdgeBudget(max_events=100000,max_raw_bytes=128000000),operand_budget=CallOperandBudget(max_events=100000,max_raw_bytes=128000000))
summary={'status':'VERIFIED','result':result,'operand_events':metadata['events'],'operand_os_writes':counts[obs._fd] if obs._fd in counts else counts[next(iter(counts))],
         'target_rows':raw.count(b'\n'),'target_os_writes':counts[target.fd],'target_counts':meta['counts'],'normal_linker_completed':True,'whole_model_complete':False}
(root/'result.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary))
