"""Connect retained source-function origins to original parameters and returns.

Reuse the existing signature binder without an entry solver or target imports.
All source-call declarations stay in their parent shards. Optional normal-flow
queries select a conditional source branch, without replacing other branches.
Function/environment versions, effects and runtime dispatch remain open.
"""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
import json
import multiprocessing
from pathlib import Path
import sys
import time

from scar.analysis.source_declared_calls import DeclaredCallStore, _NoTargets, _check_targets, _folder, _flat_tables
from scar.analysis.source_control_namespaces import ControlNamespaceStore
from scar.analysis.source_field_interfaces import _InterfaceOnly
from scar.analysis.source_function_connections import Invocation, connect
from scar.analysis.source_reference_slice import source_port
from scar.analysis.source_world_returns import _table_ref
from scar.analysis.source_value_flow import _artifact
from scar.analysis.source_symbol_variants import _table
from scar.analysis.normal_output import write_table
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_template_links import _json
from scar.ir.program import source_function_interfaces as R, source_namespace_references as N
from scar.ir.program import normal_targets as T, source_productions as P
from scar.ir.record_codec import decode, encode


SCHEMA = 'scar.source-function-interfaces'
NO_PROOF = ('source_scopes_activated', 'caller_contexts_selected', 'runtime_dispatch_proven',
    'current_function_environment_versions_proven', 'effects_proven', 'source_relations_rederived',
    'namespace_semantics_rederived', 'loops_unrolled', 'target_executed', 'first_stage_complete')
COVERAGE = 'ALL_FUNCTION_DEFINITION_ORIGINS_IN_SELECTED_RETAINED_CALLEE_QUERY_BRANCHES'
TABLES = ('queries', 'interfaces', 'frontiers')
_WORKER = None


