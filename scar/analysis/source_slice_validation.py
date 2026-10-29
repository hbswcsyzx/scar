"""Exact source/compiler ports and local reference transfer for slice access.

The combined bytecodes are compound operations. Their internal temporary slice
is not a source value. The checks certify the modeled pending references, not
runtime object identity, complete finalizer effects or physical allocations.
"""
from __future__ import annotations

import ast
import dis
from collections import deque

from scar.analysis.source_language import function_exception_types, require_source_tree, supports_cpython_compiler
from scar.ir.program.model import (AccessMode, Behavior, CompletionResult, ExitKind,
    LiteralOrigin, ReferenceValue, StateVersionValue, TerminatorKind, ValueKind, ValueType, value_type)
from scar.ir.program.source_language import SourceLanguageCapability as C, SLICE_ACCESS_PROTOCOLS
from scar.ir.program.structured import PythonProtocolKind as K
from scar.ir.program.state_addresses import (AddressCoverage, AddressEffect, Element,
    InvokeStateOperand, ReferenceOwner, Slice)
from scar.ir.semantics_v2 import Opcode
from scar.ir.v2.semantic import OperationKind


def _need(condition, detail):
    if not condition:
        raise ValueError('slice access: ' + detail)


def _span(row):
    return row.start_line, row.end_line, row.start_column, row.end_column


def _raw_handoff_holds(failed, operation, operations, protocols, values, uses):
    """Read the original raw exception corridor, including explicit decrefs.

    String primitives release their consumed inputs before FrameExit. Preserve
    those hold instances when reconstructing the state at the INVOKE's RAISE
    landing; an arbitrary effectful instruction is never a cleanup shortcut.
    """
    _need(len(failed.arguments) == 2, 'raw raise must retain exception/world landing ports')
    exception, world = failed.arguments
    _need(type(values[exception]) is ReferenceValue and type(values[world]) is StateVersionValue
          and values[world].region == values[operation.uses[-1].value].region,
          'raw exception corridor crossed a different frame')
    released = []
    for offset, identity in enumerate(failed.operations):
        cleanup, marker = operations[identity], protocols.get(identity)
        _need(marker is not None and cleanup.terminator is None and cleanup.callee is None
              and len(cleanup.results) == 1 and cleanup.uses[-1].value == world
              and len(cleanup.accesses) == 1 and cleanup.accesses[0].before == cleanup.uses[-1].id
              and cleanup.accesses[0].after == cleanup.results[0]
              and cleanup.accesses[0].mode is AccessMode.READ_WRITE
              and value_type(values[cleanup.results[0]]) == value_type(values[world]),
              'raw cleanup must thread the exact post-world through its original frame operation')
        world = cleanup.results[0]
        if marker.kind is K.FRAME_RELEASE_TEMPORARY:
            first = uses.get((identity, cleanup.uses[0].id))
            _need(len(cleanup.uses) == 2 and type(values[cleanup.uses[0].value]) is ReferenceValue
                  and first is not None and first.role == 'fstring-consumed-reference'
                  and protocols.get(operation.id) is not None
                  and protocols[operation.id].kind in (K.FSTRING_CONVERT, K.FSTRING_FORMAT, K.BUILD_STRING),
                  'raw prefix is not an original string-input reference release')
            released.append(cleanup.uses[0].value)
            continue
        _need(marker.kind is K.FRAME_EXIT, 'raw raise must reach its original FrameExit')
        payload = [use.value for use in cleanup.uses
                   if (row := uses.get((identity, use.id))) is not None and row.role == 'held-payload']
        _need(payload == [exception] and offset + 2 == len(failed.operations),
              'FrameExit must hold this exact exception and precede its sole terminal raise')
        terminal = operations[failed.operations[offset + 1]]
        _need(terminal.terminator is not None and terminal.terminator.kind is TerminatorKind.RAISE
              and not terminal.terminator.successors
              and tuple(use.value for use in terminal.uses) == (exception, world)
              and terminal.terminator.values == tuple(use.id for use in terminal.uses),
              'raw terminal lost the original exception or cleanup post-world')
        retained = tuple(use.value for use in cleanup.uses
            if (row := uses.get((identity, use.id))) is not None and row.role == 'held-temporary')
        return retained + tuple(reversed(released))
    raise ValueError('slice access: raw raise has no frame cleanup endpoint')


