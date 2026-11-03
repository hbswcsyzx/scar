"""Project conditional factory origins through the common dependency graph.

The owner supplies original-input discovery and fresh replay. Context choices
are explicit: a known suffix never converts an unknown prefix into a root.
No factory operation becomes a new CALL, invocation, state entry or graph.
"""
from __future__ import annotations

from dataclasses import replace

from scar.ir.program.dependencies import (
    DependencyCondition, DependencyEdge, DependencyEvidence, DependencyFrontier,
    DependencyKind, DependencyMeaning, DependencyNeighborhood, DependencyPoint,
    DependencyStrength, GraphNamespace, OpenDependencyContext,
)
from scar.ir.program.environments import EnvironmentRole
from scar.ir.program.function_origins import FactoryEntryOriginCondition, StaticFactoryEntryOrigin
from scar.ir.program.model import ReferenceValue
from scar.ir.program.source_references import SourceArtifactLocator


class FactoryEntryOriginDependencyProvider:
    """Project original references; neither origins nor contexts are closed.

    ``origins_for(point)`` streams (derived origin, original evidence tuple).
    ``validate_origin`` freshly replays its original inputs on every use.
    ``interface_scope(point, outgoing)`` identifies actual MAKE ports or root
    FUNCTION_OBJECT/G members, independently of successful discovery.
    Optional context/frontier callbacks expose the owner's original interface
    choices and precise missing inputs. The query's own context cannot change.
    """
    relation_kinds = frozenset((DependencyKind.ENVIRONMENT,))

    def __init__(self, *, origins_for, load_index, validate_origin, interface_scope,
                 contexts_for=None, discovery_frontiers=None):
        if any(not callable(callback) for callback in (origins_for, load_index, validate_origin, interface_scope)):
            raise TypeError("factory origin provider requires original-input callbacks")
        if any(callback is not None and not callable(callback)
               for callback in (contexts_for, discovery_frontiers)):
            raise TypeError("factory origin context/coverage callbacks must be callable")
        self.origins_for, self.load_index, self.validate_origin = origins_for, load_index, validate_origin
        self.interface_scope = interface_scope
        self.contexts_for, self.discovery_frontiers = contexts_for, discovery_frontiers

    def incoming(self, point):
        return self._neighbors(point, False)

    def outgoing(self, point):
        return self._neighbors(point, True)

    @staticmethod
    def _evidence_sources(origin, sources):
        if (type(sources) is not tuple or origin.creator.graph not in sources or origin.body.graph not in sources
                or any(type(locator) is not SourceArtifactLocator for locator in sources)):
            raise ValueError("factory origin evidence must include its original creator/body graphs")
        allowed = {"#/graph", "#/static_compilation", "#/module/declaration/compilation", "#/class/compilation"}
        for locator in sources:
            original = next((namespace.graph for namespace in (origin.creator, origin.body)
                if locator.artifact == namespace.graph.artifact
                and locator.decoded_sha256 == namespace.graph.decoded_sha256
                and locator.decoded_bytes == namespace.graph.decoded_bytes), None)
            if original is None or locator.pointer not in allowed:
                raise ValueError("factory origin evidence is not an original graph/compiler record")

    def _neighbors(self, point, outgoing):
        if type(point) is not DependencyPoint:
            raise TypeError("factory origin query needs an original dependency point")
        scoped = self.interface_scope(point, outgoing)
        if type(scoped) is not bool:
            raise TypeError("factory origin scope must explicitly select original ports")
        if not scoped:
            return DependencyNeighborhood()
        edges, frontiers = {}, {}

        def note(kind, detail):
            frontiers[DependencyFrontier(point, kind, detail)] = None

        try:
            for origin, sources in self.origins_for(point):
                if type(origin) is not StaticFactoryEntryOrigin:
                    raise TypeError("factory origin provider received an untyped origin")
                origin.__post_init__()
                creator, body = GraphNamespace.from_source(origin.creator), GraphNamespace.from_source(origin.body)
                source_node = origin.source_use or origin.source_value
                expected = (creator, source_node) if outgoing else (body, origin.member.reference)
                if (point.namespace, point.node) != expected:
                    continue
                if self.validate_origin(origin) is not True:
                    raise ValueError("factory origin was not freshly replayed against its original inputs")
                creator_index, body_index = self.load_index(creator), self.load_index(body)
                if (type(creator_index.values[origin.source_value]) is not ReferenceValue
                        or origin.source_use is not None
                        and creator_index.use_site(origin.source_use).use.value != origin.source_value):
                    raise ValueError("factory origin changed its original source reference port")
                environments = [environment for environment in body_index.graph.environments
                    if environment.id == origin.environment and origin.member in environment.members]
                if len(environments) != 1 or type(body_index.values[origin.member.reference]) is not ReferenceValue:
                    raise ValueError("factory origin changed its original entry environment member")
                callable_members = [member for member in environments[0].members
                    if member.role is EnvironmentRole.FUNCTION_OBJECT]
                if len(callable_members) != 1:
                    raise ValueError("factory origin environment lacks its original unique callable port")
                self._evidence_sources(origin, sources)
                choices = (self.contexts_for(origin, point, outgoing) if self.contexts_for is not None else
                    ((point.context, None),) if outgoing else ((None, point.context),))
                for creator_context, entry_context in choices:
                    if (creator_context if outgoing else entry_context) != point.context:
                        raise ValueError("factory origin projection changed the query's selected context")
                    source = DependencyPoint(creator, source_node, creator_context)
                    target = DependencyPoint(body, origin.member.reference, entry_context)
                    anchor = DependencyPoint(creator, origin.creation.factory, creator_context)
                    normal = DependencyPoint(creator, origin.creation.normal_value, creator_context)
                    entry_callable = DependencyPoint(body, callable_members[0].reference, entry_context)
                    evidence = DependencyEvidence("STATIC_FACTORY_ENTRY_REFERENCE_ORIGIN_V1", sources,
                        (anchor, normal, entry_callable))
                    conditions = []
                    for condition in origin.conditions:
                        relational = condition in (
                            FactoryEntryOriginCondition.ENTRY_CALLABLE_FROM_THIS_FACTORY_OCCURRENCE,
                            FactoryEntryOriginCondition.FUNCTION_CODE_MATCHES_CREATION)
                        selected = DependencyCondition.from_enum(condition)
                        conditions.append(replace(selected, subject=entry_callable if relational else normal,
                            index=origin.creation.normal_edge.successor_index
                            if condition is FactoryEntryOriginCondition.FACTORY_COMPLETED_NORMALLY else None,
                            operands=(normal, anchor) if relational else ()))
                    edge = DependencyEdge(source, target, DependencyKind.ENVIRONMENT, DependencyMeaning.REFERENCE,
                        (evidence,), tuple(conditions), DependencyStrength.MAY)
                    edges[edge] = None
                    for context, side in ((creator_context, "FACTORY_CREATION"), (entry_context, "FUNCTION_ENTRY")):
                        if context is None:
                            note(side + "_CONTEXT_UNSELECTED", "Original ports are known; this side has no selected interface stack.")
                        elif type(context) is OpenDependencyContext:
                            note(side + "_CONTEXT_OPEN_PREFIX", "Original interface suffix is known; its outer prefix remains unknown.")
        except (OverflowError, TimeoutError) as error:
            note("FACTORY_ORIGIN_QUERY_BUDGET", type(error).__name__ + ": " + str(error))
        if self.discovery_frontiers is not None:
            try:
                for frontier in self.discovery_frontiers(point, outgoing):
                    if type(frontier) is not DependencyFrontier or frontier.point != point:
                        raise TypeError("factory discovery must report typed frontiers at the original query point")
                    frontiers[frontier] = None
            except (OverflowError, TimeoutError) as error:
                note("FACTORY_ORIGIN_COVERAGE_BUDGET", type(error).__name__ + ": " + str(error))
        note("ENTRY_CALLABLE_FACTORY_SELECTION_OPEN", "The entry callable must derive from this source factory occurrence; no invocation or identity is established.")
        note("FUNCTION_ENTRY_ORIGIN_SET_OPEN", "Known alternatives do not close entry origins, outer contexts or namespace contents.")
        return DependencyNeighborhood(tuple(edges), tuple(frontiers), enumerated=False)


__all__ = ["FactoryEntryOriginDependencyProvider"]
