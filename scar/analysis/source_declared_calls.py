"""Project every retained source callsite independently of entry worklists.

Workers own per-unit shards and bounded namespace queries. Source scope owners
are declarations, not activation witnesses; no incoming interface, invocation,
body copy, loop iteration or native target is invented by this producer.
"""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
from importlib.abc import MetaPathFinder
import json
import multiprocessing
from pathlib import Path
import sys
import time
from types import SimpleNamespace

from scar.analysis.source_declared_catalog import read_source_catalog
from scar.analysis.source_namespace_references import NamespaceReferenceResolver
from scar.analysis.source_reference_slice import source_port
from scar.analysis.source_symbol_variants import _table
from scar.analysis.source_value_flow import _artifact
from scar.analysis.normal_output import write_table
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_template_links import _json
from scar.ir.program import source_declared_calls as D, normal_links as F, source_productions as P
from scar.ir.record_codec import decode, encode


SCHEMA = 'scar.source-declared-calls'
UNIT_SCHEMA = 'scar.source-declared-call-unit'
NO_PROOF = ('source_scopes_activated', 'caller_contexts_selected', 'runtime_dispatch_proven',
    'current_namespace_versions_proven', 'compiled_units_included', 'source_bodies_copied',
    'loops_unrolled', 'target_executed', 'first_stage_complete')
_WORKER = None


class _NoTargets(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0].lower() in {'torch', 'hydra', 'omegaconf', 'lewm'}:
            raise ImportError('target imports are forbidden in declared source call projection: '+fullname)


def _check_targets():
    if any(name.split('.')[0].lower() in {'torch', 'hydra', 'omegaconf', 'lewm'} for name in sys.modules):
        raise RuntimeError('declared source call projection has imported a target library')


def _open_catalog(catalog):
    catalog = read_source_catalog(catalog)
    raw = (catalog.path/'result.json').read_bytes()
    if json.loads(raw) != catalog.report: raise ValueError('declared call catalog changed')
    artifact = _artifact(catalog.path/'result.json', catalog.report['schema'])
    def validate():
        if raw != (catalog.path/'result.json').read_bytes(): raise ValueError('declared call catalog changed')
        catalog.fact_store.validate_parents(); catalog.interface_store.validate_parents()
    validate()
    return catalog, SimpleNamespace(fact_store=catalog.fact_store, validate_parents=validate), artifact


def _limits(max_states, max_selectors):
    if any(type(n) is not int or n < 1 for n in (max_states, max_selectors)):
        raise ValueError('declared callee queries require positive state and selector budgets')
    return dict(max_states=max_states, max_selectors=max_selectors)


def _roots(values):
    if isinstance(values, (str, Path)): values = (values,)
    result = tuple(sorted({str(Path(value).resolve()) for value in values}))
    if not result: raise ValueError('at least one source root is required')
    return result


def _selection(store, roots):
    paths = tuple(Path(root) for root in roots)
    return tuple(sorted(identity for identity in store.importable_units
        if identity not in store.original_source_units
        and store.rows[identity].get('facts_format') != 'COMPILE_CONTEXT_F4_JSONL'
        and any(Path(store.rows[identity]['path']).is_relative_to(root) for root in paths)))


def _owners(unit):
    owners = defaultdict(set)
    for group in unit.scope_groups:
        for span in group.tables:
            if span.table is not F.FactTable.CALLS: continue
            if group.owner.unit != unit.unit or not 0 <= span.start <= span.stop <= len(unit.calls):
                raise ValueError('source call owner range differs from its original unit')
            for index in range(span.start, span.stop): owners[index].add(group.owner)
    result = tuple(tuple(sorted(owners[i], key=lambda ref: ref.ordinal)) for i in range(len(unit.calls)))
    if any(not row for row in result): raise ValueError('source call lacks its original code scope owner')
    return result