def validate_slice_access(model, graph, interface, metadata, semantic, language, *,
                          source_tree=None, options=None, structural_only=False):
    protocols = {row.operation: row for row in model.protocols}
    selected = {identity for identity, row in protocols.items() if row.kind.value in SLICE_ACCESS_PROTOCOLS}
    if not selected:
        return set()
    _need(C.SLICE_ACCESS_314_V1 in language.capabilities and C.SLICE_KEYS in language.capabilities,
          'compound/store protocols require their distinct capability')
    operations = {row.id: row for row in graph.operations}
    values = {row.id: row for row in graph.values}
    blocks = {row.id: row for region in graph.regions for row in region.blocks}
    links = {row.operation: row for row in metadata.operation_links}
    uses = {(row.operation, row.use): row for row in metadata.use_links}
    addresses = {row.site.operation: row for row in graph.state_address_refinements}
    reference_type, state_type = ValueType(ValueKind.REFERENCE), value_type(values[interface.world])
    instructions = ()
    if not structural_only:
        _need(options is not None and supports_cpython_compiler(options.code_evidence),
              'independent CPython 3.14.7 compiler evidence is required')
        options.code_evidence.require_definition(metadata.source, interface.definition, model.source)
        instructions = tuple(dis.get_instructions(options.code_evidence.code))
    for identity in selected:
        operation, protocol, link = operations[identity], protocols[identity], links[identity]
        read, compound = protocol.kind is K.BINARY_SLICE, protocol.kind is not K.STORE_SLICE_SUBSCRIPT
        count = 3 if read or not compound else 4
        definition = semantic.definitions.get(link.semantic_operation)
        atom = semantic.source_atoms.get(link.source.atom_id)
        _need(definition is not None and definition.code_id == link.source.atom_id.wire
              and link.source.atom_id in definition.source_atoms and atom is not None
              and atom.kind == 'Subscript' and atom.reference == link.source == protocol.source,
              'operation lost its original SG/source Subscript')
        _need((definition.kind is OperationKind.INDEX and len(definition.output_slots) == 1
               and link.opcode is Opcode.INDEX) if read else
              (definition.metadata.get('role') == 'binding' and link.opcode is Opcode.OPAQUE),
              'read/store no longer has its original SG role')
        _need(operation.terminator is not None and operation.terminator.kind is TerminatorKind.INVOKE
              and operation.callee is None and not operation.effects_complete
              and len(operation.uses) == count + 1
              and tuple(use.id for use in operation.uses) == operation.invoke_arguments
              and all(type(values[use.value]) is ReferenceValue for use in operation.uses[:-1])
              and type(values[operation.uses[-1].value]) is StateVersionValue
              and value_type(values[operation.uses[-1].value]) == state_type
              and all(tag in operation.behaviors for tag in (Behavior.CONTROL, Behavior.READ, Behavior.WRITE)),
              'compound operation lost its exact reference/world invoke interface')
        expected = ((ExitKind.NORMAL, ((reference_type,) if read else ()) + (state_type,)),
                    (ExitKind.RAISE, function_exception_types(language, reference_type, state_type)))
        _need(tuple((row.kind, row.types) for row in operation.completions) == expected
              and tuple(edge.kind for edge in operation.terminator.successors) == (ExitKind.NORMAL, ExitKind.RAISE)
              and all(edge.arguments == tuple(CompletionResult(index) for index in range(len(types)))
                      and tuple(value_type(values[value]) for value in blocks[edge.block].arguments) == types
                      for edge, (_, types) in zip(operation.terminator.successors, expected)),
              'normal/raise must carry their own payload and post-world, including traceback where applicable')
        ports = operation.uses[:-1]
        roles = (('receiver', 0), ('slice-lower', 0), ('slice-upper', 1)) if read else (
            (('assigned-reference', 0), ('heap-owner', 0), ('slice-lower', 0), ('slice-upper', 1)) if compound else
            (('assigned-reference', 0), ('heap-owner', 0), ('element-key', 0)))
        source_uses = [uses.get((identity, use.id)) for use in ports]
        _need(all(row is not None and (row.role, row.index) == role
                  and semantic.source_atoms.get(row.source.atom_id) is not None
                  and semantic.source_atoms[row.source.atom_id].reference == row.source
                  for row, role in zip(source_uses, roles)), 'ordered input roles/source Uses differ')
        if compound:
            _need(all(row.semantic_value is None for row in source_uses[-2:]),
                  'a bound cannot inherit the old whole-index StaticValue')
        owner = ports[0] if read else ports[1]
        selector = Slice(ports[-2].id, ports[-1].id) if compound else Element(ports[-1].id)
        effect = AddressEffect(ReferenceOwner(owner.id), (selector,), AccessMode.READ if read else AccessMode.WRITE)
        address = addresses.get(identity)
        _need(address is not None and address.site == InvokeStateOperand(identity, operation.uses[-1].id)
              and address.coverage is AddressCoverage.PARTIAL and address.protocol is None
              and address.effects == (effect,), 'partial slice address does not use the original operation ports')
        if not structural_only:
            nodes = [row for row in require_source_tree(source_tree, language.source, link.source)
                     if isinstance(row, ast.Subscript)]
            _need(len(nodes) == 1, 'operation requires one exact source Subscript')
            node, = nodes
            _need(isinstance(node.ctx, ast.Load if read else ast.Store), 'source context differs')
            if compound:
                _need(isinstance(node.slice, ast.Slice) and node.slice.step is None,
                      'combined operation requires a direct no-step slice')
                children = ((node.value, node.slice.lower or node.slice, node.slice.upper or node.slice) if read else
                            (node, node.value, node.slice.lower or node.slice, node.slice.upper or node.slice))
                for child, bound in zip((node.slice.lower, node.slice.upper), ports[-2:]):
                    if child is None:
                        _need(type(values[bound.value].origin) is LiteralOrigin
                              and values[bound.value].origin.value is None,
                              'omitted lower/upper must be the exact None literal')
            else:
                _need(any(isinstance(child, ast.Slice) for child in ast.walk(node.slice)),
                      'new consuming store cannot silently replace the historical ordinary store contract')
                children = (node, node.value, node.slice)
            _need(tuple(_span(row.source) for row in source_uses) ==
                  tuple((child.lineno, child.end_lineno, child.col_offset, child.end_col_offset) for child in children),
                  'input evaluation sources differ from the exact RHS/receiver/bounds/key ports')
            opcode = 'BINARY_SLICE' if read else 'STORE_SLICE' if compound else 'STORE_SUBSCR'
            _need(sum(row.opname == opcode and tuple(row.positions) == _span(link.source) for row in instructions) == 1,
                  'no unique exact compiler bytecode/position for the compound operation')
        _validate_local_transfer(identity, operations, protocols, blocks, values, links, uses, language)
    return selected


