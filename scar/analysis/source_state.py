"""Attach source binding interfaces and may versions to the common graph.

No source parsing or target execution. Original C2 interfaces select symbolic
addresses; the existing matched-control solver supplies definition choices.
This adapter does not infer object contents from a stable reference binding.
"""
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

from scar.analysis.program_view import _digest
from scar.analysis.source_effects import classify_instruction
from scar.analysis.source_name_access_anchors import _bindings, anchor_name_accesses
from scar.analysis.source_name_definitions import reaching_name_definitions
from scar.analysis.source_namespace_interfaces import NamespacePlanView
from scar.analysis.source_reference_slice import source_port
from scar.analysis.source_value_flow import project_value_flow
from scar.analysis.source_consumer_parents import _stamp
from scar.ir.program import source_state as S, source_productions as P
from scar.ir.program import normal_graph as G, normal_links as F, normal_targets as T
from scar.ir.program import view as V, model as M
from scar.ir.program.source_bindings import EnvironmentInterface
from scar.ir.program.source_name_definitions import NameDefinitionKind as D
from scar.ir.program.dependencies import (DependencyPoint as Point, DependencyEdge,
    DependencyKind as K, DependencyMeaning as Meaning, DependencyStrength as Strength,
    DependencyEvidence, DependencyCondition, DependencyFrontier, DependencyNeighborhood)
from scar.ir.program.ids import LocationID, OperationID, ValueID


