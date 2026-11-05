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
import sys
from pathlib import Path
import time
from contextlib import ExitStack
import faulthandler
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
from scar.analysis import source_template_batch,source_template_workers,normal_output,source_interface_store,source_content_factors,normal_containers,source_container_delta
from scar.ir.program import source_interfaces as L,content_factors as C
from scar.analysis.source_stage import _durable_bytes,_durable_mkdir
from scar.analysis.static_query import _Fragments
from scar.analysis import normal_namespaces
from scar.analysis import source_descriptors,source_function_connections,source_construction,source_generators,source_suspension_interfaces
from scar.analysis.source_function_connections import Invocation,connect
from scar.analysis.source_descriptors import DescriptorFlow
from scar.ir.program import normal_namespaces as N
from scar.ir.program import source_generators as D,suspension_interfaces as S


def propagation_pins():
    """Bind the complete source-content implementation, including overrides."""
    return {name:sha256(Path(path).read_bytes()).hexdigest() for name,path in (
        ('solver',__file__),('containers',normal_containers.__file__),
        ('container_delta',source_container_delta.__file__))}


def _star_imports(model,unit,module):
    syntax=_Fragments(Path(model)).read(unit['artifacts']['source_syntax'])
    fields={r['name']:{n:i for i,n in enumerate(r['fields'])} for r in syntax['profile']['ast_schema']}
    from scar.ir.literals import PythonLiteral
    def scalar(node,name):return decode(PythonLiteral,node['fields'][fields[node['constructor']][name]]['scalar']).to_python()
    found=[];requested=set()
    for node in syntax['nodes']:
        if node['constructor']=='Import':
            for value in node['fields'][fields['Import']['names']]['items']:
                requested.add(scalar(syntax['nodes'][value['reference']],'name'))
            continue
        if node['constructor']!='ImportFrom':continue
        aliases=node['fields'][fields['ImportFrom']['names']]['items']
        name=scalar(node,'module') or '';level=scalar(node,'level')
        if level:
            package=module if Path(unit['path']).name=='__init__.py' else module.rpartition('.')[0]
            prefix=package.split('.')[:len(package.split('.'))-level+1]
            name='.'.join((*prefix,*(() if not name else name.split('.'))))
        if name:requested.add(name)
        if any(scalar(syntax['nodes'][v['reference']],'name')=='*' for v in aliases):found.append(name)
    return unit['key'],found,tuple(sorted(requested))


