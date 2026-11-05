"""Deferred creation and conditional synchronous iterator driving.

The reference token is an analysis handle, not a runtime object/frame ID.
Creation saves reference routes; only an actual static advance interface
admits the body. Iterator order and the selected suspension remain conditions.
"""
from collections import defaultdict
from dataclasses import replace
from time import perf_counter

from scar.ir.literals import PythonLiteral
from scar.ir.program import normal_targets as T, source_productions as P, source_generators as D
from scar.ir.program.control import LanguageCompletionKind as C
from scar.ir.program.structured import PythonProtocolKind as K
from scar.analysis.source_suspension_interfaces import SuspensionInterfaceIndex


def tables(flow,out,*,prefix=''):
    """Separate interface records from driver edges; reference original bodies."""
    from scar.analysis.normal_output import write_table as _stream
    rows=(('deferred_creations',flow.creations),('iteration_interfaces',flow.iterations),
          ('deferred_bodies',flow.bodies),('generator_iterators',flow.getters),
          ('generator_advances',flow.advances),('deferred_driver_obligations',flow.obligations))
    return {prefix+name:_stream(out/(prefix+name.replace('_','-')+'.jsonl.gz'),records.values())
            for name,records in rows}


class SourceGeneratorFlow:
    def __init__(self, solver):
        self.s=solver;self.interfaces=None;self.keys={};self.states={}
        self.creations={};self.iterations={};self.bodies={};self.getters={};self.advances={};self.obligations={}
        self.driven=defaultdict(set);self.interface_cache={};self.revisions={};self.advance_revisions={}
        self.metrics=dict(creation_requests=0,creation_replays_skipped=0,advance_requests=0,
            advance_replays_skipped=0,interface_cache_hits=0,interface_seconds=0.0,body_interface_seconds=0.0)

    def index(self):
        if self.interfaces is None:
            if not hasattr(self.s,'store'):return None
            self.interfaces=SuspensionInterfaceIndex(self.s.store,jobs=self.s.analysis_jobs,
                summaries=self.s.interface_store)
        return self.interfaces

    def validate_parents(self):
        if self.interfaces is not None:self.interfaces.validate_parents()
        elif self.s.interface_store is not None:self.s.interface_store.validate_parents()

    def close(self):
        if self.interfaces is not None:self.interfaces.close()

    @property
    def stats(self):
        result=dict(self.metrics)
        if self.interfaces is not None:result['interfaces']=self.interfaces.stats
        return result

    def create(self,fid,invocation,receiver,class_receiver,connection):
        self.metrics['creation_requests']+=1
        unit,function=self.s.functions[fid]
        if function.body_scope is None:raise ValueError('deferred body has no original source scope')
        environment=next(r.actuals for r in connection.parameters if r.kind is T.RouteKind.FUNCTION_ENVIRONMENT)
        key=fid,invocation,receiver,class_receiver,environment
        if key not in self.keys:self.keys[key]=len(self.keys)
        identity=self.keys[key];gp=self.s.gp
        origin=D.DeferredOrigin(None if invocation.result is None else gp(invocation.result),gp(fid),
            None if receiver is None else gp(receiver),None if class_receiver is None else gp(class_receiver),gp(invocation.world),environment)
        record=D.DeferredCreation(origin,function.environment.kind,function.body_scope,connection,
            (*connection.conditions,'STATIC_DEFERRED_CREATION','CAPTURED_REFERENCES_NOT_CONTENT_SNAPSHOTS'))
        if self.creations.get(identity)==record:
            self.metrics['creation_replays_skipped']+=1
            return
        self.revisions[identity]=self.revisions.get(identity,0)+1
        self.states[identity]=(fid,invocation,receiver,class_receiver,record)
        self.creations[identity]=record
        if invocation.result is not None:self.s.add(invocation.result,('source_deferred',identity))
        # A closed argument shape may arrive after a driver was registered.
        for target in tuple(self.driven[identity]):self.advance(('source_deferred',identity),target)

    def obligation(self,origin,reason,site=None,iteration=None):
        key=origin,reason,site,iteration
        self.obligations[key]=D.DeferredDriverObligation(origin,iteration,reason,site)

    def interface(self,target):
        rows=self.s.containers.iteration_sites.get(target,())
        signature=tuple((unit.unit,item) for unit,item in rows)
        prior=self.interface_cache.get(target)
        if prior is not None and prior[0]==signature:
            self.metrics['interface_cache_hits']+=1
            return prior[1]
        index=self.index()
        if index is None:return ()
        result=[];started=perf_counter()
        for unit,item in rows:
            site=index.iteration(unit,item);self.iterations[site.witness]=site;result.append(site)
        result=tuple(result);self.interface_cache[target]=signature,result
        self.metrics['interface_seconds']+=perf_counter()-started
        return result

    def get_iterator(self,value,target):
        if value[0]!='source_deferred':return
        record=self.creations[value[1]]
        sites=self.interface(target)
        if not sites:
            self.obligation(record.origin,'ITERATOR_INTERFACE_PROVIDER_REQUIRED',self.s.gp(target));return
        for site in sites:
            if record.kind is not P.DeferredBodyKind.GENERATOR:
                self.obligation(record.origin,'SYNCHRONOUS_ITERATOR_FOR_NON_GENERATOR',site.value,site.witness);continue
            key=value[1],site.witness
            if key in self.getters:continue
            self.getters[key]=D.GeneratorIterator(record.origin,site.witness,site.value,
                ('STATIC_MAY_ITERATOR_SELECTION','STANDARD_GENERATOR_ITER_RETURNS_SELF','BODY_NOT_STARTED_BY_ITER'))

    def bind_frame(self,identity,body,site):
        fid,invocation,receiver,class_receiver,creation=self.states[identity]
        connection=creation.connection;point=self.s.endpoint_point
        parameters=[]
        for route in connection.parameters:
            if route.kind is T.RouteKind.STATE:
                parameters.append(replace(route,actuals=(site.world,)));continue
            parameters.append(route);formal=point(route.formal)
            if route.kind in (T.RouteKind.ARGUMENT,T.RouteKind.INITIAL_DEFAULT,T.RouteKind.CONDITIONAL_DEFAULT):
                for actual in route.actuals:self.s.edge(point(actual),formal)
            elif route.kind is T.RouteKind.CLASS_RECEIVER:
                if class_receiver is None:raise ValueError('deferred class receiver lost its class')
                self.s.add(formal,('class',class_receiver))
            elif route.kind in (T.RouteKind.PACK_POSITIONALS,T.RouteKind.PACK_KEYWORDS):
                open_rest=any(p.formal==route.formal and p.kind in (
                    T.ProjectionKind.POSITIONAL_TAIL,T.ProjectionKind.KEYWORD_REMAINDER) for p in connection.projections)
                origin=('SYMBOLIC_PACK_PREFIX' if open_rest else 'GENERATOR_CAPTURE',identity,formal)
                self.s.containers.bind_variadic(formal,route.kind,tuple(point(a) for a in route.actuals),route.keyword_names,origin)
        for projection in connection.projections:
            self.s.containers.project_argument(point(projection.formal),point(projection.pack),projection.kind,
                index=projection.index,name=projection.name,excluded_names=projection.excluded_names)
        if hasattr(self.s,'activate_generator'):
            self.s.activate_generator(fid,point(site.value),invocation.callee)
        return replace(connection,activation=T.FunctionActivation.RESUME_BODY,parameters=tuple(parameters),returns=(),
            conditions=(*connection.conditions,'STATIC_GENERATOR_ADVANCE','CURRENT_ADVANCE_WORLD_NOT_CREATION_WORLD',
                'BODY_ENTRY_ONLY_IF_GENERATOR_NOT_STARTED'))

    def advance(self,value,target):
        if value[0]!='source_deferred':return
        self.metrics['advance_requests']+=1
        identity=value[1];fid,invocation,receiver,class_receiver,creation=self.states[identity]
        self.driven[identity].add(target)
        sites=self.interface(target)
        if not sites:
            self.obligation(creation.origin,'ADVANCE_INTERFACE_PROVIDER_REQUIRED',self.s.gp(target));return
        if creation.kind is not P.DeferredBodyKind.GENERATOR:
            for site in sites:self.obligation(creation.origin,'NON_SYNCHRONOUS_DEFERRED_DRIVER_REQUIRED',site.value,site.witness)
            return
        unit,function=self.s.functions[fid];body=None
        point=self.s.original_point
        for site in sites:
            if site.protocol is K.GET_ITERATOR:continue
            key=identity,site.witness;revision=self.revisions[identity]
            if self.advance_revisions.get(key)==revision:
                self.metrics['advance_replays_skipped']+=1
                continue
            if body is None:
                started=perf_counter();body=self.index().body(unit,function)
                self.metrics['body_interface_seconds']+=perf_counter()-started
                self.bodies[body.source_callable]=body
            connection=self.bind_frame(identity,body,site);yielded=[]
            for suspended in body.suspensions:
                if suspended.kind is not P.SuspensionKind.YIELD:
                    self.obligation(creation.origin,suspended.kind.value+'_DRIVER_REQUIRED',site.value,site.witness);continue
                for resumed in suspended.resumes:
                    if resumed.kind is not C.FALLTHROUGH:continue
                    if resumed.sent is None:raise ValueError('normal generator resume lacks sent input')
                    # NEXT sends None. The suspend RESULT is the sent value,
                    # while its argument is what the iterator exports.
                    self.s.add(point(resumed.sent),('constant','NoneType',None))
                    self.s.edge(point(suspended.exported),point(site.value))
                    yielded.append(D.GeneratorYield(suspended.witness,suspended.exported,site.value,
                        suspended.world,site.result_world,resumed.sent,resumed.world,
                        PythonLiteral.from_python(None,exact=True),
                        ('FRAME_REACHES_THIS_YIELD','SENT_NONE_ONLY_IF_FRAME_SUSPENDED_AT_THIS_SITE',
                         'RESUME_RECEIVES_CURRENT_ADVANCE_WORLD')))
            for reason in body.obligations:self.obligation(creation.origin,reason.value,site.value,site.witness)
            terminal=next((c for c in body.completions if c.kind is C.RETURN),None)
            raised=next((c for c in site.completions if c.kind is C.RAISE),None)
            exhaustion=None
            if terminal is not None:
                payload=next((p for p in terminal.ports if p!=terminal.world),None)
                exception=None if raised is None else next((p for p in raised.ports if p!=raised.world),None)
                exhaustion=D.GeneratorExhaustion(payload,terminal.world,exception,None if raised is None else raised.world)
            self.advances[identity,site.witness]=D.GeneratorAdvance(creation.origin,site.witness,connection,
                tuple(yielded),exhaustion,('STATIC_MAY_ITERATOR_ADVANCE','GENERATOR_FRAME_AT_ADMISSIBLE_RESUME_POINT',
                    'RETURN_VALUE_IS_NOT_AN_ITERATOR_ITEM','ESCAPING_EXCEPTION_IS_NOT_NORMAL_EXHAUSTION'))
            self.advance_revisions[key]=revision

    def attribute(self,value,name,target):
        if value[0]!='source_deferred':return False
        self.obligation(self.creations[value[1]].origin,'DEFERRED_ATTRIBUTE_OR_METHOD_DRIVER_REQUIRED:'+name,self.s.gp(target))
        self.s.add(target,('external_member',target,name));return True
