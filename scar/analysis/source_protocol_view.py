"""Shared source bodies behind constructor and descriptor protocols.

Protocol result/world ports and current callable/default projections are
symbolic interfaces. They establish neither allocation nor current object,
storage, MRO or content identity. Original stage guards remain explicit.
"""
import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

from scar.analysis.program_view import ProgramView, _digest
from scar.analysis.source_call_view import Flow, source_call_site, source_caller_scope, source_active_scope, prepare_source_ports
from scar.analysis.source_call_captures import FunctionCaptureStateProvider
from scar.analysis.source_declared_calls import _owners
from scar.analysis.source_protocol_materials import SourceProtocolMaterials
from scar.analysis.source_reference_slice import ReferenceSlicer, source_port
from scar.analysis.source_value_flow import _artifact
from scar.ir.program import normal_targets as T, model as M, view as V, source_protocol_view as R
from scar.ir.program.dependencies import (
    DependencyPoint as Point, DependencyFrame as Frame, DependencyEdge as Edge,
    DependencyKind as K, DependencyMeaning as Meaning, DependencyStrength as Strength,
    DependencyCondition as Condition, DependencyEvidence as Evidence,
    DependencyFrontier as Frontier, DependencyNeighborhood as Neighborhood,
    context_push, context_pop, context_frames, context_is_closed)
from scar.ir.program.ids import ValueID, LocationID, OperationID, UseID, ControlPortID
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.record_codec import encode


@dataclass(frozen=True, slots=True)
class ProtocolRelation:
    source: Point
    target: Point
    interface: tuple[str, int]
    frame: Frame | None
    flow: Flow | None
    kind: K
    meaning: Meaning
    guards: tuple[str, ...]


