"""Conditional function interfaces for explicitly selected compiled exec units.

Reuse retained source facts, namespace rules and the signature binder. Compiled
globals remain exec-context dictionaries, never importable module providers.
No target, global entry solver, scope activation or dispatch selection runs.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
import time

from scar.analysis import source_declared_calls as declared
from scar.analysis import source_function_interfaces as functions
from scar.analysis.source_field_interfaces import _InterfaceOnly
from scar.analysis.source_function_connections import Invocation, connect
from scar.analysis.source_graph_material import CompiledGraphMaterial
from scar.analysis.source_reference_slice import source_port
from scar.analysis.source_symbol_variants import _table
from scar.analysis.source_value_flow import _artifact
from scar.analysis.source_world_returns import _table_ref
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_template_links import _json
from scar.analysis.normal_output import write_table
from scar.ir.program import source_declared_calls as D, source_function_interfaces as R
from scar.ir.program import source_namespace_references as N, source_productions as P, normal_targets as T
from scar.ir.record_codec import decode, encode


SCHEMA = 'scar.source-compiled-function-interfaces'
UNIT_SCHEMA = SCHEMA+'-unit'
SCOPE = 'COMPILED_EXEC_CONTEXT'
TABLES = ('declared_queries', 'symbols', 'queries', 'interfaces', 'frontiers')
NO_PROOF = ('source_scopes_activated', 'caller_contexts_selected', 'runtime_dispatch_proven',
    'current_exec_globals_proven', 'current_function_environment_versions_proven',
    'historical_target_relations_rederived', 'effects_proven', 'source_bodies_copied',
    'loops_unrolled', 'target_executed', 'first_stage_complete')


def _pins():
    from scar.analysis import source_graph_material, source_world_material, source_relation_selection
    return dict(producer=sha256(Path(__file__).read_bytes()).hexdigest(),
        declaration_rules=declared._pins(), signature_rules=functions._pins(), **{
            name:sha256(Path(module.__file__).read_bytes()).hexdigest() for name,module in (
                ('compiled_material',source_graph_material),('material_parents',source_world_material),
                ('material_selection',source_relation_selection))})


def _selected(catalog, units):
    if isinstance(units,str):units=(units,)
    units=tuple(units or ())
    if not units or any(type(u) is not str or u not in catalog.fact_store.original_source_units
            or catalog.fact_store.rows[u].get('facts_format')!='COMPILE_CONTEXT_F4_JSONL' for u in units):
        raise ValueError('explicit original compiled exec-context unit identities required')
    return tuple(sorted(set(units)))


def _declarations(runtime, unit, limits):
    """Same per-call rules as ordinary declarations; selection is explicit exec."""
    _selected(runtime.catalog,(unit,))
    facts=runtime.catalog.fact_store.load(unit);owners=declared._owners(facts);queries=[]
    resolver=runtime.resolver
    for i,call in enumerate(facts.calls):
        callee=source_port(facts,call.callee);reference=resolver.resolve(callee,**limits)
        formal,results=declared._cuts(resolver,reference)
        queries.append(D.DeclaredCallQuery(unit,resolver.slicer.fact(facts,'calls',i),callee,
            owners[i],reference,formal,results))
    queries=tuple(queries);runtime.snapshot.validate_parents()
    return D.DeclaredCallUnit(unit,queries,declared._symbols(resolver,queries))


def _interfaces(runtime, graph, folder, receipt):
    """Bind every function origin; keep complete namespace alternatives separate."""
    unit=graph.unit;facts=runtime.catalog.fact_store.load(unit);slicer=runtime.resolver.slicer
    offset=slicer.store.offsets[unit];interfaces=[];frontiers=[];queries=[];origins=0;cache={}
    for qi,query in enumerate(graph.queries):
        evidence=_table_ref(folder,receipt,'scar.compiled-declared-source-call-query',qi)
        call=facts.calls[qi];reference=query.reference
        invocation=Invocation(offset+call.callee,tuple(offset+p for p in call.positional),
            tuple((name,offset+p) for name,p in call.keywords),offset+call.result,
            offset+call.world,offset+call.result_world,
            None if call.positional_pack is None else offset+call.positional_pack,
            None if call.keyword_pack is None else offset+call.keyword_pack)
        origin_indices=[];interface_indices=[]
        for oi,origin in enumerate(reference.origins):
            if origin.kind is not N.NamespaceOriginKind.FUNCTION_DEFINITION:continue
            origins+=1;origin_indices.append(oi);terminal=reference.states[origin.state]
            if terminal.selectors:raise ValueError('compiled function origin retains pending selectors')
            provider,local=slicer.local(terminal.port)
            matches=[(i,fn) for i,fn in enumerate(provider.functions) if fn.value==local]
            if len(matches)!=1:raise ValueError('compiled callee origin lacks one original function fact')
            fi,fn=matches[0];definition=slicer.fact(provider,'functions',fi)
            if origin.evidence!=(definition,):raise ValueError('compiled function origin evidence differs')
            if terminal.port not in cache:cache[terminal.port]=_InterfaceOnly(slicer,provider,fn)
            mini=cache[terminal.port]
            connection=connect(mini,mini.offsets[provider.unit]+fn.value,invocation,conditions=(
                'RECORDED_SOURCE_CALLEE_REFERENCE_PATH_AND_ITS_PRECONDITIONS_SELECTED',
                'CURRENT_CALLABLE_IS_RECORDED_SOURCE_FUNCTION_WITH_COMPATIBLE_CALL_PROTOCOL',
                'FUNCTION_CODE_CAPTURE_DEFAULT_AND_NAMESPACE_VERSIONS_MATCH_DECLARATION',
                'CURRENT_FRAME_GLOBALS_SELECT_RECORDED_COMPILE_CONTEXT_DICT',
                'COMPILED_EXEC_CONTEXT_DECLARATION_DOES_NOT_ESTABLISH_SCOPE_ENTRY',*origin.conditions))
            if connection is None:
                frontiers.append(R.SourceFunctionInterfaceFrontier(qi,oi,evidence,
                    'SOURCE_SIGNATURE_REQUIRES_DIFFERENT_ARGUMENT_OR_DESCRIPTOR_BINDING'));continue
            mode='SOURCE_FUNCTION' if connection.activation is T.FunctionActivation.NORMAL else 'CREATE_DEFERRED_BODY'
            link=T.CallLink(source_port(facts,call.result),source_port(facts,call.callee),
                connection.source_callable,connection.body,mode,None,connection.parameters,
                connection.returns,connection.conditions,argument_packs=connection.argument_packs,
                projections=connection.projections,binding=connection.binding)
            interface_indices.append(len(interfaces))
            interfaces.append(R.SourceFunctionInterface(qi,oi,query.call,definition,evidence,connection.activation,link))
            if connection.activation is not T.FunctionActivation.NORMAL:
                frontiers.append(R.SourceFunctionInterfaceFrontier(qi,oi,evidence,
                    'DEFERRED_CREATION_HAS_NO_ORDINARY_BODY_DATA_OR_WORLD_RETURN'))
        if not origin_indices:
            frontiers.append(R.SourceFunctionInterfaceFrontier(qi,None,evidence,
                'NO_RECORDED_SOURCE_FUNCTION_ORIGIN_OTHER_CALLEE_ALTERNATIVES_REMAIN_OPEN'))
        if reference.frontiers:
            frontiers.append(R.SourceFunctionInterfaceFrontier(qi,None,evidence,
                'PARENT_CALLEE_REFERENCE_FRONTIERS_REMAIN_OPEN'))
        indices=tuple(range(len(reference.frontiers)))
        queries.append(R.SourceFunctionInterfaceQuery(qi,query.call,evidence,evidence,query.owners,
            tuple(origin_indices),tuple(interface_indices),indices,indices))
    runtime.snapshot.validate_parents();declared._check_targets()
    return R.SourceFunctionInterfaceUnit(unit,len(graph.queries),origins,(),
        tuple(interfaces),tuple(frontiers),tuple(queries))


def _counts(graph, declarations):
    return dict(functions._counts(graph), namespace=declared._counts(declarations))


def _totals(shards):
    result=functions._totals({u:dict(counts={k:v for k,v in s['counts'].items() if k!='namespace'})
        for u,s in shards.items()})
    result['namespace']=declared._totals({u:dict(counts=s['counts']['namespace']) for u,s in shards.items()})
    return result


def _unit_report(runtime, unit, source_templates, tables, counts, pins, limits):
    row=runtime.catalog.fact_store.rows[unit]
    return dict(schema=UNIT_SCHEMA,schema_version=1,scope=SCOPE,unit=unit,
        catalog_parent=encode(runtime.parent),source_templates=encode(source_templates),
        original_source_unit=row['original_source_unit'],source=row['path'],module=row['module'],
        limits=limits,pins=pins,tables=tables,counts=counts,
        namespace_reference_rules_rederived=True,source_signature_rules_rederived=True,
        **{name:False for name in NO_PROOF})


def build_compiled_interfaces(catalog, out, *, units, max_states=4000, max_selectors=32):
    """Publish only explicit compiled units; never widen the import provider index."""
    declared._check_targets();started=time.monotonic();out=Path(out).absolute()
    if out.exists():raise ValueError('fresh compiled function interface output required')
    limits=declared._limits(max_states,max_selectors);pins=_pins();runtime=declared._Runtime(catalog)
    selected=_selected(runtime.catalog,units);_durable_mkdir(out);shards={}
    for unit in selected:
        begin=time.monotonic();material=CompiledGraphMaterial(runtime.catalog,unit)
        declarations=_declarations(runtime,unit,limits);folder=out/declared._folder(unit);_durable_mkdir(folder)
        tables={name:write_table(folder/(name+'.jsonl.gz'),rows) for name,rows in (
            ('declared_queries',declarations.queries),('symbols',declarations.symbols))}
        graph=_interfaces(runtime,declarations,folder,tables['declared_queries'])
        tables.update({name:write_table(folder/(name+'.jsonl.gz'),getattr(graph,name))
            for name in ('queries','interfaces','frontiers')})
        counts=_counts(graph,declarations);report=_unit_report(runtime,unit,material.result_artifact,tables,counts,pins,limits)
        material.validate_parents()
        if _pins()!=pins:raise ValueError('compiled interface producer changed')
        _durable_bytes(folder/'result.json',_json(report),replace=False)
        shards[unit]=dict(path=declared._folder(unit),tables=tables,counts=counts,
            source_templates=report['source_templates'],result=encode(_artifact(folder/'result.json',UNIT_SCHEMA)),
            seconds=time.monotonic()-begin)
        runtime.clear()
    runtime.snapshot.validate_parents()
    if _pins()!=pins:raise ValueError('compiled interface producer changed')
    report=dict(schema=SCHEMA,schema_version=1,scope=SCOPE,catalog=str(runtime.catalog.path),
        catalog_parent=encode(runtime.parent),selection=dict(mode='EXPLICIT_COMPILED_UNITS',units=list(selected)),
        limits=limits,pins=pins,shards=shards,tables=declared._flat_tables(shards),counts=_totals(shards),
        denominator=dict(parent_catalog_units=len(runtime.catalog.fact_store.rows),
            parent_compiled_units=len(runtime.catalog.fact_store.original_source_units),selected_units=len(selected),
            selected_calls=sum(runtime.catalog.fact_store.rows[u]['counts']['calls'] for u in selected)),
        namespace_reference_rules_rederived=True,source_signature_rules_rederived=True,
        import_provider_index_unchanged=True,parent_query_indexes_include_unconnected_calls_and_frontiers=True,
        seconds=time.monotonic()-started,**{name:False for name in NO_PROOF})
    _durable_bytes(out/'result.json',_json(report),replace=False);return report


class CompiledFunctionInterfaceStore:
    """Native compiled schema; strict unit reads replay namespace and ABI rules."""
    def __init__(self,path,catalog=None):
        self.path=Path(path).absolute();self.raw=(self.path/'result.json').read_bytes();self.report=r=json.loads(self.raw)
        if (r['schema'],r['schema_version'],r['scope'])!=(SCHEMA,1,SCOPE) or r['pins']!=_pins():
            raise ValueError('compiled function interface schema or producer differs')
        self.runtime=declared._Runtime(r['catalog'] if catalog is None else catalog)
        self.catalog=self.runtime.catalog;self.snapshot=self.runtime.snapshot;self.materials={}
        if str(self.catalog.path)!=r['catalog'] or encode(self.runtime.parent)!=r['catalog_parent']:
            raise ValueError('compiled function interface original catalog differs')
        self.units=_selected(self.catalog,r['selection']['units']);declared._limits(**r['limits'])
        denominator=dict(parent_catalog_units=len(self.catalog.fact_store.rows),
            parent_compiled_units=len(self.catalog.fact_store.original_source_units),selected_units=len(self.units),
            selected_calls=sum(self.catalog.fact_store.rows[u]['counts']['calls'] for u in self.units))
        if (r['selection']!=dict(mode='EXPLICIT_COMPILED_UNITS',units=list(self.units))
                or tuple(r['shards'])!=self.units or r['tables']!=declared._flat_tables(r['shards'])
                or r['counts']!=_totals(r['shards']) or r['denominator']!=denominator
                or any(r[n] is not False for n in NO_PROOF)
                or any(r[n] is not True for n in ('namespace_reference_rules_rederived','source_signature_rules_rederived',
                    'import_provider_index_unchanged','parent_query_indexes_include_unconnected_calls_and_frontiers'))):
            raise ValueError('compiled interface selection, coverage or proof status differs')
        for unit,shard in r['shards'].items():
            if (shard['path']!=declared._folder(unit) or set(shard['tables'])!=set(TABLES)
                    or any(v['path']!=name+'.jsonl.gz' for name,v in shard['tables'].items())
                    or shard['counts']['calls']!=self.catalog.fact_store.rows[unit]['counts']['calls']):
                raise ValueError('compiled interface original unit or table metadata differs')
        self.validate()

    def validate(self):
        if self.raw!=(self.path/'result.json').read_bytes() or self.report['pins']!=_pins():
            raise ValueError('compiled interface report or rules changed')
        self.snapshot.validate_parents()
        for material in self.materials.values():material.validate_parents()

    def _load(self,unit):
        self.validate()
        if unit not in self.report['shards']:raise ValueError('compiled interface unit was not selected')
        shard=self.report['shards'][unit];folder=self.path/shard['path']
        if encode(_artifact(folder/'result.json',UNIT_SCHEMA))!=shard['result']:
            raise ValueError('compiled interface unit report receipt differs')
        if unit not in self.materials:self.materials[unit]=CompiledGraphMaterial(self.catalog,unit)
        material=self.materials[unit]
        expected=_unit_report(self.runtime,unit,material.result_artifact,shard['tables'],
            shard['counts'],self.report['pins'],self.report['limits'])
        raw=(folder/'result.json').read_bytes()
        if json.loads(raw)!=expected or shard['source_templates']!=encode(material.result_artifact):
            raise ValueError('compiled interface unit provenance differs')
        def rows(name,kind):
            return tuple(decode(kind,w,record_tags=P.PRODUCTION_RECORD_TAGS) for w in _table(folder,shard['tables'][name]))
        declarations=D.DeclaredCallUnit(unit,rows('declared_queries',D.DeclaredCallQuery),rows('symbols',D.DeclaredCallSymbolRequest))
        graph=R.SourceFunctionInterfaceUnit(unit,shard['counts']['calls'],shard['counts']['function_origins'],(),
            rows('interfaces',R.SourceFunctionInterface),rows('frontiers',R.SourceFunctionInterfaceFrontier),
            rows('queries',R.SourceFunctionInterfaceQuery))
        facts=self.catalog.fact_store.load(unit);owners=declared._owners(facts);slicer=self.runtime.resolver.slicer
        if _counts(graph,declarations)!=shard['counts'] or len(declarations.queries)!=len(facts.calls):
            raise ValueError('compiled interface typed counts or original call coverage differs')
        for i,(query,call) in enumerate(zip(declarations.queries,facts.calls)):
            if (query.unit!=unit or query.call!=slicer.fact(facts,'calls',i)
                    or query.callee!=source_port(facts,call.callee) or query.owners!=owners[i]
                    or not query.reference.states or query.reference.states[0].port!=query.callee
                    or query.reference.states[0].selectors):raise ValueError('compiled declaration original call ABI differs')
        if raw!=(folder/'result.json').read_bytes():raise ValueError('compiled unit report changed during reading')
        self.validate();return graph,declarations

    def load_unit(self,unit):
        """Receipts/types/counts/original call checks; namespace/connection rules not replayed."""
        return self._load(unit)[0]

    def load_declarations(self,unit):
        """Retain complete original namespace candidates and frontier reasons."""
        return self._load(unit)[1]

    def read_unit(self,unit):
        graph,recorded=self._load(unit);shard=self.report['shards'][unit];folder=self.path/shard['path']
        expected=_declarations(self.runtime,unit,self.report['limits'])
        if recorded!=expected:raise ValueError('compiled namespace references differ from original source rules')
        if graph!=_interfaces(self.runtime,expected,folder,shard['tables']['declared_queries']):
            raise ValueError('compiled function interfaces differ from original callee candidates and ABI')
        self.validate();declared._check_targets();return graph


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog');parser.add_argument('--unit',action='append',default=[])
    parser.add_argument('--out');parser.add_argument('--read');parser.add_argument('--max-states',type=int,default=4000)
    parser.add_argument('--max-selectors',type=int,default=32);args=parser.parse_args()
    sys.meta_path.insert(0,declared._NoTargets());declared._check_targets()
    if args.read:
        store=CompiledFunctionInterfaceStore(args.read,catalog=args.catalog)
        units=_selected(store.catalog,args.unit)
        result={unit:functions._counts(store.read_unit(unit)) for unit in units}
        print(json.dumps(dict(status='COMPILED_FUNCTION_INTERFACES_REDERIVED',units=result,target_executed=False)),flush=True)
    else:
        if not args.catalog or not args.out or not args.unit:parser.error('--catalog, --unit and --out are required')
        report=build_compiled_interfaces(args.catalog,args.out,units=args.unit,
            max_states=args.max_states,max_selectors=args.max_selectors)
        print(json.dumps(dict(status='COMPILED_FUNCTION_INTERFACES_BUILT',counts=report['counts'],
            seconds=report['seconds'],target_executed=False)),flush=True)


if __name__=='__main__':main()
