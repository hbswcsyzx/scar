"""Common-graph projections of original field/index protocol requests.

The owned receiver Use, exact selectors and coarse world remain linked.
No default descriptor, alias, physical write or content equality is inferred.
"""
from collections import defaultdict
from dataclasses import replace

from scar.analysis.program_view import _digest
from scar.analysis.source_namespace_interfaces import NamespacePlanView
from scar.ir.program import source_content as C, view as V, model as M, normal_graph as G
from scar.ir.program.dependencies import (DependencyPoint as Point, DependencyEdge,
    DependencyCondition, DependencyEvidence, DependencyFrontier, DependencyNeighborhood,
    DependencyKind as K, DependencyMeaning as Meaning)
from scar.ir.program.ids import LocationID, ValueID
from scar.ir.program.normal_targets import GlobalPort


class SourceContentProvider:
    def __init__(self, state, *, register=True):
        from scar.analysis.source_content_interfaces import ContentInterfaceIndex
        self.bindings=state;self.view=state.view;self.source=state.source;self.namespace=state.namespace
        self.addresses={};self.projections={};self.accesses=[];self.operation_accesses=defaultdict(list)
        self.address_accesses=defaultdict(list)
        self.in_edges=defaultdict(list);self.out_edges=defaultdict(list)
        interfaces=ContentInterfaceIndex(self.source)
        for key,plan in self.source.plans.items():
            context=NamespacePlanView(self.source.unit,plan)
            for step in plan.steps:
                interface=interfaces.identify(context,step)
                if interface is None:continue
                operation=self.source._node(key,step.id)
                address=self._address(interface.receiver,interface.selector)
                before,after=context.worlds(step)
                previous=self._project(address,before);following=self._project(address,after)
                use=self.source.port(context.emitter.port(step.id,G.PortKind.ARGUMENT,interface.receiver_argument))
                record=C.ContentAccessTemplate(operation.node,context.site(step),context.owner(step.region).owner,
                    C.ContentRequestKind(interface.kind),address.id,use.node,interface.payload,interface.result,
                    before,after,previous.id,following.id,interface.attribute_fact)
                ordinal=len(self.accesses);self.accesses.append(record);self.operation_accesses[operation.node].append(ordinal)
                self.address_accesses[address.id].append(ordinal)
                location=Point(self.namespace,address.id)
                selected=DependencyCondition('scar.source-content.request','SELECTED_PROTOCOL_ADDRESS_INSTANCE',
                    operation,ordinal,(use,location))
                self._edge(use,location,K.ENVIRONMENT,Meaning.STATE_INTERFACE,(selected,))
                if type(address.selector) is C.ItemSelector:
                    keys=(address.selector.key,)
                elif type(address.selector) is C.SliceBoundsSelector:
                    keys=(address.selector.lower,address.selector.upper)
                else:keys=()
                for key_port in keys:
                    if type(key_port) is GlobalPort:
                        self._edge(self.view.source_port(key_port),location,K.PROJECTION,Meaning.DEPENDENCE,(selected,))
                self._edge(Point(self.namespace,previous.id),operation,K.STATE_INPUT,Meaning.STATE_INTERFACE,(selected,))
                completed=DependencyCondition('scar.source-content.request','ORIGINAL_NORMAL_COMPLETION_SELECTED',
                    self.view.source_port(after),ordinal,(operation,Point(self.namespace,following.id)))
                self._edge(operation,Point(self.namespace,following.id),K.STATE_OUTPUT,Meaning.STATE_INTERFACE,(selected,completed))
        if register:self.view.register(self)

    def _address(self,receiver,selector):
        identity=LocationID(_digest(('scar.source-content-address.v1',self.source.basis,receiver,selector)))
        if identity not in self.addresses:
            parameters=(C.ContentInstanceParameter.ACTIVATION,C.ContentInstanceParameter.OWNER_REFERENCE_OCCURRENCE)
            if type(selector) is not C.FieldSelector:
                parameters+= (C.ContentInstanceParameter.SELECTOR_REFERENCE_OCCURRENCES,)
            self.addresses[identity]=C.ContentAddressTemplate(identity,receiver,selector,parameters)
        return self.addresses[identity]

    def _project(self,address,world):
        source=self.view.source_port(world)
        if self.view.get(source).value_type.kind is not M.ValueKind.STATE:
            raise ValueError('content projection requires the original state world')
        identity=ValueID(_digest(('scar.source-content-state.v1',self.source.basis,address.id,world)))
        if identity not in self.projections:
            record=C.ContentStateProjection(identity,address.id,world);self.projections[identity]=record
            value=Point(self.namespace,identity);location=Point(self.namespace,address.id)
            selected=DependencyCondition('scar.source-content.projection','SAME_SELECTED_ADDRESS_INSTANCE',source,None,(location,value))
            self._edge(location,value,K.STATE_LOCATION,Meaning.STRUCTURE)
            self._edge(source,value,K.PROJECTION,Meaning.STATE_INTERFACE,(selected,))
        return self.projections[identity]

    def _edge(self,source,target,kind,meaning,conditions=()):
        edge=DependencyEdge(source,target,kind,meaning,
            (DependencyEvidence('scar.source-content.interface.v1',(self.source.locator,),(source,target)),),tuple(conditions))
        if edge not in self.out_edges[source.node]:
            self.out_edges[source.node].append(edge);self.in_edges[target.node].append(edge)

    def check(self,point=None):self.bindings.check(point)

    def describe(self,point):
        if point.namespace!=self.namespace:return None
        self.check(point)
        if point.node in self.addresses:
            return V.ProgramNode(point,V.ProgramEntityKind.STATE_LOCATION,V.ProgramNodeRole.STATE_LOCATION,None,None)
        if point.node in self.projections:
            record=self.projections[point.node]
            return V.ProgramNode(point,V.ProgramEntityKind.VALUE,V.ProgramNodeRole.CORE_VALUE,None,
                M.ValueType(M.ValueKind.STATE,location=record.address))
        return None

    def original(self,point):
        if self.describe(point) is None:raise ValueError('content endpoint is not admitted')
        return self.addresses[point.node] if point.node in self.addresses else self.projections[point.node]

    def expand(self,point):
        self.original(point)
        return tuple(Point(self.namespace,p.id,point.context) for p in self.projections.values() if p.address==point.node)

    def explain(self,point):
        record=self.original(point)
        address=point.node if point.node in self.addresses else record.address
        accesses=tuple(self.accesses[i] for i in self.address_accesses[address])
        return dict(node=self.describe(point),original=self.original(point),source_material=self.source.material.result_artifact,
            accesses=accesses,attribute_facts=tuple((a.attribute_fact,self.source.facts.attributes[a.attribute_fact])
                for a in accesses if a.attribute_fact is not None),
            protocol_effects_closed=False,physical_address_selected=False,logical_version_equality_proven=False)

    def _neighbors(self,point,incoming):
        if point.namespace!=self.namespace:return DependencyNeighborhood()
        self.check(point)
        rows=self.in_edges[point.node] if incoming else self.out_edges[point.node]
        edges=tuple(replace(edge,source=replace(edge.source,context=point.context),target=replace(edge.target,context=point.context),
            conditions=tuple(replace(c,subject=None if c.subject is None else replace(c.subject,context=point.context),
                operands=tuple(replace(p,context=point.context) for p in c.operands)) for c in edge.conditions)) for edge in rows)
        frontiers=()
        if point.node in self.addresses or point.node in self.projections or point.node in self.operation_accesses:
            frontiers=(DependencyFrontier(point,'CONTENT_PROTOCOL_AND_INSTANCE_OPEN',
                'Request/selector/world are retained; descriptor, item method, alias and actual content versions need their contracts.'),)
        return DependencyNeighborhood(edges,frontiers)

    def incoming(self,point):return self._neighbors(point,True)
    def outgoing(self,point):return self._neighbors(point,False)