class _Solver:
    def __init__(self,units,stars=(),*,jobs=None,interface_store=None):
        if jobs is not None and (type(jobs) is not int or jobs<1):raise ValueError('positive analysis worker count required')
        self.analysis_jobs=jobs
        self.interface_store=interface_store
        self.units=units;self.offsets={};self.owner=[];self.port=[];self.functions={};self.classes={}
        self.interface_ports={};self.interface_points={};self.interface_reverse={};self.original_templates={};self.original_indices={}
        self.module_units=defaultdict(list);self.adj=defaultdict(set);self.values=defaultdict(set);self.queue=deque()
        self.writes=defaultdict(set);self.reads=defaultdict(set);self.ns_values=defaultdict(set)
        self.gets=defaultdict(set);self.call_watch=defaultdict(list)
        self.member_watch=defaultdict(set);self.classmethod_watch=defaultdict(set)
        self.instance_call_sinks={};self.instance_call_watch={}
        self.dynamic_gets=defaultdict(set);self.symbol_calls=set();self.links={};self.call_rows=[]
        self.base_watch=defaultdict(set)
        self.star_forward=defaultdict(set)
        self.imported_modules=set();self.external_namespaces=set()
        self.builtin_names=set(dir(builtins));self.events=0
        for unit in units:
            offset=len(self.port);self.offsets[unit.unit]=offset
            self.owner.extend([unit.unit]*len(unit.ports));self.port.extend(unit.ports);self.module_units[unit.module].append(unit.unit)
            self.functions.update((offset+f.value,(unit,f)) for f in unit.functions)
            self.classes.update((offset+c.value,(unit,c)) for c in unit.classes)
        for target,modules,*inventory in stars:
            for module in modules:
                for source in self.module_units.get(module,()):self.star_forward[source].add(target)
            for module in (() if not inventory else inventory[0]):
                parts=module.split('.')
                self.imported_modules.update('.'.join(parts[:i]) for i in range(1,len(parts)+1))
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
                if item.action in (F.AttributeAction.GET,F.AttributeAction.IMPORT_MEMBER):
                    self.gets[offset+item.receiver].add((item.name,offset+item.value))
            for item in unit.imports:self.add(offset+item.value,('module',item.module))
            for item in unit.constants:
                value=item.literal.to_python();self.add(offset+item.value,('constant',type(value).__name__,value))
            for call in unit.calls:
                index=len(self.call_rows);self.call_rows.append((unit,call));self.call_watch[offset+call.callee].append(index)
        self.descriptors=DescriptorFlow(self,units)
        for fid in self.functions:self.add(fid,('function',fid))
        for cid in self.classes:self.add(cid,('class',cid))
        for unit in units:
            offset=self.offsets[unit.unit]
            for function in unit.functions:
                for formal in function.formals[1:-1]:self.add(offset+formal,('external_value',offset+formal))
        self.containers=source_container_delta.DeltaContainerFlow(self,units)
        self.constructions=source_construction.ConstructionFlow(self)
        self.generators=source_generators.SourceGeneratorFlow(self)

    def ns(self,unit,namespace):
        owner='' if namespace.kind is F.NamespaceKind.BUILTINS else unit
        return owner,namespace.kind.value,namespace.owner,namespace.name

    def add(self,point,value):
        # These are transfer-domain facts, not object/value identities. All
        # consumers of an open value use only its tag; provenance stays on
        # the original ports and routes rather than multiplying this token.
        if value[0]=='external_value':value=('external_value',None)
        elif value[0]=='external':value=('external',value[1])
        if value not in self.values[point]:self.values[point].add(value);self.queue.append((point,value))

    def edge(self,source,target):
        if source==target or target in self.adj[source]:return
        self.adj[source].add(target)
        for value in tuple(self.values.get(source,())):self.add(target,value)

    def namespace_value(self,key,value):
        if value in self.ns_values[key]:return
        self.ns_values[key].add(value)
        if len(key)==4 and key[1]==F.NamespaceKind.MODULE.value:
            for target in self.star_forward.get(key[0],()):self.namespace_value((target,key[1],0,key[3]),value)
        for target in self.reads.get(key,()):self.add(target,value)
        for target,receiver,cls in self.member_watch.get(key,()):self.member(target,receiver,cls,value)

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

    def instance_call(self,index,cls,receiver):
        identity=(index,cls,receiver)
        if identity in self.instance_call_sinks:return
        # This lookup target is internal: it is never an original graph port
        # or an alias of the object being called. Reusing class lookup keeps
        # late namespace, base and descriptor values in the same fixed point.
        sink=('instance_call_lookup',*identity)
        self.instance_call_sinks[identity]=sink
        self.instance_call_watch[sink]=(index,receiver)
        self.class_lookup(cls,'__call__',sink,receiver)

    def instance_call_target(self,index,receiver,value):
        conditions=('SPECIAL_METHOD_LOOKUP_ON_CLASS','INSTANCE_DICTIONARY_BYPASSED',
            'STANDARD_INSTANCE_CALL_SLOT_DISPATCH','CURRENT_CLASS_MRO_SELECTS_DECLARATION')
        if value[0]=='bound':
            fid=value[1];mode='SOURCE_INSTANCE_CALL'
            descriptor='STANDARD_FUNCTION_DESCRIPTOR_BINDING';class_receiver=None;receiver=value[2]
        elif value[0]=='function':
            fid=value[1];mode='SOURCE_INSTANCE_STATIC_CALL'
            descriptor='STANDARD_STATICMETHOD_DESCRIPTOR_BINDING';class_receiver=None;receiver=None
        elif value[0]=='classbound':
            fid=value[1];mode='SOURCE_INSTANCE_CLASS_CALL'
            descriptor='STANDARD_CLASSMETHOD_DESCRIPTOR_BINDING';class_receiver=value[2];receiver=value[3]
        else:return
        self.bind(index,fid,receiver,mode=mode,class_receiver=class_receiver,
            conditions=(*conditions,descriptor),environment_source=fid,
            deferred_mode=mode+'_CREATE_DEFERRED_BODY')

    def attribute(self,point,value,name,target):
        if self.generators.attribute(value,name,target):return
        if self.descriptors.attribute(point,value,name,target):return
        if value[0]=='module':
            module=value[1];units=self.module_units.get(module,())
            for unit in units:
                key=(unit,F.NamespaceKind.MODULE.value,0,name)
                self.reads[key].add(target)
                for item in tuple(self.ns_values[key]):self.add(target,item)
            child=module+'.'+name
            if child in self.module_units or child in self.imported_modules:self.add(target,('module',child))
            if not units:self.add(target,('external',child,(target,)))
        elif value[0]=='external':
            # A qualified symbol is not automatically another namespace.
            # Extend only admitted modules or provider-declared containers.
            # Other projections keep their original receiver/result graph
            # ports without inventing recursively concatenated symbol names.
            if value[1]=='builtins.object' and name=='__new__':
                self.add(target,('external','builtins.object.__new__'))
            elif value[1] in self.module_units or value[1] in self.imported_modules or value[1] in self.external_namespaces:
                self.add(target,('external',value[1]+'.'+name))
            else:self.add(target,('external_member',target,name))
        elif value[0] in ('external_value','external_member'):
            self.add(target,('external_member',target,name))
        elif value[0]=='class':self.class_lookup(value[1],name,target)
        elif value[0]=='instance':
            self.descriptors.read(point,value,name,target)
        elif value[0]=='container':self.containers.attribute(value,name,target)

    @lru_cache(maxsize=None)
    def gp(self,point):
        if type(point) is int and point<0:return self.interface_ports[point]
        port=self.port[point]
        if type(port) is dict:port=decode(G.Port,port,record_tags=P.PRODUCTION_RECORD_TAGS)
        return T.GlobalPort(self.owner[point],port)

    def interface_point(self,key,endpoint):
        """Internal transfer index for a typed interface, not a source ID."""
        if key not in self.interface_points:
            point=self.interface_reverse.get(endpoint)
            if point is None:
                point=-len(self.interface_ports)-1
                self.interface_ports[point]=endpoint;self.interface_reverse[endpoint]=point
            self.interface_points[key]=point
        point=self.interface_points[key]
        if self.interface_ports[point]!=endpoint:raise ValueError('interface key selects another endpoint')
        return point

    def endpoint_point(self,endpoint):
        if type(endpoint) is T.GlobalPort:return self.original_point(endpoint)
        if endpoint not in self.interface_reverse:raise ValueError('protocol endpoint was not declared')
        return self.interface_reverse[endpoint]

    def original_point(self,endpoint):
        """Reuse F5 ports or register a witnessed original F4 port lazily.

        The caller supplies provenance from the sealed interface index. New
        transfer ordinals never masquerade as positions in the F5 port table.
        """
        if type(endpoint) is not T.GlobalPort:raise ValueError('original source endpoint required')
        identity=endpoint.unit
        if identity not in self.original_templates:
            unit=self.store.load(identity) if hasattr(self,'store') else next(u for u in self.units if u.unit==identity)
            groups=defaultdict(list)
            for i,port in enumerate(unit.ports):
                key=(port['template']['occurrence'],port['template']['purpose']) if type(port) is dict else (port.template.occurrence,port.template.purpose.value)
                groups[key].append((i,port))
            self.original_templates[identity]=groups
        template=endpoint.port.template;key=identity,template
        if key not in self.original_indices:
            self.original_indices[key]={
                decode(G.Port,wire,record_tags=P.PRODUCTION_RECORD_TAGS) if type(wire) is dict else wire:self.offsets[identity]+i
                for i,wire in self.original_templates[identity].get((template.occurrence,template.purpose.value),())}
        point=self.original_indices[key].get(endpoint.port)
        return point if point is not None else self.interface_point(('original',endpoint),endpoint)

    def bind(self,call_index,fid,receiver=None,*,mode='SOURCE_FUNCTION',return_value=True,class_receiver=None,
             conditions=(),environment_source=None,deferred_mode='CREATE_DEFERRED_BODY'):
        identity=(call_index,fid,receiver,mode,class_receiver)
        if identity in self.symbol_calls:return
        self.symbol_calls.add(identity)
        caller,call=self.call_rows[call_index];offset=self.offsets[caller.unit]
        invocation=Invocation(offset+call.callee,tuple(offset+p for p in call.positional),
            tuple((name,offset+p) for name,p in call.keywords),offset+call.result,
            offset+call.world,offset+call.result_world,
            None if call.positional_pack is None else offset+call.positional_pack,
            None if call.keyword_pack is None else offset+call.keyword_pack)
        def publish(connection):
            self.links[identity]=T.CallLink(self.gp(offset+call.result),self.gp(offset+call.callee),
                connection.source_callable,connection.body,
                mode if connection.activation is T.FunctionActivation.NORMAL else deferred_mode,None,
                connection.parameters,connection.returns,connection.conditions,
                argument_packs=connection.argument_packs,projections=connection.projections,binding=connection.binding)
        connection=connect(self,fid,invocation,receiver,class_receiver=class_receiver,
            environment_source=environment_source,return_value=return_value,conditions=conditions,on_ready=publish)
        if connection is not None:publish(connection)

    def packs(self,unit,call,receiver=None,class_receiver=None):
        if call.positional_pack is None and call.keyword_pack is None:return None
        offset=self.offsets[unit.unit]
        return T.ArgumentPacks(None if call.positional_pack is None else self.gp(offset+call.positional_pack),
            None if call.keyword_pack is None else self.gp(offset+call.keyword_pack),
            None if receiver is None else self.gp(receiver),
            None if class_receiver is None else self.gp(class_receiver))

    def call(self,index,value):
        caller,call=self.call_rows[index];offset=self.offsets[caller.unit]
        if value[0]=='property_method':self.descriptors.call(index,value)
        elif value[0]=='container_method':
            name='builtins.'+('dict' if value[1][2]=='MAPPING' else 'set' if value[1][2]=='SET' else 'list')+'.'+value[2]
            self.links[(index,'container',value[1],value[2])]=T.CallLink(self.gp(offset+call.result),self.gp(offset+call.callee),
                None,None,'BUILTIN_CONTAINER_METHOD',name,conditions=('SOURCE_BUILTIN_CONTAINER','FLOW_INSENSITIVE_MAY_CONTENT'),
                argument_packs=self.packs(caller,call))
            self.containers.call(caller,call,value)
        elif value[0]=='function':self.bind(index,value[1])
        elif value[0]=='bound':self.bind(index,value[1],value[2],mode='SOURCE_BOUND_METHOD')
        elif value[0]=='classbound':self.bind(index,value[1],value[3],mode='SOURCE_CLASS_METHOD',class_receiver=value[2])
        elif value[0]=='instance':self.instance_call(index,value[1],offset+call.callee)
        elif value[0]=='class':
            cls=value[1];result=offset+call.result
            self.links[(index,'class',cls)]=T.CallLink(self.gp(result),self.gp(offset+call.callee),self.gp(cls),None,'SOURCE_CONSTRUCTION',None,
                conditions=('SOURCE_STATIC_CANDIDATE','STANDARD_TYPE_CALL_SLOT_ADMISSION','NEW_THEN_CONDITIONAL_INIT'),argument_packs=self.packs(caller,call))
            self.constructions.construct(index,cls)
        elif value[0] in ('external','external_member'):
            name=value[1] if value[0]=='external' else 'member:'+value[2]
            mode='EXTERNAL_SYMBOL' if value[0]=='external' else 'DYNAMIC_MEMBER'
            conditions=('SOURCE_RECEIVER_MEMBER','RUNTIME_MEMBER_TARGET_UNKNOWN') if mode=='DYNAMIC_MEMBER' else (
                'SOURCE_STATIC_CANDIDATE','STANDARD_IMPORT_AND_BUILTIN_NAMESPACES','STANDARD_ATTRIBUTE_LOOKUP')
            self.links[(index,mode,name)]=T.CallLink(self.gp(offset+call.result),self.gp(offset+call.callee),None,None,mode,name,
                conditions=conditions,argument_packs=self.packs(caller,call))
            self.add(offset+call.result,('external_value',offset+call.result))
            self.containers.external(caller,call,name)
            if name=='builtins.object.__new__':self.constructions.object_new(index)
            elif name=='builtins.property':self.descriptors.construct(index)
            elif name in ('builtins.staticmethod','builtins.classmethod') and call.positional:
                self.add(offset+call.result,('staticmethod' if name.endswith('staticmethod') else 'classmethod',offset+call.positional[0]))
            elif name=='builtins.getattr' and len(call.positional)>=2:
                receiver=offset+call.positional[0];name_point=offset+call.positional[1];out=offset+call.result
                self.dynamic_gets[name_point].add((receiver,out,index))
                for item in tuple(self.values[name_point]):
                    if item[0]=='constant' and item[1]=='str':
                        self.descriptors.builtin_getattr(index,item[2])
                        self.gets[receiver].add((item[2],out))
                        for base in tuple(self.values[receiver]):self.attribute(receiver,base,item[2],out)
            elif name in ('builtins.__import__','importlib.import_module') and call.positional:
                for item in tuple(self.values[offset+call.positional[0]]):
                    if item[0]=='constant' and item[1]=='str':self.add(offset+call.result,('module',item[2]))

    def solve(self,max_events=20_000_000):
        while self.queue and self.events<max_events:
            point,value=self.queue.popleft();self.events+=1
            for target in tuple(self.adj.get(point,())):self.add(target,value)
            for namespace in tuple(self.writes.get(point,())):self.namespace_value(namespace,value)
            for name,target in tuple(self.gets.get(point,())):self.attribute(point,value,name,target)
            for index in self.call_watch.get(point,()):self.call(index,value)
            if point in self.instance_call_watch:
                index,receiver=self.instance_call_watch[point]
                self.instance_call_target(index,receiver,value)
            if value[0]=='class':
                for name,target,receiver,root in tuple(self.base_watch.get(point,())):self.class_lookup(value[1],name,target,receiver,root=root)
            for target,cls,receiver in tuple(self.classmethod_watch.get(point,())):
                if value[0]=='function':self.add(target,('classbound',value[1],cls,receiver))
            if value[0]=='constant' and value[1]=='str':
                for receiver,out,index in tuple(self.dynamic_gets.get(point,())):
                    self.descriptors.builtin_getattr(index,value[2])
                    self.gets[receiver].add((value[2],out))
                    for base in tuple(self.values[receiver]):self.attribute(receiver,base,value[2],out)
            self.containers.consume(point,value)
            self.descriptors.consume(point,value)
            self.constructions.consume(point,value)
        return not self.queue


