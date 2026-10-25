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
        require_valid_module_program(result, source_texts=source_texts, code_evidence=code_evidence,
                                     max_operations=max_operations)
    except (ValueError,TypeError,KeyError,AttributeError,OSError,SyntaxError,RecursionError) as error:
        return {'valid':False,'errors':[str(error)]}
    return {'valid':True,'errors':[], 'verification':'STRUCTURE',
        'compiler_root_witness_replayed':code_evidence is not None,
        'runtime_code_instance_established':False,'namespace_alias_established':False,
        'import_module_object_established':False,'whole_program_coverage_established':False}
