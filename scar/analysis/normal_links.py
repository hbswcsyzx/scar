"""Sparse, static value/name/call constraints over the normal source graph.

Facts keep original port IDs. Value flow computes possible source targets;
neither a source target nor module lookup is an observed runtime dispatch.
"""
import argparse
from collections import Counter,defaultdict,deque
from concurrent.futures import ProcessPoolExecutor
import gzip
from hashlib import sha256
import json
import multiprocessing
from pathlib import Path
import time

from scar.analysis.normal_graph import _Emitter
from scar.analysis.source_productions import _digest
from scar.analysis.source_template_links import read_template_graph,_worker_stores,_json
from scar.analysis.source_stage import _durable_bytes,_durable_mkdir,_sync_directory
from scar.analysis.static_query import _Fragments
from scar.ir.program import normal_links as F
from scar.ir.program import normal_graph as G
from scar.ir.program import source_productions as P
from scar.ir.program.control import LanguageCompletionKind as C
from scar.ir.program.model import ValueType,ValueKind
from scar.ir.program.structured import PythonProtocolKind as K
from scar.ir.record_codec import encode,decode
from scar.ir.literals import PythonLiteral


def _module(path):
    """Infer a source package candidate without importing the target."""
    path=Path(path);parents=[]
    for parent in path.parents:
        if (parent/'__init__.py').is_file():parents.append(parent)
    base=parents[-1].parent if parents else path.parent
    parts=list(path.relative_to(base).with_suffix('').parts)
    if parts[-1]=='__init__':parts.pop()
    return '.'.join(parts)


class _Facts:
    def __init__(self,unit,syntax,bindings,declarations):
        self.unit=unit;self.syntax=syntax;self.bindings=bindings;self.declarations=declarations
        self.module=_module(unit['path'])
        self.fields={r['name']:{name:i for i,name in enumerate(r['fields'])} for r in syntax['profile']['ast_schema']}
        self.ports=[];self.ids={};self.aliases=set();self.names=[];self.functions=[];self.classes=[]
        self.attributes=[];self.imports=[];self.constants=[];self.calls=[]

    def point(self,port):
        if port not in self.ids:self.ids[port]=len(self.ports);self.ports.append(port)
        return self.ids[port]

    def scalar(self,site):
        value=self.syntax['nodes'][site.occurrence]['fields'][site.ordinal]
        for index in site.item_path:value=value['items'][index]
        return decode(PythonLiteral,value['scalar']).to_python()

    def field(self,occurrence,name):
        node=self.syntax['nodes'][occurrence]
        ordinal=self.fields[node['constructor']][name]
        return P.SlotRef(occurrence,'FIELD',ordinal)

    def namespace(self,index,name):
        interface=self.bindings['interfaces'][index];kind=interface['kind']
        if kind in ('LEXICAL_BINDING','CLASS_PROTOCOL_CELL'):
            return F.Namespace(F.NamespaceKind.LEXICAL,interface['binding'],name)
        if kind in ('CLASS_PREPARED_MAPPING','CLASS_ANNOTATION_NAMESPACE'):
            return F.Namespace(F.NamespaceKind.CLASS,interface['owner'],name)
        if kind=='BUILTINS':return F.Namespace(F.NamespaceKind.BUILTINS,0,name)
        return F.Namespace(F.NamespaceKind.MODULE,0,name)

    def name_access(self,ins,value):
        port=self.bindings['ports'][ins.port];ref=port['name']
        if ref is None:return
        name=self.declarations['names'][ref['index']]['value'] if ref['kind']=='SOURCE' else ref['symbol']
        if ins.action is P.BindingActionKind.WRITE and port['write_target'] is not None:
            self.names.append(F.NameAccess(self.namespace(port['write_target'],name),value,True))
        elif ins.action is P.BindingActionKind.READ and port['read_plan'] is not None:
            for step in self.bindings['plans'][port['read_plan']]['steps']:
                self.names.append(F.NameAccess(self.namespace(step['interface'],name),value,False))


