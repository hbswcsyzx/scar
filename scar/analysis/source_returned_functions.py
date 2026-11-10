"""One sealed-parent pass from call results to returned function interfaces.

Creator reference stacks remain provenance, separate from caller stacks.
Only retained interfaces are indexed; no historical call scan or entry solver
runs. New interfaces are published after all bounded queries have finished.
"""
import argparse
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

from scar.analysis.source_call_view import open_function_interfaces
from scar.analysis.source_function_creations import SourceFunctionCreationStore
from scar.analysis.source_stacked_references import StackedReferenceEngine
from scar.analysis.source_reference_slice import ReferenceSlicer, source_port
from scar.analysis.source_function_connections import Invocation, connect
from scar.analysis.source_field_interfaces import _InterfaceOnly
from scar.analysis.source_function_interfaces import _counts as interface_counts
from scar.analysis.source_declared_calls import _NoTargets, _check_targets, _folder, _flat_tables
from scar.analysis.source_world_returns import _table_ref
from scar.analysis.source_value_flow import _artifact
from scar.analysis.source_symbol_variants import _table
from scar.analysis.source_consumer_parents import _stamp
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_template_links import _json
from scar.analysis.normal_output import write_table
from scar.ir.program import source_returned_functions as R, source_function_interfaces as I
from scar.ir.program import normal_targets as T, source_productions as P, source_reference_slices as S
from scar.ir.program.source_call_contexts import CallInterfaceRecord
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.record_codec import encode, decode


SCHEMA='scar.source-returned-function-interfaces'
TABLES=('provenances','return_frontiers','interfaces','queries','frontiers')
NO_PROOF=('actual_callable_proven','creator_instance_proven','cell_version_proven','runtime_dispatch_proven',
    'effects_proven','namespace_semantics_rederived','historical_calls_scanned','source_bodies_copied',
    'loops_unrolled','target_executed','first_stage_complete')
GUARDS=('RECORDED_RETURNED_FUNCTION_REFERENCE_PATH_AND_PRECONDITIONS_SELECTED',
    'CURRENT_CALLABLE_SELECTS_RECORDED_CREATION_IN_SELECTED_CREATOR_CONTEXT',
    'CALLER_OUTER_AND_CREATOR_REFERENCE_CONTEXT_ARE_SEPARATE',
    'CURRENT_FUNCTION_ENVIRONMENT_DEFAULT_AND_CELL_VERSIONS_NOT_PROVEN')


class _SealedEngine(StackedReferenceEngine):
    def __init__(self,snapshot,reader):
        super().__init__(snapshot);self.reader=reader

    def index(self,units):
        # Index sealed source declarations, never historical snapshot.calls.
        # Returned/creator-qualified alternatives are not general candidates.
        # In particular, do not widen an already contextual incoming seed.
        for unit in sorted(set(units)-self.indexed):
            self.indexed.add(unit)
            if unit not in self.reader.report['shards']:continue
            graph=self.reader.load_unit(unit)
            provenance=getattr(self.reader,'callable_provenance',None)
            for i,interface in enumerate(graph.interfaces):
                evidence=_interface_fact(self.reader,unit,i)
                if evidence in self.ids:continue
                if callable(provenance) and provenance(unit,i) is not None:continue
                self.admit(evidence,interface.link)


def _pins():
    from scar.analysis import source_call_contexts,source_stacked_references,source_reference_slice
    from scar.analysis import source_function_connections,source_field_interfaces,source_function_creations
    from scar.ir.program import source_call_contexts as C,source_function_creations as F
    return dict(producer=sha256(Path(__file__).read_bytes()).hexdigest(),**{
        name:sha256(Path(module.__file__).read_bytes()).hexdigest() for name,module in (
            ('types',R),('interface_types',I),('targets',T),('production_types',P),('reference_types',S),
            ('context_types',C),('creation_types',F),('context_rules',source_call_contexts),
            ('stacked_rules',source_stacked_references),('reference_rules',source_reference_slice),
            ('binder',source_function_connections),('adapter',source_field_interfaces),('creation_rules',source_function_creations))})


