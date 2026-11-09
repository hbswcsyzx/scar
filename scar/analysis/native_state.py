"""Native type/alias declarations attached to the same dependency interface.

Original entry/exit/world coordinates are never replaced. Alias groups are
stored once and expose may-dependencies on demand, without a dense alias table.
"""
from collections import defaultdict
from dataclasses import replace

from scar.analysis.program_view import ProgramView,_digest
from scar.ir.program import native_state as N,view as V,model as M
from scar.ir.program.dependencies import (DependencyPoint as Point,DependencyEdge,DependencyEvidence,
    DependencyCondition,DependencyFrontier,DependencyNeighborhood,DependencyKind as K,
    DependencyMeaning as Meaning,DependencyStrength as Strength)
from scar.ir.program.ids import LocationID,ValueID
from scar.ir.program.native_resource_declarations import TypeProjection as PathPart
from scar.ir.program.providers import ProviderFactReference


def _leaves(type_,path=(),pointer=''):
    if type_.kind in ('OptionalType','ListType'):
        part=PathPart.OPTIONAL_ELEMENT if type_.kind=='OptionalType' else PathPart.LIST_ELEMENT
        yield from _leaves(type_.element,(*path,part),pointer+'/element')
    elif type_.kind=='BaseType' and type_.name in ('Tensor','Generator'):
        yield N.NativeStateCategory(type_.name.upper()),path,pointer


