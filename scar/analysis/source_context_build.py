"""Solve actual script entries through compiled contexts, with typed receipts."""
import argparse
from collections import Counter
from contextlib import ExitStack
import faulthandler
from hashlib import sha256
import json
from pathlib import Path
import sys
import time
from types import FunctionType

from scar.analysis import source_context_solver,source_context_fact_store,source_context_interfaces
from scar.analysis import source_namespace_flow,source_relation_replay,source_class_queries
from scar.analysis import normal_targets,source_launch,source_namespace_graph
from scar.analysis import normal_entry,normal_facts,source_namespace_builtins
from scar.analysis import source_frame_captures,source_frame_globals
from scar.analysis import source_root_namespace_views
from scar.ir.program import source_builtin_namespaces
from scar.ir.program import source_frame_bindings
from scar.analysis.normal_facts import SourceFactStore
from scar.analysis.normal_output import write_table
from scar.analysis.source_stage import _durable_bytes,_durable_mkdir
from scar.analysis.source_template_links import _json


def pins():
    from scar.analysis import source_solver_observations
    return {name:sha256(Path(module.__file__).read_bytes()).hexdigest() for name,module in (
        ('solver',source_context_solver),('facts',source_context_fact_store),
        ('interfaces',source_context_interfaces),('namespaces',source_namespace_flow),
        ('relations',source_relation_replay),('class_queries',source_class_queries),
        ('original_publisher',normal_targets),('entry_contract',source_launch),
        ('namespace_graph',source_namespace_graph),('entry_solver',normal_entry),
        ('fact_reader',normal_facts),('builtin_flow',source_namespace_builtins),
        ('builtin_types',source_builtin_namespaces),('frame_index',source_frame_captures),
        ('frame_flow',source_frame_globals),('frame_types',source_frame_bindings),
        ('root_views',source_root_namespace_views),('observations',source_solver_observations))}


def build_context_targets(facts,namespaces,entry,interfaces,out,*,max_events=2_000_000,jobs=4,supplements=(),observe_ports=()):
    with ExitStack() as resources:
        return _build_context_targets(facts,namespaces,entry,interfaces,out,max_events=max_events,jobs=jobs,
            resources=resources,supplements=tuple(supplements),observe_ports=tuple(observe_ports))