def solve_targets(facts,out,*,max_events=20_000_000,entries=(),jobs=None,interfaces=None):
    if entries:return solve_entry_targets(facts,out,entries,max_events=max_events,jobs=jobs,interfaces=interfaces)
    if interfaces is not None:raise ValueError('local interfaces require an entry-scoped source catalog')
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
    solver=_Solver(units,stars,jobs=jobs)
    while solver.queue and solver.events<max_events:
        solver.solve(min(max_events,solver.events+2_000_000))
        print(json.dumps(dict(phase='SOURCE_TARGET_PROPAGATION',events=solver.events,
            frontier=len(solver.queue),value_facts=solver.events+len(solver.queue),
            value_ports=len(solver.values),seconds=time.monotonic()-started)),file=sys.stderr,flush=True)
    fixed=not solver.queue
    return _publish(solver,facts,root,report,out,started,max_events,fixed,stars)


def _publish(solver,facts,root,report,out,started,max_events,fixed,stars,extra=None):
    publish_started=time.monotonic();table_write_seconds={}
    solver.generators.validate_parents()
    solver.generators.close()
    units=solver.units;_durable_mkdir(out)
    from scar.analysis.normal_output import write_table
    def _stream(path,records):return write_table(path,records,timings=table_write_seconds)
    fragment=_stream(out/'calls.jsonl.gz',solver.links.values())
    content=source_content_factors.write_factors(solver.containers,out)
    table_write_seconds['content-factors.jsonl.gz']=content['content_factor_stats']['seconds']
    namespaces=_stream(out/'namespaces.jsonl.gz',normal_namespaces.namespace_lookups(solver))
    properties=_stream(out/'properties.jsonl.gz',solver.descriptors.property_accesses.values())
    attribute_storage=_stream(out/'attribute-storage.jsonl.gz',solver.descriptors.storage_accesses.values())
    attribute_content=_stream(out/'attribute-content.jsonl.gz',solver.descriptors.content_links.values())
    constructions=_stream(out/'constructions.jsonl.gz',solver.constructions.links.values())
    modes=Counter(link.mode for link in solver.links.values());known_calls={link.result for link in solver.links.values()}
    source_calls={link.result for link in solver.links.values() if link.source_callable is not None}
    original_calls=sum(len(u.calls) for u in units)
    result=dict(schema='scar.normal-source-targets',schema_version=12,status='SOURCE_TARGET_FIXED_POINT' if fixed else 'SOURCE_TARGET_BUDGET_FRONTIER',
        analysis_mode='LIBRARY_MAY_ANALYSIS',
        source_facts=str(facts),source_facts_sha256=sha256(root).hexdigest(),profile='NORMAL_SUCCESS',
        selected_sources=len(units),source_calls=original_calls,source_functions=len(solver.functions),source_classes=len(solver.classes),
        calls_with_candidates=len(known_calls),candidate_links=len(solver.links),modes=dict(modes),
        calls_with_source_targets=len(source_calls),
        argument_bindings=dict(Counter(link.binding.value for link in solver.links.values())),
        argument_projections=sum(len(link.projections) for link in solver.links.values()),
        packed_source_calls=sum(c.positional_pack is not None for u in units for c in u.calls),
        packed_candidate_links=sum(link.argument_packs is not None for link in solver.links.values()),
        classes_with_packed_bases=sum(c.bases_pack is not None for u in units for c in u.classes),
        unknown_namespace_keys=len(solver.containers.unknown_keys),
        container_implementation_sha256=sha256(Path(normal_containers.__file__).read_bytes()).hexdigest(),
        propagation_pins=propagation_pins(),container_analysis=dict(solver.containers.delta_stats),
        star_import_module_candidates=sum(len(names) for _,names,*_ in stars),
        declared_import_modules=len(solver.imported_modules),namespace_lookups=namespaces['records'],namespaces=namespaces,
        properties=properties,property_states=dict(Counter(p.state.value for p in solver.descriptors.property_accesses.values())),
        attribute_storage=attribute_storage,attribute_storage_kinds=dict(Counter(p.kind.value for p in solver.descriptors.storage_accesses.values())),
        attribute_content=attribute_content,attribute_content_links=len(solver.descriptors.content_links),
        descriptor_implementation_sha256=sha256(Path(source_descriptors.__file__).read_bytes()).hexdigest(),
        invocation_implementation_sha256=sha256(Path(source_function_connections.__file__).read_bytes()).hexdigest(),
        constructions=constructions,construction_stages=dict(Counter(p.stage.value for p in solver.constructions.links.values())),
        construction_interface_ports=len(solver.constructions.ports),
        construction_implementation_sha256=sha256(Path(source_construction.__file__).read_bytes()).hexdigest(),
        generator_implementation_sha256=sha256(Path(source_generators.__file__).read_bytes()).hexdigest(),
        generator_types_sha256=sha256(Path(D.__file__).read_bytes()).hexdigest(),
        suspension_interface_implementation_sha256=sha256(Path(source_suspension_interfaces.__file__).read_bytes()).hexdigest(),
        suspension_interface_types_sha256=sha256(Path(S.__file__).read_bytes()).hexdigest(),
        source_reader_pins={name:sha256(Path(module.__file__).read_bytes()).hexdigest() for name,module in
            (('batch',source_template_batch),('workers',source_template_workers),('output',normal_output),
             ('interfaces',source_interface_store),('interface_types',L),
             ('content_factors',source_content_factors),('content_factor_types',C))},
        interface_summary=None if solver.interface_store is None else solver.interface_store.receipt,
        namespace_implementation_sha256=sha256(Path(normal_namespaces.__file__).read_bytes()).hexdigest(),
        namespace_types_sha256=sha256(Path(N.__file__).read_bytes()).hexdigest(),
        unresolved_calls=original_calls-len(known_calls),value_events=solver.events,frontier=len(solver.queue),event_budget=max_events,
        source_fact_ports=len(solver.port),index_entries={name:len(getattr(solver,name)) for name in
            ('adj','values','writes','reads','gets','call_watch','base_watch','classmethod_watch','dynamic_gets')},
        calls=fragment,seconds=time.monotonic()-started,conditions='source target alternatives; descriptor/module/attribute admissions remain conditional',
        runtime_dispatch_verified=False,effects_proven=False,first_stage_complete=False,target_executed=False,transformation_authorized=False,
        implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),types_sha256=sha256(Path(T.__file__).read_bytes()).hexdigest())
    result.update(content)
    result.update(source_generators.tables(solver.generators,out))
    solver.generators.validate_parents()
    result['generator_analysis']=solver.generators.stats
    if extra:result.update(extra)
    result['publication_seconds']=time.monotonic()-publish_started
    result['table_write_seconds']=table_write_seconds
    result['seconds']=time.monotonic()-started
    _durable_bytes(out/'result.json',_json(result),replace=False);return result


