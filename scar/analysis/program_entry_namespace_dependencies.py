"""Local and entry-state dependencies over the original dependency view.

Reference paths describe possible namespace identity, not captured contents.
Only an actual namespace read starts discovery; no CALL or root context is
invented and no STATE_VALUE edge can justify its own derivation.
"""
from __future__ import annotations

from collections import Counter, OrderedDict, deque
from dataclasses import replace

from scar.ir.program.dependencies import (
    DependencyCondition, DependencyEdge, DependencyEvidence, DependencyFrontier, DependencyKind as K,
    DependencyMeaning as M, DependencyNeighborhood, DependencyPoint,
    DependencyStrength, GraphNamespace,
)
from scar.ir.program.ids import UseID, ValueID
from scar.ir.program.environments import EnvironmentRole
from scar.ir.program.model import ReferenceValue
from scar.ir.program.source_call_bindings import SourceBodyNamespace


OWNER_KINDS = frozenset((K.ENVIRONMENT, K.ARGUMENT, K.VALUE_USE))


class EntryNamespaceDependencyProvider:
    """Fresh local writes and conditional snapshots -> namespace reads.

    Outgoing discovery scans bounded original reads in the same body and
    retains entry consumers already demanded in this owned session.  Its
    frontier keeps the global consumer set open.  The small remembered set
    contains original query points, never a graph or cached validation result.
    """
    relation_kinds = frozenset((K.STATE_VALUE,))

    def __init__(self, session):
        self.session = session
        self._point, self._notes = None, {}
        self._known_reads = OrderedDict()
        self._counts = Counter()

    def _begin(self, point):
        if type(point) is not DependencyPoint:
            raise TypeError("entry namespace discovery requires an original typed query point")
        if self._point != point:
            self._point, self._notes = point, {}

    def _note(self, point, kind, detail):
        self._notes[DependencyFrontier(point, kind, detail)] = None

    def frontiers_for(self, point):
        return tuple(self._notes) if self._point == point else ()

    def _body(self, namespace):
        body = self.session.load(namespace)
        return body if type(getattr(body, "namespace", None)) is SourceBodyNamespace else None

    def _read_body(self, point):
        if type(point.node) is not ValueID:
            return None
        body = self._body(point.namespace)
        if body is None or point.node not in body.dependencies.by_result:
            return None
        return body

    def _reference_edge(self, edge):
        if type(edge) is not DependencyEdge or edge.kind not in OWNER_KINDS:
            return False
        if edge.kind is not K.VALUE_USE:
            return edge.meaning is M.REFERENCE
        # Local VALUE_USE means VALUE for all types.  Admit this exact
        # reference operand identity only, rather than arbitrary VALUE edges.
        if (edge.meaning is not M.VALUE or type(edge.source.node) is not ValueID
                or type(edge.target.node) is not UseID
                or edge.source.namespace != edge.target.namespace
                or edge.source.context != edge.target.context):
            return False
        index = self.session.index(edge.source.namespace)
        return (type(index.values.get(edge.source.node)) is ReferenceValue
                and index.use_site(edge.target.node).use.value == edge.source.node)

    def _validate_owner_edge(self, edge):
        self.session.check()
        if not self._reference_edge(edge):
            return False
        # Filtering the provider family before querying prevents STATE_VALUE
        # self-recursion.  The whole original edge, including conditions,
        # evidence and both context endpoints, must freshly match.
        neighborhood = self.session.graph().incoming(edge.target, kinds=(edge.kind,))
        for frontier in neighborhood.frontiers:
            self._notes[frontier] = None
        return edge in neighborhood.edges

    def _module_endpoint(self, point):
        if type(point.node) is not ValueID:
            return None
        body = self._body(point.namespace)
        if body is None or body.module is None:
            return None
        roots = body.graph.frame_roots
        if len(roots) != 1:
            raise ValueError("source module has no unique original frame root")
        return body if point.node == roots[0].entry.globals_namespace else None

    def _owner_paths(self, owner):
        pending = deque(((owner, (), frozenset((owner,))),))
        examined = 0
        maximum = self.session.budget.max_entry_owner_edges
        while pending:
            self.session.check()
            point, reverse_path, ancestors = pending.popleft()
            module = self._module_endpoint(point)
            if module is not None:
                yield module, tuple(reversed(reverse_path))
                continue
            neighborhood = self.session.graph().incoming(point, kinds=OWNER_KINDS)
            for frontier in neighborhood.frontiers:
                self._notes[frontier] = None
            if not neighborhood.enumerated:
                self._note(point, "ENTRY_NAMESPACE_OWNER_SCOPE_OPEN",
                    "The original reference-owner interface still has unenumerated alternatives.")
            for edge in neighborhood.edges:
                if not self._reference_edge(edge):
                    continue
                examined += 1
                self._counts["owner_edges_examined"] += 1
                if examined > maximum:
                    raise OverflowError("entry namespace reference-owner edge budget exhausted")
                if edge.source in ancestors:
                    self._note(edge.source, "ENTRY_NAMESPACE_OWNER_CYCLE_OPEN",
                        "A cyclic reference path was retained as an open identity alternative.")
                    continue
                pending.append((edge.source, (*reverse_path, edge), ancestors | {edge.source}))

    def _namespace_body(self, body):
        from scar.analysis.static_crossbody_namespace import StaticNamespaceBody
        return StaticNamespaceBody(body.graph, body.document, body.namespace,
            body.index, body.dependencies, _facts=self.session._environment_facts)

    def _budget(self):
        from scar.analysis.static_entry_namespace import EntryNamespaceBudget
        return EntryNamespaceBudget(max_owner_edges=self.session.budget.max_entry_owner_edges,
            max_snapshots=self.session.budget.max_entry_snapshots,
            max_projections=self.session.budget.max_entry_projections)

    def _local_edges(self, body, point):
        """Replay same-body bindings without requiring a CALL publication."""
        def at(node):
            return DependencyPoint(point.namespace, node, point.context)

        for flow in body.dependencies.flows(point.node):
            self.session.check()
            flow.__post_init__()
            body.dependencies.validate(flow)
            source, target = at(flow.assigned_reference), at(flow.read_result)
            # Bind each original predicate to the complete original relation,
            # rather than sharing an unqualified enum-name guard across writes.
            ports = tuple(at(node) for node in (
                flow.write_operation, flow.write_owner, flow.write_key,
                flow.assigned_reference, flow.write_world,
                flow.read_operation, flow.read_owner, flow.read_key, flow.read_world,
                *flow.prior_lookup_owners, *flow.intervening_operations))
            conditions = tuple(replace(DependencyCondition.from_enum(condition),
                subject=target, operands=ports) for condition in flow.conditions)
            # ControlEdgeReference is not a node.  Its real operation and
            # successor ordinal remain an explicit predicate over original
            # endpoints, including normal completion of both real accesses.
            controls = tuple(dict.fromkeys((flow.write_normal, *flow.path, flow.read_normal)))
            conditions += tuple(DependencyCondition("scar.namespace-control",
                "CONTROL_EDGE_SELECTED", subject=at(control.operation),
                index=control.successor_index,
                operands=(source, target, at(flow.write_world), at(flow.read_world)))
                for control in controls)
            anchors = tuple(dict.fromkeys((*ports, *(at(control.operation) for control in controls))))
            evidence = DependencyEvidence("STATIC_LOCAL_NAMESPACE_BINDING_VALUE_V1",
                (body.namespace.graph, replace(body.namespace.graph, pointer="#")), anchors)
            self._counts["local_flows_replayed"] += 1
            yield DependencyEdge(source, target, K.STATE_VALUE, M.REFERENCE,
                (evidence,), conditions, DependencyStrength.MAY)

    def projections_for(self, point):
        """Stream typed projections; all inputs remain original receipt owners."""
        self._begin(point)
        body = self._read_body(point)
        if body is None:
            return
        from scar.analysis.static_entry_namespace import (
            derive_entry_namespace_projections, validate_entry_namespace_projection,
        )
        if body.interface is None:
            self._note(point, "ENTRY_NAMESPACE_INTERFACE_UNSUPPORTED",
                "This namespace read has no original bound function entry interface; no entry world or foreign owner is invented.")
            return
        members = [member for environment in body.graph.environments
            if environment.region == body.namespace.region for member in environment.members
            if member.role is EnvironmentRole.GLOBALS_NAMESPACE]
        if len(members) != 1:
            self._note(point, "ENTRY_NAMESPACE_GLOBALS_INTERFACE_UNSUPPORTED",
                "This original function entry has no unique retained G member.")
            return
        globals_member = members[0]
        read = body.dependencies.by_result[point.node]
        emitted = 0
        any_entry_path = False
        for slot, owner_use in enumerate(read.owners):
            self.session.check()
            owner_value = body.index.use_site(owner_use).use.value
            if owner_value != globals_member.reference:
                self._note(point, "ENTRY_NAMESPACE_NON_GLOBAL_OWNER_OPEN",
                    "This original lookup also has a separate non-G owner; it is not replaced by module namespace contents.")
                continue
            if body.dependencies._string(read.keys[slot]) is None:
                self._note(point, "ENTRY_NAMESPACE_KEY_NOT_STATIC_STRING",
                    "This original namespace selector has no retained literal string key.")
                continue
            paths = body.dependencies.entry_paths_to_read(read, slot)
            if not paths:
                continue
            any_entry_path = True
            owner = DependencyPoint(point.namespace, owner_value, point.context)
            found_module = False
            for module, owner_path in self._owner_paths(owner):
                found_module = True
                module_context = owner_path[0].source.context if owner_path else owner.context
                entry_body, module_body = self._namespace_body(body), self._namespace_body(module)
                options = dict(entry=entry_body, module=module_body,
                    validate_owner_edge=self._validate_owner_edge, load_index=self.session.index,
                    check=self.session.check, budget=self._budget(),
                    initialization_contract=False, allow_module_owner_alias=True)
                result = derive_entry_namespace_projections(owner_path=owner_path,
                    read_result=point, read_slot=slot, module_context=module_context, **options)
                for frontier in result.frontiers:
                    self._notes[frontier] = None
                for projection in result.projections:
                    if validate_entry_namespace_projection(projection, **options) is not True:
                        raise ValueError("entry namespace projection did not freshly replay its original inputs")
                    emitted += 1
                    if emitted > self.session.budget.max_entry_projections:
                        raise OverflowError("entry namespace projection budget exhausted")
                    self._counts["projections_derived"] += 1
                    self._known_reads[point] = None
                    self._known_reads.move_to_end(point)
                    while len(self._known_reads) > self.session.budget.max_entry_projections:
                        self._known_reads.popitem(last=False)
                    yield projection
            if not found_module:
                self._note(owner, "ENTRY_NAMESPACE_MODULE_REFERENCE_UNAVAILABLE",
                    "No supplied conditional reference path reached an original module G entry; entry binding contents remain unknown.")
        if any_entry_path:
            self._note(point, "ENTRY_NAMESPACE_BINDING_SET_OPEN",
                "Module snapshots are conditional entry-state candidates; other entry bindings and intervening external state remain open.")

    @staticmethod
    def _edge(projection):
        return DependencyEdge(projection.source, projection.target, K.STATE_VALUE,
            M.REFERENCE, projection.evidence, projection.conditions, DependencyStrength.MAY)

    def incoming(self, point):
        self._begin(point)
        body = self._read_body(point)
        if body is None:
            return DependencyNeighborhood()
        edges = {}
        try:
            for edge in self._local_edges(body, point):
                edges[edge] = None
            for projection in self.projections_for(point):
                edge = self._edge(projection)
                edges[edge] = None
        except (OverflowError, TimeoutError) as error:
            self._note(point, "ENTRY_NAMESPACE_DISCOVERY_BUDGET", type(error).__name__ + ": " + str(error))
        return DependencyNeighborhood(tuple(edges), self.frontiers_for(point), not self._notes)

    def outgoing(self, point):
        self._begin(point)
        if type(point.node) is not UseID:
            return DependencyNeighborhood()
        body = self._body(point.namespace)
        if body is None or not any(
                access.payload == point.node for access in body.dependencies.writes.values()):
            return DependencyNeighborhood()
        edges, notes = {}, {}
        try:
            # The same-body inverse is demand-complete only for the retained
            # read prefix.  Enumerate original reads, not the whole program.
            for position, result in enumerate(body.dependencies.by_result):
                self.session.check()
                if position >= self.session.budget.max_entry_projections:
                    notes[DependencyFrontier(point, "LOCAL_NAMESPACE_CONSUMER_SCAN_BUDGET",
                        "Further original reads in this body remain outside the bounded local inverse scan.")] = None
                    break
                read = DependencyPoint(point.namespace, result, point.context)
                for edge in self._local_edges(body, read):
                    if edge.source == point:
                        edges[edge] = None
            if body.module is not None:
                for read in tuple(self._known_reads):
                    for projection in self.projections_for(read):
                        if projection.source == point:
                            edges[self._edge(projection)] = None
                    notes.update(self._notes)
        except (OverflowError, TimeoutError) as error:
            notes[DependencyFrontier(point, "ENTRY_NAMESPACE_DISCOVERY_BUDGET",
                type(error).__name__ + ": " + str(error))] = None
        notes[DependencyFrontier(point, "ENTRY_NAMESPACE_CONSUMERS_NOT_ENUMERATED",
            "The bounded same-body inverse and already demanded entry consumers do not enumerate external namespace consumers.")] = None
        self._point, self._notes = point, notes
        return DependencyNeighborhood(tuple(edges), tuple(notes), False)

    def measurements(self):
        return {**dict(self._counts), "remembered_read_points": len(self._known_reads),
            "scope": "DEMAND_NAMESPACE_READ_AND_REFERENCE_OWNER_PATH", "entry_binding_set_complete": False,
            "target_executed": False}

    def clear(self):
        self._known_reads.clear()
        self._point, self._notes = None, {}


__all__ = ["EntryNamespaceDependencyProvider", "OWNER_KINDS"]
