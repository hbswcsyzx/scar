"""Shared exec roots and protocol requests on the existing ProgramView.

Only retained small interface tables are read. Namespace alternatives, audit
hooks, builtin insertion, source versions and effects remain conditional.
The body is shared; its discarded data result never aliases exec's None.
"""
import argparse
from collections import Counter, defaultdict
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

from scar.analysis.program_view import ProgramView, _digest
from scar.analysis.source_call_view import source_call_site, prepare_source_ports, source_caller_scope, source_active_scope
from scar.analysis.source_context_query import ContextTargetGraph
from scar.analysis.source_declared_calls import _NoTargets, _check_targets, _owners
from scar.analysis.source_launch import read_script_entry
from scar.analysis.source_reference_slice import ReferenceSlicer, source_port
from scar.analysis.source_symbol_variants import _table
from scar.analysis.source_consumer_parents import _stamp
from scar.analysis.source_value_flow import _artifact
from scar.analysis.source_world_returns import _table_ref
from scar.analysis.source_template_links import _json
from scar.ir.program import source_exec_view as R, source_exec_roots as X, source_productions as P
from scar.ir.program import source_frame_bindings as B, normal_targets as T, normal_graph as G, model as M, view as V
from scar.ir.program.python_bindings import SourceCallSite
from scar.ir.program.ids import ValueID, ControlPortID, OperationID, ProviderID
from scar.ir.program.providers import ProviderFactReference
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.program.dependencies import (
    DependencyPoint as Point, DependencyFrame as Frame, DependencyEdge as Edge,
    DependencyKind as K, DependencyMeaning as Meaning, DependencyStrength as Strength,
    DependencyCondition as Condition, DependencyEvidence as Evidence,
    DependencyFrontier as Frontier, DependencyNeighborhood as Neighborhood,
    context_push, context_pop, context_is_closed)
from scar.ir.record_codec import encode, decode


SCHEMA = 'scar.source-exec-view'


