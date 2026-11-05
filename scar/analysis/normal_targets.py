"""Propagate sparse source values and connect conditional source call targets.

The solver is a may-analysis: merging branches/call contexts retains possible
targets. Connections are not runtime observations or optimization approvals.
"""
import argparse
import builtins
from collections import defaultdict,deque,Counter
import gzip
from hashlib import sha256
import json
from pathlib import Path
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import fields
from functools import lru_cache
from types import SimpleNamespace
from typing import get_type_hints

from scar.ir.program import normal_links as F
from scar.ir.program import normal_targets as T
from scar.ir.program import source_productions as P
from scar.ir.program import normal_graph as G
from scar.ir.record_codec import decode,encode
from scar.analysis.source_template_links import _json
from scar.analysis.source_stage import _durable_bytes,_durable_mkdir
from scar.analysis.static_query import _Fragments


def _star_imports(model,unit,module):
    syntax=_Fragments(Path(model)).read(unit['artifacts']['source_syntax'])
    fields={r['name']:{n:i for i,n in enumerate(r['fields'])} for r in syntax['profile']['ast_schema']}
    from scar.ir.literals import PythonLiteral
    def scalar(node,name):return decode(PythonLiteral,node['fields'][fields[node['constructor']][name]]['scalar']).to_python()
    found=[]
    for node in syntax['nodes']:
        if node['constructor']!='ImportFrom':continue
        aliases=node['fields'][fields['ImportFrom']['names']]['items']
        if not any(scalar(syntax['nodes'][v['reference']],'name')=='*' for v in aliases):continue
        name=scalar(node,'module') or '';level=scalar(node,'level')
        if level:
            package=module if Path(unit['path']).name=='__init__.py' else module.rpartition('.')[0]
            prefix=package.split('.')[:len(package.split('.'))-level+1]
            name='.'.join((*prefix,*(() if not name else name.split('.'))))
        found.append(name)
    return unit['key'],found


