"""Conditional import/module-field provenance over immutable original ports.

No module is imported or initialized here. A source-module namespace is a
conditional interpretation of an import result, never that Python object's ID.
"""
from __future__ import annotations

import ast
from collections import OrderedDict, defaultdict
from dataclasses import replace

from scar.ir.record_codec import decode
from scar.ir.program.ids import OperationID
from scar.ir.program.model import (BlockArgument, CompletionResult, ExitKind, LiteralOrigin,
    ReferenceValue, LocalBindingValue, StateVersionValue, TerminatorKind)
from scar.ir.program.source import LoweringMetadata
from scar.ir.program.static_calls import (StaticCallFrontier, StaticImportModuleRoute,
    StaticModuleAttributeFlow, StaticQualifiedNamespaceFlow, StaticReferencePoint,
    StaticReferenceSourcePath)
from scar.ir.program.structured import ControlEdgeReference
from scar.analysis.static_namespace import normal_reference, protocol_kinds


def _need(value, detail):
    if not value: raise ValueError('static module provenance: ' + detail)


def _requirements(point):
    point.__post_init__()


def _world(body, operation):
    op=body.index.operations[operation]
    uses=[u for u in op.uses if type(body.index.values[u.value]) is StateVersionValue]
    _need(len(uses)==1, 'operation has no unique original world Use')
    return uses[0]


def _normal(body, operation):
    op=body.index.operations[operation]
    _need(op.terminator is not None and op.terminator.kind is TerminatorKind.INVOKE,
          'protocol has no original invoke')
    rows=[ControlEdgeReference(op.id,n) for n,e in enumerate(op.terminator.successors) if e.kind is ExitKind.NORMAL]
    _need(len(rows)==1,'protocol has no unique original normal edge')
    return rows[0]


def _local_parents(body, value):
    """Only true binding and ordinary phi operands; never generic op inputs."""
    for read in body.graph.binding_reads:
        if read.normal_result==value:
            return (body.index.use_site(read.binding).use.value,)
    for binding in body.graph.binding_definitions:
        if binding.value==value and binding.payload is not None:
            return (body.index.use_site(binding.payload).use.value,)
    origin=body.index.values[value].origin
    if type(origin) is BlockArgument:
        parents=[]
        for op in body.graph.operations:
            term=op.terminator
            if term is None or term.kind not in (TerminatorKind.JUMP,TerminatorKind.BRANCH):continue
            for edge in term.successors:
                if edge.block==origin.block and origin.index<len(edge.arguments):
                    actual=edge.arguments[origin.index]
                    if type(actual) is not CompletionResult:
                        parents.append(body.index.use_site(actual).use.value)
        return tuple(dict.fromkeys(parents))
    return ()


def _merge_path(path, point, *, namespace_flows=(), cross_body_namespace_flows=(),
                argument_flows=(),return_flows=(),module_attribute_flows=()):
    if point in path.points:return None
    changes={name:tuple(dict.fromkeys((*getattr(path,name),*new))) for name,new in (
        ('namespace_flows',namespace_flows),('cross_body_namespace_flows',cross_body_namespace_flows),
        ('argument_flows',argument_flows),('return_flows',return_flows),
        ('module_attribute_flows',module_attribute_flows))}
    return replace(path,points=(*path.points,point),**changes)


