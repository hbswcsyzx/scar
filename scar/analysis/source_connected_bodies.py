"""Connect guarded source interfaces, shared bodies and downstream queries.

Parent interface indices remain unchanged. Namespace origins describe how a
callable was obtained; the caller's root stack describes its actual arguments.
These two paths must not be substituted for each other.
"""
import argparse
from collections import Counter, defaultdict, deque
from hashlib import sha256
import json
from pathlib import Path
import time

from scar.analysis.source_constructor_members import ConstructorMemberParents, _preload
from scar.analysis.source_namespace_callees import read_namespace_callees, resolve_namespace_callees
from scar.analysis.source_inherited_member_graph import read_inherited_members
from scar.analysis.source_stacked_references import StackedReferenceEngine
from scar.analysis.source_call_context_graph import _function_connections
from scar.analysis.source_constructor_interfaces import project_constructor_interfaces
from scar.analysis.source_graph_material import source_graph_material
from scar.analysis.source_value_flow import project_value_flow, _artifact
from scar.analysis.source_reference_slice import source_port
from scar.analysis.source_world_returns import _table_ref
from scar.analysis.source_symbol_variants import _table
from scar.analysis.normal_output import write_table
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_template_links import _json
from scar.ir.program import source_connected_bodies as B, source_call_contexts as X
from scar.ir.program import source_namespace_callees as N, source_constructor_interfaces as C
from scar.ir.program import source_value_flow as V, source_productions as P
from scar.ir.program import normal_targets as T, declared_contexts as D
from scar.ir.program.source_body_expansion import SharedBodyReference
from scar.ir.record_codec import decode, encode


SCHEMA = 'scar.connected-source-bodies'
NO_PROOF = ('loops_unrolled', 'entry_admission_proven', 'runtime_dispatch_proven',
    'current_content_versions_proven', 'target_executed', 'first_stage_complete')
CLASSES = dict(bodies=V.SourceBodyValueFlow, references=SharedBodyReference,
    roots=B.ConnectedBodyRoot, frontiers=B.ConnectedBodyFrontier,
    interface_scopes=B.ContextualInterfaceScope,
    interfaces=X.CallInterfaceRecord, queries=X.CallContextQuery, functions=X.ContextFunctionConnection,
    namespace_lookups=N.CalleeNamespaceLookup, namespace_anchors=N.CalleeNamespaceAnchor,
    namespace_functions=N.NamespaceFunctionConnection, namespace_frontiers=N.NamespaceCallFrontier,
    namespace_symbols=N.NamespaceSymbolRequest, constructor_sites=C.ConstructorInterfaceSite,
    constructor_steps=C.ConstructorInterfaceStep, constructor_entries=C.ConstructorBodyEntry,
    constructor_frontiers=C.ConstructorInterfaceFrontier)


class ConnectedBodyParents:
    def __init__(self, namespaces, members, *, common=None):
        started = time.monotonic()
        self.namespace_root, self.member_root = Path(namespaces).absolute(), Path(members).absolute()
        header = json.loads((self.namespace_root/'result.json').read_bytes())
        self.common = common if common is not None else ConstructorMemberParents(header['calls'])
        self.namespace_report, self.namespace = read_namespace_callees(self.namespace_root, parents=self.common)
        self.member_report, self.members = read_inherited_members(self.member_root, parents=self.common)
        self.snapshot = self.common.snapshot
        self.bodies = (*self.common.base.bodies, *self.members['bodies'])
        self.references = self.members['references']
        if tuple(r.source_function for r in self.references) != tuple(b.source_function for b in self.bodies):
            raise ValueError('connected body parent registry differs from original shared references')
        self.raw = tuple((root/'result.json').read_bytes() for root in (self.namespace_root, self.member_root))
        self.parents = tuple(_artifact(root/'result.json', report['schema']) for root, report in (
            (self.namespace_root, self.namespace_report), (self.member_root, self.member_report)))
        self.validate(); self.certification_seconds = time.monotonic()-started

    def validate(self):
        from scar.analysis.source_namespace_callees import _pins as namespace_pins
        from scar.analysis.source_inherited_member_graph import _pins as member_pins
        for root, report, raw, pins in zip((self.namespace_root, self.member_root),
                (self.namespace_report, self.member_report), self.raw, (namespace_pins(), member_pins())):
            if raw != (root/'result.json').read_bytes() or report['pins'] != pins:
                raise ValueError('connected body original source graph or rules changed')
            for receipt in report['tables'].values():
                payload = (root/receipt['path']).read_bytes()
                if len(payload) != receipt['bytes'] or sha256(payload).hexdigest() != receipt['sha256']:
                    raise ValueError('connected body original source table changed')
        self.common.validate()