def _validate_local_transfer(target, operations, protocols, blocks, values, links, uses, language):
    """Follow actual normal CFG corridors from input holds through this macro.

    Exceptional corridors retain their original raw/paired payload and world.
    Their pending references independently establish the unchanged outer prefix.
    Holds keep operation identity and multiplicity; equal ValueIDs do not merge.
    """
    from scar.analysis.source_call_validation import _pop_suffix, _check_failure_pending
    from scar.analysis.source_function_try_validation import exception_handoff_holds
    ordered = list(operations)
    end = ordered.index(target)
    operands = operations[target].uses[:-1]
    starts = []
    for use in operands:
        origin = uses[target, use.id].source
        candidates = [identity for identity in ordered[:end]
            if (p := protocols.get(identity)) is not None and p.kind is K.FRAME_HOLD_TEMPORARY
            and len(operations[identity].uses) == 2 and operations[identity].uses[0].value == use.value
            and (row := uses.get((identity, operations[identity].uses[0].id))) is not None
            and row.source == origin]
        _need(bool(candidates), 'input has no preceding exact source-owned temporary hold')
        starts.append(candidates[-1])
    first = min(starts, key=ordered.index)
    positions = {identity: (block.id, index) for block in blocks.values() for index, identity in enumerate(block.operations)}
    entry = positions[first]
    queue, seen, failures = deque(((entry, ()),)), set(), []
    prefix, reached = None, False
    while queue:
        position, stack = queue.popleft()
        token = position, stack
        if token in seen:
            continue
        seen.add(token)
        _need(len(seen) <= max(128, len(operations) * 4), 'local pending CFG exceeds bounded fixed point')
        block, offset = position
        for identity in blocks[block].operations[offset:]:
            operation = operations[identity]
            protocol = protocols.get(identity)
            kind = protocol.kind if protocol is not None else None
            refs = tuple(use.value for use in operation.uses if type(values[use.value]) is ReferenceValue)
            if kind is K.FRAME_HOLD_TEMPORARY:
                _need(len(refs) == 1, 'temporary hold lost its reference')
                stack += ((identity, refs[0]),)
            elif kind is K.FRAME_RELEASE_TEMPORARY:
                stack = _pop_suffix(stack, refs)
            term = operation.terminator
            if term is None:
                continue
            if term.kind is TerminatorKind.INVOKE:
                normal, failure = stack, stack
                consumed, success_only = (), False
                if kind is not None and kind.value in SLICE_ACCESS_PROTOCOLS:
                    consumed = refs
                elif kind is K.BUILD_SLICE or links[identity].opcode is Opcode.INDEX:
                    consumed = refs
                elif kind is K.BUILD_MAP:
                    consumed = refs
                elif kind in (K.MAP_ADD,):
                    consumed = refs[-2:]
                elif kind in (K.DICT_UPDATE, K.DICT_MERGE, K.APPEND_CALL_POSITIONAL,
                               K.EXTEND_CALL_POSITIONALS, K.APPEND_DISPLAY, K.EXTEND_DISPLAY):
                    consumed = refs[-1:]
                elif kind in (K.CALL_FUNCTION_EX, K.CALL_POSITIONALS_TO_TUPLE, K.DISPLAY_LIST_TO_TUPLE):
                    consumed = refs
                elif kind in (K.BUILD_CALL_POSITIONALS, K.BUILD_CALL_POSITIONAL_LIST, K.BUILD_DISPLAY_LIST):
                    consumed, success_only = refs, True
                elif links[identity].opcode in (Opcode.BUILD_TUPLE, Opcode.BUILD_LIST) and Behavior.MEMORY in operation.behaviors:
                    consumed, success_only = refs, True
                if consumed:
                    normal = _pop_suffix(stack, consumed)
                    failure = stack if success_only else normal
                failed = blocks[term.successors[1].block]
                if C.FUNCTION_TRY_314_V1 in language.capabilities:
                    actual = exception_handoff_holds(failed.id, operations, protocols, blocks, uses)
                else:
                    _need(bool(failed.operations), 'raise lost its frame cleanup')
                    actual = _raw_handoff_holds(failed, operation, operations, protocols, values, uses)
                if identity == target:
                    _need(tuple(value for _, value in stack) == tuple(use.value for use in operands)
                          and not normal and not failure, 'macro did not consume exactly its ordered held input instances')
                    prefix = _check_failure_pending(actual, failure, prefix)
                    reached = True
                else:
                    failures.append((actual, failure))
                    queue.append(((term.successors[0].block, 0), normal))
            elif term.kind in (TerminatorKind.JUMP, TerminatorKind.BRANCH):
                queue.extend(((edge.block, 0), stack) for edge in term.successors)
            else:
                _need(False, 'input evaluation normal corridor escaped before its consuming macro')
            break
    _need(reached and prefix is not None, 'input holds do not reach their consuming macro')
    for actual, local in failures:
        _check_failure_pending(actual, local, prefix)


__all__ = ['validate_slice_access']
