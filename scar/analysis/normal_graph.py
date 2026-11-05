"""Build normal-success control/data/state edges over shared source templates.

This is an edge index over the existing source IR, not a second instruction
language. Runtime Python CALL targets are resolved by the following layer.
"""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
import gzip
from hashlib import sha256
import json
import multiprocessing
from pathlib import Path
import time

from scar.analysis.source_compilation_flow import _at, _item, references
from scar.analysis.source_productions import _digest, read_production_plan
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir, _sync_directory
from scar.analysis.source_template_links import read_template_graph, _worker_stores, _stream, _json, _read_graph_table
from scar.ir.program import normal_graph as G
from scar.ir.program import source_productions as P
from scar.ir.program.source_template_links import SourceTemplateKey
from scar.ir.program.control import LanguageCompletionKind as C
from scar.ir.program.model import ValueType, ValueKind
from scar.ir.record_codec import encode


class _Emitter:
    def __init__(self, plan, key, interfaces):
        self.plan, self.key, self.interfaces = plan, key, interfaces
        self.regions = {r.id:r for r in plan.regions}; self.steps = {s.id:s for s in plan.steps}
        self.out = []; self.step = None
        # Iterator exhaustion is normal loop control, even though CPython
        # delivers StopIteration through an exceptional protocol port.
        self.exhaustion = {s.instruction.condition.advance.region for s in plan.steps
            if type(s.instruction) is P.LoopControl and type(s.instruction.condition) is P.IterationCondition}

    def port(self, owner, kind, i=0, completion=None, path=(), template=None):
        return G.Port(self.key if template is None else template, owner, kind, i,
            None if completion is None else completion.kind,
            None if completion is None else completion.target, path)

    def value(self, value):
        if type(value) is P.ProductionParameter:
            return self.port(value.region,G.PortKind.PARAMETER,value.index),self.regions[value.region].parameters[value.index]
        row=self.steps[value.step];completion=next(c for c in row.completions if c.kind is C.FALLTHROUGH)
        return self.port(value.step,G.PortKind.RESULT,value.index,completion),completion.types[value.index]

    def data(self, source, target, kind, *, site=None, transition=G.Transition.DIRECT):
        if source == target:return
        state=type(kind) is ValueType and kind.kind is ValueKind.STATE
        self.out.append(G.Edge(source,target,G.EdgeKind.STATE if state else G.EdgeKind.DATA,kind,site,transition))

    def control(self, source, target, *, site=None, transition=G.Transition.DIRECT, guard=None, declare=False):
        condition,when=(None,None) if guard is None else guard
        self.out.append(G.Edge(source,target,G.EdgeKind.DECLARE if declare else G.EdgeKind.CONTROL,
            site=site,transition=transition,condition=condition,when=when))

    def allowed(self, completion, region=None):
        return completion.kind is not C.RAISE or region in self.exhaustion

    def invoke(self, region, inputs, path, *, template=None, guard=None, include_raise=False, resume=False):
        key=self.key if template is None else template
        target=self.regions[region] if key==self.key else self.interfaces['nodes'][key]
        params=target.parameters;completions=target.completions
        site=G.CallSite(self.key,self.step.id,path)
        if inputs is not None:
            if tuple(t for _,t in inputs)!=params:raise ValueError('region input types differ: '+str(region))
            for i,((source,kind),_) in enumerate(zip(inputs,params)):
                arg=self.port(self.step.id,G.PortKind.ARGUMENT,i,path=path)
                self.data(source,arg,kind)
                self.data(arg,self.port(region,G.PortKind.PARAMETER,i,template=key),kind,site=site,transition=G.Transition.CALL)
        self.control(self.port(self.step.id,G.PortKind.ENTER),self.port(region,G.PortKind.ENTER,template=key),
            site=site,transition=G.Transition.RESUME if resume else G.Transition.CALL,guard=guard)
        outputs={}
        for c in completions:
            if c.kind is C.RAISE and not include_raise:continue
            returned=self.port(self.step.id,G.PortKind.CALL_RETURN,completion=c,path=path)
            self.control(self.port(region,G.PortKind.EXIT,completion=c,template=key),returned,site=site,transition=G.Transition.RETURN)
            values=[]
            for i,kind in enumerate(c.types):
                result=self.port(self.step.id,G.PortKind.CALL_RESULT,i,c,path)
                self.data(self.port(region,G.PortKind.RESULT,i,c,template=key),result,kind,site=site,transition=G.Transition.RETURN)
                values.append((result,kind))
            outputs[(c.kind,c.target)]=(c,returned,tuple(values))
        return outputs

    def forward(self, output, *, completion=None, guard=None):
        original,returned,values=output; c=original if completion is None else completion
        self.control(returned,self.port(self.step.id,G.PortKind.EXIT,completion=c),guard=guard)
        for i,(source,kind) in enumerate(values):self.data(source,self.port(self.step.id,G.PortKind.RESULT,i,c),kind)

    def calls(self, instruction):
        if type(instruction) is P.EvaluateChild:
            link=self.interfaces['links'][(self.key,self.step.id)];callee=self.interfaces['nodes'][link.callee]
            args=tuple((self.port(self.step.id,G.PortKind.ARGUMENT,i),self.value(v)[1]) for i,v in enumerate(self.step.arguments))
            for output in self.invoke(callee.root,args,(),template=link.callee).values():self.forward(output)
        elif type(instruction) in (P.ApplyRegion,P.InvokeTypeParameterFactory):
            call=instruction.invocation;path=_at(instruction,'invocation')+_at(call,'region')
            for output in self.invoke(call.region,tuple(self.value(v) for v in call.arguments),path,
                    include_raise=self.step.region in self.exhaustion).values():self.forward(output)
        elif type(instruction) is P.BranchControl:
            condition=self.port(self.step.id,G.PortKind.ARGUMENT)
            for name,choice in (('on_true',True),('on_false',False)):
                call=getattr(instruction,name);path=_at(instruction,name)+_at(call,'region')
                for output in self.invoke(call.region,tuple(self.value(v) for v in call.arguments),path,guard=(condition,choice)).values():self.forward(output)
        elif type(instruction) is P.HandleCompletions:
            call=instruction.protected;path=_at(instruction,'protected')+_at(call,'region')
            outputs=self.invoke(call.region,tuple(self.value(v) for v in call.arguments),path)
            routes={(r.kind,r.target):(i,r) for i,r in enumerate(instruction.routes) if r.kind is not C.RAISE}
            for key,output in outputs.items():
                if key not in routes:self.forward(output);continue
                index,route=routes[key];route_path=_at(instruction,'routes')+(_item(index),)+_at(route,'handler')
                # Handler admission follows completion delivery, rather than
                # eagerly executing alongside its protected region.
                start=len(self.out)
                handlers=self.invoke(route.handler,(*output[2],*(self.value(v) for v in route.captures)),route_path)
                for n in range(start,len(self.out)):
                    e=self.out[n]
                    if e.kind is G.EdgeKind.CONTROL and e.transition is G.Transition.CALL:
                        self.out[n]=replace(e,source=output[1])
                for result in handlers.values():self.forward(result)

    def loop(self, instruction):
        loop=self.regions[self.step.region];inputs=tuple(self.value(v) for v in self.step.arguments)
        inv=instruction.invariant_count;targets={loop.id,instruction.source_loop}
        normal=next((c for c in self.step.completions if c.kind is C.FALLTHROUGH),None)
        def leave(output,values):
            if normal is None:return
            self.forward((normal,output[1],values),completion=normal)
        def body_outputs(outputs):
            for (kind,target),output in outputs.items():
                if kind is C.FALLTHROUGH or kind is C.CONTINUE and target in targets:
                    self.control(output[1],self.port(self.step.id,G.PortKind.ENTER),transition=G.Transition.BACKEDGE)
                    for i,(src,typ) in enumerate(output[2],inv):
                        self.data(src,self.port(loop.id,G.PortKind.PARAMETER,i),typ,transition=G.Transition.BACKEDGE)
                elif kind is C.BREAK and target in targets:leave(output,output[2])
                else:self.forward(output)
        def otherwise(output,carried,guard=None):
            if instruction.otherwise is None:
                if normal is not None:self.forward((normal,output[1],carried),completion=normal,guard=guard)
                return
            before=len(self.out)
            results=self.invoke(instruction.otherwise,(*inputs[:inv],*carried),_at(instruction,'otherwise'),guard=guard)
            for i in range(before,len(self.out)):
                e=self.out[i]
                if e.kind is G.EdgeKind.CONTROL and e.transition is G.Transition.CALL:self.out[i]=replace(e,source=output[1])
            for item in results.values():self.forward(item)
        if type(instruction.condition) is P.RepeatCondition:
            body_outputs(self.invoke(instruction.body,inputs,_at(instruction,'body')));return
        if type(instruction.condition) is P.IterationCondition:
            iteration=instruction.condition;call=iteration.advance
            path=_at(instruction,'condition')+_at(iteration,'advance')+_at(call,'region')
            outputs=self.invoke(call.region,tuple(self.value(v) for v in call.arguments),path,include_raise=True)
            advanced=outputs[(C.FALLTHROUGH,None)];arguments=list(inputs)
            arguments[iteration.world_parameter]=advanced[2][-1]
            before=len(self.out)
            body=self.invoke(instruction.body,(*arguments,advanced[2][0]),_at(instruction,'body'))
            for i in range(before,len(self.out)):
                e=self.out[i]
                if e.kind is G.EdgeKind.CONTROL and e.transition is G.Transition.CALL:self.out[i]=replace(e,source=advanced[1])
            body_outputs(body)
            exhausted=outputs[(C.RAISE,None)]
            path=_at(instruction,'condition')+_at(iteration,'exhausted');before=len(self.out)
            match=self.invoke(iteration.exhausted,exhausted[2],path)
            for i in range(before,len(self.out)):
                e=self.out[i]
                if e.kind is G.EdgeKind.CONTROL and e.transition is G.Transition.CALL:self.out[i]=replace(e,source=exhausted[1])
            classified=match[(C.FALLTHROUGH,None)];arguments=list(inputs)
            arguments[iteration.world_parameter]=exhausted[2][-1]
            otherwise(classified,tuple(arguments[inv:]),guard=(classified[2][0][0],True));return
        path=_at(instruction,'condition');outputs=self.invoke(instruction.condition,inputs,path)
        tested=outputs[(C.FALLTHROUGH,None)];decision=tested[2][0][0];carried=tested[2][1:]
        before=len(self.out)
        body=self.invoke(instruction.body,(*inputs[:inv],*carried),_at(instruction,'body'),guard=(decision,True))
        for i in range(before,len(self.out)):
            e=self.out[i]
            if e.kind is G.EdgeKind.CONTROL and e.transition is G.Transition.CALL:self.out[i]=replace(e,source=tested[1])
        body_outputs(body);otherwise(tested,carried,guard=(decision,False))
        for key,output in outputs.items():
            if key!=(C.FALLTHROUGH,None):self.forward(output)

    def run(self):
        for region in self.plan.regions:
            self.control(self.port(region.id,G.PortKind.ENTER),self.port(region.steps[0],G.PortKind.ENTER))
            for index,identity in enumerate(region.steps):
                self.step=self.steps[identity];instruction=self.step.instruction
                for i,value in enumerate(self.step.arguments):
                    source,kind=self.value(value);self.data(source,self.port(identity,G.PortKind.ARGUMENT,i),kind)
                if type(instruction) in (P.EvaluateChild,P.ApplyRegion,P.InvokeTypeParameterFactory,P.BranchControl,P.HandleCompletions):self.calls(instruction)
                elif type(instruction) is P.LoopControl:self.loop(instruction)
                elif type(instruction) is P.SuspendExecution:
                    for i,route in enumerate(instruction.routes):
                        if route.kind is C.RAISE:continue
                        path=_at(instruction,'routes')+(_item(i),)+_at(route,'region')
                        outputs=self.invoke(route.region,None,path,resume=True)
                        payload=len(self.regions[route.region].parameters)-len(instruction.saved)
                        for j,value in enumerate(instruction.saved,payload):
                            source,kind=self.value(value);self.data(source,self.port(route.region,G.PortKind.PARAMETER,j),kind,site=G.CallSite(self.key,identity,path))
                        for output in outputs.values():self.forward(output)
                else:
                    for c in self.step.completions:
                        if not self.allowed(c,region.id):continue
                        self.control(self.port(identity,G.PortKind.ENTER),self.port(identity,G.PortKind.EXIT,completion=c))
                        if type(instruction) is P.TransferCompletion:
                            for i,kind in enumerate(c.types):self.data(self.port(identity,G.PortKind.ARGUMENT,i),self.port(identity,G.PortKind.RESULT,i,c),kind)
                for path,kind,target in references(instruction):
                    if kind is P.CompilationEdgeKind.CODE_DECLARATION:
                        self.control(self.port(identity,G.PortKind.ENTER),self.port(target,G.PortKind.ENTER),site=G.CallSite(self.key,identity,path),declare=True)
                for c in self.step.completions:
                    if not self.allowed(c,region.id):continue
                    if c.kind is C.FALLTHROUGH and index+1<len(region.steps):
                        self.control(self.port(identity,G.PortKind.EXIT,completion=c),self.port(region.steps[index+1],G.PortKind.ENTER))
                    else:
                        self.control(self.port(identity,G.PortKind.EXIT,completion=c),self.port(region.id,G.PortKind.EXIT,completion=c))
                        for i,kind in enumerate(c.types):self.data(self.port(identity,G.PortKind.RESULT,i,c),self.port(region.id,G.PortKind.RESULT,i,c),kind)
        return self.out


