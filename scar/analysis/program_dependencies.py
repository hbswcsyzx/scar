"""One dependency interface over original local and cross-fragment records.

Providers project existing facts on demand. The view does not clone callees,
execute targets, manufacture ports, or interpret dependence as value equality.
"""
from __future__ import annotations

from collections import OrderedDict, defaultdict, deque
from dataclasses import dataclass, replace

from scar.ir.program.dependencies import (DependencyCondition, DependencyEdge,
    DependencyEvidence, DependencyFrame, DependencyFrontier, DependencyKind as K,
    DependencyMeaning as M, DependencyNeighborhood, DependencyPoint, DependencyStrength, GraphNamespace)
from scar.ir.program.ids import (BlockID, ControlPortID, EnvironmentInterfaceID, LocationID, OperationID, RegionID,
    NativeBoundaryID, ProviderID, ResourceDefinitionID, ResourceRequirementID, UseID, ValueID)
from scar.ir.program.model import (BlockArgument, CompletionResult, OperationResult,
    ReferenceValue, StateVersionValue, TerminatorKind, UseRole)
from scar.ir.program.bindings import BindingState
from scar.ir.program.resources import CreatedResource, ExternalResource


STRUCTURAL_KINDS = frozenset((K.CONTAINS, K.CONTROL_FLOW, K.SEQUENCE, K.STATE_LOCATION))


@dataclass(frozen=True, slots=True)
class DependencyWalk:
    roots: tuple[DependencyPoint, ...]
    points: tuple[DependencyPoint, ...]
    edges: tuple[DependencyEdge, ...]
    frontiers: tuple[DependencyFrontier, ...]
    direction: str
    traversal_exhausted: bool
    kinds: tuple[K, ...] = tuple(K)

    @property
    def dependence_closed(self):
        return (frozenset(self.kinds) >= frozenset(K) - STRUCTURAL_KINDS
            and self.traversal_exhausted and not self.frontiers and not any(
            edge.conditions or edge.strength is DependencyStrength.MAY for edge in self.edges)
        )


@dataclass(frozen=True, slots=True)
class DependencyCut:
    """A representation cut, not an authorization to replace its operations.

    Interface/implementation relations are reported separately from data
    escaping to consumers; crossing an implementation edge is not an escape.
    """
    operations: tuple[DependencyPoint, ...]
    members: tuple[DependencyPoint, ...]
    inputs: tuple[DependencyEdge, ...]
    outputs: tuple[DependencyEdge, ...]
    interfaces: tuple[DependencyEdge, ...]
    frontiers: tuple[DependencyFrontier, ...]
    transformation_authorized: bool = False