class SourceExecMaterials:
    """Receipt-bound original exec candidates; historical dispatch is not replayed."""
    def __init__(self, catalog):
        self.catalog = catalog if isinstance(catalog, ContextTargetGraph) else ContextTargetGraph(catalog)
        self.path = self.catalog.path; self.report = self.catalog.report; self._reports = {}; self._tables = {}
        self.parent = _artifact(self.path/'result.json', self.report['schema'])
        for root, report in ((self.path,self.report), (self.catalog.namespace_graph.path,self.catalog.namespace_graph.report),
                (self.catalog.namespace_graph.exec_graph.path,self.catalog.namespace_graph.exec_graph.report),
                *self.catalog.namespace_graph.exec_graph.parents.values()):
            raw=(root/'result.json').read_bytes()
            if json.loads(raw)!=report:raise ValueError('exec original parent report changed')
            self._reports[root/'result.json']=raw
        def rows(name, kind):
            receipt=self.report[name];path=self.path/receipt['path'];before=_stamp(path)
            result=tuple(decode(kind,w,record_tags=P.PRODUCTION_RECORD_TAGS) for w in _table(self.path,receipt))
            if _stamp(path)!=before:raise ValueError('exec interface table changed during reading')
            self._tables[path]=before;return result
        self.connections=rows('exec_connections',X.ExecRootConnection)
        if self.connections!=tuple(self.catalog.namespace_graph.exec_graph.connections()):
            raise ValueError('catalog exec candidates differ from their exact exec-root parent')
        self.globals=rows('frame_globals_bindings',B.FrameGlobalsBinding)
        self.roots=rows('root_namespace_bindings',B.RootNamespaceBinding)
        self.slicer=ReferenceSlicer(SimpleNamespace(fact_store=self.catalog.fact_store));self.calls={}
        for i,c in enumerate(self.connections):
            if c.root.owner.unit not in self.catalog.fact_store.original_source_units:
                raise ValueError('exec body is not an original compiled-context root')
            facts=self.catalog.fact_store.load(c.site.result.unit)
            matches=[(j,call) for j,call in enumerate(facts.calls) if source_port(facts,call.result)==c.site.result]
            if len(matches)!=1:raise ValueError('exec call lacks one original source call fact')
            j,call=matches[0]
            expected=SourceCallSite(source_port(facts,call.callee),tuple(source_port(facts,p) for p in call.positional),
                tuple((name,source_port(facts,p)) for name,p in call.keywords),source_port(facts,call.result),
                source_port(facts,call.world),source_port(facts,call.result_world),
                None if call.positional_pack is None else source_port(facts,call.positional_pack),
                None if call.keyword_pack is None else source_port(facts,call.keyword_pack))
            if (c.site!=expected or c.owner not in _owners(facts)[j] or c.code_use is None
                    or c.code_use.exec_result!=c.site.result or c.profile!='NORMAL_SUCCESS'
                    or c.normal_result.to_python() is not None
                    or self.catalog.fact_store.load(c.root.owner.unit).root_scope!=c.root):
                raise ValueError('exec original call/root/code-use/normal result ABI differs')
            self.calls[i]=self.slicer.fact(facts,'calls',j)
        ids={c.id:c for c in self.connections}
        for binding in self.globals:
            c=ids[binding.connection]
            formal=T.GlobalPort(c.root.owner.unit,G.Port(c.root.template,c.root.region,G.PortKind.PARAMETER,0))
            if (binding.caller!=c.owner or binding.protocol_reference!=c.globals.value or binding.target!=formal
                    or binding.read_world!=c.site.world or c.globals.kind is not X.ExecNamespaceKind.CALLER_GLOBALS):
                raise ValueError('frame globals binding differs from its original exec branch')
            self.slicer.local(binding.source)
            if binding.function is not None:
                f=binding.function;unit,local=self.slicer.local(f.source_callable)
                fns=[fn for fn in unit.functions if fn.value==local]
                if (len(fns)!=1 or f.body!=fns[0].body_scope or f.body.owner!=binding.caller
                        or f.environment_formal!=source_port(unit,fns[0].formals[0])
                        or f.capture.function!=f.source_callable or f.capture.body!=f.body
                        or f.capture.globals!=binding.source):raise ValueError('frame globals function/capture ABI differs')
        entry_path=Path(self.report['script_entry']['path'])
        self.entry=read_script_entry(entry_path,self.catalog.fact_store.base)
        eraw=(entry_path/'result.json').read_bytes();self._reports[entry_path/'result.json']=eraw
        receipt=json.loads(eraw)['entry'];self._reports[entry_path/receipt['path']]=(entry_path/receipt['path']).read_bytes()
        self.check()

    def fact(self, table, ordinal):
        return _table_ref(self.path,self.report[table],'scar.source-'+table.replace('_','-'),ordinal)

    def check(self):
        if any(path.read_bytes()!=raw for path,raw in self._reports.items()) or json.loads(self._reports[self.path/'result.json'])!=self.catalog.report:
            raise ValueError('exec original report bytes changed')
        if any(_stamp(path)!=stamp for path,stamp in self._tables.items()):raise ValueError('exec interface table changed')
        self.catalog.fact_store.validate_parents();self.catalog.interface_store.validate_parents()


