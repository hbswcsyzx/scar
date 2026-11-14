"""Balanced entry/exit relations for every shared source body protocol.

Unknown input origins remain projections of an explicit dispatch boundary.
They are never reference aliases, pure calls, or observed normal returns.
"""
from collections import defaultdict
from dataclasses import fields, is_dataclass, replace
import time
from pathlib import Path
from typing import get_args, get_origin, get_type_hints

from scar.analysis.program_view import _digest
from scar.analysis.source_body_activations import SourceBodyActivationStore, SCHEMA
from scar.analysis.source_world_returns import _table_ref
from scar.analysis.source_value_flow import _artifact
from scar.ir.program import source_body_interfaces as B, view as V
from scar.ir.program.normal_targets import GlobalPort
from scar.ir.program.ids import OperationID, ProviderID, ValueID
from scar.ir.program.model import ValueType, ValueKind
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.program.dependencies import (
    DependencyPoint as Point, DependencyFrame as Frame, DependencyEdge as Edge,
    DependencyKind as K, DependencyMeaning as Meaning, DependencyStrength as Strength,
    DependencyCondition as Condition, DependencyEvidence as Evidence,
    DependencyNeighborhood as Neighborhood, context_push, context_pop)


_PORT_RULES = {
    ('ingresses','*','parameters','*'):'INPUT',
    ('ingresses','*','saved','*',0):'SAVED_INPUT',
    ('ingresses','*','saved','*',1):'SAVED_SOURCE',
    ('ingresses','*','suspension'):'SUSPENSION_SITE',
    ('completions','*','ports','*'):'OUTPUT',
    ('completions','*','exit'):'EXIT',
    ('suspensions','*','arguments','*'):'HANDOFF',
    ('suspensions','*','step'):'SUSPENSION_SITE',
}


def _port_fields(kind,path=(),active=()):
    if kind is GlobalPort:return {path}
    if kind in active:return set()
    args=get_args(kind)
    if args:
        if get_origin(kind) is tuple:
            if args[-1] is Ellipsis:return _port_fields(args[0],path+('*',),active+(kind,))
            return set().union(*(_port_fields(arg,path+(i,),active+(kind,)) for i,arg in enumerate(args)))
        return set().union(*(_port_fields(arg,path,active+(kind,)) for arg in args))
    if isinstance(kind,type) and is_dataclass(kind):
        return set().union(*(_port_fields(t,path+(name,),active+(kind,)) for name,t in get_type_hints(kind).items()))
    return set()


def body_port_contract():
    """An independent denominator: every GlobalPort field needs a rule."""
    expected=_port_fields(B.SourceBodyInterface)
    if expected!=set(_PORT_RULES):
        raise ValueError('body protocol port rules differ from the complete declared schema')
    return tuple((path,role) for path,role in _PORT_RULES.items())


def _walk_ports(value,path,indices=()):
    if not path:
        yield indices,value
    elif path[0]=='*':
        for index,item in enumerate(value):yield from _walk_ports(item,path[1:],indices+(index,))
    else:
        child=value[path[0]] if type(path[0]) is int else getattr(value,path[0])
        yield from _walk_ports(child,path[1:],indices)


def _state(kind):return type(kind) is ValueType and kind.kind is ValueKind.STATE


