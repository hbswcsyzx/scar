"""Selected function origins keep past creator and current caller separate.

A returned function may outlive its creator. Creator frames describe a
reference provenance, not the live caller stack or a snapshot of cell contents.
"""
from dataclasses import dataclass,replace
from collections import defaultdict
from scar.ir.program.source_returned_functions import ReturnedCallableProvenance

from scar.analysis.source_call_view import source_call_site,source_active_scope
from scar.ir.program.dependencies import (
    DependencyPoint as Point,DependencyFrame as Frame,DependencyEdge as Edge,
    DependencyKind as K,DependencyMeaning as Meaning,DependencyStrength as Strength,
    DependencyCondition as Condition,DependencyEvidence as Evidence,
    DependencyFrontier as Frontier,DependencyNeighborhood as Neighborhood,
    context_push,context_pop,context_is_closed)


@dataclass(frozen=True,slots=True)
class ReturnedCallableBinding:
    key: tuple[str,int]
    origin: Point
    callee: Point
    current_frame: Frame
    creator_frames: tuple[Frame,...]
    provenance: ReturnedCallableProvenance


class ReturnedCallableProvider:
    relation_kinds=frozenset((K.PROJECTION,))

    def __init__(self,owner):
        self.owner=owner;self.view=owner.view;self.bindings={}
        self.by_origin=defaultdict(list);self.by_callee=defaultdict(list)
        self.view.register(self)

    @staticmethod
    def _key(point):return point.namespace,point.node

    def bind(self,key,interface,frame):
        provenance=self.owner.store.callable_provenance(*key)
        if provenance is None:return
        if provenance.creation.function!=interface.link.source_callable:
            raise ValueError('returned callable origin differs from its selected source definition')
        creator=[]
        for record in provenance.creator_interfaces:
            operation,use,callee=source_call_site(self.view,record.link)
            body=record.link.body
            target=self.view.source_region(body.unit,body.template,body.region)
            creator.append(Frame(operation.namespace,operation.node,use.node,callee.node,target.namespace,
                entry=target.node,selection=record.evidence))
        origin=self.view.source_port(provenance.creation.function)
        callee=self.view.source_port(interface.link.callee)
        binding=ReturnedCallableBinding(key,origin,callee,frame,tuple(creator),provenance)
        self.bindings[key]=binding;self.by_origin[self._key(origin)].append(key);self.by_callee[self._key(callee)].append(key)

    def creator_context(self,key,caller_context):
        binding=self.bindings[key]
        active=source_active_scope(self.view,binding.callee.namespace,caller_context)
        if active is not None and active not in binding.provenance.base_scopes:return None
        context=caller_context
        for frame in binding.creator_frames:context=context_push(context,frame)
        frames=binding.creator_frames
        namespace=frames[-1].target if frames else binding.callee.namespace
        owner=source_active_scope(self.view,namespace,context)
        if owner is not None and owner!=binding.provenance.creation.creator.owner:return None
        return context

    def _neighbors(self,point,incoming):
        self.owner._demand(point)
        keys=(self.by_callee if incoming else self.by_origin).get(self._key(point),())
        if not keys:return Neighborhood()
        self.owner.store.validate();self.view.get(point);edges=[];reasons=set()
        for key in keys:
            binding=self.bindings[key]
            if incoming:caller_context=point.context
            else:
                popped=context_pop(point.context,binding.creator_frames)
                if not popped.matched:
                    reasons.add('CALLABLE_CREATOR_REFERENCE_CONTEXT_NOT_SELECTED');continue
                caller_context=popped.remaining
            creator_context=self.creator_context(key,caller_context)
            # None is a legitimate unknown base for a zero-frame origin.
            if creator_context is None and (binding.creator_frames or caller_context is not None):
                reasons.add('CALLABLE_CREATOR_BASE_SCOPE_NOT_SELECTED');continue
            source=replace(binding.origin,context=creator_context);target=replace(binding.callee,context=caller_context)
            region=self.owner.frames[key]
            call=Point(region.caller,region.operation,caller_context)
            guards=(*binding.provenance.conditions,
                'CURRENT_CALLABLE_IS_SELECTED_RETURNED_FUNCTION_OCCURRENCE',
                'CREATOR_REFERENCE_CONTEXT_IS_NOT_CURRENT_CALLER_STACK',
                'CAPTURE_HANDLES_NOT_CURRENT_CELL_CONTENTS')
            conditions=tuple(Condition('scar.returned-callable.provenance',g,call,key[1],(source,target)) for g in guards)
            locator=self.owner.store.provenance_locator(*key)
            if locator is None:raise ValueError('returned callable lacks its original provenance receipt')
            edges.append(Edge(source,target,K.PROJECTION,Meaning.REFERENCE,
                (Evidence('scar.returned-callable.selected-creation.v1',
                    (locator,source.namespace.graph,target.namespace.graph),(call,source,target)),),conditions,Strength.MAY))
            reasons.add('RETURNED_CALLABLE_AND_CREATOR_CELL_VERSIONS_NOT_PROVEN')
        if edges and not context_is_closed(point.context):reasons.add('SOURCE_CALL_CONTEXT_PREFIX_OPEN')
        return Neighborhood(tuple(edges),tuple(Frontier(point,r,
            'Past creator context and current caller are separately selected; callable/cell identity and current versions remain conditional.')
            for r in sorted(reasons)))

    def incoming(self,point):return self._neighbors(point,True)
    def outgoing(self,point):return self._neighbors(point,False)
