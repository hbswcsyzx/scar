"""Independent SourceProgram6 entry/core/source checks, never runtime authority."""
from __future__ import annotations

import ast
from hashlib import sha256

from scar.ir.program.module_entries import (ModuleBodyOverlay, ModuleBodyStatus, ModuleUnitSource,
    ModuleProtocolKind, ModuleEntryProfile, encode_module_overlay, decode_module_overlay)
from scar.ir.program.model import (Behavior, BlockArgument, CompletionResult, ExitKind,
    LiteralOrigin, OperationResult, ReferenceValue, StateVersionValue, TerminatorKind, ValueKind, ValueType)
from scar.ir.program.source import LoweringMetadata
from scar.ir.program.call_edges import CallLinkStatus
from scar.ir.program.structured import PythonProtocolKind
from scar.ir.record_codec import encode
from scar.ir.v2.common import SourceReference


def _need(condition, detail):
    if not condition:
        raise ValueError('module source: ' + detail)


def require_valid_module_program(result, *, source_texts, code_evidence=None, max_operations=10000):
    from scar.analysis.program_lowering import PreparedSource, _symbol_tables
    from scar.analysis.source_module_lowering import module_unit, module_source_census, require_root_evidence
    from scar.analysis.source_semantics_v2 import validate_source_semantics
    from scar.analysis.control_flow_v2 import validate_source_control_flow
    from scar.ir.program.validation import require_valid
    from scar.ir.v2._validation import record_errors
    from pathlib import Path

    overlay = result.module
    _need(type(overlay) is ModuleBodyOverlay, 'v6 needs its strict module overlay')
    _need(decode_module_overlay(encode_module_overlay(overlay)) == overlay, 'module overlay is not canonical')
    unit = overlay.declaration.unit
    _need(result.profile is ModuleEntryProfile.EXEC_MAPPING_314_V1
          and result.interface is None and result.frame is None and result.structured is None
          and result.language is None, 'mapping entry must not acquire a function ABI/overlay')
    _need(result.metadata == LoweringMetadata(unit.initializer.wire, unit.snapshot),
          'v6 metadata must not contain invented function or source-atom correspondence')
    _need(type(max_operations) is int and 1 <= max_operations <= 100000
          and overlay.operations_emitted <= max_operations, 'independent module construction budget exceeded')
    _need(type(source_texts) is dict and unit.snapshot.path in source_texts
          and all(type(path) is str and type(text) is str for path, text in source_texts.items()),
          'mapping reader requires explicit complete retained source_texts; no filesystem fallback')
    text = source_texts[unit.snapshot.path]
    _need('sha256:' + sha256(text.encode()).hexdigest() == unit.snapshot.fingerprint,
          'retained module text fingerprint differs')
    _need(set(result.semantics.sources) == {unit.snapshot.path}
          and set(result.control.sources) == {unit.snapshot.path},
          'mapping capability requires one exact source unit; no unprovided source fallback')
    result.semantic.assert_valid()
    for check in (validate_source_semantics(result.semantics, result.semantic, sources=source_texts),
                  validate_source_control_flow(result.control, result.semantic, result.semantics, sources=source_texts)):
        _need(check['valid'], '; '.join(check.get('errors', ())))
    tree = ast.parse(text, filename=unit.snapshot.path)
    context = PreparedSource(Path(unit.snapshot.path), Path(unit.namespace_root), text,
        result.semantic, result.semantics, result.control, tree, {})
    _need(module_unit(context) == unit and overlay.census == module_source_census(context),
          'original module initializer/source census differs')
    witness = overlay.declaration.witness
    _need(witness.source_link.snapshot == unit.snapshot and witness.captured.filename == unit.snapshot.path
          and witness.captured.key == witness.source_link.code
          and witness.source_link.status is CallLinkStatus.VERIFIED,
          'root witness/source unit identities differ')
    if code_evidence is not None:
        _need(require_root_evidence(unit, code_evidence) == witness, 'independent compiler-root evidence differs')
    def valid_source(source):
        if type(source) is ModuleUnitSource:
            return source == unit
        if type(source) is SourceReference:
            atom = result.semantic.source_atoms.get(source.atom_id)
            return atom is not None and atom.reference == source and source.path == unit.snapshot.path
        return False
    _need(all(valid_source(row.source) for row in overlay.frontiers), 'frontier has no exact original source')
    if result.graph is None:
        _need(overlay.status is ModuleBodyStatus.UNSUPPORTED and overlay.interface is None
              and not any((overlay.operation_links, overlay.value_links, overlay.use_links, overlay.protocols, overlay.loops))
              and any(row.kind == 'MODULE_INITIALIZER_BODY_NOT_RECOVERED' for row in overlay.frontiers),
              'graph-none body must keep concrete debt and no executable endpoints')
        return
    _need(overlay.status is ModuleBodyStatus.PARTIAL and overlay.interface is not None
          and overlay.unexpanded_body is not None, 'this entry capability must retain required body expansion')
    graph, interface, body = result.graph, overlay.interface, overlay.unexpanded_body
    require_valid(graph)
    from scar.analysis.source_module_lowering import module_source_context
    _need(body.unit == unit and body.context == module_source_context(context)
          and body.required_expansion.value == 'REQUIRED', 'unexpanded body source/context/debt differs')
    regions = {row.id:row for row in graph.regions}
    _need(interface.unit == unit and graph.root == interface.region and len(regions) == 2
          and body.region in regions and body.region != graph.root and regions[body.region].parent == graph.root
          and not graph.environments and not graph.function_entries
          and not graph.binding_definitions and not graph.binding_reads,
          'mapping entry/body must not masquerade as a function or fast-local environment')
    operations = {row.id:row for row in graph.operations}
    values = {row.id:row for row in graph.values}
    blocks = {row.id:row for region in graph.regions for row in region.blocks}
    owners = {operation:region.id for region in graph.regions for block in region.blocks for operation in block.operations}
    entry = blocks[regions[graph.root].entry]
    child_entry = blocks[regions[body.region].entry]
    refs = (interface.locals_namespace,interface.globals_namespace,interface.builtins_namespace)
    _need(entry.arguments == refs+(interface.world,) and len(child_entry.arguments)==4
          and all(type(values[value]) is ReferenceValue for value in refs+child_entry.arguments[:3])
          and type(values[interface.world]) is StateVersionValue
          and type(values[child_entry.arguments[-1]]) is StateVersionValue,
          'entry/body must retain ordered namespaces and separate whole-world ports')
    _need(all(type(values[value].origin) is BlockArgument for value in entry.arguments+child_entry.arguments),
          'mapping ports must be real core BlockArguments')
    _need(overlay.operations_emitted == len(operations), 'entry construction count differs from returned graph')
    links = {row.operation:row for row in overlay.operation_links}
    _need(len(links)==len(overlay.operation_links) and set(links)==set(operations),
          'entry/core operation correspondence is incomplete')
    _need({row.value for row in overlay.value_links}==set(values), 'entry/core value correspondence is incomplete')
    _need({(row.operation,row.use) for row in overlay.use_links}==
          {(op.id,use.id) for op in operations.values() for use in op.uses}, 'entry/core Use correspondence is incomplete')
    _need(all(row.source==unit for rows in (overlay.operation_links,overlay.value_links,overlay.use_links)
          for row in rows), 'entry skeleton must not fabricate concrete statement operations or source atoms')
    _need(all(row.semantic_operation is None and row.opcode is None for row in overlay.operation_links),
          'unexpanded interface must not claim concrete original computational operations were recovered')
    protocols = {row.operation:row for row in overlay.protocols}
    _need(len(protocols)==len(overlay.protocols), 'duplicate module protocol')
    ref_type=ValueType(ValueKind.REFERENCE)
    state_type=ValueType(ValueKind.STATE,location=values[interface.world].location)
    opaque = operations[body.operation]
    calls = [op for op in operations.values() if op.callee is not None]
    _need(len(calls)==1 and calls[0].callee==body.region and owners[calls[0].id]==graph.root,
          'entry must invoke the exact same declared child body Region')
    call=calls[0]
    for op,kind,expected_refs,normal_types in (
        (opaque,ModuleProtocolKind.UNEXPANDED_BODY,child_entry.arguments[:3],(state_type,)),
        (call,ModuleProtocolKind.INVOKE_MODULE_BODY,refs,(ref_type,state_type))):
        _need(protocols.get(op.id) is not None and protocols[op.id].kind is kind
              and protocols[op.id].source==unit and op.terminator is not None
              and op.terminator.kind is TerminatorKind.INVOKE and not op.effects_complete
              and set(op.behaviors)=={Behavior.CONTROL,Behavior.READ,Behavior.WRITE}
              and tuple(use.value for use in op.uses[:-1])==expected_refs
              and type(values[op.uses[-1].value]) is StateVersionValue
              and op.invoke_arguments==tuple(use.id for use in op.uses),
              'body interface requires ordered borrowed namespaces, whole world and unknown effects')
        _need(tuple((row.kind,row.types) for row in op.completions)==
              ((ExitKind.NORMAL,normal_types),(ExitKind.RAISE,(ref_type,state_type)))
              and tuple(edge.kind for edge in op.terminator.successors)==(ExitKind.NORMAL,ExitKind.RAISE)
              and all(edge.arguments==tuple(CompletionResult(i) for i in range(len(signature.types)))
                for edge,signature in zip(op.terminator.successors,op.completions)),
              'body normal/raise interfaces must carry their own post-world')
    _need(opaque.callee is None and owners[opaque.id]==body.region and not opaque.accesses
          and not graph.state_address_refinements, 'opaque source body cannot assert target/state internals')
    first=operations[entry.operations[0]]
    _need(protocols.get(first.id) is not None and protocols[first.id].kind is PythonProtocolKind.FRAME_ENTER
          and tuple(use.value for use in first.uses[:-1])==refs, 'mapping frame must first retain exact namespaces')
    frame_protocols=[]
    for identity,protocol in protocols.items():
        _need(identity in operations and protocol.source==unit, 'module protocol endpoint/source differs')
        if type(protocol.kind) is not PythonProtocolKind:
            continue
        _need(protocol.kind in (PythonProtocolKind.FRAME_ENTER,PythonProtocolKind.FRAME_EXIT)
              and owners[identity]==graph.root, 'child body interface is not another Python frame')
        op=operations[identity];frame_protocols.append(identity)
        _need(op.terminator is None and not op.effects_complete and op.callee is None
              and set(op.behaviors)=={Behavior.READ,Behavior.WRITE,Behavior.MEMORY}
              and len(op.accesses)==1, 'mapping retention must preserve existing conditional frame/world rules')
        access=op.accesses[0]
        _need(access.mode.value=='READ_WRITE' and not access.full_overwrite and access.reference is None
              and op.results==(access.after,), 'frame transition must advance whole coarse world')
        if protocol.kind is PythonProtocolKind.FRAME_EXIT:
            block=next(block for block in blocks.values() if identity in block.operations)
            _need(len(block.operations)>=2 and block.operations[-2]==identity
                  and tuple(use.value for use in op.uses[1:-1])==refs,
                  'frame exit must retain payload and exact ordered namespace suffix')
            completion=operations[block.operations[-1]]
            _need(completion.terminator is not None and completion.terminator.kind in (TerminatorKind.RETURN,TerminatorKind.RAISE)
                  and completion.uses[0].value==op.uses[0].value
                  and completion.uses[1].value==op.results[0], 'frame exit payload/post-world differs')
    _need(len(frame_protocols)==3 and len(protocols)==5, 'entry needs one enter/two completion frame operations')
    _need(set(protocols)|{op.id for op in operations.values() if op.terminator is not None
          and op.terminator.kind in (TerminatorKind.RETURN,TerminatorKind.RAISE)}==set(operations),
          'unexpanded skeleton contains an undeclared internal operation')
    child_returns=[op for op in operations.values() if owners[op.id]==body.region
                   and op.terminator is not None and op.terminator.kind is TerminatorKind.RETURN]
    _need(len(child_returns)==1, 'exec body must retain one normal interface completion')
    payload_use={use.id:use for use in child_returns[0].uses}[child_returns[0].terminator.values[0]]
    payload=values[payload_use.value]
    _need(type(payload.origin) is LiteralOrigin and payload.origin.value is None,
          'exec-root normal interface returns None, never a namespace/import object')
    root_returns=[op for op in operations.values() if owners[op.id]==graph.root
                  and op.terminator is not None and op.terminator.kind is TerminatorKind.RETURN]
    _need(len(root_returns)==1, 'mapping wrapper must retain one normal completion')
    normal_target=blocks[call.terminator.successors[0].block]
    returned_use={use.id:use for use in root_returns[0].uses}[root_returns[0].terminator.values[0]]
    _need(returned_use.value==normal_target.arguments[0], 'wrapper must preserve body normal payload')
    _need(any(row.kind=='REQUIRED_EXPANSION' and row.source==unit for row in overlay.frontiers)
          and any(row.kind=='MODULE_INITIALIZER_BODY_NOT_RECOVERED' for row in overlay.frontiers),
          'opaque body must preserve both explicit expansion and unrecovered-body debt')