class _Solver:
    def __init__(self,units,stars=()):
        self.units=units;self.offsets={};self.owner=[];self.port=[];self.functions={};self.classes={}
        self.module_units=defaultdict(list);self.adj=defaultdict(set);self.values=defaultdict(set);self.queue=deque()
        self.writes=defaultdict(set);self.reads=defaultdict(set);self.ns_values=defaultdict(set)
        self.gets=defaultdict(set);self.sets=defaultdict(set);self.call_watch=defaultdict(list)
        self.member_watch=defaultdict(set);self.ctor_watch=defaultdict(set);self.classmethod_watch=defaultdict(set)
        self.dynamic_gets=defaultdict(set);self.symbol_calls=set();self.links={};self.call_rows=[]
        self.base_watch=defaultdict(set);self.ctor_base_watch=defaultdict(set)
        self.star_forward=defaultdict(set)
        self.builtin_names=set(dir(builtins));self.events=0
        for unit in units:
            offset=len(self.port);self.offsets[unit.unit]=offset
            self.owner.extend([unit.unit]*len(unit.ports));self.port.extend(unit.ports);self.module_units[unit.module].append(unit.unit)
            self.functions.update((offset+f.value,(unit,f)) for f in unit.functions)
            self.classes.update((offset+c.value,(unit,c)) for c in unit.classes)
        for target,modules in stars:
            for module in modules:
                for source in self.module_units.get(module,()):self.star_forward[source].add(target)
        for unit in units:
            offset=self.offsets[unit.unit]
            for a,b in unit.aliases:self.edge(offset+a,offset+b)
            for item in unit.names:
                key=self.ns(unit.unit,item.namespace)
                if item.write:self.writes[offset+item.value].add(key)
                else:
                    self.reads[key].add(offset+item.value)
                    if item.namespace.kind is F.NamespaceKind.BUILTINS and item.namespace.name in self.builtin_names:
                        self.add(offset+item.value,('external','builtins.'+item.namespace.name))
            for item in unit.attributes:
                if item.write:self.sets[offset+item.receiver].add((item.name,offset+item.value))
                else:self.gets[offset+item.receiver].add((item.name,offset+item.value))
            for item in unit.imports:self.add(offset+item.value,('module',item.module))
            for item in unit.constants:
                value=item.literal.to_python();self.add(offset+item.value,('constant',type(value).__name__,value))
            for call in unit.calls:
                index=len(self.call_rows);self.call_rows.append((unit,call));self.call_watch[offset+call.callee].append(index)
        for fid in self.functions:self.add(fid,('function',fid))
        for cid in self.classes:self.add(cid,('class',cid))
        for unit in units:
            offset=self.offsets[unit.unit]
            for function in unit.functions:
                for formal in function.formals[1:-1]:self.add(offset+formal,('external_value',offset+formal))

    def ns(self,unit,namespace):
        owner='' if namespace.kind is F.NamespaceKind.BUILTINS else unit
        return owner,namespace.kind.value,namespace.owner,namespace.name

    def add(self,point,value):
        if value not in self.values[point]:self.values[point].add(value);self.queue.append((point,value))

    def edge(self,source,target):
        if source==target or target in self.adj[source]:return
        self.adj[source].add(target)
        for value in tuple(self.values[source]):self.add(target,value)

    def namespace_value(self,key,value):
        if value in self.ns_values[key]:return
        self.ns_values[key].add(value)
        if len(key)==4 and key[1]==F.NamespaceKind.MODULE.value:
            for target in self.star_forward[key[0]]:self.namespace_value((target,key[1],0,key[3]),value)
        for target in self.reads[key]:self.add(target,value)
        for target,receiver,cls in self.member_watch[key]:self.member(target,receiver,cls,value)
        for call_index,receiver in self.ctor_watch[key]:
            if value[0]=='function':self.bind(call_index,value[1],receiver,mode='SOURCE_INIT',return_value=False)

    def member(self,target,receiver,cls,value):
        if receiver is not None and value[0]=='function':self.add(target,('bound',value[1],receiver))
        elif value[0]=='staticmethod':self.edge(value[1],target)
        elif value[0]=='classmethod':
            self.classmethod_watch[value[1]].add((target,cls,receiver))
            for inner in tuple(self.values[value[1]]):
                if inner[0]=='function':self.add(target,('classbound',inner[1],cls,receiver))
        else:self.add(target,value)

    def class_lookup(self,cls,name,target,receiver=None,seen=None,root=None):
        seen=set() if seen is None else seen
        root=cls if root is None else root
        if cls in seen:return
        seen.add(cls);unit,descriptor=self.classes[cls]
        key=(unit.unit,F.NamespaceKind.CLASS.value,descriptor.scope,name)
        watcher=(target,receiver,root)
        if watcher not in self.member_watch[key]:
            self.member_watch[key].add(watcher)
            for value in tuple(self.ns_values[key]):self.member(target,receiver,root,value)
        offset=self.offsets[unit.unit]
        for base in descriptor.bases:
            self.base_watch[offset+base].add((name,target,receiver,root))
            for value in tuple(self.values[offset+base]):
                if value[0]=='class':self.class_lookup(value[1],name,target,receiver,seen,root)

    def constructor(self,cls,index,receiver,seen=None):
        seen=set() if seen is None else seen
        if cls in seen:return
        seen.add(cls);unit,descriptor=self.classes[cls]
        key=(unit.unit,F.NamespaceKind.CLASS.value,descriptor.scope,'__init__')
        self.ctor_watch[key].add((index,receiver))
        for item in tuple(self.ns_values[key]):
            if item[0]=='function':self.bind(index,item[1],receiver,mode='SOURCE_INIT',return_value=False)
        for base in descriptor.bases:
            point=self.offsets[unit.unit]+base;self.ctor_base_watch[point].add((index,receiver))
            for item in tuple(self.values[point]):
                if item[0]=='class':self.constructor(item[1],index,receiver,seen)

    def attribute(self,point,value,name,target):
        if value[0]=='module':
            module=value[1];units=self.module_units.get(module,())
            for unit in units:
                key=(unit,F.NamespaceKind.MODULE.value,0,name)
                self.reads[key].add(target)
                for item in tuple(self.ns_values[key]):self.add(target,item)
            child=module+'.'+name
            if child in self.module_units:self.add(target,('module',child))
            if not units:self.add(target,('external',child,(target,)))
        elif value[0]=='external':
            # Retain rooted external namespace provenance until a source
            # member site repeats. Cyclic aliases then widen to an unqualified
            # member rather than growing names indefinitely. Attribute lookup
            # remains a conditional alternative, never an observed binding.
            visited=value[2] if len(value)>2 else ()
            if target not in visited:self.add(target,('external',value[1]+'.'+name,(*visited,target)))
            else:self.add(target,('external_member',target,name))
        elif value[0] in ('external_value','external_member'):
            self.add(target,('external_member',target,name))
        elif value[0]=='class':self.class_lookup(value[1],name,target)
        elif value[0]=='instance':
            key=('field',value,name)
            self.reads[key].add(target)
            for item in tuple(self.ns_values[key]):self.add(target,item)
            self.class_lookup(value[1],name,target,point)

    @lru_cache(maxsize=None)
    def gp(self,point):
        port=self.port[point]
        if type(port) is dict:port=decode(G.Port,port,record_tags=P.PRODUCTION_RECORD_TAGS)
        return T.GlobalPort(self.owner[point],port)

    def bind(self,call_index,fid,receiver=None,*,mode='SOURCE_FUNCTION',return_value=True,class_receiver=None):
        identity=(call_index,fid,receiver,mode,class_receiver)
        if identity in self.symbol_calls:return
        self.symbol_calls.add(identity)
        caller,call=self.call_rows[call_index];unit,function=self.functions[fid]
        offset=self.offsets[caller.unit];target_offset=self.offsets[unit.unit]
        if call.positional_pack is not None:
            # Target provenance is useful even with unknown argument packing.
            # No pack->formal alias, invented arity, or body execution is granted.
            routes=(T.Route(self.gp(target_offset+function.formals[0]),T.RouteKind.FUNCTION_ENVIRONMENT,(self.gp(offset+call.callee),)),
                T.Route(self.gp(target_offset+function.formals[-1]),T.RouteKind.STATE,(self.gp(offset+call.world),)))
            synchronous=function.environment.kind is P.DeferredBodyKind.FUNCTION
            self.links[identity]=T.CallLink(self.gp(offset+call.result),self.gp(offset+call.callee),self.gp(fid),
                T.Body(unit.unit,function.template,function.body),mode if synchronous else 'CREATE_DEFERRED_BODY',None,
                routes,(),('SOURCE_STATIC_CANDIDATE','CURRENT_CALLABLE_DESCRIPTOR','STANDARD_MODULE_NAMESPACES',
                    'ARGUMENT_PACK_BINDING_PENDING'),argument_packs=self.packs(caller,call,receiver,class_receiver))
            return
        positional=[offset+p for p in call.positional]
        if receiver is not None:positional.insert(0,receiver)
        keyword=dict((name,offset+p) for name,p in call.keywords)
        params=function.environment.parameters;routes=[];position=0;bindings=[];class_bindings=[]
        for i,(param,name) in enumerate(zip(params,function.parameter_names)):
            formal=target_offset+function.formals[i+1]
            kind=param.kind;actuals=();route=T.RouteKind.ARGUMENT;keys=()
            if class_receiver is not None and i==0:
                class_bindings.append((formal,('class',class_receiver)));route=T.RouteKind.CLASS_RECEIVER
                actuals=() if receiver is None else (receiver,)
                if receiver is not None:position=1
            elif kind in (P.DeferredParameterKind.POSITIONAL_ONLY,P.DeferredParameterKind.POSITIONAL_OR_KEYWORD) and position<len(positional):
                actuals=(positional[position],);position+=1
            elif kind in (P.DeferredParameterKind.POSITIONAL_OR_KEYWORD,P.DeferredParameterKind.KEYWORD_ONLY) and name in keyword:
                actuals=(keyword.pop(name),)
            elif kind is P.DeferredParameterKind.VAR_POSITIONAL:
                actuals=tuple(positional[position:]);position=len(positional);route=T.RouteKind.PACK_POSITIONALS
            elif kind is P.DeferredParameterKind.VAR_KEYWORD:
                keys=tuple(keyword);actuals=tuple(keyword.values());keyword.clear();route=T.RouteKind.PACK_KEYWORDS
            elif function.defaults[i] is not None:
                actuals=(target_offset+function.defaults[i],);route=T.RouteKind.INITIAL_DEFAULT
            else:return  # no successful binding under this source signature
            routes.append(T.Route(self.gp(formal),route,tuple(self.gp(p) for p in actuals),keys))
            if route in (T.RouteKind.ARGUMENT,T.RouteKind.INITIAL_DEFAULT):
                for source in actuals:bindings.append((source,formal))
        if position<len(positional) or keyword:return
        synchronous=function.environment.kind is P.DeferredBodyKind.FUNCTION
        if synchronous:
            for source,formal in bindings:self.edge(source,formal)
            for formal,value in class_bindings:self.add(formal,value)
        routes.insert(0,T.Route(self.gp(target_offset+function.formals[0]),T.RouteKind.FUNCTION_ENVIRONMENT,(self.gp(offset+call.callee),)))
        routes.append(T.Route(self.gp(target_offset+function.formals[-1]),T.RouteKind.STATE,(self.gp(offset+call.world),)))
        returned=[]
        if synchronous and return_value and function.returns is not None:
            self.edge(target_offset+function.returns,offset+call.result)
            returned.append((self.gp(target_offset+function.returns),self.gp(offset+call.result)))
        if synchronous and function.return_world is not None:
            returned.append((self.gp(target_offset+function.return_world),self.gp(offset+call.result_world)))
        self.links[identity]=T.CallLink(self.gp(offset+call.result),self.gp(offset+call.callee),self.gp(fid),
            T.Body(unit.unit,function.template,function.body),mode if synchronous else 'CREATE_DEFERRED_BODY',None,
            tuple(routes),tuple(returned),('SOURCE_STATIC_CANDIDATE','CURRENT_CALLABLE_DESCRIPTOR','STANDARD_MODULE_NAMESPACES'))

    def packs(self,unit,call,receiver=None,class_receiver=None):
        if call.positional_pack is None:return None
        offset=self.offsets[unit.unit]
        return T.ArgumentPacks(self.gp(offset+call.positional_pack),
            None if call.keyword_pack is None else self.gp(offset+call.keyword_pack),
            None if receiver is None else self.gp(receiver),
            None if class_receiver is None else self.gp(class_receiver))

    def call(self,index,value):
        caller,call=self.call_rows[index];offset=self.offsets[caller.unit]
        if value[0]=='function':self.bind(index,value[1])
        elif value[0]=='bound':self.bind(index,value[1],value[2],mode='SOURCE_BOUND_METHOD')
        elif value[0]=='classbound':self.bind(index,value[1],value[3],mode='SOURCE_CLASS_METHOD',class_receiver=value[2])
        elif value[0]=='class':
            cls=value[1];result=offset+call.result;self.add(result,('instance',cls,result))
            self.links[(index,'class',cls)]=T.CallLink(self.gp(result),self.gp(offset+call.callee),self.gp(cls),None,'SOURCE_CONSTRUCTION',None,
                conditions=('SOURCE_STATIC_CANDIDATE','DEFAULT_TYPE_CONSTRUCTION'),argument_packs=self.packs(caller,call))
            self.constructor(cls,index,result)
        elif value[0] in ('external','external_member'):
            name=value[1] if value[0]=='external' else 'member:'+value[2]
            mode='EXTERNAL_SYMBOL' if value[0]=='external' else 'DYNAMIC_MEMBER'
            conditions=('SOURCE_RECEIVER_MEMBER','RUNTIME_MEMBER_TARGET_UNKNOWN') if mode=='DYNAMIC_MEMBER' else (
                'SOURCE_STATIC_CANDIDATE','STANDARD_IMPORT_AND_BUILTIN_NAMESPACES','STANDARD_ATTRIBUTE_LOOKUP')
            self.links[(index,mode,name)]=T.CallLink(self.gp(offset+call.result),self.gp(offset+call.callee),None,None,mode,name,
                conditions=conditions,argument_packs=self.packs(caller,call))
            self.add(offset+call.result,('external_value',offset+call.result))
            if name in ('builtins.staticmethod','builtins.classmethod') and call.positional:
                self.add(offset+call.result,('staticmethod' if name.endswith('staticmethod') else 'classmethod',offset+call.positional[0]))
            elif name=='builtins.getattr' and len(call.positional)>=2:
                receiver=offset+call.positional[0];name_point=offset+call.positional[1];out=offset+call.result
                self.dynamic_gets[name_point].add((receiver,out))
                for item in tuple(self.values[name_point]):
                    if item[0]=='constant' and item[1]=='str':
                        self.gets[receiver].add((item[2],out))
                        for base in tuple(self.values[receiver]):self.attribute(receiver,base,item[2],out)
            elif name in ('builtins.__import__','importlib.import_module') and call.positional:
                for item in tuple(self.values[offset+call.positional[0]]):
                    if item[0]=='constant' and item[1]=='str':self.add(offset+call.result,('module',item[2]))

    def solve(self,max_events=20_000_000):
        while self.queue and self.events<max_events:
            point,value=self.queue.popleft();self.events+=1
            for target in tuple(self.adj[point]):self.add(target,value)
            for namespace in tuple(self.writes[point]):self.namespace_value(namespace,value)
            for name,target in tuple(self.gets[point]):self.attribute(point,value,name,target)
            for name,source in tuple(self.sets[point]):
                if value[0]=='instance':
                    key=('field',value,name);self.writes[source].add(key)
                    for item in tuple(self.values[source]):self.namespace_value(key,item)
            for index in self.call_watch[point]:self.call(index,value)
            if value[0]=='class':
                for name,target,receiver,root in tuple(self.base_watch[point]):self.class_lookup(value[1],name,target,receiver,root=root)
                for index,receiver in tuple(self.ctor_base_watch[point]):self.constructor(value[1],index,receiver)
            for target,cls,receiver in tuple(self.classmethod_watch[point]):
                if value[0]=='function':self.add(target,('classbound',value[1],cls,receiver))
            if value[0]=='constant' and value[1]=='str':
                for receiver,out in tuple(self.dynamic_gets[point]):
                    self.gets[receiver].add((value[2],out))
                    for base in tuple(self.values[receiver]):self.attribute(receiver,base,value[2],out)
        return not self.queue


