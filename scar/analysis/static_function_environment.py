"""Conditional function-environment routes over original qualified endpoints.

The factory site is not a runtime object identity. Routes are scoped to a call
whose selected callable comes from that factory occurrence. Reference bindings
and mutable-field initializer dependencies are deliberately different kinds.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from types import SimpleNamespace

from scar.ir.record_codec import decode, encode
from scar.ir.program.environments import EnvironmentRole
from scar.ir.program.ids import OperationID, UseID, ValueID
from scar.ir.program.model import (BlockArgument, CompletionResult, ExitKind,
    OperationResult, ReferenceValue, StateVersionValue, TerminatorKind, UseRole)
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.static_calls import StaticCallFrontier, StaticFunctionCreationRoute
from scar.ir.program.source_call_bindings import SourceBodyNamespace
from scar.ir.program.source import LoweringMetadata
from scar.ir.v2.common import SourceReference
from scar.analysis.static_namespace import protocol_kinds, normal_reference


def _index(graph, existing):
    if existing is not None:
        if type(existing) is not ProgramIndex or existing.graph is not graph:
            raise ValueError('function environment index belongs to another graph')
        return existing
    return ProgramIndex(graph)


def _source_reference(value):
    fields=set(SourceReference.__dataclass_fields__)
    if type(value)is not dict:
        raise ValueError('function source anchor is not an original reference record')
    if set(value)==fields|{'source_kind'}:
        if value['source_kind']!='SOURCE_ATOM':
            raise ValueError('function source anchor cannot be a module/generated unit')
        value={key:value[key] for key in fields}
    elif set(value)!=fields:
        raise ValueError('function source anchor has unsupported fields')
    return decode(SourceReference,value)


def _decoded_source_inputs(document):
    """Decode source records once; these records alone grant no namespace."""
    if type(document) is not dict:
        raise TypeError('static body namespace requires its original envelope object')
    metadata=decode(LoweringMetadata,document['metadata'])
    module=class_entry=interface=None
    if document.get('module') is not None:
        from scar.ir.program.module_entries import decode_frame_body
        module=decode_frame_body(document['module'])
    elif document.get('class') is not None:
        from scar.ir.program.class_entries import decode_class_entry_overlay
        class_entry=decode_class_entry_overlay(document['class'])
    else:
        from scar.ir.program.functions import BodyEntryInterface
        interface=decode(BodyEntryInterface,document['interface'])
    return metadata,module,class_entry,interface


def _check_namespace(graph, document, namespace, decoded):
    """Validate body ownership against its envelope, without source replay.

    Physical/decoded receipt verification belongs to the enclosing reader.
    This check prevents a valid graph from being relabelled with another entry,
    source definition, pointer or representation during relation derivation.
    """
    if type(namespace)is not SourceBodyNamespace:
        raise TypeError('static function environment requires a qualified body namespace')
    if type(document)is not dict:
        raise TypeError('static body namespace requires its original envelope object')
    namespace.__post_init__()
    wire=document.get('graph') if type(document)is dict else None
    if (document.get('schema')!='scar.static-body' or document.get('schema_version')!=1
            or type(wire)is not dict or wire.get('schema')!='scar.program-graph'
            or type(wire.get('schema_version'))is not int):
        raise ValueError('function environment namespace needs its original static body envelope')
    if (namespace.region!=graph.root or wire.get('root')!=encode(graph.root)
            or namespace.graph_representation!='scar.program-graph/'+str(wire['schema_version'])
            or namespace.graph.pointer!='#/graph'
            or namespace.graph.representation!='gzip-canonical-json'
            or namespace.graph.artifact.schema!='scar.static-body/1'):
        raise ValueError('body namespace graph/root/pointer/representation differs from its envelope')
    metadata,module,class_entry,interface=decoded
    sources=metadata;interface=None
    if namespace.entry!=metadata.entry:
        raise ValueError('body namespace entry differs from original metadata')
    if document.get('module') is not None:
        overlay=module;unit=overlay.declaration.unit;sources=overlay
        if (namespace.definition!=unit.initializer or namespace.source is not None
                or metadata.source!=unit.snapshot or metadata.entry!=unit.initializer.wire):
            raise ValueError('module namespace source/definition differs from its original initializer')
    elif document.get('class') is not None:
        overlay=class_entry
        if (namespace.definition!=overlay.definition or namespace.source!=overlay.source
                or metadata.entry!=overlay.definition.wire):
            raise ValueError('class namespace source/definition differs from original ClassDef')
    else:
        interface=decoded[3]
        if namespace.definition!=interface.definition or namespace.region!=interface.region or namespace.source is None:
            raise ValueError('function namespace differs from original source interface')
        structured=document.get('structured')
        if structured is not None:
            if (structured['definition']!=encode(interface.definition) or structured['region']!=encode(interface.region)
                    or _source_reference(structured['source'])!=namespace.source):
                raise ValueError('function namespace differs from original structured source owner')
        else:
            anchors={_source_reference(row['source']) for row in document['metadata'].get('value_links',())
                     if row['value']==encode(interface.world) and row['role']=='STATE'}
            if anchors!={namespace.source}:
                raise ValueError('function namespace lacks its original entry-world source anchor')
    if namespace.source is not None and (namespace.source.path!=metadata.source.path or namespace.source.fingerprint!=metadata.source.fingerprint):
        raise ValueError('body namespace source differs from its retained snapshot')
    return metadata,sources,interface


def _namespace_inputs(graph, document, namespace):
    return _check_namespace(graph,document,namespace,_decoded_source_inputs(document))


def validate_static_body_namespace(graph, document, namespace):
    """Freshly check the original namespace and decode its typed source facts."""
    return _namespace_inputs(graph,document,namespace)[0]


_WIRE_FIELDS=('graph','metadata','module','class','interface','structured')


@dataclass(frozen=True,slots=True)
class _OwnedInputs:
    """Decoded inputs issued by one private owner, never a PASS boolean."""
    owner: object
    graph: object
    document: dict
    index: ProgramIndex
    wire_fields: tuple
    metadata: LoweringMetadata
    module: object
    class_entry: object
    interface: object
    operation_links: dict
    use_links: dict
    protocols: dict
    blocks: dict
    bytes: int


class _EnvironmentFacts:
    """Bounded original typed inputs owned by one derive/consumer session.

    Qualified namespace receipts and strong object references prevent bare-ID
    reuse. Reloaded graph/index/document objects are decoded again. These are
    source snapshots, not remembered verification results: each route's ports,
    conditions and state endpoints are still replayed against them.
    """
    def __init__(self, *, max_bodies=16, max_bytes=64*1024*1024):
        if any(type(n)is not int or n<1 for n in (max_bodies,max_bytes)):
            raise ValueError('environment fact input bounds must be positive integers')
        self.max_bodies,self.max_bytes=max_bodies,max_bytes
        self.bodies=OrderedDict();self.bytes=0

    def _owned(self,inputs,graph,document,index):
        if (type(inputs)is not _OwnedInputs or inputs.owner is not self
                or inputs.graph is not graph or inputs.document is not document
                or inputs.index is not index or index.graph is not graph):
            raise ValueError('decoded environment inputs belong to another owner/graph/document/index')
        if any(old is not document.get(name) for name,old in zip(_WIRE_FIELDS,inputs.wire_fields)):
            raise ValueError('environment source inputs changed within their private snapshot scope')
        return inputs

    def inputs(self,graph,document,*,index,size_bytes):
        """Strictly decode the owner's original wire once, before namespace creation.

        The reader may retain this small source bundle alongside its original
        body. Reuse still binds all three original objects and wire fields;
        receipt checks and namespace admission remain separate operations.
        """
        index=_index(graph,index)
        if type(document)is not dict or type(size_bytes)is not int or size_bytes<1:
            raise TypeError('decoded environment inputs need an original document and positive receipt size')
        key=id(graph),id(document),id(index)
        found=self.bodies.get(key)
        if found is not None:
            self._owned(found,graph,document,index)
            self.bodies.move_to_end(key)
            return found
        metadata,module,class_entry,interface=_decoded_source_inputs(document)
        sources=module if module is not None else metadata
        operations={};uses={}
        for row in sources.operation_links:operations.setdefault(row.operation,[]).append(row)
        for row in sources.use_links:uses.setdefault(row.operation,[]).append(row)
        found=_OwnedInputs(self,graph,document,index,tuple(document.get(name)for name in _WIRE_FIELDS),
            metadata,module,class_entry,interface,operations,uses,protocol_kinds(document),
            {b.id:b for r in graph.regions for b in r.blocks},size_bytes)
        if size_bytes<=self.max_bytes:
            self.bodies[key]=found;self.bytes+=size_bytes
            while len(self.bodies)>self.max_bodies or self.bytes>self.max_bytes:
                _,old=self.bodies.popitem(last=False);self.bytes-=old.bytes
        return found

    def body(self,graph,document,namespace,index=None,*,inputs=None):
        if index is None:
            if type(inputs)is _OwnedInputs:
                index=inputs.index
            else:
                found=next((row for row in self.bodies.values()
                    if row.graph is graph and row.document is document),None)
                if found is not None:index=found.index
        index=_index(graph,index)
        if inputs is None:
            inputs=self.inputs(graph,document,index=index,size_bytes=namespace.graph.decoded_bytes)
        self._owned(inputs,graph,document,index)
        decoded=inputs.metadata,inputs.module,inputs.class_entry,inputs.interface
        metadata,sources,interface=_check_namespace(graph,document,namespace,decoded)
        return SimpleNamespace(graph=graph,document=document,namespace=namespace,index=index,
            metadata=metadata,sources=sources,interface=interface,wire_fields=inputs.wire_fields,
            operation_links=inputs.operation_links,use_links=inputs.use_links,protocols=inputs.protocols,
            blocks=inputs.blocks,bytes=inputs.bytes,environment_inputs=inputs)


def _world(index, operation):
    found=[use for use in operation.uses if use.id in operation.invoke_arguments
           and use.role is UseRole.STATE_CONTENT and type(index.values[use.value]) is StateVersionValue]
    if len(found)!=1:
        raise ValueError('function environment operation has no unique original world Use')
    return found[0]


def _roles(document, index, operation, *, inputs=None):
    overlay=document.get('module')
    rows=(inputs.use_links.get(operation.id,())if inputs is not None else
          (overlay if overlay is not None else document.get('metadata') or {}).get('use_links',()))
    found={}
    for row in rows:
        if (row.operation if inputs is not None else decode(OperationID,row['operation']))!=operation.id:
            continue
        use=row.use if inputs is not None else decode(UseID,row['use'])
        site=index.use_site(use)
        if site.operation!=operation.id or use in found:
            raise ValueError('function environment source Use is duplicated or owned by another operation')
        role,position=(row.role,row.index)if inputs is not None else(row['role'],row['index'])
        if type(role)is not str or not role or type(position)is not int or position<0:
            raise ValueError('function environment source role/index is malformed')
        found[use]=(role,position)
    return found


def _factory(index, document, protocols, route, *, inputs=None):
    if type(route)is not StaticFunctionCreationRoute:
        raise TypeError('function environment needs an existing verified factory relation')
    operation=index.operations.get(route.factory)
    if operation is None or protocols.get(route.factory) not in ('MAKE_FUNCTION_314','MAKE_NESTED_FUNCTION'):
        raise ValueError('function environment creation does not name its original supported factory')
    normal=normal_reference(index,route.factory,blocks=inputs.blocks if inputs is not None else None)
    if normal!=(route.normal_edge,route.normal_value):
        raise ValueError('function environment creation normal endpoints differ')
    code=index.use_site(route.code_use)
    if code.operation!=operation.id or code.use.id not in operation.invoke_arguments:
        raise ValueError('function environment factory code Use differs')
    origin=index.values[code.use.value].origin
    if type(origin)is not OperationResult or origin.operation!=route.code_constant_operation:
        raise ValueError('function environment code does not come from the original constant operation')
    links=(inputs.operation_links.get(operation.id,())if inputs is not None else
           [row for row in(document.get('module') if document.get('module') is not None else document['metadata']).get('operation_links',())
            if decode(OperationID,row['operation'])==operation.id])
    metadata=inputs.metadata if inputs is not None else decode(LoweringMetadata,document['metadata'])
    if (len(links)!=1 or (links[0].source if inputs is not None else _source_reference(links[0]['source']))!=route.definition.source
            or metadata.source!=route.definition.snapshot):
        raise ValueError('function factory source/snapshot differs from its original qualified definition')
    return operation


def _derive_function_environment_routes(*, caller_graph, caller_document, caller_namespace,
        callee_graph, callee_document, callee_namespace, definition, call_operation,
        callee_use, creations=(), caller_index=None, callee_index=None,
        qualified_creations=(), load_creation_body=None, facts):
    """Return (typed routes, precise frontiers), with no new graph identities.

    ``creations`` must be the source-verified routes actually traversed while
    resolving this call. Merely sharing a code definition is insufficient.
    Existing indexes may be supplied to avoid decoding/scanning large bodies.
    """
    from scar.ir.program.static_calls import (
        FunctionEnvironmentCondition as C, FunctionEnvironmentRouteKind as K,
        StaticFunctionEnvironmentRoute, StaticQualifiedFunctionCreation,
    )
    caller_inputs=facts.body(caller_graph,caller_document,caller_namespace,caller_index)
    callee_inputs=facts.body(callee_graph,callee_document,callee_namespace,callee_index)
    caller,callee=caller_inputs.index,callee_inputs.index
    callee_metadata=callee_inputs.metadata
    if callee_metadata.source!=definition.snapshot:
        raise ValueError('function environment target snapshot differs from its original body metadata')
    if callee_namespace.definition!=definition.definition or callee_namespace.source!=definition.source:
        raise ValueError('function environment target does not name its qualified source body')
    environments=[e for e in callee_graph.environments if e.region==callee_graph.root
                  and e.code_definition==definition.definition]
    if len(environments)!=1:
        return (), (StaticCallFrontier('CALLEE_ENVIRONMENT_INTERFACE_UNAVAILABLE',
            'Qualified callee has no unique existing function environment declaration.',definition.source),)
    environment=environments[0]
    if callee_use is None:
        return (), (StaticCallFrontier('CALL_CALLEE_REFERENCE_UNAVAILABLE',
            'No unique original callable Use is available for a conditional environment route.',definition.source),)
    operation=caller.operations.get(call_operation)
    if operation is None or operation.terminator is None or operation.terminator.kind is not TerminatorKind.INVOKE:
        raise ValueError('function environment call has no original invoke boundary')
    site=caller.use_site(callee_use)
    if site.operation!=operation.id or callee_use not in operation.invoke_arguments or type(caller.values[site.use.value])is not ReferenceValue:
        raise ValueError('function environment callee Use is not this invoke callable reference')
    call_world=_world(caller,operation)
    selected=[StaticQualifiedFunctionCreation(caller_namespace,r) for r in creations if r.definition==definition]
    for qualified in qualified_creations:
        if type(qualified)is not StaticQualifiedFunctionCreation:
            raise TypeError('foreign factory requires its original qualified creation relation')
        if qualified.creation.definition==definition and qualified not in selected:
            selected.append(qualified)
    if not selected:
        return (), (StaticCallFrontier('VERIFIED_FUNCTION_CREATION_UNAVAILABLE',
            'No source-verified factory occurrence is connected to this call target; a common code definition cannot choose a function object.',definition.source),)
    members={m.role:m for m in environment.members if m.role is not EnvironmentRole.CAPTURED_CELL}
    captured=tuple(m for m in environment.members if m.role is EnvironmentRole.CAPTURED_CELL)
    routes=[];frontiers=[]
    base=(C.TARGET_SELECTS_THIS_CREATION,C.FACTORY_COMPLETED_NORMALLY,
          C.CALLEE_DERIVES_FROM_THIS_FACTORY_OCCURRENCE,C.FUNCTION_CODE_MATCHES_CREATION)
    for qualified in selected:
        creation,creation_namespace=qualified.creation,qualified.body
        if creation_namespace==caller_namespace:
            creator,creator_document,creator_graph=caller,caller_document,caller_graph
            creator_inputs=caller_inputs
        else:
            if load_creation_body is None:
                frontiers.append(StaticCallFrontier('QUALIFIED_FACTORY_BODY_UNAVAILABLE',
                    'Foreign factory namespace is retained, but no source-qualified body loader was supplied.',definition.source))
                continue
            loaded=load_creation_body(creation_namespace)
            if loaded is None or loaded.namespace!=creation_namespace:
                raise ValueError('factory body loader changed its original qualified namespace')
            creator_graph,creator_document=loaded.graph,loaded.document
            creator=_index(creator_graph,loaded.index)
            creator_inputs=facts.body(creator_graph,creator_document,creation_namespace,creator)
        factory=_factory(creator,creator_document,creator_inputs.protocols,creation,inputs=creator_inputs)
        factory_world=_world(creator,factory)
        roles=_roles(creator_document,creator,factory,inputs=creator_inputs)
        if roles.get(creation.code_use)!=('function-code',0):
            raise ValueError('function environment factory code role differs from its verified creation')
        edge=factory.terminator.successors[creation.normal_edge.successor_index]
        blocks=creator_inputs.blocks
        normal_world=[formal for formal,actual in zip(blocks[edge.block].arguments,edge.arguments)
            if type(actual)is CompletionResult and type(creator.values[formal])is StateVersionValue]
        if len(normal_world)!=1:
            raise ValueError('function environment factory lacks its actual normal post-world')
        def append(member,source_value,source_use,source_role,source_index,kind,conditions):
            if type(creator.values[source_value])is not ReferenceValue or type(callee.values[member.reference])is not ReferenceValue:
                raise ValueError('function environment relation must connect existing reference endpoints')
            routes.append(StaticFunctionEnvironmentRoute(caller_namespace,operation.id,callee_use,site.use.value,
                call_world.id,call_world.value,creation_namespace,creation,factory_world.id,factory_world.value,
                normal_world[0],source_use,source_value,source_role,source_index,callee_namespace,
                environment.id,member,kind,conditions))
        member=members.get(EnvironmentRole.FUNCTION_OBJECT)
        if member is not None:
            append(member,creation.normal_value,None,'factory-normal-function',None,K.REFERENCE_BINDING,base)
        globals_inputs=[u for u in factory.uses if roles.get(u.id,('',None))[0]=='function-globals']
        member=members.get(EnvironmentRole.GLOBALS_NAMESPACE)
        if len(globals_inputs)==1 and member is not None:
            use=globals_inputs[0]
            append(member,use.value,use.id,'function-globals',roles[use.id][1],K.REFERENCE_BINDING,base)
        else:
            frontiers.append(StaticCallFrontier('FACTORY_GLOBALS_INPUT_UNAVAILABLE',
                'Factory has no unique original function-globals input Use; callee G is not borrowed from caller namespaces.',definition.source))
        defaults=[];keyword_defaults=[];cell_inputs={}
        for use in factory.uses:
            role,position=roles.get(use.id,('',None))
            if role in ('function-default','function-defaults-tuple'):
                defaults.append((use,role,position))
            elif role.startswith('function-keyword-default:'):
                keyword_defaults.append((use,role,position))
            elif role=='function-closure-cell':
                if position in cell_inputs:
                    raise ValueError('factory closure position has multiple original cell Uses')
                cell_inputs[position]=(use,role,position)
        for env_role,inputs in ((EnvironmentRole.DEFAULTS,defaults),(EnvironmentRole.KEYWORD_DEFAULTS,keyword_defaults)):
            member=members.get(env_role)
            if inputs and member is not None:
                for use,role,position in inputs:
                    conditions=base+(C.FUNCTION_FIELD_PRESERVED_SINCE_CREATION,)
                    if role!='function-defaults-tuple':conditions+=(C.PACKED_INITIALIZER_RELATION_REQUIRED,)
                    append(member,use.value,use.id,role,position,K.FIELD_INITIALIZER_DEPENDENCE,conditions)
            else:
                frontiers.append(StaticCallFrontier(env_role.value+'_INITIALIZATION_UNCONNECTED',
                    'No original factory input represents this field initializer. None/packing or later attribute writes require their own existing provenance, not an invented reference.',definition.source))
        for member in captured:
            item=cell_inputs.get(member.cell_position)
            if item is None:
                frontiers.append(StaticCallFrontier('CAPTURED_CELL_INITIALIZATION_UNCONNECTED',
                    'Captured cell slot has no original factory input at its exact closure position; names or class later attribute writes are not substituted.',definition.source))
                continue
            use,role,position=item
            append(member,use.value,use.id,role,position,K.REFERENCE_BINDING,base)
        frontiers.append(StaticCallFrontier('SAVED_BUILTINS_CREATION_SELECTION_OPEN',
            'Saved builtins is selected during function creation from the creating globals and interpreter fallback. No route equates it with caller current builtins or the current globals builtins entry.',definition.source))
    return tuple(dict.fromkeys(routes)),tuple(dict.fromkeys(frontiers))


def derive_function_environment_routes(*, caller_graph, caller_document, caller_namespace,
        callee_graph, callee_document, callee_namespace, definition, call_operation,
        callee_use, creations=(), caller_index=None, callee_index=None,
        qualified_creations=(), load_creation_body=None):
    """Fresh standalone derive; typed input reuse lasts only for this call."""
    return _derive_function_environment_routes(caller_graph=caller_graph,caller_document=caller_document,
        caller_namespace=caller_namespace,callee_graph=callee_graph,callee_document=callee_document,
        callee_namespace=callee_namespace,definition=definition,call_operation=call_operation,
        callee_use=callee_use,creations=creations,caller_index=caller_index,callee_index=callee_index,
        qualified_creations=qualified_creations,load_creation_body=load_creation_body,facts=_EnvironmentFacts())


def _validate_function_environment_route(route, *, facts, **inputs):
    routes,_=_derive_function_environment_routes(**inputs,facts=facts)
    if route not in routes:
        raise ValueError('stored function environment route differs from original qualified factory/call/member endpoints')


def validate_function_environment_route(route, **inputs):
    """Fresh replay; no previous consumer's input scope is accepted here."""
    return _validate_function_environment_route(route,facts=_EnvironmentFacts(),**inputs)