class _Aliases(_Emitter):
    def __init__(self,plan,key,interfaces,facts):
        super().__init__(plan,key,interfaces);self.facts=facts

    def control(self,*args,**kwargs):pass

    def data(self,source,target,kind,**kwargs):
        if type(kind) is ValueType and kind.kind is ValueKind.REFERENCE and source!=target:
            self.facts.aliases.add((self.facts.point(source),self.facts.point(target)))

    def value_id(self,value):return self.facts.point(self.value(value)[0])

    def result_id(self,step,index=0):
        completion=next(c for c in step.completions if c.kind is C.FALLTHROUGH)
        return self.facts.point(self.port(step.id,G.PortKind.RESULT,index,completion))

    def describe(self):
        facts=self.facts;module=facts.module
        for step in self.plan.steps:
            self.step=step;ins=step.instruction
            normal=next((c for c in step.completions if c.kind is C.FALLTHROUGH),None)
            if type(ins) is P.AccessBinding:
                if ins.action is P.BindingActionKind.WRITE:facts.name_access(ins,self.value_id(step.arguments[0]))
                elif ins.action is P.BindingActionKind.READ:facts.name_access(ins,self.result_id(step))
            elif type(ins) is P.ImportRequest:
                name=ins.requested_name
                if ins.relative_level:
                    package=module if Path(facts.unit['path']).name=='__init__.py' else module.rpartition('.')[0]
                    prefix=package.split('.')[:len(package.split('.'))-ins.relative_level+1]
                    name='.'.join((*prefix,*(() if not name else name.split('.'))))
                if ins.from_names is None:name=name.split('.')[0]
                facts.imports.append(F.Import(self.result_id(step),name))
            elif type(ins) is P.ImportMember:
                facts.attributes.append(F.Attribute(self.value_id(step.arguments[0]),ins.member_name,self.result_id(step),False))
            elif type(ins) is P.ApplyLanguageAction:
                if ins.action in (P.LanguageActionKind.ATTRIBUTE_GET,P.LanguageActionKind.ATTRIBUTE_SET):
                    name=facts.scalar(ins.selectors[0]);write=ins.action is P.LanguageActionKind.ATTRIBUTE_SET
                    facts.attributes.append(F.Attribute(self.value_id(step.arguments[0]),name,
                        self.value_id(step.arguments[1]) if write else self.result_id(step),write))
                elif ins.action is P.LanguageActionKind.CALL:
                    owner=ins.selectors[0].occurrence;constructor=facts.syntax['nodes'][owner]['constructor']
                    args_slot,kw_slot=ins.selectors
                    arg_values=facts.syntax['nodes'][owner]['fields'][args_slot.ordinal]['items']
                    kw_values=facts.syntax['nodes'][owner]['fields'][kw_slot.ordinal]['items']
                    if constructor=='ClassDef':
                        declared=next((s.instruction for s in self.plan.steps if type(s.instruction) is P.DeferClassBody),None)
                        if declared is not None:
                            hidden=3+int(bool(facts.syntax['nodes'][owner]['fields'][facts.field(owner,'type_params').ordinal]['items']))
                            bases=tuple(self.value_id(v) for v in step.arguments[hidden:hidden+len(arg_values)])
                            facts.classes.append(F.Class(self.result_id(step),self.key,declared.interface.scope,declared.body,bases))
                        continue
                    names=[facts.scalar(facts.field(v['reference'],'arg')) for v in kw_values]
                    actual=step.arguments[1:-1];n=len(arg_values)
                    facts.calls.append(F.Call(self.value_id(step.arguments[0]),tuple(self.value_id(v) for v in actual[:n]),
                        tuple((name,self.value_id(v)) for name,v in zip(names,actual[n:])),self.result_id(step),
                        self.value_id(step.arguments[-1]),self.result_id(step,len(normal.types)-1)))
            elif type(ins) is P.ApplyDecorator:
                facts.calls.append(F.Call(self.value_id(step.arguments[0]),(self.value_id(step.arguments[1]),),(),
                    self.result_id(step),self.value_id(step.arguments[-1]),self.result_id(step,1)))
            elif type(ins) is P.BuildFunction or type(ins) is P.ApplyPythonProtocol and ins.protocol in (K.MAKE_LAMBDA_FUNCTION,K.MAKE_GENEXPR_FUNCTION,K.MAKE_NESTED_FUNCTION):
                code=step.arguments[0]
                if type(code) is not P.ProductionResult:continue
                declaration=self.steps[code.step].instruction
                if type(declaration) is not P.DeferRegion:continue
                env=declaration.environment;body=self.regions[declaration.body]
                names=[];defaults=[]
                for parameter in env.parameters:
                    if parameter.kind is P.DeferredParameterKind.INITIAL_ITERATOR:names.append('.0')
                    else:names.append(facts.scalar(parameter.source))
                    site=parameter.default_source
                    if site is None:defaults.append(None);continue
                    selected=facts.syntax['nodes'][site.occurrence]['fields'][site.ordinal]
                    for i in site.item_path:selected=selected['items'][i]
                    key=type(self.key)(selected['reference'],P.ProductionPurpose.VALUE)
                    if key not in self.interfaces['nodes']:defaults.append(None);continue
                    root=self.interfaces['nodes'][key]
                    completion=next(c for c in root.completions if c.kind is C.FALLTHROUGH)
                    defaults.append(facts.point(self.port(root.root,G.PortKind.RESULT,0,completion,template=key)))
                returned=next((c for c in body.completions if c.kind is C.RETURN),None)
                function=F.Function(self.result_id(step),self.key,body.id,env,tuple(names),
                    tuple(facts.point(self.port(body.id,G.PortKind.PARAMETER,i)) for i in range(len(body.parameters))),tuple(defaults),
                    None if returned is None else facts.point(self.port(body.id,G.PortKind.RESULT,0,returned)),
                    None if returned is None else facts.point(self.port(body.id,G.PortKind.RESULT,len(returned.types)-1,returned)))
                facts.functions.append(function)
                for parameter,formal in zip(env.parameters,function.formals[1:-1]):
                    if parameter.binding_port is not None:
                        facts.name_access(P.AccessBinding(P.BindingActionKind.WRITE,parameter.binding_port),formal)
            elif type(ins) is P.ConstructValue and ins.construction is P.ConstructionKind.LITERAL:
                literal=facts.scalar(ins.payload[0])
                if type(literal) in (str,int,bool) or literal is None:
                    facts.constants.append(F.Constant(self.result_id(step),PythonLiteral.from_python(literal,exact=True)))
            elif type(ins) is P.DefineLiteral:
                value=ins.value.to_python()
                if type(value) in (str,int,bool) or value is None:facts.constants.append(F.Constant(self.result_id(step),ins.value))


