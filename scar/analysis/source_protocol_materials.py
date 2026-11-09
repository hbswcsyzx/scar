"""Narrow material/ABI reader for original constructor and member candidates.

Historical namespace, class/MRO and descriptor target choices are retained
provenance. No global solver or recursive ancestor derivation is run here.
"""
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

from scar.analysis.source_context_query import ContextTargetGraph
from scar.analysis.source_reference_slice import ReferenceSlicer, source_port
from scar.analysis.source_constructor_interfaces import _site, _stage, _source_entry, _SOURCE, _PENDING
from scar.analysis.source_symbol_variants import _table
from scar.analysis.source_world_returns import _table_ref
from scar.analysis.source_consumer_parents import _stamp
from scar.ir.program import source_constructor_interfaces as C, declared_contexts as D
from scar.ir.program import source_productions as P, normal_targets as T
from scar.ir.program.providers import ProviderArtifact
from scar.ir.program.source_value_flow import SourceBodyCall
from scar.ir.record_codec import decode, encode


class SourceProtocolMaterials:
    def __init__(self,path,catalog,*,members=None):
        from scar.analysis import source_call_context_graph as calls
        self.path=Path(path).absolute()
        self.catalog=catalog if isinstance(catalog,ContextTargetGraph) else ContextTargetGraph(catalog)
        self._reports={};self._tables={};self._rules=[]
        self.report=self._report(self.path,schema='scar.source-call-context-graph',pins=calls._pins)
        if self.report['schema_version']!=1:raise ValueError('unsupported constructor context material version')
        self._false(self.report,('runtime_dispatch_proven','content_versions_proven','target_executed','first_stage_complete'))
        if self.report['all_historical_candidates_retained'] is not True:raise ValueError('constructor candidate coverage differs')
        # Follow only exact report receipts. These are report paths, never
        # source-fact URIs; logical facts are validated by ReferenceSlicer.
        report=self.report
        for key,schema in (('body_expansion','scar.source-body-expansion'),
                ('interfaces','scar.source-value-interfaces'),('values','scar.source-value-flow'),
                ('consumers','scar.reference-consumer-graph'),('returns','scar.world-return-graph'),
                ('world','scar.source-world-flow'),('join','scar.declared-state-connections')):
            report=self._report(report[key],report['parent'],schema)
        report=self._report(report['contexts'],report['parents']['contexts'],'scar.declared-context-graph')
        fields=self._report(report['parent'],report['parent_ref'],'scar.source-field-interface-graph')
        actual=self._report(self.catalog.path,fields['catalog_parent'],self.catalog.report['schema'])
        if Path(fields['catalog']).absolute()!=self.catalog.path or actual!=self.catalog.report:
            raise ValueError('protocol source catalog differs from exact ancestor receipt')
        rows={name:self._rows(self.path,self.report,'constructor_'+name,kind) for name,kind in (
            ('sites',C.ConstructorInterfaceSite),('steps',C.ConstructorInterfaceStep),
            ('entries',C.ConstructorBodyEntry),('frontiers',C.ConstructorInterfaceFrontier))}
        self.graph=C.ConstructorInterfaceGraph(**rows)
        slicer=ReferenceSlicer(SimpleNamespace(fact_store=self.catalog.fact_store))
        sites=[_site(slicer,s.unit,s.record) for s in self.graph.sites]
        entries=[];frontiers=[]
        for i,step in enumerate(self.graph.steps):
            self._index(step.site,len(sites),'constructor site');unit,call=sites[step.site]
            result,world=_stage(slicer,unit,call,step.link)
            if step.link.stage in _PENDING:
                frontiers.append(C.ConstructorInterfaceFrontier(i,step.link.stage.value+'_UNRESOLVED'))
            elif step.link.stage in _SOURCE:
                reason=_source_entry(slicer,unit,call,step.link,result,world)
                if reason is None:entries.append(C.ConstructorBodyEntry(i,step.link.connection))
                else:frontiers.append(C.ConstructorInterfaceFrontier(i,reason))
        if (tuple(entries)!=self.graph.entries or tuple(frontiers)!=self.graph.frontiers
                or any(len(rows[n])!=self.report['counts']['constructor_'+n] for n in rows)):
            raise ValueError('constructor source entries/frontiers or original material counts differ')
        self.members=None;self.member_root=self.member_path=None;self.member_report=None;self._member_calls=[]
        if members is not None:self._members(members,slicer)
        self.original_materials_checked=True;self.source_interfaces_rederived=True
        self.namespace_semantics_rederived=False;self.runtime_dispatch=False
        self.source_interface_validation_scope='ORIGINAL_SITE_STAGE_FUNCTION_ENVIRONMENT_FORMALS_PACKS_AND_RETURNS_ABI'
        self.check()

    @staticmethod
    def _index(i,size,label):
        if type(i) is not int or not 0<=i<size:raise ValueError(label+' index lies outside original table')

    @staticmethod
    def _false(report,names):
        if any(report[n] is not False for n in names):raise ValueError('protocol materials cannot grant runtime authority')

    def _report(self,root,reference=None,schema=None,pins=None):
        path=Path(root).absolute()/'result.json';raw=path.read_bytes();report=json.loads(raw)
        artifact=ProviderArtifact(str(path),sha256(raw).hexdigest(),len(raw),report['schema'])
        if (schema is not None and report['schema']!=schema) or (reference is not None and encode(artifact)!=reference):
            raise ValueError('protocol ancestor report URI/schema/byte receipt differs')
        if pins is not None:
            expected=pins()
            if report['pins']!=expected:raise ValueError('protocol original producer differs')
            self._rules.append((pins,expected))
        if path in self._reports and self._reports[path][0]!=raw:raise ValueError('protocol ancestor changed')
        self._reports[path]=(raw,report)
        return report

    def _rows(self,root,report,name,kind):
        receipt=report['tables'][name];relative=Path(receipt['path'])
        if relative.is_absolute() or '..' in relative.parts:raise ValueError('protocol table leaves its original report')
        path=Path(root)/relative;before=_stamp(path)
        result=tuple(decode(kind,row,record_tags=P.PRODUCTION_RECORD_TAGS) for row in _table(Path(root),receipt))
        if before!=_stamp(path):raise ValueError('protocol table changed while decoding')
        self._tables[path]=before;return result

    def _members(self,path,slicer):
        from scar.analysis import source_constructor_members as producer
        self.member_root=self.member_path=Path(path).absolute()
        raw,_=self._reports[self.path/'result.json']
        expected=encode(ProviderArtifact(str(self.path/'result.json'),sha256(raw).hexdigest(),len(raw),self.report['schema']))
        report=self.member_report=self._report(self.member_root,schema='scar.constructor-member-contexts',pins=producer._pins)
        if report['schema_version']!=1 or Path(report['calls']).absolute()!=self.path or report['parent']!=expected:
            raise ValueError('member graph uses another constructor context parent')
        self._false(report,('loops_unrolled','runtime_class_proven','mro_proven','runtime_dispatch_proven','target_executed','first_stage_complete'))
        rows={n:self._rows(self.member_root,report,n,t) for n,t in (
            ('contexts',D.DeclaredContext),('entries',D.DeclaredContextEntry),
            ('edges',D.DeclaredContextEdge),('frontiers',D.ContextFrontier))}
        graph=D.DeclaredContextGraph(**rows)
        for context in graph.contexts:self._function(slicer,context.source_callable,context.body)
        for entry in graph.entries:
            self._index(entry.target,len(graph.contexts),'member entry target')
            prefix='#/records/';tail=entry.parent.locator.removeprefix(prefix)
            if not entry.parent.locator.startswith(prefix) or not tail.isdecimal() or str(int(tail))!=tail:
                raise ValueError('member root lacks original constructor-entry ordinal')
            i=int(tail);self._index(i,len(self.graph.entries),'member constructor entry')
            if entry.parent!=_table_ref(self.path,self.report['tables']['constructor_entries'],'scar.constructor-body-entries',i) or entry.connection!=self.graph.entries[i].connection:
                raise ValueError('member entry changed its original constructor connection')
            target=graph.contexts[entry.target]
            if (target.source_callable,target.body)!=(entry.connection.source_callable,entry.connection.body):raise ValueError('member entry context differs')
        for edge in graph.edges:
            self._index(edge.caller,len(graph.contexts),'member caller');self._index(edge.target,len(graph.contexts),'member target')
            caller=graph.contexts[edge.caller];target=graph.contexts[edge.target];connection=edge.connection
            unit=slicer.unit(caller.body.unit)[0];prefix=slicer.fact(unit,'calls',0).locator.rsplit('/',1)[0]+'/'
            tail=edge.call.locator.removeprefix(prefix)
            if not edge.call.locator.startswith(prefix) or not tail.isdecimal() or str(int(tail))!=tail:raise ValueError('member original call ordinal differs')
            i=int(tail);self._index(i,len(unit.calls),'member source call');call=unit.calls[i]
            if edge.call!=slicer.fact(unit,'calls',i) or (target.source_callable,target.body)!=(connection.source_callable,connection.body):raise ValueError('member original call/target differs')
            self._member_calls.append((unit.unit,SourceBodyCall(edge.call,call)))
            provider,fn=self._function(slicer,connection.source_callable,connection.body)
            formals=tuple(source_port(provider,p) for p in fn.formals)
            activation=T.FunctionActivation.NORMAL if fn.environment.kind is P.DeferredBodyKind.FUNCTION else T.FunctionActivation.CREATE_DEFERRED_BODY
            env=[r for r in connection.parameters if r.kind is T.RouteKind.FUNCTION_ENVIRONMENT]
            state=[r for r in connection.parameters if r.kind is T.RouteKind.STATE]
            if (connection.activation is not activation or len(env)!=1 or env[0].formal!=formals[0]
                    or env[0].actuals!=(source_port(unit,call.callee),) or len(state)!=1
                    or state[0].formal!=formals[-1] or state[0].actuals!=(source_port(unit,call.world),)):
                raise ValueError('member environment/state/activation ABI differs')
            for route in connection.parameters:
                if route not in (*env,*state) and route.formal not in formals[1:-1]:raise ValueError('member parameter formal differs')
                for actual in route.actuals:
                    if type(actual) is not T.GlobalPort:raise ValueError('member operand needs a constructor protocol endpoint')
                    slicer.local(actual)
            returns=()
            if activation is T.FunctionActivation.NORMAL:
                if fn.returns is not None:returns=((source_port(provider,fn.returns),source_port(unit,call.result)),)
                if fn.return_world is not None:returns+=((source_port(provider,fn.return_world),source_port(unit,call.result_world)),)
            if connection.returns!=returns:raise ValueError('member normal return ABI differs')
        for frontier in graph.frontiers:self._index(frontier.context,len(graph.contexts),'member frontier')
        if any(len(rows[n])!=report['counts'][n] for n in rows):raise ValueError('member material counts differ')
        self.members=graph

    @staticmethod
    def _function(slicer,point,body):
        unit,local=slicer.local(point);matches=[f for f in unit.functions if f.value==local]
        if len(matches)!=1 or body!=T.Body(unit.unit,matches[0].template,matches[0].body):raise ValueError('protocol source function/body differs')
        return unit,matches[0]

    def step_fact(self,i):
        self.check();self._index(i,len(self.graph.steps),'constructor step')
        return _table_ref(self.path,self.report['tables']['constructor_steps'],'scar.constructor-interface-steps',i)

    def member_fact(self,i):
        self.check()
        if self.members is None:raise ValueError('no original member graph was supplied')
        self._index(i,len(self.members.edges),'member edge')
        return _table_ref(self.member_root,self.member_report['tables']['edges'],'scar.constructor-member-edges',i)

    def member_call(self,i):
        self.check();self._index(i,len(self._member_calls),'member edge')
        return self._member_calls[i]

    def check(self):
        if any(path.read_bytes()!=raw or json.loads(raw)!=report for path,(raw,report) in self._reports.items()):raise ValueError('protocol ancestor report changed')
        if any(_stamp(path)!=stamp for path,stamp in self._tables.items()) or any(pins()!=expected for pins,expected in self._rules):raise ValueError('protocol table or producer changed')
        self.catalog.fact_store.validate_parents();self.catalog.interface_store.validate_parents()
