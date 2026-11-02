"""Project explicitly supplied, freshly replayed factory-origin references.

Discovery and publication are intentionally absent.  The caller supplies the
one shared index loader and an original-input replay callback.  An unselected
creator/entry context remains None; no MAKE operation becomes a caller frame.
"""
from __future__ import annotations

from dataclasses import replace

from scar.ir.program.dependencies import (
    DependencyCondition, DependencyEdge, DependencyEvidence, DependencyFrontier,
    DependencyKind, DependencyMeaning, DependencyNeighborhood, DependencyPoint,
    DependencyStrength, GraphNamespace,
)
from scar.ir.program.environments import EnvironmentRole
from scar.ir.program.function_origins import FactoryEntryOriginCondition, StaticFactoryEntryOrigin
from scar.ir.program.ids import UseID
from scar.ir.program.model import ReferenceValue
from scar.ir.program.source_references import SourceArtifactLocator


class FactoryEntryOriginDependencyProvider:
    """``origins_for(point)`` yields (derived origin, original evidence tuple).

    ``validate_origin(origin)`` must replay from receipt-checked original inputs
    on every use and return True, or reject.  It is not a cached PASS flag.
    ``interface_scope(point, outgoing)`` identifies original normal/capture or
    entry-member ports from owned body metadata/protocols.  An empty origin list
    must not change that scope; unrelated literals must not be claimed as MAKEs.
    Neither a stored origin record nor completeness of its origin set is
    asserted.  A source occurrence can denote multiple runtime factories.
    """
    relation_kinds = frozenset((DependencyKind.ENVIRONMENT,))

    def __init__(self, *, origins_for, load_index, validate_origin, interface_scope):
        if any(not callable(callback) for callback in (origins_for, load_index, validate_origin, interface_scope)):
            raise TypeError("factory origin provider requires explicit original-input callbacks")
        self.origins_for, self.load_index, self.validate_origin = origins_for, load_index, validate_origin
        self.interface_scope = interface_scope

    def incoming(self, point):
        return self._neighbors(point, False)

    def outgoing(self, point):
        return self._neighbors(point, True)

    def _neighbors(self, point, outgoing):
        if type(point) is not DependencyPoint:
            raise TypeError("factory origin query needs an original dependency point")
        edges, frontiers = {}, {}
        index = self.load_index(point.namespace)
        scoped = self.interface_scope(point, outgoing)
        if type(scoped) is not bool:
            raise TypeError("factory origin interface scope must explicitly select original ports")
        relevant = scoped or (any(member.reference == point.node and member.role in (
            EnvironmentRole.FUNCTION_OBJECT, EnvironmentRole.GLOBALS_NAMESPACE)
            for environment in index.graph.environments for member in environment.members) if not outgoing else False)

        def note(kind, detail):
            frontiers[DependencyFrontier(point, kind, detail)] = None

        try:
            for origin, sources in self.origins_for(point):
                if type(origin) is not StaticFactoryEntryOrigin:
                    raise TypeError("factory origin provider received an untyped origin")
                origin.__post_init__()
                if self.validate_origin(origin) is not True:
                    raise ValueError("factory origin was not freshly replayed against its original inputs")
                creator, body = GraphNamespace.from_source(origin.creator), GraphNamespace.from_source(origin.body)
                source_node = origin.source_use or origin.source_value
                if outgoing:
                    if (point.namespace, point.node) != (creator, source_node):
                        continue
                    source, target = point, DependencyPoint(body, origin.member.reference, None)
                else:
                    if (point.namespace, point.node) != (body, origin.member.reference):
                        continue
                    source, target = DependencyPoint(creator, source_node, None), point
                relevant = True
                creator_index, body_index = self.load_index(creator), self.load_index(body)
                value = (creator_index.use_site(source.node).use.value
                    if type(source.node) is UseID else source.node)
                if value != origin.source_value or type(creator_index.values[value]) is not ReferenceValue:
                    raise ValueError("factory origin changed its original source reference port")
                environments = [environment for environment in body_index.graph.environments
                    if environment.id == origin.environment and origin.member in environment.members]
                if len(environments) != 1 or type(body_index.values[target.node]) is not ReferenceValue:
                    raise ValueError("factory origin changed its original entry environment member")
                callable_members = [member for member in environments[0].members
                    if member.role is EnvironmentRole.FUNCTION_OBJECT]
                if len(callable_members) != 1:
                    raise ValueError("factory origin environment lacks its original unique callable port")
                if (type(sources) is not tuple or origin.creator.graph not in sources or origin.body.graph not in sources
                        or any(type(locator) is not SourceArtifactLocator for locator in sources)):
                    raise ValueError("factory origin evidence must include its original creator/body graphs")
                allowed = {"#/graph", "#/static_compilation", "#/module/declaration/compilation", "#/class/compilation"}
                for locator in sources:
                    original = next((namespace.graph for namespace in (creator, body)
                        if locator.artifact == namespace.graph.artifact
                        and locator.decoded_sha256 == namespace.graph.decoded_sha256
                        and locator.decoded_bytes == namespace.graph.decoded_bytes), None)
                    if original is None or locator.pointer not in allowed:
                        raise ValueError("factory origin evidence is not an original graph/compiler record")
                anchor = DependencyPoint(creator, origin.creation.factory, source.context)
                normal = DependencyPoint(creator, origin.creation.normal_value, source.context)
                entry_callable = DependencyPoint(body, callable_members[0].reference, target.context)
                evidence = DependencyEvidence("STATIC_FACTORY_ENTRY_REFERENCE_ORIGIN_V1", sources,
                    (anchor, normal, entry_callable))
                conditions = []
                for condition in origin.conditions:
                    subject = (entry_callable if condition in (
                        FactoryEntryOriginCondition.ENTRY_CALLABLE_FROM_THIS_FACTORY_OCCURRENCE,
                        FactoryEntryOriginCondition.FUNCTION_CODE_MATCHES_CREATION) else
                        normal if condition is FactoryEntryOriginCondition.FACTORY_COMPLETED_NORMALLY else anchor)
                    selected = DependencyCondition.from_enum(condition)
                    conditions.append(replace(selected, subject=subject,
                        index=origin.creation.normal_edge.successor_index
                        if condition is FactoryEntryOriginCondition.FACTORY_COMPLETED_NORMALLY else None,
                        operands=(normal, anchor) if condition in (
                            FactoryEntryOriginCondition.ENTRY_CALLABLE_FROM_THIS_FACTORY_OCCURRENCE,
                            FactoryEntryOriginCondition.FUNCTION_CODE_MATCHES_CREATION) else ()))
                edge = DependencyEdge(source, target, DependencyKind.ENVIRONMENT, DependencyMeaning.REFERENCE,
                    (evidence,), tuple(conditions),
                    DependencyStrength.MAY)
                edges[edge] = None
                if source.context is None:
                    note("FACTORY_CREATION_CONTEXT_UNSELECTED", "Original creator ports are known; a creation context has not been selected.")
                if target.context is None:
                    note("FUNCTION_ENTRY_CONTEXT_UNSELECTED", "Original entry ports are known; an entry caller context has not been selected.")
        except (OverflowError, TimeoutError) as error:
            relevant = True
            note("FACTORY_ORIGIN_QUERY_BUDGET", type(error).__name__ + ": " + str(error))
        if relevant:
            note("ENTRY_CALLABLE_FACTORY_SELECTION_OPEN", "The entry callable must derive from this exact source factory occurrence; no invocation or identity is established.")
            note("FUNCTION_ENTRY_ORIGIN_SET_OPEN", "Explicitly supplied factory alternatives do not close the set of entry origins or captured namespace contents.")
        return DependencyNeighborhood(tuple(edges), tuple(frontiers), enumerated=not relevant)


__all__ = ["FactoryEntryOriginDependencyProvider"]
