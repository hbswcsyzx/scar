"""Caller-matched source interfaces on the existing shared ProgramView.

Bodies remain shared. A context is a static interface selection, never a
runtime invocation. Parent namespace candidates and creation versions stay
conditional; this provider does not turn declarations into dispatch proofs.
"""
import argparse
from collections import Counter,defaultdict
from dataclasses import dataclass,replace
from enum import Enum
import json
from pathlib import Path
from typing import Protocol,runtime_checkable

from scar.analysis.program_view import ProgramView
from scar.analysis.source_function_interfaces import SourceFunctionInterfaceStore
from scar.analysis.source_namespace_interfaces import NamespacePlanView
from scar.analysis.source_reference_slice import source_port
from scar.analysis.source_value_flow import _artifact
from scar.analysis.source_world_returns import _table_ref
from scar.analysis.source_call_defaults import FunctionDefaultStateProvider
from scar.analysis.source_call_captures import FunctionCaptureStateProvider
from scar.ir.program import normal_graph as G,normal_targets as T,normal_links as F
from scar.ir.program.dependencies import (
    DependencyPoint as Point,DependencyFrame as Frame,DependencyEdge as Edge,
    DependencyCondition as Condition,DependencyEvidence as Evidence,
    DependencyKind as Kind,DependencyMeaning as Meaning,DependencyStrength as Strength,
    DependencyFrontier as Frontier,DependencyNeighborhood as Neighborhood,
    context_push,context_pop,context_is_closed,context_frames)
from scar.ir.program.ids import OperationID,ValueID,UseID,ControlPortID
from scar.ir.program.source_references import SourceArtifactLocator


@runtime_checkable
class FunctionInterfaceReader(Protocol):
    path: Path
    report: dict
    catalog: object

    def read_unit(self,unit): ...
    def validate(self): ...


def open_function_interfaces(value):
    """Select a declared material representation, never a workload name."""
    if isinstance(value,FunctionInterfaceReader): return value
    path=Path(value).absolute();schema=json.loads((path/'result.json').read_bytes())['schema']
    from scar.analysis.source_function_interfaces import SCHEMA as ordinary_schema
    if schema==ordinary_schema: return SourceFunctionInterfaceStore(path)
    from scar.analysis.source_compiled_interfaces import SCHEMA as compiled_schema,CompiledFunctionInterfaceStore
    if schema==compiled_schema: return CompiledFunctionInterfaceStore(path)
    from scar.analysis.source_returned_functions import SCHEMA as returned_schema,ReturnedFunctionInterfaceStore
    if schema==returned_schema:return ReturnedFunctionInterfaceStore(path)
    from scar.analysis.source_function_collection import SCHEMA as collection_schema,FunctionInterfaceCollection
    if schema==collection_schema:return FunctionInterfaceCollection(path)
    from scar.analysis.source_observed_interfaces import SCHEMA as observed_schema,ObservedFunctionInterfaceStore
    if schema==observed_schema:return ObservedFunctionInterfaceStore(path)
    raise ValueError('unsupported function-interface material representation: '+str(schema))


def function_interface_fact(store,unit,ordinal):
    """Stable interface alternative, including inherited rows of an overlay."""
    getter=getattr(store,'interface_fact',None)
    if callable(getter):return getter(unit,ordinal)
    shard=store.report['shards'][unit]
    return _table_ref(store.path/shard['path'],shard['tables']['interfaces'],
        'scar.source-function-interface-record',ordinal)


def prepare_source_ports(view,ports,*,bodies=()):
    """Batch only referenced original templates before individual port queries.

    Construction interfaces contribute their original call/class anchors;
    they are not source ports. Each unit receives one deduplicated _expand,
    without admitting callers, copying bodies or changing context selections.
    """
    keys=defaultdict(set)
    def add(point):
        if type(point) is T.GlobalPort:
            if type(point.port) is not G.Port:raise TypeError('source preparation needs an original graph port')
            keys[point.unit].add(point.port.template)
        elif type(point) is T.ConstructionPort:
            if type(point.call) is not T.GlobalPort or type(point.source_class) is not T.GlobalPort:
                raise TypeError('construction preparation needs its original call/class ports')
            add(point.call);add(point.source_class)
        else:raise TypeError('source preparation needs exact GlobalPort or ConstructionPort endpoints')
    if type(ports) in (T.GlobalPort,T.ConstructionPort):ports=(ports,)
    for point in ports:add(point)
    if type(bodies) is T.Body:bodies=(bodies,)
    for body in bodies:
        if type(body) is not T.Body:raise TypeError('source preparation needs exact original Body records')
        keys[body.unit].add(body.template)
    for unit in sorted(keys):
        view.unit(unit)._expand(tuple(sorted(keys[unit],key=lambda key:(key.occurrence,key.purpose.value))))


