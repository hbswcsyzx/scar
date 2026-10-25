"""Independent source/compiler/CFG checks for the opt-in kwargs call protocol.

These queries inspect existing ports/holds. No second execution or lifetime
IR is published. Local pending suffix checks do not establish the enclosing
frame prefix, runtime code identity, actual mapping items or full call cleanup.
"""
from __future__ import annotations

import ast
import dis

from scar.analysis.source_language import SourceLanguageOptions, require_source_tree
from scar.ir.program.model import (AccessMode, Behavior, CompletionResult, ExitKind, OperationResult,
    ReferenceValue, StateVersionValue, TerminatorKind, ValueKind, ValueType, value_type)
from scar.ir.program.source import GapKind
from scar.ir.program.source_language import SourceLanguageCapability as Capability
from scar.ir.program.structured import PythonProtocolKind as Kind
from scar.ir.semantics_v2 import Opcode
from scar.ir.v2.semantic import OperationKind

CALL_PROTOCOLS = frozenset((Kind.BUILD_CALL_POSITIONALS, Kind.DICT_MERGE, Kind.CALL_FUNCTION_EX))


def is_original_call_definition(semantic, definition, source):
    """Recognize frontend_v2's unchanged opaque Call, never invent a CALL kind."""
    atom = semantic.source_atoms.get(source.atom_id)
    if atom is None or atom.kind != "Call" or atom.reference != source:
        return False
    matches = [row for row in semantic.definitions.values()
               if row.kind is OperationKind.OPAQUE and row.metadata.get("ast_type") == "Call"
               and row.code_id == source.atom_id.wire and source.atom_id in row.source_atoms
               and len(row.output_slots) == 1]
    return len(matches) == 1 and definition is matches[0]


def _need(condition, detail):
    if not condition:
        raise ValueError("kwargs call validation: " + detail)


def _span(reference):
    return reference.start_line, reference.end_line, reference.start_column, reference.end_column


def _ast_span(node):
    return node.lineno, node.end_lineno, node.col_offset, node.end_col_offset


def _expected(node):
    """Independent AST staging: packing, complete named runs, then merges."""
    result = [("PACK", len(node.args), None)]
    receiver, index = False, 0
    while index < len(node.keywords):
        child = node.keywords[index]
        if child.arg is None:
            if not receiver:
                result.append(("BUILD_MAP", 0, None)); receiver = True
            result.append(("DICT_MERGE", 1, index)); index += 1
        else:
            end = index
            while end < len(node.keywords) and node.keywords[end].arg is not None:
                result.append(("KEY", node.keywords[end].arg, end)); end += 1
            result.append(("BUILD_MAP", end - index, index))
            if receiver: result.append(("DICT_MERGE", 1, index))
            receiver, index = True, end
    result.append(("CALL_FUNCTION_EX", None, None))
    return result


def _pop_suffix(stack, consumed):
    """Ordered hold instances, retaining multiplicity even for equal ValueIDs."""
    if not consumed: return tuple(stack)
    _need(len(stack) >= len(consumed) and tuple(row[1] for row in stack[-len(consumed):]) == tuple(consumed),
          "primitive consumed a different ordered held suffix")
    return tuple(stack[:-len(consumed)])


def _check_failure_pending(actual, local, prefix=None, *, exact=True):
    expected = tuple(row[1] for row in local)
    if prefix is None:
        _need(len(actual) >= len(expected) and (not expected or tuple(actual[-len(expected):]) == expected),
              "failure lost or reordered its call-owned pending suffix")
        return tuple(actual[:-len(expected)]) if expected else tuple(actual)
    _need(tuple(actual) == prefix + expected if exact else tuple(actual[:len(prefix) + len(expected)]) == prefix + expected,
          "failure changed its enclosing prefix or call-owned pending references")
    return prefix


