"""Attach immutable input algebra to a guarded source content boundary.

This is a declarative layer. Its expression operations are not runtime
invocations. The receiver's post-call content, Python None result, whole world
and future task configuration remain separate.
"""
import argparse
from collections import defaultdict,Counter
from dataclasses import replace
from hashlib import sha256
from itertools import zip_longest
import json
from pathlib import Path
from types import SimpleNamespace

from scar.analysis.program_view import ProgramView,_digest
from scar.analysis.source_configuration_state_binding import read_configuration_state_bindings
from scar.analysis.source_configuration_value_store import read_configuration_values
from scar.analysis.source_call_view import prepare_source_ports,source_call_site,source_active_scope
from scar.analysis.source_reference_slice import source_port
from scar.analysis.source_world_returns import _table_ref
from scar.analysis.source_value_flow import _artifact
from scar.ir.program import source_configuration_view as R,source_content as C,model as M,view as V
from scar.ir.program.dependencies import (
    DependencyPoint as Point,DependencyEdge as Edge,DependencyKind as K,DependencyMeaning as Meaning,
    DependencyStrength as Strength,DependencyCondition as Condition,DependencyEvidence as Evidence,
    DependencyFrontier as Frontier,DependencyNeighborhood as Neighborhood)
from scar.ir.program.ids import OperationID,ValueID,RegionID,LocationID
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.record_codec import encode,decode


