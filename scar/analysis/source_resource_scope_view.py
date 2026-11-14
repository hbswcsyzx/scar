"""Shared source/state interfaces referencing actual scoped OS observations."""
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

from scar.analysis.source_resource_scopes import ResourceScopeStore,SCHEMA
from scar.analysis.program_view import _digest
from scar.analysis.source_call_view import prepare_source_ports
from scar.analysis.source_value_flow import _artifact
from scar.ir.program import resource_scopes as R,view as V
from scar.ir.program.ids import ProviderID,RegionID,ResourceDefinitionID
from scar.ir.program.resources import ResourceDefinition,ResourceKind,ResourceRole,ExternalResource
from scar.ir.program.model import ValueType,ValueKind
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.program.dependencies import (GraphNamespace,DependencyPoint as Point,
    DependencyEdge as Edge,DependencyKind as K,DependencyMeaning as Meaning,
    DependencyStrength as Strength,DependencyEvidence as Evidence,DependencyCondition as Condition,
    DependencyNeighborhood as Neighborhood,DependencyFrontier as Frontier)


class SourceResourceScopeProvider:
    relation_kinds=frozenset((K.CONTAINS,K.RESOURCE,K.STATE_INTERFACE))

    def __init__(self,view,store):
        self.store=store if type(store)is ResourceScopeStore else ResourceScopeStore(store)
        if self.store.index is None or view.catalog.path!=self.store.index.view.catalog.path:
            raise ValueError('resource source view requires the same admitted source catalog')
        self.view=view;self.nodes={};self.in_edges=defaultdict(list);self.out_edges=defaultdict(list)
        artifact=_artifact(self.store.path/'result.json',SCHEMA)
        self.locator=SourceArtifactLocator(artifact,artifact.sha256,artifact.size_bytes,'canonical-json')
        root=RegionID(_digest((SCHEMA+'.evidence-root',self.store.coordinates.run.id)))
        self.namespace=GraphNamespace(self.locator,SCHEMA+'.observations.v1',root)
        self.owned_namespaces=(self.namespace,)
        self.root=Point(self.namespace,root,None)
        self.nodes[root]=(self.store.report,self.root,V.ProgramEntityKind.REGION,V.ProgramNodeRole.PROVIDER)
        scopes={row.id:row for row in self.store.rows['scopes']};work=defaultdict(list)
        for row in self.store.rows['work']:work[row.scope].append(row)
        groups=defaultdict(set)
        for binding in self.store.bindings:groups[binding.anchor].add(binding.scope)
        self.interfaces={};self.group_work={};self.actors={};self.group_scopes={}
        ports=[]
        for anchor in groups:
            ports.extend((anchor.operation,*anchor.arguments))
            for completion in anchor.completions:ports.extend((*completion.ports,completion.exit))
        prepare_source_ports(view,tuple(dict.fromkeys(ports)))
        native_threads={row.tid:row for row in self.store.coordinates.threads
            if row.process==self.store.coordinates.target_process.id}
        for anchor,identities in sorted(groups.items(),key=lambda item:_digest(item[0])):
            identities=tuple(sorted(identities,key=lambda i:i.value));observations=tuple(scopes[i] for i in identities)
            original=R.SourceResourceInterface(ProviderID(_digest((SCHEMA+'.interface',artifact.sha256,anchor))),
                anchor,identities,sum(len(work[i]) for i in identities))
            group=Point(self.namespace,original.id,None)
            operation=view.unit(anchor.operation.unit)._node(anchor.operation.port.template,anchor.operation.port.owner)
            self.nodes[group.node]=(original,operation,None,V.ProgramNodeRole.PROVIDER)
            self.interfaces[group.node]=original;self.group_scopes[group.node]=observations
            self.group_work[group.node]=tuple(row for i in identities for row in work[i])
            self._add(self.root,group,K.CONTAINS,Meaning.STRUCTURE,'SHARED_SOURCE_RESOURCE_INTERFACE')
            self._add(operation,group,K.RESOURCE,Meaning.REFERENCE,'OBSERVED_NATIVE_CALL_SCOPE_NOT_EXCLUSIVE_WORK_OR_COST')
            for port,type_ in zip(anchor.arguments,anchor.types):
                if type(type_)is ValueType and type_.kind is ValueKind.STATE:
                    self._add(view.source_port(port),group,K.STATE_INTERFACE,Meaning.STATE_INTERFACE,
                        'ORIGINAL_INPUT_WORLD_NOT_RECONSTRUCTED_RESOURCE_CONTENT')
            for completion in anchor.completions:
                for port,type_ in zip(completion.ports,completion.types):
                    if type(type_)is ValueType and type_.kind is ValueKind.STATE:
                        self._add(group,view.source_port(port),K.STATE_INTERFACE,Meaning.STATE_INTERFACE,
                            'ORIGINAL_OUTPUT_WORLD_COMPLETION_AND_EFFECTS_REMAIN_CONDITIONAL')
            for tid in sorted({scope.begin.native_tid for scope in observations}):
                actor=native_threads.get(tid)
                if actor is None:raise ValueError('resource scope native thread lacks capture coordinates')
                identity=ResourceDefinitionID(_digest((SCHEMA+'.native-thread',actor.id)))
                target=Point(self.namespace,identity,None)
                definition=ResourceDefinition(identity,ResourceKind.THREAD,ResourceRole.EXECUTOR,
                    ExternalResource(root,'observed-native-thread:'+actor.id.value))
                self.nodes[identity]=(definition,self.root,V.ProgramEntityKind.RESOURCE,V.ProgramNodeRole.RESOURCE)
                self.actors[identity]=actor
                self._add(group,target,K.RESOURCE,Meaning.REFERENCE,'OBSERVED_CALLING_THREAD_NOT_DEVICE_PLACEMENT_OR_READY')
        view.register(self)

    def _add(self,source,target,kind,meaning,rule):
        guards=tuple(Condition(SCHEMA,name,source,None,(source,target)) for name in (
            'AGGREGATED_ORIGINAL_INVOCATIONS_NOT_PARAMETER_CONTENT_ALIASES',
            'OWNED_MARKER_DESCRIPTOR_AND_FILE_NOT_MODIFIED_BY_APPLICATION',rule))
        edge=Edge(source,target,kind,meaning,
            (Evidence(SCHEMA+'.original-markers-and-source-ports',(self.locator,),(source,target)),),guards,Strength.MAY)
        self.out_edges[source.namespace,source.node].append(edge);self.in_edges[target.namespace,target.node].append(edge)

    def describe(self,point):
        if point.namespace!=self.namespace or point.node not in self.nodes:return None
        self.store.check();_,owner,kind,role=self.nodes[point.node]
        return V.ProgramNode(point,kind,role,replace(owner,context=point.context),None)

    def original(self,point):return self.nodes[point.node][0]
    def expand(self,point):
        return tuple(edge.target for edge in self.outgoing(point).edges if edge.kind is K.CONTAINS)
    def explain(self,point):
        return dict(original=self.original(point),scopes=self.group_scopes.get(point.node,()),
            work=self.group_work.get(point.node,()),actor=self.actors.get(point.node),
            marker_writes_excluded=True,direct_program_origin_proven=False,
            resource_contents_or_readiness_proven=False,clock_matching_used=False)

    def _neighbors(self,point,incoming):
        rows=(self.in_edges if incoming else self.out_edges).get((point.namespace,point.node),())
        if not rows:return Neighborhood()
        self.store.check()
        if point.context:
            return Neighborhood((),(Frontier(point,'RESOURCE_SCOPE_INVOCATION_CONTEXT_UNSELECTED',
                'Actual invocation evidence is retained; this static call context has not selected one.'),),False)
        return Neighborhood(tuple(replace(edge,source=replace(edge.source,context=point.context),
            target=replace(edge.target,context=point.context)) for edge in rows))

    def incoming(self,point):return self._neighbors(point,True)
    def outgoing(self,point):return self._neighbors(point,False)


