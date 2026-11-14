"""Typed readback of additional binding-version relations, without solving.

The enclosing observer admits producer/input receipts and actual body choices.
This unit reader checks saved table bytes, types and endpoint closure against
the original source projection. Independent source rederivation remains the
separate state-view reader; it is not repeated for graph navigation.
"""
from collections import defaultdict
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

from scar.analysis.source_symbol_variants import _table
from scar.analysis.source_consumer_parents import _stamp
from scar.ir.program import source_state as S,source_productions as P,view as V,model as M
from scar.ir.program.source_name_definitions import NameDefinitionKind as D
from scar.ir.program.dependencies import (DependencyPoint as Point,DependencyEdge as Edge,
    DependencyCondition as Condition,DependencyEvidence as Evidence,DependencyNeighborhood as Neighborhood,
    DependencyFrontier as Frontier,DependencyKind as K)
from scar.ir.program.providers import ProviderArtifact
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.record_codec import decode,encode


TABLES=frozenset(('rules','requests','locations','accesses','versions','selections','tracks','edges',
    'content_addresses','content_states','content_accesses','content_edges'))


class StoredBindingVersions:
    def __init__(self,view,folder,header,summary):
        self.folder=Path(folder);self.header=header;self.summary=summary
        self.source=view.project_unit(header['unit']);self.namespace=self.source.namespace
        if (encode(self.namespace)!=header['namespace']
                or encode(self.source.material.result_artifact)!=header['source_material']
                or set(header['tables'])!=TABLES or header['original_body_bytes_copied']!=0
                or any(header[k]is not False for k in ('loops_unrolled','target_executed',
                    'tensor_content_versions_proven','effect_membership_closed','first_stage_complete'))):
            raise ValueError('stored binding source domain, table grammar or authority differs')
        self.guards={};self.locations={};self.versions={};self.in_edges=defaultdict(list);self.out_edges=defaultdict(list)
        for artifact in header['binding_materials']:
            p=Path(artifact['uri']);raw=p.read_bytes()
            if len(raw)!=artifact['size_bytes'] or sha256(raw).hexdigest()!=artifact['sha256']:
                raise ValueError('stored binding original C2 material changed')
            self.guards[p]=_stamp(p)
        # Check every saved table, including proof records not needed for this
        # neighborhood. Hash compressed bytes incrementally; do not decode the
        # full per-variable control histories just to follow a version edge.
        for name,receipt in header['tables'].items():
            if receipt['path']!=name+'.jsonl.gz':raise ValueError('stored binding table path differs')
            p=self.folder/receipt['path'];before=_stamp(p);digest=sha256();size=0
            with p.open('rb') as stream:
                for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block);size+=len(block)
            if size!=receipt['bytes'] or digest.hexdigest()!=receipt['sha256'] or _stamp(p)!=before:
                raise ValueError('stored binding table receipt changed')
            self.guards[p]=before
        for name,cls,target in (('locations',S.BindingLocationTemplate,self.locations),
                ('versions',S.BindingVersionTemplate,self.versions)):
            for wire in _table(self.folder,header['tables'][name]):
                row=decode(cls,wire,record_tags=P.PRODUCTION_RECORD_TAGS)
                if row.id in target:raise ValueError('duplicate stored binding identity')
                target[row.id]=row
            if len(target)!=header['counts'][name]:raise ValueError('stored binding node denominator differs')
        for row in self.versions.values():
            bound=(S.BindingBoundness.BOUND if row.kind in (D.FORMAL,D.WRITE) else
                S.BindingBoundness.UNBOUND if row.kind is D.DELETE else S.BindingBoundness.UNKNOWN)
            if row.location not in self.locations or row.source_function.unit!=header['unit'] or row.boundness is not bound:
                raise ValueError('stored binding version location/function/boundness differs')
        raw=(self.folder/'result.json').read_bytes()
        artifact=ProviderArtifact(str(self.folder/'result.json'),sha256(raw).hexdigest(),len(raw),'scar.source-state-view')
        self.locator=SourceArtifactLocator(artifact,artifact.sha256,artifact.size_bytes,'canonical-json')
        point=lambda identity:Point(self.namespace,identity,None)
        known=lambda identity:identity in self.source.nodes or identity in self.locations or identity in self.versions
        count=0;self.projected_relations=0
        for wire in _table(self.folder,header['tables']['edges']):
            row=decode(S.StoredBindingEdge,wire,record_tags=P.PRODUCTION_RECORD_TAGS);count+=1
            if not all(known(n) for n in (row.source,row.target,
                    *(c.subject for c in row.conditions if c.subject is not None),
                    *(n for c in row.conditions for n in c.operands))):
                raise ValueError('stored binding edge has an undeclared source/state endpoint')
            if row.source not in self.versions and row.target not in self.versions:continue
            conditions=tuple(Condition(c.domain,c.name,None if c.subject is None else point(c.subject),
                c.index,tuple(point(n) for n in c.operands)) for c in row.conditions)
            edge=Edge(point(row.source),point(row.target),row.kind,row.meaning,
                (Evidence(row.rule,(self.locator,),(point(row.source),point(row.target))),),conditions,row.strength)
            self.in_edges[row.target].append(edge);self.out_edges[row.source].append(edge);self.projected_relations+=1
        if count!=header['counts']['relations']:raise ValueError('stored binding edge denominator differs')
        self.check()

    def check(self,point=None):
        self.source.check(point)
        if any(_stamp(p)!=stamp for p,stamp in self.guards.items()):
            raise ValueError('admitted stored binding unit changed')

    def describe(self,point):
        if point.namespace!=self.namespace:return None
        self.check(point)
        if point.node in self.locations:
            return V.ProgramNode(point,V.ProgramEntityKind.STATE_LOCATION,V.ProgramNodeRole.STATE_LOCATION,None,None)
        if point.node in self.versions:
            row=self.versions[point.node]
            return V.ProgramNode(point,V.ProgramEntityKind.VALUE,V.ProgramNodeRole.CORE_VALUE,None,
                M.ValueType(M.ValueKind.STATE,location=row.location))
        return None

    def original(self,point):
        if self.describe(point)is None:raise ValueError('point is not a stored binding state node')
        return self.locations.get(point.node) or self.versions[point.node]

    def expand(self,point):
        self.original(point)
        return tuple(Point(self.namespace,row.id,point.context) for row in self.versions.values() if row.location==point.node)

    def explain(self,point):
        return dict(node=self.describe(point),original=self.original(point),stored_source=self.locator,
            source_rederived_now=False,admission='PINNED_TYPED_STORED_STATE_WITH_ENDPOINT_CLOSURE',
            binding_versions_not_tensor_contents=True,runtime_instance_selected=False,
            track_summary=self.summary,independent_replay='scar state-view --read '+str(self.folder))

    def _neighbors(self,point,incoming):
        if point.namespace!=self.namespace:return Neighborhood()
        self.check(point);rows=(self.in_edges if incoming else self.out_edges).get(point.node,())
        edges=tuple(replace(e,source=replace(e.source,context=point.context),target=replace(e.target,context=point.context),
            conditions=tuple(replace(c,subject=None if c.subject is None else replace(c.subject,context=point.context),
                operands=tuple(replace(p,context=point.context) for p in c.operands)) for c in e.conditions)) for e in rows)
        frontiers=[]
        if point.node in self.locations or point.node in self.versions:
            frontiers.append(Frontier(point,'STATE_INSTANCE_AND_OBJECT_CONTENT_NOT_SELECTED',
                'Static binding versions require frame/occurrence selection and are not tensor contents.'))
        if rows and self.summary['budget_or_control_incomplete']:
            frontiers.append(Frontier(point,'SOURCE_BINDING_TRACK_COVERAGE_REQUIRES_SELECTION',
                'Some tracks in this unit are open; saved track/selection records qualify each read.'))
        return Neighborhood(edges,tuple(frontiers))

    def incoming(self,point):return self._neighbors(point,True)
    def outgoing(self,point):return self._neighbors(point,False)
