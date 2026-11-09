"""Conditional Python normalization and canonical native interfaces in one view.

Conversions and return wrapping are dependencies, never reference/storage
identity. Native bodies stay shared; original named-match frames select their
caller. This adapter neither executes the target nor proves parser/dispatch.
"""
import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
import json

from scar.analysis.program_view import ProgramView
from scar.analysis.source_binding_native_graph import BindingNativeStore
from scar.analysis.native_state import NativeStateSession
from scar.analysis.native_state_materials import NativeStateMaterials
from scar.analysis.source_call_view import Flow, source_call_site, source_caller_scope, prepare_source_ports
from scar.analysis.source_declared_calls import DeclaredCallStore, _owners
from scar.analysis.source_reference_slice import source_port
from scar.analysis.source_value_flow import _artifact
from scar.ir.program import software_resources as S
from scar.ir.program.dependencies import (
    DependencyPoint as Point, DependencyFrame as Frame, DependencyEdge as Edge,
    DependencyCondition as Condition, DependencyEvidence as Evidence,
    DependencyKind as K, DependencyMeaning as Meaning, DependencyStrength as Strength,
    DependencyFrontier as Frontier, DependencyNeighborhood as Neighborhood,
    context_push, context_pop, context_frames, context_is_closed)
from scar.ir.program.ids import OperationID, ValueID, UseID, ControlPortID
from scar.ir.program.source_references import SourceArtifactLocator


@dataclass(frozen=True, slots=True)
class NativeCallRelation:
    source: Point
    target: Point
    frame: Frame
    flow: Flow
    kind: K
    meaning: Meaning
    interface: tuple[str, int]
    table: str
    ordinal: int
    guards: tuple[str, ...]
    frontier: str | None = None