def module_validation_report(result, *, source_texts, code_evidence=None, max_operations=10000):
    try:
        from scar.ir.program.module_entries import ModulePrefixOverlay,StructuredFrameBodyOverlay
        checker = (require_valid_structured_module_program if type(result.module) is StructuredFrameBodyOverlay
                   else require_valid_module_prefix if type(result.module) is ModulePrefixOverlay else require_valid_module_program)
        checker(result, source_texts=source_texts, code_evidence=code_evidence,
                max_operations=max_operations)
    except (ValueError,TypeError,KeyError,AttributeError,OSError,SyntaxError,RecursionError) as error:
        return {'valid':False,'errors':[str(error)]}
    from scar.analysis.source_language import SourceCodeEvidence
    from scar.ir.program.module_entries import StaticModuleEntryDeclaration
    return {'valid':True,'errors':[], 'verification':'STRUCTURE',
        'compiler_root_witness_replayed':type(code_evidence) is SourceCodeEvidence,
        'static_source_compilation_replayed':type(result.module.declaration) is StaticModuleEntryDeclaration,
        'runtime_code_instance_established':False,'namespace_alias_established':False,
        'import_module_object_established':False,'whole_program_coverage_established':False}


def require_valid_module_prefix(result,*,source_texts,code_evidence=None,max_operations=10000):
    """SP7 validation; the preceding SP6 closed validator is unchanged."""
    from pathlib import Path
    from scar.analysis.program_lowering import PreparedSource
    from scar.analysis.source_module_lowering import (module_unit,module_source_census,
        require_root_evidence,first_import_selection)
    from scar.analysis.source_semantics_v2 import validate_source_semantics
    from scar.analysis.control_flow_v2 import validate_source_control_flow
    from scar.ir.program.module_entries import (ModulePrefixOverlay,ModuleBodyExpansionProfile,
        ModulePrefixProtocolKind as K,ModuleProtocolKind,encode_module_prefix,decode_module_prefix)
    from scar.ir.program.validation import require_valid
    from scar.ir.program.state_addresses import (InvokeStateOperand,ReferenceOwner,NamespaceKey,AddressCoverage)
    overlay=result.module
    _need(type(overlay) is ModulePrefixOverlay and decode_module_prefix(encode_module_prefix(overlay))==overlay,
          'v7 requires its exact closed prefix overlay')
    unit=overlay.declaration.unit
    _need(result.profile is ModuleBodyExpansionProfile.IMPORT_PREFIX_314_V1
          and result.interface is None and result.frame is None and result.structured is None and result.language is None,
          'prefix profile must preserve separate mapping ABI and historical function guards')
    _need(result.metadata==LoweringMetadata(unit.initializer.wire,unit.snapshot), 'prefix metadata differs')
    _need(type(max_operations) is int and 1<=max_operations<=100000 and overlay.operations_emitted<=max_operations,
          'independent prefix operation budget exceeded')
    _need(type(source_texts) is dict and unit.snapshot.path in source_texts
          and all(type(path) is str and type(text) is str for path,text in source_texts.items()),
          'prefix requires explicit retained source text, no path fallback')
    text=source_texts[unit.snapshot.path]
    _need('sha256:'+sha256(text.encode()).hexdigest()==unit.snapshot.fingerprint,
          'prefix retained source fingerprint differs')
    _need(set(result.semantics.sources)=={unit.snapshot.path} and set(result.control.sources)=={unit.snapshot.path},
          'prefix must retain exactly one original source unit')
    result.semantic.assert_valid()
    for checked in (validate_source_semantics(result.semantics,result.semantic,sources=source_texts),
        validate_source_control_flow(result.control,result.semantic,result.semantics,sources=source_texts)):
        _need(checked['valid'],'; '.join(checked.get('errors',())))
    context=PreparedSource(Path(unit.snapshot.path),Path(unit.namespace_root),text,result.semantic,
        result.semantics,result.control,ast.parse(text,filename=unit.snapshot.path),{})
    _need(module_unit(context)==unit and overlay.census==module_source_census(context), 'original full source census differs')
    witness=overlay.declaration.witness
    _need(witness.source_link.snapshot==unit.snapshot and witness.captured.filename==unit.snapshot.path
          and witness.source_link.code==witness.captured.key and witness.source_link.status is CallLinkStatus.VERIFIED,
          'prefix root source witness differs')
    if code_evidence is not None:
        _need(require_root_evidence(unit,code_evidence)==witness,'prefix readonly whole-root witness differs')
    node,source,sg,cfg,subject,offsets=first_import_selection(context,code_evidence)
    prefix=overlay.prefix;remaining=overlay.remaining
    _need((prefix.source,prefix.sg_definition,prefix.cfg_node)==(source,sg,cfg)
          and remaining.subject==subject and remaining.required_expansion.value=='REQUIRED',
          'prefix/original SG/CFG or exact residual source slice differs')
    if offsets is not None:
        _need((prefix.import_code_offset,prefix.store_code_offset)==offsets,'readonly root compiler import/store offsets differ')
    graph=result.graph;_need(graph is not None,'proved import prefix must return its partial graph');require_valid(graph)
    _need(not any((graph.environments,graph.function_entries,graph.binding_definitions,graph.binding_reads,
          graph.stored_value_writes,graph.stored_value_reads,graph.call_effect_expansions)),
          'mapping attempt cannot grant a function/fast-local/stored-content/effect expansion proof')
    regions={row.id:row for row in graph.regions};operations={row.id:row for row in graph.operations}
    values={row.id:row for row in graph.values};blocks={row.id:row for row in graph.regions for row in row.blocks}
    owners={op:region.id for region in graph.regions for block in region.blocks for op in block.operations}
    interface=overlay.interface;body=overlay.body_region
    _need(graph.root==interface.region and interface.unit==unit and len(regions)==4
          and set(regions)=={graph.root,body,prefix.region,remaining.region}
          and regions[body].parent==graph.root and regions[prefix.region].parent==body and regions[remaining.region].parent==body,
          'entry/same body/import prefix/remaining Region ownership differs')
    entries={identity:blocks[region.entry] for identity,region in regions.items()}
    refs={identity:block.arguments[:3] for identity,block in entries.items()}
    world=values[interface.world].location
    for entry in entries.values():
        _need(len(entry.arguments)==4 and all(type(values[v]) is ReferenceValue for v in entry.arguments[:3])
              and type(values[entry.arguments[-1]]) is StateVersionValue and values[entry.arguments[-1]].location==world,
              'each computation region needs three namespace refs and the same coarse world')
    _need(entries[graph.root].arguments==(interface.locals_namespace,interface.globals_namespace,interface.builtins_namespace,interface.world),
          'mapping entry interface order differs')
    _need(overlay.operations_emitted==len(operations),'prefix construction operation count differs')
    def original_source(value):
        if type(value) is ModuleUnitSource:return value==unit
        atom=result.semantic.source_atoms.get(value.atom_id) if type(value) is SourceReference else None
        return atom is not None and atom.reference==value and value.path==unit.snapshot.path
    _need(all(original_source(row.source) for rows in (overlay.operation_links,overlay.value_links,overlay.use_links,overlay.frontiers)
              for row in rows),'prefix invented a source atom/unit')
    links={row.operation:row for row in overlay.operation_links}
    _need(len(links)==len(overlay.operation_links) and set(links)==set(operations)
          and {row.value for row in overlay.value_links}==set(values)
          and {(row.operation,row.use) for row in overlay.use_links}=={(op.id,use.id) for op in operations.values() for use in op.uses},
          'prefix/core source correspondence is incomplete')
    _need(all(row.semantic_operation is None and row.opcode is None for row in overlay.operation_links),
          'source SG import is indexed explicitly; do not invent a computational Opcode record')
    protocols={row.operation:row for row in overlay.protocols}
    _need(len(protocols)==len(overlay.protocols),'duplicate prefix protocol')
    def by_kind(kind):
        rows=[operations[p.operation] for p in overlay.protocols if p.kind is kind]
        _need(len(rows)==1,'missing/duplicate prefix protocol '+kind.value);return rows[0]
    root_call=by_kind(ModuleProtocolKind.INVOKE_MODULE_BODY)
    import_call=by_kind(K.INVOKE_IMPORT_PREFIX);tail_call=by_kind(K.INVOKE_REMAINING)
    imp=by_kind(K.IMPORT_NAME_314);store=by_kind(K.STORE_NAME_314);opaque=by_kind(K.UNEXPANDED_SLICE)
    _need((imp.id,store.id,opaque.id)==(prefix.import_operation,prefix.store_operation,remaining.operation), 'prefix protocol indices differ')
    _need([(op.id,op.callee) for op in graph.operations if op.callee is not None]==
          [(op.id,op.callee) for op in graph.operations if op.id in (root_call.id,import_call.id,tail_call.id)],
          'import is not a known fixed callable or another invented activation')
    _need((root_call.callee,import_call.callee,tail_call.callee)==(body,prefix.region,remaining.region)
          and (owners[root_call.id],owners[import_call.id],owners[tail_call.id])==(graph.root,body,body)
          and owners[imp.id]==prefix.region and owners[store.id]==body and owners[opaque.id]==remaining.region,
          'unit/prefix/store/remaining call control order differs')
    ref_type=ValueType(ValueKind.REFERENCE);state_type=ValueType(ValueKind.STATE,location=world)
    def invocation(op,reference_inputs,normal_types):
        _need(op.terminator is not None and op.terminator.kind is TerminatorKind.INVOKE and not op.effects_complete
              and set(op.behaviors)=={Behavior.CONTROL,Behavior.READ,Behavior.WRITE}
              and tuple(use.value for use in op.uses[:-1])==tuple(reference_inputs)
              and op.invoke_arguments==tuple(use.id for use in op.uses)
              and type(values[op.uses[-1].value]) is StateVersionValue and values[op.uses[-1].value].location==world,
              'prefix protocol must use exact ordered refs and whole-world may-raise invocation')
        _need(tuple((row.kind,row.types) for row in op.completions)==
              ((ExitKind.NORMAL,normal_types),(ExitKind.RAISE,(ref_type,state_type)))
              and tuple(edge.kind for edge in op.terminator.successors)==(ExitKind.NORMAL,ExitKind.RAISE)
              and all(edge.arguments==tuple(CompletionResult(i) for i in range(len(signature.types)))
                for edge,signature in zip(op.terminator.successors,op.completions)), 'prefix completion/world signatures differ')
        return tuple(blocks[edge.block] for edge in op.terminator.successors)
    root_normal,root_failure=invocation(root_call,refs[graph.root],(ref_type,state_type))
    import_normal,import_failure=invocation(import_call,refs[body],(ref_type,state_type))
    tail_normal,tail_failure=invocation(tail_call,refs[body],(ref_type,state_type))
    _need(len(imp.uses)==8,'IMPORT_NAME ports differ')
    imported_literals=(node.names[0].name,0,None,'__import__')
    for use,expected in zip(imp.uses[3:-1],imported_literals):
        origin=values[use.value].origin
        _need(type(origin) is LiteralOrigin and type(origin.value) is type(expected) and origin.value==expected,
              'import name/level/fromlist/lookup key differs from original source/compiler')
    _need(tuple(use.value for use in imp.uses[:3])==(refs[prefix.region][2],refs[prefix.region][1],refs[prefix.region][0]),
          'IMPORT_NAME must consume saved builtins/globals/locals, not a reloaded namespace or fixed callee')
    imp_normal,imp_failure=invocation(imp,tuple(use.value for use in imp.uses[:-1]),(ref_type,state_type))
    _need(store.uses[0].value==refs[body][0] and store.uses[2].value==import_normal.arguments[0],
          'import result must flow to exact locals STORE_NAME input')
    key=values[store.uses[1].value].origin
    _need(type(key) is LiteralOrigin and key.value==(node.names[0].asname or node.names[0].name), 'import alias binding key differs')
    store_normal,store_failure=invocation(store,tuple(use.value for use in store.uses[:-1]),(state_type,))
    opaque_normal,opaque_failure=invocation(opaque,refs[remaining.region],(state_type,))
    _need(import_call.uses[-1].value==entries[body].arguments[-1]
          and imp.uses[-1].value==entries[prefix.region].arguments[-1]
          and store.uses[-1].value==import_normal.arguments[-1]
          and tail_call.uses[-1].value==store_normal.arguments[-1]
          and opaque.uses[-1].value==entries[remaining.region].arguments[-1], 'prefix post-world sequencing differs')
    _need(protocols[imp.id].source==source and protocols[store.id].source==source,
          'import and attempted namespace store must retain original Import source, no fake Name node')
    refinements={row.site.operation:row for row in graph.state_address_refinements}
    _need(set(refinements)=={imp.id,store.id} and len(graph.state_address_refinements)==2,
          'only known attempted builtin lookup/locals write may have partial address indices')
    for op,owner_index,key_index,mode in ((imp,0,6,'READ'),(store,0,1,'WRITE')):
        row=refinements[op.id]
        _need(type(row.site) is InvokeStateOperand and row.site.state_use==op.uses[-1].id
              and row.coverage is AddressCoverage.PARTIAL and row.protocol is None and len(row.effects)==1,
              'namespace protocol attempts require partial addresses, not stored-content proof')
        effect=row.effects[0]
        _need(type(effect.owner) is ReferenceOwner and effect.owner.use==op.uses[owner_index].id
              and len(effect.path)==1 and type(effect.path[0]) is NamespaceKey and effect.path[0].key==op.uses[key_index].id
              and effect.mode.value==mode,'namespace attempt address must reference exact owned Uses')
    def completion(block,kind,payload,post_world):
        _need(len(block.operations)==1,'child completion cannot execute residual/source operations after a raised prefix')
        op=operations[block.operations[0]]
        _need(op.terminator is not None and op.terminator.kind is (TerminatorKind.RETURN if kind is ExitKind.NORMAL else TerminatorKind.RAISE)
              and tuple(use.value for use in op.uses)==(payload,post_world)
              and op.terminator.values==tuple(use.id for use in op.uses),'child completion payload/world differs')
    for block in (import_failure,store_failure,tail_failure,imp_failure,opaque_failure):
        completion(block,ExitKind.RAISE,block.arguments[0],block.arguments[-1])
    completion(imp_normal,ExitKind.NORMAL,imp_normal.arguments[0],imp_normal.arguments[-1])
    completion(tail_normal,ExitKind.NORMAL,tail_normal.arguments[0],tail_normal.arguments[-1])
    last=operations[opaque_normal.operations[-1]];payload=values[last.uses[0].value]
    _need(type(payload.origin) is LiteralOrigin and payload.origin.value is None,'remaining exec source normal completion is None')
    completion(opaque_normal,ExitKind.NORMAL,payload.id,opaque_normal.arguments[-1])
    _need(import_normal.operations==(store.id,) and store_normal.operations==(tail_call.id,),
          'import result/store must precede residual; no duplicated whole-body execution')
    consumed=store.uses[2].value
    _need([(op.id,use.id) for op in graph.operations for use in op.uses if use.value==consumed]==[(store.id,store.uses[2].id)],
          'STORE_NAME stack input is consumed on both completions; no stale pending use/free claim')
    first=operations[entries[graph.root].operations[0]]
    _need(protocols[first.id].kind is PythonProtocolKind.FRAME_ENTER
          and tuple(use.value for use in first.uses[:-1])==refs[graph.root]
          and root_call.uses[-1].value==first.results[0], 'mapping frame enter/world differs')
    frames=[]
    for protocol in overlay.protocols:
        _need(protocol.operation in operations and protocol.source==links[protocol.operation].source,'prefix protocol source/core differs')
        if type(protocol.kind) is PythonProtocolKind:
            op=operations[protocol.operation];frames.append(op)
            _need(owners[op.id]==graph.root and protocol.kind in (PythonProtocolKind.FRAME_ENTER,PythonProtocolKind.FRAME_EXIT)
                  and op.terminator is None and not op.effects_complete and len(op.accesses)==1
                  and set(op.behaviors)=={Behavior.READ,Behavior.WRITE,Behavior.MEMORY}, 'children are not Python frames; conditional lifetime contract differs')
            access=op.accesses[0]
            _need(access.mode.value=='READ_WRITE' and not access.full_overwrite and access.reference is None and op.results==(access.after,), 'frame whole-world update differs')
            if protocol.kind is PythonProtocolKind.FRAME_EXIT:
                block=next(block for block in blocks.values() if op.id in block.operations)
                end=operations[block.operations[-1]]
                _need(block.operations[-2]==op.id and tuple(use.value for use in op.uses[1:-1])==refs[graph.root]
                      and tuple(use.value for use in end.uses)==(op.uses[0].value,op.results[0]), 'frame exit must preserve payload/namespaces without consumed store temporary')
    _need(len(frames)==3 and len(protocols)==9,'prefix requires its closed protocol/conditional frame partition')
    _need(set(protocols)|{op.id for op in graph.operations if op.terminator is not None
          and op.terminator.kind in (TerminatorKind.RETURN,TerminatorKind.RAISE)}==set(operations), 'undeclared prefix internal operation')
    _need(any(f.kind=='REQUIRED_EXPANSION' for f in overlay.frontiers)
          and any(f.kind=='IMPORT_INTERNALS_REQUIRED_EXPANSION' and f.source==source for f in overlay.frontiers)
          and any(f.kind=='NAMESPACE_CONTENT_UNPROVEN' for f in overlay.frontiers), 'import/residual/content debt cannot be discharged by normal completion')