def _body_registry(parents):
    registry = list(parents.bodies); ids = {body.source_function: i for i, body in enumerate(registry)}
    missing = defaultdict(dict)
    for item in parents.namespace['functions']:
        connection = item.connection
        if connection.activation is not T.FunctionActivation.NORMAL: continue
        if connection.source_callable in ids:
            if registry[ids[connection.source_callable]].body != connection.body:
                raise ValueError('source function has inconsistent shared body identity')
        else: missing[connection.body.unit][connection.source_callable] = connection.body
    for unit, bodies in missing.items():
        material = source_graph_material(parents.snapshot.catalog, unit)
        _preload(material, tuple(dict.fromkeys(body.template for body in bodies.values())))
        for point, body in bodies.items():
            ids[point] = len(registry); registry.append(project_value_flow(material, point, body))
        material.validate_parents()
    return tuple(registry), ids


def _link(unit, call, connection, mode):
    return T.CallLink(source_port(unit, call.result), source_port(unit, call.callee),
        connection.source_callable, connection.body, mode, None, connection.parameters, connection.returns,
        connection.conditions, argument_packs=connection.argument_packs,
        projections=connection.projections, binding=connection.binding)


def _entrances(parents, engine, body_ids, max_roots):
    roots = []; frontiers = []; pending = deque(); parent = parents.common.graph
    by_call = defaultdict(list)
    for qi, query in enumerate(parent['queries']): by_call[query.call].append(qi)

    def add(connection, call_unit, call, evidence, outer, kind, parent_query=None,
            context=None, predecessor=None, seen=frozenset(), mode='SOURCE_FUNCTION'):
        if connection.activation is not T.FunctionActivation.NORMAL:
            frontiers.append(B.ConnectedBodyFrontier(evidence, 'DEFERRED_CREATION_IS_NOT_BODY_ENTRY')); return
        if len(roots) >= max_roots:
            frontiers.append(B.ConnectedBodyFrontier(evidence, 'CONNECTED_BODY_ROOT_BUDGET_FRONTIER')); return
        # Constructor mode excludes discarded init data from ordinary returns;
        # new results also remain inside the original construction protocol.
        incoming = engine.admit_contextual(evidence, _link(call_unit, call, connection, mode), outer)
        index = len(roots)
        roots.append(B.ConnectedBodyRoot(body_ids[connection.source_callable], incoming, tuple(outer),
            evidence, kind, parent_query, context, predecessor))
        if context is not None: pending.append((index, seen | {context}))

    for ordinal, item in enumerate(parents.namespace['functions']):
        anchor = parents.namespace['anchors'][item.anchor]; query = parent['queries'][anchor.query]
        unit = engine.slicer.unit(query.callee.unit)[0]; call = unit.calls[int(query.call.locator.rsplit('/', 1)[1])]
        # The origin may be inside a factory return. Its stack is provenance,
        # not the frame in which this source call's actual arguments are read.
        outer = query.reference.states[0].interfaces
        evidence = _table_ref(parents.namespace_root, parents.namespace_report['tables']['functions'],
            'scar.namespace-function-connections', ordinal)
        add(item.connection, unit, call, evidence, outer, B.EntranceKind.NAMESPACE_FUNCTION, anchor.query)
    for entry in parents.members['entries']:
        ordinal = int(entry.parent.locator.rsplit('/', 1)[1])
        constructor = parents.common.constructors.entries[ordinal]
        if entry.connection != constructor.connection:
            raise ValueError('connected constructor entrance changed its original protocol interface')
        step = parents.common.constructors.steps[constructor.step]
        site = parents.common.constructors.sites[step.site]
        unit = engine.slicer.unit(site.unit)[0]; callers = by_call.get(site.record.fact, ())
        if not callers:
            add(entry.connection, unit, site.record.call, entry.parent, (), B.EntranceKind.CONSTRUCTOR,
                context=entry.target, mode=step.link.stage.value)
            frontiers.append(B.ConnectedBodyFrontier(entry.parent, 'OUTER_CONSTRUCTOR_CALLER_CONTEXT_NOT_SELECTED'))
        for qi in callers:
            add(entry.connection, unit, site.record.call, entry.parent,
                parent['queries'][qi].reference.states[0].interfaces, B.EntranceKind.CONSTRUCTOR, qi, entry.target,
                mode=step.link.stage.value)
    edges = defaultdict(list)
    for ordinal, edge in enumerate(parents.members['edges']): edges[edge.caller].append((ordinal, edge))
    while pending:
        predecessor, seen = pending.popleft(); root = roots[predecessor]
        for ordinal, edge in edges[root.declared_context]:
            evidence = _table_ref(parents.member_root, parents.member_report['tables']['edges'],
                'scar.inherited-context-edges', ordinal)
            if edge.target in seen:
                frontiers.append(B.ConnectedBodyFrontier(evidence, 'RECURSIVE_BODY_PATH_SHARED_NOT_UNROLLED', predecessor)); continue
            context = parents.members['contexts'][edge.caller]
            unit = engine.slicer.unit(context.body.unit)[0]
            call_ordinal = int(edge.call.locator.rsplit('/', 1)[1]); call = unit.calls[call_ordinal]
            if edge.call != engine.slicer.fact(unit, 'calls', call_ordinal):
                raise ValueError('connected member source call differs from the original context edge')
            mode = 'SOURCE_CLASS_METHOD' if edge.descriptor.kind is D.DescriptorKind.CLASSMETHOD else (
                'SOURCE_BOUND_METHOD' if edge.descriptor.kind is D.DescriptorKind.FUNCTION
                and edge.receiver.kind is D.ClassValueKind.INSTANCE else 'SOURCE_FUNCTION')
            add(edge.connection, unit, call, evidence, (*root.outer, root.incoming),
                B.EntranceKind.DECLARED_MEMBER, context=edge.target, predecessor=predecessor, seen=seen, mode=mode)
    return tuple(roots), tuple(frontiers)