def _parent(path):
    if isinstance(path,(str,Path)) and json.loads((Path(path)/'result.json').read_bytes())['schema']==SCHEMA:
        return ReturnedFunctionInterfaceStore(path)
    return open_function_interfaces(path)


def _interface_fact(parent,unit,i):
    if callable(getattr(parent,'interface_fact',None)):return parent.interface_fact(unit,i)
    shard=parent.report['shards'][unit]
    return _table_ref(parent.path/shard['path'],shard['tables']['interfaces'],'scar.source-function-interface-record',i)


def _declarations(parent,unit):
    method=getattr(parent,'load_declarations',None)
    return method(unit) if callable(method) else parent.parents.calls.load_unit(unit)


def _limits(max_states,max_depth):
    if any(type(v) is not int or v<1 for v in (max_states,max_depth)):raise ValueError('positive returned-reference bounds required')
    return dict(max_states=max_states,max_depth=max_depth)


def _selected(parent,units):
    if isinstance(units,str):units=(units,)
    result=tuple(sorted(set(units or parent.report['shards'])))
    if not result or any(u not in parent.report['shards'] for u in result):raise ValueError('selected unit is absent from sealed parent')
    return result


class _Parents:
    def __init__(self,parent,creations,catalog=None):
        self.parent=_parent(parent);self.catalog=self.parent.catalog
        if catalog is not None and (catalog.path,catalog.report)!=(self.catalog.path,self.catalog.report):
            raise ValueError('returned interfaces need the exact original catalog')
        self.creations=SourceFunctionCreationStore(creations,catalog=self.catalog);self.creation_units={}
        self.snapshot=SimpleNamespace(fact_store=self.catalog.fact_store,validate_parents=self.validate)
        self.slicer=ReferenceSlicer(self.snapshot)

    def validate(self):self.parent.validate();self.creations.validate()

    def creation(self,point):
        if point.unit not in self.creation_units:
            if point.unit not in self.creations.report['shards']:return None
            self.creation_units[point.unit]=self.creations.read_unit(point.unit)
        matches=[c for c in self.creation_units[point.unit].creations if c.function==point]
        if len(matches)>1:raise ValueError('returned function has multiple original factory records')
        return matches[0] if matches else None

    def collect(self,unit,graph,limits):
        declarations=_declarations(self.parent,unit);provenances=[];frontiers=[]
        getter=getattr(self.parent,'callable_provenance',None)
        inherited=tuple(p for i in range(len(graph.interfaces))
            if callable(getter) and (p:=getter(unit,i)) is not None)
        if len(declarations.queries)!=graph.calls or tuple(q.query for q in graph.queries)!=tuple(range(graph.calls)):
            raise ValueError('returned consumer queries differ from original call denominator')
        for qi,query in enumerate(declarations.queries):
            for cut in query.call_result_frontiers:
                point=query.reference.states[cut].port;matched=False;declared=graph.queries[qi].declared
                def frontier(reason,seed=None,source=None,reference=None):
                    frontiers.append(R.ReturnedCallableFrontier(qi,cut,declared,seed,source,reference,reason))
                for si,seed in enumerate(graph.interfaces):
                    if seed.link.result!=point:continue
                    matched=True;base=tuple(sorted(set(query.owners)&set(graph.queries[seed.query].owners),key=lambda x:(x.unit,x.ordinal)))
                    record=CallInterfaceRecord(_interface_fact(self.parent,unit,si),seed.link)
                    if not base:frontier('RETURN_SEED_AND_CONSUMER_CODE_SCOPES_DO_NOT_MATCH',record);continue
                    if seed.activation is not T.FunctionActivation.NORMAL:
                        frontier('DEFERRED_CREATION_IS_NOT_ORDINARY_BODY_RETURN',record);continue
                    sources=[a for a,b in seed.link.returns if b==seed.link.result]
                    if not sources:frontier('SEALED_INTERFACE_HAS_NO_NORMAL_DATA_RETURN',record);continue
                    for source in sources:
                        if type(source) is not T.GlobalPort:frontier('RETURN_REQUIRES_CONSTRUCTOR_PROTOCOL',record);continue
                        engine=_SealedEngine(self.snapshot,self.parent);incoming=engine.admit_contextual(record.evidence,record.link,())
                        reference,=engine.solve_stacks(((incoming,source,()),),**limits)
                        if reference.frontiers:frontier('BOUNDED_REFERENCE_FRONTIERS_REMAIN_OPEN',record,source,reference)
                        origins=[(oi,o) for oi,o in enumerate(reference.origins) if o.kind is S.ReferenceOriginKind.FUNCTION_DEFINITION]
                        if not origins:frontier('NO_RETURNED_FUNCTION_ORIGIN_IN_SEALED_REFERENCE_PASS',record,source,reference)
                        for oi,origin in origins:
                            state=reference.states[origin.state];creation=self.creation(state.port)
                            if creation is None:frontier('RETURNED_FUNCTION_FACTORY_NOT_RETAINED',record,source,reference);continue
                            provider,local=engine.slicer.local(state.port);fns=[f for f in provider.functions if f.value==local]
                            if (len(fns)!=1 or creation.function_fact!=origin.evidence[0]
                                    or creation.body!=T.Body(provider.unit,fns[0].template,fns[0].body)
                                    or creation.environment!=fns[0].environment):raise ValueError('returned origin/factory/function ABI differs')
                            creators=tuple(engine.interfaces[j] for j in state.interfaces)
                            owner=None
                            if creators:
                                top=creators[-1].link;owner_unit,owner_local=engine.slicer.local(top.source_callable)
                                owner_fn=next(f for f in owner_unit.functions if f.value==owner_local)
                                owner=owner_fn.body_scope.owner
                            if (creators and owner!=creation.creator.owner) or (not creators and creation.creator.owner not in base):
                                frontier('RETURNED_CREATOR_CODE_SCOPE_OR_CONTEXT_NOT_SELECTED',record,source,reference);continue
                            provenance=R.ReturnedCallableProvenance(qi,cut,declared,record,source,reference,oi,
                                creation,creators,base,(*GUARDS,*record.link.conditions,*origin.conditions,*creation.conditions))
                            # Reusing a sealed pass must not append the exact
                            # same derivation again. Different creators, paths,
                            # guards or consumers remain separate alternatives.
                            if provenance not in inherited and provenance not in provenances:
                                provenances.append(provenance)
                if not matched:frontier('CALL_RESULT_HAS_NO_SEALED_PARENT_INTERFACE')
        self.validate();return tuple(provenances),tuple(frontiers)

    def overlay(self,unit,parent,provenances,return_frontiers,folder,receipt):
        caller=self.catalog.fact_store.load(unit);offset=self.catalog.fact_store.offsets[unit]
        interfaces=list(parent.interfaces);frontiers=list(parent.frontiers);queries=list(parent.queries)
        for p in return_frontiers:frontiers.append(I.SourceFunctionInterfaceFrontier(p.query,None,p.declared,p.reason))
        for pi,p in enumerate(provenances):
            if (not 0<=p.query<parent.calls or p.declared!=parent.queries[p.query].declared
                    or not 0<=p.origin<len(p.reference.origins)):
                raise ValueError('returned provenance consumer or origin ordinal differs')
            origin=p.reference.origins[p.origin]
            if (origin.kind is not S.ReferenceOriginKind.FUNCTION_DEFINITION
                    or not 0<=origin.state<len(p.reference.states)
                    or p.reference.states[origin.state].port!=p.creation.function
                    or origin.evidence!=(p.creation.function_fact,)):
                raise ValueError('returned provenance origin differs from original factory fact')
            evidence=_table_ref(folder,receipt,'scar.returned-callable-provenance',pi)
            call=caller.calls[p.query];unit_fn,local=self.slicer.local(p.creation.function)
            fn=next(f for f in unit_fn.functions if f.value==local);mini=_InterfaceOnly(self.slicer,unit_fn,fn)
            invocation=Invocation(offset+call.callee,tuple(offset+x for x in call.positional),
                tuple((n,offset+x) for n,x in call.keywords),offset+call.result,offset+call.world,offset+call.result_world,
                None if call.positional_pack is None else offset+call.positional_pack,
                None if call.keyword_pack is None else offset+call.keyword_pack)
            connection=connect(mini,mini.offsets[unit_fn.unit]+fn.value,invocation,conditions=p.conditions)
            if connection is None:
                frontiers.append(I.SourceFunctionInterfaceFrontier(p.query,p.origin,evidence,'RETURNED_FUNCTION_SIGNATURE_NOT_ACCEPTED'));continue
            mode='SOURCE_FUNCTION' if connection.activation is T.FunctionActivation.NORMAL else 'CREATE_DEFERRED_BODY'
            link=T.CallLink(source_port(caller,call.result),source_port(caller,call.callee),connection.source_callable,
                connection.body,mode,None,connection.parameters,connection.returns,connection.conditions,
                argument_packs=connection.argument_packs,projections=connection.projections,binding=connection.binding)
            qi=p.query;query=queries[qi]
            queries[qi]=replace(query,interfaces=(*query.interfaces,len(interfaces)))
            interfaces.append(I.SourceFunctionInterface(qi,p.origin,query.call,p.creation.function_fact,evidence,connection.activation,link))
            if connection.activation is not T.FunctionActivation.NORMAL:
                frontiers.append(I.SourceFunctionInterfaceFrontier(qi,p.origin,evidence,'DEFERRED_CREATION_HAS_NO_ORDINARY_BODY_DATA_OR_WORLD_RETURN'))
        self.validate()
        return replace(parent,interfaces=tuple(interfaces),queries=tuple(queries),frontiers=tuple(frontiers))


