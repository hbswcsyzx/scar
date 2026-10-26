"""One actual retained model: exact callee/Use/formal roles, no new capture."""
from dataclasses import replace
from pathlib import Path
import hashlib,json
from scar.ir.program.python_call_targets import PythonSourcePortModel
from scar.ir.program.functions import BodyEntryInterface
from scar.ir.program.codec import loads
from scar.ir.record_codec import decode
from scar.analysis.call_operand_reader import read_call_operands
from scar.analysis.python_call_targets import read_python_call_targets

ROOT=Path(__file__).resolve().parent
model=PythonSourcePortModel.loads((ROOT/'model.json').read_text())
trace=read_call_operands(ROOT.parent/'capture',ROOT.parent/'project')
assert read_python_call_targets(trace)==model.observed
document=json.loads((ROOT/'inventory.json').read_text())
interfaces={decode(BodyEntryInterface,b).definition:decode(BodyEntryInterface,b) for b in document['interfaces']['bodies']}
graphs={}
for binding in model.bindings:
    for namespace in (binding.caller_body,binding.callee_body):
        if namespace.graph.pointer in graphs:continue
        raw=Path(namespace.graph.artifact.uri).read_bytes()
        assert hashlib.sha256(raw).hexdigest()==namespace.graph.artifact.sha256
        value=json.loads(raw)
        for component in namespace.graph.pointer[2:].split('/'):
            value=value[int(component)] if isinstance(value,list) else value[component]
        graphs[namespace.graph.pointer]=loads(json.dumps(value))

def check(binding):
    interface=interfaces[binding.callee_body.definition]
    operation=next(o for o in graphs[binding.caller_body.graph.pointer].operations if o.id==binding.call.core_operation)
    uses={u.id:u for u in operation.uses}
    offset=int(binding.receiver is not None)
    assert len(interface.parameters)==len(binding.arguments)+offset
    if binding.receiver is not None:
        port=binding.receiver;formal=interface.parameters[0]
        if (port.formal_slot,port.formal_value)!=(formal.slot,formal.value):raise ValueError('receiver must identify the original first formal')
        if (port.callable_use,port.callable_value)!=(binding.call.callee_use,binding.call.callee_value):raise ValueError('receiver must project original callee Use/value')
        assert uses[port.callable_use].value==port.callable_value
    for index,port in enumerate(binding.arguments):
        formal=interface.parameters[index+offset]
        if (port.formal_slot,port.formal_value)!=(formal.slot,formal.value):raise ValueError('explicit argument formal index includes receiver offset')
        assert operation.invoke_arguments[index+1]==port.actual_use and uses[port.actual_use].value==port.actual_value

for binding in model.bindings:check(binding)
method=next(b for b in model.bindings if b.receiver is not None)
wrong=replace(method,receiver=replace(method.receiver,formal_slot=method.arguments[0].formal_slot,formal_value=method.arguments[0].formal_value))
try:check(wrong)
except ValueError as error:rejection=str(error)
else:raise AssertionError('wrong receiver-to-explicit-formal relation accepted')
sources=['scar/trace/call_edges.py','scar/trace/call_operands.py','scar/trace/python_call_targets.py','scar/ir/program/python_call_targets.py','scar/analysis/python_call_targets.py']
result={'status':'PASS','actual_bindings':len(model.bindings),'receiver_ports':2,'explicit_argument_ports':3,'normal_core_graphs':len(graphs),'wrong_receiver_formal_rejected':rejection,'new_capture_or_source_lowering':False,'model_sha256':hashlib.sha256((ROOT/'model.json').read_bytes()).hexdigest(),'source_sha256':{p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in sources}}
(ROOT/'FINAL_CHECK.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
