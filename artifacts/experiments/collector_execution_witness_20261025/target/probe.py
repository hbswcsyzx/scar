import json,os,sys
from pathlib import Path
import torch

def cpu_probe(x):
    return x + 1

y=cpu_probe(torch.ones(2))
assert y.device.type == "cpu"
hook=sys.getprofile()
closure=dict(zip(hook.__code__.co_freevars,(cell.cell_contents for cell in hook.__closure__)))
r=closure['recorder'];w=r.collector_witness
w.validate_live()
assert r.operand_observer.recorder is r
assert r.operand_observer.environment_observer is w.registry['environments'][0]
assert r._collector_native_manager._call_recorder is r
assert r._collector_native_manager._dispatch_evidence.recorder is r
Path(os.environ['SCAR_COLLECTOR_PROBE_OUT']).write_text(json.dumps({'issuer':w.issuer,'roles':sorted(w.registry),'cwd':os.getcwd(),'argv':sys.argv,'process_id':os.getpid(),'cpu':True}))