class FunctionInterfaceParents:
    def __init__(self, calls, *, control=None):
        _check_targets()
        self.calls = calls if isinstance(calls, DeclaredCallStore) else DeclaredCallStore(calls)
        self.control = None; self.control_parent = None
        if control is not None:
            self.control = control if isinstance(control, ControlNamespaceStore) else ControlNamespaceStore(control)
            if (self.control.parent.path != self.calls.path or self.control.report['parent'] !=
                    encode(_artifact(self.calls.path/'result.json', self.calls.report['schema']))):
                raise ValueError('source function interfaces use a different control/declaration parent')
            # Both strict readers established the exact same parent receipt.
            # Share its catalog and caches instead of retaining a second copy.
            self.control.parent = self.calls
            self.control_parent = _artifact(self.control.path/'result.json', self.control.report['schema'])
        self.parent = _artifact(self.calls.path/'result.json', self.calls.report['schema'])

    def validate(self):
        self.calls.validate()
        if self.control is not None:
            if (self.control.raw != (self.control.path/'result.json').read_bytes()
                    or self.control_parent != _artifact(self.control.path/'result.json', self.control.report['schema'])):
                raise ValueError('source function normal-control parent changed')
            from scar.analysis.source_control_namespaces import _pins
            if self.control.report['pins'] != _pins(): raise ValueError('source function normal-control rules changed')

    def project(self, unit):
        """Rebind retained origins; the parent's namespace proof is not replayed.

        Optional control queries are separately rederived and select only their
        recorded normal-view branch. The original declaration and all its
        frontiers remain available through each output query's parent index.
        """
        controlled = self.control is not None and unit in self.control.report['shards']
        original = self.calls.load_unit(unit); references = {}; controlled_queries = ()
        if controlled:
            graph = self.control.read_unit(unit); controlled_queries = tuple(q.query for q in graph.queries)
            shard = self.control.report['shards'][unit]; folder = self.control.path/shard['path']
            for ordinal, query in enumerate(graph.queries):
                if (not 0 <= query.query < len(original.queries) or query.query in references
                        or query.callee != original.queries[query.query].callee):
                    raise ValueError('controlled callee differs from original source call')
                references[query.query] = (query.reference, _table_ref(folder, shard['tables']['queries'],
                    'scar.control-qualified-source-query', ordinal), query.conditions)
        source_shard = self.calls.report['shards'][unit]; folder = self.calls.path/source_shard['path']
        resolver = self.calls.runtime.resolver; slicer = resolver.slicer
        caller = self.calls.catalog.fact_store.load(unit); offset = slicer.store.offsets[unit]
        interfaces = []; frontiers = []; queries = []; functions = {}; origins = 0
        for qi, query in enumerate(original.queries):
            declared = _table_ref(folder, source_shard['tables']['queries'], 'scar.declared-source-call-query', qi)
            reference, evidence, branch = references.get(qi, (query.reference,
                declared, ()))
            call = caller.calls[qi]
            invocation = Invocation(offset+call.callee, tuple(offset+p for p in call.positional),
                tuple((name, offset+p) for name,p in call.keywords), offset+call.result,
                offset+call.world, offset+call.result_world,
                None if call.positional_pack is None else offset+call.positional_pack,
                None if call.keyword_pack is None else offset+call.keyword_pack)
            origin_indices = []; interface_indices = []
            for oi, origin in enumerate(reference.origins):
                if origin.kind is not N.NamespaceOriginKind.FUNCTION_DEFINITION: continue
                origins += 1; origin_indices.append(oi); terminal = reference.states[origin.state]
                if terminal.selectors: raise ValueError('source function origin retains pending attributes')
                provider, local = slicer.local(terminal.port)
                matches = [(i,f) for i,f in enumerate(provider.functions) if f.value == local]
                if len(matches) != 1: raise ValueError('source function origin is not one original function definition')
                fi, function = matches[0]; definition = slicer.fact(provider, 'functions', fi)
                if origin.evidence != (definition,): raise ValueError('source function definition evidence differs')
                if terminal.port not in functions: functions[terminal.port] = _InterfaceOnly(slicer, provider, function)
                mini = functions[terminal.port]
                connection = connect(mini, mini.offsets[provider.unit]+function.value, invocation, conditions=(
                    'RECORDED_SOURCE_CALLEE_REFERENCE_PATH_AND_ITS_PRECONDITIONS_SELECTED',
                    'CURRENT_CALLABLE_IS_RECORDED_SOURCE_FUNCTION_WITH_COMPATIBLE_CALL_PROTOCOL',
                    'FUNCTION_CODE_CAPTURE_DEFAULT_AND_NAMESPACE_VERSIONS_MATCH_DECLARATION',
                    *origin.conditions,
                    *branch))
                if connection is None:
                    frontiers.append(R.SourceFunctionInterfaceFrontier(qi, oi, evidence,
                        'SOURCE_SIGNATURE_REQUIRES_DIFFERENT_ARGUMENT_OR_DESCRIPTOR_BINDING')); continue
                mode = ('SOURCE_FUNCTION' if connection.activation is T.FunctionActivation.NORMAL
                    else 'CREATE_DEFERRED_BODY')
                link = T.CallLink(source_port(caller, call.result), source_port(caller, call.callee),
                    connection.source_callable, connection.body, mode, None, connection.parameters,
                    connection.returns, connection.conditions, argument_packs=connection.argument_packs,
                    projections=connection.projections, binding=connection.binding)
                interface_indices.append(len(interfaces))
                interfaces.append(R.SourceFunctionInterface(qi, oi, query.call, definition, evidence, connection.activation, link))
                if connection.activation is not T.FunctionActivation.NORMAL:
                    frontiers.append(R.SourceFunctionInterfaceFrontier(qi, oi, evidence,
                        'DEFERRED_CREATION_HAS_NO_ORDINARY_BODY_DATA_OR_WORLD_RETURN'))
            if not origin_indices:
                frontiers.append(R.SourceFunctionInterfaceFrontier(qi, None, evidence,
                    'NO_RECORDED_SOURCE_FUNCTION_ORIGIN_OTHER_CALLEE_ALTERNATIVES_REMAIN_OPEN'))
            if reference.frontiers:
                frontiers.append(R.SourceFunctionInterfaceFrontier(qi, None, evidence,
                    'PARENT_CALLEE_REFERENCE_FRONTIERS_REMAIN_OPEN'))
            queries.append(R.SourceFunctionInterfaceQuery(qi, query.call, declared, evidence, query.owners,
                tuple(origin_indices), tuple(interface_indices), tuple(range(len(query.reference.frontiers))),
                tuple(range(len(reference.frontiers)))))
        self.validate(); _check_targets()
        return R.SourceFunctionInterfaceUnit(unit, len(original.queries), origins, controlled_queries,
            tuple(interfaces), tuple(frontiers), tuple(queries))


