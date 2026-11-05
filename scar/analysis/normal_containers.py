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
        self.iteration_sites=defaultdict(list);self.iteration_site_keys=set();self.iterator_getters=defaultdict(set)
        self.followed_iterators=set()
        self.links={};self.namespace_sources=defaultdict(set);self.unknown_keys=set()
        # Shape witnesses use original construction facts, never the size or
        # contents of the flow-insensitive entries map.
        self.pack_units={};self.pack_reverse=defaultdict(set);self.pack_constructors={}
        self.pack_constants={};self.pack_blocked=set();self.pack_updates={};self.pack_writes={}
        self.pack_escapes={};self.pack_merge_proofs={};self.pack_origins={}
        self.pack_watch=defaultdict(set);self.pending_invocations={}
        self.variadic_origins=defaultdict(dict);self.variadic_prefixes=defaultdict(dict);self.open_containers=set()
        self.argument_projections=defaultdict(set);self.remainder_projections=defaultdict(set)
        for source,namespaces in solver.writes.items():
            for namespace in namespaces:self.namespace_sources[namespace].add(source)
        for unit in units:
            for table in ('containers','items','updates','iterations'):
                for i in range(len(getattr(unit,table))):self.admit(unit,table,i)

    def admit(self,unit,table,index):
        self._index_pack_unit(unit)
        o=self.s.offsets[unit.unit];item=getattr(unit,table)[index]
        if table=='containers':
            value=('container',o+item.value,item.kind.value);self.s.add(o+item.value,value)
            for i,element in enumerate(item.elements):self.write(value,('int',i),o+element)
            for key,element in item.pairs:self.register(o+item.value,o+key,o+element,True)
        elif table=='items':
            self.register(o+item.receiver,o+item.key if type(item.key) is int else item.key,o+item.value,item.write)
            for value in tuple(self.s.values.get(o+item.receiver,())):
                self.apply_item(value,o+item.key if type(item.key) is int else item.key,o+item.value,item.write)
        elif table=='updates':
            if item.append:self.items[o+item.target].add((None,o+item.source,True))
            else:self.update(o+item.source,o+item.target)
            for value in tuple(self.s.values.get(o+item.target if item.append else o+item.source,())):
                self.consume(o+item.target if item.append else o+item.source,value)
        elif table=='iterations':
            identity=unit.unit,item
            if identity not in self.iteration_site_keys:
                self.iteration_site_keys.add(identity);self.iteration_sites[o+item.value].append((unit,item))
            if item.advance:
                self.iterators[o+item.source].add(o+item.value)
                for value in tuple(self.s.values.get(o+item.source,())):self.consume(o+item.source,value)
            else:
                self.iterator_getters[o+item.source].add(o+item.value)
                self.s.add(o+item.value,('iterator',o+item.source))
                if hasattr(self.s,'generators'):
                    for value in tuple(self.s.values.get(o+item.source,())):self.s.generators.get_iterator(value,o+item.value)
        else:raise ValueError('unknown container fact table')

    def bind_variadic(self,formal,route,actuals,names,origin=None):
        """Create the formal tuple/dict abstraction, including empty packs.

        A formal can receive many invocations. Entries are a may-union; each
        binding's separate ordered witness is retained for later refinements.
        No element is an alias of the tuple/dict object itself.
        """
        mapping=route is T.RouteKind.PACK_KEYWORDS
        container=('container',formal,'MAPPING' if mapping else 'SEQUENCE')
        witness=(container[2],tuple(actuals),tuple(names))
        if type(origin) is tuple and origin and origin[0]=='SYMBOLIC_PACK_PREFIX':
            self.variadic_prefixes[formal][origin]=witness;self.open_containers.add(container)
        else:self.variadic_origins[formal][origin]=witness
        self.s.add(formal,container)
        for index,point in enumerate(actuals):
            self.write(container,('str',names[index]) if mapping else ('int',index),point)

    def project_argument(self,formal,pack,kind,index=None,name=None,excluded_names=()):
        """Subscribe to possible elements, never alias the pack to its formal.

        Closed shape admission is separate. These constraints describe the
        original call only under signature acceptance and source-selection
        conditions published by FunctionConnection.ArgumentProjection.
        """
        spec=(formal,kind,index,name,tuple(excluded_names))
        if spec in self.argument_projections[pack]:return
        self.argument_projections[pack].add(spec)
        if kind in (T.ProjectionKind.POSITIONAL_TAIL,T.ProjectionKind.KEYWORD_REMAINDER):
            container=('container',formal,'SEQUENCE' if kind is T.ProjectionKind.POSITIONAL_TAIL else 'MAPPING')
            self.open_containers.add(container);self.s.add(formal,container)
        for value in tuple(self.s.values.get(pack,())):self.project_value(value,spec)

    def project_value(self,value,spec):
        formal,kind,index,name,excluded=spec
        scalar=kind in (T.ProjectionKind.POSITIONAL_ITEM,T.ProjectionKind.KEYWORD_ITEM)
        if value[0]!='container':
            if scalar and value[0] in ('external_value','external_member'):
                self.s.add(formal,('external_value',None))
            return
        sequence=kind in (T.ProjectionKind.POSITIONAL_ITEM,T.ProjectionKind.POSITIONAL_TAIL)
        if value[2]!=('SEQUENCE' if sequence else 'MAPPING'):return
        if scalar:
            self.read(value,('int',index) if sequence else ('str',name),formal)
            if value in self.open_containers:self.s.add(formal,('external_value',None))
        else:
            self.remainder_projections[value].add(spec)
            for key,sources in tuple(self.entries[value].items()):
                for source in tuple(sources):self.project_remainder(value,key,source,spec)

    def project_remainder(self,container,key,source,spec):
        formal,kind,index,name,excluded=spec
        sequence=kind is T.ProjectionKind.POSITIONAL_TAIL
        if sequence:
            if key is not None and (key[0]!='int' or key[1]<index):return
            selected=None if key is None else ('int',key[1]-index)
        else:
            if key is not None and (key[0]!='str' or key[1] in excluded):return
            selected=key
        target=('container',formal,'SEQUENCE' if sequence else 'MAPPING')
        self.write(target,selected,source)

    def _index_pack_unit(self,unit):
        if unit.unit in self.pack_units:return
        self.pack_units[unit.unit]=unit;o=self.s.offsets[unit.unit]
        for source,target in unit.aliases:self.pack_reverse[o+target].add(o+source)
        for item in unit.containers:self.pack_constructors[o+item.value]=(unit,item)
        for item in unit.constants:self.pack_constants[o+item.value]=item.literal
        self.pack_blocked.update(o+item.value for item in unit.names if not item.write)
        self.pack_blocked.update(o+item.value for item in unit.attributes
            if item.action in (F.AttributeAction.GET,F.AttributeAction.IMPORT_MEMBER))
        self.pack_blocked.update(o+item.value for item in unit.items if not item.write)
        self.pack_blocked.update(o+item.result for item in unit.calls)
        self.pack_blocked.update(o+formal for f in unit.functions for formal in f.formals)
        self.pack_updates[unit.unit]=tuple((o+x.target,o+x.source,x.append) for x in unit.updates)
        self.pack_writes[unit.unit]=tuple(o+x.receiver for x in unit.items if x.write)
        self.pack_escapes[unit.unit]=tuple(o+x.value for x in unit.names if x.write)

    def _pack_origin(self,point,seen=frozenset()):
        if point in self.pack_constructors or point in self.pack_constants:return point
        if point in self.pack_origins:return self.pack_origins[point]
        if point in seen or point in self.pack_blocked:return None
        sources=self.pack_reverse.get(point,())
        origins={self._pack_origin(p,seen|{point}) for p in sources}
        origin=next(iter(origins)) if len(origins)==1 and None not in origins else None
        self.pack_origins[point]=origin
        return origin

    def _merge_proof(self,unit,point):
        """Admit only original straight-line DICT_MERGE construction steps.

        F5 intentionally omits the mutation opcode. Recover that discriminator
        from its sealed F4 parent rather than interpreting a generic update as
        a complete dictionary or deriving key closure from observed contents.
        """
        from scar.ir.program import normal_graph as G,source_productions as P
        from scar.ir.program.structured import PythonProtocolKind as K
        from scar.ir.record_codec import decode
        from scar.analysis.normal_graph import _Emitter
        o=self.s.offsets[unit.unit];wire=unit.ports[point-o]
        port=decode(G.Port,wire,record_tags=P.PRODUCTION_RECORD_TAGS) if type(wire) is dict else wire
        cache=unit.unit,port.template
        if cache not in self.pack_merge_proofs:
            proof=set();store=getattr(self.s,'store',None)
            if store is not None:
                # Share the sealed plan cache with generator/iteration
                # interfaces rather than decoding the same unit independently.
                plan=self.s.generators.index()._plan(unit,port.template)[0]
                if all(step.region==plan.root for step in plan.steps):
                    emitter=_Emitter(plan,port.template,{})
                    points={}
                    for index,raw in enumerate(unit.ports):
                        if type(raw) is dict:
                            key=raw['template']
                            if (key['occurrence'],key['purpose'])!=(port.template.occurrence,port.template.purpose.value):continue
                            raw=decode(G.Port,raw,record_tags=P.PRODUCTION_RECORD_TAGS)
                        if raw.template==port.template:points[raw]=o+index
                    for step in plan.steps:
                        ins=step.instruction
                        if type(ins) is P.ApplyPythonProtocol and ins.protocol is K.DICT_MERGE:
                            target=points.get(emitter.value(step.arguments[1])[0])
                            source=points.get(emitter.value(step.arguments[2])[0])
                            if target is not None and source is not None:proof.add((target,source))
            self.pack_merge_proofs[cache]=proof
        return self.pack_merge_proofs[cache]

    def _closed_pack(self,point,kind,seen=frozenset()):
        origin=self._pack_origin(point)
        if origin is None or origin in seen or origin not in self.pack_constructors:return None
        unit,item=self.pack_constructors[origin];o=self.s.offsets[unit.unit]
        container=('container',origin,kind)
        if item.kind.value!=kind or container in self.open_containers:return None
        # A saved/merged namespace reference or a write prevents this fresh
        # expression from being used as an immutable construction witness.
        if any(self._pack_origin(p)==origin for p in (*self.pack_escapes[unit.unit],*self.pack_writes[unit.unit])):return None
        updates=[(target,source,append) for target,source,append in self.pack_updates[unit.unit]
                 if self._pack_origin(target)==origin]
        if kind=='SEQUENCE':
            if updates:return None
            return tuple(o+p for p in item.elements),origin
        pairs={}
        for key,value in item.pairs:
            literal=self.pack_constants.get(self._pack_origin(o+key))
            if literal is None:return None
            name=literal.to_python()
            if type(name) is not str:return None
            pairs[name]=o+value
        if updates:
            proof=self._merge_proof(unit,origin)
            for target,source,append in updates:
                if append or (target,source) not in proof:return None
                merged=self._closed_pack(source,'MAPPING',seen|{origin})
                if merged is None:return None
                for name,value in merged[0]:
                    if name in pairs:return None
                    pairs[name]=value
        return tuple(pairs.items()),origin

    def invocation_arguments(self,invocation):
        """Return arguments only with a closed original-construction witness.

        Value arrival is a readiness/pollution check. It never supplies arity,
        key completeness, equality or a last-write interpretation.
        """
        for unit in self.s.units:self._index_pack_unit(unit)
        positional=list(invocation.positional);keywords=list(invocation.keywords)
        for point,kind in ((invocation.positional_pack,'SEQUENCE'),(invocation.keyword_pack,'MAPPING')):
            if point is None:continue
            closed=self._closed_pack(point,kind)
            if closed is None:return None
            contents,origin=closed;expected=('container',origin,kind)
            values=self.s.values.get(point,())
            if expected not in values or any(value!=expected for value in values):return None
            if kind=='SEQUENCE':positional.extend(contents)
            else:keywords.extend(contents)
        return tuple(positional),tuple(keywords)

    def watch_invocation(self,key,invocation,retry):
        self.pending_invocations.setdefault(key,retry)
        for point in (invocation.positional_pack,invocation.keyword_pack):
            if point is not None:self.pack_watch[point].add(key)

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
        for spec in tuple(self.remainder_projections.get(container,())):
            self.project_remainder(container,key,source,spec)

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
        if container[0]=='source_deferred':
            self.s.generators.advance(container,target);return
        if container[0]=='iterator':
            key=container,target
            if key in self.followed_iterators:return
            self.followed_iterators.add(key);self.iter_sources[container[1]].add(target)
            for value in tuple(self.s.values.get(container[1],())):self.iterate(value,target)
            return
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
        if target[0]!='container':return
        if source[0]=='source_deferred' and hasattr(self.s,'generators'):
            self.s.generators.obligation(self.s.generators.creations[source[1]].origin,
                'CONTAINER_CONSUMER_ITERATOR_DRIVER_REQUIRED',self.s.gp(target[1]));return
        if source[0]!='container' or target[0]!='container':return
        self.copies[source].add(target)
        for key,sources in tuple(self.entries[source].items()):
            for point in tuple(sources):
                if target[2]==F.ContainerKind.MAPPING.value and source[2]==target[2]:self.write(target,key,point)
                elif source[2]!=F.ContainerKind.MAPPING.value:self.write(target,None,point)

    def consume(self,point,value):
        if hasattr(self.s,'generators'):
            for target in tuple(self.iterator_getters.get(point,())):self.s.generators.get_iterator(value,target)
        for spec in tuple(self.argument_projections.get(point,())):self.project_value(value,spec)
        for key,target,write in tuple(self.items.get(point,())):self.apply_item(value,key,target,write)
        for receiver,target,write in tuple(self.keys.get(point,())):
            for container in tuple(self.s.values[receiver]):self.apply_item(container,point,target,write)
        for target in tuple(self.updates.get(point,())):
            for container in tuple(self.s.values[target]):self.copy(value,container)
        # A target can become known after its copy source.
        if value[0]=='container':
            for source in tuple(self.update_targets.get(point,())):
                for container in tuple(self.s.values[source]):self.copy(container,value)
        for target in tuple(self.iterators.get(point,())):
            if value[0]=='iterator':
                self.iter_sources[value[1]].add(target)
                for container in tuple(self.s.values[value[1]]):self.iterate(container,target)
            elif value[0]=='source_deferred':self.s.generators.advance(value,target)
        for target in tuple(self.iter_sources.get(point,())):self.iterate(value,target)
        for container,target in tuple(self.method_keys.get(point,())):self.apply_item(container,point,target,False)
        for key in tuple(self.pack_watch.get(point,())):
            retry=self.pending_invocations.get(key)
            if retry is not None and retry():
                self.pending_invocations.pop(key,None)
                for watched in (key[1].positional_pack,key[1].keyword_pack):
                    if watched is not None:self.pack_watch[watched].discard(key)

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
            self.open_containers.add(container)
            self.write(container,None,o+call.positional[0])
        elif name in ('extend','update') and call.positional:
            self.open_containers.add(container)
            source=o+call.positional[0];self.update(source,container[1])
            for value in tuple(self.s.values[source]):self.copy(value,container)
        if name=='update' and container[2]=='MAPPING':
            self.open_containers.add(container)
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
