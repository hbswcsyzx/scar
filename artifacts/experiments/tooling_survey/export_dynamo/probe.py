"""Bounded CPU-only capability probes; not SCAR validation or a backend."""
import dataclasses
import copy
import hashlib
import inspect
import json
import os
from pathlib import Path
import platform
import sys
import time
import traceback

os.environ.setdefault('CUDA_VISIBLE_DEVICES', '')
os.environ.setdefault('OMP_NUM_THREADS', '1')
os.environ.setdefault('MKL_NUM_THREADS', '1')
import torch
from torch.fx.experimental.proxy_tensor import make_fx

OUT = Path(__file__).resolve().parent
torch.set_num_threads(1)
torch.manual_seed(0)
RESULT = {'environment': {'python': sys.version, 'torch': torch.__version__,
    'torch_git': torch.version.git_version, 'torch_file': torch.__file__,
    'export_signature': str(inspect.signature(torch.export.export)),
    'platform': platform.platform(), 'device': 'cpu', 'gpu_used': False,
    'command': ' '.join(sys.orig_argv), 'probe_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
    'probes': []}

def encode(v):
    if v is None or type(v) in (str, int, float, bool): return v
    if isinstance(v, torch.Tensor):
        return {'shape': encode(tuple(v.shape)), 'dtype': str(v.dtype), 'stride': encode(tuple(v.stride())), 'requires_grad': v.requires_grad}
    if dataclasses.is_dataclass(v): return {f.name: encode(getattr(v, f.name)) for f in dataclasses.fields(v)}
    if isinstance(v, dict): return {str(k): encode(val) for k, val in v.items()}
    if isinstance(v, (tuple, list)): return [encode(x) for x in v]
    return str(v)

def error(fn):
    try: return {'ok': True, 'result': encode(fn())}
    except Exception as exc: return {'ok': False, 'type': type(exc).__name__, 'message': str(exc)[:5000]}

def graph(gm):
    rows=[]
    for node in gm.graph.nodes:
        target=node.target
        rows.append({'name': node.name, 'op':node.op, 'target': str(target),
            'args': str(node.args), 'kwargs': str(node.kwargs),
            'schema': str(getattr(target, '_schema', '')),
            'meta': {k: encode(node.meta[k]) for k in ('val','stack_trace','nn_module_stack','source_fn_stack') if k in node.meta}})
    return {'code':gm.code,'nodes':rows}

def ep_info(ep):
    return {'graph': graph(ep.graph_module), 'signature': encode(ep.graph_signature),
        'range_constraints': encode(ep.range_constraints),
        'call_spec': encode(ep.call_spec), 'module_call_graph': encode(ep.module_call_graph)}

def run(name, fn):
    start=time.perf_counter()
    row={'name':name}
    try: row.update(status='PASS', result=fn())
    except Exception as exc: row.update(status='ERROR', error_type=type(exc).__name__, error=str(exc), traceback=traceback.format_exc())
    row['seconds']=time.perf_counter()-start
    RESULT['probes'].append(row)
    (OUT/'results.json').write_text(json.dumps(RESULT,indent=2,sort_keys=True))
    print(name,row['status'],round(row['seconds'],3),flush=True)

class Mutation(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.p=torch.nn.Parameter(torch.ones(3),requires_grad=False)
        self.register_buffer('b',torch.zeros(3))
    def forward(self,x):
        self.b.add_(2)
        x.add_(1)
        return (x*self.p+self.b, x.view(-1), x)

def mutations():
    ep=torch.export.export(Mutation(),(torch.zeros(3),),strict=True)
    fp=ep.run_decompositions({})
    data={'training':ep_info(ep),'functional':ep_info(fp)}
    for name,item in [('training',ep),('functional',fp)]:
        mod=copy.deepcopy(item.module()); x=torch.zeros(3); out=mod(x)
        data[name]['execution']={'x':x.tolist(),'b':mod.b.tolist(),'output0':out[0].tolist(),
            'output2_is_input':out[2] is x,'view_aliases_input':torch._C._is_alias_of(out[1],x)}
    return data

class ParamMutation(torch.nn.Module):
    def __init__(self):
        super().__init__(); self.p=torch.nn.Parameter(torch.ones(2))
    def forward(self,x):
        with torch.no_grad(): self.p.add_(1)
        return x*self.p

def parameter_mutation():
    ep=torch.export.export(ParamMutation(),(torch.ones(2),),strict=True)
    return {'training':ep_info(ep),'functionalization':error(lambda:ep_info(ep.run_decompositions({})))}

class Child(torch.nn.Module):
    def forward(self,x): return {'value':x.sin()+1}
class Parent(torch.nn.Module):
    def __init__(self): super().__init__(); self.child=Child()
    def forward(self,x): return self.child(x)['value']*2

def hierarchy():
    ep=torch.export.export(Parent(),(torch.ones(2),),strict=True,preserve_module_call_signature=('child',))
    reconstructed=torch.export.unflatten(ep)
    return {'export':ep_info(ep),'unflatten_children':list(dict(reconstructed.named_modules())),
        'result':reconstructed(torch.ones(2)).tolist()}

class Guarded(torch.nn.Module):
    def forward(self,x,flag=True):
        if x.shape[0]>2 and flag: return x+1
        return x-1

def guards():
    ep=torch.export.export(
        Guarded(),(torch.ones(4,2),True),strict=True,
        dynamic_shapes=({0:torch.export.Dim('batch',min=3,max=8)},None))
    return {'export':ep_info(ep),'n5':error(lambda:ep.module()(torch.ones(5,2),True)),
        'n2':error(lambda:ep.module()(torch.ones(2,2),True)),
        'different_flag':error(lambda:ep.module()(torch.ones(4,2),False))}

SIDE=[]
SCALE=2
class SideEffects(torch.nn.Module):
    def forward(self,x):
        SIDE.append('called')
        return x*SCALE

def side_effects():
    global SCALE
    SIDE.clear(); SCALE=2
    ep=torch.export.export(SideEffects(),(torch.ones(2),),strict=False)
    capture_count=len(SIDE); SCALE=5
    result=ep.module()(torch.ones(2)); after_graph=len(SIDE)
    eager=SideEffects()(torch.ones(2))
    return {'export':ep_info(ep),'capture_python_events':capture_count,
        'after_exported_execution':after_graph,'after_eager_execution':len(SIDE),
        'exported_result':result.tolist(),'current_eager_result':eager.tolist()}

class DataBranch(torch.nn.Module):
    def forward(self,x):
        if x.sum()>0: return x+1
        return x-1
class Cond(torch.nn.Module):
    def forward(self,x): return torch.cond(x.sum()>0,lambda z:z+1,lambda z:z-1,(x,))
class While(torch.nn.Module):
    def forward(self,x):
        return torch.while_loop(lambda i,v:i<3,lambda i,v:(i+1,v+1),(torch.tensor(0),x))[1]

def control():
    return {'python_if':error(lambda:ep_info(torch.export.export(DataBranch(),(torch.ones(2),),strict=True))),
        'cond':error(lambda:ep_info(torch.export.export(Cond(),(torch.ones(2),),strict=True))),
        'while_loop':error(lambda:ep_info(torch.export.export(While(),(torch.ones(2),),strict=True)))}

def functionalization():
    def f(x):
        y=x.view(-1); y.add_(3); return y
    data={}
    for remove in ('mutations','mutations_and_views'):
        fn=torch.func.functionalize(f,remove=remove)
        gm=make_fx(fn)(torch.zeros(2,2))
        x=torch.zeros(2,2); out=fn(x)
        data[remove]={'graph':graph(gm),'input_after':x.tolist(),'output':out.tolist(),
            'output_aliases_input':torch._C._is_alias_of(out,x)}
    class Aliased(torch.nn.Module):
        def forward(self,x,y): x.add_(1); return y*2
    x=torch.ones(2)
    ep=torch.export.export(Aliased(),(x,x),strict=True)
    data['mutated_aliased_inputs']={'training':ep_info(ep),
        'functionalization':error(lambda:ep_info(ep.run_decompositions({})))}
    return data

def dynamo():
    def f(x):
        y=x.sin(); torch._dynamo.graph_break(); return y+1
    ex=torch._dynamo.explain(f)(torch.ones(2))
    return {'graph_count':ex.graph_count,'graph_break_count':ex.graph_break_count,
        'break_reasons':[str(x) for x in ex.break_reasons],
        'graphs':[graph(g) for g in ex.graphs],
        'guards':[{'name':g.name,'source':str(g.source),'types':g.guard_types,'code':g.code_list} for g in ex.out_guards]}

class Loss(torch.nn.Module):
    def __init__(self): super().__init__(); self.p=torch.nn.Parameter(torch.ones(2))
    def forward(self,x): return ((self.p*x).square().sum(),)

def aot():
    from torch._functorch.aot_autograd import aot_export_module
    m=Loss(); x=torch.tensor([2.,3.],requires_grad=True)
    gm,sig=aot_export_module(m,(x,),trace_joint=True,output_loss_index=0)
    values=gm(m.p,x)
    return {'graph':graph(gm),'signature':encode(sig),'outputs':[v.tolist() for v in values]}

if __name__=='__main__':
    start=time.perf_counter()
    for name,fn in [('mutations_and_signature',mutations),('parameter_mutation',parameter_mutation),
        ('hierarchy_source',hierarchy),('guards_specialization',guards),('python_side_effects',side_effects),
        ('control_flow',control),('functionalization_alias',functionalization),('dynamo_fragments',dynamo),('aot_joint',aot)]: run(name,fn)
    RESULT['total_seconds']=time.perf_counter()-start
    RESULT['errors']=sum(r['status']=='ERROR' for r in RESULT['probes'])
    (OUT/'results.json').write_text(json.dumps(RESULT,indent=2,sort_keys=True))
    sys.exit(bool(RESULT['errors']))