def solve_targets(facts,out,*,max_events=20_000_000):
    started=time.monotonic();facts=Path(facts).absolute();out=Path(out).absolute()
    if out.exists():raise ValueError('fresh target output required')
    root=(facts/'result.json').read_bytes();report=json.loads(root);units=[]
    if report['implementation_sha256']['facts']!=sha256(Path(F.__file__).read_bytes()).hexdigest():raise ValueError('source fact declarations differ')
    hints=get_type_hints(F.UnitFacts);expected={f.name for f in fields(F.UnitFacts)}
    for row in report['units']:
        payload=(facts/row['facts']).read_bytes()
        if len(payload)!=row['bytes'] or sha256(payload).hexdigest()!=row['sha256']:raise ValueError('source facts compressed receipt differs')
        raw=gzip.decompress(payload)
        if len(raw)!=row['decoded_bytes'] or sha256(raw).hexdigest()!=row['decoded_sha256']:raise ValueError('source facts decoded receipt differs')
        document=json.loads(raw)
        if set(document)!=expected or document['unit']!=row['unit']:raise ValueError('source fact fields differ')
        # The immutable producer receipt covers the complete port table.
        # Keep its wire representation until a queried/output port is needed;
        # that port then goes through the same exact nominal decoder.
        ports=document['ports'];aliases=document['aliases']
        if type(ports) is not list or type(aliases) is not list:raise ValueError('source fact tables differ')
        size=len(ports)
        if any(type(pair) is not list or len(pair)!=2 or any(type(v) is not int or not 0<=v<size for v in pair) for pair in aliases):raise ValueError('source alias ordinal differs')
        loaded={name:decode(hints[name],value,record_tags=P.PRODUCTION_RECORD_TAGS) for name,value in document.items() if name not in ('ports','aliases')}
        units.append(SimpleNamespace(**loaded,ports=ports,aliases=aliases))
    model=Path(report['model']);model_raw=(model/'manifest.json').read_bytes()
    if sha256(model_raw).hexdigest()!=report['model_manifest_sha256']:raise ValueError('source model changed')
    model_units={u['key']:u for u in json.loads(model_raw)['units']}
    with ThreadPoolExecutor(max_workers=8) as pool:
        stars=list(pool.map(lambda u:_star_imports(str(model),model_units[u.unit],u.module),units))
    solver=_Solver(units,stars);fixed=solver.solve(max_events);_durable_mkdir(out)
    from scar.analysis.source_template_links import _stream
    fragment=_stream(out/'calls.jsonl.gz',solver.links.values())
    modes=Counter(link.mode for link in solver.links.values());known_calls={link.result for link in solver.links.values()}
    source_calls={link.result for link in solver.links.values() if link.source_callable is not None}
    original_calls=sum(len(u.calls) for u in units)
    result=dict(schema='scar.normal-source-targets',schema_version=2,status='SOURCE_TARGET_FIXED_POINT' if fixed else 'SOURCE_TARGET_BUDGET_FRONTIER',
        source_facts=str(facts),source_facts_sha256=sha256(root).hexdigest(),profile='NORMAL_SUCCESS',
        selected_sources=len(units),source_calls=original_calls,source_functions=len(solver.functions),source_classes=len(solver.classes),
        calls_with_candidates=len(known_calls),candidate_links=len(solver.links),modes=dict(modes),
        calls_with_source_targets=len(source_calls),
        packed_source_calls=sum(c.positional_pack is not None for u in units for c in u.calls),
        packed_candidate_links=sum(link.argument_packs is not None for link in solver.links.values()),
        classes_with_packed_bases=sum(c.bases_pack is not None for u in units for c in u.classes),
        star_import_module_candidates=sum(len(names) for _,names in stars),
        unresolved_calls=original_calls-len(known_calls),value_events=solver.events,frontier=len(solver.queue),
        calls=fragment,seconds=time.monotonic()-started,conditions='source target alternatives; descriptor/module/attribute admissions remain conditional',
        runtime_dispatch_verified=False,effects_proven=False,first_stage_complete=False,target_executed=False,transformation_authorized=False,
        implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),types_sha256=sha256(Path(T.__file__).read_bytes()).hexdigest())
    _durable_bytes(out/'result.json',_json(result),replace=False);return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--facts',required=True);p.add_argument('--out',required=True)
    p.add_argument('--max-events',type=int,default=20_000_000);a=p.parse_args();r=solve_targets(a.facts,a.out,max_events=a.max_events)
    print(json.dumps({k:r[k] for k in ('status','source_calls','calls_with_candidates','candidate_links','modes','value_events','seconds')},indent=2))


if __name__=='__main__':main()