def _counts(graph,parent_count,provenances,frontiers):
    return dict(calls=graph.calls,interfaces=len(graph.interfaces),parent_interfaces=parent_count,
        derived_interfaces=len(graph.interfaces)-parent_count,parent_function_origins=graph.function_origins,
        derived_function_origins=len(provenances),return_frontiers=len(frontiers),frontiers=len(graph.frontiers),
        interface_counts=interface_counts(graph))


def _totals(shards):
    return dict(units=len(shards),**{k:sum(s['counts'][k] for s in shards.values()) for k in (
        'calls','interfaces','parent_interfaces','derived_interfaces','parent_function_origins',
        'derived_function_origins','return_frontiers','frontiers')})


def build_returned_interfaces(parent_path,creations_path,out,units=(),max_states=256,max_depth=8):
    parents=_Parents(parent_path,creations_path);limits=_limits(max_states,max_depth);pins=_pins()
    out=Path(out).absolute()
    if out.exists():raise ValueError('fresh returned-interface output required')
    selected=_selected(parents.parent,units);_durable_mkdir(out);shards={}
    for unit in selected:
        graph=parents.parent.load_unit(unit);ps,fs=parents.collect(unit,graph,limits)
        folder=out/_folder(unit);_durable_mkdir(folder)
        tables={'provenances':write_table(folder/'provenances.jsonl.gz',ps),
            'return_frontiers':write_table(folder/'return_frontiers.jsonl.gz',fs)}
        output=parents.overlay(unit,graph,ps,fs,folder,tables['provenances'])
        tables.update({n:write_table(folder/(n+'.jsonl.gz'),getattr(output,n)) for n in ('interfaces','queries','frontiers')})
        shards[unit]=dict(path=_folder(unit),tables=tables,counts=_counts(output,len(graph.interfaces),ps,fs),
            controlled_queries=list(output.controlled_queries))
    parents.validate()
    if pins!=_pins():raise ValueError('returned-interface producer changed')
    report=dict(schema=SCHEMA,schema_version=1,parent_path=str(parents.parent.path),creations_path=str(parents.creations.path),
        parent=encode(_artifact(parents.parent.path/'result.json',parents.parent.report['schema'])),
        creations=encode(_artifact(parents.creations.path/'result.json',parents.creations.report['schema'])),
        catalog=str(parents.catalog.path),catalog_parent=encode(_artifact(parents.catalog.path/'result.json',parents.catalog.report['schema'])),
        pins=pins,limits=limits,selection=list(selected),shards=shards,tables=_flat_tables(shards),counts=_totals(shards),
        sealed_parent_single_pass=True,creator_context_separate_from_caller_outer=True,creation_factories_rederived=True,
        sealed_source_interfaces_only=True,contextual_seeds_never_generalized=True,
        returned_provenances_never_generally_admitted=True,
        provenance_wire_format='gzip-jsonl',
        **{n:False for n in NO_PROOF})
    _durable_bytes(out/'result.json',_json(report),replace=False);return report