def _counts(graph):
    return dict(calls=graph.calls, function_origins=graph.function_origins, controlled_queries=len(graph.controlled_queries),
        query_indexes=len(graph.queries),
        declared_namespace_frontiers=sum(len(q.declared_frontiers) for q in graph.queries),
        retained_namespace_frontiers=sum(len(q.reference_frontiers) for q in graph.queries),
        interfaces=len(graph.interfaces), source_functions=len({r.link.source_callable for r in graph.interfaces}),
        connected_calls=len({r.query for r in graph.interfaces}),
        unconnected_calls=graph.calls-len({r.query for r in graph.interfaces}),
        binding_kinds=dict(Counter(r.link.binding.value for r in graph.interfaces)),
        activation_kinds=dict(Counter(r.activation.value for r in graph.interfaces)),
        parameter_routes=sum(len(r.link.parameters) for r in graph.interfaces),
        projection_routes=sum(len(r.link.projections) for r in graph.interfaces),
        data_returns=sum(sum(target == r.link.result for _, target in r.link.returns) for r in graph.interfaces),
        state_returns=sum(sum(target != r.link.result for _, target in r.link.returns) for r in graph.interfaces),
        frontiers=len(graph.frontiers), frontier_reasons=dict(Counter(f.reason for f in graph.frontiers)))


def _totals(shards):
    scalar = Counter(); dictionaries = {k:Counter() for k in ('binding_kinds', 'activation_kinds', 'frontier_reasons')}
    for shard in shards.values():
        for key,value in shard['counts'].items():
            if key in dictionaries: dictionaries[key].update(value)
            else: scalar[key] += value
    # source_functions counts per-unit unique targets, not globally unique functions.
    scalar['source_function_unit_pairs'] = scalar.pop('source_functions', 0)
    return dict(units=len(shards), **scalar, **{k:dict(v) for k,v in dictionaries.items()})


def _pins():
    from scar.analysis import source_function_connections, source_field_interfaces
    from scar.analysis import normal_output, source_reference_slice, source_symbol_variants
    from scar.analysis import source_world_returns, source_value_flow
    from scar.ir import record_codec
    return dict(producer=sha256(Path(__file__).read_bytes()).hexdigest(), **{
        name:sha256(Path(module.__file__).read_bytes()).hexdigest() for name,module in (
            ('types', R), ('binder', source_function_connections), ('interface_adapter', source_field_interfaces),
            ('target_types', T), ('production_types', P), ('namespace_types', N),
            ('references', source_reference_slice), ('table_references', source_world_returns),
            ('material_receipts', source_value_flow), ('output', normal_output),
            ('tables', source_symbol_variants), ('codec', record_codec))})


def _selected(parent, units=None):
    if isinstance(units, str): units = (units,)
    requested = tuple(units or ())
    if any(type(u) is not str or u not in parent['shards'] for u in requested):
        raise ValueError('source function interface unit is absent from declared calls')
    return tuple(sorted(set(requested))) if requested else tuple(parent['shards'])


def _denominator(parent, shards):
    parent_calls = sum(s['counts']['calls'] for s in parent['shards'].values())
    selected_calls = sum(s['calls'] for s in shards.values())
    return dict(parent_units=len(parent['shards']), selected_units=len(shards),
        unselected_units=len(parent['shards'])-len(shards), parent_calls=parent_calls,
        selected_calls=selected_calls, unselected_calls=parent_calls-selected_calls,
        selected_declared_function_origins=sum(parent['shards'][u]['counts']['origin_kinds'].get(
            'FUNCTION_DEFINITION', 0) for u in shards))


def _write(parents, unit, out, pins):
    started = time.monotonic(); graph = parents.project(unit); folder = Path(out)/_folder(unit); tables = {}
    _durable_mkdir(folder)
    tables = {name:write_table(folder/(name+'.jsonl.gz'), getattr(graph,name)) for name in TABLES}
    if pins != _pins(): raise ValueError('source function interface rules changed')
    parents.calls.runtime.clear()
    return dict(path=_folder(unit), calls=graph.calls, function_origins=graph.function_origins,
        controlled_queries=list(graph.controlled_queries), tables=tables, counts=_counts(graph), seconds=time.monotonic()-started)


def _initialize(calls, control, out, pins):
    global _WORKER
    sys.meta_path.insert(0, _NoTargets()); _check_targets()
    _WORKER = FunctionInterfaceParents(calls, control=control), out, pins


def _worker(unit):
    parents,out,pins = _WORKER
    return unit,_write(parents,unit,out,pins)


