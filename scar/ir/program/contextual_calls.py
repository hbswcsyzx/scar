"""Conditional source-call interfaces with independent contextual axes.

An interface is a source/port declaration, not a dispatch fact.  A contextual
source selects one continuous original factory-to-callable path.  The caller
and factory contexts remain separate; entering a real CALL pushes its original
frame onto the caller context without manufacturing an unknown outer prefix.
Original-input discovery and fresh port/receipt validation belong to the read
session.  These records check structure and expose only guarded MAY relations.
"""
from __future__ import annotations

from dataclasses import dataclass

from .dependencies import (DependencyCondition as Condition, DependencyContext,
    DependencyEdge as Edge, DependencyEvidence as Evidence,
    DependencyFrame as Frame, DependencyKind as K, DependencyMeaning as M,
    DependencyPoint as Point, DependencyStrength as Strength, GraphNamespace,
    context_push)
from .functions import CandidateBinding, CallBindingStatus
from .ids import OperationID, UseID, ValueID
from .model import ExitKind, ValueKind
from .source_call_bindings import SourceArgumentPort, SourceBodyNamespace
from .source_references import SourceDefinitionReference
from .source_returns import SourceReturnSite
from .static_calls import (StaticCallFrontier, StaticCompletionRoute,
    StaticFunctionEnvironmentRoute, StaticQualifiedFunctionCreation,
    StaticStateEntryRoute)


def _exact(value, kind):
    if type(value) is not kind:
        raise TypeError("contextual calls require exact " + kind.__name__)
    post = getattr(value, '__post_init__', None)
    if post is not None:
        post()


def _rows(rows, kind):
    if type(rows) is not tuple:
        raise TypeError("contextual call rows must be immutable tuples")
    for item in rows:
        _exact(item, kind)


def _unique(rows):
    return tuple(dict.fromkeys(rows))


@dataclass(frozen=True, slots=True)
class StaticCallInterface:
    """Source interface facts without any selected caller requirement path."""
    definition: SourceDefinitionReference
    body: SourceBodyNamespace | None
    basis: tuple[str, ...]
    binding: CandidateBinding | None = None
    arguments: tuple[SourceArgumentPort, ...] = ()
    normal_returns: tuple[SourceReturnSite, ...] = ()
    completions: tuple[StaticCompletionRoute, ...] = ()
    state_entry: StaticStateEntryRoute | None = None
    frontiers: tuple[StaticCallFrontier, ...] = ()
    qualification: str = 'STATIC_CALL_INTERFACE_NOT_DISPATCH'
    environment_routes: tuple[StaticFunctionEnvironmentRoute, ...] = ()

    def __post_init__(self):
        _exact(self.definition, SourceDefinitionReference)
        if self.body is not None:
            _exact(self.body, SourceBodyNamespace)
            if (self.body.definition != self.definition.definition
                    or self.body.source != self.definition.source):
                raise ValueError("call interface changed its original qualified body/definition")
        if (type(self.basis) is not tuple or not self.basis
                or any(type(item) is not str or not item for item in self.basis)):
            raise ValueError("call interface needs explicit original resolution bases")
        if self.binding is not None:
            _exact(self.binding, CandidateBinding)
            if self.binding.target != self.definition.definition:
                raise ValueError("call interface binding names another source definition")
        for rows, kind in ((self.arguments, SourceArgumentPort),
                (self.normal_returns, SourceReturnSite), (self.completions, StaticCompletionRoute),
                (self.frontiers, StaticCallFrontier),
                (self.environment_routes, StaticFunctionEnvironmentRoute)):
            _rows(rows, kind)
        if self.state_entry is not None:
            _exact(self.state_entry, StaticStateEntryRoute)
        if self.body is None:
            if (self.arguments or self.normal_returns or self.completions
                    or self.state_entry is not None or self.environment_routes):
                raise ValueError("an unavailable source body cannot supply invented interface ports")
        else:
            if any(port.formal_body != self.body for port in self.arguments):
                raise ValueError("argument formal belongs to another original body")
            if any(route.callee_port.region != self.body.region for route in self.completions):
                raise ValueError("completion belongs to another original callee region")
            if any(site.exit_port.region != self.body.region for site in self.normal_returns):
                raise ValueError("normal return belongs to another original callee region")
            if any(route.callee != self.body or route.creation.definition != self.definition
                   for route in self.environment_routes):
                raise ValueError("environment interface belongs to another body/factory definition")
        if self.qualification != 'STATIC_CALL_INTERFACE_NOT_DISPATCH':
            raise ValueError("source interface facts cannot assert selected or observed dispatch")