def _local_pending(group, all_operations, protocols, use_links, blocks, values, links):
    final = group[-1]
    call = all_operations[final]
    callee = call.uses[0].value
    candidates = []
    ordered = list(all_operations)
    first, end = ordered.index(group[0]), ordered.index(final)
    for identity in ordered[:first]:
        operation = all_operations[identity]
        if protocols.get(identity) is None or protocols[identity].kind is not Kind.FRAME_HOLD_TEMPORARY:
            continue
        refs = operation.uses[:-1]
        if len(refs) == 1:
            source = use_links.get((identity, refs[0].id))
            if (refs[0].value == callee and source is not None and source.role == "call-held-callee"
                    and source.source == use_links[(final, call.uses[0].id)].source):
                candidates.append(identity)
    _need(len(candidates) == 1, "call has no unique original callee hold instance")
    begin = ordered.index(candidates[0])
    owned_values = {callee}
    for identity in group:
        operation = all_operations[identity]
        owned_values.update(use.value for use in operation.uses[:-1])
        protocol = protocols[identity].kind
        if protocol is Kind.READ_CODE_CONSTANT:
            owned_values.update(operation.results)
        elif operation.terminator is not None:
            normal = blocks[operation.terminator.successors[0].block]
            owned_values.update(normal.arguments[:-1])
    stack, prefix, deferred, checked = (), None, [], 0
    group_set = set(group)
    for identity in ordered[begin:end + 1]:
        operation = all_operations[identity]
        protocol = protocols.get(identity)
        kind = protocol.kind if protocol is not None else None
        if kind is Kind.FRAME_HOLD_TEMPORARY:
            refs = operation.uses[:-1]
            if len(refs) == 1:
                source = use_links.get((identity, refs[0].id))
                if source is not None and source.role.startswith("call-held-") and refs[0].value in owned_values:
                    stack += ((identity, refs[0].value),)
        if operation.terminator is None or operation.terminator.kind is not TerminatorKind.INVOKE:
            continue
        refs = tuple(use.value for use in operation.uses[:-1])
        normal_stack, failure_stack = stack, stack
        if identity in group_set:
            if kind is Kind.BUILD_CALL_POSITIONALS:
                normal_stack = _pop_suffix(stack, refs)  # failure is success-only steal.
            elif kind is Kind.BUILD_MAP:
                normal_stack = failure_stack = _pop_suffix(stack, refs)
            elif kind is Kind.DICT_MERGE:
                normal_stack = failure_stack = _pop_suffix(stack, refs[-1:])
            elif kind is Kind.CALL_FUNCTION_EX:
                normal_stack = failure_stack = _pop_suffix(stack, refs)
        failure = blocks[operation.terminator.successors[1].block]
        _need(bool(failure.operations), "call/child failure has no cleanup")
        cleanup = all_operations[failure.operations[0]]
        _need(protocols.get(cleanup.id) is not None and protocols[cleanup.id].kind is Kind.FRAME_EXIT,
              "call/child failure does not route its post-world through FRAME_EXIT")
        actual = tuple(use.value for use in cleanup.uses
            if (link := use_links.get((cleanup.id, use.id))) is not None and link.role == "held-temporary")
        if identity in group_set:
            prefix = _check_failure_pending(actual, failure_stack, prefix)
        else:
            deferred.append((actual, failure_stack))
        stack = normal_stack; checked += 1
    _need(not stack and prefix is not None, "call-owned holds were leaked or never reviewed")
    for actual, local in deferred:
        _check_failure_pending(actual, local, prefix, exact=False)
    return {"call_owned_pending_checked": True, "invoke_failures_checked": checked,
            "enclosing_prefix_consistency_checked": True, "outer_pending_verified": False,
            "call_cleanup_contract_verified": False, "whole_lifetime_verified": False}