class ProgramDependencyGraph:
    """Composable typed adjacency; source graphs remain the sole authority."""

    def __init__(self, load_index, *, providers=(), max_local_edges=200000):
        if not callable(load_index):
            raise TypeError("dependency view needs a shared original graph loader")
        self.load_index = load_index
        self.local = LocalDependencyProvider(load_index, max_cached_edges=max_local_edges)
        from scar.analysis.program_control_dependencies import ControlDependencyProvider
        self.control = ControlDependencyProvider(load_index)
        self.providers = [self.local, self.control]
        for provider in providers:
            self.register(provider)

    def register(self, provider):
        if not all(callable(getattr(provider, name, None)) for name in ("incoming", "outgoing")):
            raise TypeError("dependency provider must implement incoming/outgoing")
        self.providers.append(provider)
        return provider

    def neighborhood(self, point, *, direction="incoming", kinds=None):
        if type(point) is not DependencyPoint or direction not in ("incoming", "outgoing"):
            raise ValueError("select a qualified endpoint and incoming/outgoing direction")
        if point.context and point.context[-1].target != point.namespace:
            raise ValueError("selected context does not end at the original endpoint namespace")
        if kinds is not None:
            kinds = frozenset(kinds)
            if any(type(kind) is not K for kind in kinds):
                raise TypeError("dependency kind filters must be typed")
        edges, frontiers, enumerated = {}, {}, True
        for provider in self.providers:
            relation_kinds = getattr(provider, "relation_kinds", None)
            if kinds is not None and relation_kinds is not None and not kinds.intersection(relation_kinds):
                continue
            try:
                result = getattr(provider, direction)(point)
            except (OverflowError, TimeoutError) as error:
                result = DependencyNeighborhood(frontiers=(DependencyFrontier(point,
                    "DEPENDENCY_PROVIDER_BUDGET", type(error).__name__ + ": " + str(error)),), enumerated=False)
            if type(result) is not DependencyNeighborhood:
                raise TypeError("dependency provider returned an untyped neighborhood")
            enumerated = enumerated and result.enumerated
            for edge in result.edges:
                endpoint = edge.target if direction == "incoming" else edge.source
                if endpoint != point:
                    raise ValueError("dependency provider mixed endpoints or call contexts")
                if kinds is None or edge.kind in kinds:
                    edges[edge] = edge
            for frontier in result.frontiers:
                frontiers[frontier] = frontier
        return DependencyNeighborhood(tuple(edges), tuple(frontiers), enumerated)

    def incoming(self, point, *, kinds=None):
        return self.neighborhood(point, direction="incoming", kinds=kinds)

    def outgoing(self, point, *, kinds=None):
        return self.neighborhood(point, direction="outgoing", kinds=kinds)

    def walk(self, roots, *, direction="incoming", kinds=None, max_points=4096,
             max_edges=16384, max_depth=128, include_structure=False):
        roots = tuple(roots)
        if not roots or any(type(root) is not DependencyPoint for root in roots):
            raise TypeError("dependency walk needs original qualified roots")
        if direction not in ("incoming", "outgoing"):
            raise ValueError("walk direction must be incoming or outgoing")
        if any(type(bound) is not int or bound < 1 for bound in (max_points, max_edges, max_depth)):
            raise ValueError("dependency walk needs positive explicit bounds")
        selected = (frozenset(kinds) if kinds is not None else
            frozenset(K) if include_structure else frozenset(K) - STRUCTURAL_KINDS)
        pending = deque((root, 0) for root in roots)
        seen, edges, frontiers = {}, {}, {}
        exhausted = True
        while pending:
            point, depth = pending.popleft()
            if point in seen:
                continue
            if len(seen) >= max_points:
                item = DependencyFrontier(point, "DEPENDENCY_POINT_BUDGET", "Unvisited endpoint remains in the declared traversal frontier.")
                frontiers[item] = item; exhausted = False
                break
            seen[point] = point
            neighborhood = self.neighborhood(point, direction=direction, kinds=selected)
            exhausted = exhausted and neighborhood.enumerated
            frontiers.update((item, item) for item in neighborhood.frontiers)
            for edge in neighborhood.edges:
                if not include_structure and edge.meaning is M.STRUCTURE:
                    continue
                if edge not in edges and len(edges) >= max_edges:
                    item = DependencyFrontier(point, "DEPENDENCY_EDGE_BUDGET", "Additional original dependencies were not traversed.")
                    frontiers[item] = item; exhausted = False
                    pending.clear()
                    break
                edges[edge] = edge
                other = edge.source if direction == "incoming" else edge.target
                if other in seen:
                    continue
                if depth >= max_depth:
                    item = DependencyFrontier(other, "DEPENDENCY_DEPTH_BUDGET", "Original dependency endpoint retained beyond this traversal depth.")
                    frontiers[item] = item; exhausted = False
                else:
                    pending.append((other, depth + 1))
        return DependencyWalk(roots, tuple(seen), tuple(edges), tuple(frontiers), direction, exhausted,
                              tuple(kind for kind in K if kind in selected))

    def cut(self, operations, *, max_members=16384):
        """List original edges crossing an explicitly selected operation set."""
        operations = tuple(dict.fromkeys(operations))
        if not operations or any(type(point) is not DependencyPoint or type(point.node) is not OperationID
                                 for point in operations):
            raise TypeError("dependency cut needs qualified original Operation endpoints")
        if type(max_members) is not int or max_members < 1:
            raise ValueError("dependency cut needs a positive membership bound")
        if len(operations) > max_members:
            raise OverflowError("dependency cut membership budget exhausted")
        members = dict.fromkeys(operations)
        for point in operations:
            index = self.load_index(point.namespace)
            operation = index.operations[point.node]
            owned = [use.id for use in operation.uses] + list(operation.results)
            if operation.terminator is not None:
                for successor in operation.terminator.successors:
                    owned.extend(formal for actual, formal in zip(successor.arguments,
                        index._block_records[successor.block].arguments) if type(actual) is CompletionResult)
            for identity in owned:
                members[DependencyPoint(point.namespace, identity, point.context)] = None
                if len(members) > max_members:
                    raise OverflowError("dependency cut membership budget exhausted")
        inputs, outputs, interfaces, notes = {}, {}, {}, {}
        interface_kinds = frozenset((K.CALL_TARGET, K.IMPLEMENTATION, K.ARGUMENT,
            K.COMPLETION, K.ENVIRONMENT, K.FIELD_INITIALIZER, K.STATE_INTERFACE))
        for point in members:
            for direction in ("incoming", "outgoing"):
                neighborhood = self.neighborhood(point, direction=direction)
                notes.update((item, item) for item in neighborhood.frontiers)
                if not neighborhood.enumerated:
                    item = DependencyFrontier(point, "DEPENDENCY_BOUNDARY_ENUMERATION_OPEN",
                        "The selected " + direction + " neighborhood was not fully enumerated.")
                    notes[item] = item
                for edge in neighborhood.edges:
                    if edge.kind in STRUCTURAL_KINDS or edge.meaning is M.STRUCTURE:
                        continue
                    if edge.source in members and edge.target in members:
                        continue
                    if edge.kind in interface_kinds or (edge.meaning is M.STATE_INTERFACE and (
                            edge.source.namespace != edge.target.namespace or edge.source.context != edge.target.context)):
                        interfaces[edge] = edge
                    elif edge.target in members:
                        inputs[edge] = edge
                    else:
                        outputs[edge] = edge
        return DependencyCut(operations, tuple(members), tuple(inputs), tuple(outputs),
                             tuple(interfaces), tuple(notes))


