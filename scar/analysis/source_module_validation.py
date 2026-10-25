"""Independent SourceProgram6 entry/core/source checks, never runtime authority."""
from __future__ import annotations

import ast
from hashlib import sha256

from scar.ir.program.module_entries import (ModuleBodyOverlay, ModuleBodyStatus, ModuleUnitSource,
    ModuleProtocolKind, ModuleEntryProfile, encode_module_overlay, decode_module_overlay)
from scar.ir.program.model import (Behavior, BlockArgument, CompletionResult, ExitKind,
    LiteralOrigin, ReferenceValue, StateVersionValue, TerminatorKind, ValueKind, ValueType)
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
        from scar.ir.program.module_entries import ModulePrefixOverlay
        checker = require_valid_module_prefix if type(result.module) is ModulePrefixOverlay else require_valid_module_program
        checker(result, source_texts=source_texts, code_evidence=code_evidence,
                max_operations=max_operations)
    except (ValueError,TypeError,KeyError,AttributeError,OSError,SyntaxError,RecursionError) as error:
        return {'valid':False,'errors':[str(error)]}
    return {'valid':True,'errors':[], 'verification':'STRUCTURE',
        'compiler_root_witness_replayed':code_evidence is not None,
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