def derive_connected_bodies(parents, limits):
    bodies, body_ids = _body_registry(parents); engine = StackedReferenceEngine(parents.snapshot)
    for ordinal, record in enumerate(parents.common.graph['interfaces']):
        if engine.admit(record.evidence, record.link) != ordinal:
            raise ValueError('parent selected interface indices changed')
        if record.evidence.artifact.schema == 'scar.context.calls': engine.indexed.add(record.link.result.unit)
    roots, frontiers = _entrances(parents, engine, body_ids, limits['max_roots'])
    # Batch all newly entered units into one original historical table scan.
    engine.index({bodies[root.body].body.unit for root in roots})
    requests = []; metadata = []; sites = []
    for ri, root in enumerate(roots):
        body = bodies[root.body]; unit = engine.slicer.unit(body.body.unit)[0]
        for record in body.calls:
            point = source_port(unit, record.call.callee)
            requests.append((root.incoming, point, root.outer)); metadata.append((ri, root, record.fact, point))
            sites.append((body.body.unit, record))
    references = engine.solve_stacks(requests, max_states=limits['max_states'], max_depth=limits['max_depth'])
    queries = tuple(X.CallContextQuery(root.incoming, fact, point, reference, ri)
        for (ri, root, fact, point), reference in zip(metadata, references))
    functions = _function_connections(engine, queries, sites)
    namespaces = resolve_namespace_callees(parents.snapshot, queries)
    unique = {}
    for body in bodies:
        for record in body.calls: unique.setdefault(record.fact, (body.body.unit, record))
    constructors = project_constructor_interfaces(parents.snapshot, tuple(unique.values()))
    parents.validate()
    return bodies, dict(roots=roots, frontiers=frontiers, interfaces=tuple(engine.interfaces),
        interface_scopes=tuple(B.ContextualInterfaceScope(incoming, outer) for incoming, outer in engine.scopes),
        queries=queries, functions=functions,
        **{'namespace_'+name: rows for name, rows in namespaces.items()},
        **{'constructor_'+name: getattr(constructors, name) for name in ('sites', 'steps', 'entries', 'frontiers')})


