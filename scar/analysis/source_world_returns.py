"""Connect shared post-call state graphs through original source interfaces.

The selected declared context is followed before consulting older may-call
alternatives. Normal data and world returns remain distinct. A reference is
carried only under its original source path conditions; no function name,
field name, or apparent copy gives object/content equality.
"""
import argparse
from collections import defaultdict, deque, Counter
from hashlib import sha256
import json
from pathlib import Path
import time
import sys

from scar.analysis.source_world_flow import project_world_flow
from scar.analysis.source_relation_snapshot import RelationSnapshot
from scar.analysis.source_reference_slice import ReferenceSlicer, source_port
from scar.analysis.source_address_paths import AddressResolver
from scar.analysis.source_world_return_parents import CertifiedWorldParents
from scar.analysis.normal_output import write_table
from scar.analysis.source_symbol_variants import _table
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_template_links import _json
from scar.ir.program import world_returns as R, normal_targets as T, normal_links as F, source_productions as P
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.record_codec import encode, decode


def _artifact(path, schema):
    path = Path(path).absolute(); raw = path.read_bytes()
    return ProviderArtifact(str(path), sha256(raw).hexdigest(), len(raw), schema)


def _table_ref(root, receipt, schema, ordinal):
    return ProviderFactReference(ProviderArtifact(str(Path(root)/receipt['path']), receipt['sha256'],
        receipt['bytes'], schema), '#/records/'+str(ordinal))


def _caller_material(catalog, unit):
    # The common reader's receipt guards import this module, so defer loading
    # the adapter until the original world-return declarations are available.
    from scar.analysis.source_graph_material import source_graph_material
    return source_graph_material(catalog, unit)


class ReturnInterfaces:
    def __init__(self, snapshot, declared_root, declared_report, graph, fields_root, fields_report, queries):
        self.snapshot = snapshot; self.slicer = ReferenceSlicer(snapshot); self.graph = graph
        self.declared_root = Path(declared_root); self.report = declared_report
        self.fields_root = Path(fields_root); self.fields_report = fields_report; self.queries = queries
        self.call_cache = defaultdict(list); self.indexed_call_units = set(); self.functions = {}

    def function(self, point):
        if point not in self.functions:
            unit, local = self.slicer.local(point)
            fn = next(f for f in unit.functions if f.value == local)
            self.functions[point] = unit, fn
        return self.functions[point]

    def source_call(self, evidence):
        # Declared edges retain original unit-fact references, not table call IDs.
        identity = next((u for u in self.slicer.store.rows if self.slicer.fact(
            type('Unit', (), {'unit': u})(), 'calls', 0).artifact.uri == evidence.artifact.uri), None)
        if identity is None: raise ValueError('return edge does not cite an original source unit')
        unit, *_ = self.slicer.unit(identity); index = int(evidence.locator.rsplit('/', 1)[1])
        if self.slicer.fact(unit, 'calls', index) != evidence: raise ValueError('source return call evidence differs')
        return unit, index, unit.calls[index]

    def caller(self, unit, index):
        owners = {group.owner for group in unit.scope_groups for span in group.tables
            if span.table is F.FactTable.CALLS and span.start <= index < span.stop}
        candidates = [f for f in unit.functions if f.body_scope is not None and f.body_scope.owner in owners]
        return candidates[0] if len(candidates) == 1 else None

    def parents(self, function, context):
        if context is not None:
            for ordinal, edge in enumerate(self.graph.edges):
                if edge.target != context or edge.connection.source_callable != function: continue
                unit, index, call = self.source_call(edge.call)
                yield unit, index, call, edge.connection, edge.call, _table_ref(self.declared_root,
                    self.report['tables']['edges'], 'scar.declared-context-edges', ordinal), edge.caller
            for entry in self.graph.entries:
                if entry.target != context or entry.connection.source_callable != function: continue
                found = None
                for shard, query in zip(self.fields_report['shards'], self.queries):
                    path = str(self.fields_root/shard['folder']/shard['table']['path'])
                    if path != entry.parent.artifact.uri: continue
                    ordinal = int(entry.parent.locator.rsplit('/', 1)[1])
                    method = query.methods[ordinal]
                    if method.connection == entry.connection: found = method
                if found is None: raise ValueError('declared root interface lost its parent field query')
                unit, index, call = self.source_call(found.call)
                yield unit, index, call, entry.connection, found.call, entry.parent, None
            return
        if function.unit not in self.indexed_call_units:
            selected = self.snapshot.rows('calls', lambda w:w.get('source_callable') is not None
                and w['source_callable']['unit'] == function.unit, T.CallLink)
            for ordinal, link, evidence in selected:
                if link.mode in ('SOURCE_INIT', 'SOURCE_NEW', 'SOURCE_CONSTRUCTION') or link.body is None: continue
                unit, *_ = self.slicer.unit(link.result.unit)
                matches = [(i, c) for i, c in enumerate(unit.calls)
                    if source_port(unit, c.result) == link.result and source_port(unit, c.callee) == link.callee]
                for index, call in matches:
                    connection = T.FunctionConnection(link.source_callable, link.body, T.FunctionActivation.NORMAL,
                        link.parameters, link.returns, link.conditions, link.argument_packs, link.projections, link.binding)
                    self.call_cache[link.source_callable].append((unit, index, call, connection,
                        self.slicer.fact(unit, 'calls', index), evidence, None))
            self.indexed_call_units.add(function.unit)
        yield from self.call_cache.get(function, ())