class SourceExecProvider:
    """Retained protocol actions and branch-matched shared root interfaces."""
    relation_kinds=frozenset((K.CONTROL_FLOW,K.ARGUMENT,K.COMPLETION,K.STATE_INTERFACE,K.CALL_TARGET,
        K.OPERAND,K.RESULT,K.STATE_INPUT,K.STATE_OUTPUT,K.ENVIRONMENT,K.PROJECTION,K.CONTAINS))

    def __init__(self, view, catalog_or_materials):
        self.view=view
        self.materials=catalog_or_materials if isinstance(catalog_or_materials,SourceExecMaterials) else SourceExecMaterials(catalog_or_materials)
        self.catalog=self.materials.catalog
        if view.catalog is None or (view.catalog.path,view.catalog.report)!=(self.catalog.path,self.catalog.report):
            raise ValueError('exec view and original catalog differ')
        self.records={};self.owners={};self.children=defaultdict(list);self.out_edges=defaultdict(list);self.in_edges=defaultdict(list)
        self.relations=[];self.frames={};self.operations={};self.pending=defaultdict(set);self.interfaces=[]
        artifact=self.materials.parent
        self.locator=SourceArtifactLocator(artifact,artifact.sha256,artifact.size_bytes,'canonical-json')
        self._prepare()
        # Metadata admission must be available before exposing protocol edges.
        view.register(self)
        for i,c in enumerate(self.materials.connections):self._attach(i,c)
        self._entry();self.materials.check()

    @staticmethod
    def _key(point):return point.namespace,point.node

    def _prepare(self):
        ports=[];bodies=[]
        def endpoint(p):
            if type(p) is T.GlobalPort:ports.append(p)
            elif type(p) is X.ExecProtocolValue:ports.append(p.site)
            else:raise TypeError('exec interface needs its original typed endpoint')
        for c in self.materials.connections:
            bodies.append(T.Body(c.root.owner.unit,c.root.template,c.root.region))
            ports.extend((c.site.callee,c.site.result,c.site.world,c.site.result_world,*c.site.positional,
                *(v for _,v in c.site.keywords),*(p for p in (c.site.positional_pack,c.site.keyword_pack) if p is not None)))
            for e in c.edges:endpoint(e.source);endpoint(e.target)
            for a in c.actions:
                for p in (a.world_in,a.world_out,a.control_in,a.control_out,*a.inputs,*a.outputs):endpoint(p)
            for p in (*c.predicates,*c.globals.conditions,*c.locals.conditions):
                if p.source is not None:ports.append(p.source)
        for b in self.materials.globals:
            ports.extend((b.source,b.target,b.read_world))
            if b.function is not None:ports.append(b.function.environment_formal)
        entry=self.materials.entry;root=entry.root
        bodies.append(T.Body(root.owner.unit,root.template,root.region))
        ports.extend(T.GlobalPort(root.owner.unit,G.Port(root.template,root.region,G.PortKind.PARAMETER,i)) for i in range(3))
        prepare_source_ports(self.view,ports,bodies=bodies)

    def _remember(self, namespace, record, owner):
        point=Point(namespace,record.id,None);key=self._key(point)
        if self.records.setdefault(key,record)!=record or self.owners.setdefault(key,owner)!=owner:
            raise ValueError('exec auxiliary identity collision')
        if record.id not in self.children[self._key(owner)]:self.children[self._key(owner)].append(record.id)
        return point

    def endpoint(self, endpoint):
        if type(endpoint) is T.GlobalPort:return self.view.source_port(endpoint)
        if type(endpoint) is not X.ExecProtocolValue:raise TypeError('exec endpoint is not an original typed interface')
        i=self.by_id[endpoint.branch];c=self.materials.connections[i]
        if endpoint.site!=c.site.result or endpoint.owner!=c.owner:raise ValueError('exec protocol endpoint changed branch/site/owner')
        return self.protocol_points[endpoint]

    def _relation(self, source, target, i, rule, ordinal, kind, meaning, *, transition=G.Transition.DIRECT,
            flow=None, guards=(), predicates=()):
        c=self.materials.connections[i]
        row=R.ExecRelation(source,target,i,rule,ordinal,kind,meaning,transition,flow,
            tuple(dict.fromkeys((*c.conditions,*guards))),tuple(dict.fromkeys((
                *c.predicates,*c.globals.conditions,*c.locals.conditions,*predicates))))
        self.relations.append(row);self.out_edges[self._key(source)].append(row);self.in_edges[self._key(target)].append(row)

    def _attach(self,i,c):
        if not hasattr(self,'by_id'):self.by_id={v.id:j for j,v in enumerate(self.materials.connections)};self.protocol_points={}
        operation,use,callee=source_call_site(self.view,c.site);self.operations[i]=operation
        body=self.view.source_region(c.root.owner.unit,c.root.template,c.root.region)
        frame=Frame(operation.namespace,operation.node,use.node,callee.node,body.namespace,
            entry=body.node,selection=self.materials.fact('exec_connections',i))
        self.frames[i]=frame;self.interfaces.append(R.ExecBodyInterface(i,frame.selection,frame))
        source=self.view.namespaces[operation.namespace];roles={}
        def role(endpoint,kind):
            if type(endpoint) is T.GlobalPort:return
            if type(endpoint) is not X.ExecProtocolValue:raise TypeError('exec action has an untyped endpoint')
            if endpoint in roles and roles[endpoint] is not kind:raise ValueError('exec protocol state/data/control roles conflict')
            roles[endpoint]=kind
        for a in c.actions:
            role(a.world_in,R.ExecValueKind.STATE);role(a.world_out,R.ExecValueKind.STATE)
            role(a.control_in,R.ExecValueKind.CONTROL);role(a.control_out,R.ExecValueKind.CONTROL)
            for p in (*a.inputs,*a.outputs):role(p,R.ExecValueKind.REFERENCE)
        for e in c.edges:
            kind=(R.ExecValueKind.STATE if e.kind is G.EdgeKind.STATE else
                R.ExecValueKind.CONTROL if e.kind is G.EdgeKind.CONTROL else R.ExecValueKind.REFERENCE)
            role(e.source,kind);role(e.target,kind)
        for p,kind in roles.items():
            identity=(ControlPortID if kind is R.ExecValueKind.CONTROL else ValueID)(_digest(('scar.exec-protocol-value.v1',source.basis,p)))
            type_=(None if kind is R.ExecValueKind.CONTROL else source.graph.profile.world
                if kind is R.ExecValueKind.STATE else M.ValueType(M.ValueKind.REFERENCE))
            self.protocol_points[p]=self._remember(source.namespace,R.ExecInterfaceValue(identity,p,kind,type_),operation)
        self._relation(operation,body,i,'EXEC_BODY_TARGET',0,K.CALL_TARGET,Meaning.DEPENDENCE,flow=R.ExecFlow.ENTER)
        for j,e in enumerate(c.edges):
            a,b=self.endpoint(e.source),self.endpoint(e.target);flow=None
            if a.namespace!=b.namespace:
                flow=R.ExecFlow.ENTER if (a.namespace,b.namespace)==(frame.caller,frame.target) else R.ExecFlow.RETURN
                expected=G.Transition.CALL if flow is R.ExecFlow.ENTER else G.Transition.RETURN
                if e.transition is not expected:raise ValueError('exec cross-root edge transition differs')
            kind,meaning={G.EdgeKind.DATA:(K.ARGUMENT,Meaning.REFERENCE),
                G.EdgeKind.STATE:(K.STATE_INTERFACE,Meaning.STATE_INTERFACE),
                G.EdgeKind.CONTROL:(K.CONTROL_FLOW,Meaning.ORDER)}[e.kind]
            if flow is R.ExecFlow.RETURN and e.kind is G.EdgeKind.DATA:kind,meaning=K.COMPLETION,Meaning.DEPENDENCE
            self._relation(a,b,i,'ORIGINAL_EXEC_EDGE',j,kind,meaning,transition=e.transition,flow=flow,predicates=e.conditions)
        for j,a in enumerate(c.actions):
            identity=OperationID(_digest(('scar.exec-protocol-action.v1',source.basis,frame.selection,j)))
            op=self._remember(source.namespace,R.ExecActionOperation(identity,frame.selection,j,a),operation)
            guards=('STANDARD_EXEC_PROTOCOL_PHASE_COMPLETES_NORMALLY',a.phase.value)
            self._relation(self.endpoint(a.world_in),op,i,'ACTION_WORLD_INPUT',j,K.STATE_INPUT,Meaning.STATE_INTERFACE,guards=guards,predicates=a.conditions)
            self._relation(self.endpoint(a.control_in),op,i,'ACTION_CONTROL_INPUT',j,K.CONTROL_FLOW,Meaning.ORDER,guards=guards,predicates=a.conditions)
            for p in a.inputs:self._relation(self.endpoint(p),op,i,'ACTION_OPERAND',j,K.OPERAND,Meaning.DEPENDENCE,guards=guards,predicates=a.conditions)
            # BODY outputs come only from original matched root-return edges.
            # Connecting its operation directly to these outputs would bypass
            # the selected shared body in control/world dependency queries.
            if a.phase is not X.ExecPhase.BODY:
                self._relation(op,self.endpoint(a.world_out),i,'ACTION_WORLD_OUTPUT',j,K.STATE_OUTPUT,Meaning.STATE_INTERFACE,guards=guards,predicates=a.conditions)
                self._relation(op,self.endpoint(a.control_out),i,'ACTION_CONTROL_OUTPUT',j,K.CONTROL_FLOW,Meaning.ORDER,guards=guards,predicates=a.conditions)
                for p in a.outputs:self._relation(op,self.endpoint(p),i,'ACTION_RESULT',j,K.RESULT,Meaning.DEPENDENCE,guards=guards,predicates=a.conditions)
            self.pending[self._key(op)].add('EXEC_PROTOCOL_EFFECTS_EXTERNAL_HOOKS_AND_NAMESPACE_MUTATION_OPEN')
        normal=self._remember(source.namespace,R.ExecNormalResult(ValueID(_digest((
            'scar.exec-normal-result.v1',source.basis,frame.selection))),frame.selection,c.normal_result),operation)
        self._relation(normal,self.endpoint(c.site.result),i,'EXEC_NORMAL_NONE_RESULT',0,K.RESULT,Meaning.DEPENDENCE,
            guards=('STANDARD_EXEC_NORMAL_SUCCESS_RETURNS_NONE','BODY_DATA_RETURN_IS_DISCARDED'))
        for j,b in enumerate(self.materials.globals):
            if b.connection!=c.id:continue
            value=self._remember(source.namespace,R.ExecFrameGlobalsValue(ValueID(_digest((
                'scar.exec-frame-globals.v1',source.basis,frame.selection,j))),frame.selection,
                self.materials.fact('frame_globals_bindings',j),b),operation)
            current=b.source if b.function is None else b.function.environment_formal
            self._relation(self.endpoint(current),value,i,'CURRENT_FRAME_GLOBALS_ENVIRONMENT',j,K.ENVIRONMENT,Meaning.DEPENDENCE,guards=b.conditions)
            self._relation(self.endpoint(b.read_world),value,i,'CURRENT_FRAME_GLOBALS_WORLD',j,K.PROJECTION,Meaning.STATE_INTERFACE,guards=b.conditions)
            self._relation(value,self.endpoint(b.protocol_reference),i,'CURRENT_FRAME_GLOBALS_HANDLE',j,K.ENVIRONMENT,Meaning.DEPENDENCE,guards=b.conditions)
            self.pending[self._key(value)].add('FUNCTION_CREATION_INSTANCE_AND_FRAME_GLOBALS_VERSION_NOT_SELECTED')
        for point in (operation,body,self.endpoint(c.site.result)):
            self.pending[self._key(point)].update(('EXEC_NAMESPACE_BRANCH_AND_CURRENT_CODE_VERSION_NOT_SELECTED',
                'EXEC_EXCEPTIONAL_COMPLETIONS_NOT_CONNECTED',*c.obligations))

    def _entry(self):
        contract=self.materials.entry;matches=[b for b in self.materials.roots if b.root==contract.root]
        if len(matches)!=1:raise ValueError('declared script entry lacks one original root namespace binding')
        binding=matches[0];source=self.view.unit(contract.source.unit);root=self.view.entry(source.unit)
        if binding.entry_contract_sha256!=sha256(_json(encode(contract,record_tags=P.PRODUCTION_RECORD_TAGS))).hexdigest():
            raise ValueError('entry namespace binding changed its original contract')
        self._remember(source.namespace,R.ExecEntryDeclaration(ProviderID(_digest((
            'scar.exec-entry-declaration.v1',source.basis,binding.entry_contract_sha256))),contract,binding),root)
        for point in (root,self.endpoint(binding.globals),self.endpoint(binding.locals)):
            self.pending[self._key(point)].add('DECLARED_SCRIPT_ENTRY_AND_INITIAL_NAMESPACE_VERSIONS_NOT_RUNTIME_ACTIVATION')
        world=T.GlobalPort(source.unit,G.Port(contract.root.template,contract.root.region,G.PortKind.PARAMETER,2))
        self.pending[self._key(self.endpoint(world))].add('SCRIPT_ENTRY_WORLD_IS_EXTERNAL_UNSELECTED_INPUT')

    def describe(self,point):
        record=self.records.get(self._key(point))
        if record is None:return None
        self.view.namespaces[point.namespace].check(point);owner=replace(self.owners[self._key(point)],context=point.context)
        if type(record) is R.ExecActionOperation:kind,role,type_=V.ProgramEntityKind.OPERATION,V.ProgramNodeRole.OPERATION,None
        elif type(record) is R.ExecEntryDeclaration:kind,role,type_=None,V.ProgramNodeRole.PROVIDER,None
        elif type(record) is R.ExecInterfaceValue and record.kind is R.ExecValueKind.CONTROL:
            kind,role,type_=None,V.ProgramNodeRole.CORE_CONTROL_PORT,None
        else:kind,role,type_=V.ProgramEntityKind.VALUE,V.ProgramNodeRole.CORE_VALUE,(
            record.value_type if type(record) is R.ExecInterfaceValue else M.ValueType(M.ValueKind.REFERENCE))
        return V.ProgramNode(point,kind,role,owner,type_)

    def original(self,point):
        if self.describe(point) is None:raise ValueError('unadmitted exec metadata endpoint')
        return self.records[self._key(point)]

    def expand(self,point):
        self.original(point)
        return tuple(Point(point.namespace,n,point.context) for n in self.children.get(self._key(point),()))

    def explain(self,point):
        return dict(node=self.describe(point),original=self.original(point),runtime_activation_proven=False,
            namespace_identity_proven=False,current_contents_proven=False,effects_closed=False)

    def _neighbors(self,point,incoming):
        rows=(self.in_edges if incoming else self.out_edges).get(self._key(point),())
        owned=((point.node,) if self._key(point) in self.records else ()) if incoming else self.children.get(self._key(point),())
        reasons=set(self.pending.get(self._key(point),()));edges=[];needs_frame=False;matched=False
        if not rows and not owned and not reasons:return Neighborhood()
        self.materials.check();self.view.get(point)
        for identity in owned:
            child=Point(point.namespace,identity,point.context);owner=replace(self.owners[self._key(child)],context=point.context)
            edges.append(Edge(owner,child,K.CONTAINS,Meaning.STRUCTURE,(Evidence('scar.source-exec.owns-interface.v1',(self.locator,),(owner,child)),)))
        for row in rows:
            frame=self.frames[row.connection];caller_context=point.context
            if row.flow is None:
                contexts=(point.context,point.context)
            else:
                pop=(incoming and row.flow is R.ExecFlow.ENTER) or (not incoming and row.flow is R.ExecFlow.RETURN)
                if pop:
                    needs_frame=True;popped=context_pop(point.context,(frame,))
                    if not popped.matched:continue
                    matched=True;caller_context=popped.remaining;callee_context=point.context
                else:callee_context=context_push(caller_context,frame)
                contexts=(caller_context,callee_context) if row.flow is R.ExecFlow.ENTER else (callee_context,caller_context)
            scope=source_caller_scope(self.view,frame,caller_context)
            if scope is not None and scope!=self.materials.connections[row.connection].owner:
                reasons.add('SOURCE_CALLER_CODE_SCOPE_DOES_NOT_OWN_EXEC_CALLSITE');continue
            source,target=replace(row.source,context=contexts[0]),replace(row.target,context=contexts[1])
            call=replace(self.operations[row.connection],context=caller_context)
            conditions=tuple(Condition('scar.source-exec.precondition',g,call,row.connection) for g in row.guards)
            conditions+=tuple(Condition('scar.source-exec.predicate',p.rule,call,row.connection,
                () if p.source is None else (replace(self.endpoint(p.source),context=caller_context),)) for p in row.predicates)
            conditions+=(Condition('scar.source-exec.original-transition',row.transition.value,call,row.ordinal),)
            edges.append(Edge(source,target,row.kind,row.meaning,(Evidence('scar.source-exec.'+row.rule.lower()+'.v1',
                (replace(self.locator,pointer='#/exec_connections'),frame.target.graph),(call,source,target)),),conditions,Strength.MAY))
        if needs_frame and not matched:reasons.add('EXEC_BODY_CALLER_BRANCH_FRAME_NOT_SELECTED')
        if edges and not context_is_closed(point.context):reasons.add('SOURCE_CALL_CONTEXT_PREFIX_OPEN')
        return Neighborhood(tuple(dict.fromkeys(edges)),tuple(Frontier(point,r,
            'Conditional exec protocol; original namespaces, versions, audit hooks and normal-success branches remain unselected.') for r in sorted(reasons)))

    def incoming(self,point):return self._neighbors(point,True)
    def outgoing(self,point):return self._neighbors(point,False)

    def summary(self):
        return dict(connections=len(self.frames),actions=sum(type(r) is R.ExecActionOperation for r in self.records.values()),
            records=len(self.records),relations=len(self.relations),original_edges=sum(r.rule=='ORIGINAL_EXEC_EDGE' for r in self.relations),
            kinds=dict(Counter(r.kind.value for r in self.relations)),shared_roots=len({f.target for f in self.frames.values()}),
            canonical_body_bytes_copied=0,runtime_dispatch_proven=False,namespace_versions_proven=False,
            effects_closed=False,loops_unrolled=False,target_executed=False,first_stage_complete=False)


