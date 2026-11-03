"""Conditional module bindings reached through the shared receiver graph.

An import result supplies a guarded source-module interpretation. The snapshot
of its original normal initializer return is not the contents at a later read;
that preservation premise retains all participating worlds and known writers.
"""
from __future__ import annotations

import ast
from collections import Counter, OrderedDict, defaultdict, deque
from dataclasses import dataclass, replace

from scar.analysis.attribute_selector import derive_attribute_selector, prepare_attribute_selector_source
from scar.analysis.contextual_module_imports import ContextualImportSources, ContextualModuleImport
from scar.analysis.contextual_receiver_sources import walk_reference_sources
from scar.analysis.source_attribute_lookup import _source_lookup
from scar.analysis.static_namespace import NamespaceBindingWitness
from scar.ir.program.attribute_lookups import StaticAttributeSelector
from scar.ir.program.dependencies import (
    DependencyCondition as Condition, DependencyEdge as Edge, DependencyEvidence as Evidence,
    DependencyFrontier as Frontier, DependencyKind as K, DependencyMeaning as M,
    DependencyNeighborhood as Neighborhood, DependencyPoint as Point,
    DependencyStrength as Strength, GraphNamespace,
)
from scar.ir.program.ids import OperationID, UseID, ValueID
from scar.ir.program.model import LiteralOrigin, ReferenceValue, StateVersionValue, TerminatorKind
from scar.ir.program.source_call_bindings import SourceBodyNamespace
from scar.ir.program.static_calls import StaticAttributeAccess, StaticImportFromRead
from scar.ir.program.structured import ControlEdgeReference


def _need(ok, detail):
    if not ok:
        raise ValueError('contextual module binding: ' + detail)


@dataclass(frozen=True, slots=True)
class ContextualModuleBindingProjection:
    read: StaticAttributeAccess | StaticImportFromRead
    key: str
    selector: StaticAttributeSelector | None
    import_source: ContextualModuleImport
    receiver_path: tuple[Edge, ...]
    source_module: SourceBodyNamespace
    snapshot_operation: OperationID
    snapshot_world: UseID
    namespace_binding: NamespaceBindingWitness
    consumer_path: tuple[ControlEdgeReference, ...]
    consumer_operations: tuple[OperationID, ...]
    known_writes: tuple[Point, ...]
    source: Point
    target: Point
    conditions: tuple[Condition, ...]
    evidence: tuple[Evidence, ...]

    def __post_init__(self):
        _need(type(self.read) in (StaticAttributeAccess, StaticImportFromRead), 'original field-read required')
        for value, kind in ((self.import_source, ContextualModuleImport),
                (self.source_module, SourceBodyNamespace), (self.snapshot_operation, OperationID),
                (self.snapshot_world, UseID), (self.namespace_binding, NamespaceBindingWitness),
                (self.source, Point), (self.target, Point)):
            _need(type(value) is kind, 'original typed ' + kind.__name__ + ' required')
            value.__post_init__()
        _need(type(self.key) is str and bool(self.key), 'known actual lookup key required')
        if type(self.read) is StaticAttributeAccess:
            _need(type(self.selector) is StaticAttributeSelector and self.selector.lookup_name == self.key,
                'Attribute lookup key must come from its original lexical selector')
        else:
            _need(self.selector is None and self.key == self.read.field, 'FROM key changed its literal selector')
        for rows, kind in ((self.receiver_path, Edge), (self.consumer_path, ControlEdgeReference),
                (self.consumer_operations, OperationID), (self.known_writes, Point),
                (self.conditions, Condition), (self.evidence, Evidence)):
            _need(type(rows) is tuple and all(type(row) is kind for row in rows),
                'immutable original path/condition/evidence records required')
        binding = self.namespace_binding
        _need(self.source_module == self.import_source.module
            and self.source.namespace == GraphNamespace.from_source(self.source_module)
            and self.source.context is None and self.source.node == binding.write.payload
            and self.target.namespace == GraphNamespace.from_source(self.read.body)
            and self.target.node == self.read.result
            and (binding.query_operation, binding.query_world, binding.query_owner, binding.key) ==
                (self.snapshot_operation, self.snapshot_world, self.import_source.globals_namespace, self.key)
            and binding.equivalent_owners == tuple(dict.fromkeys((self.import_source.locals_namespace,
                self.import_source.globals_namespace))), 'snapshot/payload/read changed original endpoints')
        receiver = Point(self.target.namespace, self.read.receiver, self.target.context)
        _need(bool(self.receiver_path) and self.receiver_path[0].source == self.import_source.origin
            and self.receiver_path[-1].target == receiver, 'import origin must reach the actual receiver Use')
        cursor, seen = self.import_source.origin, {self.import_source.origin}
        for edge in self.receiver_path:
            _need(edge.source == cursor and edge.target not in seen, 'receiver path is disconnected or self-seeding')
            _need(all(condition in self.conditions for condition in edge.conditions)
                and all(item in self.evidence for item in edge.evidence), 'receiver path evidence was dropped')
            cursor = edge.target; seen.add(cursor)
        _need(bool(self.evidence) and all(condition in self.conditions for condition in self.import_source.conditions)
            and all(item in self.evidence for item in self.import_source.evidence), 'import conditions/evidence were dropped')

    def dependency_edge(self):
        return Edge(self.source, self.target, K.STATE_VALUE, M.REFERENCE,
            self.evidence, self.conditions, Strength.MAY)