@dataclass(frozen=True, slots=True)
class ContextualFunctionSource:
    """One original factory occurrence alternative reaching a callable Use.

    Binding token edges describe their payload field, not token/object identity.
    Ordinary operand, state-interface and compute-result edges are excluded.
    The session must freshly verify the actual port meanings and every edge.
    """
    callable: Point
    factory: Point
    creation: StaticQualifiedFunctionCreation
    path: tuple[Edge, ...]

    def __post_init__(self):
        _exact(self.callable, Point); _exact(self.factory, Point)
        _exact(self.creation, StaticQualifiedFunctionCreation)
        if type(self.callable.node) is not UseID or type(self.factory.node) is not ValueID:
            raise TypeError("function source must retain callable Use and factory normal Value")
        if (self.factory.namespace != GraphNamespace.from_source(self.creation.body)
                or self.factory.node != self.creation.creation.normal_value
                or self.creation.creation.normal_edge.operation != self.creation.creation.factory):
            raise ValueError("function source changed its original factory normal reference")
        _rows(self.path, Edge)
        if not self.path or self.path[0].source != self.factory or self.path[-1].target != self.callable:
            raise ValueError("function source path must join factory normal to this exact callable Use")
        points = [self.factory]
        for edge in self.path:
            if edge.source != points[-1] or edge.target in points:
                raise ValueError("function source path is disconnected, mixed or self-seeding")
            if any(type(point.node) not in (UseID, ValueID) for point in (edge.source, edge.target)):
                raise ValueError("function source path cannot treat computation/control as reference identity")
            if edge.kind is K.VALUE_USE and edge.meaning is M.VALUE:
                if (type(edge.source.node) is not ValueID or type(edge.target.node) is not UseID
                        or edge.source.namespace != edge.target.namespace
                        or edge.source.context != edge.target.context):
                    raise ValueError("VALUE_USE provenance changed its original operand namespace/context")
            elif edge.kind in (K.BINDING_PAYLOAD, K.BINDING_READ) and edge.meaning is M.BINDING:
                pass
            elif (edge.kind not in (K.ARGUMENT, K.COMPLETION, K.ENVIRONMENT, K.STATE_VALUE, K.BLOCK_ARGUMENT)
                    or edge.meaning not in (M.REFERENCE, M.VALUE, M.BINDING)):
                raise ValueError("function source requires declared reference or binding-field transport")
            points.append(edge.target)

    @property
    def conditions(self):
        return _unique(condition for edge in self.path for condition in edge.conditions)

    @property
    def evidence(self):
        return _unique(evidence for edge in self.path for evidence in edge.evidence)