def _cuts(resolver, reference):
    formals = []; results = []; result_sets = {}
    for frontier in reference.frontiers:
        if frontier.reason == 'FUNCTION_PARAMETER_REQUIRES_SELECTED_CALL_CONTEXT':
            formals.append(frontier.state)
        if frontier.reason == 'SOURCE_REFERENCE_PRODUCER_UNRESOLVED':
            state = reference.states[frontier.state]; unit, local = resolver.slicer.local(state.port)
            if unit.unit not in result_sets: result_sets[unit.unit] = {call.result for call in unit.calls}
            if local in result_sets[unit.unit]: results.append(frontier.state)
    return tuple(sorted(set(formals))), tuple(sorted(set(results)))


def _symbols(resolver, queries):
    symbols = []
    for ordinal, query in enumerate(queries):
        for index, state in enumerate(query.reference.states):
            if not state.selectors: continue
            unit, local = resolver.slicer.local(state.port)
            _, *_, imports, _ = resolver.unit(unit.unit)
            for imported_ordinal, imported in imports.get(local, ()):
                symbols.append(D.DeclaredCallSymbolRequest(ordinal, index,
                    resolver.slicer.fact(unit, 'imports', imported_ordinal), imported.module,
                    imported.requested_module, state.selectors))
    return tuple(symbols)


def project_declared_calls(snapshot, identity, *, resolver=None, max_states=4000, max_selectors=32):
    limits = _limits(max_states, max_selectors); store = snapshot.fact_store
    if identity not in store.importable_units or identity in store.original_source_units:
        raise ValueError('declared call projection requires an original importable source unit')
    resolver = resolver if resolver is not None else NamespaceReferenceResolver(snapshot)
    unit = store.load(identity); owners = _owners(unit); queries = []
    for ordinal, call in enumerate(unit.calls):
        callee = source_port(unit, call.callee); reference = resolver.resolve(callee, **limits)
        formal, results = _cuts(resolver, reference)
        queries.append(D.DeclaredCallQuery(identity, resolver.slicer.fact(unit, 'calls', ordinal),
            callee, owners[ordinal], reference, formal, results))
    queries = tuple(queries); snapshot.validate_parents()
    return D.DeclaredCallUnit(identity, queries, _symbols(resolver, queries))


def _counts(graph):
    named = {row.query for row in graph.symbols}
    return dict(calls=len(graph.queries), named_requests=len(graph.symbols), queries_with_named_requests=len(named),
        queries_with_formal_frontier=sum(bool(q.formal_frontiers) for q in graph.queries),
        queries_with_call_result_frontier=sum(bool(q.call_result_frontiers) for q in graph.queries),
        formal_frontier_states=sum(len(q.formal_frontiers) for q in graph.queries),
        call_result_frontier_states=sum(len(q.call_result_frontiers) for q in graph.queries),
        namespace_states=sum(len(q.reference.states) for q in graph.queries),
        namespace_edges=sum(len(q.reference.edges) for q in graph.queries),
        origin_kinds=dict(Counter(o.kind.value for q in graph.queries for o in q.reference.origins)),
        frontier_reasons=dict(Counter(f.reason for q in graph.queries for f in q.reference.frontiers)))


def _totals(shards):
    result = Counter(); origins = Counter(); frontiers = Counter()
    for shard in shards.values():
        for key, value in shard['counts'].items():
            if key == 'origin_kinds': origins.update(value)
            elif key == 'frontier_reasons': frontiers.update(value)
            else: result[key] += value
    return dict(units=len(shards), **result, origin_kinds=dict(origins), frontier_reasons=dict(frontiers))


def _pins():
    from scar.analysis import source_namespace_references, source_reference_slice, source_class_base_graph
    from scar.analysis import source_context_query, source_context_fact_store, normal_facts, normal_output
    from scar.analysis import source_symbol_variants
    from scar.ir.program import source_namespace_references as N, normal_targets as T, normal_graph as G
    from scar.ir import record_codec
    return dict(producer=sha256(Path(__file__).read_bytes()).hexdigest(), **{
        name: sha256(Path(module.__file__).read_bytes()).hexdigest() for name, module in (
            ('types', D), ('namespaces', source_namespace_references), ('namespace_types', N),
            ('references', source_reference_slice), ('catalog_adapter', source_class_base_graph),
            ('catalog_reader', source_context_query), ('context_facts', source_context_fact_store),
            ('facts', normal_facts), ('fact_types', F), ('target_types', T), ('graph_types', G),
            ('production_types', P), ('output', normal_output), ('tables', source_symbol_variants),
            ('codec', record_codec))})


