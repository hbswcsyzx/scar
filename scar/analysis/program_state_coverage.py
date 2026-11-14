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
from scar.analysis.source_declared_catalog import read_source_catalog
from scar.analysis.source_declared_calls import _NoTargets,_check_targets
from scar.analysis.source_local_state import local_read_tracks
from scar.analysis.source_stage import _durable_bytes,_durable_mkdir
from scar.analysis.source_template_links import _json
from scar.analysis.normal_output import write_table
from scar.analysis.program_state_view import _pins as state_pins,_counts,_rows
from scar.analysis.program_view_storage import pack_nodes,pack_edges
from scar.analysis.source_value_flow import _artifact
from scar.ir.record_codec import encode


_WORKER=None


def _pins():
    from scar.analysis import source_local_state,program_view_storage
    return dict(inventory=sha256(Path(__file__).read_bytes()).hexdigest(),state=state_pins(),
        graph_storage=sha256(Path(program_view_storage.__file__).read_bytes()).hexdigest(),
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
    _WORKER=read_source_catalog(path),Path(out),pins


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
        if set(source.expanded)!=set(source.material.interfaces['nodes']):
            raise ValueError('local graph did not cover every declared shared template')
        graph_folder=folder/'graph';_durable_mkdir(graph_folder)
        graph_tables=dict(nodes=write_table(graph_folder/'nodes.jsonl.gz',pack_nodes(source)),
            edges=write_table(graph_folder/'edges.jsonl.gz',pack_edges(source)))
        projections=sum(len(rows) for rows in source.edge_sources.values())
        if (graph_tables['nodes']['records'],graph_tables['edges']['records'])!=(len(source.nodes),projections):
            raise ValueError('stored graph node or edge projection denominator differs')
        state_folder=folder/'state';_durable_mkdir(state_folder)
        state_tables={name:write_table(state_folder/(name+'.jsonl.gz'),rows)
            for name,(_,rows) in _rows(state).items()}
        result=dict(schema='scar.source-state-unit-coverage',schema_version=1,status='INVENTORIED',
            unit=unit,path=row['path'],namespace=encode(state.namespace),source_material=encode(state.material.result_artifact),
            counts=counts,instructions=dict(instructions),families=dict(families),open_effect_fields=dict(pending),
            gaps=table,gap_operations=len(gaps),binding_fixed_points_complete=False,
            graph=dict(tables=graph_tables,templates=len(source.expanded),nodes=len(source.nodes),
                relations=len(source.edge_sources),edge_projections=projections),state_tables=state_tables,
            original_body_bytes_copied=0,loops_unrolled=False,
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
    source=read_source_catalog(catalog);all_units=set(source.fact_store.rows)
    selected=all_units if not units else set(units)
    if not selected<=all_units:raise ValueError('coverage unit is outside the original catalog')
    ordered=sorted(selected,key=lambda u:(-source.fact_store.rows[u]['counts']['ports'],u))
    _durable_mkdir(out);parent=_artifact(source.path/'result.json',source.report['schema'])
    plan=dict(schema='scar.source-state-coverage-plan',schema_version=1,catalog=str(source.path),parent=encode(parent),
        scope='CATALOG' if not units else 'EXPLICIT_ORIGINAL_UNITS',catalog_units=len(all_units),
        selected_units=ordered,entry_sources=source.report.get('entry_sources'),pins=pins,
        catalog_schema=source.report['schema'],local_graph_shards=True,
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
    index_inventory(out)
    return report


def _inventory_index(path):
    """Authenticate completed shards without rebuilding any original graph.

    This also seals inventories made before the shard index was introduced.
    Their original plan, producer pins and result bytes remain untouched.
    """
    path=Path(path).absolute();raw=(path/'result.json').read_bytes();report=json.loads(raw)
    if (report['schema'],report['schema_version'])!=('scar.source-state-coverage',1):
        raise ValueError('unsupported coverage inventory')
    plan=json.loads((path/'plan.json').read_bytes())
    if plan!=report['plan'] or len(set(plan['selected_units']))!=len(plan['selected_units']):
        raise ValueError('inventory plan or original unit domain differs')
    actual={};counts=Counter();gaps=Counter();instructions=Counter();families=Counter()
    failures=[];peaks={};stored=0
    for unit in plan['selected_units']:
        folder=path/'units'/unit;data=(folder/'result.json').read_bytes();row=json.loads(data)
        if (row['unit']!=unit or row['schema']!='scar.source-state-unit-coverage'
                or row['schema_version']!=1 or row['target_executed'] is not False
                or row['first_stage_complete'] is not False):
            raise ValueError('inventory shard identity or scope differs')
        actual[unit]=encode(_artifact(folder/'result.json',row['schema']));stored+=len(data)
        pid=str(row['worker_pid']);peaks[pid]=max(peaks.get(pid,0),row['worker_peak_rss_kib'])
        if row['status']=='FAILED':
            failures.append(dict(unit=unit,error_type=row['error_type'],error=row['error']));continue
        if row['status']!='INVENTORIED' or row['binding_fixed_points_complete'] is not False:
            raise ValueError('inventory shard claims an unperformed analysis')
        table=row['gaps']
        if table['path']!='gaps.jsonl.gz':raise ValueError('inventory gap table path differs')
        payload=(folder/table['path']).read_bytes();stored+=len(payload)
        if (len(payload)!=table['bytes'] or sha256(payload).hexdigest()!=table['sha256']
                or table['records']!=row['gap_operations']
                or table['records']!=sum(row['counts']['missing_address_rules'].values())):
            raise ValueError('inventory gap receipt/count differs')
        if plan.get('local_graph_shards'):
            graph=row['graph']
            if (set(graph['tables'])!={'nodes','edges'} or row['loops_unrolled']is not False
                    or row['original_body_bytes_copied']!=0
                    or graph['templates']!=row['counts']['templates']
                    or graph['nodes']!=graph['tables']['nodes']['records']
                    or graph['edge_projections']!=graph['tables']['edges']['records']):
                raise ValueError('inventory local graph coverage or storage domain differs')
            for subfolder,tables in (('graph',graph['tables']),('state',row['state_tables'])):
                for name,receipt in tables.items():
                    if receipt['path']!=name+'.jsonl.gz':raise ValueError('inventory table path differs')
                    payload=(folder/subfolder/receipt['path']).read_bytes();stored+=len(payload)
                    if len(payload)!=receipt['bytes'] or sha256(payload).hexdigest()!=receipt['sha256']:
                        raise ValueError('inventory local graph/state table receipt differs')
        counts.update({k:v for k,v in row['counts'].items() if type(v)is int})
        gaps.update(row['counts']['missing_address_rules']);instructions.update(row['instructions']);families.update(row['families'])
    if (report['completed_units']!=len(actual) or report['inventoried_units']!=len(actual)-len(failures)
            or report['counts']!=dict(counts) or report['missing_address_rules']!=dict(gaps)
            or report['instructions']!=dict(instructions) or report['families']!=dict(families)
            or sorted(report['failures'],key=lambda r:r['unit'])!=sorted(failures,key=lambda r:r['unit'])
            or report['status']!=('INCOMPLETE_INVENTORY' if failures else 'COMPLETE_INVENTORY')):
        raise ValueError('inventory aggregate differs from its unit shards')
    if raw!=(path/'result.json').read_bytes():raise ValueError('inventory changed while indexing')
    result=dict(schema='scar.source-state-coverage-index',schema_version=1,
        inventory=encode(_artifact(path/'result.json',report['schema'])),
        plan=encode(_artifact(path/'plan.json',plan['schema'])),units=actual,
        stored_shard_bytes=stored,worker_peak_rss_kib=peaks,
        catalog_local_graph_materialized=bool(plan.get('local_graph_shards') and not failures
            and plan['scope']=='CATALOG' and len(actual)==plan['catalog_units']),
        producer_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        semantic_rederivation=False,target_executed=False,first_stage_complete=False)
    return result


def index_inventory(path):
    """Seal all finished graph/state shards without repeating their analysis."""
    result=_inventory_index(path)
    _durable_bytes(Path(path)/'index.json',_json(result),replace=False)
    return result


def read_inventory(path,*,catalog=None):
    """Admit the complete stored unit domain and receipts, not a graph walk."""
    path=Path(path).resolve();raw=(path/'index.json').read_bytes();actual=json.loads(raw)
    expected=_inventory_index(path)
    if actual!=expected:raise ValueError('stored inventory index differs from its original shards')
    plan=json.loads((path/'plan.json').read_bytes())
    if plan['pins']!=_pins():raise ValueError('inventory implementation changed')
    source=read_source_catalog(catalog if catalog is not None else plan['catalog'])
    if (str(source.path)!=plan['catalog']
            or encode(_artifact(source.path/'result.json',source.report['schema']))!=plan['parent']
            or plan['scope']=='CATALOG' and set(plan['selected_units'])!=set(source.fact_store.rows)):
        raise ValueError('inventory original catalog unit denominator differs')
    if raw!=(path/'index.json').read_bytes():raise ValueError('inventory index changed during read')
    return actual


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog');parser.add_argument('--out');parser.add_argument('--index')
    parser.add_argument('--unit',action='append',default=[]);parser.add_argument('--jobs',type=int,default=16)
    parser.add_argument('--memory-mib',type=int,default=8192)
    args=parser.parse_args()
    if args.index:
        if args.catalog or args.out or args.unit:parser.error('--index stands alone')
        report=index_inventory(args.index)
        print(json.dumps(dict(status='INVENTORY_SHARDS_INDEXED',units=len(report['units']),stored_shard_bytes=report['stored_shard_bytes'])))
        return
    if not args.catalog or not args.out:parser.error('--catalog and --out are required')
    report=inventory(args.catalog,args.out,units=args.unit,jobs=args.jobs,memory_mib=args.memory_mib)
    print(json.dumps({key:report[key] for key in ('status','completed_units','inventoried_units','missing_address_rules','seconds')}))


if __name__=='__main__':main()