class SourceStateProvider:
    def __init__(self, view, unit):
        self.view = view; self.source = view.project_unit(unit)
        self.material = self.source.material; self.namespace = self.source.namespace
        self.bindings, self.declarations, self.materials = _bindings(self.material, {})
        self.interface_ids = {descriptor:index for index,descriptor in enumerate(self.bindings.interfaces)}
        self._guard = {Path(m.uri):_stamp(Path(m.uri)) for m in self.materials}
        self.locations = {}; self.versions = {}; self.accesses = []; self.requests = {}
        self.in_edges = defaultdict(list); self.out_edges = defaultdict(list)
        self.tracks = []; self.track_ids = {}; self.selections = []; self.track_limits = []
        self.flows = {}; self.anchors = None
        self.read_frontiers = defaultdict(list)
        self.content_provider = None
        for key, plan in self.source.plans.items():
            context = NamespacePlanView(unit, plan)
            for step in plan.steps:
                operation = self.source._identity(OperationID, key, step.id)
                rule = classify_instruction(step.instruction)
                accesses = self._identify(context, step, operation)
                missing = (() if accesses else ('STATE_ADDRESS_PROJECTION_NOT_IMPLEMENTED',)) if rule.resolution.value == 'ADDRESS_RULE' else ()
                self.requests[operation] = S.SourceEffectRequest(operation, rule, accesses, missing,
                    ('CALLBACK_OBJECT_CONTENT_ALIAS_RNG_EXTERNAL_AND_ORDERING_EFFECTS_NOT_CLOSED',))
        view.register(self)

    def content(self):
        """Attach object/index requests to the same source namespace."""
        if self.content_provider is None:
            from scar.analysis.source_content import SourceContentProvider
            self.content_provider = SourceContentProvider(self)
        return self.content_provider

    def _name(self, name):
        return self.declarations.names[name.index].value if name.kind == 'SOURCE' else name.symbol

    def _location(self, descriptor, key):
        # Lexical interfaces refer to the same original slot even when reached
        # through different environment descriptors. A frame/cell is still a
        # parameter, not a physical identity inferred from the source slot.
        if descriptor.kind in ('LEXICAL_BINDING', 'CLASS_PROTOCOL_CELL'):
            slot = self.bindings.bindings[descriptor.binding]
            if self._name(slot.name) != key:
                raise ValueError('state key differs from original lexical binding')
            descriptor = EnvironmentInterface('LEXICAL_BINDING', slot.owner, descriptor.binding)
        identity = LocationID(_digest(('scar.source-binding-location.v1', self.source.basis, descriptor, key)))
        self.locations.setdefault(identity, S.BindingLocationTemplate(identity, self.material.unit, descriptor, key))
        return identity

    def _alternative(self, interface, key, ordinal=None, lookup=None):
        descriptor = self.bindings.interfaces[interface]
        return S.BindingAccessAlternative(self._location(descriptor, key), interface, ordinal,
            None if lookup is None else lookup.on_hit,
            None if lookup is None else lookup.on_miss,
            None if lookup is None else lookup.on_exception)

    def _identify(self, context, step, operation):
        ins = step.instruction; kind = None; index = None; alternatives = (); missing = None
        payload = None; owner_handles = ()
        if type(ins) in (P.AccessBinding, P.DeleteExceptionBinding, P.BindTypeParameter):
            index = ins.parameter.binding_port if type(ins) is P.BindTypeParameter else ins.port
            port = self.bindings.ports[index]
            if port.name is None: raise ValueError('binding access lacks its original name')
            key = self._name(port.name)
            kind = (S.BindingAccessKind.DELETE if type(ins) is P.DeleteExceptionBinding else
                S.BindingAccessKind.WRITE if type(ins) is P.BindTypeParameter else S.BindingAccessKind(ins.action.value))
            if kind is S.BindingAccessKind.READ:
                if port.read_plan is None: raise ValueError('read lacks original lookup plan')
                plan = self.bindings.plans[port.read_plan]
                alternatives = tuple(self._alternative(s.interface, key, i, s) for i,s in enumerate(plan.steps))
                missing = plan.missing_outcome; payload = context.result(step)
            else:
                # Exception-handler cleanup uses the original Store port under
                # CLEAR_ON_HANDLER_EXIT; do not manufacture a source Del port.
                if type(ins) is P.BindTypeParameter:
                    if port.declref is None or port.resolution is None:
                        raise ValueError('type parameter lacks its original declaration/resolution')
                    contribution = self.declarations.contributions[port.declref]
                    resolution = self.bindings.resolutions[port.resolution]
                    binding = resolution.binding
                    if (contribution.port != index or 'TYPE_PARAMETER_INTERFACE' not in contribution.operations
                            or binding is None or self.bindings.bindings[binding].domain != 'TYPE_PARAMETER_BINDING'
                            or self.bindings.bindings[binding].name != port.name or resolution.name != port.name):
                        raise ValueError('type parameter is not an original binding admission')
                    slot = self.bindings.bindings[binding]
                    descriptor = EnvironmentInterface('LEXICAL_BINDING', slot.owner, binding)
                    alternatives = (S.BindingAccessAlternative(self._location(descriptor, key), self.interface_ids.get(descriptor), None),)
                else:
                    target = port.write_target if kind is S.BindingAccessKind.WRITE or type(ins) is P.DeleteExceptionBinding else port.delete_target
                    if target is None: raise ValueError('binding update lacks original target')
                    alternatives = (self._alternative(target, key),)
                if kind is S.BindingAccessKind.WRITE: payload = context.value(step.arguments[0])
        elif type(ins) is P.AccessClassProtocol:
            slot = self.bindings.bindings[ins.binding]
            if ins.binding not in ins.interface.protocol_bindings:
                raise ValueError('class protocol access is outside its declared interface')
            descriptor = EnvironmentInterface('CLASS_PROTOCOL_CELL', slot.owner, ins.binding)
            alternatives = (S.BindingAccessAlternative(self._location(descriptor, self._name(slot.name)), self.interface_ids.get(descriptor), None),)
            kind = S.BindingAccessKind.HANDLE if ins.action is P.ClassProtocolActionKind.CELL_REFERENCE else S.BindingAccessKind.WRITE
            payload = context.result(step) if kind is S.BindingAccessKind.HANDLE else context.value(step.arguments[1])
        else:
            from scar.analysis.source_implicit_namespaces import identify_implicit_namespace
            implicit = identify_implicit_namespace(self.bindings, self.declarations, context, step)
            if implicit is not None:
                kind = implicit.kind; payload = implicit.payload; missing = implicit.missing_outcome
                owner_handles = implicit.owner_handles
                read = kind is S.BindingAccessKind.READ
                alternatives = tuple(S.BindingAccessAlternative(self._location(descriptor, implicit.key),
                    self.interface_ids.get(descriptor), ordinal if read else None,
                    'RETURN_VALUE' if read else None,
                    ('NEXT' if ordinal+1<len(implicit.descriptors) else missing) if read else None,
                    'PROPAGATE' if read else None)
                    for ordinal,descriptor in enumerate(implicit.descriptors))
        if kind is None: return ()
        before, after = context.worlds(step)
        record = S.BindingAccessTemplate(operation, context.site(step), context.owner(step.region).owner,
            kind, index, alternatives, payload, before, after, missing)
        ordinal = len(self.accesses); self.accesses.append(record)
        op = Point(self.namespace, operation)
        for branch, alternative in enumerate(alternatives):
            location = Point(self.namespace, alternative.location)
            condition = DependencyCondition('scar.source-state.address', 'SELECTED_ACTIVATION_AND_LOOKUP_BRANCH',
                op, branch, (location,))
            read = kind in (S.BindingAccessKind.READ, S.BindingAccessKind.HANDLE)
            self._edge(location if read else op, op if read else location,
                K.ENVIRONMENT if kind is S.BindingAccessKind.HANDLE else K.STATE_INPUT if read else K.STATE_OUTPUT,
                Meaning.STATE_INTERFACE, (condition,), 'scar.source-state.binding-interface.v1')
            if owner_handles and owner_handles[branch] is not None:
                handle = self.view.source_port(owner_handles[branch])
                selected = DependencyCondition('scar.source-state.address-owner',
                    self.locations[alternative.location].interface.kind, op, branch, (handle, location))
                self._edge(handle, location, K.ENVIRONMENT, Meaning.STATE_INTERFACE, (selected,),
                    'scar.source-state.explicit-namespace-owner.v1')
        return (ordinal,)

    def _edge(self, source, target, kind, meaning, conditions=(), rule='scar.source-state.binding-version.v1', strength=Strength.EXACT):
        evidence = DependencyEvidence(rule, (self.source.locator,), (source, target))
        edge = DependencyEdge(source, target, kind, meaning, (evidence,), tuple(conditions), strength)
        if edge not in self.out_edges[source.node]:
            self.out_edges[source.node].append(edge); self.in_edges[target.node].append(edge)
        return edge

    def track(self, source_function, namespace, **limits):
        """Join the original may definitions; no static last-writer shortcut.

        Only a function's own lexical slot can use this intraprocedural solver.
        Captured/mapping/object-content state remains an explicit interface.
        """
        self.check()
        if (type(namespace) is not F.Namespace or namespace.kind is not F.NamespaceKind.LEXICAL
                or type(namespace.owner) is not int or not 0 <= namespace.owner < len(self.bindings.bindings)):
            raise ValueError('binding track requires a complete original lexical slot')
        functions = [f for f in self.source.facts.functions if source_port(self.source.facts, f.value) == source_function]
        if len(functions) != 1: raise ValueError('binding track source is not a unique original function')
        function = functions[0]; slot = self.bindings.bindings[namespace.owner]
        if (slot.domain != 'LOCAL_BINDING' or slot.owner != function.environment.scope
                or self._name(slot.name) != namespace.name):
            raise ValueError('captured/nonlocal/name-mismatched slot needs its selected environment interface')
        key = source_function, namespace
        limits = dict(max_states=limits.get('max_states', 20000), max_stack=limits.get('max_stack', 128),
            max_updates=limits.get('max_updates', 1000000), **{k:v for k,v in limits.items()
                if k not in ('max_states', 'max_stack', 'max_updates')})
        if key in self.track_ids:
            index = self.track_ids[key]
            if limits != self.track_limits[index]: raise ValueError('cached binding track has different traversal limits')
            return self.tracks[index]
        if self.anchors is None:
            self.anchors = anchor_name_accesses(self.view.catalog, self.material.unit, material=self.material)
        if source_function not in self.flows:
            body = T.Body(self.material.unit, function.template, function.body)
            self.flows[source_function] = project_value_flow(self.material, source_function, body)
        graph = reaching_name_definitions(self.view.catalog, source_function, namespace,
            anchor_graph=self.anchors, material=self.material, flow=self.flows[source_function], **limits)
        ordinal = len(self.tracks); self.track_ids[key] = ordinal; self.tracks.append(graph); self.track_limits.append(limits)
        location = self._location(EnvironmentInterface('LEXICAL_BINDING', slot.owner, namespace.owner), namespace.name)
        for index, definition in enumerate(graph.definitions):
            identity = ValueID(_digest(('scar.source-binding-version.v1', self.source.basis, source_function,
                namespace, index, definition)))
            bound = (S.BindingBoundness.BOUND if definition.kind in (D.FORMAL, D.WRITE) else
                S.BindingBoundness.UNBOUND if definition.kind is D.DELETE else S.BindingBoundness.UNKNOWN)
            version = S.BindingVersionTemplate(identity, location, source_function, namespace,
                index, definition.kind, bound, definition.value)
            self.versions[identity] = version
            value = Point(self.namespace, identity); address = Point(self.namespace, location)
            self._edge(address, value, K.STATE_LOCATION, Meaning.STRUCTURE)
            site = self.view.source_port(T.GlobalPort(self.material.unit, definition.site))
            selected = DependencyCondition('scar.source-state.version', 'SAME_ACTIVATION_AND_DEFINITION_OCCURRENCE',
                site, index, (value, address))
            self._edge(site, value, K.STATE_OUTPUT, Meaning.STATE_INTERFACE, (selected,))
            if definition.value is not None:
                payload = self.view.source_port(definition.value)
                self._edge(payload, value, K.BINDING_PAYLOAD, Meaning.BINDING, (selected,))
        by_definition = {v.definition:v.id for v in self.versions.values()
            if v.source_function == source_function and v.namespace == namespace}
        for index, read in enumerate(graph.reads):
            access = graph.anchor_graph.accesses[read.access]
            op = self.source._identity(OperationID, access.site.port.template, access.site.port.owner)
            target = Point(self.namespace, op)
            versions = tuple(by_definition[n] for n in read.definitions)
            self.selections.append(S.BindingReadSelection(ordinal, index, read.access, read.state, versions))
            self.read_frontiers[op].extend(frontier.reason for frontier in graph.frontiers)
            condition = DependencyCondition('scar.source-state.read', 'MATCHED_RECIPE_STATE_AND_FRAME_SELECTED',
                target, index, (self.view.source_port(source_function),))
            for identity in versions:
                self._edge(Point(self.namespace, identity), target, K.BINDING_READ, Meaning.BINDING,
                    (condition,), strength=Strength.MAY)
        return graph

    def effects(self, operation):
        self.check()
        if type(operation) is Point:
            self.source.check(operation); operation = operation.node
        return self.requests[operation]

    def check(self, point=None):
        self.source.check(point)
        if any(_stamp(path) != stamp for path,stamp in self._guard.items()):
            raise ValueError('admitted original binding/declaration material changed')

    def describe(self, point):
        if point.namespace != self.namespace: return None
        self.check(point)
        if point.node in self.locations:
            return V.ProgramNode(point, V.ProgramEntityKind.STATE_LOCATION, V.ProgramNodeRole.STATE_LOCATION, None, None)
        if point.node in self.versions:
            version = self.versions[point.node]
            return V.ProgramNode(point, V.ProgramEntityKind.VALUE, V.ProgramNodeRole.CORE_VALUE, None,
                M.ValueType(M.ValueKind.STATE, location=version.location))
        return None

    def original(self, point):
        if self.describe(point) is None: raise ValueError('state endpoint is not admitted')
        return self.locations[point.node] if point.node in self.locations else self.versions[point.node]

    def expand(self, point):
        self.original(point)
        if point.node not in self.locations: return ()
        return tuple(Point(self.namespace, v.id, point.context) for v in self.versions.values() if v.location == point.node)

    def explain(self, point):
        return dict(node=self.describe(point), original=self.original(point),
            source_material=self.material.result_artifact, c2_materials=self.materials,
            binding_versions_not_object_or_tensor_content=True, runtime_instance_selected=False)

    def _neighbors(self, point, incoming):
        if point.namespace != self.namespace: return DependencyNeighborhood()
        self.check(point)
        rows = self.in_edges[point.node] if incoming else self.out_edges[point.node]
        edges = tuple(replace(edge, source=replace(edge.source, context=point.context),
            target=replace(edge.target, context=point.context), conditions=tuple(replace(c,
                subject=None if c.subject is None else replace(c.subject, context=point.context),
                operands=tuple(replace(p, context=point.context) for p in c.operands)) for c in edge.conditions)) for edge in rows)
        frontiers = []
        if point.node in self.locations or point.node in self.versions:
            frontiers.append(DependencyFrontier(point, 'STATE_INSTANCE_AND_OBJECT_CONTENT_NOT_SELECTED',
                'Static binding versions require a frame/occurrence and do not identify tensor contents.'))
        for reason in dict.fromkeys(self.read_frontiers.get(point.node, ())):
            frontiers.append(DependencyFrontier(point, 'SOURCE_BINDING_'+reason,
                'Original matched-control definition analysis retains this unresolved alternative.'))
        return DependencyNeighborhood(edges, tuple(dict.fromkeys(frontiers)))

    def incoming(self, point): return self._neighbors(point, True)
    def outgoing(self, point): return self._neighbors(point, False)
