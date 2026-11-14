"""Solve local binding versions in bodies selected by actual code entries.

Source declarations remain complete. Runtime evidence selects code bodies,
not values or a future dispatch path. Each selected body's local READ slots
use the existing matched-control solver, including loop backedges and opaque
writer alternatives. This is a state-graph producer, not an optimization.
"""
import argparse
from collections import Counter,defaultdict
from concurrent.futures import ProcessPoolExecutor,as_completed
import gc
from hashlib import sha256
import json
import multiprocessing
import os
from pathlib import Path
import resource
import time

from scar.analysis.program_view import ProgramView,_digest
from scar.analysis.program_state_view import _pins as state_pins
from scar.analysis.binding_track_storage import publish_state_view,pins as storage_pins
from scar.analysis.program_state_coverage import _release
from scar.analysis.source_declared_catalog import read_source_catalog,_receipt,_check
from scar.analysis.source_local_state import local_read_tracks
from scar.analysis.source_observed_interfaces import ObservedFunctionInterfaceStore
from scar.analysis.source_stage import _durable_bytes,_durable_mkdir
from scar.analysis.source_template_links import _json
from scar.analysis.source_value_flow import _artifact
from scar.ir.record_codec import encode


SCHEMA='scar.observed-source-binding-states'
_WORKER=None


def _pins():
    from scar.analysis import source_observed_interfaces,source_local_state,source_graph_material
    return dict(producer=sha256(Path(__file__).read_bytes()).hexdigest(),state=state_pins(),
        selection=sha256(Path(source_observed_interfaces.__file__).read_bytes()).hexdigest(),
        materials=sha256(Path(source_graph_material.__file__).read_bytes()).hexdigest(),
        local_slots=sha256(Path(source_local_state.__file__).read_bytes()).hexdigest(),storage=storage_pins())


def compatible_pins(actual):
    """Producer provenance may evolve; used analysis contracts stay exact.

    The reader independently checks actual code selection. Schema-1 units
    predate the storage pin; their format and analysis pins are checked too.
    """
    expected=_pins();provenance=actual.get('producer')
    if type(provenance)is not str or len(provenance)!=64 or any(c not in '0123456789abcdef' for c in provenance):return False
    if {k:v for k,v in actual.items() if k not in ('producer','storage')}!={k:v for k,v in expected.items() if k not in ('producer','storage')}:return False
    return 'storage' not in actual or actual['storage']==expected['storage']


def _initialize(catalog,out,pins,limits,memory_mib):
    global _WORKER
    soft,hard=resource.getrlimit(resource.RLIMIT_AS);limit=memory_mib*1024*1024
    if hard!=resource.RLIM_INFINITY:limit=min(limit,hard)
    resource.setrlimit(resource.RLIMIT_AS,(limit,hard))
    _WORKER=read_source_catalog(catalog),Path(out),pins,limits