def _pins():
    return dict(builder=sha256(Path(__file__).read_bytes()).hexdigest(),facts=sha256(Path(F.__file__).read_bytes()).hexdigest(),
        normal_builder=sha256(Path(_Emitter.run.__code__.co_filename).read_bytes()).hexdigest())


def _extract(task):
    model,templates,out,unit,pins=task
    if _pins()!=pins:raise ValueError('link facts builder changed')
    reader=_Fragments(Path(model));syntax=reader.read(unit['artifacts']['source_syntax'])
    facts=_Facts(unit,syntax,reader.read(unit['artifacts']['source_bindings']),reader.read(unit['artifacts']['source_declarations']))
    graph=read_template_graph(templates,unit['key']);root=json.loads((Path(templates)/'result.json').read_bytes())
    specifications=tuple((p['domain'],p['materials'],p['verification'],p['collection_sha256'],p['verification_sha256']) for p in root['parents'])
    stores=_worker_stores(specifications,root['model_manifest_sha256'])
    interfaces=dict(nodes={n.key:n for n in graph.templates},links={(e.caller,e.step):e for e in graph.links})
    origins={(n.origin.domain,n.origin.line):n for n in graph.templates}
    for store in stores:
        basis=store.basis[unit['key']]
        for domain,line,document in store.records(dict(key=unit['key'],**{k:v for k,v in basis.items() if k!='unit'})):
            if (domain,line) not in origins:continue
            node=origins[(domain,line)]
            if _digest(document)!=node.origin.plan_sha256:raise ValueError('sealed source body differs')
            # Parent proof and original digest establish the source rule. The
            # strict codec restores its typed records without rebuilding the
            # same fixed type catalog once for every source expression.
            plan=decode(P.SourceProductionPlan,document,record_tags=P.PRODUCTION_RECORD_TAGS)
            emitter=_Aliases(plan,node.key,interfaces,facts);emitter.run();emitter.describe()
    value=F.UnitFacts(unit['key'],_module(unit['path']),tuple(facts.ports),tuple(sorted(facts.aliases)),tuple(facts.names),
        tuple(facts.functions),tuple(facts.classes),tuple(facts.attributes),tuple(facts.imports),tuple(facts.constants),tuple(facts.calls))
    payload=_json(encode(value,record_tags=P.PRODUCTION_RECORD_TAGS));compressed=gzip.compress(payload,compresslevel=3,mtime=0)
    path=Path(out)/'units'/unit['key'];_durable_mkdir(path);_durable_bytes(path/'facts.json.gz',compressed,replace=False)
    return dict(unit=unit['key'],path=unit['path'],module=value.module,facts='units/'+unit['key']+'/facts.json.gz',
        bytes=len(compressed),sha256=sha256(compressed).hexdigest(),decoded_bytes=len(payload),decoded_sha256=sha256(payload).hexdigest(),
        counts={name:len(getattr(value,name)) for name in ('ports','aliases','names','functions','classes','attributes','imports','constants','calls')})


