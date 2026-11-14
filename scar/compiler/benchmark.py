"""Clean, paired region validation and measured no-op/native selection."""
import argparse
from dataclasses import asdict
from hashlib import sha256
import importlib.util
import inspect
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import time
import warnings
import numpy as np
from scar.codegen import CppArtifact,load
from .runtime import guarded_function
from scar.optimization import select_measured

def load_source(path):
    path=Path(path).resolve();spec=importlib.util.spec_from_file_location('scar_compiler_validation_target',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def resolve(module,qualname):
    obj=module
    for part in qualname.split('.'):
        if part=='<locals>':raise ValueError('local functions need a captured invocation')
        obj=getattr(obj,part)
    return obj

def distribution(values):
    return dict(median=statistics.median(values),min=min(values),max=max(values),
        stdev=statistics.stdev(values) if len(values)>1 else 0,samples=values)

def bitwise_equal(left,right):
    return left.dtype==right.dtype and left.shape==right.shape and np.array_equal(left.view(np.uint64),right.view(np.uint64))

def benchmark(artifact_path,out,*,shape=(1026,1026),warmup=3,repetitions=9):
    if warmup<0 or repetitions<3 or len(shape)!=2 or min(shape)<3:raise ValueError('valid 2D shape and >=3 repetitions required')
    if sys.getprofile() is not None or sys.gettrace() is not None:raise ValueError('clean benchmark cannot have Python trace/profile hooks')
    artifact=artifact_path if isinstance(artifact_path,CppArtifact) else load(artifact_path)
    if sha256(Path(artifact.plan.region.source.path).read_bytes()).hexdigest()!=artifact.plan.region.source.sha256:
        raise ValueError('benchmark source version differs from compiled graph')
    module=load_source(artifact.plan.region.source.path)
    original=resolve(module,artifact.plan.region.source.qualname)
    wrapped=guarded_function(original,artifact,exclusive_inputs=True,trial=True)
    signature=inspect.signature(original)
    def invoke(function,values):
        positional=[];keywords={}
        for name,value in zip(artifact.plan.region.parameters,values,strict=True):
            if signature.parameters[name].kind is inspect.Parameter.KEYWORD_ONLY:keywords[name]=value
            else:positional.append(value)
        return function(*positional,**keywords)
    rng=np.random.default_rng(42);arrays=[rng.normal(0,0.1,size=shape) for _ in artifact.plan.region.parameters]
    snapshots=[a.copy() for a in arrays];before=invoke(original,arrays);after=invoke(wrapped,arrays)
    if not bitwise_equal(before,after):raise AssertionError('region output differs bitwise')
    if any(not np.array_equal(a,b) for a,b in zip(arrays,snapshots)):raise AssertionError('region mutated input')
    if any(np.shares_memory(after,a) for a in arrays):raise AssertionError('output aliases input')
    after[:]=123
    if not bitwise_equal(invoke(original,arrays),invoke(wrapped,arrays)):raise AssertionError('output reuse exposed caller mutation')
    arrays[0][:]+=0.001
    if not bitwise_equal(invoke(original,arrays),invoke(wrapped,arrays)):raise AssertionError('input mutation reused stale contents')
    fallback_before=wrapped.scar_stats['fallback_calls']
    low=[a.astype(np.float32) for a in arrays]
    np.testing.assert_array_equal(invoke(original,low),invoke(wrapped,low))
    if wrapped.scar_stats['fallback_calls']!=fallback_before+1:raise AssertionError('dtype fallback did not execute original once')
    bad=[a.copy() for a in arrays];bad[0][:]=np.nan
    with warnings.catch_warnings(record=True):
        np.testing.assert_array_equal(invoke(original,bad),invoke(wrapped,bad))
    fallback_before_timing=wrapped.scar_stats['fallback_calls']
    for _ in range(warmup):invoke(original,arrays);invoke(wrapped,arrays)
    timings=[[],[]]
    for i in range(repetitions):
        for which in ((0,1) if i%2==0 else (1,0)):
            started=time.perf_counter_ns();result=invoke(original if which==0 else wrapped,arrays)
            elapsed=time.perf_counter_ns()-started;del result;timings[which].append(elapsed/1e9)
    no_fallback=wrapped.scar_stats['fallback_calls']==fallback_before_timing
    a,b=map(distribution,timings);speedup=a['median']/b['median']
    decision=select_measured(artifact.plan,timings[0],timings[1],validated=True,
        native_fallbacks=wrapped.scar_stats['fallback_calls']-fallback_before_timing)
    selected=decision['selected']
    report=dict(schema='scar.region-benchmark',schema_version=1,scope='controlled_synchronous_cpu_region',
        validation=dict(bitwise_output=True,input_unchanged=True,fresh_output=True,mutable_input_invalidation=True,
            caller_output_mutation_safe=True,dtype_fallback_once=True,nonfinite_fallback=True),
        source=asdict(artifact.plan.region.source),artifact=artifact.report,shape=list(shape),
        region_id=artifact.plan.region.id,
        resource_binding=None if artifact.plan.resource_binding is None else asdict(artifact.plan.resource_binding),
        warmup=warmup,repetitions=repetitions,paired_order='AB_BA_ALTERNATING',instrumented=False,
        baseline_seconds=a,optimized_seconds=b,speedup=speedup,native_without_fallback=no_fallback,
        stats=wrapped.scar_stats,decision=decision['decision'],selection=decision,
        profitability='profitable' if selected else 'not profitable',selection_margin=0.05,
        assumptions=['SYNCHRONOUS_CPU_EXECUTION','NO_FOREIGN_CONCURRENT_INPUT_WRITERS'],
        environment=dict(python=sys.version,numpy=np.__version__,platform=platform.platform(),
            processor=platform.processor(),logical_cpus=os.cpu_count(),
            cpu_affinity=sorted(os.sched_getaffinity(0)) if hasattr(os,'sched_getaffinity') else None,
            planned_cpu_threads=artifact.plan.cpu_threads,torch_cuda_used=False,
            compiler=artifact.report.get('compiler_command')),
        whole_program_validated=False,first_stage_complete=False)
    Path(out).write_text(json.dumps(report,indent=2,allow_nan=False)+'\n');return report

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('artifact');p.add_argument('--out',required=True)
    p.add_argument('--shape',type=int,nargs=2,default=(1026,1026));p.add_argument('--warmup',type=int,default=3)
    p.add_argument('--repetitions',type=int,default=9);a=p.parse_args()
    r=benchmark(a.artifact,a.out,shape=a.shape,warmup=a.warmup,repetitions=a.repetitions)
    print(json.dumps({k:r[k] for k in ('decision','speedup','profitability','baseline_seconds','optimized_seconds')}))

if __name__=='__main__':main()