def _counts(bodies, graph, old_count):
    new = bodies[old_count:]
    return dict(shared_bodies=len(bodies), reused_parent_bodies=old_count, new_bodies=len(new),
        new_operations=sum(len(b.operations) for b in new), new_edges=sum(len(b.edges) for b in new),
        new_calls=sum(len(b.calls) for b in new), roots=len(graph['roots']),
        root_kinds=dict(Counter(r.kind.value for r in graph['roots'])),
        roots_with_outer_context=sum(bool(r.outer) for r in graph['roots']),
        max_incoming_stack=max((len(r.outer)+1 for r in graph['roots']), default=0),
        entrance_frontiers=dict(Counter(f.reason for f in graph['frontiers'])),
        interfaces=len(graph['interfaces']), queries=len(graph['queries']),
        derived_interface_scopes=len(graph['interface_scopes']),
        reference_states=sum(len(q.reference.states) for q in graph['queries']),
        reference_edges=sum(len(q.reference.edges) for q in graph['queries']),
        reference_frontiers=dict(Counter(f.reason for q in graph['queries'] for f in q.reference.frontiers)),
        source_function_connections=len(graph['functions']),
        source_functions=len({f.connection.source_callable for f in graph['functions']}),
        namespace_function_connections=len(graph['namespace_functions']),
        namespace_functions=len({f.connection.source_callable for f in graph['namespace_functions']}),
        namespace_symbols=len(graph['namespace_symbols']), constructor_entries=len(graph['constructor_entries']))


def _pins():
    from scar.analysis import source_call_contexts, source_namespace_callees, source_constructor_members, source_stacked_references
    from scar.analysis import source_graph_material, source_value_flow, source_constructor_interfaces
    return {name: sha256(Path(path).read_bytes()).hexdigest() for name, path in (
        ('producer', __file__), ('types', B.__file__), ('contexts', source_call_contexts.__file__),
        ('stacked_contexts', source_stacked_references.__file__),
        ('namespaces', source_namespace_callees.__file__), ('members', source_constructor_members.__file__),
        ('materials', source_graph_material.__file__), ('values', source_value_flow.__file__),
        ('constructors', source_constructor_interfaces.__file__))}


def _parent(namespaces, members, parents):
    parents = parents if parents is not None else ConnectedBodyParents(namespaces, members)
    if (parents.namespace_root, parents.member_root) != (Path(namespaces).absolute(), Path(members).absolute()):
        raise ValueError('connected source body parents differ')
    parents.validate(); return parents