def normal_edges(plan, interfaces):
    key=SourceTemplateKey(plan.source.occurrence,plan.purpose)
    if interfaces['nodes'][key].origin.plan_sha256!=_digest(encode(plan,record_tags=P.PRODUCTION_RECORD_TAGS)):
        raise ValueError('normal graph input differs from the sealed template')
    return _Emitter(plan,key,interfaces).run()


def _unit(task):
    source,out,unit,max_visits,pins=task
    if _pins()!=pins:raise ValueError('normal graph implementation changed')
    graph=read_template_graph(source,unit);report=json.loads((Path(source)/'result.json').read_bytes())
    specifications=tuple((p['domain'],p['materials'],p['verification'],p['collection_sha256'],p['verification_sha256']) for p in report['parents'])
    stores=_worker_stores(specifications,report['model_manifest_sha256'])
    interfaces=dict(nodes={n.key:n for n in graph.templates},links={(e.caller,e.step):e for e in graph.links})
    origins={(n.origin.domain,n.origin.line):n for n in graph.templates};counts=Counter()
    def edges():
        for store in stores:
            basis=store.basis[unit]
            for domain,line,document in store.records(dict(key=unit,**{k:v for k,v in basis.items() if k!='unit'})):
                if (domain,line) not in origins:continue
                node=origins[(domain,line)]
                if _digest(document)!=node.origin.plan_sha256:raise ValueError('original template body differs')
                plan=read_production_plan(document,max_visits=max_visits)
                counts.update(templates=1,regions=len(plan.regions),operations=len(plan.steps))
                counts.update(loop_templates=sum(type(s.instruction) is P.LoopControl for s in plan.steps))
                for edge in _Emitter(plan,node.key,interfaces).run():
                    counts[edge.kind.value]+=1;yield edge
    path=Path(out)/'units'/unit;_durable_mkdir(path)
    fragment=_stream(path/'edges.jsonl.gz',edges())
    if counts['templates']!=len(graph.templates):raise ValueError('source templates omitted')
    header=dict(schema='scar.normal-program-graph-unit',schema_version=1,unit=unit,input=encode(graph.input),profile='NORMAL_SUCCESS',edges=fragment,counts=dict(counts))
    raw=_json(header);_durable_bytes(path/'header.json',raw,replace=False);_sync_directory(path)
    return dict(unit=unit,header='units/'+unit+'/header.json',header_sha256=sha256(raw).hexdigest(),header_bytes=len(raw),counts=dict(counts),compressed_bytes=fragment['bytes'])