def _pins():
    from scar.analysis import program_view,source_call_view,source_context_query,source_exec_query,source_namespace_graph,source_launch
    from scar.ir.program import dependencies
    return dict(producer=sha256(Path(__file__).read_bytes()).hexdigest(),**{
        name:sha256(Path(module.__file__).read_bytes()).hexdigest() for name,module in (
            ('types',R),('view',program_view),('helpers',source_call_view),('context_reader',source_context_query),
            ('exec_reader',source_exec_query),('namespace_reader',source_namespace_graph),('launch',source_launch),
            ('context_types',dependencies),('exec_types',X),('frame_types',B))})


def publish_exec_view(provider,out):
    from scar.analysis.normal_output import write_table
    from scar.analysis.source_stage import _durable_bytes,_durable_mkdir
    provider.materials.check();out=Path(out).absolute()
    if out.exists():raise ValueError('fresh exec view output required')
    _durable_mkdir(out);rows=tuple(provider.records.values());tables={}
    for name,kind in (('values',R.ExecInterfaceValue),('actions',R.ExecActionOperation),
            ('normal_results',R.ExecNormalResult),('frame_globals',R.ExecFrameGlobalsValue),('entries',R.ExecEntryDeclaration)):
        tables[name]=write_table(out/(name+'.jsonl.gz'),(r for r in rows if type(r) is kind))
    tables['interfaces']=write_table(out/'interfaces.jsonl.gz',provider.interfaces)
    tables['relations']=write_table(out/'relations.jsonl.gz',provider.relations)
    report=dict(schema=SCHEMA,schema_version=1,catalog=str(provider.catalog.path),parent=encode(provider.materials.parent),
        pins=_pins(),tables=tables,summary=provider.summary(),source_interfaces_rechecked=True,
        historical_namespace_solver_replayed=False,runtime_dispatch_proven=False,target_executed=False,first_stage_complete=False)
    provider.materials.check();_durable_bytes(out/'result.json',_json(report),replace=False);return report