def build_connected_bodies(namespaces, members, out, *, parents=None, max_roots=256, max_states=4000, max_depth=24):
    started = time.monotonic(); pins = _pins(); out = Path(out).absolute()
    if out.exists(): raise ValueError('fresh connected body output required')
    limits = dict(max_roots=max_roots, max_states=max_states, max_depth=max_depth)
    if any(type(n) is not int or n < 1 for n in limits.values()): raise ValueError('positive connected query limits required')
    parents = _parent(namespaces, members, parents)
    bodies, graph = derive_connected_bodies(parents, limits); old_count = len(parents.bodies)
    if pins != _pins(): raise ValueError('connected source body rules changed')
    _durable_mkdir(out); body_table = write_table(out/'bodies.jsonl.gz', bodies[old_count:])
    references = (*parents.references, *(SharedBodyReference(body.source_function,
        _table_ref(out, body_table, 'scar.source-value-flow-bodies', i)) for i, body in enumerate(bodies[old_count:])))
    tables = dict(bodies=body_table, references=write_table(out/'references.jsonl.gz', references),
        **{name: write_table(out/(name+'.jsonl.gz'), rows) for name, rows in graph.items()})
    report = dict(schema=SCHEMA, schema_version=1, status='SHARED_BODIES_WITH_MATCHED_OUTER_CALL_CONTEXTS',
        namespaces=str(parents.namespace_root), members=str(parents.member_root),
        parents=[encode(p) for p in parents.parents], catalog=str(parents.snapshot.catalog.path),
        relations=str(parents.snapshot.path), pins=pins, limits=limits, tables=tables,
        counts=_counts(bodies, graph, old_count), caller_stacks_retained=True,
        derived_return_contexts_matched=True,
        **{name: False for name in NO_PROOF}, seconds=time.monotonic()-started)
    _durable_bytes(out/'result.json', _json(report), replace=False); return report


def read_connected_bodies(path, *, parents=None):
    path = Path(path).absolute(); raw = (path/'result.json').read_bytes(); report = json.loads(raw)
    if (report['schema'], report['schema_version']) != (SCHEMA, 1) or report['pins'] != _pins():
        raise ValueError('connected body producer differs')
    parents = _parent(report['namespaces'], report['members'], parents)
    if report['parents'] != [encode(p) for p in parents.parents]: raise ValueError('connected body source parents differ')
    if (report['catalog'], report['relations']) != (str(parents.snapshot.catalog.path), str(parents.snapshot.path)):
        raise ValueError('connected body original catalog or relation snapshot differs')
    rows = {name: tuple(decode(cls, row, record_tags=P.PRODUCTION_RECORD_TAGS)
        for row in _table(path, report['tables'][name])) for name, cls in CLASSES.items()}
    bodies = (*parents.bodies, *rows['bodies']); old_count = len(parents.bodies)
    expected = (*parents.references, *(SharedBodyReference(body.source_function,
        _table_ref(path, report['tables']['bodies'], 'scar.source-value-flow-bodies', i)) for i, body in enumerate(rows['bodies'])))
    graph = {name: value for name, value in rows.items() if name not in ('bodies', 'references')}
    if (rows['references'] != expected or (bodies, graph) != derive_connected_bodies(parents, report['limits'])
            or _counts(bodies, graph, old_count) != report['counts']):
        raise ValueError('connected body roots, original interfaces, outer stacks or queries differ')
    if (report['caller_stacks_retained'] is not True or report['derived_return_contexts_matched'] is not True
            or any(report[name] is not False for name in NO_PROOF)):
        raise ValueError('connected source body queries cannot grant runtime or entry authority')
    parents.validate()
    if raw != (path/'result.json').read_bytes(): raise ValueError('connected body graph changed')
    return report, rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--namespaces'); parser.add_argument('--members'); parser.add_argument('--out'); parser.add_argument('--read')
    args = parser.parse_args()
    if args.read: report, _ = read_connected_bodies(args.read)
    else:
        if not args.namespaces or not args.members or not args.out: parser.error('--namespaces, --members, --out required')
        report = build_connected_bodies(args.namespaces, args.members, args.out)
    print(json.dumps(dict(status=report['status'], counts=report['counts'], seconds=report['seconds'])), flush=True)


if __name__ == '__main__': main()
