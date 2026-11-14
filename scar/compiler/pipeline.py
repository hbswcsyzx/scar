"""Compile guarded source regions through graph passes to C++ artifacts."""
from dataclasses import asdict
import argparse
import json
import os
from pathlib import Path
import time

from .frontend import discover_regions
from .model import write_plan
from .validation import validate_plan

def compile_source(source,out,*,catalog=None,memory_budget_bytes=None,cpu_threads=None):
    from scar.optimization import optimize_region
    from scar.codegen import build
    started=time.perf_counter();out=Path(out).absolute()
    if out.exists():raise ValueError('fresh compiler output required')
    out.mkdir(parents=True)
    regions,rejections=discover_regions(source,catalog=catalog)
    capacity=len(os.sched_getaffinity(0)) if hasattr(os,'sched_getaffinity') else (os.cpu_count() or 1)
    threads=min(4,capacity) if cpu_threads is None else cpu_threads
    (out/'graph.json').write_text(json.dumps(dict(schema='scar.optimization-regions',schema_version=1,
        regions=[asdict(r) for r in regions],rejections=rejections),indent=2,allow_nan=False)+'\n')
    publications=[]
    for ordinal,region in enumerate(regions):
        plan=optimize_region(region,memory_budget_bytes=memory_budget_bytes,cpu_threads=threads)
        folder=out/f'region-{ordinal}';folder.mkdir()
        write_plan(plan,folder/'plan.json')
        row=dict(region=region.id,qualname=region.source.qualname,source=asdict(region.source),
            plan=str(folder/'plan.json'),proof=plan.proof,cost=plan.cost,selected=False)
        try:
            validate_plan(plan);artifact=build(plan,folder/'native')
            row.update(status='COMPILED_UNMEASURED',artifact=str(folder/'native'),backend=artifact.report)
        except (ValueError,NotImplementedError) as error:
            row.update(status='UNSUPPORTED',reason=str(error))
        publications.append(row)
    report=dict(schema='scar.compiler-build',schema_version=1,source=str(Path(source).absolute()),
        catalog=None if catalog is None else str(Path(catalog).absolute()),regions=publications,
        rejected_functions=len(rejections),whole_program_compiled=False,first_stage_complete=False,
        hardware=dict(cpu_affinity_capacity=capacity,planned_cpu_threads=threads),
        selected_for_use=False,seconds=time.perf_counter()-started)
    (out/'result.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    return report

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source');parser.add_argument('--out',required=True);parser.add_argument('--catalog')
    parser.add_argument('--memory-budget-bytes',type=int)
    parser.add_argument('--cpu-threads',type=int,help='CPU workers; default min(4, available affinity)')
    args=parser.parse_args();r=compile_source(args.source,args.out,catalog=args.catalog,
        memory_budget_bytes=args.memory_budget_bytes,cpu_threads=args.cpu_threads)
    print(json.dumps(dict(compiled=sum(x['status']=='COMPILED_UNMEASURED' for x in r['regions']),
        regions=len(r['regions']),seconds=r['seconds'],result=str(Path(args.out)/'result.json'))))

if __name__=='__main__':main()
