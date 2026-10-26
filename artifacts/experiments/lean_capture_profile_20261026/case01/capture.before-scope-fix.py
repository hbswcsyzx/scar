"""One generic CPU program, invoked in legacy/lean processes for comparison."""
from pathlib import Path
import ast,json,secrets,sys
import torch
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'project'))
import sample
from scar.trace.call_edges import install
from scar.trace.call_operands import install as install_operands
from scar.trace.lean_capture import LeanCapturePlan
from scar.trace.dispatch_evidence import DispatchEvidence,PROVIDER_REVISION
mode=sys.argv[1];out=ROOT/mode
# Imports and caller-owned explicit inputs are outside the declared run scope.
value=torch.ones(2);values=(value,);box=sample.Box()
# One mechanical static selection: callback-dispatch bodies remain interfaces.
# This demo policy is not a detector or a production library/name whitelist.
source=ast.parse((ROOT/'project/sample.py').read_text());selected=[];unplanned=[]
for node in ast.walk(source):
    if not isinstance(node,ast.FunctionDef):continue
    params={a.arg for a in node.args.args}
    callback=any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id in params for n in ast.walk(node))
    obj=getattr(sample,node.name,None)
    if obj is None:
        obj=next(getattr(getattr(sample,c.name),node.name) for c in source.body if isinstance(c,ast.ClassDef) and node in c.body)
    if callback:unplanned.append(node.name)
    else:selected.append(obj.__code__)
plan=LeanCapturePlan.from_codes(ROOT/'project',tuple(selected))
(ROOT/'selection.json').write_text(json.dumps({'planned':[b.code.qualname for b in plan.bodies],
    'unplanned':unplanned,'policy':'explicit demo AST callback boundary; selected code/sites only; not whole program'},indent=2)+'\n')
recorder=install(out,ROOT/'project',lean_plan=plan if mode=='lean' else None)
observer=install_operands(recorder,capture='lean-ports' if mode=='lean' else 'windows',
    max_events=10000,max_bytes=8_000_000,python_targets=True)
dispatch=DispatchEvidence(out,recorder,nonce=secrets.token_hex(16),provider_revision=PROVIDER_REVISION,
    max_events=100,max_bytes=1_000_000)
assert dispatch.start(torch)
try:
    result=sample.run(box,value,values)
    # Metadata only; no item/readback/extra Tensor computation or sync.
    assert result.shape==value.shape and result.dtype==value.dtype
finally:
    dispatch.close()
print(json.dumps({'status':'GENERIC_PYTHON_TORCH_RETURNED','mode':mode,'tensor_contents_read':False,
    'scope':'sample.run activation and declared plan; imports/input construction outside scope'}))