class NativeStateProvider:
    def __init__(self,unit):
        self.unit=unit;self.namespace=unit.namespace;self.index=unit.index
        self.addresses={};self.projections={};self.accesses=[];self.groups=[]
        self.in_edges=defaultdict(list);self.out_edges=defaultdict(list);self.group_memberships=defaultdict(list)
        boundary=unit.boundary;index=unit.index
        operations=[op for op in index.operations.values() if op.terminator is not None
            and op.terminator.kind is M.TerminatorKind.INVOKE
            and index._blocks[index._operation_blocks[op.id]]==boundary.region]
        if len(operations)!=1:raise ValueError('native local profile needs its one original boundary invocation')
        operation=operations[0];self.operation=operation.id
        worlds=[index.entry_port(slot.port).id for slot in boundary.core_inputs
            if type(index.entry_port(slot.port)) is M.StateVersionValue]
        if len(worlds)!=1:raise ValueError('native boundary needs its original unique state input')
        world_before=worlds[0];completed={}
        for slot in boundary.core_outputs:
            for site in index.exit_port_uses(slot.port):
                value=index.values[site.use.value]
                if type(value) is M.StateVersionValue:
                    completed.setdefault(slot.port.exit_name,set()).add(value.id)
        if any(len(values)!=1 for values in completed.values()) or set(completed)!={'normal','raised'}:
            raise ValueError('native state exits differ from original normal/raised world coordinates')
        world_normal=next(iter(completed['normal']));world_raised=next(iter(completed['raised']))
        memberships=defaultdict(list)
        for direction,field,ports,slots in ((N.NativePortDirection.INPUT,'inputs',unit.declaration.inputs,boundary.inputs),
                (N.NativePortDirection.OUTPUT,'outputs',unit.declaration.outputs,boundary.outputs)):
            for position,(port,slot) in enumerate(zip(ports,slots,strict=True)):
                if direction is N.NativePortDirection.INPUT:
                    reference=index.entry_port(slot.port).id
                else:
                    results={site.use.value for site in index.exit_port_uses(slot.port)}
                    if len(results)!=1:raise ValueError('native return needs its original unique declared result')
                    reference=next(iter(results))
                for category,path,tail in _leaves(port.type):
                    identity=LocationID(_digest(('scar.native-state.address.v1',unit.namespace.identity,boundary.id,slot.port,path,category)))
                    parameters=(N.NativeStateParameter.INVOCATION,N.NativeStateParameter.PORT_VALUE_INSTANCE)
                    if PathPart.OPTIONAL_ELEMENT in path:parameters+=(N.NativeStateParameter.OPTIONAL_LEAF_PRESENT,)
                    if PathPart.LIST_ELEMENT in path:parameters+=(N.NativeStateParameter.LIST_ELEMENT_SELECTIONS,)
                    fact=ProviderFactReference(unit.declaration_fact.artifact,
                        unit.declaration_fact.locator+'/'+field+'/'+str(position)+'/type'+tail)
                    alias=port.alias
                    address=N.NativeStateAddress(identity,boundary.id,slot.port,direction,position,reference,category,
                        port.type.text,path,fact,None if alias is None else alias.before,
                        None if alias is None else alias.may_write,None if alias is None else alias.after,parameters)
                    self.addresses[identity]=address
                    location=self.point(identity);owner=self.point(reference)
                    selected=DependencyCondition('scar.native-state.instance','SELECTED_NATIVE_PORT_LEAF_PRESENT',
                        self.point(boundary.id),position,(owner,location))
                    self._edge(owner,location,K.ENVIRONMENT,Meaning.STATE_INTERFACE,(selected,))
                    previous=self._project(address,world_before) if direction is N.NativePortDirection.INPUT else None
                    normal=self._project(address,world_normal)
                    raised=self._project(address,world_raised) if previous is not None else None
                    access=N.NativeStateAccess(operation.id,identity,world_before if previous is not None else None,
                        world_normal,world_raised if raised is not None else None,
                        None if previous is None else previous.id,normal.id,None if raised is None else raised.id)
                    self.accesses.append(access)
                    if previous is not None:self._edge(self.point(previous.id),self.point(operation.id),K.STATE_INPUT,Meaning.STATE_INTERFACE,(selected,))
                    for value,exit_ in ((normal,'normal'),(raised,'raised')):
                        if value is None:continue
                        completed_=DependencyCondition('scar.native-state.completion',exit_,self.point(value.world),None,(self.point(operation.id),))
                        self._edge(self.point(operation.id),self.point(value.id),K.STATE_OUTPUT,Meaning.STATE_INTERFACE,(selected,completed_))
                    if alias is not None:
                        for phase,labels in ((N.AliasAnnotationPhase.BEFORE,alias.before),(N.AliasAnnotationPhase.EXPLICIT_AFTER,alias.after)):
                            for label in labels:memberships[phase,label].append(identity)
        for (phase,label),members in memberships.items():
            group=N.NativeAliasGroup(boundary.id,unit.declaration_fact,phase,label,tuple(dict.fromkeys(members)),label=='*')
            self.groups.append(group)
            for identity in group.members:self.group_memberships[identity].append(group)

    def point(self,node):return Point(self.namespace,node)

    def _project(self,address,world):
        identity=ValueID(_digest(('scar.native-state.projection.v1',self.namespace.identity,address.id,world)))
        if identity not in self.projections:
            self.projections[identity]=N.NativeStateProjection(identity,address.id,world)
            self._edge(self.point(address.id),self.point(identity),K.STATE_LOCATION,Meaning.STRUCTURE)
            selected=DependencyCondition('scar.native-state.projection','SAME_SELECTED_NATIVE_ADDRESS_INSTANCE',
                self.point(world),None,(self.point(address.id),self.point(identity)))
            self._edge(self.point(world),self.point(identity),K.PROJECTION,Meaning.STATE_INTERFACE,(selected,))
        return self.projections[identity]

    def _edge(self,source,target,kind,meaning,conditions=(),strength=Strength.EXACT,rule='scar.native-state.local.v1'):
        edge=DependencyEdge(source,target,kind,meaning,
            (DependencyEvidence(rule,(self.namespace.graph,),(source,target)),),tuple(conditions),strength)
        if edge not in self.out_edges[source.node]:
            self.out_edges[source.node].append(edge);self.in_edges[target.node].append(edge)
        return edge

    def describe(self,point):
        if point.namespace!=self.namespace:return None
        owner=self.point(self.unit.boundary.region)
        if point.node in self.addresses:
            return V.ProgramNode(point,V.ProgramEntityKind.STATE_LOCATION,V.ProgramNodeRole.STATE_LOCATION,
                replace(owner,context=point.context),None)
        if point.node in self.projections:
            value=self.projections[point.node]
            return V.ProgramNode(point,V.ProgramEntityKind.VALUE,V.ProgramNodeRole.CORE_VALUE,
                replace(owner,context=point.context),M.ValueType(M.ValueKind.STATE,location=value.address))
        return None

    def original(self,point):
        if self.describe(point) is None:raise ValueError('native state point is not an admitted extension')
        return self.addresses[point.node] if point.node in self.addresses else self.projections[point.node]

    def expand(self,point):
        self.original(point)
        return tuple(Point(self.namespace,p.id,point.context) for p in self.projections.values() if p.address==point.node)

    def explain(self,point):
        record=self.original(point);address=point.node if point.node in self.addresses else record.address
        return dict(node=self.describe(point),original=record,declaration=self.unit.declaration_fact,
            alias_groups=tuple(self.group_memberships.get(address,())),effects_closed=False,physical_alias_proven=False)

    def _neighbors(self,point,incoming):
        if point.namespace!=self.namespace:return DependencyNeighborhood()
        rows=list(self.in_edges[point.node] if incoming else self.out_edges[point.node])
        for group in self.group_memberships.get(point.node,()):
            if group.wildcard:continue
            for peer in group.members:
                if peer==point.node:continue
                source,target=(self.point(peer),self.point(point.node)) if incoming else (self.point(point.node),self.point(peer))
                condition=DependencyCondition('scar.native-state.alias.'+group.phase.value,group.label,
                    self.point(group.boundary),None,(source,target))
                rows.append(DependencyEdge(source,target,K.PROJECTION,Meaning.DEPENDENCE,
                    (DependencyEvidence('scar.native-state.declared-may-alias.v1',(self.namespace.graph,),(source,target)),),
                    (condition,),Strength.MAY))
        edges=tuple(replace(edge,source=replace(edge.source,context=point.context),target=replace(edge.target,context=point.context),
            conditions=tuple(replace(c,subject=None if c.subject is None else replace(c.subject,context=point.context),
                operands=tuple(replace(p,context=point.context) for p in c.operands)) for c in edge.conditions)) for edge in rows)
        note=()
        if point.node in self.addresses or point.node in self.projections or point.node in (self.operation,self.unit.boundary.id):
            note=(DependencyFrontier(point,'NATIVE_STATE_INSTANCE_ALIAS_AND_EFFECTS_OPEN',
                'Types and schema alias fields are declarations; instances, wildcard/post aliases, RNG, effects and storage remain open.'),)
        return DependencyNeighborhood(edges,note)

    def incoming(self,point):return self._neighbors(point,True)
    def outgoing(self,point):return self._neighbors(point,False)