class ModuleAttributeDependencies:
    """Per-analysis bounded original-body indexes and derived value relations.

    ``module_bodies(name)`` selects only snapshot-qualified source candidates.
    ``reference_sources`` supplies the existing qualified argument/return/G
    relations. Neither callback executes an import or a target function.
    """
    def __init__(self, *, load_body, source_context, module_bodies, namespace_for,
                 reference_sources=None, max_steps=4096, max_facts=262144, check=None,
                 external_fact_count=None, max_cached_bytes=64_000_000):
        self.load_body,self.source_context,self.module_bodies=load_body,source_context,module_bodies
        self.namespace_for,self.reference_sources=namespace_for,reference_sources
        self.max_steps,self.max_facts=max_steps,max_facts;self.check=check or(lambda:None)
        self.external_fact_count=external_fact_count or(lambda:0)
        self.max_cached_bytes=max_cached_bytes;self._fact_count=0
        self._facts=OrderedDict();self._active=set()
        self.import_routes=defaultdict(dict);self.flows=defaultdict(dict);self.frontiers=defaultdict(dict)
        self.attribute_counts={};self.analyzed_reads=set()
        # Static interface/source-scope notes survive all demand refinements.
        # Demand notes are replaced only after this exact qualified read and
        # context finish recomputation; an in-flight attempt has its own map.
        self._permanent_frontiers=defaultdict(dict)
        self._read_frontiers={};self._read_frontiers_by_body=defaultdict(dict)
        self._pending_read_frontiers={}

    @property
    def fact_count(self):return self._fact_count

    def _project_frontiers(self,namespace):
        rows=dict(self._permanent_frontiers.get(namespace,{}))
        for notes in self._read_frontiers_by_body.get(namespace,{}).values():rows.update(notes)
        self.frontiers[namespace]=rows

    def _replace_read_frontiers(self,point,notes):
        self._read_frontiers[point]=notes
        self._read_frontiers_by_body[point.body][point]=notes
        self._project_frontiers(point.body)

    def _note(self,body,kind,detail,source=None,*,demand=None):
        row=StaticCallFrontier(kind,detail,source)
        if demand is None:
            self._permanent_frontiers[body.namespace][row]=row
            self._project_frontiers(body.namespace)
        else:
            _need(type(demand)is StaticReferencePoint and demand.body==body.namespace,
                  'demand frontier must retain its exact original read/context namespace')
            pending=self._pending_read_frontiers.get(demand)
            if pending is not None:
                pending[row]=row
            else:
                # A refusal before entering the read (e.g. depth budget) must
                # append evidence while retaining an earlier completed result.
                notes=dict(self._read_frontiers.get(demand,{}));notes[row]=row
                self._replace_read_frontiers(demand,notes)

    def _body(self,namespace):
        body=self.load_body(namespace)
        _need(body is not None and body.namespace==namespace,'body loader relabeled an original namespace')
        return body

    def _index(self,body):
        key=body.namespace
        saved=self._facts.get(key)
        if saved is not None and saved[0] is body.graph and saved[1] is body.document:
            self._facts.move_to_end(key);return saved[2]
        from types import SimpleNamespace
        from scar.analysis.static_fields import derive_attribute_accesses,FieldCFGPaths
        tree,semantic,text=self.source_context(body)
        module=None
        if body.document.get('module') is not None:
            from scar.ir.program.module_entries import decode_frame_body
            module=decode_frame_body(body.document['module'])
        metadata=decode(LoweringMetadata,body.document['metadata'])
        links=module.operation_links if module is not None else metadata.operation_links
        by_source=defaultdict(list)
        for node in ast.walk(tree):
            # This index serves plain-import occurrences only. Source metadata
            # such as TypeIgnore has a line but no expression end/column; it
            # stays in the retained AST without becoming an executable import.
            if isinstance(node,ast.Import):
                by_source[(type(node).__name__,node.lineno,node.end_lineno,node.col_offset,node.end_col_offset)].append(node)
        protocols=protocol_kinds(body.document)
        imports=[];normal_producers={}
        blocks={block.id:block for region in body.graph.regions for block in region.blocks}
        for op in body.graph.operations:
            result=normal_reference(body.index,op.id,blocks=blocks)
            if result is not None:normal_producers[result[1]]=op.id
            if protocols.get(op.id) in ('IMPORT_NAME_314','FUNCTION_IMPORT_NAME'):
                own=[l for l in links if l.operation==op.id]
                _need(len(own)==1,'import protocol lost its original source link')
                source=own[0].source
                nodes=by_source.get(('Import',source.start_line,source.end_line,source.start_column,source.end_column),())
                if len(nodes)!=1:
                    self._note(body,'IMPORT_MODULE_VALUE_PROTOCOL_OPEN',
                        'ImportFrom/submodule-result protocols retain their own source; no plain-import alias is invented.',source)
                    continue
                imports.append((op,source,nodes[0]))
        grouped=defaultdict(list)
        for op,source,node in imports:grouped[source].append(op.id)
        aliases={op.id:(node,source,grouped[source].index(op.id))for op,source,node in imports}
        accesses=derive_attribute_accesses(body,source_text=text,semantic=semantic)
        self.attribute_counts[body.namespace]=(sum(a.result is not None for a in accesses),
            sum(a.assigned is not None for a in accesses))
        result=SimpleNamespace(module=module,metadata=metadata,links=links,protocols=protocols,
            imports=aliases,normal_producers=normal_producers,accesses=accesses,
            reads={a.result:a for a in accesses if a.result is not None},
            writes=tuple(a for a in accesses if a.assigned is not None),
            paths=FieldCFGPaths(body,max_steps=self.max_steps,check=self.check))
        self._facts[key]=(body.graph,body.document,result);self._facts.move_to_end(key)
        while (len(self._facts)>16 or sum(n.graph.decoded_bytes for n in self._facts)>self.max_cached_bytes):
            self._facts.popitem(last=False)
        return result

    def imports_for_result(self,body,value,requirements=()):
        StaticReferencePoint(body.namespace,value,requirements)
        facts=self._index(body);operation=facts.normal_producers.get(value)
        selected=facts.imports.get(operation)
        if selected is None:return ()
        node,source,ordinal=selected
        _need(ordinal<len(node.names),'import ordinal exceeds exact source aliases')
        alias=node.names[ordinal]
        op=body.index.operations[operation]
        operands=[u for u in op.uses if type(body.index.values[u.value]) is not StateVersionValue]
        offset=3 if facts.protocols[operation]=='IMPORT_NAME_314' else 2
        _need(len(operands)==offset+4,'import protocol has unexpected original argument layout')
        def literal(use):
            origin=body.index.values[use.value].origin
            _need(type(origin)is LiteralOrigin,'import argument is not its original literal')
            return origin.value
        _need(literal(operands[offset])==alias.name and literal(operands[offset+1])==0
              and literal(operands[offset+2]) is None and literal(operands[offset+3])=='__import__',
              'import alias/requested/level/fromlist differs from original source')
        returned=alias.name.split('.')[0];rows=[]
        for module in self.module_bodies(returned):
            mf=self._index(module)
            if mf.module is None:continue
            frame=module.graph.frame_roots[0].entry
            route=StaticImportModuleRoute(body.namespace,operation,source,ordinal,alias.name,returned,
                _world(body,operation).id,_normal(body,operation),value,module.namespace,
                frame.locals_namespace,frame.globals_namespace,frame.world,requirements)
            self._admit(self.import_routes[body.namespace],route)
            rows.append(route)
        if not rows:
            self._note(body,'IMPORT_MODULE_SOURCE_BODY_UNAVAILABLE',
                'No supplied canonical source module matches this import result candidate; import hooks/cache and missing source remain open.',source)
        return tuple(rows)

    def _admit(self,table,row):
        if row in table:return
        if self._fact_count+self.external_fact_count()>=self.max_facts:
            raise OverflowError('shared qualified/module provenance fact budget exhausted before admission')
        table[row]=row;self._fact_count+=1

    def walk(self,body,value,requirements=(),requester=None):
        first=StaticReferencePoint(body.namespace,value,requirements)
        pending=[(body,StaticReferenceSourcePath((first,)))];seen=set()
        while pending:
            self.check();current,path=pending.pop();point=path.points[-1]
            if point in seen:continue
            seen.add(point)
            if len(seen)>self.max_steps:raise OverflowError('module reference-source traversal budget exhausted')
            yield current,path
            for parent in _local_parents(current,point.value):
                next_path=_merge_path(path,StaticReferencePoint(point.body,parent,point.requirements))
                if next_path is not None:pending.append((current,next_path))
            dependencies=self.namespace_for(current)
            for flow in dependencies.flows(point.value):
                dependencies.validate(flow)
                parent=current.index.use_site(flow.assigned_reference).use.value
                next_path=_merge_path(path,StaticReferencePoint(point.body,parent,point.requirements),
                    namespace_flows=(StaticQualifiedNamespaceFlow(point.body,flow),))
                if next_path is not None:pending.append((current,next_path))
            if self.reference_sources is not None:
                for inherited in self.reference_sources(current,point.value,point.requirements,requester):
                    source=self._body(inherited.body_namespace)
                    next_path=_merge_path(path,StaticReferencePoint(inherited.body_namespace,inherited.value,inherited.requirements),
                        cross_body_namespace_flows=inherited.crossflows,argument_flows=inherited.argflows,
                        return_flows=inherited.returnflows)
                    if next_path is not None:pending.append((source,next_path))
            for flow in self.sources(current,point.value,point.requirements,requester):
                source=self._body(flow.source_body)
                next_path=_merge_path(path,StaticReferencePoint(flow.source_body,flow.source_value,flow.source_requirements),
                    module_attribute_flows=(flow,))
                if next_path is not None:pending.append((source,next_path))

    def receiver_routes(self,body,value,requirements=(),requester=None):
        rows=[]
        for current,path in self.walk(body,value,requirements,requester):
            point=path.points[-1]
            rows.extend((route,path) for route in self.imports_for_result(current,point.value,point.requirements))
        return tuple(dict.fromkeys(rows))

    def _same_import(self,left,right):
        return (left.body,left.operation,left.result,left.module_body,left.requirements)==(
            right.body,right.operation,right.result,right.module_body,right.requirements)

    def _write_routes(self,body,read,route,requirements,requester):
        rows=[]
        for write in self._index(body).writes:
            if write.field!=read.field:continue
            receiver=body.index.use_site(write.receiver).use.value
            found=self.receiver_routes(body,receiver,requirements,requester)
            if not found:continue
            # An ambiguous receiver may denote another module. It cannot
            # strongly kill this namespace's initializer definition.
            matches=[(r,p)for r,p in found if self._same_import(r,route)]
            if matches and len(matches)==len(found):rows.extend((write,p)for r,p in matches)
        return tuple(rows)

    def sources(self,body,value,requirements=(),requester=None):
        point=StaticReferencePoint(body.namespace,value,requirements)
        facts=self._index(body);read=facts.reads.get(value)
        if read is None:return ()
        if point in self._active:
            self._note(body,'RECURSIVE_MODULE_VALUE_SOURCE_OPEN',
                'A source-property cycle cannot establish its own import/module reference.',read.source,demand=point)
            return ()
        if len(self._active)>=64:
            self._note(body,'MODULE_SOURCE_DEPTH_BUDGET',
                'Nested module property provenance reached its explicit finite depth budget.',read.source,demand=point)
            return ()
        self._active.add(point)
        self.analyzed_reads.add(point)
        previous_frontiers=dict(self._read_frontiers.get(point,{}))
        self._pending_read_frontiers[point]={}
        try:
            outputs=[];receiver=body.index.use_site(read.receiver).use.value
            routes=self.receiver_routes(body,receiver,requirements,requester)
            if not routes:
                self._note(body,'MODULE_ATTRIBUTE_RECEIVER_UNCONNECTED',
                    'Original ATTRIBUTE field/receiver/world/result are known. This module-origin relation '
                    'has no connected import source in this context; other object kinds or native contracts '
                    'may apply. This does not mark the ATTRIBUTE structure missing.',read.source,demand=point)
            for route,receiver_path in routes:
                writes=self._write_routes(body,read,route,requirements,requester)
                kills={w.operation for w,p in writes}
                for write,write_path in writes:
                    start=body.index.operations[write.operation].terminator.successors[write.normal.successor_index].block
                    path=facts.paths.find_path(start,read.operation,read.field,kills)
                    if path is None:continue
                    payload=body.index.use_site(write.assigned).use.value
                    flow=StaticModuleAttributeFlow(read,route,receiver_path,body.namespace,write.operation,
                        write.receiver,write.assigned,write.world,write.normal,payload,None,
                        read.operation,read.world,(),(),*path,write,write_path,requirements,requirements)
                    flow=replace(flow,overwrites=tuple(w for w,p in writes),
                        overwrite_receiver_paths=tuple(p for w,p in writes))
                    self._admit(self.flows[body.namespace],flow);outputs.append(flow)
                if route.body==body.namespace:
                    start=body.index.operations[route.operation].terminator.successors[route.normal.successor_index].block
                else:start=body.index.regions[body.graph.root].entry
                path=facts.paths.find_path(start,read.operation,read.field,kills)
                if path is None:continue
                module=self._body(route.module_body);mf=self._index(module)
                if any('REQUIRED_EXPANSION' in f.kind for f in mf.module.frontiers):
                    self._note(body,'SOURCE_MODULE_INITIALIZER_PARTIAL',
                        'Selected source module retains an unexpanded suffix; no complete initialized-namespace snapshot is invented.',read.source,demand=point)
                    continue
                dependencies=self.namespace_for(module)
                for terminal in module.graph.operations:
                    if (terminal.terminator is None or terminal.terminator.kind is not TerminatorKind.RETURN
                            or mf.paths.owners[terminal.id][0]!=module.graph.root):
                        continue
                    worlds=[u for u in terminal.uses if type(module.index.values[u.value])is StateVersionValue]
                    if len(worlds)!=1:continue
                    world=worlds[0]
                    for binding in dependencies.bindings_at(route.locals_namespace,read.field,terminal.id,world.id):
                        dependencies.validate_binding(binding);write=binding.write
                        payload=module.index.use_site(write.payload).use.value
                        flow=StaticModuleAttributeFlow(read,route,receiver_path,module.namespace,write.operation,
                            write.owners[0],write.payload,write.world,write.normal_edge,payload,write.keys[0],
                            terminal.id,world.id,binding.path,binding.intervening_operations,*path,
                            requirements=requirements,source_requirements=())
                        flow=replace(flow,overwrites=tuple(w for w,p in writes),
                            overwrite_receiver_paths=tuple(p for w,p in writes))
                        self._admit(self.flows[body.namespace],flow);outputs.append(flow)
                self._note(body,'MODULE_STATE_AND_ATTRIBUTE_CONTRACT_OPEN',
                    'Module source/normal snapshot and current attribute ports are conditionally joined; cached imports, custom lookup, external/cross-body mutation and intervening effects remain unproved.',read.source,demand=point)
            result=tuple(dict.fromkeys(outputs))
            self._replace_read_frontiers(point,self._pending_read_frontiers[point])
            return result
        except BaseException as error:
            kind=('MODULE_READ_TIME_BUDGET_INTERRUPTED'if isinstance(error,TimeoutError)else
                  'MODULE_READ_FACT_OR_TRAVERSAL_BUDGET_INTERRUPTED'if isinstance(error,OverflowError)else
                  'MODULE_READ_ANALYSIS_INTERRUPTED')
            self._note(body,kind,
                'Read-demand recomputation did not complete ('+type(error).__name__+': '+str(error)+
                '); previous frontiers and this attempt\'s pending evidence are retained.',read.source,demand=point)
            retained=previous_frontiers
            retained.update(self._pending_read_frontiers[point])
            self._replace_read_frontiers(point,retained)
            raise
        finally:
            del self._pending_read_frontiers[point]
            self._active.remove(point)

    def collect_body(self,body,requirements=(),requester=None):
        facts=self._index(body)
        for value in facts.normal_producers:
            self.imports_for_result(body,value,requirements)
        for value in facts.reads:self.sources(body,value,requirements,requester)


