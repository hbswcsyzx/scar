"""Bounded parallel inventory of original local graph/state interfaces.

This is coverage evidence, not an optimization or reachability proof. Original
F4 bodies remain in their stores; per-unit gaps retain normalized operation IDs.
Binding fixed points are deliberately reported as demand analyses, not run or
claimed complete by this inventory.
"""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor,as_completed
import gc
from hashlib import sha256
import json
import multiprocessing
import os
from pathlib import Path
import resource
import time

from scar.analysis.program_view import ProgramView
from scar.analysis.source_context_query import ContextTargetGraph
from scar.analysis.source_declared_calls import _NoTargets,_check_targets
from scar.analysis.source_local_state import local_read_tracks
from scar.analysis.source_stage import _durable_bytes,_durable_mkdir
from scar.analysis.source_template_links import _json
from scar.analysis.normal_output import write_table
from scar.analysis.program_state_view import _pins as state_pins,_counts
from scar.analysis.source_value_flow import _artifact
from scar.ir.record_codec import encode


_WORKER=None


def _pins():
    from scar.analysis import source_local_state
    return dict(inventory=sha256(Path(__file__).read_bytes()).hexdigest(),state=state_pins(),
        track_selection=sha256(Path(source_local_state.__file__).read_bytes()).hexdigest())


def _release(catalog,view):
    if view is not None:
        view.dependencies.providers.clear();view.metadata_providers.clear()
        view.units.clear();view.namespaces.clear();view.state_providers.clear()
    keep=set(catalog.fact_store.original_source_units);seen=set()
    def release(parent):
        if id(parent) in seen:return
        seen.add(id(parent))
        for unit in tuple(parent.loaded):
            if unit not in keep:del parent.loaded[unit]
        for child in getattr(parent,'parents',()):release(child)
    release(catalog.fact_store)
    for parent in catalog.fact_store._source_parents.values():release(parent)


def _initialize(path,out,pins,memory_mib):
    global _WORKER
    import sys
    sys.meta_path.insert(0,_NoTargets());_check_targets()
    soft,hard=resource.getrlimit(resource.RLIMIT_AS);limit=memory_mib*1024*1024
    if hard!=resource.RLIM_INFINITY:limit=min(limit,hard)
    resource.setrlimit(resource.RLIMIT_AS,(limit,hard))
    _WORKER=ContextTargetGraph(path),Path(out),pins


