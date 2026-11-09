"""Initial factory operand roles over existing F4 Uses and operations."""
from collections import Counter,defaultdict
from dataclasses import replace

from scar.analysis.source_function_creations import SourceFunctionCreationStore
from scar.analysis.source_namespace_interfaces import NamespacePlanView
from scar.analysis.source_value_flow import _artifact
from scar.ir.program import normal_graph as G
from scar.ir.program.ids import OperationID,UseID,ValueID
from scar.ir.program.dependencies import (
    DependencyCondition as Condition,DependencyEdge as Edge,DependencyEvidence as Evidence,
    DependencyKind as Kind,DependencyMeaning as Meaning,DependencyStrength as Strength,
    DependencyNeighborhood as Neighborhood)
from scar.ir.program.source_references import SourceArtifactLocator


class SourceFunctionCreationProvider:
    """Role edges are creation dependencies, never current-content aliases.

    Default expression-to-factory forwarding remains in original F4 edges.
    The retained operand Use is labeled here, without entering the body or
    assigning a creation activation to a later caller's context.
    """
    relation_kinds=frozenset((Kind.FIELD_INITIALIZER,Kind.ENVIRONMENT))

    def __init__(self,view,creations,*,units=()):
        self.view=view
        self.store=creations if isinstance(creations,SourceFunctionCreationStore) else SourceFunctionCreationStore(creations,catalog=view.catalog)
        if (self.store.catalog.path,self.store.catalog.report)!=(view.catalog.path,view.catalog.report):
            raise ValueError('creation roles require the same original source catalog')
        self.graphs={};self.records={};self.in_edges=defaultdict(list);self.out_edges=defaultdict(list)
        self.roles=Counter();artifact=_artifact(self.store.path/'result.json',self.store.report['schema'])
        self.manifest=SourceArtifactLocator(artifact,artifact.sha256,artifact.size_bytes,'canonical-json')
        for unit in units:self.attach(unit)
        view.register(self)

    def attach(self,unit):
        if unit in self.graphs:return self.graphs[unit]
        graph=self.store.read_unit(unit);self.graphs[unit]=graph
        source=self.view.unit(unit);source._expand(graph.templates)
        for ordinal,record in enumerate(graph.creations):
            operation=source._node(record.site.port.template,record.site.port.owner)
            step=self.view.original(operation);plan=source.plans[record.site.port.template]
            context=NamespacePlanView(unit,plan)
            if context.result(step)!=record.function:raise ValueError('creation role has a different factory result')
            result=self.view.source_port(record.function);self.records[source.namespace,result.node]=record
            roles=[('CODE',0,Kind.ENVIRONMENT),('GLOBALS',1,Kind.ENVIRONMENT)]
            roles.extend(('INITIAL_DEFAULT',d.operand_ordinal,Kind.FIELD_INITIALIZER) for d in record.defaults)
            roles.extend(('CELL_HANDLE_NOT_CONTENT',c.operand_ordinal,Kind.ENVIRONMENT) for c in record.captures)
            if record.annotation is not None:
                found=[i for i,v in enumerate(step.arguments[:-1]) if context.value(v)==record.annotation]
                if len(found)!=1:raise ValueError('annotation role lacks its exact original owned operand')
                roles.append(('DEFERRED_ANNOTATION_OPERAND',found[0],Kind.ENVIRONMENT))
            locator=replace(self.manifest,pointer='#/shards/'+unit+'/tables/creations')
            for role,index,kind in roles:
                use=source.port(context.emitter.port(step.id,G.PortKind.ARGUMENT,index))
                condition=Condition('scar.source-creation.operand',role,operation,index,(use,result))
                evidence=Evidence('scar.source-creation.initial-operand-role.v1',(source.locator,locator),(use,operation))
                edge=Edge(use,operation,kind,Meaning.DEPENDENCE,(evidence,),(condition,),Strength.MAY)
                self.out_edges[source.namespace,use.node].append(edge)
                self.in_edges[source.namespace,operation.node].append(edge);self.roles[role]+=1
        self.store.validate();return graph

    def _demand(self,point):
        if type(point.node) not in (OperationID,UseID,ValueID):return
        source=self.view.namespaces.get(point.namespace)
        unit=getattr(source,'unit',None)
        if unit in self.store.report['shards'] and unit not in self.graphs:self.attach(unit)

    def creation(self,point):
        self._demand(point);self.view.get(point)
        return self.records.get((point.namespace,point.node))

    def _neighbors(self,point,incoming):
        self._demand(point);rows=(self.in_edges if incoming else self.out_edges).get((point.namespace,point.node),())
        if not rows:return Neighborhood()
        self.store.validate();self.view.get(point)
        return Neighborhood(tuple(replace(e,source=replace(e.source,context=point.context),
            target=replace(e.target,context=point.context),conditions=tuple(replace(c,
                subject=None if c.subject is None else replace(c.subject,context=point.context),
                operands=tuple(replace(p,context=point.context) for p in c.operands)) for c in e.conditions)) for e in rows))

    def incoming(self,point):return self._neighbors(point,True)
    def outgoing(self,point):return self._neighbors(point,False)

    def summary(self):
        return dict(available_units=len(self.store.report['shards']),units=len(self.graphs),
            creations=len(self.records),operand_roles=dict(self.roles),
            current_defaults_or_cells_proven=False,creation_instances_selected=False)