class _Runtime:
    def __init__(self, catalog):
        _check_targets()
        self.catalog, self.snapshot, self.parent = _open_catalog(catalog)
        self.resolver = NamespaceReferenceResolver(self.snapshot)

    def clear(self):
        # Keep one catalog/resolver, but release ordinary facts and port maps
        # between unit tasks. Namespace traversal may have loaded other units.
        self.resolver.units.clear(); self.resolver.slicer.units.clear()
        store = self.catalog.fact_store; keep = set(store.original_source_units); visited = set()
        def release(parent):
            if id(parent) in visited: return
            visited.add(id(parent))
            for identity in tuple(parent.loaded):
                if identity not in keep: del parent.loaded[identity]
            for child in getattr(parent, 'parents', ()): release(child)
        release(store)
        for parent in store._source_parents.values(): release(parent)


def _folder(unit):
    if type(unit) is not str or not unit or Path(unit).name != unit or unit in ('.', '..') or '\\' in unit:
        raise ValueError('source unit is not a safe original shard identity')
    return 'units/'+unit


def _write_unit(runtime, unit, out, limits, pins):
    started = time.monotonic(); row = runtime.catalog.fact_store.rows[unit]
    graph = project_declared_calls(runtime.snapshot, unit, resolver=runtime.resolver, **limits)
    folder = Path(out)/_folder(unit); _durable_mkdir(folder)
    tables = {name: write_table(folder/(name+'.jsonl.gz'), getattr(graph, name)) for name in ('queries', 'symbols')}
    descriptor = dict(path=_folder(unit), source=row['path'], module=row['module'], tables=tables, counts=_counts(graph))
    report = dict(schema=UNIT_SCHEMA, schema_version=1, unit=unit, parent=encode(runtime.parent),
        source=descriptor['source'], module=descriptor['module'], limits=limits, pins=pins,
        tables=tables, counts=descriptor['counts'], **{name: False for name in NO_PROOF})
    if _pins() != pins: raise ValueError('declared call projection rules changed')
    _durable_bytes(folder/'result.json', _json(report), replace=False)
    descriptor['result'] = encode(_artifact(folder/'result.json', UNIT_SCHEMA))
    descriptor['seconds'] = time.monotonic()-started
    runtime.clear(); _check_targets()
    return descriptor


def _initialize_worker(catalog, parent, out, limits, pins):
    global _WORKER
    _check_targets(); sys.meta_path.insert(0, _NoTargets())
    runtime = _Runtime(catalog)
    if encode(runtime.parent) != parent or _pins() != pins:
        raise ValueError('declared call worker catalog or producer differs')
    _WORKER = runtime, out, limits, pins


def _worker(unit):
    runtime, out, limits, pins = _WORKER
    return unit, _write_unit(runtime, unit, out, limits, pins)


def _flat_tables(shards):
    return {unit+'/'+name: dict(receipt, path=shard['path']+'/'+receipt['path'])
        for unit, shard in shards.items() for name, receipt in shard['tables'].items()}