def verify_resource_scope_graph(path,out,*,index=None):
    """Read stored observations and check every exposed relation in both directions."""
    import time
    from scar.analysis.source_stage import _durable_bytes
    from scar.analysis.source_template_links import _json
    started=time.monotonic();store=ResourceScopeStore(path,index=index)
    provider=SourceResourceScopeProvider(store.index.view,store);checked=0
    for edges in provider.out_edges.values():
        for edge in edges:
            if edge not in provider.outgoing(edge.source).edges or edge not in provider.incoming(edge.target).edges:
                raise ValueError('source/state/resource relation is not bidirectionally queryable')
            checked+=1
    if any(edge.kind is K.ALIAS for edges in provider.out_edges.values() for edge in edges):
        raise ValueError('resource scope evidence must not invent content aliases')
    r=dict(schema=SCHEMA+'.graph-check',status='STRUCTURE_VERIFIED',summary=store.report['summary'],
        shared_interfaces=len(provider.interfaces),actual_thread_resources=len(provider.actors),
        bidirectional_relations=checked,source_bodies_copied=False,clock_matching_used=False,
        exclusive_program_work_or_resource_content_proven=False,first_stage_complete=False,
        seconds=time.monotonic()-started)
    _durable_bytes(Path(out),_json(r),replace=False);return r