class SourceConfigurationProvider:
    """One shared view of input declarations and original boundary state."""
    relation_kinds=frozenset((K.CONTAINS,K.ARGUMENT,K.RESULT,K.PROJECTION,K.ENVIRONMENT,K.STATE_LOCATION))

    def __init__(self,view,boundaries):
        self.view=view;self.path=Path(boundaries).absolute()
        self.report,self.bindings=read_configuration_state_bindings(self.path)
        self.values_path=Path(self.report['values']).absolute()
        self.value_report,self.values=read_configuration_values(self.values_path)
        self.reports={p:(p.read_bytes()) for p in (self.path/'result.json',self.values_path/'result.json')}
        self.records={};self.nodes={};self.sources={};self.in_edges=defaultdict(list);self.out_edges=defaultdict(list);self.scopes={}
        self.regions=[];self.expressions={};self.projections={};self.content_candidates=[]
        artifact=_artifact(self.values_path/'result.json',self.value_report['schema'])
        self.locator=SourceArtifactLocator(artifact,artifact.sha256,artifact.size_bytes,'canonical-json')
        for ordinal,binding in enumerate(self.bindings):self._attach(ordinal,binding,artifact)
        self.check();view.register(self)

    @staticmethod
    def _key(point):return point.namespace,point.node

    def _record(self,source,record,kind,role,owner,type_=None):
        point=Point(source.namespace,record.id,None);key=self._key(point)
        if self.records.setdefault(key,record)!=record:raise ValueError('configuration identity collision')
        self.nodes[key]=V.ProgramNode(point,kind,role,owner,type_);return point

    def _edge(self,source,target,kind,meaning,boundary,*,guarded=False):
        conditions=tuple(Condition('scar.configuration.input-contract',name,
            self.regions[-1],None,(source,target)) for name in (*self.values.conditions,*boundary.conditions)) if guarded else ()
        edge=Edge(source,target,kind,meaning,(Evidence('scar.configuration.declared-input-interface.v1',
            (self.locator,self.sources[source.namespace].locator),(source,target)),),conditions,
            Strength.MAY if guarded else Strength.EXACT)
        if edge not in self.out_edges[self._key(source)]:
            self.out_edges[self._key(source)].append(edge);self.in_edges[self._key(target)].append(edge)
        if guarded:self.scopes[edge]=boundary.caller.owner

    def _attach(self,ordinal,binding,artifact):
        if self.view.catalog is None or binding.receiver.unit not in self.view.catalog.fact_store.rows:
            raise ValueError('configuration boundary lacks its original source catalog unit')
        source=self.view.unit(binding.receiver.unit);self.sources[source.namespace]=source;facts=source.facts
        candidates=[c for c in facts.calls if source_port(facts,c.result)==binding.data_result]
        if len(candidates)!=1:raise ValueError('configuration boundary lacks one original call')
        call=candidates[0]
        if (source_port(facts,call.callee)!=binding.callee or source_port(facts,call.world)!=binding.world_before
                or source_port(facts,call.result_world)!=binding.world_after
                or binding.receiver not in tuple(source_port(facts,p) for p in call.positional)):
            raise ValueError('configuration boundary changed callee/receiver/world ABI')
        prepare_source_ports(self.view,(binding.receiver,binding.callee,binding.world_before,binding.world_after,binding.data_result))
        operation,_,_=source_call_site(self.view,SimpleNamespace(result=binding.data_result,callee=binding.callee))
        prefix=(source.basis,artifact,binding.call)
        identity=RegionID(_digest(('scar.configuration-declared-region.v1',prefix)))
        fact=_table_ref(self.path,self.report['bindings'],'scar.source-state-projections',ordinal)
        region=self._record(source,R.ConfigurationRegion(identity,artifact,fact),V.ProgramEntityKind.REGION,V.ProgramNodeRole.REGION,operation)
        self.regions.append(region);self._edge(operation,region,K.CONTAINS,Meaning.STRUCTURE,binding)
        expression_values={};projection_values={}
        for expression in self.values.expressions:
            op_id=OperationID(_digest(('scar.configuration-expression-op.v1',prefix,expression.ordinal)))
            op=self._record(source,R.ConfigurationExpressionOperation(op_id,expression),V.ProgramEntityKind.OPERATION,V.ProgramNodeRole.OPERATION,region)
            value_id=ValueID(_digest(('scar.configuration-expression-value.v1',prefix,expression.ordinal)))
            value=self._record(source,R.ConfigurationExpressionValue(value_id,expression.ordinal),V.ProgramEntityKind.VALUE,
                V.ProgramNodeRole.CORE_VALUE,region,M.ValueType(M.ValueKind.DATA,'configuration.tree'))
            expression_values[expression.ordinal]=value;self.expressions[ordinal,expression.ordinal]=value
            self._edge(region,op,K.CONTAINS,Meaning.STRUCTURE,binding);self._edge(region,value,K.CONTAINS,Meaning.STRUCTURE,binding)
            for previous in expression.inputs:self._edge(expression_values[previous],op,K.ARGUMENT,Meaning.DEPENDENCE,binding)
            self._edge(op,value,K.RESULT,Meaning.DEPENDENCE,binding)
        for projection in self.values.projections:
            value_id=ValueID(_digest(('scar.configuration-projection-value.v1',prefix,projection.ordinal)))
            value=self._record(source,R.ConfigurationProjectionValue(value_id,projection),V.ProgramEntityKind.VALUE,
                V.ProgramNodeRole.CORE_VALUE,region,M.ValueType(M.ValueKind.DATA,'configuration.literal' if projection.literal is not None else 'configuration.tree'))
            projection_values[projection.ordinal]=value;self.projections[ordinal,projection.ordinal]=value
            self._edge(region,value,K.CONTAINS,Meaning.STRUCTURE,binding)
            self._edge(expression_values[projection.root],value,K.PROJECTION,Meaning.DEPENDENCE,binding)
        for projection in self.values.projections:
            for previous in projection.dependencies:self._edge(projection_values[previous],projection_values[projection.ordinal],K.PROJECTION,Meaning.DEPENDENCE,binding)
        for interpolation in self.values.interpolations:
            identity=OperationID(_digest(('scar.configuration-interpolation-op.v1',prefix,interpolation.ordinal)))
            op=self._record(source,R.ConfigurationInterpolationOperation(identity,interpolation),V.ProgramEntityKind.OPERATION,V.ProgramNodeRole.OPERATION,region)
            self._edge(region,op,K.CONTAINS,Meaning.STRUCTURE,binding)
            projection=self.values.projections[interpolation.projection]
            self._edge(expression_values[projection.root],op,K.ARGUMENT,Meaning.DEPENDENCE,binding)
            for previous in interpolation.dependencies:self._edge(projection_values[previous],op,K.ARGUMENT,Meaning.DEPENDENCE,binding)
            self._edge(op,projection_values[projection.ordinal],K.RESULT,Meaning.DEPENDENCE,binding)
        for index,root in enumerate(self.values.roots):
            identity=ValueID(_digest(('scar.configuration-declared-version.v1',prefix,index)))
            value=self._record(source,R.ConfigurationDeclaredVersion(identity,root),V.ProgramEntityKind.VALUE,V.ProgramNodeRole.CORE_VALUE,
                region,M.ValueType(M.ValueKind.DATA,'configuration.declared-root-version'))
            self._edge(region,value,K.CONTAINS,Meaning.STRUCTURE,binding)
            self._edge(expression_values[root.expression],value,K.PROJECTION,Meaning.DEPENDENCE,binding)
        for demand in self.values.read_demands:
            identity=OperationID(_digest(('scar.configuration-read-operation.v1',prefix,demand.ordinal)))
            op=self._record(source,R.ConfigurationReadOperation(identity,demand),V.ProgramEntityKind.OPERATION,V.ProgramNodeRole.OPERATION,region)
            self._edge(region,op,K.CONTAINS,Meaning.STRUCTURE,binding)
            if demand.projection is not None:self._edge(projection_values[demand.projection],op,K.ARGUMENT,Meaning.DEPENDENCE,binding)
        # Reuse the canonical whole-owner address/state formulas from the
        # source content adapter; no physical cfg slot or new identity family.
        address_id=LocationID(_digest(('scar.source-content-address.v1',source.basis,binding.receiver,C.WholeOwner())))
        address=C.ContentAddressTemplate(address_id,binding.receiver,C.WholeOwner(),
            (C.ContentInstanceParameter.ACTIVATION,C.ContentInstanceParameter.OWNER_REFERENCE_OCCURRENCE))
        location=self._record(source,address,V.ProgramEntityKind.STATE_LOCATION,V.ProgramNodeRole.STATE_LOCATION,operation)
        state_id=ValueID(_digest(('scar.source-content-state.v1',source.basis,address_id,binding.world_after)))
        state=self._record(source,C.ContentStateProjection(state_id,address_id,binding.world_after),V.ProgramEntityKind.VALUE,
            V.ProgramNodeRole.CORE_VALUE,operation,M.ValueType(M.ValueKind.STATE,location=address_id))
        self._edge(operation,location,K.CONTAINS,Meaning.STRUCTURE,binding);self._edge(operation,state,K.CONTAINS,Meaning.STRUCTURE,binding)
        self._edge(self.view.source_port(binding.receiver),location,K.ENVIRONMENT,Meaning.STATE_INTERFACE,binding,guarded=True)
        self._edge(location,state,K.STATE_LOCATION,Meaning.STRUCTURE,binding)
        self._edge(self.view.source_port(binding.world_after),state,K.PROJECTION,Meaning.STATE_INTERFACE,binding,guarded=True)
        declared=expression_values[binding.value_expression]
        self._edge(declared,state,K.PROJECTION,Meaning.DEPENDENCE,binding,guarded=True)
        self.content_candidates.append((ordinal,binding,declared,location,state))

    def check(self,point=None):
        if any(path.read_bytes()!=raw for path,raw in self.reports.items()):raise ValueError('configuration source reports changed')
        for source in self.sources.values():source.check(point if point is not None and point.namespace==source.namespace else None)

    def describe(self,point):
        node=self.nodes.get(self._key(point))
        if node is None:return None
        self.check(point);return replace(node,point=point,owner=None if node.owner is None else replace(node.owner,context=point.context))

    def original(self,point):
        if self.describe(point) is None:raise ValueError('configuration point is not admitted')
        return self.records[self._key(point)]

    def expand(self,point):
        self.original(point)
        return tuple(replace(n.point,context=point.context) for n in self.nodes.values() if n.owner is not None and self._key(n.owner)==self._key(point))

    def explain(self,point):
        return dict(node=self.describe(point),original=self.original(point),layer='DECLARED_CONFIGURATION_ALGEBRA',
            values=self.values.conditions,obligations=self.values.obligations,current_task_fields_proven=False,
            input_versions_at_call_proven=False,physical_identity_proven=False,runtime_operations_observed=False)

    def _neighbors(self,point,incoming):
        rows=(self.in_edges if incoming else self.out_edges).get(self._key(point),())
        if not rows:return Neighborhood()
        self.check(point);self.view.get(point);edges=[]
        for edge in rows:
            if edge in self.scopes:
                active=source_active_scope(self.view,point.namespace,point.context)
                if active is not None and active!=self.scopes[edge]:continue
            edges.append(replace(edge,source=replace(edge.source,context=point.context),target=replace(edge.target,context=point.context),
                conditions=tuple(replace(c,subject=None if c.subject is None else replace(c.subject,context=point.context),
                    operands=tuple(replace(p,context=point.context) for p in c.operands)) for c in edge.conditions)))
        return Neighborhood(tuple(edges),(Frontier(point,'CONFIGURATION_DECLARATION_NOT_CURRENT_TASK_CONTENT',
            'Input algebra is declared; current cfg identity, input versions, protocol selection and later mutation remain guarded.'),))

    def summary(self):
        return dict(boundaries=len(self.bindings),records=len(self.records),relations=sum(map(len,self.out_edges.values())),
            types=dict(Counter(type(r).__name__ for r in self.records.values())),
            current_task_fields_proven=False,runtime_operations_observed=False,target_executed=False,first_stage_complete=False)

    def incoming(self,point):return self._neighbors(point,True)
    def outgoing(self,point):return self._neighbors(point,False)