def build_declared_calls(catalog, out, *, source_roots, jobs=4, max_states=4000, max_selectors=32):
    started = time.monotonic(); pins = _pins(); out = Path(out).absolute()
    if out.exists(): raise ValueError('fresh declared call output required')
    if type(jobs) is not int or jobs < 1: raise ValueError('declared call jobs must be positive')
    limits = _limits(max_states, max_selectors); roots = _roots(source_roots); runtime = _Runtime(catalog)
    units = _selection(runtime.catalog.fact_store, roots)
    if not units: raise ValueError('source roots select no retained importable source units')
    _durable_mkdir(out); shards = {}
    if jobs == 1:
        for unit in units: shards[unit] = _write_unit(runtime, unit, out, limits, pins)
    else:
        with ProcessPoolExecutor(max_workers=min(jobs, len(units)),
                mp_context=multiprocessing.get_context('spawn'), initializer=_initialize_worker,
                initargs=(str(runtime.catalog.path), encode(runtime.parent), str(out), limits, pins)) as pool:
            for unit, shard in pool.map(_worker, units, chunksize=1): shards[unit] = shard
    runtime.snapshot.validate_parents()
    if pins != _pins(): raise ValueError('declared call producer changed')
    report = dict(schema=SCHEMA, schema_version=1, status='ALL_SELECTED_SOURCE_CALL_DECLARATIONS_PROJECTED',
        catalog=str(runtime.catalog.path), parent=encode(runtime.parent), source_roots=list(roots),
        limits=limits, jobs=jobs, start_method='spawn' if jobs > 1 else 'serial', pins=pins,
        shards=shards, tables=_flat_tables(shards), counts=_totals(shards),
        source_selection_is_not_entry_admission=True, source_calls_are_declarations=True,
        **{name: False for name in NO_PROOF}, seconds=time.monotonic()-started)
    _durable_bytes(out/'result.json', _json(report), replace=False)
    return report