def extract_facts(model,templates,out,sources=(),*,jobs=1):
    started=time.monotonic();model=Path(model).absolute();templates=Path(templates).absolute();out=Path(out).absolute()
    if out.exists():raise ValueError('fresh facts output required')
    model_raw=(model/'manifest.json').read_bytes();manifest=json.loads(model_raw)
    source_raw=(templates/'result.json').read_bytes();source=json.loads(source_raw)
    if sha256(model_raw).hexdigest()!=source['model_manifest_sha256']:raise ValueError('model version differs')
    wanted=set(sources);available={u['unit'] for u in source['units']}
    units=[u for u in manifest['units'] if u['key'] in available and Path(u['path']).suffix=='.py' and (not wanted or u['path'] in wanted)]
    if not units or wanted and {u['path'] for u in units}!=wanted:raise ValueError('source selection differs')
    pins=_pins();_durable_mkdir(out);tasks=[(str(model),str(templates),str(out),u,pins) for u in units]
    if jobs==1:rows=[_extract(t) for t in tasks]
    else:
        with ProcessPoolExecutor(max_workers=jobs,mp_context=multiprocessing.get_context('spawn')) as pool:rows=list(pool.map(_extract,tasks))
    if _pins()!=pins or (model/'manifest.json').read_bytes()!=model_raw or (templates/'result.json').read_bytes()!=source_raw:raise ValueError('facts inputs changed')
    counts=Counter()
    for row in rows:counts.update(row['counts'])
    result=dict(schema='scar.normal-source-link-facts',schema_version=1,status='SOURCE_LINK_FACTS_EXTRACTED',model=str(model),templates=str(templates),
        model_manifest_sha256=sha256(model_raw).hexdigest(),source_result_sha256=sha256(source_raw).hexdigest(),implementation_sha256=pins,
        selected_sources=len(rows),units=rows,counts=dict(counts),seconds=time.monotonic()-started,
        profile='NORMAL_SUCCESS',runtime_dispatch_verified=False,first_stage_complete=False,target_executed=False)
    _durable_bytes(out/'result.json',_json(result),replace=False);return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--model',required=True);p.add_argument('--templates',required=True)
    p.add_argument('--out',required=True);p.add_argument('--source',action='append',default=[]);p.add_argument('--jobs',type=int,default=1)
    a=p.parse_args();r=extract_facts(a.model,a.templates,a.out,a.source,jobs=a.jobs)
    print(json.dumps({k:r[k] for k in ('status','selected_sources','counts','seconds')},indent=2))


if __name__=='__main__':main()