def _unit(task):
    unit,functions=task;catalog,out,pins,limits=_WORKER;started=time.monotonic()
    view=ProgramView(catalog);state=view.state(unit)
    selected=frozenset(functions)
    tracks=tuple(pair for pair in local_read_tracks(state) if pair[0] in selected)
    for function,namespace in tracks:state.track(function,namespace,**limits)
    folder=out/'units'/unit
    published=publish_state_view(state,folder)
    complete=sum(g.traversal_complete and g.dataflow_complete for g in state.tracks)
    frontier_counts=Counter(f.reason for g in state.tracks for f in g.frontiers)
    row=dict(unit=unit,state=_receipt(folder/'result.json'),selected_functions=len(selected),
        selected_local_read_slots=len(tracks),completed_fixed_points=complete,
        budget_or_control_incomplete=len(tracks)-complete,
        frontier_counts=dict(frontier_counts),counts=published['counts'],
        shared_function_value_flows=len(state.flows),
        loop_iterations_unrolled=False,runtime_value_identity_proven=False,
        seconds=time.monotonic()-started,worker_pid=os.getpid(),
        worker_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    state.check()
    if pins!=_pins():raise ValueError('observed binding producer changed during solve')
    _release(catalog,view);del state,view;gc.collect()
    return row


def build(interfaces,out,*,jobs=8,memory_mib=8192,max_states=20000,max_stack=128,max_updates=1000000):
    started=time.monotonic();out=Path(out).absolute()
    if out.exists() or out.resolve()!=out or not 1<=jobs<=32 or memory_mib<256:
        raise ValueError('fresh canonical output, 1..32 workers and >=256 MiB required')
    limits=dict(max_states=max_states,max_stack=max_stack,max_updates=max_updates)
    if any(type(v)is not int or v<1 for v in limits.values()):raise ValueError('positive solver limits required')
    pins=_pins();store=ObservedFunctionInterfaceStore(interfaces);index=store.index
    parent=_receipt(store.path/'result.json');catalog=_artifact(store.catalog.path/'result.json',store.catalog.report['schema'])
    actual={(entry.invocation.process_id,entry.code) for entry in index.codes.trace.entries}
    selected=defaultdict(set);links=[]
    for row in index.codes.records.values():
        captures=tuple(c for c in row.captures if (c.process_id,c.code.key) in actual)
        if captures:
            selected[row.function.unit].add(row.function)
            links.append(dict(function=encode(row.function),code_link=encode(row.id),
                function_fact=encode(row.function_fact),captured_codes=encode(captures)))
    _durable_mkdir(out)
    plan=dict(schema=SCHEMA+'.plan',schema_version=1,parent=parent,catalog=encode(catalog),
        selection='RECORDED_FUNCTION_BODY_ALTERNATIVES_ALL_LOCAL_READ_SLOTS',
        functions=links,units=sorted(selected),run_scope=index.codes.targets.source_sha256,
        non_function_body_correspondences=sum(len(getattr(index.codes,name)) for name in
            ('scope_records','request_records','compiler_records')),
        non_function_body_state='ORIGINAL_SOURCE_WORLD_INTERFACES_NOT_LOCAL_FUNCTION_BINDING_TRACKS',
        jobs=min(jobs,len(selected) or 1),worker_memory_mib=memory_mib,limits=limits,pins=pins)
    _durable_bytes(out/'plan.json',_json(plan),replace=False);rows=[]
    tasks=[(unit,tuple(sorted(functions,key=_digest))) for unit,functions in sorted(selected.items())]
    with ProcessPoolExecutor(max_workers=plan['jobs'],mp_context=multiprocessing.get_context('spawn'),
            initializer=_initialize,initargs=(str(store.catalog.path),str(out),pins,limits,memory_mib)) as pool:
        pending={pool.submit(_unit,task):task[0] for task in tasks}
        for future in as_completed(pending):
            row=future.result();rows.append(row)
            print(json.dumps(dict(done=len(rows),total=len(tasks),unit=row['unit'],
                slots=row['selected_local_read_slots'],versions=row['counts']['versions'],
                seconds=round(row['seconds'],3))),flush=True)
    rows.sort(key=lambda row:row['unit']);store.validate();_check(parent)
    if pins!=_pins():raise ValueError('observed binding inputs or producer changed')
    counts=Counter();frontiers=Counter()
    for row in rows:
        counts.update({k:v for k,v in row['counts'].items() if type(v)is int})
        frontiers.update(row['frontier_counts'])
    report=dict(schema=SCHEMA,schema_version=1,plan=plan,units=rows,counts=dict(counts),
        selected_local_read_slots=sum(r['selected_local_read_slots'] for r in rows),
        completed_fixed_points=sum(r['completed_fixed_points'] for r in rows),
        budget_or_control_incomplete=sum(r['budget_or_control_incomplete'] for r in rows),
        frontier_counts=dict(frontiers),source_bodies_copied=False,loops_unrolled=False,
        actual_frame_or_tensor_contents_proven=False,opaque_writers_excluded=False,
        target_executed=False,first_stage_complete=False,seconds=time.monotonic()-started)
    _durable_bytes(out/'result.json',_json(report),replace=False);return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--interfaces',required=True);p.add_argument('--out',required=True)
    p.add_argument('--jobs',type=int,default=8);p.add_argument('--memory-mib',type=int,default=8192)
    a=p.parse_args();r=build(a.interfaces,a.out,jobs=a.jobs,memory_mib=a.memory_mib)
    print(json.dumps({k:r[k] for k in ('selected_local_read_slots','completed_fixed_points',
        'budget_or_control_incomplete','counts','seconds')}),flush=True)


if __name__=='__main__':main()