def _build_context_targets(facts,namespaces,entry,interfaces,out,*,max_events,jobs,resources,supplements,observe_ports):
    started=time.monotonic(); out=Path(out).absolute()
    if out.exists():raise ValueError('fresh context target output required')
    base=SourceFactStore(facts); graph=source_namespace_graph.NamespaceGraph(namespaces)
    contract=source_launch.read_script_entry(entry,base)
    initial=pins(); producer=sha256(Path(__file__).read_bytes()).hexdigest()
    supplemental_sources=tuple(SourceFactStore(pair[0]) for pair in supplements)
    solver=source_context_solver.ContextEntrySolver(base,graph,(),interfaces=interfaces,jobs=jobs,
        supplemental_sources=supplemental_sources,supplemental_interfaces=tuple(pair[1] for pair in supplements),
        entry_units=(contract.source.unit,))
    resources.callback(solver.frames.close)
    resources.callback(solver.generators.close)
    prepared=time.monotonic()
    solver.frames.configure_entry(contract)
    for binding in contract.globals:
        value=binding.literal.to_python()
        solver.namespace_value(solver.ns(contract.source.unit,binding.namespace),('constant',type(value).__name__,value))
    while (solver.queue or solver.pending or solver.namespace_pending) and (max_events is None or solver.events<max_events):
        solver.solve(solver.events+200_000 if max_events is None else min(max_events,solver.events+200_000))
        print(json.dumps(dict(phase='CONTEXT_ENTRY_PROPAGATION',events=solver.events,frontier=len(solver.queue),
            namespace_frontier=len(solver.namespace_pending),active_scopes=len(solver.active_scopes),
            exec_connections=len(solver.namespace_flow.connections),loaded_units=len(solver.store.loaded),
            seconds=time.monotonic()-started)),file=sys.stderr,flush=True)
    fixed=not solver.queue and not solver.pending and not solver.namespace_pending
    solver.frames.validate_parents()
    solver.complete_call_demands(); _durable_mkdir(out)
    _durable_bytes(out/'context-facts.json',solver.store.raw,replace=False)
    observations=None
    if observe_ports:
        from scar.analysis.source_solver_observations import snapshot_ports
        raw=_json(snapshot_ports(solver,observe_ports))
        _durable_bytes(out/'solver-observations.json',raw,replace=False)
        observations=dict(path='solver-observations.json',bytes=len(raw),sha256=sha256(raw).hexdigest())
    extra=dict(analysis_mode='ENTRY_COMPILED_CONTEXT_MAY_ANALYSIS',entry_sources=[contract.source.path],
        active_code_scopes=len(solver.active_scopes),loaded_sources=len(solver.units),
        active_source_calls=len(solver.active_call_indices),pending_code_scopes=len(solver.pending),
        namespace_frontier=len(solver.namespace_pending),
        active_compiled_namespaces=sorted({o.unit for o in solver.active_scopes if o.unit in solver.store.original_source_units}),
        admitted_exec_connections=len(solver.namespace_flow.connections),
        entry_activations=write_table(out/'entry-activations.jsonl.gz',solver.activations.values()),
        entry_module_demands=write_table(out/'entry-module-demands.jsonl.gz',solver.module_demands.values()),
        entry_body_demands=write_table(out/'entry-body-demands.jsonl.gz',solver.body_demands.values()),
        entry_call_demands=write_table(out/'entry-call-demands.jsonl.gz',solver.call_demands.values()),
        exec_connections=write_table(out/'exec-connections.jsonl.gz',solver.namespace_flow.connections.values()),
        builtin_candidates=write_table(out/'builtin-candidates.jsonl.gz',solver.namespace_flow.builtins.fallbacks),
        builtin_selections=write_table(out/'builtin-selections.jsonl.gz',solver.namespace_flow.builtins.selections),
        root_namespace_bindings=write_table(out/'root-namespace-bindings.jsonl.gz',solver.frames.roots.values()),
        frame_globals_bindings=write_table(out/'frame-globals-bindings.jsonl.gz',solver.frames.bindings.values()),
        frame_globals_reads=write_table(out/'frame-globals-reads.jsonl.gz',solver.frames.reads.values()),
        frame_globals_obligations=write_table(out/'frame-globals-obligations.jsonl.gz',solver.frames.obligations.values()),
        frame_capture_obligations=write_table(out/'frame-capture-obligations.jsonl.gz',
            (o for material in solver.frames.materials.values() for o in material.obligations)),
        static_input_bindings=write_table(out/'static-input-bindings.jsonl.gz',solver.frames.views.input_bindings.values()),
        frame_source_stats=solver.frames.index.stats,
        construction_queries=dict(solver.constructions.query_stats),
        namespace_requests=len(solver.namespace_flow.mapping_requests),
        analysis_phase_seconds=dict(preparation=prepared-started,propagation=time.monotonic()-prepared))
    # Reuse the unchanged relation/table publisher. Its source-only report is
    # intercepted before writing; this graph gets a distinct context schema.
    def tables_only(path,data,**kwargs):
        if Path(path)==out/'result.json':return
        return _durable_bytes(path,data,**kwargs)
    original=normal_targets._publish
    publish=FunctionType(original.__code__,dict(original.__globals__,_durable_bytes=tables_only),
        original.__name__,original.__defaults__,original.__closure__)
    report=publish(solver,base.path,base.raw,solver.store.report,out,started,max_events,fixed,solver.stars,extra)
    solver.frames.validate_parents(); solver.frames.close()
    if (pins()!=initial or sha256(Path(__file__).read_bytes()).hexdigest()!=producer
            or (base.path/'result.json').read_bytes()!=base.raw):
        raise ValueError('context source rules changed during propagation')
    solver.store.validate_parents()
    def reference(path):
        path=Path(path).absolute()
        return dict(path=str(path),sha256=sha256((path/'result.json').read_bytes()).hexdigest())
    report.update(schema='scar.context-source-targets',schema_version=1,
        status='CONTEXT_TARGET_FIXED_POINT' if fixed else 'CONTEXT_TARGET_BUDGET_FRONTIER',
        source_only_publisher_sha256=report.pop('implementation_sha256'),
        implementation_sha256=producer,extension_pins=initial,
        context_facts=dict(path='context-facts.json',bytes=len(solver.store.raw),sha256=sha256(solver.store.raw).hexdigest()),
        namespace_graph=reference(namespaces),script_entry=reference(entry),
        supplemental_sources=[dict(facts=reference(source.path),interfaces=reference(pair[1]))
            for source,pair in zip(supplemental_sources,supplements)],
        entry_unit=contract.source.unit,importable_compiled_namespaces=False,
        namespace_lookup_semantics='ORDERED_SOURCE_GRAPH_CONDITIONAL_MAY_TRANSFER',
        solver_observations=observations,
        fixed_point_scope='ADMITTED_SOURCE_AND_EXEC_CONTEXT_CONSTRAINTS',
        target_executed=False,first_stage_complete=False,seconds=time.monotonic()-started)
    _durable_bytes(out/'result.json',_json(report),replace=False)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('facts','namespaces','entry','interfaces','out'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--max-events',type=int,default=2_000_000)
    parser.add_argument('--until-fixed-point',action='store_true')
    parser.add_argument('--jobs',type=int,default=4)
    parser.add_argument('--supplement',nargs=2,action='append',default=[],metavar=('FACTS','INTERFACES'),
        help='append a pinned source catalog and its local interfaces without changing existing ports')
    parser.add_argument('--observe-port',nargs=2,action='append',default=[],metavar=('UNIT','LOCAL'),
        help='snapshot selected analyzer port values and subscriptions at this event frontier')
    parser.add_argument('--stack-log')
    args=parser.parse_args()
    with ExitStack() as diagnostics:
        if args.stack_log:
            stream=diagnostics.enter_context(Path(args.stack_log).open('x'))
            faulthandler.dump_traceback_later(30,repeat=True,file=stream)
            diagnostics.callback(faulthandler.cancel_dump_traceback_later)
        report=build_context_targets(args.facts,args.namespaces,args.entry,args.interfaces,args.out,
            max_events=None if args.until_fixed_point else args.max_events,jobs=args.jobs,supplements=args.supplement,
            observe_ports=tuple((unit,int(local)) for unit,local in args.observe_port))
    print(json.dumps({name:report[name] for name in ('status','value_events','frontier','admitted_exec_connections',
        'active_compiled_namespaces','seconds')}),flush=True)


if __name__=='__main__':main()