class DeclaredCallStore:
    """Small certified index; load_unit checks material/ABI, read_unit rederives."""
    def __init__(self, path, catalog=None):
        self.path = Path(path).absolute(); self.raw = (self.path/'result.json').read_bytes()
        self.report = r = json.loads(self.raw)
        if (r['schema'], r['schema_version']) != (SCHEMA, 1) or r['pins'] != _pins():
            raise ValueError('declared call producer differs')
        self.runtime = _Runtime(r['catalog'] if catalog is None else catalog)
        self.catalog, self.snapshot = self.runtime.catalog, self.runtime.snapshot
        if str(self.catalog.path) != r['catalog'] or encode(self.runtime.parent) != r['parent']:
            raise ValueError('declared call original catalog differs')
        _limits(**r['limits']); roots = _roots(r['source_roots'])
        if list(roots) != r['source_roots'] or tuple(r['shards']) != _selection(self.catalog.fact_store, roots):
            raise ValueError('declared call source selection differs')
        for unit, shard in r['shards'].items():
            row = self.catalog.fact_store.rows[unit]
            if (shard['path'] != _folder(unit) or shard['source'] != row['path'] or shard['module'] != row['module']
                    or set(shard['tables']) != {'queries', 'symbols'}
                    or any(v['path'] != name+'.jsonl.gz' for name, v in shard['tables'].items())
                    or shard['counts']['calls'] != row['counts']['calls']):
                raise ValueError('declared call shard metadata differs from its original source unit')
        if r['tables'] != _flat_tables(r['shards']) or r['counts'] != _totals(r['shards']):
            raise ValueError('declared call global receipt index or counts differ')
        if (any(r[name] is not False for name in NO_PROOF)
                or r['source_selection_is_not_entry_admission'] is not True or r['source_calls_are_declarations'] is not True):
            raise ValueError('source call declarations cannot grant entry or runtime authority')
        self.validate()

    def validate(self):
        if self.raw != (self.path/'result.json').read_bytes() or self.report['pins'] != _pins():
            raise ValueError('declared call report or rules changed')
        self.snapshot.validate_parents()

    def load_unit(self, unit):
        """Check table receipts, types, original ABI and names; no namespace solve.

        Consumers using this method must report source_relations_rederived=False.
        Namespace semantic acceptance is the responsibility of read_unit or a
        separately certified source graph, not this material-only read.
        """
        self.validate(); self.runtime.clear(); shard = self.report['shards'][unit]; folder = self.path/shard['path']
        if encode(_artifact(folder/'result.json', UNIT_SCHEMA)) != shard['result']:
            raise ValueError('declared call original unit report receipt differs')
        raw = (folder/'result.json').read_bytes(); report = json.loads(raw)
        expected = dict(schema=UNIT_SCHEMA, schema_version=1, unit=unit, parent=self.report['parent'],
            source=shard['source'], module=shard['module'], limits=self.report['limits'], pins=self.report['pins'],
            tables=shard['tables'], counts=shard['counts'], **{name: False for name in NO_PROOF})
        if report != expected: raise ValueError('declared call unit provenance or projection metadata differs')
        queries = tuple(decode(D.DeclaredCallQuery, wire, record_tags=P.PRODUCTION_RECORD_TAGS)
            for wire in _table(folder, shard['tables']['queries']))
        symbols = tuple(decode(D.DeclaredCallSymbolRequest, wire, record_tags=P.PRODUCTION_RECORD_TAGS)
            for wire in _table(folder, shard['tables']['symbols']))
        graph = D.DeclaredCallUnit(unit, queries, symbols); facts = self.catalog.fact_store.load(unit)
        owners = _owners(facts); resolver = self.runtime.resolver
        if len(queries) != len(facts.calls): raise ValueError('declared call table omitted an original source call')
        for ordinal, (query, call) in enumerate(zip(queries, facts.calls)):
            if (query.unit != unit or query.call != resolver.slicer.fact(facts, 'calls', ordinal)
                    or query.callee != source_port(facts, call.callee) or query.owners != owners[ordinal]
                    or not query.reference.states or query.reference.states[0].port != query.callee
                    or query.reference.states[0].selectors):
                raise ValueError('declared call original fact, callee, owners or query root differs')
            size = len(query.reference.states)
            if (any(not 0 <= e.downstream < size or not 0 <= e.upstream < size for e in query.reference.edges)
                    or any(not 0 <= x.state < size for x in (*query.reference.origins, *query.reference.frontiers))):
                raise ValueError('declared namespace reference index lies outside its unit query')
            if (query.formal_frontiers, query.call_result_frontiers) != _cuts(resolver, query.reference):
                raise ValueError('declared call formal or call-result boundary metadata differs')
        if symbols != _symbols(resolver, queries) or _counts(graph) != shard['counts']:
            raise ValueError('declared named requests or source call counts differ')
        self.validate()
        if raw != (folder/'result.json').read_bytes(): raise ValueError('declared call unit report changed')
        return graph

    def read_unit(self, unit):
        graph = self.load_unit(unit)
        expected = project_declared_calls(self.snapshot, unit, resolver=self.runtime.resolver, **self.report['limits'])
        if graph != expected: raise ValueError('declared namespace sources differ from original source facts')
        self.validate()
        return graph


def read_declared_calls(path, *, unit, catalog=None):
    store = DeclaredCallStore(path, catalog)
    return store.report, store.read_unit(unit)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog'); parser.add_argument('--source-root', action='append', default=[])
    parser.add_argument('--out'); parser.add_argument('--read'); parser.add_argument('--unit')
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--max-states', type=int, default=4000); parser.add_argument('--max-selectors', type=int, default=32)
    args = parser.parse_args()
    if args.read:
        if not args.unit: parser.error('--read requires --unit for explicit single-unit semantic verification')
        report, graph = read_declared_calls(args.read, unit=args.unit)
        print(json.dumps(dict(status='DECLARED_SOURCE_UNIT_REDERIVED', unit=graph.unit, counts=_counts(graph))), flush=True)
    else:
        if not args.catalog or not args.source_root or not args.out: parser.error('--catalog, --source-root and --out required')
        report = build_declared_calls(args.catalog, args.out, source_roots=args.source_root, jobs=args.jobs,
            max_states=args.max_states, max_selectors=args.max_selectors)
        print(json.dumps(dict(status=report['status'], counts=report['counts'], seconds=report['seconds'])), flush=True)


if __name__ == '__main__':
    main()