class ContextualModuleBindingProvider:
    relation_kinds = frozenset((K.STATE_VALUE,))

    def __init__(self, resolver):
        self.resolver = resolver
        self.imports = ContextualImportSources(resolver)
        self._active = set()
        self._known = OrderedDict()
        self._counts = Counter()
        self._last = None

    def _read(self, point):
        if (type(point) is not Point or type(point.node) is not ValueID
                or point.namespace.source_body is None):
            return None
        body = self.resolver._body(point.namespace)
        if type(body.index.values.get(point.node)) is not ReferenceValue:
            return None
        facts = self.resolver.modules._index(body)
        read = facts.reads.get(point.node)
        return (body, facts, read) if type(read) in (StaticAttributeAccess, StaticImportFromRead) else None

    def _key(self, body, read):
        if type(read) is StaticImportFromRead:
            value = body.index.use_site(read.key).use.value
            origin = body.index.values[value].origin
            _need(type(origin) is LiteralOrigin and origin.value == read.field,
                'FROM member key is not its actual original string literal')
            return read.field, None
        context = body.context
        saved = getattr(context, '_contextual_module_selector_inputs', None)
        if saved is None or saved[0] is not context.tree or saved[1] is not context.semantic:
            text = context.docs['source']['text']
            original = _source_lookup(context.semantic, body.metadata.source.path, body.metadata.source.fingerprint)
            facts = prepare_attribute_selector_source(context.tree, text, body.metadata.source.path)
            nodes = {}
            for node in ast.walk(context.tree):
                if type(node) is ast.Attribute:
                    source = original(node)
                    if source is not None:
                        _need(source not in nodes, 'ambiguous original Attribute source')
                        nodes[source] = node
            saved = context.tree, context.semantic, text, original, facts, nodes
            context._contextual_module_selector_inputs = saved
        node = saved[5].get(read.source)
        _need(node is not None, 'Attribute read lost its exact original source node')
        selector = derive_attribute_selector(node, source_tree=context.tree, source=read.source,
            source_text=saved[2], source_for_node=saved[3], source_facts=saved[4])
        return selector.lookup_name, selector

    def _receiver_paths(self, walk, origin):
        by_target = defaultdict(list)
        for edge in walk.edges:
            by_target[edge.target].append(edge)
        root, = walk.roots
        pending = deque(((root, (), frozenset((root,))),))
        steps = 0
        while pending:
            self.resolver.owner._check()
            point, reverse, ancestors = pending.popleft(); steps += 1
            if steps > self.resolver.owner.budget.max_resolution_steps:
                raise OverflowError('module receiver-path reconstruction budget exhausted')
            if point == origin:
                yield tuple(reversed(reverse))
                continue
            for edge in by_target.get(point, ()):
                if edge.source not in ancestors:
                    pending.append((edge.source, (*reverse, edge), ancestors | {edge.source}))

    def _snapshots(self, module):
        overlay = module.module
        _need(overlay is not None, 'import source must retain its actual MODULE overlay')
        partial = (getattr(overlay, 'remaining', None) is not None
            or getattr(overlay, 'unexpanded_body', None) is not None
            or any('REQUIRED_EXPANSION' in str(getattr(row.kind, 'value', row.kind))
                   for row in overlay.frontiers))
        if partial:
            return None
        dependencies = self.resolver.owner._namespace_for(module)
        snapshots = []
        for operation in module.graph.operations:
            if (operation.terminator is not None and operation.terminator.kind is TerminatorKind.RETURN
                    and dependencies.owners[operation.id][0] == module.graph.root):
                worlds = [use.id for use in operation.uses
                    if type(module.index.values[use.value]) is StateVersionValue]
                _need(len(worlds) == 1, 'module RETURN snapshot lost its unique original world')
                snapshots.append((operation.id, worlds[0]))
        return dependencies, tuple(snapshots)

    def _consumer_corridor(self, body, facts, read, imported, key, context):
        start = body.index.regions[body.graph.root].entry
        if (imported.origin.namespace == GraphNamespace.from_source(body.namespace)
                and imported.origin.context == context):
            # This CFG corridor is usable only within the same selected context.
            # Otherwise the receiver path carries the interprocedural ordering.
            operation = body.index.operations[imported.operation]
            start = operation.terminator.successors[imported.normal.successor_index].block
        return facts.paths.find_path(start, read.operation, key, ())

    def _projection(self, body, facts, read, query, key, selector, imported, path, module,
                    dependencies, snapshot, binding, consumer):
        dependencies.validate_binding(binding)
        source_ns = GraphNamespace.from_source(imported.module)
        source = Point(source_ns, binding.write.payload, None)
        payload = module.index.use_site(binding.write.payload).use.value
        _need(type(module.index.values[payload]) is ReferenceValue, 'snapshot binding has no original reference payload')
        snapshot_op, snapshot_world = snapshot
        consumer_path, consumer_operations = consumer
        conditions = dict.fromkeys((*imported.conditions,
            *(condition for edge in path for condition in edge.conditions)))
        anchors = dict.fromkeys((source, query, imported.origin))
        sources = dict.fromkeys((query.namespace.graph, source_ns.graph,
            replace(query.namespace.graph, pointer='#'), replace(source_ns.graph, pointer='#')))
        known_writes = {}

        def point(namespace, node, context):
            result = Point(namespace, node, context); anchors[result] = None
            return result

        def ports(original, namespace, identity, context, *, full=True):
            operation = original.index.operations[identity]
            point(namespace, identity, context)
            for use in operation.uses:
                if full or type(original.index.values[use.value]) is StateVersionValue:
                    point(namespace, use.id, context)
            for value in operation.results:
                if full or type(original.index.values[value]) is StateVersionValue:
                    point(namespace, value, context)
            if operation.terminator is not None:
                for edge in operation.terminator.successors:
                    for value in original.index._block_records[edge.block].arguments:
                        if type(original.index.values[value]) is StateVersionValue:
                            point(namespace, value, context)

        point(query.namespace, read.receiver, query.context)
        point(query.namespace, read.world, query.context)
        if type(read) is StaticImportFromRead:
            point(query.namespace, read.key, query.context)
        for node in (imported.locals_namespace, imported.globals_namespace, imported.entry_world):
            point(source_ns, node, None)
        for node in (binding.query_owner, binding.write.owners[0], binding.write.keys[0],
                binding.write.world, snapshot_world):
            point(source_ns, node, None)
        ports(module, source_ns, binding.write.operation, None)
        ports(module, source_ns, snapshot_op, None)
        ports(body, query.namespace, read.operation, query.context)
        origin_body = self.resolver._body(imported.origin.namespace)
        ports(origin_body, imported.origin.namespace, imported.operation, imported.origin.context)
        if imported.request is not None:
            for node in (imported.request.requested_use, imported.request.level_use,
                    imported.request.fromlist_use, imported.request.fromlist_constant.operation):
                point(imported.origin.namespace, node, imported.origin.context)
        for edge in path:
            anchors[edge.source] = None; anchors[edge.target] = None
            sources[edge.source.namespace.graph] = None; sources[edge.target.namespace.graph] = None
        for identity in binding.intervening_operations:
            ports(module, source_ns, identity, None, full=False)
        for identity in consumer_operations:
            ports(body, query.namespace, identity, query.context, full=False)
        # Retain known write interfaces in every body/context participating in
        # this receiver path. Their aliases/commit/effects are not inferred.
        contexts = dict.fromkeys(((query.namespace, query.context),
            *((endpoint.namespace, endpoint.context) for edge in path for endpoint in (edge.source, edge.target))))
        for namespace, context in contexts:
            self.resolver.owner._check()
            if namespace.source_body is None:
                continue
            original = self.resolver._body(namespace)
            original_facts = self.resolver.modules._index(original)
            local = self.resolver.owner._namespace_for(original)
            writes = dict.fromkeys((*local.writes,
                *(write.operation for write in original_facts.writes)))
            for identity in writes:
                writer = point(namespace, identity, context); known_writes[writer] = None
                ports(original, namespace, identity, context)
        operands = tuple(anchors)

        def condition(name, subject=query):
            conditions[Condition('scar.contextual-module-binding', name, subject, operands=operands)] = None

        condition('STANDARD_IMPORT_INITIALIZER_USES_MODULE_DICT')
        condition('SOURCE_MODULE_INITIALIZER_COMPLETED_NORMALLY')
        if type(read) is StaticImportFromRead:
            condition('IMPORT_FROM_LOOKUP_USES_NAMESPACE_BINDING')
            condition('IMPORT_FROM_FALLBACKS_NOT_SELECTED')
        else:
            condition('MODULE_LOOKUP_USES_SOURCE_MODULE_DICT')
            condition('MODULE_LOOKUP_HOOKS_NOT_SELECTED')
        condition('SOURCE_SNAPSHOT_BINDING_PRESERVED_AT_CURRENT_READ')
        for original in binding.conditions:
            conditions[replace(Condition.from_enum(original), subject=query, operands=operands)] = None
        for namespace, context, controls in ((source_ns, None, (binding.write.normal_edge, *binding.path)),
                (query.namespace, query.context, (*consumer_path, read.normal)),
                (imported.origin.namespace, imported.origin.context, (imported.normal,))):
            for control in controls:
                conditions[Condition('canonical', 'SUCCESSOR_SELECTED',
                    Point(namespace, control.operation, context), control.successor_index)] = None
        evidence = tuple(dict.fromkeys((*imported.evidence,
            *(item for edge in path for item in edge.evidence),
            Evidence('CONTEXTUAL_MODULE_BINDING_FROM_SHARED_REFERENCE_SOURCE_V1', tuple(sources), operands))))
        return ContextualModuleBindingProjection(read, key, selector, imported, path, imported.module,
            snapshot_op, snapshot_world, binding, consumer_path, consumer_operations,
            tuple(known_writes), source, query, tuple(conditions), evidence)

    def _derive(self, query):
        if (type(query) is not Point or type(query.node) is not ValueID
                or query.namespace.source_body is None):
            return (), (), True
        try:
            self.resolver.owner._check()
            selected = self._read(query)
        except (OverflowError, TimeoutError) as error:
            return (), (Frontier(query, 'CONTEXTUAL_MODULE_BINDING_BUDGET',
                type(error).__name__ + ': ' + str(error)),), False
        if selected is None:
            return (), (), True
        if query in self._active:
            return (), (Frontier(query, 'CONTEXTUAL_MODULE_BINDING_SOURCE_CYCLE_OPEN',
                'An active field read cannot establish its own receiver module or snapshot binding.'),), False
        self._active.add(query)
        rows, notes = {}, {}
        def note(kind, detail):
            notes[Frontier(query, kind, detail)] = None
        note('CONTEXTUAL_MODULE_BINDING_SCOPE_OPEN',
            'Import selection/cache/hooks, conditional initializer L/G alias, lookup and preservation across all original worlds remain open.')
        try:
            body, facts, read = selected
            key, selector = self._key(body, read)
            if key is None:
                note('CONTEXTUAL_MODULE_LOOKUP_NAME_UNRESOLVED', selector.unresolved_reason)
                return (), tuple(notes), False
            root = Point(query.namespace, read.receiver, query.context)
            walk = walk_reference_sources(self.resolver, root)
            notes.update((item, None) for item in walk.frontiers)
            for origin in walk.points:
                if type(origin.node) is not ValueID or origin.namespace.source_body is None:
                    continue
                self.resolver.owner._check()
                origin_body = self.resolver._body(origin.namespace)
                origin_facts = self.resolver.modules._index(origin_body)
                producer = origin_facts.normal_producers.get(origin.node)
                if origin_facts.protocols.get(producer) not in ('IMPORT_NAME_314', 'FUNCTION_IMPORT_NAME'):
                    continue
                for imported in self.imports.sources(origin):
                    module = self.resolver._body(GraphNamespace.from_source(imported.module))
                    snapshots = self._snapshots(module)
                    if snapshots is None:
                        note('CONTEXTUAL_MODULE_INITIALIZER_PARTIAL',
                            'The selected source module retains an unexpanded suffix; no complete initialized snapshot is invented.')
                        continue
                    dependencies, terminals = snapshots
                    if not terminals:
                        note('CONTEXTUAL_MODULE_INITIALIZER_NORMAL_RETURN_UNAVAILABLE',
                            'The selected source MODULE has no original root normal RETURN snapshot.')
                    consumer = self._consumer_corridor(body, facts, read, imported, key, query.context)
                    if consumer is None:
                        note('CONTEXTUAL_MODULE_READ_CONTROL_PATH_UNAVAILABLE',
                            'No original conditional CFG corridor reaches this field read from its entry/import boundary.')
                        continue
                    for path in self._receiver_paths(walk, origin):
                        for snapshot_op, world in terminals:
                            bindings = dependencies.bindings_at(imported.globals_namespace, key, snapshot_op, world,
                                equivalent_owners=tuple(dict.fromkeys((imported.locals_namespace, imported.globals_namespace))))
                            for binding in bindings:
                                if len(rows) >= self.resolver.owner.budget.max_candidates_per_call:
                                    raise OverflowError('contextual module binding projection budget exhausted')
                                projection = self._projection(body, facts, read, query, key, selector,
                                    imported, path, module, dependencies, (snapshot_op, world), binding, consumer)
                                rows[projection] = None
                notes.update((item, None) for item in self.imports.frontiers_for(origin))
        except (OverflowError, TimeoutError) as error:
            note('CONTEXTUAL_MODULE_BINDING_BUDGET', type(error).__name__ + ': ' + str(error))
        finally:
            self._active.remove(query)
        for projection in rows:
            self._known[projection] = None; self._known.move_to_end(projection)
        while len(self._known) > self.resolver.owner.budget.max_candidates_per_call:
            self._known.popitem(last=False)
        self._counts['read_queries'] += 1; self._counts['projections'] += len(rows)
        return tuple(rows), tuple(notes), False

    def projections_for(self, point):
        rows, notes, enumerated = self._derive(point)
        self._last = point, rows, notes
        return rows

    def incoming(self, point):
        rows, notes, enumerated = self._derive(point)
        self._last = point, rows, notes
        return Neighborhood(tuple(row.dependency_edge() for row in rows), notes, enumerated)

    def outgoing(self, point):
        if point.namespace.source_body is None or type(point.node) is not UseID:
            return Neighborhood()
        body = self.resolver._body(point.namespace)
        if body.module is None:
            return Neighborhood()
        dependencies = self.resolver.owner._namespace_for(body)
        if not any(write.payload == point.node for write in dependencies.writes.values()):
            return Neighborhood()
        rows = [row for row in self._known if row.source == point]
        for row in rows:
            self.validate_projection(row)
        return Neighborhood(tuple(row.dependency_edge() for row in rows),
            (Frontier(point, 'CONTEXTUAL_MODULE_BINDING_CONSUMERS_NOT_ENUMERATED',
                'Only bounded already discovered projections are mirrored; other contexts and consumers were not enumerated.'),), False)

    def validate_projection(self, projection):
        _need(type(projection) is ContextualModuleBindingProjection, 'typed module projection required')
        projection.__post_init__()
        selected = self._read(projection.target)
        _need(selected is not None and selected[2] == projection.read, 'read differs from original source/ports')
        body, facts, read = selected
        key, selector = self._key(body, read)
        _need((key, selector) == (projection.key, projection.selector), 'lookup name differs from fresh lexical source')
        self.imports.validate(projection.import_source)
        for edge in projection.receiver_path:
            _need(self.resolver._transport(edge), 'receiver path is not legal original reference transport')
            fresh = self.resolver.session.graph().incoming(edge.target, kinds=(edge.kind,))
            _need(edge in fresh.edges, 'receiver path differs from fresh shared-graph evidence')
        module = self.resolver._body(GraphNamespace.from_source(projection.source_module))
        snapshots = self._snapshots(module)
        _need(snapshots is not None, 'partial module cannot supply a completed initializer snapshot')
        dependencies, terminals = snapshots
        snapshot = projection.snapshot_operation, projection.snapshot_world
        _need(snapshot in terminals, 'snapshot is not the original root MODULE RETURN/world')
        dependencies.validate_binding(projection.namespace_binding)
        consumer = self._consumer_corridor(body, facts, read, projection.import_source, key,
            projection.target.context)
        _need(consumer == (projection.consumer_path, projection.consumer_operations),
            'consumer control corridor differs from original CFG')
        expected = self._projection(body, facts, read, projection.target, key, selector,
            projection.import_source, projection.receiver_path, module, dependencies, snapshot,
            projection.namespace_binding, consumer)
        _need(expected == projection, 'projection payload/owners/worlds/guards/evidence differ from original inputs')
        self._counts['fresh_validations'] += 1
        return True

    def clear(self):
        self._active.clear(); self._known.clear(); self._last = None

    def measurements(self):
        return {**dict(self._counts), 'retained_projection_witnesses': len(self._known),
            'projection_retention_ceiling': self.resolver.owner.budget.max_candidates_per_call,
            'full_consumer_scope_enumerated': False}


__all__ = ['ContextualModuleBindingProjection', 'ContextualModuleBindingProvider']