def _pins():
    return {str(Path(m.__file__).name):sha256(Path(m.__file__).read_bytes()).hexdigest() for m in (G,)} | {
        'builder':sha256(Path(__file__).read_bytes()).hexdigest(),
        'source_reader':sha256(Path(read_template_graph.__code__.co_filename).read_bytes()).hexdigest()}


def build_normal_graph(source,out,sources=(),*,jobs=1,max_visits=20_000_000):
    started=time.monotonic();source=Path(source).absolute();out=Path(out).absolute()
    if out.exists() or out.resolve()!=out:raise ValueError('normal graph needs a fresh canonical output')
    raw=(source/'result.json').read_bytes();parent=json.loads(raw)
    wanted=set(sources);selected=[r for r in parent['units'] if not wanted or r['path'] in wanted]
    if not selected or wanted and {r['path'] for r in selected}!=wanted:raise ValueError('source selection differs')
    pins=_pins();_durable_mkdir(out)
    tasks=[(str(source),str(out),r['unit'],max_visits,pins) for r in selected]
    if jobs==1:rows=[_unit(t) for t in tasks]
    else:
        with ProcessPoolExecutor(max_workers=jobs,mp_context=multiprocessing.get_context('spawn')) as pool:rows=list(pool.map(_unit,tasks))
    if (source/'result.json').read_bytes()!=raw or _pins()!=pins:raise ValueError('source or builder changed')
    counts=Counter()
    for row in rows:counts.update(row['counts'])
    result=dict(schema='scar.normal-program-graph',schema_version=1,status='NORMAL_GRAPH_GENERATED',profile='NORMAL_SUCCESS',
        source_interfaces=str(source),source_result_sha256=sha256(raw).hexdigest(),implementation_sha256=pins,
        selected_sources=len(rows),units=rows,counts=dict(counts),compressed_bytes=sum(r['compressed_bytes'] for r in rows),
        seconds=time.monotonic()-started,jobs=jobs,application_error_paths='OUT_OF_SCOPE',
        native_call_targets_resolved=False,canonical_n1_generated=False,first_stage_complete=False,target_executed=False,transformation_authorized=False)
    _durable_bytes(out/'result.json',_json(result),replace=False);return result