def source_call_site(view,link):
    """Resolve the original F4 call operation and its callee Use/value.

    Only link.result and link.callee are required, so source-function and
    generated-native interfaces share the same exact original ABI check.
    """
    caller=view.unit(link.result.unit)
    caller._expand((link.result.port.template,))
    operation=caller._node(link.result.port.template,link.result.port.owner)
    step=view.original(operation);context=NamespacePlanView(caller.unit,caller.plans[link.result.port.template])
    if (context.result(step)!=link.result or not step.arguments
            or context.value(step.arguments[0])!=link.callee):
        raise ValueError('source call frame differs from original callee/result ABI')
    use=caller.port(context.emitter.port(step.id,G.PortKind.ARGUMENT,0))
    value=view.source_port(link.callee)
    return operation,use,value


def source_caller_scope(view,frame,context):
    """Resolve the caller source scope without unioning same-unit functions."""
    return source_active_scope(view,frame.caller,context)


def source_active_scope(view,namespace,context):
    """Resolve one source activation scope, including a protocol's caller."""
    frames=context_frames(context);source=view.namespaces[namespace]
    if not frames:
        return source.facts.root_scope.owner if context_is_closed(context) else None
    entry=frames[-1].entry or frames[-1].target.root
    node=source.nodes.get(entry)
    if node is None:raise ValueError('caller context entry is not attached to its original source unit')
    plan=source.plans[node.anchor.template]
    ports=[p for p in plan.compilation_flow.ports if p.region==node.anchor.original]
    if len(ports)!=1:raise ValueError('caller context entry lacks its original code-scope port')
    return F.CodeScopeRef(source.unit,ports[0].code_scope)


class Flow(str,Enum):
    ENTER='ENTER'
    RETURN='RETURN'


@dataclass(frozen=True,slots=True)
class CallRelation:
    source: Point
    target: Point
    frame: Frame
    flow: Flow
    kind: Kind
    meaning: Meaning
    interface: tuple[str,int]
    route: int
    guards: tuple[str,...]