class SourceBodyActivationProvider:
    relation_kinds=frozenset((K.CONTAINS,K.IMPLEMENTATION,K.CALL_TARGET,K.CONTROL_FLOW,
        K.OPERAND,K.PROJECTION,K.STATE_INPUT,K.STATE_OUTPUT,K.STATE_INTERFACE,K.COMPLETION,K.RESULT))

    def __init__(self,view,store):
        self.port_rules=body_port_contract()
        self.view=view; self.store=store if type(store) is SourceBodyActivationStore else SourceBodyActivationStore(store)
        if (view.catalog.path,view.catalog.report)!=(self.store.view.catalog.path,self.store.view.catalog.report):
            raise ValueError('activation provider uses another original source catalog')
        self.nodes={}; self.out_edges=defaultdict(list); self.in_edges=defaultdict(list)
        self.interfaces={}; self.activations={}; self.observations=defaultdict(list); self.points={}
        self.frames={}; self.frame_keys={}; self.origins={}; self.code_points={}; self.covered=set()
        self.frame_rows=defaultdict(list)
        for table in self.store.index.codes.body_link_tables():
            for key,row in table.items():self.code_points[row.id]=self.store.index.codes.points[key]
        artifact=_artifact(self.store.path/'result.json',SCHEMA)
        self.locator=SourceArtifactLocator(artifact,artifact.sha256,artifact.size_bytes,'canonical-json')
        for values in self.store.rows.values():
            self.interfaces.update((row.id,row) for row in values['interfaces'])
            self.activations.update((row.id,row) for row in values['activations'])
            for row in values['observations']:self.observations[row.activation].append(row)
        for unit,values in self.store.rows.items():
            for ordinal,row in enumerate(values['activations']):self._attach(unit,ordinal,row)
        # Repeated invocations remain evidence for one shared parent relation.
        parents={(row.parent,row.child,row.direct) for values in self.store.rows.values() for row in values['parents']}
        for parent,child,direct in parents:
            for left in self.points[parent]:
                for right in self.points[child]:
                    self._add(left,right,None,'STATIC',K.CONTROL_FLOW,Meaning.ORDER,
                        ('RECORDED_DIRECT_PARENT' if direct else 'RECORDED_ANCESTOR_WITH_RETAINED_PATH',),None)
        self._check_ports()
        view.register(self)

    @staticmethod
    def _key(point):return point.namespace,point.node

    def _port(self,port):
        point=self.view.source_port(port); self.origins[self._key(point)]=port
        return point

    def _add(self,left,right,frame,flow,kind,meaning,guards,fact):
        row=(left,right,frame,flow,kind,meaning,tuple(guards),fact)
        if row not in self.out_edges[self._key(left)]:
            self.out_edges[self._key(left)].append(row); self.in_edges[self._key(right)].append(row)
            if frame is not None:self.frame_rows[frame].append(row)

    def _node(self,site,namespace,phase,index,owner,kind=None,value_type=None):
        cls=OperationID if kind is V.ProgramEntityKind.OPERATION else ValueID if kind is V.ProgramEntityKind.VALUE else ProviderID
        identity=cls(_digest((SCHEMA+'.port',site.id,phase,index)))
        point=Point(namespace,identity,None)
        self.nodes[self._key(point)]=(site,phase,index,owner,kind,value_type)
        return point

    def _attach(self,unit,ordinal,site):
        interface=self.interfaces[site.interface]
        code=self.code_points[site.code_link]
        namespaces=tuple(dict.fromkeys(self.view.unit(anchor.operation.unit).namespace for anchor in site.anchors))
        if not namespaces:
            namespaces=tuple(dict.fromkeys(self.code_points[key].namespace for key in site.caller_links)) or (code.namespace,)
        shard=self.store.report['shards'][unit]
        fact=_table_ref(self.store.path/shard['path'],shard['tables']['activations'],SCHEMA+'.site',ordinal)
        points=[]
        for namespace in namespaces:
            point=Point(namespace,site.id,None); points.append(point)
            self.nodes[self._key(point)]=(site,'ACTIVATION',None,code,None,None)
            self._add(code,point,None,'STATIC',K.IMPLEMENTATION,Meaning.STRUCTURE,('RECORDED_BODY_CODE',),fact)
            for parent in site.caller_links:
                self._add(self.code_points[parent],point,None,'STATIC',K.CONTROL_FLOW,Meaning.ORDER,('RECORDED_CALLER_PATH',),fact)
            anchors=tuple(anchor for anchor in site.anchors if self.view.unit(anchor.operation.unit).namespace==namespace)
            for ingress_index,ingress in enumerate(interface.ingresses if site.suspended else interface.ingresses[:1]):
                driver=self._node(site,namespace,'INGRESS',ingress_index,point,V.ProgramEntityKind.OPERATION)
                self._add(point,driver,None,None,K.CONTAINS,Meaning.STRUCTURE,(),fact)
                target=self.view.source_region(ingress.region.unit,ingress.region.template,ingress.region.region)
                frame=Frame(namespace,driver.node,None,None,target.namespace,entry=target.node,selection=fact)
                self.frames[site.id,namespace,ingress_index]=frame
                self.frame_keys[frame]=(site.id,namespace,ingress_index)
                guards=('ORIGINAL_BODY_PROTOCOL_SELECTED','PARAMETER_AND_NAMESPACE_INSTANCES_NOT_BOUND')
                if site.suspended:guards+=('START_OR_ACTIVE_RESUME_POSITION_MUST_BE_SELECTED',)
                for anchor in anchors:
                    self._add(self._port(anchor.operation),driver,None,None,K.CONTROL_FLOW,Meaning.ORDER,
                        (*guards,'SOURCE_OPERATION_ALTERNATIVE_SELECTED'),fact)
                    for port,kind in zip(anchor.arguments,anchor.types):
                        self._add(self._port(port),driver,None,None,K.STATE_INPUT if _state(kind) else K.OPERAND,
                            Meaning.STATE_INTERFACE if _state(kind) else Meaning.DEPENDENCE,
                            (*guards,'HIDDEN_PATH_INPUT_DEPENDENCE_NOT_ALIAS'),fact)
                world_type=ingress.types[ingress.world_index]
                world=self._node(site,namespace,'CURRENT_WORLD',ingress_index,driver,V.ProgramEntityKind.VALUE,world_type)
                self._add(driver,world,None,None,K.STATE_OUTPUT,Meaning.STATE_INTERFACE,
                    (*guards,'PREFIX_EFFECTS_UNKNOWN_FRESH_CURRENT_WORLD'),fact)
                self._add(driver,target,frame,'ENTER',K.CALL_TARGET,Meaning.DEPENDENCE,guards,fact)
                saved=dict(ingress.saved)
                for port,kind in zip(ingress.parameters,ingress.types):
                    formal=self._port(port)
                    if port in saved:
                        self._add(self._port(saved[port]),formal,frame,'LOCAL',K.PROJECTION,Meaning.REFERENCE,
                            (*guards,'SAVED_REFERENCE_SAME_ACTIVATION_NOT_CONTENT_SNAPSHOT'),fact)
                    else:
                        self._add(world if _state(kind) else driver,formal,frame,'ENTER',
                            K.STATE_INTERFACE if _state(kind) else K.PROJECTION,
                            Meaning.STATE_INTERFACE if _state(kind) else Meaning.DEPENDENCE,guards,fact)
                for completion_index,completion in enumerate(interface.completions):
                    post=self._node(site,namespace,'COMPLETE',(ingress_index,completion_index),point,V.ProgramEntityKind.OPERATION)
                    selected=(*guards,'BODY_COMPLETION_'+completion.kind.value+'_SELECTED')
                    self._add(self._port(completion.exit),post,frame,'RETURN',K.COMPLETION,Meaning.ORDER,selected,fact)
                    for port,kind in zip(completion.ports,completion.types):
                        self._add(self._port(port),post,frame,'RETURN',K.STATE_INPUT if _state(kind) else K.COMPLETION,
                            Meaning.STATE_INTERFACE if _state(kind) else Meaning.DEPENDENCE,selected,fact)
                    self._outer(post,anchors,selected,fact)
                for suspension_index,suspension in enumerate(interface.suspensions if site.suspended else ()):
                    post=self._node(site,namespace,'HANDOFF',(ingress_index,suspension_index),point,V.ProgramEntityKind.OPERATION)
                    selected=(*guards,'ACTIVE_SUSPENSION_'+_digest(suspension.step)+'_SELECTED')
                    self._add(self._port(suspension.step),post,frame,'RETURN',K.COMPLETION,Meaning.ORDER,selected,fact)
                    for port,kind in zip(suspension.arguments,suspension.types):
                        self._add(self._port(port),post,frame,'RETURN',K.STATE_INPUT if _state(kind) else K.COMPLETION,
                            Meaning.STATE_INTERFACE if _state(kind) else Meaning.DEPENDENCE,selected,fact)
                    self._outer(post,anchors,selected,fact)
        self.points[site.id]=tuple(points)

    def _outer(self,post,anchors,guards,fact):
        for anchor in anchors:
            for completion in anchor.completions:
                selected=(*guards,'WRAPPER_CONTINUATION_AND_OUTER_'+completion.kind.value+'_SELECTED')
                self._add(post,self._port(completion.exit),None,None,K.COMPLETION,Meaning.ORDER,selected,fact)
                for port,kind in zip(completion.ports,completion.types):
                    self._add(post,self._port(port),None,None,K.STATE_OUTPUT if _state(kind) else K.RESULT,
                        Meaning.STATE_INTERFACE if _state(kind) else Meaning.DEPENDENCE,
                        (*selected,'WRAPPER_RESULT_DEPENDENCE_NOT_CALLBACK_RESULT_ALIAS'),fact)

    def _check_ports(self):
        """Check requirements from IR fields against the constructed relation index."""
        for key,frame in self.frames.items():
            site_id,namespace,ingress_index=key; site=self.activations[site_id]; interface=self.interfaces[site.interface]
            ingress=interface.ingresses[ingress_index]
            rows=self.frame_rows[frame]
            inputs={self.origins.get(self._key(row[1])) for row in rows if row[3] in ('ENTER','LOCAL')}
            sources={self.origins.get(self._key(row[0])) for row in rows if row[3] in ('LOCAL','RETURN')}
            required_inputs=set(); required_sources=set()
            for path,role in self.port_rules:
                for indices,port in _walk_ports(interface,path):
                    if port is None:continue
                    if path[0]=='ingresses' and indices[0]!=ingress_index:continue
                    if role=='HANDOFF' and not site.suspended:continue
                    (required_inputs if role in ('INPUT','SAVED_INPUT') else required_sources).add(port)
            target=self.view.source_region(ingress.region.unit,ingress.region.template,ingress.region.region)
            control=any(row[1]==target and row[3]=='ENTER' and row[4] is K.CALL_TARGET for row in rows)
            if not control or not required_inputs<=inputs or not required_sources<=sources:
                raise ValueError('activation graph misses a required original ingress/completion/saved/handoff port')
            self.covered.update((site_id,namespace,ingress_index,port) for port in required_inputs|required_sources)

    def describe(self,point):
        row=self.nodes.get(self._key(point))
        if row is None:return None
        self.store.check(); _,_,_,owner,kind,value_type=row
        return V.ProgramNode(point,kind,V.ProgramNodeRole.PROVIDER,replace(owner,context=point.context),value_type)

    def original(self,point):return self.nodes[self._key(point)][0]
    def expand(self,point):
        site=self.original(point)
        return tuple(edge.target for edge in self.outgoing(point).edges if edge.kind in (K.CONTAINS,K.CALL_TARGET))
    def explain(self,point):
        site=self.original(point)
        return dict(original=site,interface=self.interfaces[site.interface],observations=tuple(self.observations[site.id]),
            argument_aliases_proven=False,namespace_instances_bound=False,resume_position_selected=False,
            callback_result_is_outer_result=False,first_stage_complete=False)

    def _neighbors(self,point,incoming):
        self.store.check(); rows=(self.in_edges if incoming else self.out_edges).get(self._key(point),()); edges=[]
        for left,right,frame,flow,kind,meaning,guards,fact in rows:
            context=point.context
            if flow=='STATIC':
                if context is not None:continue
                source,target=left,right
            elif flow=='ENTER':
                if incoming:
                    popped=context_pop(context,(frame,))
                    if not popped.matched:continue
                    source,target=replace(left,context=popped.remaining),replace(right,context=context)
                else:source,target=replace(left,context=context),replace(right,context=context_push(context,frame))
            elif flow=='RETURN':
                if incoming:source,target=replace(left,context=context_push(context,frame)),replace(right,context=context)
                else:
                    popped=context_pop(context,(frame,))
                    if not popped.matched:continue
                    source,target=replace(left,context=context),replace(right,context=popped.remaining)
            elif flow=='LOCAL':
                if not context_pop(context,(frame,)).matched:continue
                source,target=replace(left,context=context),replace(right,context=context)
            else:source,target=replace(left,context=context),replace(right,context=context)
            conditions=tuple(Condition(SCHEMA,guard,source,n,(source,target)) for n,guard in enumerate(guards))
            evidence=Evidence(SCHEMA+'.original-body-protocol', (self.locator,), (source,target))
            edges.append(Edge(source,target,kind,meaning,(evidence,),conditions,Strength.MAY))
        return Neighborhood(tuple(edges),())

    def outgoing(self,point):return self._neighbors(point,False)
    def incoming(self,point):return self._neighbors(point,True)


