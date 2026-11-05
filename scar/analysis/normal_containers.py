"""Reference-content constraints for source-built containers and globals.

This is a flow-insensitive may-analysis. It does not establish content versions,
constant tensor values, standard custom __getitem__, or optimization legality.
Unknown receivers remain requirements in the original item-access facts.
"""
from collections import defaultdict

from scar.ir.literals import PythonLiteral
from scar.ir.program import normal_links as F, normal_targets as T


def _key(value):
    # Python dicts compare integer and boolean keys equal.
    if type(value) is bool:value=int(value)
    return type(value).__name__,value


class ContainerFlow:
    def __init__(self,solver,units):
        self.s=solver;self.entries=defaultdict(lambda:defaultdict(set));self.readers=defaultdict(set)
        self.items=defaultdict(set);self.keys=defaultdict(set);self.updates=defaultdict(set)
        self.update_targets=defaultdict(set);self.all_readers=defaultdict(set);self.method_keys=defaultdict(set)
        self.copies=defaultdict(set);self.iterators=defaultdict(set);self.iter_sources=defaultdict(set)
        self.content_readers=defaultdict(set)
        self.links={};self.namespace_sources=defaultdict(set);self.unknown_keys=set()
        for source,namespaces in solver.writes.items():
            for namespace in namespaces:self.namespace_sources[namespace].add(source)
        for unit in units:
            o=solver.offsets[unit.unit]
            for c in unit.containers:
                value=('container',o+c.value,c.kind.value);solver.add(o+c.value,value)
                for index,element in enumerate(c.elements):self.write(value,('int',index),o+element)
                for key,element in c.pairs:self.register(o+c.value,o+key,o+element,True)
            for item in unit.items:
                self.register(o+item.receiver,o+item.key if type(item.key) is int else item.key,o+item.value,item.write)
            for update in unit.updates:
                if update.append:
                    self.items[o+update.target].add((None,o+update.source,True))
                else:self.update(o+update.source,o+update.target)
            for iteration in unit.iterations:
                if iteration.advance:self.iterators[o+iteration.source].add(o+iteration.value)
                else:solver.add(o+iteration.value,('iterator',o+iteration.source))

    def register(self,receiver,key,value,write):
        self.items[receiver].add((key,value,write))
        if type(key) is int:self.keys[key].add((receiver,value,write))

    def update(self,source,target):
        self.updates[source].add(target);self.update_targets[target].add(source)

    def link(self,source,target,container,key=None):
        if source==target:return
        self.s.edge(source,target)
        identity=(source,target,container,key)
        if identity not in self.links:
            literal=None if key is None else PythonLiteral.from_python(key[1],exact=True)
            self.links[identity]=T.ContentLink(self.s.gp(source),self.s.gp(target),self.s.gp(container),literal)

    def write(self,container,key,source):
        if source in self.entries[container][key]:return
        self.entries[container][key].add(source)
        for wanted in (key,None):
            for target in tuple(self.readers[container,wanted]):self.link(source,target,container[1],key)
        if key is None:
            for target in tuple(self.all_readers[container]):self.link(source,target,container[1])
        for target in tuple(self.iter_sources[container]):self.iterate(container,target)
        for mode,target in tuple(self.content_readers[container]):self.iterate_mode(container,target,mode)
        for target in tuple(self.copies[container]):self.copy(container,target)

    def read(self,container,key,target):
        if container[2]=='SEQUENCE' and key is not None and key[0]=='int' and key[1]<0:key=None
        if container[2]=='SET' and key is not None:return
        self.all_readers[container].add(target)
        self.readers[container,key].add(target)
        entries=self.entries[container]
        sources=entries.get(key,set())|entries.get(None,set()) if key is not None else set().union(*entries.values())
        for source in tuple(sources):self.link(source,target,container[1],key)

    def access(self,receiver,key,target,write):
        if receiver[0]=='container':
            if write:self.write(receiver,key,target)
            else:self.read(receiver,key,target)
        elif receiver[0]=='namespace_mapping':
            if key is None:
                self.unknown_keys.add((receiver[1],target,write));return
            if key[0]!='str':return
            namespace=(receiver[1],F.NamespaceKind.MODULE.value,0,key[1])
            if write:
                self.namespace_sources[namespace].add(target);self.s.writes[target].add(namespace)
                for value in tuple(self.s.values[target]):self.s.namespace_value(namespace,value)
                for reader in tuple(self.s.reads[namespace]):self.link(target,reader,receiver[2],key)
            else:
                self.s.reads[namespace].add(target)
                for value in tuple(self.s.ns_values[namespace]):self.s.add(target,value)
                for source in tuple(self.namespace_sources[namespace]):self.link(source,target,receiver[2],key)
        elif receiver[0]=='pair' and not write and key in (('int',0),('int',1)):
            if key[1]==0:self.s.add(target,('constant',receiver[2][0],receiver[2][1]))
            else:self.read(receiver[1],receiver[2],target)

    def apply_item(self,receiver,key,target,write):
        if key is None:self.access(receiver,None,target,write)
        elif type(key) is PythonLiteral:self.access(receiver,_key(key.to_python()),target,write)
        else:
            for literal in tuple(self.s.values[key]):
                if literal[0]=='constant':self.access(receiver,_key(literal[2]),target,write)
                elif literal[0] in ('external_value','external_member'):self.access(receiver,None,target,write)

    def iterate(self,container,target):
        if container[0]=='content_iterator':
            self.iterate_mode(container[1],target,container[2]);return
        if container[0]!='container':return
        self.iter_sources[container].add(target)
        if container[2]==F.ContainerKind.MAPPING.value:
            for key in tuple(self.entries[container]):
                if key is not None:self.s.add(target,('constant',key[0],key[1]))
        else:self.read(container,None,target)

    def iterate_mode(self,container,target,mode):
        self.content_readers[container].add((mode,target))
        if mode=='values':self.read(container,None,target)
        elif mode=='keys':self.iterate(container,target)
        else:
            for key in tuple(self.entries[container]):
                if key is not None:self.s.add(target,('pair',container,key))

    def copy(self,source,target):
        if source[0]!='container' or target[0]!='container':return
        self.copies[source].add(target)
        for key,sources in tuple(self.entries[source].items()):
            for point in tuple(sources):
                if target[2]==F.ContainerKind.MAPPING.value and source[2]==target[2]:self.write(target,key,point)
                elif source[2]!=F.ContainerKind.MAPPING.value:self.write(target,None,point)

    def consume(self,point,value):
        for key,target,write in tuple(self.items[point]):self.apply_item(value,key,target,write)
        for receiver,target,write in tuple(self.keys[point]):
            for container in tuple(self.s.values[receiver]):self.apply_item(container,point,target,write)
        for target in tuple(self.updates[point]):
            for container in tuple(self.s.values[target]):self.copy(value,container)
        # A target can become known after its copy source.
        if value[0]=='container':
            for source in tuple(self.update_targets[point]):
                for container in tuple(self.s.values[source]):self.copy(container,value)
        for target in tuple(self.iterators[point]):
            if value[0]=='iterator':
                self.iter_sources[value[1]].add(target)
                for container in tuple(self.s.values[value[1]]):self.iterate(container,target)
        for target in tuple(self.iter_sources[point]):self.iterate(value,target)
        for container,target in tuple(self.method_keys[point]):self.apply_item(container,point,target,False)

    def attribute(self,value,name,target):
        if value[0]=='container' and name in ('get','update','append','extend','keys','values','items'):
            self.s.add(target,('container_method',value,name))

    def call(self,unit,call,value):
        container,name=value[1:];o=self.s.offsets[unit.unit];result=o+call.result
        if name in ('keys','values','items') and container[2]=='MAPPING':
            self.s.add(result,('content_iterator',container,name))
        elif name=='get' and container[2]=='MAPPING' and call.positional:
            key=o+call.positional[0];self.method_keys[key].add((container,result))
            self.apply_item(container,key,result,False)
            if len(call.positional)>1:self.link(o+call.positional[1],result,container[1])
            else:self.s.add(result,('constant','NoneType',None))
        elif name=='append' and container[2]=='SEQUENCE' and call.positional:
            self.write(container,None,o+call.positional[0])
        elif name in ('extend','update') and call.positional:
            source=o+call.positional[0];self.update(source,container[1])
            for value in tuple(self.s.values[source]):self.copy(value,container)
        if name=='update' and container[2]=='MAPPING':
            for key,point in call.keywords:self.write(container,('str',key),o+point)

    def external(self,unit,call,name):
        o=self.s.offsets[unit.unit];result=o+call.result
        if name=='builtins.globals' and not call.positional and call.positional_pack is None:
            self.s.add(result,('namespace_mapping',unit.unit,result))
        elif name in ('builtins.dict','builtins.list','builtins.tuple','builtins.set'):
            kind='MAPPING' if name.endswith('.dict') else 'SET' if name.endswith('.set') else 'SEQUENCE'
            container=('container',result,kind);self.s.add(result,container)
            if call.positional:
                source=o+call.positional[0];self.update(source,result)
                for value in tuple(self.s.values[source]):self.copy(value,container)
            if kind=='MAPPING':
                for key,value in call.keywords:self.write(container,('str',key),o+value)