def compose_returns(interfaces, initial, *, max_nodes=32, max_edges=128, max_templates=4000):
    nodes = []; edges = []; roots = []; frontiers = []; ids = {}; pending = deque(); materials = {}
    def intern(function, context, reference, flow):
        key = function, context, reference, flow.anchor
        if key not in ids:
            if len(nodes) >= max_nodes: return None
            ids[key] = len(nodes); nodes.append(R.WorldReturnNode(function, context, reference, flow)); pending.append(ids[key])
        return ids[key]
    for function, context, reference, flow in initial:
        index = intern(function, context, reference, flow)
        if index is None: raise ValueError('world return roots exceed budget')
        roots.append(index)
    while pending:
        index = pending.popleft(); node = nodes[index]
        unit, fn = interfaces.function(node.source_function)
        if not node.flow.anchor_reaches_exit:
            frontiers.append(R.WorldReturnFrontier(index, 'CALLEE_POST_ANCHOR_EXIT_PATH_UNRESOLVED')); continue
        if fn.environment.kind is not P.DeferredBodyKind.FUNCTION:
            frontiers.append(R.WorldReturnFrontier(index, 'DEFERRED_NORMAL_RETURN_NOT_ORDINARY_BODY_RETURN')); continue
        candidates = tuple(interfaces.parents(node.source_function, node.declared_context))
        if not candidates: frontiers.append(R.WorldReturnFrontier(index, 'CALLER_RETURN_INTERFACE_UNRESOLVED'))
        for caller_unit, call_index, call, connection, call_ref, witness, caller_context in candidates:
            if len(edges) >= max_edges:
                frontiers.append(R.WorldReturnFrontier(index, 'RETURN_EDGE_BUDGET_FRONTIER')); break
            caller_fn = interfaces.caller(caller_unit, call_index)
            if caller_fn is None:
                frontiers.append(R.WorldReturnFrontier(index, 'CALLER_IS_MODULE_OR_UNRESOLVED_SOURCE_SCOPE')); continue
            if caller_fn.return_world is None or fn.return_world is None:
                frontiers.append(R.WorldReturnFrontier(index, 'NORMAL_RETURN_WORLD_NOT_DECLARED')); continue
            exit = source_port(unit, fn.return_world); after = source_port(caller_unit, call.result_world)
            state = (exit, after)
            formal_world = source_port(unit, fn.formals[-1])
            if (state not in connection.returns or connection.body != node.flow.caller_body
                    or not any(r.kind is T.RouteKind.STATE and r.formal == formal_world
                        and r.actuals == (source_port(caller_unit, call.world),) for r in connection.parameters)):
                frontiers.append(R.WorldReturnFrontier(index, 'SOURCE_WORLD_RETURN_OR_INPUT_ROUTE_UNRESOLVED')); continue
            data = None
            if fn.returns is not None:
                candidate = (source_port(unit, fn.returns), source_port(caller_unit, call.result))
                if candidate in connection.returns: data = candidate
            paths = ()
            if data is not None and node.tracked_reference is not None:
                paths = tuple(p for p in AddressResolver(interfaces.slicer.store, unit, fn.body_scope.owner).paths(
                    fn.returns, max_depth=128) if p.root == node.tracked_reference and not p.selectors and p.frontier is None)
            reference = data[1] if paths else None
            key = caller_unit.unit
            node_key = source_port(caller_unit, caller_fn.value), caller_context, reference, after
            if node_key in ids:
                target = ids[node_key]
                caller_flow = nodes[target].flow
            elif len(nodes) >= max_nodes:
                frontiers.append(R.WorldReturnFrontier(index, 'RETURN_NODE_BUDGET_FRONTIER')); continue
            else:
                target = None
            if target is None:
                if key not in materials: materials[key] = _caller_material(interfaces.snapshot.catalog, key)
                body = T.Body(key, caller_fn.template, caller_fn.body)
                caller_flow = project_world_flow(materials[key], body, witness, after,
                    source_port(caller_unit, caller_fn.return_world), max_templates=max_templates)
                target = intern(source_port(caller_unit, caller_fn.value), caller_context, reference, caller_flow)
            if target is None:
                frontiers.append(R.WorldReturnFrontier(index, 'RETURN_NODE_BUDGET_FRONTIER')); continue
            conditions = (*connection.conditions, 'SAME_SOURCE_CALL_NORMAL_COMPLETION_SELECTED',
                'WORLD_RETURN_IS_NOT_CONTENT_PRESERVATION', 'REFERENCE_RETURN_REQUIRES_ALL_RECORDED_PATH_GUARDS')
            edges.append(R.WorldReturnEdge(index, target, call_ref, witness, connection, state, data, paths, bool(paths), conditions))
            if node.tracked_reference is not None and not paths:
                frontiers.append(R.WorldReturnFrontier(index, 'TRACKED_REFERENCE_RETURN_PATH_UNRESOLVED'))
        print(json.dumps(dict(phase='WORLD_RETURN_CONNECTION',nodes=len(nodes),edges=len(edges),
            pending=len(pending),frontiers=len(frontiers))),file=sys.stderr,flush=True)
    interfaces.snapshot.validate_parents()
    return R.WorldReturnGraph(tuple(roots), tuple(nodes), tuple(edges), tuple(frontiers))