@dataclass(frozen=True, slots=True)
class ContextualCallTarget:
    """A real CALL and one conditional factory source/interface alternative."""
    call: Point
    callee: Point
    callee_value: Point
    source: ContextualFunctionSource
    interface: StaticCallInterface
    conditions: tuple[Condition, ...] = ()
    evidence: tuple[Evidence, ...] = ()

    def __post_init__(self):
        for point in (self.call, self.callee, self.callee_value):
            _exact(point, Point)
        _exact(self.source, ContextualFunctionSource)
        _exact(self.interface, StaticCallInterface)
        if (type(self.call.node) is not OperationID or type(self.callee.node) is not UseID
                or type(self.callee_value.node) is not ValueID):
            raise TypeError("contextual target needs original CALL operation/callee Use/value")
        if (self.call.namespace != self.callee.namespace or self.call.namespace != self.callee_value.namespace
                or self.call.context != self.callee.context or self.call.context != self.callee_value.context
                or self.source.callable != self.callee):
            raise ValueError("CALL and callable points must retain the exact caller axis/context")
        definition = self.source.creation.creation.definition
        if (self.interface.definition.definition != definition.definition
                or self.interface.definition.source != definition.source):
            raise ValueError("contextual target source and interface name different source definitions")
        _rows(self.conditions, Condition); _rows(self.evidence, Evidence)
        for port in self.interface.arguments:
            if (GraphNamespace.from_source(port.actual_body) != self.call.namespace
                    or port.operation != self.call.node):
                raise ValueError("contextual argument changed its actual caller operation/body")
            binding = self.interface.binding
            if (binding is None or binding.status is not CallBindingStatus.CONDITIONAL
                    or port.parameter not in binding.routes or port.index >= len(binding.arguments)):
                raise ValueError("contextual actual/formal route lacks its original valid binding")
            actual = binding.arguments[port.index]
            if actual.use != port.actual_use or actual.source != port.actual_source:
                raise ValueError("contextual actual/formal route differs from original binding operands")
        if any(route.caller_edge.operation != self.call.node for route in self.interface.completions):
            raise ValueError("contextual completion belongs to another original CALL")
        if any(GraphNamespace.from_source(route.caller) != self.call.namespace
                or route.call_operation != self.call.node or route.callee_use != self.callee.node
                or route.callee_value != self.callee_value.node
                for route in self.interface.environment_routes):
            raise ValueError("environment interface changed its original CALL/callee ports")

    @property
    def frame(self) -> Frame | None:
        body = self.interface.body
        if body is None:
            return None
        return Frame(self.call.namespace, self.call.node, self.callee.node,
            self.callee_value.node, GraphNamespace.from_source(body), self.interface.definition.definition)

    @property
    def callee_context(self) -> DependencyContext:
        frame = self.frame
        return None if frame is None else context_push(self.call.context, frame)

    def _entry(self):
        if self.interface.body is None:
            return None
        namespace = GraphNamespace.from_source(self.interface.body)
        return Point(namespace, self.interface.body.region, self.callee_context)

    def _guards(self):
        entry = self._entry()
        factory_op = Point(self.source.factory.namespace,
            self.source.creation.creation.factory, self.source.factory.context)
        operands = (self.callee, self.callee_value, self.source.factory, factory_op)
        if entry is not None:
            operands += (entry,)
        declared = (
            Condition('scar.contextual-call', 'CALL_SELECTS_THIS_FACTORY_INTERFACE', self.call,
                operands=operands),
            Condition('scar.contextual-call', 'FUNCTION_CODE_MATCHES_FACTORY_CREATION', self.callee_value,
                operands=(self.source.factory, factory_op)),
            Condition('scar.contextual-call', 'FACTORY_COMPLETED_NORMALLY', self.source.factory,
                self.source.creation.creation.normal_edge.successor_index, (factory_op,)),
            Condition('scar.contextual-call', 'CALL_ENTRY_BINDING_VALID', self.call, operands=operands),
        )
        return _unique((*self.source.conditions, *self.conditions, *declared))

    def _proofs(self, rule, anchors):
        sources = [self.call.namespace.graph, self.source.factory.namespace.graph]
        if self.interface.body is not None:
            sources.append(self.interface.body.graph)
        evidence = Evidence(rule, _unique(sources),
            _unique((self.call, self.callee, self.callee_value, self.source.factory, *anchors)))
        return _unique((*self.source.evidence, *self.evidence, evidence))

    def argument_edges(self) -> tuple[Edge, ...]:
        if self.interface.body is None:
            return ()
        edges = []
        context = self.callee_context
        for port in self.interface.arguments:
            actual = Point(self.call.namespace, port.actual_use, self.call.context)
            actual_value = Point(self.call.namespace, port.actual_value, self.call.context)
            formal = Point(GraphNamespace.from_source(port.formal_body), port.formal_value, context)
            guards = (*self._guards(), Condition('scar.contextual-call',
                'ACTUAL_REFERENCE_BOUND_TO_FORMAL', formal,
                operands=(actual, actual_value, self.call, self.source.factory)))
            edges.append(Edge(actual, formal, K.ARGUMENT, M.REFERENCE,
                self._proofs('CONTEXTUAL_SOURCE_ACTUAL_FORMAL_V1', (actual, actual_value, formal)),
                _unique(guards), Strength.MAY))
        return tuple(edges)

    def normal_completion_edges(self) -> tuple[Edge, ...]:
        if self.interface.body is None:
            return ()
        edges = []
        namespace = GraphNamespace.from_source(self.interface.body)
        context = self.callee_context
        entry = self._entry()
        for route in self.interface.completions:
            if (route.kind is not ExitKind.NORMAL or route.value_kind is not ValueKind.REFERENCE
                    or route.completion_index != 0 or route.callee_port.index != 0):
                continue
            landing = Point(self.call.namespace, route.landing_value, self.call.context)
            for terminal in route.terminals:
                returned = Point(namespace, terminal.use, context)
                terminal_value = Point(namespace, terminal.value, context)
                terminal_op = Point(namespace, terminal.operation, context)
                guards = (*self._guards(),
                    Condition('scar.contextual-call', 'CALLEE_COMPLETES_NORMALLY', entry,
                        operands=(self.call, self.source.factory, terminal_op)),
                    Condition('scar.contextual-call', 'CALL_NORMAL_EDGE_SELECTED', self.call,
                        route.caller_edge.successor_index, (self.callee, self.source.factory, entry)),
                    Condition('scar.contextual-call', 'CALLEE_NORMAL_REFERENCE_TERMINAL_SELECTED', terminal_op,
                        route.completion_index, (self.call, self.source.factory, returned, terminal_value)))
                edges.append(Edge(returned, landing, K.COMPLETION, M.REFERENCE,
                    self._proofs('CONTEXTUAL_SOURCE_NORMAL_REFERENCE_COMPLETION_V1',
                        (entry, returned, terminal_value, terminal_op, landing)),
                    _unique(guards), Strength.MAY))
        return tuple(edges)

    def dependency_edges(self) -> tuple[Edge, ...]:
        """Value/reference interfaces only; entry state is not content equality."""
        return (*self.argument_edges(), *self.normal_completion_edges())


__all__ = ['StaticCallInterface', 'ContextualFunctionSource', 'ContextualCallTarget']