def validate_reference_source_path(path, *, load_body, namespace_for, check_support):
    path.__post_init__()
    for flow in path.namespace_flows:
        namespace_for(load_body(flow.body)).validate(flow.flow)
    for flow in (*path.cross_body_namespace_flows,*path.argument_flows,*path.return_flows,*path.module_attribute_flows):
        check_support(flow)
    for before,after in zip(path.points,path.points[1:]):
        left,right=load_body(before.body),load_body(after.body)
        _need(type(left.index.values.get(before.value))in(ReferenceValue,LocalBindingValue)
              and type(right.index.values.get(after.value))in(ReferenceValue,LocalBindingValue),
              'reference path endpoint is not an original reference')
        if (before.body==after.body and before.requirements==after.requirements
                and after.value in _local_parents(left,before.value)):continue
        matched=False
        for qualified in path.namespace_flows:
            flow=qualified.flow
            if (qualified.body==before.body==after.body and before.requirements==after.requirements
                    and flow.read_result==before.value and left.index.use_site(flow.assigned_reference).use.value==after.value):matched=True
        for flow in path.cross_body_namespace_flows:
            if (flow.read.body==before.body and flow.read.result==before.value and flow.write.body==after.body
                    and right.index.use_site(flow.write.assigned_reference).use.value==after.value):
                from scar.ir.program.static_calls import StaticCallContext
                contexts=tuple(StaticCallContext(b.environment.caller,b.environment.call_operation,
                    b.environment.callee_use,b.environment.callee_value,b.environment.creation.definition,
                    b.environment.callee)for b in flow.bridges)
                expected=(*after.requirements,*contexts)
                if not before.requirements or before.requirements==expected:matched=True
        for flow in path.argument_flows:
            port=flow.argument
            if (port.formal_body==before.body and port.formal_value==before.value and port.actual_body==after.body
                    and port.actual_value==after.value and after.requirements==flow.requirements
                    and (not before.requirements or before.requirements==(*flow.requirements,flow.context))):matched=True
        for flow in path.return_flows:
            if (flow.context.caller==before.body and flow.completion.landing_value==before.value
                    and flow.context.callee==after.body and flow.terminal.value==after.value
                    and before.requirements==flow.requirements and after.requirements==(*flow.requirements,flow.context)):matched=True
        for flow in path.module_attribute_flows:
            if (flow.read.body==before.body and flow.read.result==before.value and flow.source_body==after.body
                    and flow.source_value==after.value and before.requirements==flow.requirements
                    and after.requirements==flow.source_requirements):matched=True
        _need(matched,'reference-source hop is not supported by an original binding/phi/qualified value relation')
    return True