def _rows(provider):
    kinds=dict(regions=R.ConfigurationRegion,expressions=R.ConfigurationExpressionOperation,
        values=R.ConfigurationExpressionValue,projections=R.ConfigurationProjectionValue,
        interpolations=R.ConfigurationInterpolationOperation,versions=R.ConfigurationDeclaredVersion,
        reads=R.ConfigurationReadOperation,addresses=C.ContentAddressTemplate,states=C.ContentStateProjection)
    rows=tuple(provider.records.values())
    result={name:(kind,tuple(r for r in rows if type(r) is kind)) for name,kind in kinds.items()}
    result['edges']=(Edge,tuple(e for edges in provider.out_edges.values() for e in edges))
    return result


def publish_configuration_view(provider,out):
    from scar.analysis.normal_output import write_table
    from scar.analysis.source_stage import _durable_mkdir,_durable_bytes
    from scar.analysis.source_template_links import _json
    out=Path(out).absolute()
    if out.exists():raise ValueError('fresh configuration-view output required')
    provider.check();_durable_mkdir(out)
    tables={name:write_table(out/(name+'.jsonl.gz'),rows) for name,(_,rows) in _rows(provider).items()}
    report=dict(schema='scar.source-configuration-view',schema_version=1,catalog=str(provider.view.catalog.path),
        boundaries=str(provider.path),parents={str(path):sha256(raw).hexdigest() for path,raw in provider.reports.items()},
        namespaces=[encode(source.namespace) for source in provider.sources.values()],tables=tables,summary=provider.summary(),
        producer_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),types_sha256=sha256(Path(R.__file__).read_bytes()).hexdigest(),
        target_executed=False,first_stage_complete=False)
    provider.check();_durable_bytes(out/'result.json',_json(report),replace=False);return report