def _artifact(path, schema):
    path = Path(path).absolute(); raw = path.read_bytes()
    return ProviderArtifact(str(path), sha256(raw).hexdigest(), len(raw), schema)


def _pins():
    from scar.analysis import source_world_flow, source_address_paths, source_world_material, source_graph_material, source_world_return_parents
    return {name: sha256(Path(path).read_bytes()).hexdigest() for name, path in (
        ('producer', __file__), ('types', R.__file__), ('world_flow', source_world_flow.__file__),
        ('addresses', source_address_paths.__file__), ('material', source_world_material.__file__),
        ('material_adapter', source_graph_material.__file__),
        ('parent_reader', source_world_return_parents.__file__))}


def _derive(world, limits):
    parents = CertifiedWorldParents(world)
    flows = parents.flows; jr = parents.join_report; joins = parents.joins
    cr = parents.context_report; graph = parents.graph
    fr = parents.field_report; queries = parents.queries
    snapshot = RelationSnapshot(fr['relations'], fr['catalog'])
    projections = parents.bindings
    print(json.dumps(dict(phase='WORLD_RETURN_PARENTS_CERTIFIED',guards=parents.validate())),file=sys.stderr,flush=True)
    interfaces = ReturnInterfaces(snapshot, jr['contexts'], cr, graph, cr['parent'], fr, queries)
    initial = []
    for flow in flows:
        ordinal = int(flow.projection.locator.rsplit('/', 1)[1]); binding = projections[ordinal]
        unit = snapshot.fact_store.load(flow.unit)
        fn = next(f for f in unit.functions if f.body_scope == binding.caller)
        for join in joins:
            if join.projection.locator != flow.projection.locator: continue
            edge = graph.edges[int(join.edge.locator.rsplit('/', 1)[1])]
            roots = AddressResolver(snapshot.fact_store, unit, fn.body_scope.owner).paths(
                interfaces.slicer.local(binding.receiver)[1], max_depth=128)
            references = tuple(dict.fromkeys(p.root for p in roots if not p.selectors and p.frontier is None)) or (None,)
            initial.extend((source_port(unit, fn.value), edge.caller, reference, flow) for reference in references)
    result = compose_returns(interfaces, initial, **limits)
    parents.validate()
    return result