def build_function_interfaces(calls, out, *, control=None, jobs=4, units=None):
    started = time.monotonic(); pins = _pins(); out = Path(out).absolute()
    if out.exists(): raise ValueError('fresh source function interface output required')
    if type(jobs) is not int or jobs < 1: raise ValueError('positive source function interface jobs required')
    parents = FunctionInterfaceParents(calls, control=control)
    selected = _selected(parents.calls.report, units)
    selection = dict(mode='EXPLICIT_UNITS' if units else 'ALL_PARENT_UNITS', units=list(selected))
    _durable_mkdir(out)
    if jobs == 1:
        shards = {u:_write(parents,u,out,pins) for u in selected}
    else:
        with ProcessPoolExecutor(max_workers=min(jobs, len(selected)), mp_context=multiprocessing.get_context('spawn'), initializer=_initialize,
                initargs=(str(parents.calls.path), None if parents.control is None else str(parents.control.path), str(out), pins)) as pool:
            shards = dict(pool.map(_worker, selected, chunksize=1))
    parents.validate()
    if pins != _pins(): raise ValueError('source function interface rules changed during build')
    report = dict(schema=SCHEMA, schema_version=1, calls=str(parents.calls.path), parent=encode(parents.parent),
        control=None if parents.control is None else str(parents.control.path),
        control_parent=None if parents.control_parent is None else encode(parents.control_parent), pins=pins,
        shards=shards,tables=_flat_tables(shards),counts=_totals(shards),jobs=jobs,seconds=time.monotonic()-started,
        selection=selection, denominator=_denominator(parents.calls.report, shards), coverage=COVERAGE,
        scope='CONDITIONAL_SIGNATURE_INTERFACES_NOT_SELECTED_CALLERS_OR_RUNTIME_DISPATCH',
        parent_query_indexes_include_unconnected_calls_and_frontiers=True,
        **{name:False for name in NO_PROOF})
    _durable_bytes(out/'result.json',_json(report),replace=False)
    return report


