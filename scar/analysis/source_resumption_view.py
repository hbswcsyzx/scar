"""Shared temporal interfaces in the ordinary program dependency view.

Source bodies remain original shared regions. Repeated interpreter boundaries
are evidence for phase/port groups, not copies of the body or loop iterations.
Temporal order never turns a fresh world into a saved content snapshot.
"""
from collections import defaultdict
from dataclasses import replace
import json
from pathlib import Path
import time

from scar.analysis.source_observed_resumptions import SCHEMA, _pins, derive
from scar.analysis.source_observed_interfaces import ObservedFunctionInterfaceStore
from scar.analysis.source_declared_catalog import _check
from scar.analysis.source_consumer_parents import _stamp
from scar.analysis.source_symbol_variants import _table
from scar.analysis.source_call_view import prepare_source_ports
from scar.analysis.source_value_flow import _artifact
from scar.analysis.program_view import _digest
from scar.ir.record_codec import encode, decode
from scar.ir.program import source_body_interfaces as B, source_productions as P, view as V
from scar.ir.program.ids import RegionID, ProviderID
from scar.ir.program.model import ValueType, ValueKind
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.program.dependencies import (GraphNamespace, DependencyPoint as Point,
    DependencyEdge as Edge, DependencyKind as K, DependencyMeaning as Meaning,
    DependencyStrength as Strength, DependencyEvidence as Evidence,
    DependencyCondition as Condition, DependencyNeighborhood as Neighborhood, DependencyFrontier as Frontier)


class ResumptionStore:
    """Admit saved source joins with one existing code/source index.

    A linear join replay checks selection against original interpreter events
    and sealed body interfaces. It does not solve state fixed points or rebuild
    the source catalog. Subsequent graph queries check admitted file stamps.
    """
    def __init__(self, path, *, index=None):
        self.path = Path(path).resolve(); self.report = r = json.loads((self.path/'result.json').read_bytes())
        if (r['schema'], r['schema_version'], r['pins']) != (SCHEMA, 1, _pins()):
            raise ValueError('source-resumption schema or rules differ')
        if (r['original_body_bytes_copied'] != 0 or any(r[k] is not False for k in
                ('loops_unrolled','target_executed','contents_or_driver_normalization_proven','first_stage_complete'))):
            raise ValueError('source-resumption joins claim unsupported identities or effects')
        _check(r['parent']); _check(r['metadata'])
        if index is None: index = ObservedFunctionInterfaceStore(Path(r['parent']['path']).parent).index
        if str(index.view.catalog.path) != r['catalog'] or str(index.codes.trace.directory) != r['trace']:
            raise ValueError('source-resumption join uses another original catalog or trace')
        self.index = index; self.rows = derive(index, r['metadata']['path'])
        if set(r['tables']) != {'events','interfaces','bindings','frontiers'}:
            raise ValueError('source-resumption table domain differs')
        paths = [self.path/'result.json', Path(r['parent']['path']), Path(r['metadata']['path']),
            index.view.catalog.path/'result.json']
        for name in r['tables']:
            expected = [encode(row, record_tags=P.PRODUCTION_RECORD_TAGS) if name in ('events','interfaces') else row
                for row in self.rows[name]]
            if list(_table(self.path, r['tables'][name])) != expected:
                raise ValueError('source-resumption join differs from original source/event replay: '+name)
            paths.append(self.path/r['tables'][name]['path'])
        if (len(self.rows['events']), len(self.rows['interfaces']), self.rows['covered'],
                len(self.rows['frontiers']), self.rows['source_port_counts'],self.rows['capture']['activations'],
                self.rows['capture']['process_id']) != (
                r['records'],r['source_body_interfaces'],r['source_port_events'],r['frontier_count'],r['source_port_counts'],
                r['activations'],r['process_id']):
            raise ValueError('source-resumption coverage denominator differs')
        from scar.trace.files import resolve
        paths += [resolve(row['uri']) for row in self.rows['capture']['legacy_inputs']]
        paths.append(resolve(self.rows['capture']['events']['uri']))
        paths += list(index.codes._guard)
        self.guards = {p: _stamp(p) for p in set(paths)}
        _check(r['parent']); _check(r['metadata']); index.check(); self.check()

    def check(self):
        if any(_stamp(p) != stamp for p, stamp in self.guards.items()):
            raise ValueError('admitted source-resumption inputs changed')