class ReturnedFunctionInterfaceStore:
    def __init__(self,path,catalog=None):
        self.path=Path(path).absolute();self.raw=(self.path/'result.json').read_bytes();self.report=r=json.loads(self.raw)
        if (r['schema'],r['schema_version'])!=(SCHEMA,1) or r['pins']!=_pins():raise ValueError('returned-interface schema or rules differ')
        self.parents=_Parents(r['parent_path'],r['creations_path']);self.parent=self.parents.parent;self.catalog=self.parents.catalog
        if catalog is not None:
            from scar.analysis.source_context_query import ContextTargetGraph
            catalog=catalog if isinstance(catalog,ContextTargetGraph) else ContextTargetGraph(catalog)
            if (catalog.path,catalog.report)!=(self.catalog.path,self.catalog.report):raise ValueError('returned catalog differs')
        self._loaded={};self._cache={};self._verified=set();_limits(**r['limits'])
        if (r['selection']!=list(_selected(self.parent,r['selection'])) or tuple(r['shards'])!=tuple(r['selection'])
                or r['tables']!=_flat_tables(r['shards']) or r['counts']!=_totals(r['shards'])
                or r['provenance_wire_format']!='gzip-jsonl'
                or r['catalog']!=str(self.catalog.path)
                or r['catalog_parent']!=encode(_artifact(self.catalog.path/'result.json',self.catalog.report['schema']))
                or r['parent']!=encode(_artifact(self.parent.path/'result.json',self.parent.report['schema']))
                or r['creations']!=encode(_artifact(self.parents.creations.path/'result.json',self.parents.creations.report['schema']))
                or any(r[n] is not False for n in NO_PROOF)
                or any(r[n] is not True for n in ('sealed_parent_single_pass','creator_context_separate_from_caller_outer','creation_factories_rederived',
                    'sealed_source_interfaces_only','contextual_seeds_never_generalized','returned_provenances_never_generally_admitted'))):
            raise ValueError('returned-interface parents, selection, counts or proof flags differ')
        for unit,s in r['shards'].items():
            if s['path']!=_folder(unit) or set(s['tables'])!=set(TABLES) or any(t['path']!=n+'.jsonl.gz' for n,t in s['tables'].items()):
                raise ValueError('returned-interface table layout differs')
        self.validate()

    def validate(self):
        if self.raw!=(self.path/'result.json').read_bytes() or self.report['pins']!=_pins() or any(_stamp(p)!=s for p,s in self._loaded.items()):
            raise ValueError('returned-interface material or rules changed')
        self.parents.validate()

    def _load(self,unit):
        self.validate()
        if unit in self._cache:return self._cache[unit]
        s=self.report['shards'][unit];folder=self.path/s['path']
        def rows(name,kind):
            p=folder/s['tables'][name]['path'];stamp=_stamp(p)
            result=tuple(decode(kind,w,record_tags=P.PRODUCTION_RECORD_TAGS) for w in _table(folder,s['tables'][name]))
            if _stamp(p)!=stamp:raise ValueError('returned-interface table changed while decoding')
            self._loaded[p]=stamp;return result
        ps=rows('provenances',R.ReturnedCallableProvenance);fs=rows('return_frontiers',R.ReturnedCallableFrontier)
        graph=I.SourceFunctionInterfaceUnit(unit,s['counts']['calls'],s['counts']['parent_function_origins'],tuple(s['controlled_queries']),
            rows('interfaces',I.SourceFunctionInterface),rows('frontiers',I.SourceFunctionInterfaceFrontier),rows('queries',I.SourceFunctionInterfaceQuery))
        parent=self.parent.load_unit(unit)
        if (_counts(graph,len(parent.interfaces),ps,fs)!=s['counts'] or graph!=self.parents.overlay(unit,parent,ps,fs,folder,s['tables']['provenances'])):
            raise ValueError('returned interfaces differ from sealed parent and original signature ABI')
        self._cache[unit]=(graph,ps,fs);self.validate();return self._cache[unit]

    def load_unit(self,unit):return self._load(unit)[0]
    def load_declarations(self,unit):return _declarations(self.parent,unit)

    def read_unit(self,unit):
        graph,ps,fs=self._load(unit)
        if unit not in self._verified:
            expected=self.parents.collect(unit,self.parent.load_unit(unit),self.report['limits'])
            if (ps,fs)!=expected:raise ValueError('returned references, creator selection or bounds differ from original rules')
            self._verified.add(unit)
        self.validate();return graph

    def interface_fact(self,unit,i):
        self.validate();s=self.report['shards'][unit]
        if type(i) is not int or not 0<=i<s['counts']['interfaces']:raise ValueError('interface ordinal lies outside original unit')
        if i<s['counts']['parent_interfaces']:return _interface_fact(self.parent,unit,i)
        return _table_ref(self.path/s['path'],s['tables']['interfaces'],'scar.source-function-interface-record',i)

    def callable_provenance(self,unit,i):
        self.interface_fact(unit,i);graph,ps,_=self._load(unit);s=self.report['shards'][unit]
        if i<s['counts']['parent_interfaces']:
            method=getattr(self.parent,'callable_provenance',None)
            return method(unit,i) if callable(method) else None
        evidence=graph.interfaces[i].reference
        return next(p for j,p in enumerate(ps) if evidence==_table_ref(self.path/s['path'],s['tables']['provenances'],'scar.returned-callable-provenance',j))

    def provenance_locator(self,unit,i):
        """The exact original manifest receipt; the interface retains the row FactRef."""
        self.interface_fact(unit,i);s=self.report['shards'][unit]
        if i<s['counts']['parent_interfaces']:
            method=getattr(self.parent,'provenance_locator',None)
            return method(unit,i) if callable(method) else None
        artifact=_artifact(self.path/'result.json',SCHEMA)
        return SourceArtifactLocator(artifact,artifact.sha256,artifact.size_bytes,'canonical-json',
            '#/shards/'+unit+'/tables/provenances')


def main():
    import sys
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--parent');parser.add_argument('--creations')
    parser.add_argument('--out');parser.add_argument('--unit',action='append',default=[]);parser.add_argument('--read')
    parser.add_argument('--max-states',type=int,default=256);parser.add_argument('--max-depth',type=int,default=8)
    args=parser.parse_args();sys.meta_path.insert(0,_NoTargets());_check_targets()
    if args.read:
        store=ReturnedFunctionInterfaceStore(args.read)
        for unit in _selected(store,args.unit):store.read_unit(unit)
        print(json.dumps(store.report['counts']),flush=True)
    else:
        if not args.parent or not args.creations or not args.out:parser.error('--parent, --creations and --out required')
        r=build_returned_interfaces(args.parent,args.creations,args.out,args.unit,args.max_states,args.max_depth)
        _check_targets();print(json.dumps(r['counts']),flush=True)


if __name__=='__main__':main()