def read_exec_view(path,*,view=None):
    """Reproject the small interface tables; original F4 bodies stay shared."""
    path=Path(path).absolute();raw=(path/'result.json').read_bytes();report=json.loads(raw)
    if (report['schema'],report['schema_version'])!=(SCHEMA,1) or report['pins']!=_pins():
        raise ValueError('exec view schema or producer differs')
    view=ProgramView(report['catalog']) if view is None else view
    provider=SourceExecProvider(view,view.catalog)
    if (str(view.catalog.path)!=report['catalog'] or encode(provider.materials.parent)!=report['parent']
            or report['summary']!=provider.summary() or report['source_interfaces_rechecked'] is not True
            or any(report[n] is not False for n in ('historical_namespace_solver_replayed',
                'runtime_dispatch_proven','target_executed','first_stage_complete'))):
        raise ValueError('exec view original catalog, counts or proof status differs')
    kinds=dict(values=R.ExecInterfaceValue,actions=R.ExecActionOperation,normal_results=R.ExecNormalResult,
        frame_globals=R.ExecFrameGlobalsValue,entries=R.ExecEntryDeclaration,
        interfaces=R.ExecBodyInterface,relations=R.ExecRelation)
    if set(report['tables'])!=set(kinds):raise ValueError('exec view tables differ')
    records=tuple(provider.records.values())
    for name,kind in kinds.items():
        receipt=report['tables'][name]
        if receipt['path']!=name+'.jsonl.gz':raise ValueError('exec view table path differs')
        rows=tuple(decode(kind,w,record_tags=P.PRODUCTION_RECORD_TAGS) for w in _table(path,receipt))
        expected=(tuple(provider.interfaces) if name=='interfaces' else tuple(provider.relations)
            if name=='relations' else tuple(r for r in records if type(r) is kind))
        if rows!=expected:raise ValueError('exec view differs from original interface projection: '+name)
    if raw!=(path/'result.json').read_bytes():raise ValueError('exec view report changed during reading')
    provider.materials.check();return report,provider


def main():
    import sys
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--catalog');parser.add_argument('--out');parser.add_argument('--read')
    args=parser.parse_args();sys.meta_path.insert(0,_NoTargets());_check_targets()
    if args.read:
        report,provider=read_exec_view(args.read);_check_targets();print(json.dumps(provider.summary()),flush=True);return
    if not args.catalog:parser.error('--catalog is required')
    view=ProgramView(args.catalog);provider=SourceExecProvider(view,view.catalog)
    report=publish_exec_view(provider,args.out) if args.out else provider.summary()
    _check_targets();print(json.dumps(report),flush=True)


if __name__=='__main__':main()