class SourceNativeCallProvider:
    """Attach source normalization shards on demand, with matched return paths."""
    relation_kinds = frozenset((K.CALL_TARGET, K.ARGUMENT, K.COMPLETION, K.STATE_INTERFACE))

    def __init__(self, view, source, *, native=None, units=()):
        self.view = view
        self.store = source if isinstance(source, BindingNativeStore) else BindingNativeStore(source)
        if view.catalog is None or str(view.catalog.path) != json.loads(self.store.parents.source_raw)['catalog']:
            raise ValueError('native normalization and source view need the same original catalog')
        self.native = native if native is not None else NativeStateSession(NativeStateMaterials(self.store.path), view=view)
        if (self.native.view is not view or self.native.materials.path != self.store.path
                or self.native.materials.report != self.store.report):
            raise ValueError('native normalization needs the same authenticated native publication and view')
        self.graphs = {}; self.frames = {}; self.interfaces = {}; self.owners = {}
        self.relations = []; self.in_edges = defaultdict(list); self.out_edges = defaultdict(list)
        self.available_units = frozenset(self.store.report['shards'])
        artifact = _artifact(self.store.path/'result.json', self.store.report['schema'])
        self.manifest = SourceArtifactLocator(artifact, artifact.sha256, artifact.size_bytes, 'canonical-json')
        for unit in dict.fromkeys(units): self.attach(unit)
        view.register(self)

    @staticmethod
    def _key(point): return point.namespace, point.node

    def _relation(self, source, target, frame, flow, kind, meaning, key, table, ordinal, guards, frontier=None):
        relation = NativeCallRelation(source, target, frame, flow, kind, meaning, key, table, ordinal, guards, frontier)
        self.relations.append(relation)
        self.out_edges[self._key(source)].append(relation)
        self.in_edges[self._key(target)].append(relation)

    def attach(self, unit):
        if unit in self.graphs: return self.graphs[unit]
        graph = self.store.read_unit(unit)
        if not graph.outputs:
            self.graphs[unit] = graph
            return graph
        source = self.view.unit(unit); facts = source.facts
        owners = _owners(facts)
        call_owners = {source_port(facts, call.result): owners[i] for i, call in enumerate(facts.calls)}
        matches = {self.store.parents.match_reference(unit, i): row.candidate
            for i, row in enumerate(self.store.parents.matches(unit))}
        ports=[]
        for output in graph.outputs:
            ports.extend((output.result,output.world,output.result_world,matches[output.match].site.callee))
        for row in graph.inputs:ports.extend((row.dependency.call,*row.dependency.actuals))
        prepare_source_ports(self.view,ports)
        grouped = defaultdict(list)
        for i, row in enumerate(graph.inputs): grouped[row.match].append((i, row))
        for ordinal, output in enumerate(graph.outputs):
            key = unit, ordinal; candidate = matches[output.match]; site = candidate.site
            if (site.result, site.world, site.result_world) != (output.result, output.world, output.result_world):
                raise ValueError('native output wrapper differs from its original source call')
            operation, use, value = source_call_site(self.view, site)
            selector = self.store.by_id[output.binding].native.selector
            namespace = self.native.selectors[selector]; native = self.native.providers[namespace]
            if (native.unit.boundary.id != output.boundary or native.unit.boundary.outputs != output.native_outputs):
                raise ValueError('native normalization changed canonical boundary coordinates')
            frame = Frame(operation.namespace, operation.node, use.node, value.node,
                namespace, entry=namespace.root, selection=output.match)
            self.frames[key] = frame; self.interfaces[key] = output; self.owners[key] = call_owners[site.result]
            self._relation(operation, Point(namespace, namespace.root, None), frame, Flow.ENTER,
                K.CALL_TARGET, Meaning.DEPENDENCE, key, 'outputs', ordinal, output.conditions)
            for index, row in grouped[output.match]:
                dep = row.dependency
                if (dep.binding, dep.boundary, dep.call) != (output.binding, output.boundary, output.result):
                    raise ValueError('normalization input left its original named-match interface')
                formal = native.index.entry_port(dep.native_port)
                target = Point(namespace, formal.id, None)
                guards = (*dep.conditions, 'OPERAND_SOURCE_'+dep.kind.value)
                if row.aggregation: guards += (row.aggregation,)
                frontier = None
                if dep.kind in (S.OperandSourceKind.RECEIVER_OPEN, S.OperandSourceKind.CONVERSION_OPEN):
                    frontier = 'NATIVE_'+dep.kind.value
                if dep.default_expression is not None:
                    guards += ('DECLARED_DEFAULT_EXPRESSION:'+dep.default_expression,)
                # A no-actual default/open conversion remains an interface of
                # the call, not an invented source value or constant alias.
                actuals = tuple(self.view.source_port(p) for p in dep.actuals) or (operation,)
                for actual in actuals:
                    if actual.namespace != frame.caller:
                        raise ValueError('native actual needs its original producer context')
                    self._relation(actual, target, frame, Flow.ENTER, K.ARGUMENT, Meaning.DEPENDENCE,
                        key, 'inputs', index, guards, frontier)
            world = native.index.entry_port(output.native_world)
            self._relation(self.view.source_port(output.world), Point(namespace, world.id, None), frame,
                Flow.ENTER, K.STATE_INTERFACE, Meaning.STATE_INTERFACE, key, 'outputs', ordinal, output.conditions)
            result = self.view.source_port(output.result)
            for slot in output.native_outputs:
                for returned in native.index.exit_port_uses(slot.port):
                    self._relation(Point(namespace, returned.use.id, None), result, frame, Flow.RETURN,
                        K.COMPLETION, Meaning.DEPENDENCE, key, 'outputs', ordinal,
                        (*output.conditions, 'NATIVE_OUTPUT_POSITION:'+str(slot.position)), output.frontier)
            for returned in native.index.exit_port_uses(output.native_normal_world):
                point = Point(namespace, returned.use.id, None)
                self._relation(point, self.view.source_port(output.result_world), frame, Flow.RETURN,
                    K.STATE_INTERFACE, Meaning.STATE_INTERFACE, key, 'outputs', ordinal, output.conditions)
                if not output.native_outputs:
                    self._relation(point, result, frame, Flow.RETURN, K.COMPLETION, Meaning.DEPENDENCE,
                        key, 'outputs', ordinal, (*output.conditions, 'WRAPPER_ONLY_DATA_RETURN'), output.frontier)
        self.graphs[unit] = graph
        self.store.validate(); self.native.materials.check()
        return graph

    def _demand(self, point):
        if type(point.node) not in (OperationID, ValueID, UseID, ControlPortID): return
        for namespace in dict.fromkeys((point.namespace, *(f.caller for f in context_frames(point.context)))):
            unit = getattr(self.view.namespaces.get(namespace), 'unit', None)
            if unit in self.available_units and unit not in self.graphs: self.attach(unit)

    def _boundary(self, point):
        native = self.native.providers.get(point.namespace)
        if native is None: return False
        boundary = native.unit.boundary
        if point.node == boundary.region: return True
        inputs = (*boundary.inputs, *boundary.core_inputs)
        outputs = (*boundary.outputs, *boundary.core_outputs)
        return (any(point.node == native.index.entry_port(slot.port).id for slot in inputs)
            or any(point.node == site.use.id for slot in outputs
                for site in native.index.exit_port_uses(slot.port)))

    def _neighbors(self, point, incoming):
        self._demand(point)
        rows = (self.in_edges if incoming else self.out_edges).get(self._key(point), ())
        if not rows:
            if self._boundary(point):
                return Neighborhood(frontiers=(Frontier(point, 'NATIVE_SOURCE_CALL_FRAME_NOT_SELECTED',
                    'Source normalization is loaded by the original caller; no all-caller union is inferred.'),))
            return Neighborhood()
        self.store.validate(); self.native.materials.check(); self.view.get(point)
        edges = []; reasons = set(); needs_frame = False; matched = False
        for row in rows:
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
            call = Point(row.frame.caller, row.frame.operation, caller_context)
            unit, ordinal = row.interface
            locator = replace(self.manifest, pointer='#/shards/'+unit+'/tables/'+row.table)
            conditions = tuple(Condition('scar.source-native.precondition', guard, call, ordinal) for guard in row.guards)
            conditions += (Condition('scar.source-native.route', row.flow.value, call, row.ordinal, (source, target)),)
            edges.append(Edge(source, target, row.kind, row.meaning,
                (Evidence('scar.source-native.matched-normalization.v1',
                    (self.view.namespaces[row.frame.caller].locator, row.frame.target.graph, locator),
                    (call, source, target)),), conditions, Strength.MAY))
            if row.frontier: reasons.add(row.frontier)
        if needs_frame and not matched: reasons.add('NATIVE_SOURCE_CALL_FRAME_NOT_SELECTED')
        if edges:
            reasons.add('NATIVE_PARSER_OVERRIDE_AND_RUNTIME_DISPATCH_NOT_PROVEN')
            if not context_is_closed(point.context): reasons.add('SOURCE_CALL_CONTEXT_PREFIX_OPEN')
        return Neighborhood(tuple(dict.fromkeys(edges)), tuple(Frontier(point, reason,
            'Original normalization dependencies retain named-match, conversion, wrapping and caller conditions.')
            for reason in sorted(reasons)))

    def incoming(self, point): return self._neighbors(point, True)
    def outgoing(self, point): return self._neighbors(point, False)

    def interface(self, unit, ordinal):
        self.attach(unit)
        return dict(original=self.interfaces[unit, ordinal], frame=self.frames[unit, ordinal],
            inputs=tuple(row for row in self.graphs[unit].inputs if row.match == self.interfaces[unit, ordinal].match),
            runtime_dispatch_proven=False, identity_proven=False, effects_closed=False)

    def summary(self):
        return dict(available_units=len(self.available_units), units=len(self.graphs),
            native_units=len(self.native.providers), interfaces=len(self.interfaces), relations=len(self.relations),
            kinds=dict(Counter(r.kind.value for r in self.relations)), canonical_body_bytes_copied=0,
            runtime_dispatch_proven=False, identity_proven=False, effects_closed=False,
            loops_unrolled=False, target_executed=False, first_stage_complete=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True); parser.add_argument('--unit', action='append', default=[])
    args = parser.parse_args(); store = BindingNativeStore(args.source)
    calls = DeclaredCallStore(store.parents.source_root)
    view = ProgramView(calls.catalog)
    provider = SourceNativeCallProvider(view, store, units=args.unit)
    print(json.dumps(provider.summary()), flush=True)


if __name__ == '__main__': main()