def validate_call_protocols(model, graph, interface, metadata, semantic, language, *,
                            source_tree=None, options=None, structural_only=False):
    protocols = {row.operation: row for row in model.protocols}
    new = {identity for identity, row in protocols.items() if row.kind in CALL_PROTOCOLS}
    auxiliary = {identity for identity, row in protocols.items()
        if row.kind in (Kind.BUILD_MAP, Kind.MAP_ADD, Kind.DICT_UPDATE, Kind.READ_CODE_CONSTANT)
        and (atom := semantic.source_atoms.get(row.source.atom_id)) is not None and atom.kind == "Call"}
    if not new:
        _need(not auxiliary, "orphan call packing/constant has no final kwargs call")
        return {"calls": 0, "records": [], "whole_lifetime_verified": False}
    _need(Capability.CALL_KWARGS_314_V1 in language.capabilities, "new protocol has no explicit kwargs capability")
    if not structural_only:
        _need(isinstance(source_tree, ast.Module) and type(options) is SourceLanguageOptions
              and options.code_evidence is not None, "exact kwargs checking requires independent source/code inputs")
        evidence = options.code_evidence
        evidence.require_definition(metadata.source, interface.definition, model.source)
        _need(evidence.store.document["runtime"]["version"][:3] == [3, 14, 7], "kwargs contract requires pinned CPython 3.14.7")
    operations = {row.id: row for row in graph.operations}
    values = {row.id: row for row in graph.values}
    blocks = {block.id: block for region in graph.regions for block in region.blocks}
    positions = {identity: (block.id, index) for block in blocks.values() for index, identity in enumerate(block.operations)}
    links = {row.operation: row for row in metadata.operation_links}
    uses = {(row.operation, row.use): row for row in metadata.use_links}
    constants = {row.operation: row for row in language.constants}
    ref, world = ValueType(ValueKind.REFERENCE), value_type(values[interface.world])
    finals = [identity for identity, row in protocols.items() if row.kind is Kind.CALL_FUNCTION_EX]
    _need(len({protocols[identity].source for identity in finals}) == len(finals), "Call has duplicate final call protocol")
    covered, records = set(), []
    for final in finals:
        source = protocols[final].source
        atom = semantic.source_atoms.get(source.atom_id)
        definition = semantic.definitions.get(links[final].semantic_operation)
        _need(atom is not None and atom.kind == "Call" and atom.reference == source
              and definition is not None and is_original_call_definition(semantic, definition, source)
              and definition.code_id == source.atom_id.wire and source.atom_id in definition.source_atoms
              and len(definition.output_slots) == 1 and links[final].opcode is Opcode.CALL,
              "final kwargs call has no unique original SG Call/output source")
        group = [identity for identity in operations if identity in protocols and protocols[identity].source == source
                 and protocols[identity].kind in CALL_PROTOCOLS | {Kind.BUILD_MAP, Kind.MAP_ADD, Kind.DICT_UPDATE, Kind.READ_CODE_CONSTANT}]
        _need(group and group[-1] == final, "call preparation is missing or appears after final call")
        _need(all(protocols[i].kind not in (Kind.MAP_ADD, Kind.DICT_UPDATE) for i in group),
              "kwargs preparation cannot use DICT_UPDATE or an unsupported large keyword run")
        covered.update(set(group) & new)
        node = None
        if not structural_only:
            selected = [n for n in require_source_tree(source_tree, language.source, source) if isinstance(n, ast.Call)]
            _need(len(selected) == 1, "kwargs call has no unique exact source AST")
            node = selected[0]
            _need(any(k.arg is None for k in node.keywords) and not any(isinstance(a, ast.Starred) for a in node.args),
                  "kwargs profile requires ** and fixed ordinary positionals")
        built_maps, packed, stage, receiver = {}, {}, [], None
        final_refs = tuple(use.value for use in operations[final].uses[:-1])
        _need(len(final_refs) == 3, "final call needs callee/positional tuple/kwargs dict")
        callee = final_refs[0]
        for identity in group:
            operation, kind = operations[identity], protocols[identity].kind
            _need(links[identity].source == source and protocols[identity].source == source,
                  "call protocol lost its exact original source")
            if kind is Kind.READ_CODE_CONSTANT:
                _need(identity in constants and links[identity].semantic_operation is None,
                      "call constant lacks exact code provenance")
                value = operation.results[0]
                if value == final_refs[1]: packed[value] = identity
                stage.append(("CONST", identity)); continue
            _need(operation.callee is None and not operation.effects_complete
                  and operation.terminator is not None and operation.terminator.kind is TerminatorKind.INVOKE
                  and tuple(use.id for use in operation.uses) == operation.invoke_arguments
                  and all(type(values[use.value]) is ReferenceValue for use in operation.uses[:-1])
                  and type(values[operation.uses[-1].value]) is StateVersionValue
                  and values[operation.uses[-1].value].location == values[interface.world].location
                  and all(b in operation.behaviors for b in (Behavior.CONTROL, Behavior.READ, Behavior.WRITE, Behavior.MEMORY)),
                  "call protocol lost ordered references/incomplete world invoke")
            count = len(operation.uses) - 1
            result_count = 1 if kind in (Kind.BUILD_MAP, Kind.BUILD_CALL_POSITIONALS, Kind.CALL_FUNCTION_EX) else 0
            _need(tuple((c.kind, c.types) for c in operation.completions) ==
                  ((ExitKind.NORMAL, (ref,) * result_count + (world,)), (ExitKind.RAISE, (ref, world)))
                  and tuple(e.kind for e in operation.terminator.successors) == (ExitKind.NORMAL, ExitKind.RAISE)
                  and all(e.arguments == tuple(CompletionResult(i) for i in range(len(c.types)))
                          for e, c in zip(operation.terminator.successors, operation.completions)),
                  "call normal/raise payloads and post-world differ")
            refs = tuple(use.value for use in operation.uses[:-1])
            source_uses = [uses[(identity, use.id)] for use in operation.uses[:-1]]
            for source_use in source_uses:
                atom = semantic.source_atoms.get(source_use.source.atom_id)
                _need((source_use.source.path, source_use.source.fingerprint) == (source.path, source.fingerprint)
                      and atom is not None and atom.reference == source_use.source,
                      "call operand differs from its exact source namespace/atom")
            normal = blocks[operation.terminator.successors[0].block]
            if kind is Kind.BUILD_MAP:
                _need(links[identity].semantic_operation is None and count <= 30 and count % 2 == 0,
                      "keyword run is not bounded synthetic BUILD_MAP")
                for index in range(0, count, 2):
                    key, value = source_uses[index:index + 2]
                    _need(key.role == "call-keyword-name" and value.role.startswith("keyword:")
                          and key.index == value.index and key.source == source,
                          "keyword run lost original ordered name/value Uses")
                built_maps[normal.arguments[0]] = identity
                if receiver is None:
                    receiver = normal.arguments[0]
            elif kind is Kind.BUILD_CALL_POSITIONALS:
                _need(links[identity].semantic_operation is None
                      and [(u.role, u.index) for u in source_uses] == [("argument", i) for i in range(count)],
                      "positional tuple lost ordered original argument Uses")
                packed[normal.arguments[0]] = identity
            elif kind is Kind.DICT_MERGE:
                _need(links[identity].semantic_operation is None and count == 3 and refs[0] == callee
                      and refs[1] == receiver and refs[2] != refs[1]
                      and [(u.role, u.index) for u in source_uses[:2]] == [("callee", 0), ("call-keywords", 0)]
                      and source_uses[2].role in ("keyword_unpack", "call-keyword-run"),
                      "DICT_MERGE lost callee/receiver/update or used an invented dict")
                _need(source_uses[2].role != "call-keyword-run" or refs[2] in built_maps,
                      "keyword run merge update has no original call BUILD_MAP")
            else:
                _need(count == 3 and refs[1] in packed and refs[2] == receiver
                      and [(u.role, u.index) for u in source_uses] == [("callee", 0), ("call-positionals", 0), ("call-keywords", 0)],
                      "final call lost its original callee or prepared argument containers")
            stage.append((kind.value, identity))
        _need(len(packed) == 1, "call positional tuple preparation is not unique")
        # Graph ordering alone is insufficient: each next stage must be the
        # first call-owned stage on every normal child/control continuation.
        own = set(group)
        for current, expected_next in zip(group, group[1:]):
            operation = operations[current]
            if operation.terminator is None:
                block, index = positions[current]; pending = [(block, index + 1)]
            else:
                pending = [(operation.terminator.successors[0].block, 0)]
            seen, found = set(), set()
            while pending:
                position = pending.pop()
                if position in seen: continue
                seen.add(position)
                _need(len(seen) <= len(operations) * 2 + 1, "call normal staging traversal budget exceeded")
                block, index = blocks[position[0]], position[1]
                _need(index < len(block.operations), "call normal continuation falls out of block")
                identity = block.operations[index]
                if identity in own:
                    found.add(identity); continue
                child = operations[identity]
                if child.terminator is None:
                    pending.append((block.id, index + 1))
                elif child.terminator.kind is TerminatorKind.INVOKE:
                    pending.extend((e.block, 0) for e in child.terminator.successors if e.kind is ExitKind.NORMAL)
                elif child.terminator.kind in (TerminatorKind.JUMP, TerminatorKind.BRANCH):
                    pending.extend((e.block, 0) for e in child.terminator.successors)
                else:
                    raise ValueError("kwargs call validation: child normal path skips later call stage")
            _need(found == {expected_next}, "ordered call preparation stages can be reordered or skipped")
        if node is not None:
            _check_source_and_code(node, group, operations, protocols, uses, constants, values, options.code_evidence)
        _need(any(g.kind is GapKind.FRAME_EFFECT and g.source == source
                  and g.detail.startswith("CALL_EX_LOCAL_UNWIND_CONTRACT_UNVERIFIED:") for g in metadata.gaps),
              "call must retain its explicit unverified runtime cleanup frontier")
        pending = _local_pending(group, operations, protocols, uses, blocks, values, links)
        records.append({"operation": final.wire, "source": source.atom_id.wire,
            "protocol_operations": len(group), "source_code_verified": not structural_only,
            "pending": pending, "frontiers": ["CALL_EX_LOCAL_UNWIND_CONTRACT_UNVERIFIED", "OUTER_PENDING_PREFIX_UNVERIFIED"]})
    _need(covered == new and auxiliary <= {identity for final in finals for identity in operations
          if identity in protocols and protocols[identity].source == protocols[final].source},
          "orphan kwargs preparation has no exact final Call")
    return {"calls": len(records), "records": records, "runtime_code_instance_established": False,
            "effects_established": False, "whole_lifetime_verified": False}