def _counts(graph):
    return dict(nodes=len(graph.nodes), edges=len(graph.edges), roots=len(graph.roots), frontiers=len(graph.frontiers),
        reference_returns=sum(e.reference_forwarded for e in graph.edges),
        anchored_exits=sum(n.flow.anchor_reaches_exit for n in graph.nodes),
        frontier_reasons=dict(Counter(f.reason for f in graph.frontiers)))


def build_world_returns(world, out, *, max_nodes=16, max_edges=32, max_templates=4000):
    started = time.monotonic(); world = Path(world).absolute(); out = Path(out).absolute(); pins = _pins()
    if out.exists(): raise ValueError('fresh world return graph required')
    parent = _artifact(world/'result.json', 'scar.source-world-flow')
    limits = dict(max_nodes=max_nodes, max_edges=max_edges, max_templates=max_templates)
    graph = _derive(world, limits)
    if pins != _pins() or parent != _artifact(world/'result.json', parent.schema): raise ValueError('world return rules or parent changed')
    _durable_mkdir(out); tables = {name: write_table(out/(name+'.jsonl.gz'), getattr(graph, name))
        for name in ('roots', 'nodes', 'edges', 'frontiers')}
    r = dict(schema='scar.world-return-graph', schema_version=1, status='CONDITIONAL_INTERPROCEDURAL_WORLD_RETURNS',
        pins=pins, world=str(world), parent=encode(parent), limits=limits, tables=tables, counts=_counts(graph),
        semantics=graph.semantics, content_versions_proven=False, runtime_identity_proven=False,
        target_executed=False, first_stage_complete=False, seconds=time.monotonic()-started)
    _durable_bytes(out/'result.json', _json(r), replace=False); return r


def read_world_returns(path):
    path = Path(path).absolute(); raw = (path/'result.json').read_bytes(); r = json.loads(raw)
    if (r['schema'], r['schema_version']) != ('scar.world-return-graph', 1) or r['pins'] != _pins(): raise ValueError('world return producer differs')
    if r['parent'] != encode(_artifact(Path(r['world'])/'result.json', 'scar.source-world-flow')): raise ValueError('world return parent differs')
    types = dict(roots=int, nodes=R.WorldReturnNode, edges=R.WorldReturnEdge, frontiers=R.WorldReturnFrontier)
    values = {name: tuple(decode(cls, w, record_tags=P.PRODUCTION_RECORD_TAGS)
        for w in _table(path, r['tables'][name])) for name, cls in types.items()}
    graph = R.WorldReturnGraph(**values)
    if graph != _derive(r['world'], r['limits']) or _counts(graph) != r['counts'] or graph.semantics != r['semantics']: raise ValueError('world return routes/reference witnesses differ')
    if any(r[k] is not False for k in ('content_versions_proven', 'runtime_identity_proven', 'target_executed', 'first_stage_complete')): raise ValueError('world returns cannot prove current content')
    if (path/'result.json').read_bytes() != raw: raise ValueError('world return graph changed during validation')
    return r, graph


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--world'); p.add_argument('--out'); p.add_argument('--read')
    p.add_argument('--max-nodes', type=int, default=16); p.add_argument('--max-edges', type=int, default=32); a = p.parse_args()
    if a.read: r, _ = read_world_returns(a.read)
    else:
        if not a.world or not a.out: p.error('--world --out required')
        r = build_world_returns(a.world, a.out, max_nodes=a.max_nodes, max_edges=a.max_edges)
    print(json.dumps(dict(status=r['status'], counts=r['counts'], seconds=r['seconds'])), flush=True)


if __name__ == '__main__': main()