def require_valid_structured_module_program(result,*,source_texts,code_evidence=None,max_operations=10000):
    """SP8 B contract. No producer replay, packet inference or actual ABI proof."""
    from pathlib import Path
    import dis
    from scar.analysis.program_lowering import PreparedSource
    from scar.analysis.source_module_lowering import (module_unit,module_source_census,module_source_context,
        require_root_evidence,mapping_prefix_selection,frame_statement_slice,_module_statement_ref)
    from scar.analysis.source_semantics_v2 import validate_source_semantics
    from scar.analysis.control_flow_v2 import validate_source_control_flow
    from scar.ir.program.module_entries import (StructuredFrameBodyOverlay,FrameBodyProfile,
        FrameBodyProtocolKind as K,StatementSequenceField as F,FrameCompletionProfile,
        NamespacePolicy,encode_frame_body,decode_frame_body)
    from scar.ir.program.source_subjects import MappingFramePorts,FrameKind
    from scar.ir.program.control import ControlScopeKind
    from scar.ir.program.state_addresses import (InvokeStateOperand,ReferenceOwner,NamespaceKey,AddressCoverage)
    from scar.ir.program.validation import require_valid
    overlay=result.module
    _need(type(overlay) is StructuredFrameBodyOverlay and decode_frame_body(encode_frame_body(overlay))==overlay,'SP8 needs its closed typed overlay')
    paired=result.profile is FrameBodyProfile.STRUCTURED_MAPPING_PROPAGATION_314_V1
    _need(result.profile in (FrameBodyProfile.STRUCTURED_MAPPING_314_V1,FrameBodyProfile.STRUCTURED_MAPPING_PROPAGATION_314_V1) and overlay.profile is result.profile
          and overlay.namespace_policy is NamespacePolicy.MODULE_MAPPING_314_V1
          and overlay.completion_profile is (FrameCompletionProfile.PROPAGATION_REF_PAIR_314_V1 if paired else FrameCompletionProfile.RAW_EXCEPTION_REF_314_V1)
          and all(value is None for value in (result.interface,result.frame,result.structured,result.language)),
          'SP8 mapping profile cannot acquire a function ABI or packet-completion claim')
    unit=overlay.declaration.unit
    _need(result.metadata==LoweringMetadata(unit.initializer.wire,unit.snapshot),'SP8 metadata invented function/source atoms')
    _need(type(source_texts) is dict and unit.snapshot.path in source_texts,'SP8 needs explicit retained source text, no live fallback')
    text=source_texts[unit.snapshot.path]
    _need(type(text) is str and 'sha256:'+sha256(text.encode()).hexdigest()==unit.snapshot.fingerprint,'SP8 retained source fingerprint differs')
    _need(set(result.semantics.sources)==set(result.control.sources)=={unit.snapshot.path},'SP8 source collection differs')
    result.semantic.assert_valid()
    for check in (validate_source_semantics(result.semantics,result.semantic,sources=source_texts),
                  validate_source_control_flow(result.control,result.semantic,result.semantics,sources=source_texts)):
        _need(check['valid'],'; '.join(check.get('errors',())))
    context=PreparedSource(Path(unit.snapshot.path),Path(unit.namespace_root),text,result.semantic,result.semantics,result.control,
        ast.parse(text,filename=unit.snapshot.path),{})
    _need(module_unit(context)==unit and module_source_census(context)==overlay.census,'SP8 original MODULE census differs')
    from scar.ir.program.module_entries import StaticModuleEntryDeclaration
    from scar.ir.program.source_subjects import SourceCompilationFrameRoot, FrameRoot
    static_root = type(overlay.declaration) is StaticModuleEntryDeclaration
    if static_root:
        # Independently recompile retained text. The declaration is a receipt,
        # never permission to trust its code path or borrow a runtime witness.
        from scar.analysis.static_compilation import compile_source_unit, StaticCodeEvidence
        replayed = compile_source_unit(context).for_module(unit)
        _need(replayed.to_reference() == overlay.declaration.compilation,
              'static module declaration differs from independently compiled retained source')
        if code_evidence is not None:
            _need(type(code_evidence) is StaticCodeEvidence and
                  require_root_evidence(unit,code_evidence) == replayed.to_reference(),
                  'supplied static module compiler input differs')
        code_evidence = replayed
    else:
        _need(code_evidence is not None and require_root_evidence(unit,code_evidence)==overlay.declaration.witness,
              'SP8 requires exact readonly whole-root evidence, not a code-name or report boolean')
    prefix,tail=mapping_prefix_selection(context,code_evidence,profile=result.profile)
    _need(overlay.prefix==(frame_statement_slice(context,unit,F.BODY,prefix) if prefix else None),'SP8 prefix is not the mechanical maximal supported collection')
    _need((overlay.remaining is not None)==bool(tail),'SP8 missing/extra remaining source collection')
    if tail:
        _need(overlay.remaining.subject==frame_statement_slice(context,unit,F.BODY,tail)
              and overlay.remaining.required_expansion.value=='REQUIRED','SP8 residual membership/context/control range differs')
    graph=result.graph;_need(graph is not None,'proved mapping root cannot silently disappear')
    require_valid(graph)
    _need(type(max_operations) is int and 1<=max_operations<=100000
          and len(graph.operations)==overlay.operations_emitted<=max_operations,'SP8 operation budget/count differs')
    _need(not any((graph.environments,graph.function_entries,graph.binding_definitions,graph.binding_reads,
          graph.resumable_bodies,graph.stored_value_writes,graph.stored_value_reads,
          graph.call_effect_expansions)), 'B raw-reference profile cannot claim function/pending/cleanup/stored-content effects')
    if not paired:_need(not any((graph.control_ports,graph.exception_packets,graph.pending_completions,graph.handled_context_domains,
          graph.cleanup_interfaces,graph.cleanup_enters,graph.cleanup_resumes,graph.cleanup_replacements,
          graph.handled_context_reads)) and len(graph.control_scopes)==1,'B raw-reference profile cannot acquire C0/C1 propagation')
    _need(len(graph.frame_roots)==1,'SP8 has exactly one actual frame authority')
    root=graph.frame_roots[0];scope=next((row for row in graph.control_scopes if row.id==root.scope),None)
    _need(scope is not None,'missing actual frame root scope')
    _need(type(root) is (SourceCompilationFrameRoot if static_root else FrameRoot)
          and root.scope==scope.id==overlay.root_scope and root.kind is FrameKind.MODULE
          and root.code==(overlay.declaration.compilation if static_root else code_evidence.captured)
          and scope.kind is ControlScopeKind.FRAME and scope.source==unit and scope.region==graph.root
          and type(root.entry) is MappingFramePorts and not root.entry.closure_cells,
          'SP8 root source/code/namespace ABI differs; empty closure is this source profile only')
    regions={row.id:row for row in graph.regions};operations={row.id:row for row in graph.operations}
    values={row.id:row for row in graph.values};blocks={row.id:row for region in graph.regions for row in region.blocks}
    owners={op:region.id for region in graph.regions for block in region.blocks for op in block.operations}
    region=regions[graph.root];entry=blocks[region.entry];abi=root.entry
    refs=(abi.locals_namespace,abi.globals_namespace,abi.builtins_namespace)
    world=values[abi.world].location;ref_type=ValueType(ValueKind.REFERENCE);state_type=ValueType(ValueKind.STATE,location=world)
    links={row.operation:row for row in overlay.operation_links};protocols={row.operation:row for row in overlay.protocols}
    def original(source):
        if type(source) is ModuleUnitSource:return source==unit
        atom=result.semantic.source_atoms.get(source.atom_id) if type(source) is SourceReference else None
        return atom is not None and atom.reference==source and source.path==unit.snapshot.path
    _need(len(links)==len(overlay.operation_links) and set(links)==set(operations)
          and len(protocols)==len(overlay.protocols) and set(protocols)<=set(operations)
          and {row.value for row in overlay.value_links}==set(values)
          and {(row.operation,row.use) for row in overlay.use_links}=={(op.id,use.id) for op in graph.operations for use in op.uses},
          'SP8 correspondence/core endpoints are incomplete')
    _need(all(original(row.source) for rows in (overlay.operation_links,overlay.value_links,overlay.use_links,overlay.protocols,overlay.frontiers)
          for row in rows),'SP8 invented a source reference')
    for link in overlay.operation_links:
        if link.semantic_operation is not None:
            definition=result.semantic.definitions.get(link.semantic_operation)
            _need(type(link.source) is SourceReference and definition is not None
                  and definition.code_id==link.source.atom_id.wire and link.source.atom_id in definition.source_atoms,
                  'SP8 SG/source identity join differs')
    for protocol in overlay.protocols:_need(protocol.source==links[protocol.operation].source,'SP8 protocol/source endpoint differs')
    def invoke(op,normal_types):
        _need(op.terminator is not None and op.terminator.kind is TerminatorKind.INVOKE and not op.effects_complete
              and set(op.behaviors)=={Behavior.CONTROL,Behavior.READ,Behavior.WRITE}
              and op.invoke_arguments==tuple(use.id for use in op.uses)
              and tuple((row.kind,row.types) for row in op.completions)==
              ((ExitKind.NORMAL,normal_types),(ExitKind.RAISE,((ref_type,ref_type,state_type) if paired else (ref_type,state_type))))
              and tuple(edge.kind for edge in op.terminator.successors)==(ExitKind.NORMAL,ExitKind.RAISE)
              and all(edge.arguments==tuple(CompletionResult(i) for i in range(len(signature.types)))
                  for edge,signature in zip(op.terminator.successors,op.completions)), 'SP8 invocation raw completion/world signature differs')
        return tuple(blocks[edge.block] for edge in op.terminator.successors)
    def literal(use,expected):
        origin=values[use.value].origin
        _need(type(origin) is LiteralOrigin and type(origin.value) is type(expected) and origin.value==expected,
              'SP8 namespace/import literal key differs')
    refinements={row.site.operation:row for row in graph.state_address_refinements}
    expected_addresses=set()
    nodes={};expression_nodes={}
    for node in ast.walk(context.tree):
        if isinstance(node,(ast.expr,ast.stmt,ast.ExceptHandler)):
            try:reference=_module_statement_ref(context,node)
            except ValueError:continue  # Unvisited source gaps do not acquire fabricated atoms.
            (expression_nodes if isinstance(node,ast.expr) else nodes)[reference]=node
    instructions=tuple(dis.get_instructions(code_evidence.code,adaptive=False,show_caches=False))
    imports_by_source={}
    for protocol in overlay.protocols:
        op=operations[protocol.operation];kind=protocol.kind
        if type(kind) is not K:continue
        if kind in (K.MATCH_EXCEPTION_BORROWED_314,K.FRAME_EXIT_EXCEPTION_PACKET):
            _need(paired,'RAW profile cannot acquire propagation frame/matcher primitives')
            continue
        normal_types=(state_type,) if kind in (K.STORE_NAME_314,K.DELETE_NAME_314,K.UNEXPANDED_SLICE) else (ref_type,state_type)
        invoke(op,normal_types)
        if kind is K.LOAD_NAME_314:
            node=expression_nodes.get(protocol.source)
            _need(isinstance(node,ast.Name) and len(op.uses)==5 and tuple(use.value for use in op.uses[:3])==refs,
                  'LOAD_NAME must retain named L/G/savedB and exact Name source')
            literal(op.uses[3],node.id);expected_addresses.add(op.id)
            expected=[(i,3,'READ') for i in range(3)]
        elif kind is K.STORE_NAME_314:
            _need(len(op.uses)==4 and op.uses[0].value==abi.locals_namespace,'STORE_NAME must target declared L, not fast locals/G')
            node=expression_nodes.get(protocol.source) or nodes.get(protocol.source)
            if isinstance(node,ast.Name):literal(op.uses[1],node.id)
            else:
                _need(isinstance(node,(ast.Import,ast.ImportFrom)) or paired and isinstance(node,ast.ExceptHandler),'STORE_NAME source must be an original binding/import/handler')
                allowed=[node.name] if isinstance(node,ast.ExceptHandler) else [alias.asname or alias.name for alias in node.names]
                _need(type(values[op.uses[1].value].origin) is LiteralOrigin and values[op.uses[1].value].origin.value in allowed,'import alias STORE_NAME key differs')
            expected_addresses.add(op.id);expected=[(0,1,'WRITE')]
        elif kind is K.IMPORT_NAME_314:
            node=nodes.get(protocol.source)
            _need(isinstance(node,(ast.Import,ast.ImportFrom)) and len(op.uses)==8
                  and tuple(use.value for use in op.uses[:3])==tuple(reversed(refs)) and op.callee is None,
                  'IMPORT_NAME uses savedB/G/L, not a fixed callable/module object')
            literal(op.uses[6],'__import__')
            index=imports_by_source.get(protocol.source,0);imports_by_source[protocol.source]=index+1
            requested=node.names[index].name if isinstance(node,ast.Import) else node.module or ''
            literal(op.uses[3],requested);literal(op.uses[4],0 if isinstance(node,ast.Import) else node.level)
            if isinstance(node,ast.Import):literal(op.uses[5],None)
            else:
                fromlist=values[op.uses[5].value]
                _need(type(fromlist.origin) is OperationResult,'IMPORT_NAME fromlist must come from its typed code-constant read')
                constants=[row for row in overlay.constants if fromlist.origin.operation==row.operation]
                _need(len(constants)==1 and constants[0].source==protocol.source
                      and len(constants[0].constant_path)==1
                      and constants[0].constant_path[0]<len(code_evidence.code.co_consts)
                      and code_evidence.code.co_consts[constants[0].constant_path[0]]==tuple(alias.name for alias in node.names),
                      'IMPORT_NAME fromlist must be this exact whole-root typed code constant')
            _need(any(row.opname=='IMPORT_NAME' and row.argval==requested and tuple(row.positions)==
                  (node.lineno,node.end_lineno,node.col_offset,node.end_col_offset) for row in instructions),
                  'import interface has no matching original root opcode/source span')
            expected_addresses.add(op.id);expected=[(0,6,'READ')]
        elif kind is K.IMPORT_FROM_314:
            _need(isinstance(nodes.get(protocol.source),ast.ImportFrom) and len(op.uses)==3 and op.callee is None,
                  'IMPORT_FROM must keep its original source and dynamic receiver/key')
            expected=None
        elif kind is K.DELETE_NAME_314:
            node=nodes.get(protocol.source)
            _need(paired and isinstance(node,ast.ExceptHandler) and node.name and len(op.uses)==3
                  and op.uses[0].value==abi.locals_namespace,'handler deletion needs original as-name and L')
            literal(op.uses[1],node.name);expected_addresses.add(op.id);expected=[(0,1,'WRITE')]
        elif kind is K.VALIDATE_EXCEPT_TYPE_314:
            _need(paired and isinstance(nodes.get(protocol.source),ast.ExceptHandler) and len(op.uses)==2,
                  'handler validation needs its original source and dynamic handler ref')
            expected=None
        else:expected=None
        if expected is not None:
            row=refinements.get(op.id)
            _need(row is not None and type(row.site) is InvokeStateOperand and row.site.state_use==op.uses[-1].id
                  and row.coverage is AddressCoverage.PARTIAL and row.protocol is None and len(row.effects)==len(expected),
                  'namespace access must remain partial attempted address on this exact invoke state')
            for effect,(owner,key,mode) in zip(row.effects,expected):
                _need(type(effect.owner) is ReferenceOwner and effect.owner.use==op.uses[owner].id
                      and len(effect.path)==1 and type(effect.path[0]) is NamespaceKey
                      and effect.path[0].key==op.uses[key].id and effect.mode.value==mode,'SP8 attempted namespace role/key differs')
    _need(set(refinements)>=expected_addresses,'SP8 namespace attempted addresses missing')
    # Exact original prefix/nested statement coverage, with actual owned operations.
    expected_statements=[]
    def descend(node):
        expected_statements.append(node)
        if isinstance(node,ast.For):
            for child in (*node.body,*node.orelse):descend(child)
        if paired and isinstance(node,ast.Try):
            for child in node.body:descend(child)
            for handler in node.handlers:
                for child in handler.body:descend(child)
    for node in prefix:descend(node)
    expansions={row.source:row for row in overlay.expansions}
    _need(len(expansions)==len(overlay.expansions) and set(expansions)=={_module_statement_ref(context,node) for node in expected_statements},
          'SP8 expanded source members are missing/extra/duplicated')
    for node in expected_statements:
        expansion=expansions[_module_statement_ref(context,node)]
        expected_children=tuple(frame_statement_slice(context,expansion.source,field,getattr(node,name))
            for name,field in (('body',F.BODY),('orelse',F.ORELSE)) if isinstance(node,ast.For) and getattr(node,name))
        if paired and isinstance(node,ast.Try):
            expected_children=(frame_statement_slice(context,expansion.source,F.BODY,node.body),)+tuple(
                frame_statement_slice(context,_module_statement_ref(context,handler),F.HANDLER_BODY,handler.body) for handler in node.handlers)
        _need(expansion.region==graph.root and expansion.child_slices==expected_children
              and expansion.entry in blocks and expansion.normal in blocks
              and expansion.entry in {block.id for block in region.blocks}
              and expansion.normal in {block.id for block in region.blocks}
              and len(set(expansion.operations))==len(expansion.operations)
              and all(identity in operations and owners[identity]==graph.root for identity in expansion.operations),
              'SP8 statement/recursive slice operations differ')
        if not isinstance(node,ast.Pass):_need(bool(expansion.operations),'expanded non-Pass statement has no data/control operations')
    def ordered_statements(nodes,initial=None):
        previous=initial
        for node in nodes:
            expansion=expansions[_module_statement_ref(context,node)]
            if previous is not None:_need(expansion.entry==previous,'source statement normal continuation is reordered/disconnected')
            previous=expansion.normal
        return previous
    last_normal=ordered_statements(prefix,entry.id)
    # Derive expression results only from actual producer ports/literals.
    def expression_value(node):
        source=_module_statement_ref(context,node)
        if isinstance(node,ast.Constant):
            candidates={row.value for row in overlay.value_links if row.source==source
                and isinstance(values[row.value],ReferenceValue) and type(values[row.value].origin) is LiteralOrigin
                and type(values[row.value].origin.value) is type(node.value) and values[row.value].origin.value==node.value}
            _need(len(candidates)==1,'scalar source expression has no unique exact literal reference')
            return next(iter(candidates))
        constant=[row for row in overlay.constants if row.source==source]
        if constant:
            _need(len(constant)==1,'code-constant source expression is ambiguous')
            return operations[constant[0].operation].results[0]
        candidates=[op for op in graph.operations if owners[op.id]==graph.root and links[op.id].source==source
            and op.terminator is not None and op.terminator.kind is TerminatorKind.INVOKE
            and (links[op.id].semantic_operation is not None
                 or op.id in protocols and protocols[op.id].kind is K.LOAD_NAME_314)]
        _need(len(candidates)==1,'source expression needs its unique canonical invocation')
        op=candidates[0];normal,_=invoke(op,(ref_type,state_type))
        if isinstance(node,ast.Name):return normal.arguments[0]
        children=([node.left,node.right] if isinstance(node,ast.BinOp) else [node.operand] if isinstance(node,ast.UnaryOp)
            else [node.left,node.comparators[0]] if isinstance(node,ast.Compare) else [node.value] if isinstance(node,ast.Attribute)
            else [node.value,node.slice] if isinstance(node,ast.Subscript) else list(node.elts) if isinstance(node,(ast.List,ast.Tuple))
            else [node.func,*node.args,*(keyword.value for keyword in node.keywords)] if isinstance(node,ast.Call) else None)
        _need(children is not None and tuple(use.value for use in op.uses[:-1])==tuple(expression_value(child) for child in children),
              'source expression ordered operand graph differs')
        return normal.arguments[0]
    def store_at(source):
        found=[operations[p.operation] for p in overlay.protocols if p.kind is K.STORE_NAME_314 and p.source==source]
        _need(len(found)==1,'source binding has no unique mapping store attempt')
        return found[0]
    for node in expected_statements:
        source=_module_statement_ref(context,node)
        if isinstance(node,ast.Assign):
            store=store_at(_module_statement_ref(context,node.targets[0]))
            _need(store.uses[2].value==expression_value(node.value),'RHS must feed its exact namespace store')
        elif isinstance(node,ast.Expr):
            discard=[operations[p.operation] for p in overlay.protocols if p.kind is PythonProtocolKind.FRAME_DISCARD and p.source==source]
            _need(len(discard)==1 and discard[0].uses[0].value==expression_value(node.value),'expression result must feed its exact discard')
        elif isinstance(node,ast.For):
            iterator_ops=[operations[p.operation] for p in overlay.protocols if p.kind is PythonProtocolKind.GET_ITERATOR
                and p.source==_module_statement_ref(context,node.iter)]
            _need(len(iterator_ops)==1 and iterator_ops[0].uses[0].value==expression_value(node.iter),'for iterable eager evaluation differs')
            iterator=invoke(iterator_ops[0],(ref_type,state_type))[0].arguments[0]
            advances=[operations[p.operation] for p in overlay.protocols if p.kind is PythonProtocolKind.ADVANCE_ITERATOR and p.source==source]
            _need(len(advances)==1 and advances[0].uses[0].value==iterator,'for advance must drive this same iterator')
            item=invoke(advances[0],(ref_type,state_type))[0].arguments[0]
            target=store_at(_module_statement_ref(context,node.target));body_entry=invoke(target,(state_type,))[0]
            _need(target.uses[2].value==item,'for item must feed its exact mapping target store')
            ordered_statements(node.body,body_entry.id)
        elif isinstance(node,(ast.Import,ast.ImportFrom)):
            imported=[operations[p.operation] for p in overlay.protocols if p.kind is K.IMPORT_NAME_314 and p.source==source]
            stores=[operations[p.operation] for p in overlay.protocols if p.kind is K.STORE_NAME_314 and p.source==source]
            _need(len(imported)==(len(node.names) if isinstance(node,ast.Import) else 1) and len(stores)==len(node.names),
                  'import alias/protocol inventory differs')
            if isinstance(node,ast.Import):
                for imp,store in zip(imported,stores):
                    normal,_=invoke(imp,(ref_type,state_type))
                    _need(store.uses[2].value==normal.arguments[0] and store.uses[-1].value==normal.arguments[-1],
                          'import result/post-world must feed its own alias store')
            else:
                receiver=invoke(imported[0],(ref_type,state_type))[0].arguments[0]
                froms=[operations[p.operation] for p in overlay.protocols if p.kind is K.IMPORT_FROM_314 and p.source==source]
                _need(len(froms)==len(node.names),'IMPORT_FROM alias inventory differs')
                for member,frm,store in zip(node.names,froms,stores):
                    literal(frm.uses[1],member.name);normal,_=invoke(frm,(ref_type,state_type))
                    _need(frm.uses[0].value==receiver and store.uses[2].value==normal.arguments[0]
                          and store.uses[-1].value==normal.arguments[-1],'from receiver/result/store sequencing differs')
    for protocol in overlay.protocols:
        if protocol.kind is K.STORE_NAME_314:
            store=operations[protocol.operation];consumed=store.uses[2].value
            if paired and isinstance(nodes.get(protocol.source),ast.ExceptHandler):continue
            _need([(op.id,use.id) for op in graph.operations for use in op.uses if use.value==consumed]==[(store.id,store.uses[2].id)],
                  'STORE_NAME consumed stack input must not remain pending on either completion')
    # Constant references remain the original typed whole-root code-slot records.
    instructions=tuple(dis.get_instructions(code_evidence.code,adaptive=False,show_caches=False))
    for constant in overlay.constants:
        _need(constant.code_key==root.code.key and len(constant.constant_path)==1 and constant.operation in operations
              and protocols[constant.operation].kind is PythonProtocolKind.READ_CODE_CONSTANT,'SP8 code-constant record lost its original identity/primitive')
        matches=[row for row in instructions if row.opname=='LOAD_CONST' and row.arg==constant.constant_path[0]
            and tuple(row.positions)==(constant.source.start_line,constant.source.end_line,constant.source.start_column,constant.source.end_column)]
        _need(len(matches)==1 and type(matches[0].argval) in (tuple,slice)
              and code_evidence.code.co_consts[matches[0].arg] is matches[0].argval,'SP8 whole-root code constant slot/span differs')
        _need(owners[constant.operation]==graph.root,'code constant must belong to this actual module frame')
    _need({row.operation for row in overlay.constants}=={p.operation for p in overlay.protocols if p.kind is PythonProtocolKind.READ_CODE_CONSTANT},'SP8 typed code constant inventory incomplete')
    for loop in overlay.loops:
        _need(loop.region==graph.root and not loop.bindings and loop.source in expansions,
              'module loop must use mapping stores, not function slot SSA')
        for edge in loop.backedges:_need(edge.operation in operations,'loop backedge must refer to existing CFG')
    if tail:
        residual=overlay.remaining
        _need(len(regions)==2 and residual.region!=graph.root and regions[residual.region].parent==graph.root,
              'remaining slice is a computation Region, not another Python frame')
        _need(residual.operation in protocols and protocols[residual.operation].kind is K.UNEXPANDED_SLICE,
              'remaining exact source interface missing')
        calls=[op for op in graph.operations if op.callee is not None]
        _need(len(calls)==1 and calls[0].callee==residual.region and protocols[calls[0].id].kind is K.INVOKE_REMAINING,
              'remaining source must run once after the actual prefix, not a duplicate whole body')
        if last_normal is not None:_need(calls[0].id in blocks[last_normal].operations,'remaining source must begin at prefix normal continuation')
    else:_need(len(regions)==1 and not any(op.callee is not None for op in graph.operations),'extra source computation Region')
    _need(any(frontier.kind=='ENTRY_PROTOCOL_UNPROVEN' for frontier in overlay.frontiers)
          and any(frontier.kind=='NAMESPACE_CONTENT_UNPROVEN' for frontier in overlay.frontiers)
          and (not tail or any(frontier.kind=='REQUIRED_EXPANSION' for frontier in overlay.frontiers)),
          'SP8 cannot silently discharge namespace/runtime/residual obligations')
    if paired:require_valid_module_propagation(result,context=context,code_evidence=code_evidence)