def _check_source_and_code(node, group, operations, protocols, uses, constants, values, evidence):
    expected = _expected(node)
    actual = []
    for identity in group:
        operation, kind = operations[identity], protocols[identity].kind
        if kind is Kind.READ_CODE_CONSTANT:
            source = constants[identity]
            _need(source.code_key == evidence.captured.key and len(source.constant_path) == 1,
                  "call constant uses a different compiler witness")
            value = evidence.code.co_consts[source.constant_path[0]]
            actual.append(("PACK" if type(value) is tuple and not value else "KEY", value, identity))
        elif kind is Kind.BUILD_CALL_POSITIONALS:
            actual.append(("PACK", len(operation.uses) - 1, identity))
        else:
            actual.append((kind.value, (len(operation.uses) - 1) // 2 if kind is Kind.BUILD_MAP else 1 if kind is Kind.DICT_MERGE else None, identity))
    _need(len(actual) == len(expected), "call stage count differs from original keyword runs")
    for (kind, value, identity), (expected_kind, argument, index) in zip(actual, expected):
        _need(kind == expected_kind and (value == argument or kind == "PACK" and argument == 0 and value == ()),
              "call stage/name/run order differs from original AST")
        operation = operations[identity]
        source_uses = [uses[(identity, use.id)] for use in operation.uses[:-1]]
        if kind == "PACK" and protocols[identity].kind is Kind.BUILD_CALL_POSITIONALS:
            _need(tuple(_span(u.source) for u in source_uses) == tuple(_ast_span(n) for n in node.args),
                  "positional tuple children differ from exact AST order")
        elif kind == "BUILD_MAP" and argument:
            for pair, keyword_index in enumerate(range(index, index + argument)):
                _need(source_uses[pair * 2].index == keyword_index
                      and source_uses[pair * 2 + 1].role == "keyword:" + node.keywords[keyword_index].arg
                      and _span(source_uses[pair * 2 + 1].source) == _ast_span(node.keywords[keyword_index].value),
                      "named run child source/index differs")
        elif kind == "DICT_MERGE":
            update = source_uses[2]
            unpack = node.keywords[index].arg is None
            _need(update.index == index and update.role == ("keyword_unpack" if unpack else "call-keyword-run")
                  and (not unpack or _span(update.source) == _ast_span(node.keywords[index].value)),
                  "merge source/update index differs from exact keyword sequence")
        elif kind == "CALL_FUNCTION_EX":
            _need(_span(source_uses[0].source) == _ast_span(node.func), "callee source is not the original single evaluation")
    names = {"LOAD_CONST", "BUILD_TUPLE", "BUILD_LIST", "LIST_APPEND", "LIST_EXTEND", "LIST_TO_TUPLE",
             "BUILD_MAP", "MAP_ADD", "DICT_MERGE", "DICT_UPDATE", "CALL_FUNCTION_EX", "CALL_KW", "CALL"}
    instructions = [i for i in dis.get_instructions(evidence.code) if tuple(i.positions) == _ast_span(node) and i.opname in names]
    _need(len(instructions) == len(expected), "compiler uses a different packing/merge call sequence")
    for instruction, (kind, argument, _index), (_actual, _value, identity) in zip(instructions, expected, actual):
        if kind in ("PACK", "KEY") and protocols[identity].kind is Kind.READ_CODE_CONSTANT:
            _need(instruction.opname == "LOAD_CONST" and instruction.arg == constants[identity].constant_path[0],
                  "call code constant does not identify exact compiler instruction/slot")
        elif kind == "PACK":
            _need(instruction.opname == "BUILD_TUPLE" and instruction.arg == argument, "call positional packing differs from exact compiler")
        else:
            _need(instruction.opname == kind and (argument is None or instruction.arg == argument),
                  "call merge/named-run differs from exact compiler")


__all__ = ["validate_call_protocols"]
