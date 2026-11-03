"""Contextual instances of original CALL-free import/module templates.

The template's empty requirements describe the absence of CALL support, not
a closed execution context. External module contexts remain unknown. All
import selection, lookup, alias and state-preservation premises remain guards.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace

from scar.ir.program.dependencies import (
    DependencyCondition, DependencyEdge, DependencyEvidence, DependencyFrontier,
    DependencyKind as K, DependencyMeaning as M, DependencyNeighborhood,
    DependencyPoint, DependencyStrength, GraphNamespace,
)
from scar.ir.program.ids import UseID, ValueID
from scar.ir.program.model import ReferenceValue
from scar.ir.program.source_call_bindings import SourceBodyNamespace
from scar.ir.program.static_calls import (
    StaticAttributeAccess, StaticImportFromRead, StaticModuleAttributeFlow, StaticReferencePoint,
)


class _CallSupportUnavailable(LookupError):
    """A valid witness belongs to another, unsupported context family."""


@dataclass(frozen=True, slots=True)
class ModuleReferenceProjection:
    """One original structural witness and its explicit contextual endpoints."""
    flow: StaticModuleAttributeFlow
    source: DependencyPoint
    target: DependencyPoint
    conditions: tuple[DependencyCondition, ...]
    evidence: tuple[DependencyEvidence, ...]

    def __post_init__(self):
        if type(self.flow) is not StaticModuleAttributeFlow:
            raise TypeError("module projection requires its original typed witness")
        self.flow.__post_init__()
        if type(self.source) is not DependencyPoint or type(self.target) is not DependencyPoint:
            raise TypeError("module projection requires original contextual points")
        if ((self.source.namespace, self.source.node) !=
                (GraphNamespace.from_source(self.flow.source_body), self.flow.source_payload)
                or (self.target.namespace, self.target.node) !=
                (GraphNamespace.from_source(self.flow.read.body), self.flow.read.result)):
            raise ValueError("module template instance changed original payload/read endpoints")
        expected = self.target.context if self.source.namespace == self.target.namespace else None
        if self.source.context != expected:
            raise ValueError("an external module context must remain unknown")
        if (type(self.conditions) is not tuple
                or any(type(row) is not DependencyCondition for row in self.conditions)
                or type(self.evidence) is not tuple or not self.evidence
                or any(type(row) is not DependencyEvidence for row in self.evidence)):
            raise TypeError("module projection needs typed immutable conditions and evidence")

    def dependency_edge(self):
        return DependencyEdge(self.source, self.target, K.STATE_VALUE, M.REFERENCE,
            self.evidence, self.conditions, DependencyStrength.MAY)


class ModuleReferenceDependencyProvider:
    """Demand only actual ATTRIBUTE/IMPORT_FROM reads over one shared owner."""
    relation_kinds = frozenset((K.STATE_VALUE,))

    def __init__(self, session, engine, *, body_for=None):
        from scar.analysis.static_module_attributes import ModuleAttributeDependencies
        if type(engine) is not ModuleAttributeDependencies:
            raise TypeError("module reference provider needs the original module engine")
        if engine.reference_sources is not None:
            raise ValueError("contextual module templates require a CALL-free module engine")
        self.session, self.engine = session, engine
        self.body_for = engine._body if body_for is None else body_for
        if not callable(self.body_for):
            raise TypeError("module reference provider requires a shared original body loader")
        self._point, self._notes = None, {}
        self._counts = Counter()

    def _begin(self, point):
        if type(point) is not DependencyPoint:
            raise TypeError("module reference discovery needs an original typed query point")
        if self._point != point:
            self._point, self._notes = point, {}

    def _note(self, point, kind, detail):
        self._notes[DependencyFrontier(point, kind, detail)] = None

    def frontiers_for(self, point):
        return tuple(self._notes) if self._point == point else ()

    def _body(self, namespace):
        # The public owner checks each supplied receipt/declaration first.
        original = self.session.load(namespace)
        source = getattr(original, "namespace", None)
        if type(source) is not SourceBodyNamespace:
            return None
        body = self.body_for(source)
        if (type(getattr(body, "namespace", None)) is not SourceBodyNamespace
                or GraphNamespace.from_source(body.namespace) != GraphNamespace.from_source(source)
                or (body.namespace.definition, body.namespace.source, body.namespace.entry) !=
                    (source.definition, source.source, source.entry)
                or body.graph is not original.graph or body.index is not original.index
                or body.document is not original.document):
            raise ValueError("module engine did not reuse the receipt-checked original body/index/document")
        return body

    @staticmethod
    def _paths(flow):
        return (flow.receiver_path,
            *((flow.write_receiver_path,) if flow.write_receiver_path is not None else ()),
            *flow.overwrite_receiver_paths)

    def _call_free_records(self, flow):
        """Check the complete support tree, not only the outer empty tuple."""
        pending, seen, modules, namespaces = [flow], set(), [], []
        while pending:
            self.session.check()
            current = pending.pop()
            if type(current) is not StaticModuleAttributeFlow:
                raise _CallSupportUnavailable("The template has a non-module contextual support relation.")
            if id(current) in seen:
                continue
            seen.add(id(current))
            if len(seen) > self.session.budget.max_entry_projections:
                raise OverflowError("CALL-free module template support budget exhausted")
            current.__post_init__()
            if current.requirements or current.source_requirements or current.module.requirements:
                raise _CallSupportUnavailable("The module witness has recorded CALL requirements.")
            modules.append(current)
            for path in self._paths(current):
                path.__post_init__()
                if (any(point.requirements for point in path.points)
                        or path.argument_flows or path.return_flows
                        or path.cross_body_namespace_flows or path.module_globals_flows):
                    raise _CallSupportUnavailable(
                        "The module witness depends on argument/return/cross-body/globals CALL support.")
                namespaces.extend(path.namespace_flows)
                pending.extend(path.module_attribute_flows)
        return tuple(modules), tuple(dict.fromkeys(namespaces))

    def _validate(self, flow, active=None):
        from scar.analysis.static_module_attributes import validate_module_attribute_flow
        self._call_free_records(flow)
        active = set() if active is None else active
        if id(flow) in active:
            raise ValueError("a module template cannot validate its own cyclic support")
        active.add(id(flow))
        try:
            def support(child):
                if type(child) is not StaticModuleAttributeFlow:
                    raise _CallSupportUnavailable("The template validator requested CALL-dependent support.")
                self._validate(child, active)
            validate_module_attribute_flow(flow, engine=self.engine, check_support=support)
        finally:
            active.remove(id(flow))
        self._counts["fresh_template_replays"] += 1

    def _projection(self, flow, query, modules, namespaces):
        anchors, sources, conditions = {}, {}, {}

        def point(namespace, node):
            graph = GraphNamespace.from_source(namespace)
            return DependencyPoint(graph, node, query.context if graph == query.namespace else None)

        def retain(namespace):
            body = self._body(namespace)
            if body is None:
                raise ValueError("module template source is not an original source body")
            sources[namespace.graph] = None
            sources[replace(namespace.graph, pointer="#")] = None
            return body

        def add_condition(condition, target, operands):
            row = replace(DependencyCondition.from_enum(condition), subject=target, operands=operands)
            conditions[row] = None

        def controls(namespace, rows, operands):
            for control in rows:
                operation = point(namespace, control.operation)
                anchors[operation] = None
                conditions[DependencyCondition("scar.module-template-control", "CONTROL_EDGE_SELECTED",
                    subject=operation, index=control.successor_index, operands=operands)] = None

        for current in modules:
            read, route = current.read, current.module
            for namespace in (read.body, current.source_body, route.body, route.module_body):
                retain(namespace)
            ports = [point(read.body, node) for node in
                (read.operation, read.receiver, read.world, read.result)]
            if type(read) is StaticImportFromRead:
                ports.append(point(read.body, read.key))
            ports.extend(point(current.source_body, node) for node in (
                current.source_operation, current.source_owner, current.source_payload,
                current.source_world, current.snapshot_operation, current.snapshot_world))
            if current.source_key is not None:
                ports.append(point(current.source_body, current.source_key))
            ports.extend(point(route.body, node) for node in (route.operation, route.world, route.result))
            ports.extend(point(route.module_body, node) for node in
                (route.locals_namespace, route.globals_namespace, route.entry_world))
            if route.request is not None:
                request = route.request
                ports.extend(point(route.body, node) for node in (
                    request.requested_use, request.level_use, request.fromlist_use,
                    request.fromlist_constant.operation))
            ports.extend(point(current.source_body, node) for node in current.source_operations)
            ports.extend(point(read.body, node) for node in current.consumer_operations)
            for overwrite in current.overwrites:
                ports.extend(point(overwrite.body, node) for node in
                    (overwrite.operation, overwrite.receiver, overwrite.assigned, overwrite.world))
            for path in self._paths(current):
                ports.extend(point(original.body, original.value) for original in path.points)
            operands = tuple(dict.fromkeys(ports))
            anchors.update((port, None) for port in operands)
            target = point(read.body, read.result)
            for condition in current.conditions:
                add_condition(condition, target, operands)
            controls(route.body, (route.normal,), operands)
            controls(read.body, (read.normal, *current.consumer_path), operands)
            controls(current.source_body, (current.source_normal, *current.source_path), operands)
            for overwrite in current.overwrites:
                controls(overwrite.body, (overwrite.normal,), operands)
            if GraphNamespace.from_source(current.source_body) != GraphNamespace.from_source(read.body):
                conditions[DependencyCondition("scar.contextual-module",
                    "IMPORT_BINDING_STATE_PRESERVED_AT_READ", subject=target,
                    operands=(point(current.source_body, current.snapshot_world),
                        point(read.body, read.world), point(current.source_body, current.source_owner),
                        point(route.module_body, route.globals_namespace)))] = None
            for path in self._paths(current):
                for original in path.points:
                    retain(original.body)
                    anchors[point(original.body, original.value)] = None

        for qualified in namespaces:
            retain(qualified.body)
            local = qualified.flow
            ports = tuple(point(qualified.body, node) for node in (
                local.write_operation, local.write_owner, local.write_key,
                local.assigned_reference, local.write_world, local.read_operation,
                local.read_owner, local.read_key, local.read_world, local.read_result,
                *local.prior_lookup_owners, *local.intervening_operations))
            anchors.update((port, None) for port in ports)
            for condition in local.conditions:
                add_condition(condition, point(qualified.body, local.read_result), ports)
            controls(qualified.body, (local.write_normal, *local.path, local.read_normal), ports)

        source = point(flow.source_body, flow.source_payload)
        target = point(flow.read.body, flow.read.result)
        if target != query:
            raise ValueError("contextual module instance changed the queried original endpoint")
        source_body = self._body(flow.source_body)
        if (source_body is None or source_body.index.use_site(flow.source_payload).use.value != flow.source_value
                or type(source_body.index.values[flow.source_value]) is not ReferenceValue):
            raise ValueError("module template payload is not its original reference Use/value")
        evidence = DependencyEvidence("CONTEXTUAL_MODULE_TEMPLATE_INSTANTIATION_V1",
            tuple(sources), tuple(anchors))
        return ModuleReferenceProjection(flow, source, target, tuple(conditions), (evidence,))

    def projections_for(self, query):
        """Yield fresh original witnesses alongside their contextual instances."""
        self._begin(query)
        if type(query.node) is not ValueID:
            return
        if self.engine.reference_sources is not None:
            raise ValueError("CALL-free module engine acquired contextual CALL support")
        body = self._body(query.namespace)
        if body is None or type(body.index.values.get(query.node)) is not ReferenceValue:
            return
        facts = self.engine._index(body)
        read = facts.reads.get(query.node)
        if type(read) not in (StaticAttributeAccess, StaticImportFromRead):
            return
        self._note(query, "CONTEXTUAL_MODULE_LOOKUP_AND_STATE_OPEN",
            "Source-module selection, import cache/hooks, lookup fallbacks, aliases and preservation across original worlds remain conditional.")
        count = 0
        for flow in self.engine.sources(body, query.node, requirements=()):
            self.session.check()
            try:
                modules, namespaces = self._call_free_records(flow)
                self._validate(flow)
            except _CallSupportUnavailable as error:
                self._note(query, "CONTEXTUAL_MODULE_CALL_SUPPORT_UNAVAILABLE", str(error))
                continue
            count += 1
            if count > self.session.budget.max_entry_projections:
                raise OverflowError("contextual module projection budget exhausted")
            projection = self._projection(flow, query, modules, namespaces)
            self._counts["projections_derived"] += 1
            yield projection
        # The engine's aggregate body table also contains notes from other
        # read demands.  Retain this exact template demand plus input-scope
        # notes, rather than attaching another read's unresolved consumer.
        notes = dict(self.engine._permanent_frontiers.get(body.namespace, {}))
        notes.update(self.engine._read_frontiers.get(
            StaticReferencePoint(body.namespace, query.node, ()), {}))
        for frontier in notes:
            self._note(query, frontier.kind, frontier.detail)

    def incoming(self, point):
        self._begin(point)
        edges = {}
        try:
            for projection in self.projections_for(point):
                edges[projection.dependency_edge()] = None
        except (OverflowError, TimeoutError) as error:
            self._note(point, "CONTEXTUAL_MODULE_DISCOVERY_BUDGET", type(error).__name__ + ": " + str(error))
        return DependencyNeighborhood(tuple(edges), self.frontiers_for(point), not self._notes)

    def validate_projection(self, projection):
        """Independently replay a retained instance; never cache a PASS."""
        if type(projection) is not ModuleReferenceProjection:
            raise TypeError("expected a typed contextual module projection")
        projection.__post_init__()
        self._begin(projection.target)
        if self.engine.reference_sources is not None:
            raise ValueError("CALL-free module engine acquired contextual CALL support")
        modules, namespaces = self._call_free_records(projection.flow)
        self._validate(projection.flow)
        if projection != self._projection(projection.flow, projection.target, modules, namespaces):
            raise ValueError("module template instance differs from its original contextual replay")
        return True

    def outgoing(self, point):
        self._begin(point)
        if type(point.node) is not UseID:
            return DependencyNeighborhood()
        body = self._body(point.namespace)
        if body is None:
            return DependencyNeighborhood()
        dependencies = self.engine.namespace_for(body)
        if not any(write.payload == point.node for write in dependencies.writes.values()):
            facts = self.engine._index(body)
            if not any(write.assigned == point.node for write in facts.writes):
                return DependencyNeighborhood()
        self._note(point, "CONTEXTUAL_MODULE_CONSUMERS_NOT_ENUMERATED",
            "Module templates are demanded by original reads; no global consumer scan or empty-consumer claim is made.")
        return DependencyNeighborhood(frontiers=self.frontiers_for(point), enumerated=False)

    def measurements(self):
        return {**dict(self._counts), "scope": "DEMAND_CALL_FREE_ATTRIBUTE_AND_IMPORT_FROM_TEMPLATES",
            "target_executed": False, "module_state_complete": False}

    def clear(self):
        self._point, self._notes = None, {}


__all__ = ["ModuleReferenceProjection", "ModuleReferenceDependencyProvider"]