def require_valid_module_propagation(result,*,context,code_evidence):
    """Source C: derive provenance and cleanup order from canonical endpoints."""
    from scar.ir.program.module_entries import FrameBodyProtocolKind as K
    from scar.ir.program.control import (ProtocolValueKind as P,ControlScopeKind as S,LanguageCompletionKind as L,
        PendingDispatchTerminator)
    from scar.ir.program.cleanup import CleanupRouteTerminator
    from scar.ir.program.model import ProtocolValue,UseRole
    from scar.analysis.source_module_lowering import _module_statement_ref
    graph=result.graph;overlay=result.module
    values={v.id:v for v in graph.values};ops={o.id:o for o in graph.operations}
    blocks={b.id:b for region in graph.regions for b in region.blocks}
    owners={b:s.id for s in graph.control_scopes for b in s.blocks}
    scopes={s.id:s for s in graph.control_scopes}
    op_blocks={op:b.id for b in blocks.values() for op in b.operations}
    protocols={p.operation:p for p in overlay.protocols}
    all_uses={use.id:use for op in graph.operations for use in op.uses}
    # Only actual RAISE completion pairs seed provenance. Propagate pairs together
    # over original Uses, never by class/name/hash equality or an evidence boolean.
    pairs=set();incoming={b:[] for b in blocks}
    for op in graph.operations:
        term=op.terminator
        if term is None:continue
        for edge in term.successors:incoming[edge.block].append((op,edge))
        if term.kind is TerminatorKind.INVOKE:
            edge=next(edge for edge in term.successors if edge.kind is ExitKind.RAISE)
            pairs.add(tuple(blocks[edge.block].arguments[:2]))
    changed=True
    while changed:
        changed=False
        for block in blocks.values():
            refs=[v for v in block.arguments if isinstance(values[v],ReferenceValue)]
            if len(refs)!=2 or tuple(refs) in pairs or not incoming[block.id]:continue
            positions=[block.arguments.index(v) for v in refs]
            sources=[]
            for op,edge in incoming[block.id]:
                actual=[edge.arguments[index] for index in positions]
                if not all(use in {u.id for u in op.uses} for use in actual):sources.append(None)
                else:sources.append(tuple(all_uses[use].value for use in actual))
            if all(pair in pairs for pair in sources):pairs.add(tuple(refs));changed=True
    for declaration in graph.exception_packets:
        pair=(all_uses[declaration.exception].value,all_uses[declaration.traceback].value)
        _need(pair in pairs,'packet must preserve one actual invocation/forwarded propagation pair; no guessed traceback')
    frame=graph.frame_roots[0];abi=frame.entry
    frame_exits={p.operation for p in overlay.protocols if p.kind is K.FRAME_EXIT_EXCEPTION_PACKET}
    for identity in frame_exits:
        op=ops[identity];packet=values[op.uses[0].value]
        _need(isinstance(packet,ProtocolValue) and packet.protocol is P.EXCEPTION_PACKET
              and op.uses[0].role is UseRole.PROTOCOL
              and tuple(use.value for use in op.uses[1:4])==(abi.locals_namespace,abi.globals_namespace,abi.builtins_namespace)
              and all(isinstance(values[use.value],ReferenceValue) for use in op.uses[1:-1])
              and op.terminator is None and op.callee is None and not op.effects_complete
              and set(op.behaviors)=={Behavior.READ,Behavior.WRITE,Behavior.MEMORY}
              and len(op.accesses)==1 and op.accesses[0].mode.value=='READ_WRITE'
              and op.accesses[0].before==op.uses[-1].id and op.results==(op.accesses[0].after,),
              'packet frame-exit must retain its real protocol aggregate/refs and current world, without pending escape')
        block=blocks[op_blocks[identity]];last=ops[block.operations[-1]]
        _need(owners[block.id]==frame.scope and block.operations==(op.id,last.id)
              and last.terminator.kind is TerminatorKind.RAISE and last.terminator.exit=='raise'
              and tuple(use.value for use in last.uses)==(packet.id,op.results[0]),
              'frame closing landing must raise the identical selected packet with its post-world')
    for region in graph.regions:
        if region.id!=graph.root:continue
        for block in region.blocks:
            last=ops[block.operations[-1]]
            if last.terminator.kind is TerminatorKind.RAISE:
                _need(len(block.operations)==2 and block.operations[0] in frame_exits,'module raise bypassed packet-preserving frame close')
    for port in graph.control_ports:
        if port.kind is L.RAISE:
            _need(port.block in blocks and port.scope==frame.scope
                  and blocks[port.block].operations[0] in frame_exits and port.exit is None,
                  'C source Raise port is its explicit frame-closing block landing, never a relaxed exit shim')
    # A paired profile never routes a symbolic traceback via Python attribute lookup.
    _need(not graph.handled_context_reads,'C does not need a new context-read/source-sys.exception authority')
    interfaces={row.scope:row for row in graph.cleanup_interfaces}
    enters={row.cleanup:row for row in graph.cleanup_enters}
    packets={row.value:row for row in graph.exception_packets}
    pending={row.value:row for row in graph.pending_completions}
    nodes={_module_statement_ref(context,node):node for node in ast.walk(context.tree) if isinstance(node,ast.ExceptHandler)}
    def reachable(start,stop_actions=True):
        seen=set();queue=[start]
        action_ops={row.operation for row in (*graph.cleanup_resumes,*graph.cleanup_replacements)}
        while queue:
            identity=queue.pop()
            if identity in seen:continue
            seen.add(identity);block=blocks[identity]
            if stop_actions and any(op in action_ops for op in block.operations):continue
            term=ops[block.operations[-1]].terminator
            queue.extend(edge.block for edge in term.successors)
        return seen
    for cleanup,interface in interfaces.items():
        source=scopes[cleanup].source;handler=nodes.get(source)
        _need(handler is not None and scopes[cleanup].kind is S.CLEANUP,'cleanup must correspond to the original ExceptHandler atom')
        entry=blocks[interface.entry];enter=enters[cleanup]
        _need(len(entry.arguments)==3 and isinstance(values[entry.arguments[1]],ReferenceValue),
              'caught exception is an actual handler entry Reference, separate from pending/context')
        caught=entry.arguments[1]
        protected=scopes[interface.protected]
        gate_blocks=[blocks[b] for b in protected.blocks]
        _need(len(gate_blocks)==1,'caught propagation gate must retain its one original incoming pair')
        gate=gate_blocks[0];route=ops[gate.operations[-1]]
        _need(type(route.terminator) is CleanupRouteTerminator and len(route.terminator.successors)==1,'handler entry must use the canonical C1 route')
        edge=route.terminator.successors[0]
        token=all_uses[edge.arguments[0]].value;packet_value=all_uses[pending[token].payload].value
        declaration=packets[packet_value]
        _need(edge.block==entry.id and all_uses[edge.arguments[1]].value==all_uses[declaration.exception].value,
              'handler exception reference must come from this same packet constructor, not a parallel identity guess')
        if handler.type is not None:
            matchers=[row for row in graph.exception_matches if protocols.get(row.operation) is not None and protocols[row.operation].source==source]
            _need(len(matchers)==1 and matchers[0].raise_result is None
                  and all_uses[matchers[0].input_use].value==caught
                  and protocols[matchers[0].operation].kind is K.MATCH_EXCEPTION_BORROWED_314,
                  'handler needs the original normal-only borrowed matcher, with type errors on the separate paired operation')
            validations=[ops[p.operation] for p in overlay.protocols if p.kind is K.VALIDATE_EXCEPT_TYPE_314 and p.source==source]
            _need(len(validations)==1,'dynamic handler type validation/error protocol missing')
            handler_operand=all_uses[matchers[0].handler.use].value
            normal_edge=validations[0].terminator.successors[0]
            _need(handler_operand==blocks[normal_edge.block].arguments[0],'matcher must consume this validation normal result port')
        stores=[ops[p.operation] for p in overlay.protocols if p.kind is K.STORE_NAME_314 and p.source==source]
        deletes=[ops[p.operation] for p in overlay.protocols if p.kind is K.DELETE_NAME_314 and p.source==source]
        if not handler.name:_need(not stores and not deletes,'bare handler invented an as-name cleanup');continue
        binding=[op for op in stores if op.uses[2].value==caught]
        clears=[op for op in stores if type(values[op.uses[2].value].origin) is LiteralOrigin
                and values[op.uses[2].value].origin.value is None]
        _need(len(binding)==1 and len(clears) in (1,2) and len(deletes)==len(clears),'as binding and actual cleanup paths are incomplete')
        binding_failure=binding[0].terminator.successors[1].block
        before_restore=reachable(binding_failure)
        _need(not any(op_blocks[op.id] in before_restore for op in (*clears,*deletes)),
              'binding failure must not execute name-clear protection that was not entered')
        for clear in clears:
            normal=blocks[clear.terminator.successors[0].block]
            following=[op for op in deletes if op.id in normal.operations]
            _need(len(following)==1 and following[0].uses[-1].value==normal.arguments[-1],
                  'handler cleanup must perform None-store then delete on its exact normal post-world')
            owner=owners[op_blocks[clear.id]]
            _need(owner in (cleanup,scopes[cleanup].parent),'name clear escaped its normal/exceptional lexical corridor')
        _need(any(owners[op_blocks[clear.id]]==scopes[cleanup].parent for clear in clears),
              'normal handler must restore ambient before name clear')
        # All C1 private context/token forwarding, LIFO, freshness and actual
        # current-state edges already passed the ordinary core/C0/C1 validators.
    _need(len(graph.cleanup_enters)==len(graph.cleanup_interfaces),'C cannot omit context entry for an expanded handler')