class SourceProtocolCallProvider:
    """Normalize only demanded caller units; retain original shared bodies."""
    relation_kinds = frozenset((K.CALL_TARGET, K.ARGUMENT, K.ENVIRONMENT, K.PROJECTION,
        K.STATE_LOCATION, K.STATE_INTERFACE, K.COMPLETION, K.RESULT, K.STATE_OUTPUT, K.ORDER, K.CONTAINS))

    def __init__(self, view, materials, *, units=()):
        self.view = view; self.materials = materials
        if view.catalog is None or (view.catalog.path, view.catalog.report) != (materials.catalog.path, materials.catalog.report):
            raise ValueError('protocol graph must share its original source catalog')
        self.records = {}; self.records_by_owner = defaultdict(list); self.record_owners = {}; self.relations = []
        self.in_edges = defaultdict(list); self.out_edges = defaultdict(list); self.pending = defaultdict(set)
        self.frames = {}; self.interfaces = {}; self.owners = {}; self.functions = {}; self.attached = set()
        self.slicer = ReferenceSlicer(SimpleNamespace(fact_store=view.catalog.fact_store))
        self.captures = FunctionCaptureStateProvider(view)
        self.available_units = frozenset(materials.graph.sites[s.site].unit for s in materials.graph.steps) | frozenset(
            materials.members.contexts[e.caller].body.unit for e in (() if materials.members is None else materials.members.edges))
        self.manifests = {}
        for kind, path in (('constructor', materials.path), ('member', materials.member_path)):
            if path is None: continue
            report = json.loads((path/'result.json').read_bytes()); artifact = _artifact(path/'result.json', report['schema'])
            self.manifests[kind] = SourceArtifactLocator(artifact, artifact.sha256, artifact.size_bytes, 'canonical-json')
        for unit in dict.fromkeys(units): self.attach(unit)
        view.register(self)

    @staticmethod
    def _key(point): return point.namespace, point.node

    def _remember(self, source, record, owner):
        point = Point(source.namespace, record.id, None); key = self._key(point)
        if self.records.setdefault(key, record) != record: raise ValueError('protocol value identity collision')
        if self.record_owners.setdefault(key, owner) != owner: raise ValueError('protocol interface owner changed')
        if point.node not in self.records_by_owner[self._key(owner)]: self.records_by_owner[self._key(owner)].append(point.node)
        return point

    def endpoint(self, endpoint):
        if type(endpoint) is T.GlobalPort: return self.view.source_port(endpoint)
        if type(endpoint) is not T.ConstructionPort: raise TypeError('protocol needs its original typed endpoint')
        source = self.view.unit(endpoint.unit); call = self.view.source_port(endpoint.call)
        owner = source._node(endpoint.call.port.template, endpoint.call.port.owner)
        identity = ValueID(_digest(('scar.source-construction-port.v1', source.basis, endpoint)))
        return self._remember(source, R.ConstructionInterfaceValue(identity, endpoint), owner)

    def _relation(self, source, target, key, kind, meaning, guards, frame=None, flow=None):
        if (frame is None) != (flow is None): raise ValueError('protocol context transition needs frame and direction')
        relation = ProtocolRelation(source, target, key, frame, flow, kind, meaning, tuple(guards))
        self.relations.append(relation); self.out_edges[self._key(source)].append(relation); self.in_edges[self._key(target)].append(relation)

    def _function(self, definition):
        if definition.unit not in self.functions:
            source = self.view.unit(definition.unit)
            self.functions[definition.unit] = {source_port(source.facts, f.value): (i, f) for i, f in enumerate(source.facts.functions)}
        return self.functions[definition.unit][definition]

    def _selected_callable(self, key, connection, operation, callee, world, guards):
        source = self.view.namespaces[operation.namespace]; selection = self.interfaces[key]['evidence']
        identity = ValueID(_digest(('scar.protocol-callable-selection.v1', source.basis, callee, connection.source_callable, world, selection)))
        record = R.ProtocolCallableSelection(identity, callee, connection.source_callable, world, selection, self.interfaces[key]['protocol'])
        point = self._remember(source, record, operation)
        self._relation(self.view.source_port(callee), point, key, K.ENVIRONMENT, Meaning.DEPENDENCE, guards)
        self._relation(self.endpoint(world), point, key, K.PROJECTION, Meaning.STATE_INTERFACE, guards)
        self.pending[self._key(point)].add('CURRENT_PROTOCOL_FUNCTION_INSTANCE_AND_DESCRIPTOR_VERSION_NOT_SELECTED')
        return point

    def _default(self, key, connection, route, selected, world, operation, guards):
        ordinal, function = self._function(connection.source_callable); source = self.view.unit(connection.body.unit)
        formals = tuple(source_port(source.facts, p) for p in function.formals[1:-1]); index = formals.index(route.formal)
        initial = function.defaults[index]
        if initial is None or route.actuals != (source_port(source.facts, initial),):
            raise ValueError('protocol default lost its original parameter/creation provenance')
        caller = self.view.namespaces[operation.namespace]
        location_id = LocationID(_digest(('scar.protocol-default-slot.v1', caller.basis, selected.node, connection.source_callable, index)))
        slot = R.ProtocolDefaultSlot(location_id, selected.node, connection.source_callable, index,
            function.parameter_names[index], source_port(source.facts, initial))
        location = self._remember(caller, slot, operation)
        identity = ValueID(_digest(('scar.protocol-default-state.v1', location_id, world)))
        point = self._remember(caller, R.ProtocolDefaultState(identity, location_id, world), operation)
        self._relation(selected, location, key, K.ENVIRONMENT, Meaning.STATE_INTERFACE, guards)
        self._relation(location, point, key, K.STATE_LOCATION, Meaning.STRUCTURE, guards)
        self._relation(self.endpoint(world), point, key, K.PROJECTION, Meaning.STATE_INTERFACE, guards)
        self.pending[self._key(point)].add('CURRENT_PROTOCOL_DEFAULT_MUTATION_HISTORY_NOT_SELECTED')
        return point

    def _body(self, key, unit, record, connection, world, guards, *, source_class=None, receiver=None):
        guards = tuple(dict.fromkeys((*guards, *connection.conditions)))
        if connection.activation is not T.FunctionActivation.NORMAL:
            operation = self.view.unit(unit)._node(self.interfaces[key]['result'].port.template, self.interfaces[key]['result'].port.owner)
            self.pending[self._key(operation)].add('DEFERRED_PROTOCOL_CREATION_IS_NOT_BODY_ENTRY'); return
        facts = self.view.unit(unit).facts; call = record.call
        site = SimpleNamespace(result=source_port(facts, call.result), callee=source_port(facts, call.callee))
        operation, use, value = source_call_site(self.view, site)
        body = self.view.source_region(connection.body.unit, connection.body.template, connection.body.region)
        frame = Frame(operation.namespace, operation.node, use.node, value.node, body.namespace,
            entry=body.node, selection=self.interfaces[key]['evidence'])
        self.frames[key] = frame; self.owners[key] = _owners(facts)[facts.calls.index(call)]
        self._relation(operation, body, key, K.CALL_TARGET, Meaning.DEPENDENCE, guards, frame, Flow.ENTER)
        selected = self._selected_callable(key, connection, operation, site.callee, world, guards)
        function_index, _ = self._function(connection.source_callable)
        provider_facts = self.view.unit(connection.body.unit).facts
        for route in connection.parameters:
            formal = self.endpoint(route.formal); route_guards = (*guards, 'PARAMETER_ROUTE_'+route.kind.value)
            kind = K.ARGUMENT; meaning = Meaning.DEPENDENCE
            if route.kind is T.RouteKind.FUNCTION_ENVIRONMENT:
                actuals = (selected,); kind = K.ENVIRONMENT
                self.captures.bind_connection(connection, route, frame,
                    definition=self.slicer.fact(provider_facts, 'functions', function_index), call=record.fact,
                    reference=self.interfaces[key]['evidence'])
            elif route.kind in (T.RouteKind.INITIAL_DEFAULT, T.RouteKind.CONDITIONAL_DEFAULT):
                actuals = (self._default(key, connection, route, selected, world, operation, route_guards),); kind = K.PROJECTION
            elif route.kind is T.RouteKind.CLASS_RECEIVER:
                actuals = (self.endpoint(receiver) if receiver is not None else value,)
                route_guards += ('CLASS_RECEIVER_TYPE_PROJECTION_NOT_SOURCE_DEFINITION_ALIAS',)
            else:
                actuals = []
                for actual in route.actuals:
                    if type(actual) is T.ConstructionPort: actuals.append(self.endpoint(actual))
                    elif source_class is not None and actual == source_class:
                        actuals.append(value); route_guards += ('CALLEE_VALUE_SELECTS_RECORDED_SOURCE_CLASS',)
                    elif actual.unit == unit: actuals.append(self.endpoint(actual))
                    else:
                        self.endpoint(actual)
                        self.pending[self._key(formal)].add('PROTOCOL_OPERAND_CREATION_CONTEXT_NOT_SELECTED')
                if route.kind is T.RouteKind.STATE: kind = K.STATE_INTERFACE; meaning = Meaning.STATE_INTERFACE
                elif route.kind is T.RouteKind.ARGUMENT: meaning = Meaning.REFERENCE
            for actual in actuals:
                self._relation(actual, formal, key, kind, meaning, route_guards, frame, Flow.ENTER)
        for projection in connection.projections:
            self._relation(self.endpoint(projection.pack), self.endpoint(projection.formal), key,
                K.PROJECTION, Meaning.DEPENDENCE, (*guards, *projection.conditions, projection.kind.value), frame, Flow.ENTER)
        for actual, target in connection.returns:
            target_point = self.endpoint(target)
            state = (type(target) is T.ConstructionPort and target.role is T.ConstructionPortKind.NEW_WORLD
                or type(target) is T.GlobalPort and target == source_port(facts, call.result_world))
            self._relation(self.endpoint(actual), target_point, key,
                K.STATE_INTERFACE if state else K.COMPLETION,
                Meaning.STATE_INTERFACE if state else Meaning.REFERENCE, guards, frame, Flow.RETURN)

    def _prepare(self, unit):
        """Decode each participating unit's template tables once per batch."""
        ports = []; bodies = []
        def connection(row):
            if row is None: return
            bodies.append(row.body); ports.append(row.source_callable)
            for route in row.parameters: ports.extend((route.formal, *route.actuals))
            for source, target in row.returns: ports.extend((source, target))
            for projection in row.projections: ports.extend((projection.pack, projection.formal))
        for step in self.materials.graph.steps:
            if self.materials.graph.sites[step.site].unit != unit: continue
            link = step.link
            ports.extend((link.result, link.callee, link.source_class, *link.inputs, *link.outputs))
            connection(link.connection)
        if self.materials.members is not None:
            for i, edge in enumerate(self.materials.members.edges):
                if self.materials.members.contexts[edge.caller].body.unit != unit: continue
                identity, record = self.materials.member_call(i); facts = self.view.catalog.fact_store.load(identity)
                ports.extend(source_port(facts, p) for p in (record.call.result, record.call.callee, record.call.world, record.call.result_world))
                ports.extend((edge.receiver.point, edge.receiver.source_class)); connection(edge.connection)
        prepare_source_ports(self.view, ports, bodies=bodies)

    def attach(self, unit):
        if unit in self.attached: return
        self._prepare(unit)
        for ordinal, step in enumerate(self.materials.graph.steps):
            site = self.materials.graph.sites[step.site]
            if site.unit != unit: continue
            key = 'constructor', ordinal; link = step.link
            self.interfaces[key] = dict(result=link.result, evidence=self.materials.step_fact(ordinal), protocol=link.stage.value, original=step)
            source = self.view.unit(unit); operation, _, _ = source_call_site(self.view, link)
            self.owners[key] = _owners(source.facts)[source.facts.calls.index(site.record.call)]
            guards = tuple(dict.fromkeys((*link.conditions,
                *(() if link.connection is None else link.connection.conditions), 'CONSTRUCTION_STAGE_'+link.stage.value)))
            for endpoint in (*link.inputs, *link.outputs): self.endpoint(endpoint)
            pending = link.stage in (T.ConstructionStage.NEW_LOOKUP_PENDING, T.ConstructionStage.INIT_LOOKUP_PENDING, T.ConstructionStage.RESULT_TYPE_OPEN)
            if pending:
                for point in (operation, *(self.endpoint(p) for p in (*link.inputs, *link.outputs))):
                    self.pending[self._key(point)].add(link.stage.value+'_UNRESOLVED')
            elif link.connection is not None:
                self._body(key, unit, site.record, link.connection, link.inputs[1], guards, source_class=link.source_class)
            else:
                for output in link.outputs:
                    state = (type(output) is T.ConstructionPort and output.role is T.ConstructionPortKind.NEW_WORLD
                        or type(output) is T.GlobalPort and output == source_port(source.facts, site.record.call.result_world))
                    self._relation(operation, self.endpoint(output), key,
                        K.STATE_OUTPUT if state else K.RESULT, Meaning.STATE_INTERFACE if state else Meaning.DEPENDENCE, guards)
            if link.stage in (T.ConstructionStage.OBJECT_INIT, T.ConstructionStage.RETURN_FOREIGN):
                self._relation(self.endpoint(link.inputs[1]), self.endpoint(source_port(source.facts, site.record.call.result_world)),
                    key, K.STATE_INTERFACE, Meaning.STATE_INTERFACE, guards)
            if link.stage in (T.ConstructionStage.SOURCE_INIT, T.ConstructionStage.OBJECT_INIT, T.ConstructionStage.RETURN_FOREIGN):
                self._relation(self.endpoint(link.inputs[0]), self.endpoint(link.result), key,
                    K.COMPLETION, Meaning.REFERENCE, (*guards, 'CONSTRUCTION_RETURNS_NEW_RESULT_NOT_INIT_DATA'))
                self._relation(self.endpoint(source_port(source.facts, site.record.call.result_world)),
                    self.endpoint(link.result), key, K.ORDER, Meaning.ORDER, guards)
        members = self.materials.members
        if members is not None:
            for ordinal, edge in enumerate(members.edges):
                if members.contexts[edge.caller].body.unit != unit: continue
                identity, record = self.materials.member_call(ordinal); facts = self.view.unit(identity).facts
                key = 'member', ordinal; result = source_port(facts, record.call.result)
                self.interfaces[key] = dict(result=result, evidence=self.materials.member_fact(ordinal), protocol=edge.descriptor.kind.value, original=edge)
                guards = tuple(dict.fromkeys((*edge.conditions, *edge.connection.conditions)))
                self._body(key, identity, record, edge.connection, source_port(facts, record.call.world),
                    guards, source_class=edge.receiver.source_class, receiver=edge.receiver.point)
        self.attached.add(unit); self.materials.check()

    def describe(self, point):
        record = self.records.get(self._key(point))
        if record is None: return None
        self.view.namespaces[point.namespace].check(point)
        if type(record) is R.ProtocolDefaultSlot:
            return V.ProgramNode(point, V.ProgramEntityKind.STATE_LOCATION, V.ProgramNodeRole.STATE_LOCATION,
                replace(self.record_owners[self._key(point)], context=point.context), None)
        state = type(record) is R.ProtocolDefaultState or (type(record) is R.ConstructionInterfaceValue
            and record.endpoint.role is T.ConstructionPortKind.NEW_WORLD)
        type_ = (M.ValueType(M.ValueKind.STATE, location=record.address) if type(record) is R.ProtocolDefaultState else
            self.view.namespaces[point.namespace].graph.profile.world if state else M.ValueType(M.ValueKind.REFERENCE))
        return V.ProgramNode(point, V.ProgramEntityKind.VALUE, V.ProgramNodeRole.CORE_VALUE,
            replace(self.record_owners[self._key(point)], context=point.context), type_)

    def original(self, point):
        if self.describe(point) is None: raise ValueError('unadmitted protocol interface')
        return self.records[self._key(point)]

    def expand(self, point):
        record = self.original(point)
        return tuple(Point(point.namespace, r.id, point.context) for (ns, _), r in self.records.items()
            if ns == point.namespace and type(r) is R.ProtocolDefaultState and r.address == record.id)

    def explain(self, point):
        return dict(node=self.describe(point), original=self.original(point), physical_identity_proven=False,
            allocation_proven=False, content_versions_proven=False, runtime_dispatch_proven=False)

    def _neighbors(self, point, incoming):
        for namespace in dict.fromkeys((point.namespace, *(f.caller for f in context_frames(point.context)))):
            unit = getattr(self.view.namespaces.get(namespace), 'unit', None)
            if unit in self.available_units and unit not in self.attached: self.attach(unit)
        rows = (self.in_edges if incoming else self.out_edges).get(self._key(point), ())
        owned = ((point.node,) if self._key(point) in self.record_owners else ()) if incoming else self.records_by_owner.get(self._key(point), ())
        reasons = set(self.pending.get(self._key(point), ())); edges = []; needs_frame = False; matched = False
        if not rows and not reasons and not owned: return Neighborhood()
        self.materials.check(); self.view.get(point)
        for identity in owned:
            child = Point(point.namespace, identity, point.context)
            owner = replace(self.record_owners[self._key(child)], context=point.context)
            edges.append(Edge(owner, child, K.CONTAINS, Meaning.STRUCTURE,
                (Evidence('scar.source-protocol.contains-interface.v1',
                    (self.view.namespaces[point.namespace].locator, *self.manifests.values()), (owner, child)),)))
        for row in rows:
            if row.frame is None:
                scope = source_active_scope(self.view, row.source.namespace, point.context)
                if scope is not None and scope not in self.owners[row.interface]:
                    reasons.add('SOURCE_CALLER_CODE_SCOPE_DOES_NOT_OWN_CALLSITE'); continue
                contexts = point.context, point.context
            else:
                pop = (incoming and row.flow is Flow.ENTER) or (not incoming and row.flow is Flow.RETURN)
                if pop:
                    needs_frame = True; popped = context_pop(point.context, (row.frame,))
                    if not popped.matched: continue
                    matched = True; caller_context = popped.remaining; callee_context = point.context
                else:
                    caller_context = point.context; callee_context = context_push(caller_context, row.frame)
                scope = source_caller_scope(self.view, row.frame, caller_context)
                if scope is not None and scope not in self.owners[row.interface]:
                    reasons.add('SOURCE_CALLER_CODE_SCOPE_DOES_NOT_OWN_CALLSITE'); continue
                contexts = (caller_context, callee_context) if row.flow is Flow.ENTER else (callee_context, caller_context)
            source, target = replace(row.source, context=contexts[0]), replace(row.target, context=contexts[1])
            kind, ordinal = row.interface; interface = self.interfaces[row.interface]
            call = self.endpoint(interface['result']); call = replace(call, node=self.view.namespaces[call.namespace]._node(
                interface['result'].port.template, interface['result'].port.owner).node,
                context=contexts[0] if row.frame is None or row.flow is Flow.ENTER else contexts[1])
            conditions = tuple(Condition('scar.source-protocol.precondition', guard, call, ordinal) for guard in row.guards)
            locator = replace(self.manifests[kind], pointer='#/tables/'+('constructor_steps' if kind == 'constructor' else 'edges'))
            edges.append(Edge(source, target, row.kind, row.meaning,
                (Evidence('scar.source-protocol.matched-interface.v1', (locator, source.namespace.graph, target.namespace.graph),
                    (call, source, target)),), conditions, Strength.MAY))
        if needs_frame and not matched: reasons.add('SOURCE_PROTOCOL_CALL_FRAME_NOT_SELECTED')
        if edges and not context_is_closed(point.context): reasons.add('SOURCE_CALL_CONTEXT_PREFIX_OPEN')
        return Neighborhood(tuple(dict.fromkeys(edges)), tuple(Frontier(point, r,
            'Protocol dependencies retain original source interfaces and unresolved instances, versions and dispatch.') for r in sorted(reasons)))

    def incoming(self, point): return self._neighbors(point, True)
    def outgoing(self, point): return self._neighbors(point, False)

    def summary(self):
        return dict(available_units=len(self.available_units), units=len(self.attached), interfaces=len(self.interfaces),
            body_frames=len(self.frames), relation_templates=len(self.relations),
            ownership_relations=len(self.records),
            records=dict(Counter(type(r).__name__ for r in self.records.values())),
            pending_endpoint_reasons=sum(map(len, self.pending.values())),
            source_bodies_copied=False, loops_unrolled=False, allocation_proven=False,
            runtime_dispatch_proven=False, namespace_semantics_rederived=False, first_stage_complete=False)