def solve_entry_targets(facts,out,entries,*,max_events=20_000_000,jobs=None,interfaces=None):
    from scar.analysis import normal_entry,normal_facts
    from scar.ir.program import normal_entry as E
    from scar.analysis.normal_output import write_table as _stream
    from heapq import nlargest
    started=time.monotonic();store=normal_facts.SourceFactStore(facts);out=Path(out).absolute()
    catalog_seconds=time.monotonic()-started
    if out.exists():raise ValueError('fresh entry target output required')
    entries=tuple(str(Path(p).absolute()) for p in entries)
    summaries=None if interfaces is None else source_interface_store.SourceInterfaceStore(interfaces,store)
    solver=normal_entry.EntrySolver(store,entries,jobs=jobs,interface_store=summaries);solver.prepare()
    prepared=time.monotonic()
    while (solver.queue or solver.pending) and solver.events<max_events:
        solver.solve(min(max_events,solver.events+2_000_000))
        print(json.dumps(dict(phase='ENTRY_SCOPE_PROPAGATION',events=solver.events,frontier=len(solver.queue),
            pending_scopes=len(solver.pending),active_scopes=len(solver.active_scopes),loaded_units=len(store.loaded),
            seconds=time.monotonic()-started)),file=sys.stderr,flush=True)
    propagated=time.monotonic()
    fixed=not solver.queue and not solver.pending;solver.complete_call_demands();_durable_mkdir(out)
    kinds=Counter(value[0] for values in solver.values.values() for value in values)
    hot=[]
    for point,values in nlargest(8,solver.values.items(),key=lambda item:len(item[1])):
        if type(point) is int and point>=0:
            identity,_=store.locate(point)
            hot.append(dict(port=encode(solver.gp(point),record_tags=P.PRODUCTION_RECORD_TAGS),
                source=store.rows[identity]['path'],facts=len(values),kinds=dict(Counter(v[0] for v in values))))
    known_calls={link.result for link in solver.links.values()}
    extra=dict(analysis_mode='ENTRY_SCOPED_MAY_ANALYSIS',entry_sources=entries,
        analysis_phase_seconds=dict(fact_catalog=catalog_seconds,entry_preparation=prepared-started-catalog_seconds,
            propagation=propagated-prepared),
        selected_sources=store.report['selected_sources'],loaded_sources=len(store.loaded),
        active_code_scopes=len(solver.active_scopes),pending_code_scopes=len(solver.pending),
        active_source_calls=len(solver.active_call_indices),
        source_calls=store.report['counts']['calls'],unresolved_calls=len(solver.active_call_indices)-len(known_calls),
        fixed_point_scope='ADMITTED_ENTRY_CONSTRAINTS',abstract_fact_kinds=dict(kinds),abstract_fact_hotspots=hot,
        source_catalog_retained=True,declared_source_calls=store.report['counts']['calls'],
        declared_source_functions=store.report['counts']['functions'],
        entry_activations=_stream(out/'entry-activations.jsonl.gz',solver.activations.values()),
        entry_module_demands=_stream(out/'entry-module-demands.jsonl.gz',solver.module_demands.values()),
        entry_body_demands=_stream(out/'entry-body-demands.jsonl.gz',solver.body_demands.values()),
        entry_call_demands=_stream(out/'entry-call-demands.jsonl.gz',solver.call_demands.values()),
        entry_implementation_sha256=sha256(Path(normal_entry.__file__).read_bytes()).hexdigest(),
        fact_reader_sha256=sha256(Path(normal_facts.__file__).read_bytes()).hexdigest(),
        entry_types_sha256=sha256(Path(E.__file__).read_bytes()).hexdigest())
    result=_publish(solver,store.path,store.raw,store.report,out,started,max_events,fixed,solver.stars,extra)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--facts',required=True);p.add_argument('--out',required=True)
    p.add_argument('--entry',action='append',required=True,help='source entry module; declarations alone do not choose execution roots')
    p.add_argument('--max-events',type=int,default=20_000_000)
    p.add_argument('--jobs',type=int,default=None,help='template reader processes; default min(48, CPU affinity)')
    p.add_argument('--interfaces',help='precomputed per-unit source interface store')
    p.add_argument('--stack-log',help='sample the analyzer stack every 30 seconds; no target instrumentation')
    a=p.parse_args()
    with ExitStack() as diagnostics:
        if a.stack_log:
            stream=diagnostics.enter_context(Path(a.stack_log).open('x'))
            faulthandler.dump_traceback_later(30,repeat=True,file=stream)
            diagnostics.callback(faulthandler.cancel_dump_traceback_later)
        r=solve_targets(a.facts,a.out,max_events=a.max_events,entries=a.entry,jobs=a.jobs,interfaces=a.interfaces)
    print(json.dumps({k:r[k] for k in ('status','source_calls','calls_with_candidates','candidate_links','modes','value_events','seconds')},indent=2))


if __name__=='__main__':main()
