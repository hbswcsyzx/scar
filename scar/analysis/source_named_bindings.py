"""Join complete declared namespace paths to generated binding declarations.

All overloads remain conditional. A spelling match does not prove the current
namespace export, parser acceptance, override selection or native execution.
Original source operands remain dependencies, never aliases to native values.
"""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
import json
import multiprocessing
from pathlib import Path
import time

from scar.analysis.source_declared_calls import DeclaredCallStore
from scar.analysis.source_native_binding_materials import read_binding_materials
from scar.analysis.python_bindings import _symbols
from scar.analysis.source_reference_slice import ReferenceSlicer, source_port
from scar.analysis.source_value_flow import _artifact
from scar.analysis.source_world_returns import _table_ref
from scar.analysis.source_symbol_variants import _table
from scar.analysis.normal_output import write_table
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_template_links import _json
from scar.ir.program import python_bindings as B, source_named_bindings as N, source_productions as P
from scar.ir.record_codec import decode, encode


SCHEMA='scar.source-named-binding-interfaces'
_WORKER=None


def match_unit(store, unit_id, declarations, binding_root, binding_report):
    graph=store.load_unit(unit_id); slicer=ReferenceSlicer(store.snapshot)
    unit=store.snapshot.fact_store.load(unit_id); symbols=_symbols(declarations)
    ids={definition.id:i for i,definition in enumerate(declarations)}
    matches=[]; frontiers=[]
    shard=store.report['shards'][unit_id]
    root=store.path/shard['path']
    for ordinal,request in enumerate(graph.symbols):
        evidence=_table_ref(root,shard['tables']['symbols'],'scar.declared-call-symbol-requests',ordinal)
        query=graph.queries[request.query]; call=unit.calls[request.query]
        if query.call!=slicer.fact(unit,'calls',request.query) or query.callee!=source_port(unit,call.callee):
            raise ValueError('named binding source call differs from its original ABI')
        symbol='.'.join((request.returned_module,*(selector.member for selector in request.selectors)))
        definitions=symbols.get(symbol,())
        if not definitions:
            frontiers.append(N.NamedBindingFrontier(evidence,symbol,'NO_GENERATED_BINDING_DECLARATION_FOR_EXACT_SYMBOL'))
        for definition in definitions:
            site=B.SourceCallSite(source_port(unit,call.callee),tuple(source_port(unit,p) for p in call.positional),
                tuple((name,source_port(unit,p)) for name,p in call.keywords),source_port(unit,call.result),
                source_port(unit,call.world),source_port(unit,call.result_world),
                None if call.positional_pack is None else source_port(unit,call.positional_pack),
                None if call.keyword_pack is None else source_port(unit,call.keyword_pack))
            mode=B.ReceiverMode.UNBOUND if definition.kind is B.BindingKind.METHOD else B.ReceiverMode.FUNCTION
            receiver=site.positional[0] if mode is B.ReceiverMode.UNBOUND and site.positional else None
            # The request also stores epistemic labels (e.g. branch not yet
            # selected). Keep those on its evidence record, not in a runtime
            # guard conjunction that asks for this binding to be selected.
            guards=tuple(dict.fromkeys(('STANDARD_IMPORT_RETURN_AND_RECORDED_ATTRIBUTE_PATH_SELECTED',*definition.conditions,
                'SOURCE_SCOPE_AND_RECORDED_NAMESPACE_REFERENCE_PATH_SELECTED',
                'CURRENT_NAMESPACE_EXPORT_SELECTS_RECORDED_GENERATED_BINDING',
                'PARSER_SIGNATURE_ACCEPTS_ACTUAL_ARGUMENTS',
                'NO_TORCH_FUNCTION_OVERRIDE_OR_MODE','NO_TORCH_DISPATCH_OVERRIDE_OR_MODE',
                'STANDARD_TENSOR_DESCRIPTOR_ADMISSION','NORMAL_NATIVE_WRAPPER_RETURN',
                'PARSER_VARIANT:'+str(definition.parser_index),'BINDING_BRANCH:'+str(definition.branch_condition),
                'DECLARATION_MATCH_NOT_RUNTIME_DISPATCH_OR_NATIVE_SCHEMA_PROOF')))
            candidate=B.NativeCallCandidate(site,definition.id,guards,False,receiver,mode)
            declaration=_table_ref(binding_root,binding_report['definitions'],
                'scar.generated-python-binding-definitions',ids[definition.id])
            matches.append(N.NamedBindingMatch(evidence,query.call,declaration,symbol,candidate))
    return tuple(matches),tuple(frontiers)


