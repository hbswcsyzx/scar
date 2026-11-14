"""Mechanical admission for the bounded execution-plan profile."""
import math
import os
from pathlib import Path
from .model import ExecutionPlan,ArrayRegion,PROFILE,OPS

class InvalidPlan(ValueError):pass

def validate_region(region):
    if not isinstance(region,ArrayRegion):raise InvalidPlan('ArrayRegion required')
    if region.frontiers:raise InvalidPlan('unresolved region frontiers: '+', '.join(region.frontiers))
    if not region.parameters or any(type(p)is not str or not p for p in region.parameters) or len(set(region.parameters))!=len(region.parameters):
        raise InvalidPlan('unique array parameters required')
    source=region.source
    if not Path(source.path).is_absolute() or len(source.sha256)!=64 or not source.code_key:
        raise InvalidPlan('versioned source identity required')
    required={'EXACT_NUMPY_NDARRAY_FLOAT64_CPU_2D','FRESH_OUTPUT','NO_INPUT_WRITES'}
    if not required.issubset(region.assumptions):raise InvalidPlan('missing guarded array/effect contract')
    by_id={};scalar={};parameters=[]
    arities={'input':0,'const':0,'slice':1,'neg':1,'add':2,'sub':2,'mul':2,'div':2}
    for node in region.nodes:
        if node.op not in OPS or not node.id or node.id in by_id:raise InvalidPlan('unknown operation or duplicate ID')
        fields={'input':{'name'},'const':{'value'},'slice':{'bounds'}}.get(node.op,set())
        if not isinstance(node.attrs,dict) or (set(node.attrs)!=fields and not
                (node.op=='input' and set(node.attrs)=={'name','index'})):
            raise InvalidPlan('unsupported operation attributes')
        if len(node.inputs)!=arities[node.op] or any(i not in by_id for i in node.inputs):
            raise InvalidPlan('operation arity, topological order or dependency invalid')
        if node.op=='input':
            name=node.attrs.get('name')
            if name not in region.parameters or name in parameters:raise InvalidPlan('input does not name one original parameter')
            if 'index' in node.attrs and (type(node.attrs['index'])is not int or node.attrs['index']!=region.parameters.index(name)):
                raise InvalidPlan('input ordinal mismatch')
            parameters.append(name);scalar[node.id]=False
        elif node.op=='const':
            v=node.attrs.get('value')
            if type(v)not in (int,float) or not math.isfinite(v) or type(v)is int and abs(v)>2**53:
                raise InvalidPlan('unsupported numeric constant')
            scalar[node.id]=True
        elif node.op=='slice':
            bounds=node.attrs.get('bounds')
            if (by_id[node.inputs[0]].op not in ('input','slice') or not isinstance(bounds,(list,tuple)) or len(bounds)!=2
                    or any(not isinstance(p,(list,tuple)) or len(p)!=2 or any(v is not None and
                        (type(v)is not int or abs(v)>2**63-1) for v in p) for p in bounds)):
                raise InvalidPlan('only unit-step 2D input/view slices supported')
            scalar[node.id]=False
        else:scalar[node.id]=all(scalar[i] for i in node.inputs)
        by_id[node.id]=node
    if set(parameters)!=set(region.parameters):raise InvalidPlan('every parameter needs an input node')
    if region.output not in by_id or scalar[region.output] or by_id[region.output].op in ('input','slice'):
        raise InvalidPlan('output must be a fresh array computation')
    live=set();pending=[region.output]
    while pending:
        key=pending.pop()
        if key not in live:live.add(key);pending.extend(by_id[key].inputs)
    if any(n.id not in live and n.op not in ('input','const') for n in region.nodes):
        raise InvalidPlan('dead arithmetic may carry NumPy warning/exception effects')
    return dict(nodes=len(by_id),live_nodes=len(live),array_inputs=len(parameters),source_identity=source.sha256)

def validate_plan(plan):
    if not isinstance(plan,ExecutionPlan) or (plan.schema_version,plan.profile,plan.operator_abi_version)!=(1,PROFILE,1):
        raise InvalidPlan('unsupported execution plan schema/profile/ABI')
    if plan.device!='cpu' or plan.buffer_policy!='fresh_output':raise InvalidPlan('unsupported resource placement or ownership')
    capacity=len(os.sched_getaffinity(0)) if hasattr(os,'sched_getaffinity') else (os.cpu_count() or 1)
    if type(plan.cpu_threads)is not int or not 1<=plan.cpu_threads<=capacity:raise InvalidPlan('CPU thread allocation exceeds available affinity')
    if tuple((x.variable,x.extent) for x in plan.schedule)!=(('row','output.shape[0]'),('col','output.shape[1]')):
        raise InvalidPlan('unsupported loop schedule')
    if plan.proof.get('supported') is False or plan.proof.get('retained_constant_operations'):
        raise InvalidPlan('plan proof retains unsupported operations')
    budget=plan.cost.get('memory_budget_bytes')
    if budget is not None and (type(budget)is not int or budget<8):raise InvalidPlan('invalid output memory budget')
    return validate_region(plan.region)