class LocalDependencyProvider:
    """Core def/use, CFG, state, resources and explicit region-call interfaces.

    Sequential position and containment are structural relations, deliberately
    distinct from required ordering or a data/control-dependence proof.
    """

    def __init__(self, load_index, *, max_cached_edges=200000):
        if type(max_cached_edges) is not int or max_cached_edges < 1:
            raise ValueError("local dependency cache needs a positive edge bound")
        self.load_index, self.maximum = load_index, max_cached_edges
        self._cache, self._cached_edges = OrderedDict(), 0

    def _tables(self, namespace):
        # Loader validates every supplied namespace/declaration even if the
        # immutable fragment's decoded graph is shared by its private cache.
        index = self.load_index(namespace)
        if namespace in self._cache:
            self._cache.move_to_end(namespace)
            return self._cache[namespace]
        rows = self._build(namespace, index)
        count = sum(len(edges) for edges in rows[0].values())
        if count <= self.maximum:
            while self._cache and self._cached_edges + count > self.maximum:
                _, removed = self._cache.popitem(last=False)
                self._cached_edges -= removed[4]
            rows = (*rows, count)
            self._cache[namespace] = rows
            self._cached_edges += count
        else:
            rows = (*rows, count)
        return rows

    def _neighborhood(self, point, incoming):
        before, after, frontiers, members, _ = self._tables(point.namespace)
        if point.node not in members:
            raise ValueError("dependency point is absent from its original graph fragment")
        templates = (before if incoming else after).get(point.node, ())
        def contextual(endpoint):
            return replace(endpoint, context=point.context)
        edges = tuple(replace(edge, source=contextual(edge.source), target=contextual(edge.target),
            evidence=tuple(replace(item, anchors=tuple(contextual(anchor) for anchor in item.anchors))
                for item in edge.evidence),
            conditions=tuple(replace(condition, subject=contextual(condition.subject))
                if condition.subject is not None else condition for condition in edge.conditions)) for edge in templates)
        notes = tuple(DependencyFrontier(point, kind, detail) for kind, detail in frontiers.get(point.node, ()))
        if point.context is None:
            notes += (DependencyFrontier(point, "CALL_CONTEXT_UNKNOWN", "Original local structure is retained; no caller activation is selected."),)
        # Direct region-call edges carry a different context transition and
        # are generated on demand rather than flattening shared callees.
        interfaces = self._region_calls(point, self.load_index(point.namespace), incoming, templates)
        return DependencyNeighborhood((*edges, *interfaces.edges), (*notes, *interfaces.frontiers))

    def incoming(self, point):
        return self._neighborhood(point, True)

    def outgoing(self, point):
        return self._neighborhood(point, False)

    @staticmethod
    def _build(namespace, index):
        graph = index.graph
        before, after, frontiers = defaultdict(list), defaultdict(list), defaultdict(list)
        members = set(index.values) | set(index.operations) | set(index.regions) | set(index.locations) | set(index._uses) | set(index._blocks)
        members.update(item.id for item in (*graph.resources, *graph.resource_requirements,
            *graph.environments, *graph.control_ports, *graph.provider_envelopes, *graph.native_boundaries))
        def point(node):return DependencyPoint(namespace, node)
        evidence = DependencyEvidence("CANONICAL_PROGRAM_RELATIONS_V1", (namespace.graph,))
        def edge(source, target, kind, meaning=M.DEPENDENCE, conditions=(), strength=DependencyStrength.EXACT, *, provenance=None):
            item = DependencyEdge(point(source), point(target), kind, meaning,
                (evidence,) if provenance is None else provenance, conditions, strength)
            before[target].append(item); after[source].append(item)
        def declaration(rule, *paths, anchors):
            return (DependencyEvidence(rule, tuple(replace(namespace.graph,
                pointer=namespace.graph.pointer + '/' + path) for path in paths),
                tuple(point(anchor) for anchor in anchors)),)
        def control_condition(operation, number):
            return (DependencyCondition("canonical", "SUCCESSOR_SELECTED", point(operation), number),)
        for region in graph.regions:
            edge(region.id, region.entry, K.CONTROL_FLOW, M.STRUCTURE)
            if region.parent is not None:edge(region.parent, region.id, K.CONTAINS, M.STRUCTURE)
            for block in region.blocks:
                edge(region.id, block.id, K.CONTAINS, M.STRUCTURE)
                for value in block.arguments:edge(block.id, value, K.CONTAINS, M.STRUCTURE)
                previous = None
                for identity in block.operations:
                    edge(block.id, identity, K.CONTAINS, M.STRUCTURE)
                    if previous is not None:edge(previous, identity, K.SEQUENCE, M.STRUCTURE)
                    previous = identity
        for value in graph.values:
            if type(value.origin) is OperationResult:
                kind = K.STATE_OUTPUT if type(value) is StateVersionValue else K.RESULT
                edge(value.origin.operation, value.id, kind)
            elif type(value.origin) is BlockArgument:
                pass  # Actual predecessor and call mappings below define inputs.
            else:
                edge(value.region, value.id, K.CONTAINS, M.STRUCTURE)
            if type(value) is StateVersionValue:
                edge(value.location, value.id, K.STATE_LOCATION, M.STRUCTURE)
            if type(value) is ReferenceValue:
                if value.targets is not None:
                    for target in value.targets:
                        edge(value.id, target, K.ALIAS, M.DEPENDENCE,
                            (DependencyCondition("canonical", "DECLARED_POINTS_TO", point(value.id)),), DependencyStrength.MAY)
                else:
                    frontiers[value.id].append(("ALIAS_TARGETS_OPEN", "Reference and producer are known; mutable-location alias targets are not closed."))
        for operation_position, operation in enumerate(graph.operations):
            for use in operation.uses:
                kind = K.ORDER if use.role is UseRole.STATE_ORDER else K.STATE_INPUT if use.role is UseRole.STATE_CONTENT else K.VALUE_USE
                meaning = M.ORDER if kind is K.ORDER else M.STATE_INTERFACE if kind is K.STATE_INPUT else M.VALUE
                edge(use.value, use.id, kind, meaning)
                edge(use.id, operation.id, K.OPERAND if kind is K.VALUE_USE else kind)
                edge(operation.id, use.id, K.CONTAINS, M.STRUCTURE)
            for access in operation.accesses:
                edge(access.location, operation.id, K.STATE_LOCATION, M.STRUCTURE)
            if not operation.effects_complete:
                frontiers[operation.id].append(("EFFECT_SUMMARY_OPEN", "Original effects are not closed; empty visible reads/writes do not establish purity."))
            term = operation.terminator
            if term is None:continue
            if term.condition is not None:edge(term.condition, operation.id, K.CONTROL_CONDITION)
            for number, successor in enumerate(term.successors):
                conditions = control_condition(operation.id, number)
                edge(operation.id, successor.block, K.CONTROL_FLOW, M.STRUCTURE, conditions)
                block = index._block_records[successor.block]
                for argument_position, (actual, formal) in enumerate(zip(successor.arguments, block.arguments)):
                    if type(actual) is UseID:
                        meaning = M.STATE_INTERFACE if type(index.values[formal]) is StateVersionValue else M.VALUE
                        edge(actual, formal, K.BLOCK_ARGUMENT, meaning, conditions)
                    elif type(actual) is CompletionResult:
                        kind = K.STATE_OUTPUT if type(index.values[formal]) is StateVersionValue else K.RESULT
                        # The result slot is an original static port mapping,
                        # not an unresolved execution predicate. Keep its
                        # exact record as evidence; the selected successor is
                        # the actual path condition.
                        projection = 'operations/' + str(operation_position) + '/terminator/successors/' + str(number) + '/arguments/' + str(argument_position)
                        edge(operation.id, formal, kind, M.DEPENDENCE, conditions,
                            provenance=declaration('CANONICAL_COMPLETION_RESULT_PROJECTION_V1', projection,
                                anchors=(operation.id, formal)))
                    else:
                        frontiers[formal].append(("SPECIAL_SUCCESSOR_INPUT_OPEN", "Resumption or driver input retains its original protocol interface; transfer rule is pending."))
        for ordering in graph.ordering:edge(ordering.before, ordering.after, K.ORDER, M.ORDER)
        for ordinal, environment in enumerate(graph.environments):
            path='environments/'+str(ordinal)
            edge(environment.region, environment.id, K.CONTAINS, M.STRUCTURE,
                provenance=declaration('CANONICAL_ENVIRONMENT_DECLARATION_V1',path,
                    anchors=(environment.region,environment.id)))
            for position, member in enumerate(environment.members):
                member_path=path+'/members/'+str(position)
                member_evidence=declaration('CANONICAL_ENVIRONMENT_MEMBER_V1',member_path,
                    anchors=(environment.id,member.reference))
                edge(environment.id, member.reference, K.CONTAINS, M.STRUCTURE,
                    provenance=member_evidence)
                for location_position, location in enumerate(member.locations):
                    edge(location, member.reference, K.STATE_LOCATION, M.STRUCTURE,
                        provenance=declaration('CANONICAL_ENVIRONMENT_STATE_DOMAIN_V1',member_path,
                            member_path+'/locations/'+str(location_position),
                            anchors=(environment.id,member.reference,location)))
            frontiers[environment.id].extend((
                ('ENVIRONMENT_BINDING_IDENTITY_OPEN',
                    'Original code definition and ordered member ports are declared; active function/environment identity is not established.'),
                ('ENVIRONMENT_STATE_COVERAGE_OPEN',
                    'Member locations are declared necessary state domains; they do not close reads, aliases or mutable contents.')))
        scopes={scope.id:(ordinal,scope) for ordinal,scope in enumerate(graph.control_scopes)}
        region_positions={region.id:ordinal for ordinal,region in enumerate(graph.regions)}
        for ordinal, port in enumerate(graph.control_ports):
            scope_position,scope=scopes[port.scope]
            path='control_ports/'+str(ordinal)
            scope_path='control_scopes/'+str(scope_position)
            edge(scope.region,port.id,K.CONTAINS,M.STRUCTURE,
                provenance=declaration('CANONICAL_CONTROL_PORT_DECLARATION_V1',path,scope_path,
                    anchors=(scope.region,port.id)))
            if port.block is not None:
                edge(port.id,port.block,K.CONTROL_FLOW,M.STRUCTURE,
                    provenance=declaration('CANONICAL_CONTROL_PORT_BLOCK_DESTINATION_V1',path,scope_path,
                        anchors=(port.id,port.block)))
            else:
                region=index.regions[scope.region]
                exit_position=next(i for i,item in enumerate(region.exits) if item.name==port.exit)
                exit_path='regions/'+str(region_positions[scope.region])+'/exits/'+str(exit_position)
                edge(port.id,scope.region,K.CONTROL_FLOW,M.STRUCTURE,
                    provenance=declaration('CANONICAL_CONTROL_PORT_NAMED_EXIT_DESTINATION_V1',path,scope_path,exit_path,
                        anchors=(port.id,scope.region)))
            frontiers[port.id].append(('CONTROL_PORT_TRANSFER_RELATIONS_OPEN',
                'The original completion destination is declared; pending/cleanup transfer relations are not projected by this declaration-only interface.'))
        # A binding token is not its Python object payload. These typed
        # projections retain that distinction instead of declaring alias.
        for binding in graph.binding_definitions:
            if binding.state is BindingState.BOUND:
                edge(binding.payload, binding.value, K.BINDING_PAYLOAD, M.BINDING)
            elif binding.state is BindingState.UNKNOWN:
                frontiers[binding.value].append(("LOCAL_BINDING_PAYLOAD_OPEN",
                    "This SSA binding update has an unknown payload; its previous token is not an unchanged-value proof."))
        for read in graph.binding_reads:
            if read.normal_result is not None:
                edge(read.binding, read.normal_result, K.BINDING_READ, M.BINDING,
                    (DependencyCondition("canonical.binding", "READ_NORMAL_REQUIRES_BOUND", point(read.operation)),))
        for resource in graph.resources:
            if type(resource.origin) is CreatedResource:
                edge(resource.origin.operation, resource.id, K.RESOURCE)
            elif type(resource.origin) is ExternalResource:
                edge(resource.origin.region, resource.id, K.RESOURCE)
                frontiers[resource.id].append(("EXTERNAL_RESOURCE_INPUT",
                    "Declared external resource port " + resource.origin.port
                    + "; no supplying resource interface is selected by this local graph."))
        for requirement in graph.resource_requirements:
            edge(requirement.id, requirement.owner, K.RESOURCE)
            for relation in requirement.relations:
                conditions = (DependencyCondition("canonical.resource.constraint", relation.relation.value,
                    point(requirement.id)),)
                # Binding either requirement constrains the other. This is
                # a static constraint, not observed sharing or data transfer.
                edge(relation.other, requirement.id, K.RESOURCE, conditions=conditions)
                edge(requirement.id, relation.other, K.RESOURCE, conditions=conditions)
        for use in graph.resource_uses:
            edge(use.requirement, use.operation, K.RESOURCE)
            if use.definition is not None:edge(use.definition, use.requirement, K.RESOURCE)
            if use.handle is not None:edge(use.handle, use.requirement, K.RESOURCE)
        for location in graph.resource_locations:edge(location.resource, location.location, K.RESOURCE)
        from scar.analysis.program_native_dependencies import native_declaration_relations
        native_edges, native_frontiers = native_declaration_relations(namespace, index)
        for item in native_edges:
            before[item.target.node].append(item); after[item.source.node].append(item)
        for item in native_frontiers:
            frontiers[item.point.node].append((item.kind, item.detail))
        for identity in members:
            if type(identity) not in (OperationID, ValueID, UseID, BlockID, RegionID, LocationID,
                    ResourceDefinitionID, ResourceRequirementID, EnvironmentInterfaceID, ControlPortID,
                    NativeBoundaryID, ProviderID):
                frontiers[identity].append(("PROTOCOL_ENTITY_RELATIONS_OPEN", "Original typed entity is present; its protocol-specific relation projection remains open."))
        return before, after, frontiers, members

    def _region_calls(self, point, index, incoming, templates):
        candidates = []
        # A selected inner frame is the only route back to a local caller.
        if point.context:
            frame = point.context[-1]
            if frame.target == point.namespace and frame.entry is not None:
                candidates.append((frame, point.context[:-1]))
        operation_ids = set()
        if type(point.node) is OperationID:operation_ids.add(point.node)
        elif type(point.node) is UseID:operation_ids.add(index.use_site(point.node).operation)
        elif type(point.node) is ValueID:
            origin = index.values[point.node].origin
            if type(origin) is OperationResult:operation_ids.add(origin.operation)
            operation_ids.update(edge.source.node for edge in templates if type(edge.source.node) is OperationID)
        for identity in operation_ids:
            operation = index.operations[identity]
            if operation.callee is None:continue
            body = point.namespace.source_body
            definition = body.definition if body is not None and operation.callee == point.namespace.root else None
            frame = DependencyFrame(point.namespace, operation.id, None, None, point.namespace,
                definition=definition, entry=operation.callee)
            if point.context is not None:candidates.append((frame, point.context))
        rows, notes = {}, []
        for frame, outer in dict.fromkeys(candidates):
            if frame.caller != point.namespace or frame.target != point.namespace:continue
            operation = index.operations.get(frame.operation)
            if operation is None or operation.callee != frame.entry:continue
            inner = (*outer, frame)
            evidence = DependencyEvidence("CANONICAL_REGION_INTERFACE_V1", (point.namespace.graph,))
            def emit(source, target, kind, meaning=M.DEPENDENCE):
                item = DependencyEdge(source, target, kind, meaning, (evidence,))
                if (item.target if incoming else item.source) == point:rows[item] = item
            def endpoint(node, context):return DependencyPoint(point.namespace, node, context)
            emit(endpoint(operation.id, outer), endpoint(frame.entry, inner), K.CALL_TARGET)
            formals = index.entry_arguments(frame.entry)
            arguments = operation.invoke_arguments if operation.terminator is not None else operation.call_arguments
            for actual, formal in zip(arguments, formals):
                meaning = M.STATE_INTERFACE if type(formal) is StateVersionValue else M.VALUE
                emit(endpoint(actual, outer), endpoint(formal.id, inner), K.ARGUMENT, meaning)
            if operation.terminator is not None:
                if operation.terminator.kind is TerminatorKind.INVOKE:
                    from scar.ir.program.native import ExitPortRef
                    region = index.regions[frame.entry]
                    by_kind = {exit_.kind: exit_ for exit_ in region.exits}
                    for successor_number, successor in enumerate(operation.terminator.successors):
                        exit_ = by_kind.get(successor.kind)
                        if exit_ is None:continue
                        block = index._block_records[successor.block]
                        for actual, formal in zip(successor.arguments, block.arguments):
                            if type(actual) is not CompletionResult:continue
                            kind = K.STATE_INTERFACE if type(index.values[formal]) is StateVersionValue else K.COMPLETION
                            meaning = M.STATE_INTERFACE if kind is K.STATE_INTERFACE else M.VALUE
                            for terminal in index.exit_port_uses(ExitPortRef(frame.entry, exit_.name, actual.index)):
                                item = DependencyEdge(endpoint(terminal.use.id, inner), endpoint(formal, outer),
                                    kind, meaning, (evidence,), (DependencyCondition("canonical", "SUCCESSOR_SELECTED",
                                        endpoint(operation.id, outer), successor_number),))
                                if (item.target if incoming else item.source) == point:rows[item] = item
                continue
            region = index.regions[frame.entry]
            normal = [exit_ for exit_ in region.exits if exit_.kind.value == "NORMAL"]
            if len(normal) == 1:
                from scar.ir.program.native import ExitPortRef
                for ordinal, result in enumerate(operation.results):
                    if ordinal >= len(normal[0].types):break
                    is_state = type(index.values[result]) is StateVersionValue
                    for terminal in index.exit_port_uses(ExitPortRef(frame.entry, normal[0].name, ordinal)):
                        emit(endpoint(terminal.use.id, inner), endpoint(result, outer),
                            K.STATE_INTERFACE if is_state else K.COMPLETION,
                            M.STATE_INTERFACE if is_state else M.VALUE)
        return DependencyNeighborhood(tuple(rows), tuple(dict.fromkeys(notes)))