def read_configuration_view(path):
    from scar.analysis.source_symbol_variants import _table
    from scar.ir.program import source_productions as P
    path=Path(path).absolute();raw=(path/'result.json').read_bytes();report=json.loads(raw)
    if ((report['schema'],report['schema_version'])!=('scar.source-configuration-view',1)
            or report['producer_sha256']!=sha256(Path(__file__).read_bytes()).hexdigest()
            or report['types_sha256']!=sha256(Path(R.__file__).read_bytes()).hexdigest()
            or report['target_executed'] is not False or report['first_stage_complete'] is not False):
        raise ValueError('configuration-view producer or authority differs')
    provider=SourceConfigurationProvider(ProgramView(report['catalog']),report['boundaries'])
    if (report['parents']!={str(path):sha256(raw).hexdigest() for path,raw in provider.reports.items()}
            or report['namespaces']!=[encode(s.namespace) for s in provider.sources.values()]
            or report['summary']!=provider.summary() or set(report['tables'])!=set(_rows(provider))):
        raise ValueError('configuration-view source or complete interface coverage differs')
    sentinel=object()
    for name,(kind,expected) in _rows(provider).items():
        receipt=report['tables'][name]
        if receipt['path']!=name+'.jsonl.gz':raise ValueError('configuration-view table path differs')
        actual=(decode(kind,row,record_tags=P.PRODUCTION_RECORD_TAGS) for row in _table(path,receipt))
        if any(a!=b for a,b in zip_longest(actual,expected,fillvalue=sentinel)):
            raise ValueError('configuration-view typed rederivation differs: '+name)
    provider.check()
    if (path/'result.json').read_bytes()!=raw:raise ValueError('configuration-view report changed')
    return report,provider


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog');parser.add_argument('--boundaries');parser.add_argument('--out');parser.add_argument('--read')
    args=parser.parse_args()
    if args.read:
        if args.catalog or args.boundaries or args.out:parser.error('--read stands alone')
        _,provider=read_configuration_view(args.read);report=provider.summary()
    else:
        if not args.catalog or not args.boundaries:parser.error('--catalog and --boundaries required')
        provider=SourceConfigurationProvider(ProgramView(args.catalog),args.boundaries)
        report=publish_configuration_view(provider,args.out) if args.out else provider.summary()
    print(json.dumps(report),flush=True)


if __name__=='__main__':main()