class SourceFunctionInterfaceStore:
    """Material-only load_unit; read_unit replays only the interface projection.

    The declared namespace graph is loaded with its original receipts/ABI;
    read_unit does not certify that parent's namespace relations anew.
    """
    def __init__(self,path):
        self.path=Path(path).absolute();self.raw=(self.path/'result.json').read_bytes();self.report=r=json.loads(self.raw)
        if (r['schema'],r['schema_version'])!=(SCHEMA,1) or r['pins']!=_pins():
            raise ValueError('source function interface schema or rules differ')
        self.parents=FunctionInterfaceParents(r['calls'],control=r['control'])
        if (r['parent']!=encode(self.parents.parent) or r['control_parent']!=(None if self.parents.control_parent is None
                else encode(self.parents.control_parent))): raise ValueError('source function interface parents differ')
        selection=r['selection']
        if selection['mode'] not in ('ALL_PARENT_UNITS', 'EXPLICIT_UNITS'):
            raise ValueError('source function interface selection mode differs')
        selected=_selected(self.parents.calls.report,
            None if selection['mode']=='ALL_PARENT_UNITS' else selection['units'])
        if (selection['units']!=list(selected) or tuple(r['shards'])!=selected or r['tables']!=_flat_tables(r['shards'])
                or r['counts']!=_totals(r['shards']) or any(r[n] is not False for n in NO_PROOF)
                or r['coverage']!=COVERAGE or r['denominator']!=_denominator(self.parents.calls.report,r['shards'])
                or r['scope']!='CONDITIONAL_SIGNATURE_INTERFACES_NOT_SELECTED_CALLERS_OR_RUNTIME_DISPATCH'
                or r['parent_query_indexes_include_unconnected_calls_and_frontiers'] is not True):
            raise ValueError('source function interface coverage, receipts or proof status differ')
        for unit,shard in r['shards'].items():
            source=self.parents.calls.report['shards'][unit]
            if (shard['path']!=_folder(unit) or shard['calls']!=source['counts']['calls']
                    or set(shard['tables'])!=set(TABLES)
                    or any(v['path']!=name+'.jsonl.gz' for name,v in shard['tables'].items())):
                raise ValueError('source function interface original unit or tables differ')
        self.catalog=self.parents.calls.catalog; self.snapshot=self.parents.calls.snapshot
        self.validate()

    def validate(self):
        if self.raw!=(self.path/'result.json').read_bytes() or self.report['pins']!=_pins():
            raise ValueError('source function interface report/rules changed')
        self.parents.validate()

    def load_unit(self,unit):
        """Check stored bytes/types/counts/indexes; no namespace or ABI rebinding."""
        self.validate();shard=self.report['shards'][unit];folder=self.path/shard['path']
        def rows(name,cls):
            return tuple(decode(cls,w,record_tags=P.PRODUCTION_RECORD_TAGS)
                for w in _table(folder,shard['tables'][name]))
        graph=R.SourceFunctionInterfaceUnit(unit,shard['calls'],shard['function_origins'],tuple(shard['controlled_queries']),
            rows('interfaces',R.SourceFunctionInterface),rows('frontiers',R.SourceFunctionInterfaceFrontier),
            rows('queries',R.SourceFunctionInterfaceQuery))
        if _counts(graph)!=shard['counts']: raise ValueError('source function interface unit counts differ')
        if (tuple(q.query for q in graph.queries)!=tuple(range(graph.calls))
                or sum(len(q.function_origins) for q in graph.queries)!=graph.function_origins
                or len(set(graph.controlled_queries))!=len(graph.controlled_queries)
                or any(not 0<=q<graph.calls for q in graph.controlled_queries)):
            raise ValueError('source function interface query coverage differs')
        parent=self.parents.calls.report['shards'][unit]; parent_folder=self.parents.calls.path/parent['path']
        indexed=defaultdict(list)
        for i,interface in enumerate(graph.interfaces): indexed[interface.query].append(i)
        for query in graph.queries:
            if (query.declared!=_table_ref(parent_folder,parent['tables']['queries'],
                    'scar.declared-source-call-query',query.query)
                    or not query.owners or any(o.unit!=unit for o in query.owners)
                    or query.interfaces!=tuple(indexed[query.query])):
                raise ValueError('source function interface parent query/index differs')
        for interface in graph.interfaces:
            if not 0<=interface.query<graph.calls:
                raise ValueError('source function interface lies outside its original calls')
            query=graph.queries[interface.query]
            if (interface.origin not in query.function_origins or interface.call!=query.call
                    or interface.reference!=query.reference or interface.link.runtime_dispatch_verified is not False
                    or interface.link.source_callable is None or interface.link.body is None
                    or (interface.activation is T.FunctionActivation.NORMAL and interface.link.mode!='SOURCE_FUNCTION')
                    or (interface.activation is T.FunctionActivation.CREATE_DEFERRED_BODY
                        and (interface.link.mode!='CREATE_DEFERRED_BODY' or interface.link.returns))
                    or interface.activation not in (T.FunctionActivation.NORMAL,T.FunctionActivation.CREATE_DEFERRED_BODY)):
                raise ValueError('source function interface candidate/activation differs')
        for frontier in graph.frontiers:
            if (not 0<=frontier.query<graph.calls or frontier.reference!=graph.queries[frontier.query].reference
                    or (frontier.origin is not None and frontier.origin not in graph.queries[frontier.query].function_origins)):
                raise ValueError('source function interface frontier index differs')
        self.validate()
        return graph

    def read_unit(self,unit):
        """Rebind this selected unit against retained parent queries/original facts."""
        graph=self.load_unit(unit)
        if graph!=self.parents.project(unit): raise ValueError('source function interfaces differ from original callee candidates/ABI')
        self.validate(); _check_targets(); return graph


def read_function_interfaces(path, *, unit):
    store=SourceFunctionInterfaceStore(path)
    return store.report,store.read_unit(unit)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--calls');parser.add_argument('--control');parser.add_argument('--out')
    parser.add_argument('--jobs',type=int,default=4);parser.add_argument('--read')
    parser.add_argument('--unit',action='append',default=[])
    args=parser.parse_args()
    sys.meta_path.insert(0,_NoTargets()); _check_targets()
    if args.read:
        if not args.unit:parser.error('--read requires --unit for explicit source interface rederivation')
        store=SourceFunctionInterfaceStore(args.read)
        counts={unit:_counts(store.read_unit(unit)) for unit in _selected(store.report,args.unit)}
        print(json.dumps(dict(status='SOURCE_FUNCTION_INTERFACES_REDERIVED',units=counts,
            namespace_semantics_rederived=False,source_relations_rederived=False)),flush=True)
    else:
        if not args.calls or not args.out:parser.error('--calls and --out required')
        report=build_function_interfaces(args.calls,args.out,control=args.control,jobs=args.jobs,units=args.unit)
        print(json.dumps(dict(status='SOURCE_FUNCTION_INTERFACES_BUILT',counts=report['counts'],
            denominator=report['denominator'],seconds=report['seconds'])),flush=True)


if __name__=='__main__':main()