class NativeStateSession:
    """One shared view over the original canonical native units."""
    def __init__(self,materials,*,view=None):
        self.materials=materials;self.providers={};self.selectors={}
        for unit in materials.units():
            provider=NativeStateProvider(unit)
            self.providers[unit.namespace]=provider;self.selectors[unit.declaration.selector]=unit.namespace
        self.view=ProgramView(None) if view is None else view
        self.previous_loader=self.view.core_loader
        self.view.core_loader=self._index;self.view.register(self)

    def _provider(self,point):
        provider=self.providers.get(point.namespace)
        if provider is None:return None
        self.materials.check()
        if point.namespace.graph!=provider.namespace.graph:
            raise ValueError('native query locator changed its full source declaration')
        return provider

    def _index(self,namespace):
        provider=self._provider(Point(namespace,namespace.root))
        if provider is None:
            if self.previous_loader is not None:return self.previous_loader(namespace)
            raise ValueError('native source namespace is not admitted')
        return provider.index

    def describe(self,point):
        provider=self._provider(point)
        return None if provider is None else provider.describe(point)

    def original(self,point):return self._provider(point).original(point)
    def expand(self,point):return self._provider(point).expand(point)
    def explain(self,point):return self._provider(point).explain(point)
    def incoming(self,point):
        provider=self._provider(point)
        return DependencyNeighborhood() if provider is None else provider.incoming(point)
    def outgoing(self,point):
        provider=self._provider(point)
        return DependencyNeighborhood() if provider is None else provider.outgoing(point)