def read_normal_edges(store,unit):
    """Read one source shard; original operation/region bodies stay shared."""
    store=Path(store).absolute();raw=(store/'result.json').read_bytes();report=json.loads(raw)
    if report['schema']!='scar.normal-program-graph' or report['profile']!='NORMAL_SUCCESS':raise ValueError('unsupported normal graph')
    if report['implementation_sha256']['normal_graph.py']!=sha256(Path(G.__file__).read_bytes()).hexdigest():raise ValueError('edge schema differs')
    if sha256((Path(report['source_interfaces'])/'result.json').read_bytes()).hexdigest()!=report['source_result_sha256']:raise ValueError('source interface version differs')
    rows=[u for u in report['units'] if u['unit']==unit]
    if len(rows)!=1:raise ValueError('source shard absent or ambiguous')
    row=rows[0];path=store/row['header'];header_bytes=path.read_bytes()
    if path.resolve()!=path or not path.is_relative_to(store) or len(header_bytes)!=row['header_bytes'] or sha256(header_bytes).hexdigest()!=row['header_sha256']:raise ValueError('source header receipt differs')
    header=json.loads(header_bytes)
    if header['unit']!=unit or header['profile']!='NORMAL_SUCCESS':raise ValueError('source profile differs')
    edges=_read_graph_table(path,header['edges'],G.Edge)
    if (store/'result.json').read_bytes()!=raw:raise ValueError('normal graph changed while reading')
    return edges


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--templates',required=True);p.add_argument('--out',required=True)
    p.add_argument('--source',action='append',default=[]);p.add_argument('--jobs',type=int,default=1)
    p.add_argument('--max-visits',type=int,default=20_000_000);a=p.parse_args()
    r=build_normal_graph(a.templates,a.out,a.source,jobs=a.jobs,max_visits=a.max_visits)
    print(json.dumps({k:r[k] for k in ('status','selected_sources','counts','compressed_bytes','seconds')},indent=2))


if __name__=='__main__':main()