def _pins():
    from scar.analysis import python_bindings, source_declared_calls
    return {name:sha256(Path(path).read_bytes()).hexdigest() for name,path in (
        ('producer',__file__),('types',N.__file__),('binding_types',B.__file__),
        ('symbols',python_bindings.__file__),('source_queries',source_declared_calls.__file__))}


def _write_unit(store, unit, declarations, binding_root, binding_report, out):
    started=time.monotonic()
    matches,frontiers=match_unit(store,unit,declarations,binding_root,binding_report)
    folder=Path(out)/'units'/unit;_durable_mkdir(folder)
    tables={name:write_table(folder/(name+'.jsonl.gz'),rows) for name,rows in (
        ('matches',matches),('frontiers',frontiers))}
    counts=dict(matches=len(matches),requests_without_generated_binding=len(frontiers),
        matched_calls=len({m.call for m in matches}),matched_symbol_units=len({m.symbol for m in matches}))
    store.runtime.clear()
    return dict(path='units/'+unit,tables=tables,counts=counts,seconds=time.monotonic()-started)


def _initialize_worker(calls, bindings, out, parents, pins):
    global _WORKER
    store=DeclaredCallStore(calls);binding_root=Path(bindings)
    report,declarations=read_binding_materials(binding_root)
    actual=[encode(_artifact(store.path/'result.json',store.report['schema'])),
        encode(_artifact(binding_root/'result.json',report['schema']))]
    if actual!=parents or pins!=_pins():raise ValueError('named binding worker inputs or rules differ')
    _WORKER=store,declarations,binding_root,report,out


def _worker(unit):
    store,declarations,binding_root,report,out=_WORKER
    return unit,_write_unit(store,unit,declarations,binding_root,report,out)


def build_named_bindings(calls, bindings, out, *, jobs=4):
    started=time.monotonic(); pins=_pins();out=Path(out).absolute()
    if out.exists():raise ValueError('fresh named binding output required')
    if type(jobs) is not int or jobs<1:raise ValueError('positive named binding worker count required')
    store=DeclaredCallStore(calls);binding_root=Path(bindings).absolute()
    binding_report,declarations=read_binding_materials(binding_root)
    parent=_artifact(store.path/'result.json',store.report['schema'])
    binding_parent=_artifact(binding_root/'result.json',binding_report['schema'])
    _durable_mkdir(out);shards={};totals=Counter()
    units=tuple(store.report['shards'])
    if jobs==1:
        for unit in units:shards[unit]=_write_unit(store,unit,declarations,binding_root,binding_report,out)
    else:
        with ProcessPoolExecutor(max_workers=min(jobs,len(units)),mp_context=multiprocessing.get_context('spawn'),
                initializer=_initialize_worker,initargs=(str(store.path),str(binding_root),str(out),
                    [encode(parent),encode(binding_parent)],pins)) as pool:
            for unit,shard in pool.map(_worker,units,chunksize=1):shards[unit]=shard
    for shard in shards.values():totals.update(shard['counts'])
    if pins!=_pins():raise ValueError('named binding source or matching rules changed')
    if parent!=_artifact(store.path/'result.json',store.report['schema']):raise ValueError('declared source graph changed')
    if binding_parent!=_artifact(binding_root/'result.json',binding_report['schema']):raise ValueError('generated binding graph changed')
    store.snapshot.validate_parents()
    tables={unit+'/'+name:dict(receipt,path=shard['path']+'/'+receipt['path'])
        for unit,shard in shards.items() for name,receipt in shard['tables'].items()}
    report=dict(schema=SCHEMA,schema_version=1,status='CONDITIONAL_FULL_NAMESPACE_BINDING_INTERFACES',
        calls=str(store.path),bindings=str(binding_root),parents=[encode(parent),encode(binding_parent)],
        pins=pins,shards=shards,tables=tables,counts=dict(totals),jobs=jobs,
        start_method='spawn' if jobs>1 else 'serial',all_declared_overloads_retained=True,
        source_relations_rederived=False,parser_acceptance_proven=False,native_schemas_connected=False,
        runtime_dispatch_proven=False,target_executed=False,first_stage_complete=False,seconds=time.monotonic()-started)
    _durable_bytes(out/'result.json',_json(report),replace=False);return report