def _unit(unit):
    catalog,out,pins=_WORKER;started=time.monotonic();view=None;folder=out/'units'/unit
    _durable_mkdir(folder);row=catalog.fact_store.rows[unit]
    try:
        view=ProgramView(catalog);state=view.state(unit);state.content();source=state.source
        steps=sum(len(plan.steps) for plan in source.plans.values())
        if steps!=len(state.requests):raise ValueError('original operation denominator differs from state requests')
        counts=_counts(state)
        counts.update(templates=len(source.plans),original_steps=steps,
            regions=sum(len(plan.regions) for plan in source.plans.values()),
            normalized_endpoints=len(source.nodes),normalized_relations=len(source.edge_sources),
            local_read_tracks_available=len(local_read_tracks(state)),local_read_tracks_solved=len(state.tracks))
        instructions=Counter(request.rule.instruction for request in state.requests.values())
        families=Counter(request.rule.family.value for request in state.requests.values())
        pending=Counter(reason for request in state.requests.values() for reason in request.pending)
        gaps=tuple(request for request in state.requests.values() if request.missing_rules)
        table=write_table(folder/'gaps.jsonl.gz',gaps)
        result=dict(schema='scar.source-state-unit-coverage',schema_version=1,status='INVENTORIED',
            unit=unit,path=row['path'],namespace=encode(state.namespace),source_material=encode(state.material.result_artifact),
            counts=counts,instructions=dict(instructions),families=dict(families),open_effect_fields=dict(pending),
            gaps=table,gap_operations=len(gaps),binding_fixed_points_complete=False,
            target_executed=False,first_stage_complete=False)
        state.check();_check_targets()
    except Exception as error:
        result=dict(schema='scar.source-state-unit-coverage',schema_version=1,status='FAILED',unit=unit,path=row['path'],
            error_type=type(error).__name__,error=str(error),target_executed=False,first_stage_complete=False)
    if pins!=_pins():raise ValueError('coverage producer changed while a unit was running')
    result.update(seconds=time.monotonic()-started,worker_pid=os.getpid(),
        worker_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    _durable_bytes(folder/'result.json',_json(result),replace=False)
    if view is not None:
        _release(catalog,view)
    else:_release(catalog,None)
    # Break state/content/view cycles before the next independent unit.
    if 'state' in locals():del state
    if 'source' in locals():del source
    del view;gc.collect()
    return result


def inventory(catalog,out,*,units=(),jobs=16,memory_mib=8192):
    started=time.monotonic();pins=_pins();out=Path(out).absolute()
    if out.exists():raise ValueError('fresh state-coverage output required')
    if type(jobs) is not int or jobs<1 or type(memory_mib) is not int or memory_mib<256:
        raise ValueError('positive worker count and at least 256 MiB per worker required')
    source=ContextTargetGraph(catalog);all_units=set(source.fact_store.rows)
    selected=all_units if not units else set(units)
    if not selected<=all_units:raise ValueError('coverage unit is outside the original catalog')
    ordered=sorted(selected,key=lambda u:(-source.fact_store.rows[u]['counts']['ports'],u))
    _durable_mkdir(out);parent=_artifact(source.path/'result.json',source.report['schema'])
    plan=dict(schema='scar.source-state-coverage-plan',schema_version=1,catalog=str(source.path),parent=encode(parent),
        scope='CATALOG' if not units else 'EXPLICIT_ORIGINAL_UNITS',catalog_units=len(all_units),
        selected_units=ordered,entry_sources=source.report['entry_sources'],pins=pins,
        jobs=min(jobs,len(ordered) or 1),worker_memory_mib=memory_mib,
        binding_fixed_points_run=False,target_executed=False,first_stage_complete=False)
    _durable_bytes(out/'plan.json',_json(plan),replace=False);results={}
    with ProcessPoolExecutor(max_workers=plan['jobs'],mp_context=multiprocessing.get_context('spawn'),
            initializer=_initialize,initargs=(str(source.path),str(out),pins,memory_mib)) as executor:
        tasks={executor.submit(_unit,unit):unit for unit in ordered}
        for task in as_completed(tasks):
            row=task.result();results[row['unit']]=row
            print(json.dumps(dict(done=len(results),total=len(ordered),unit=row['unit'],status=row['status'],
                seconds=round(row['seconds'],3),gap_operations=row.get('gap_operations'),
                error_type=row.get('error_type'))),flush=True)
    if pins!=_pins() or encode(_artifact(source.path/'result.json',parent.schema))!=encode(parent):
        raise ValueError('coverage source or producer changed')
    scalar=Counter();gaps=Counter();instructions=Counter();families=Counter();failures=[]
    for unit,row in results.items():
        if row['status']=='FAILED':failures.append(dict(unit=unit,error_type=row['error_type'],error=row['error']));continue
        for key,value in row['counts'].items():
            if type(value) is int:scalar[key]+=value
        gaps.update(row['counts']['missing_address_rules']);instructions.update(row['instructions']);families.update(row['families'])
    report=dict(schema='scar.source-state-coverage',schema_version=1,status='COMPLETE_INVENTORY' if not failures else 'INCOMPLETE_INVENTORY',
        plan=plan,completed_units=len(results),inventoried_units=len(results)-len(failures),failures=failures,
        counts=dict(scalar),missing_address_rules=dict(gaps),instructions=dict(instructions),families=dict(families),
        local_model_closed=False,call_reachability_proven=False,binding_fixed_points_complete=False,
        target_executed=False,first_stage_complete=False,seconds=time.monotonic()-started)
    _durable_bytes(out/'result.json',_json(report),replace=False)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog',required=True);parser.add_argument('--out',required=True)
    parser.add_argument('--unit',action='append',default=[]);parser.add_argument('--jobs',type=int,default=16)
    parser.add_argument('--memory-mib',type=int,default=8192)
    args=parser.parse_args();report=inventory(args.catalog,args.out,units=args.unit,jobs=args.jobs,memory_mib=args.memory_mib)
    print(json.dumps({key:report[key] for key in ('status','completed_units','inventoried_units','missing_address_rules','seconds')}))


if __name__=='__main__':main()