class SourceFunctionCallProvider:
    """Attach selected stored units, without unioning callers at formal ports."""
    relation_kinds=frozenset((Kind.ARGUMENT,Kind.ENVIRONMENT,Kind.STATE_INTERFACE,
        Kind.COMPLETION,Kind.PROJECTION,Kind.CALL_TARGET))

    def __init__(self,view,interfaces,*,units=None):
        self.view=view
        self.store=open_function_interfaces(interfaces)
        if view.catalog is None or (view.catalog.path,view.catalog.report)!=(self.store.catalog.path,self.store.catalog.report):
            raise ValueError('source call view and interfaces need the same original catalog')
        self.graphs={};self.frames={};self.links={};self.relations=[]
        self.available_units=frozenset(self.store.report['shards']);self.boundary_ports={}
        self.incoming_index=defaultdict(list);self.outgoing_index=defaultdict(list)
        self.pending=defaultdict(set)
        self.defaults=FunctionDefaultStateProvider(view)
        self.captures=FunctionCaptureStateProvider(view)
        self.returned=None
        if callable(getattr(self.store,'callable_provenance',None)):
            from scar.analysis.source_callable_provenance_view import ReturnedCallableProvider
            self.returned=ReturnedCallableProvider(self)
        artifact=_artifact(self.store.path/'result.json',self.store.report['schema'])
        self.manifest=SourceArtifactLocator(artifact,artifact.sha256,artifact.size_bytes,'canonical-json')
        # Stored interface shards already are the complete conditional graph.
        # Normalize only selected/demanded units; opening a large store must
        # not instantiate every body and retain every normalized endpoint.
        selected=() if units is None else tuple(dict.fromkeys(units))
        for unit in selected:self.attach(unit)
        view.register(self)

    @staticmethod
    def _key(point):return point.namespace,point.node

    def _note(self,point,reason):self.pending[self._key(point)].add(reason)

    def _demand(self,point):
        if type(point.node) not in (OperationID,ValueID,UseID,ControlPortID):return
        namespaces=(point.namespace,*(f.caller for f in context_frames(point.context)))
        for namespace in dict.fromkeys(namespaces):
            source=self.view.namespaces.get(namespace)
            unit=getattr(source,'unit',None)
            if unit in self.available_units and unit not in self.graphs:self.attach(unit)

    def _boundary(self,point):
        source=self.view.namespaces.get(point.namespace)
        if source is None or point.node not in source.records:return False
        original=source.records[point.node]
        if type(original) is not G.Port:return False
        if point.namespace not in self.boundary_ports:
            ports=set()
            for function in source.facts.functions:
                indices=(*function.formals,*(i for i in (function.returns,function.return_world) if i is not None))
                ports.update(source_port(source.facts,i).port for i in indices)
            self.boundary_ports[point.namespace]=ports
        return original in self.boundary_ports[point.namespace]

    def _call(self,link):
        return source_call_site(self.view,link)

    def _caller_scope(self,frame,context):
        """Namespace equality alone cannot select a function within one unit."""
        return source_caller_scope(self.view,frame,context)

    def _relation(self,source,target,frame,flow,kind,meaning,key,route,guards):
        relation=CallRelation(source,target,frame,flow,kind,meaning,key,route,guards)
        self.relations.append(relation)
        self.outgoing_index[self._key(source)].append(relation)
        self.incoming_index[self._key(target)].append(relation)

    def attach(self,unit):
        if unit in self.graphs:return self.graphs[unit]
        graph=self.store.read_unit(unit);self.graphs[unit]=graph
        caller=self.view.unit(unit);facts=caller.facts
        ports=[];bodies=[]
        for query in graph.queries:
            call=facts.calls[query.query]
            ports.extend((source_port(facts,call.result),source_port(facts,call.callee)))
        for interface in graph.interfaces:
            link=interface.link
            ports.extend(p for p in (link.callee,link.result,link.source_callable) if p is not None)
            if link.body is not None:bodies.append(link.body)
            for route in link.parameters:ports.extend((route.formal,*route.actuals))
            for source,target in link.returns:ports.extend((source,target))
            for projection in link.projections:ports.extend((projection.formal,projection.pack))
            if link.argument_packs is not None:
                pack=link.argument_packs
                ports.extend(p for p in (pack.positional,pack.keywords,pack.receiver,pack.class_receiver) if p is not None)
        prepare_source_ports(self.view,ports,bodies=bodies)
        call_points={}
        for query in graph.queries:
            fact=facts.calls[query.query]
            result_gp=source_port(facts,fact.result)
            result=self.view.source_port(result_gp)
            operation=caller._node(result_gp.port.template,result_gp.port.owner)
            callee=self.view.source_port(source_port(facts,fact.callee))
            call_points[query.query]=(operation,callee,result)
            reasons=[]
            if not query.interfaces:reasons.append('SOURCE_CALL_TARGET_NOT_BOUND_BY_FUNCTION_INTERFACE')
            if query.declared_frontiers or query.reference_frontiers:
                reasons.append('ORIGINAL_CALLEE_NAMESPACE_FRONTIERS_REMAIN_OPEN')
            for point in (operation,callee,result):
                for reason in reasons:self._note(point,reason)
        for frontier in graph.frontiers:
            for point in call_points[frontier.query]:self._note(point,frontier.reason)
        for ordinal,interface in enumerate(graph.interfaces):
            key=unit,ordinal;link=interface.link;self.links[key]=interface
            operation,use,value=self._call(link)
            if interface.activation is not T.FunctionActivation.NORMAL:
                self._note(operation,'DEFERRED_CREATION_IS_NOT_ORDINARY_BODY_EXECUTION');continue
            body=self.view.source_region(link.body.unit,link.body.template,link.body.region)
            frame=Frame(operation.namespace,operation.node,use.node,value.node,body.namespace,entry=body.node,
                selection=function_interface_fact(self.store,unit,ordinal))
            self.frames[key]=frame
            if self.returned is not None:self.returned.bind(key,interface,frame)
            self._relation(operation,body,frame,Flow.ENTER,Kind.CALL_TARGET,Meaning.DEPENDENCE,
                key,0,link.conditions)
            for ri,route in enumerate(link.parameters):
                formal=self.view.source_port(route.formal)
                if route.kind is T.RouteKind.FUNCTION_ENVIRONMENT:
                    self.captures.bind(interface,route,frame)
                if route.kind in (T.RouteKind.INITIAL_DEFAULT,T.RouteKind.CONDITIONAL_DEFAULT):
                    world=source_port(facts,facts.calls[interface.query].world)
                    current=self.defaults.read(interface,route,frame,world)
                    self._relation(current,formal,frame,Flow.ENTER,Kind.PROJECTION,Meaning.DEPENDENCE,
                        key,ri,(*link.conditions,'PARAMETER_ROUTE_'+route.kind.value))
                    continue
                if not route.actuals:
                    self._note(formal,'SOURCE_CALL_ROUTE_HAS_NO_DIRECT_REFERENCE_OPERAND');continue
                for actual in route.actuals:
                    if type(actual) is not T.GlobalPort:
                        self._note(formal,'SOURCE_CALL_CONSTRUCTION_ENDPOINT_NEEDS_PROTOCOL_INTERFACE');continue
                    source=self.view.source_port(actual)
                    if source.namespace!=frame.caller:
                        self._note(formal,'SOURCE_CALL_OPERAND_ORIGIN_CONTEXT_NOT_SELECTED');continue
                    kind=(Kind.STATE_INTERFACE if route.kind is T.RouteKind.STATE else
                        Kind.ENVIRONMENT if route.kind is T.RouteKind.FUNCTION_ENVIRONMENT else Kind.ARGUMENT)
                    meaning=(Meaning.STATE_INTERFACE if route.kind is T.RouteKind.STATE else
                        Meaning.REFERENCE if route.kind is T.RouteKind.ARGUMENT else Meaning.DEPENDENCE)
                    self._relation(source,formal,frame,Flow.ENTER,kind,meaning,key,ri,
                        (*link.conditions,'PARAMETER_ROUTE_'+route.kind.value))
            for pi,projection in enumerate(link.projections):
                source=self.view.source_port(projection.pack);target=self.view.source_port(projection.formal)
                if source.namespace!=frame.caller:
                    self._note(target,'SOURCE_CALL_PACK_CREATION_CONTEXT_NOT_SELECTED');continue
                self._relation(source,target,frame,Flow.ENTER,Kind.PROJECTION,Meaning.DEPENDENCE,key,pi,
                    (*link.conditions,*projection.conditions,'ARGUMENT_PROJECTION_'+projection.kind.value))
            for ri,(source,target) in enumerate(link.returns):
                if type(source) is not T.GlobalPort or type(target) is not T.GlobalPort:
                    self._note(operation,'SOURCE_CALL_RETURN_ENDPOINT_NEEDS_PROTOCOL_INTERFACE');continue
                source=self.view.source_port(source);target=self.view.source_port(target)
                if (source.namespace,target.namespace)!=(frame.target,frame.caller):
                    raise ValueError('source return does not belong to selected body/caller')
                data=target.node==self.view.source_port(link.result).node
                self._relation(source,target,frame,Flow.RETURN,
                    Kind.COMPLETION if data else Kind.STATE_INTERFACE,
                    Meaning.REFERENCE if data else Meaning.STATE_INTERFACE,key,ri,link.conditions)
        self.store.validate()
        return graph

    def _neighbors(self,point,incoming):
        self._demand(point)
        key=self._key(point);rows=(self.incoming_index if incoming else self.outgoing_index).get(key,())
        if not rows and key not in self.pending:
            if self._boundary(point):
                return Neighborhood(frontiers=(Frontier(point,'SOURCE_CALL_CONTEXT_FRAME_NOT_SELECTED',
                    'A declared function boundary has no selected attached caller/resume interface.'),))
            return Neighborhood()
        self.store.validate();self.view.get(point)
        edges=[];needs_frame=False;matched=False;wrong_caller_scope=False
        for relation in rows:
            pop=(incoming and relation.flow is Flow.ENTER) or (not incoming and relation.flow is Flow.RETURN)
            if pop:
                needs_frame=True;popped=context_pop(point.context,(relation.frame,))
                if not popped.matched:continue
                matched=True;caller_context=popped.remaining;callee_context=point.context
            else:
                caller_context=point.context;callee_context=context_push(caller_context,relation.frame)
            unit,ordinal=relation.interface
            query=self.graphs[unit].queries[self.links[relation.interface].query]
            active=self._caller_scope(relation.frame,caller_context)
            if active is not None and active not in query.owners:
                wrong_caller_scope=True;continue
            source_context=caller_context if relation.flow is Flow.ENTER else callee_context
            target_context=callee_context if relation.flow is Flow.ENTER else caller_context
            source=replace(relation.source,context=source_context);target=replace(relation.target,context=target_context)
            call=Point(relation.frame.caller,relation.frame.operation,caller_context)
            manifest=replace(self.manifest,pointer='#/shards/'+unit+'/tables/interfaces')
            sources=(self.view.namespaces[relation.frame.caller].locator,
                self.view.namespaces[relation.frame.target].locator,manifest)
            conditions=tuple(Condition('scar.source-call.precondition',name,call,ordinal)
                for name in relation.guards)
            conditions+=(Condition('scar.source-call.route',relation.flow.value,call,relation.route,(source,target)),)
            edges.append(Edge(source,target,relation.kind,relation.meaning,
                (Evidence('scar.source-call.matched-interface.v1',sources,(call,source,target)),),
                conditions,Strength.MAY))
        reasons=set(self.pending.get(key,()))
        if needs_frame and not matched:reasons.add('SOURCE_CALL_CONTEXT_FRAME_NOT_SELECTED')
        if wrong_caller_scope:reasons.add('SOURCE_CALLER_CODE_SCOPE_DOES_NOT_OWN_CALLSITE')
        if edges and not context_is_closed(point.context):reasons.add('SOURCE_CALL_CONTEXT_PREFIX_OPEN')
        frontiers=tuple(Frontier(point,r,'Retained source interfaces require the recorded target, versions and matching caller frame.')
            for r in sorted(reasons))
        return Neighborhood(tuple(dict.fromkeys(edges)),frontiers)

    def incoming(self,point):return self._neighbors(point,True)
    def outgoing(self,point):return self._neighbors(point,False)

    def summary(self):
        return dict(units=len(self.graphs),available_units=len(self.available_units),
            available_calls=self.store.report['counts']['calls'],calls=sum(g.calls for g in self.graphs.values()),
            interfaces=len(self.links),normal_frames=len(self.frames),relations=len(self.relations),
            flows=dict(Counter(r.flow.value for r in self.relations)),
            kinds=dict(Counter(r.kind.value for r in self.relations)),
            default_reads=len(self.defaults.reads),default_slots=len(self.defaults.addresses),
            captured_cell_bindings=len(self.captures.bindings),captured_locations=len(self.captures.locations),
            returned_callable_bindings=0 if self.returned is None else len(self.returned.bindings),
            pending_endpoint_reasons=sum(len(r) for r in self.pending.values()),
            namespace_semantics_rederived=False,runtime_dispatch_proven=False,
            source_bodies_copied=False,loops_unrolled=False,first_stage_complete=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--interfaces',required=True);parser.add_argument('--unit',action='append')
    parser.add_argument('--creations',help='optional original factory-role graph, loaded on demand')
    args=parser.parse_args();store=open_function_interfaces(args.interfaces)
    view=ProgramView(store.catalog)
    provider=SourceFunctionCallProvider(view,store,units=args.unit)
    report=provider.summary()
    if args.creations:
        from scar.analysis.source_creation_view import SourceFunctionCreationProvider
        creations=SourceFunctionCreationProvider(view,args.creations,units=tuple(args.unit or ()))
        report['creation_roles']=creations.summary()
    print(json.dumps(report),flush=True)


if __name__=='__main__':main()