class SourceResumptionProvider:
    relation_kinds = frozenset((K.CONTAINS,K.IMPLEMENTATION,K.CONTROL_FLOW,
        K.OPERAND,K.STATE_INTERFACE,K.RESULT,K.PROJECTION))

    def __init__(self, view, store):
        self.store = store if type(store) is ResumptionStore else ResumptionStore(store)
        if view.catalog.path != self.store.index.view.catalog.path:
            raise ValueError('resumption view requires the same original source catalog')
        self.view = view; self.nodes = {}; self.out_edges = defaultdict(list); self.in_edges = defaultdict(list)
        self.observations = defaultdict(set); self.order_evidence = defaultdict(list)
        artifact = _artifact(self.store.path/'result.json', SCHEMA)
        self.locator = SourceArtifactLocator(artifact, artifact.sha256, artifact.size_bytes, 'canonical-json')
        root = RegionID(_digest((SCHEMA+'.root',artifact.sha256)))
        self.namespace = GraphNamespace(self.locator, SCHEMA+'.temporal-interfaces.v1', root)
        self.owned_namespaces = (self.namespace,)
        self.root = Point(self.namespace, root, None)
        self.nodes[root] = dict(report=self.store.report)
        interfaces = {body.id:body for body in self.store.rows['interfaces']}
        self.events = {event.sequence:event for event in self.store.rows['events']}
        groups = {}; by_event = defaultdict(dict); ports = []; prepared = []
        bindings = list(self.store.rows['bindings'])
        bound = {row['sequence'] for row in bindings}
        for event in self.events.values():
            if event.sequence not in bound:
                bindings.append(dict(sequence=event.sequence,interface=None,source_ports=(),
                    selection='SOURCE_BODY_UNRESOLVED'))
        for row in bindings:
            event = self.events[row['sequence']]
            body = None if row['interface'] is None else interfaces[decode(ProviderID,row['interface'])]
            cls = (B.SourceBodyIngress if event.kind in ('PY_START','PY_RESUME','PY_THROW') else
                B.SourceBodySuspension if event.kind == 'PY_YIELD' else B.SourceBodyCompletion)
            selected = tuple(decode(cls, p, record_tags=P.PRODUCTION_RECORD_TAGS) for p in row['source_ports'])
            identity = ProviderID(_digest((SCHEMA+'.phase',None if body is None else body.id,
                event.position.code,event.kind,selected,row['selection'])))
            point = Point(self.namespace, identity, None)
            self.observations[identity].add(event.sequence)
            by_event[event.sequence][None if body is None else body.id] = point
            if identity in groups: continue
            groups[identity] = body, selected
            self.nodes[identity] = dict(kind=event.kind,source_body=None if body is None else body.body,
                code=event.position.code,selection=row['selection'],source_port_alternatives=len(selected))
            self._add(self.root,point,K.CONTAINS,Meaning.STRUCTURE,'SHARED_TEMPORAL_PHASE_INTERFACE')
            if body is not None:
                for selected_port in selected:
                    if type(selected_port) is B.SourceBodyIngress:
                        ports.extend(selected_port.parameters)
                        if selected_port.suspension is not None: ports.append(selected_port.suspension)
                        for formal,actual in selected_port.saved: ports.extend((formal,actual))
                    elif type(selected_port) is B.SourceBodySuspension:
                        ports.extend((selected_port.step,*selected_port.arguments))
                    else: ports.extend((selected_port.exit,*selected_port.ports))
            prepared.append((point,body,selected,row['selection']))
        prepare_source_ports(view,tuple(dict.fromkeys(ports)))
        for point,body,selected,selection in prepared:
            if body is None: continue
            original = view.source_region(body.body.unit,body.body.template,body.body.region)
            self._add(original,point,K.IMPLEMENTATION,Meaning.STRUCTURE,'OBSERVED_CODE_BODY_TEMPORAL_INTERFACE')
            for selected_port in selected:
                if type(selected_port) is B.SourceBodyIngress:
                    region = selected_port.region
                    target = view.source_region(region.unit,region.template,region.region)
                    self._add(point,target,K.IMPLEMENTATION,Meaning.STRUCTURE,selection)
                    for parameter,kind in zip(selected_port.parameters,selected_port.types,strict=True):
                        state = type(kind) is ValueType and kind.kind is ValueKind.STATE
                        self._add(point,view.source_port(parameter),K.STATE_INTERFACE if state else K.PROJECTION,
                            Meaning.STATE_INTERFACE if state else Meaning.REFERENCE,
                            'FRESH_WORLD_NOT_SAVED_CONTENT' if state else 'DECLARED_INPUT_NOT_OBSERVED_PAYLOAD')
                    for formal,actual in selected_port.saved:
                        self._add(view.source_port(actual),view.source_port(formal),K.PROJECTION,Meaning.REFERENCE,
                            'DECLARED_SAVED_REFERENCE_NOT_CONTENT_OR_INSTANCE_IDENTITY')
                elif type(selected_port) is B.SourceBodySuspension:
                    self._add(view.source_port(selected_port.step),point,K.IMPLEMENTATION,Meaning.STRUCTURE,selection)
                    for argument,kind in zip(selected_port.arguments,selected_port.types,strict=True):
                        state = type(kind) is ValueType and kind.kind is ValueKind.STATE
                        self._add(view.source_port(argument),point,K.STATE_INTERFACE if state else K.OPERAND,
                            Meaning.STATE_INTERFACE if state else Meaning.REFERENCE,'DECLARED_HANDOFF_NOT_OBSERVED_PAYLOAD')
                else:
                    self._add(point,view.source_port(selected_port.exit),K.IMPLEMENTATION,Meaning.STRUCTURE,selection)
                    for result in selected_port.ports:
                        self._add(point,view.source_port(result),K.RESULT,Meaning.REFERENCE,'DECLARED_COMPLETION_NOT_OBSERVED_PAYLOAD')
        for sequence,current in by_event.items():
            event = self.events[sequence]
            for body,right in current.items():
                left = by_event.get(event.previous,{}).get(body)
                if left is None: continue
                self.order_evidence[left.node,right.node].append((event.activation,event.previous,sequence))
        for left,right in self.order_evidence:
            self._add(Point(self.namespace,left,None),Point(self.namespace,right,None),K.CONTROL_FLOW,Meaning.ORDER,
                'OBSERVED_SAME_ACTIVATION_ORDER_NOT_UNCONDITIONAL_SOURCE_CONTROL')
        self.groups = groups; self.store.check(); view.register(self)

    def _add(self,left,right,kind,meaning,rule):
        guards = tuple(Condition(SCHEMA,name,left,None,(left,right)) for name in (
            'SOURCE_ALTERNATIVES_AND_DRIVER_NORMALIZATION_REMAIN_CONDITIONAL',
            'NO_PAYLOAD_CONTENT_ALIAS_OR_FUTURE_DISPATCH_PROOF',rule))
        edge = Edge(left,right,kind,meaning,(Evidence(SCHEMA+'.source-and-interpreter-events',
            (self.locator,),(left,right)),),guards,Strength.MAY)
        if edge not in self.out_edges[left.namespace,left.node]:
            self.out_edges[left.namespace,left.node].append(edge); self.in_edges[right.namespace,right.node].append(edge)

    def describe(self,point):
        if point.namespace != self.namespace or point.node not in self.nodes:return None
        self.store.check()
        return V.ProgramNode(point,V.ProgramEntityKind.REGION if point.node == self.root.node else None,
            V.ProgramNodeRole.PROVIDER,replace(self.root,context=point.context),None)

    def original(self,point):return self.nodes[point.node]
    def expand(self,point):return tuple(e.target for e in self.outgoing(point).edges if e.kind is K.CONTAINS)
    def explain(self,point):
        return dict(original=self.original(point),observations=tuple(sorted(self.observations.get(point.node,()))),
            event_table=self.store.report['tables']['events'],original_body_copies=0,
            runtime_values_or_saved_contents_proven=False,driver_normalization_proven=False)

    def _neighbors(self,point,incoming):
        rows = (self.in_edges if incoming else self.out_edges).get((point.namespace,point.node),())
        if not rows:return Neighborhood()
        self.store.check()
        if point.context:
            return Neighborhood((),(Frontier(point,'RESUMPTION_INVOCATION_CONTEXT_UNSELECTED',
                'Recorded activation evidence has not selected this static call context.'),),False)
        frontiers = ()
        if point.namespace == self.namespace and self.nodes.get(point.node,{}).get('source_port_alternatives') == 0:
            frontiers = (Frontier(point,'RESUMABLE_SOURCE_PORT_UNRESOLVED',
                'Code and actual boundary are retained; the matching source temporal port remains unresolved.'),)
        return Neighborhood(tuple(rows),frontiers)

    def incoming(self,point):return self._neighbors(point,True)
    def outgoing(self,point):return self._neighbors(point,False)


def verify_resumption_graph(path,out,*,index=None):
    from scar.analysis.source_stage import _durable_bytes
    from scar.analysis.source_template_links import _json
    started = time.monotonic(); store = ResumptionStore(path,index=index)
    provider = SourceResumptionProvider(store.index.view,store); checked = 0
    for edges in provider.out_edges.values():
        for edge in edges:
            if edge not in provider.outgoing(edge.source).edges or edge not in provider.incoming(edge.target).edges:
                raise ValueError('temporal/source relation is not bidirectionally queryable')
            checked += 1
    r = dict(schema=SCHEMA+'.graph-check',shared_phase_interfaces=len(provider.groups),
        records=store.report['records'],source_port_events=store.report['source_port_events'],
        bidirectional_relations=checked,temporal_group_pairs=len(provider.order_evidence),
        source_body_copies=0,loops_unrolled=False,first_stage_complete=False,seconds=time.monotonic()-started)
    _durable_bytes(Path(out),_json(r),replace=False); return r


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path'); parser.add_argument('--out',required=True); args = parser.parse_args()
    print(json.dumps(verify_resumption_graph(args.path,args.out)),flush=True)