def verify_body_activations(path,out,*,index=None):
    """Read stored tables and every balanced relation; reuse an admitted index."""
    from scar.analysis.source_stage import _durable_bytes
    from scar.analysis.source_template_links import _json
    started=time.monotonic(); store=SourceBodyActivationStore(path,index=index)
    provider=SourceBodyActivationProvider(store.view,store)
    checked=0
    for rows in provider.out_edges.values():
        for left,right,frame,flow,*_ in rows:
            source=left
            if flow in ('RETURN','LOCAL'):source=replace(left,context=context_push(None,frame))
            expected_context=context_push(None,frame) if flow in ('ENTER','LOCAL') else None
            matches=[edge for edge in provider.outgoing(source).edges
                if provider._key(edge.target)==provider._key(right) and edge.target.context==expected_context]
            if not matches:raise ValueError('required activation relation is not queryable in its declared frame')
            for edge in matches:
                if edge not in provider.incoming(edge.target).edges:
                    raise ValueError('activation incoming/outgoing queries disagree')
                checked+=1
    # A return cannot escape through an unrelated activation selection.
    checked_frames=0
    for frame,rows in provider.frame_rows.items():
        returns=[row for row in rows if row[3]=='RETURN']
        if not returns:continue
        row=returns[0]; wrong=replace(frame,operation=OperationID(_digest(('unrelated-frame',frame.operation))))
        query=replace(row[0],context=context_push(None,wrong))
        if any(provider._key(edge.target)==provider._key(row[1]) and edge.target.context is None
                for edge in provider.outgoing(query).edges):
            raise ValueError('activation return accepted an unrelated frame')
        checked_frames+=1
    store.check()
    report=dict(schema=SCHEMA+'.graph-check',schema_version=1,status='STRUCTURE_VERIFIED',
        coverage=store.report['coverage'],shared_activations=len(provider.activations),
        ingress_frames=len(provider.frames),required_ports_checked=len(provider.covered),
        bidirectional_edges_checked=checked,unrelated_return_frames_rejected=checked_frames,
        first_stage_complete=False,target_executed=False,source_bodies_copied=False,
        seconds=time.monotonic()-started)
    out=Path(out);out.parent.mkdir(parents=True,exist_ok=True)
    _durable_bytes(out,_json(report),replace=False)
    return report


__all__=['SourceBodyActivationProvider','body_port_contract','verify_body_activations']