def validate_import_module_route(route, *, engine, check_context=None):
    route.__post_init__()
    if check_context is not None:
        for position,context in enumerate(route.requirements):check_context(context,route.requirements[:position])
    body=engine._body(route.body)
    _need(route in engine.imports_for_result(body,route.result,route.requirements),
          'import source/module/alias/frame ports differ from original inputs')
    return True


def validate_module_attribute_flow(flow, *, engine, check_support, check_context=None):
    """Freshly rederive paths/overwrites from original immutable body inputs.

    Supporting interprocedural hops are checked by the enclosing public reader;
    they cannot be replaced by a display target union or a source-name hint.
    """
    from types import SimpleNamespace
    flow.__post_init__()
    paths=[flow.receiver_path]
    if flow.write_receiver_path is not None:paths.append(flow.write_receiver_path)
    paths.extend(flow.overwrite_receiver_paths)
    for path in paths:
        for point in path.points:
            if check_context is not None:
                for n,context in enumerate(point.requirements):check_context(context,point.requirements[:n])
        validate_reference_source_path(path,load_body=engine._body,
            namespace_for=engine.namespace_for,check_support=check_support)
    def sources(body,value,requirements,requester):
        for path in paths:
            for before,after in zip(path.points,path.points[1:]):
                if (before.body,before.value,before.requirements)!=(body.namespace,value,requirements):continue
                cross=tuple(f for f in path.cross_body_namespace_flows if f.read.body==before.body
                    and f.read.result==before.value and f.write.body==after.body
                    and engine._body(after.body).index.use_site(f.write.assigned_reference).use.value==after.value)
                args=tuple(f for f in path.argument_flows if f.argument.formal_body==before.body
                    and f.argument.formal_value==before.value and f.argument.actual_body==after.body
                    and f.argument.actual_value==after.value)
                returns=tuple(f for f in path.return_flows if f.context.caller==before.body
                    and f.completion.landing_value==before.value and f.context.callee==after.body
                    and f.terminal.value==after.value)
                if cross or args or returns:
                    yield SimpleNamespace(body_namespace=after.body,value=after.value,requirements=after.requirements,
                        crossflows=cross,argflows=args,returnflows=returns)
    fresh=ModuleAttributeDependencies(load_body=engine.load_body,source_context=engine.source_context,
        module_bodies=engine.module_bodies,namespace_for=engine.namespace_for,reference_sources=sources,
        max_steps=engine.max_steps,max_facts=engine.max_facts,check=engine.check)
    validate_import_module_route(flow.module,engine=fresh,check_context=check_context)
    body=fresh._body(flow.read.body)
    _need(flow in fresh.sources(body,flow.read.result,flow.requirements),
          'attribute source/receiver/field/world/control/overwrite provenance differs from original inputs')
    return True