def read_named_bindings(path, unit):
    path=Path(path).absolute();raw=(path/'result.json').read_bytes();report=json.loads(raw)
    if (report['schema'],report['schema_version'])!=(SCHEMA,1) or report['pins']!=_pins():
        raise ValueError('named binding producer differs')
    store=DeclaredCallStore(report['calls']);binding_root=Path(report['bindings'])
    binding_report,declarations=read_binding_materials(binding_root)
    parents=[encode(_artifact(store.path/'result.json',store.report['schema'])),
        encode(_artifact(binding_root/'result.json',binding_report['schema']))]
    if parents!=report['parents']:raise ValueError('named binding source or generated declarations changed')
    if set(report['shards'])!=set(store.report['shards']) or any(
            item['path']!='units/'+identity for identity,item in report['shards'].items()):
        raise ValueError('named binding source unit coverage or shard paths differ')
    shard=report['shards'][unit];folder=path/shard['path']
    matches=tuple(decode(N.NamedBindingMatch,row,record_tags=P.PRODUCTION_RECORD_TAGS) for row in _table(folder,shard['tables']['matches']))
    frontiers=tuple(decode(N.NamedBindingFrontier,row) for row in _table(folder,shard['tables']['frontiers']))
    if (matches,frontiers)!=match_unit(store,unit,declarations,binding_root,binding_report):
        raise ValueError('named binding original source operands or declaration paths differ')
    counts=dict(matches=len(matches),requests_without_generated_binding=len(frontiers),
        matched_calls=len({m.call for m in matches}),matched_symbol_units=len({m.symbol for m in matches}))
    flat={identity+'/'+name:dict(receipt,path=item['path']+'/'+receipt['path'])
        for identity,item in report['shards'].items() for name,receipt in item['tables'].items()}
    totals=Counter()
    for item in report['shards'].values():totals.update(item['counts'])
    if counts!=shard['counts'] or dict(totals)!=report['counts'] or flat!=report['tables']:
        raise ValueError('named binding shard counts or table directory differs')
    if report['all_declared_overloads_retained'] is not True or any(report[k] is not False for k in (
            'source_relations_rederived','parser_acceptance_proven','native_schemas_connected',
            'runtime_dispatch_proven','target_executed','first_stage_complete')):
        raise ValueError('named declaration matches cannot grant runtime or parser authority')
    if raw!=(path/'result.json').read_bytes():raise ValueError('named binding graph changed')
    return report,matches,frontiers


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--calls');parser.add_argument('--bindings');parser.add_argument('--out')
    parser.add_argument('--read');parser.add_argument('--unit');parser.add_argument('--jobs',type=int,default=4)
    args=parser.parse_args()
    if args.read:
        if not args.unit:parser.error('--unit required for per-unit read')
        report,_,_=read_named_bindings(args.read,args.unit)
    else:
        if not args.calls or not args.bindings or not args.out:parser.error('--calls, --bindings, --out required')
        report=build_named_bindings(args.calls,args.bindings,args.out,jobs=args.jobs)
    print(json.dumps(dict(status=report['status'],counts=report['counts'],seconds=report['seconds'])),flush=True)


if __name__=='__main__':main()