def publish_protocol_view(provider, out):
    """Write small unit shards; source and native bodies remain references."""
    from scar.analysis.normal_output import write_table
    from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
    from scar.analysis.source_template_links import _json
    provider.materials.check(); out = Path(out).absolute()
    if out.exists(): raise ValueError('fresh protocol-view output required')
    _durable_mkdir(out); shards = {}
    for unit in sorted(provider.attached):
        source = provider.view.unit(unit); folder = out/'units'/unit; _durable_mkdir(folder)
        records = tuple(r for (ns, _), r in provider.records.items() if ns == source.namespace)
        rows = dict(construction_values=(r for r in records if type(r) is R.ConstructionInterfaceValue),
            callables=(r for r in records if type(r) is R.ProtocolCallableSelection),
            default_slots=(r for r in records if type(r) is R.ProtocolDefaultSlot),
            default_states=(r for r in records if type(r) is R.ProtocolDefaultState),
            relations=(r for r in provider.relations if provider.interfaces[r.interface]['result'].unit == unit))
        tables = {name: write_table(folder/(name+'.jsonl.gz'), values) for name, values in rows.items()}
        shards[unit] = dict(path='units/'+unit, namespace=encode(source.namespace), tables=tables)
    provider.materials.check()
    parents = dict(constructors=encode(_artifact(provider.materials.path/'result.json', provider.materials.report['schema'])))
    if provider.materials.member_path is not None:
        parents['members'] = encode(_artifact(provider.materials.member_path/'result.json', provider.materials.member_report['schema']))
    report = dict(schema='scar.source-protocol-view', schema_version=1, catalog=str(provider.view.catalog.path),
        constructors=str(provider.materials.path), members=None if provider.materials.member_path is None else str(provider.materials.member_path),
        parents=parents, shards=shards, summary=provider.summary(),
        producer_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        types_sha256=sha256(Path(R.__file__).read_bytes()).hexdigest(),
        original_interfaces_rechecked=True, namespace_semantics_rederived=False, runtime_dispatch_proven=False,
        allocation_proven=False, canonical_body_bytes_copied=0, target_executed=False, first_stage_complete=False,
        stored_bytes=sum(t['bytes'] for shard in shards.values() for t in shard['tables'].values()))
    _durable_bytes(out/'result.json', _json(report), replace=False)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True); parser.add_argument('--catalog', required=True)
    parser.add_argument('--members'); parser.add_argument('--unit', action='append', default=[])
    parser.add_argument('--out', help='optional fresh directory for compact unit shards')
    args = parser.parse_args(); view = ProgramView(args.catalog)
    materials = SourceProtocolMaterials(args.source, view.catalog, members=args.members)
    provider = SourceProtocolCallProvider(view, materials, units=args.unit)
    if args.out and not args.unit:
        for unit in sorted(provider.available_units): provider.attach(unit)
    report = publish_protocol_view(provider, args.out) if args.out else provider.summary()
    print(json.dumps(report), flush=True)


if __name__ == '__main__': main()
