"""Opt-in CPython 3.14.7 kwargs preparation over original source/core ports.

DICT_MERGE is deliberately distinct from dict-display DICT_UPDATE. Mapping
keys/items, collision/error formatting and partial mutation stay inside its
incomplete world invoke; no dynamic entries or internal calls are invented.
CALL_FUNCTION_EX uses an explicit call-plus-local-operand-unwind boundary.
Its physical cleanup/monitoring/finalizer qualification remains a frontier.
"""
from __future__ import annotations

import ast
import dis
from dataclasses import replace

from scar.analysis.program_lowering import _REF, _Unsupported
from scar.analysis.source_heap_lowering import _source_definition, _associate
from scar.analysis.source_mapping_lowering import _transfer
from scar.ir.program.ids import OperationID, ValueID
from scar.ir.program.model import AccessMode, Behavior, ExitKind, Operation, OperationResult, ReferenceValue, StateAccess
from scar.ir.program.source import GapKind, SourceRole
from scar.ir.program.source_language import CodeConstantSource
from scar.ir.program.structured import PythonProtocolKind as Kind
from scar.ir.semantics_v2 import Opcode
from scar.analysis.source_call_validation import is_original_call_definition


def _span(node):
    return node.lineno, node.end_lineno, node.col_offset, node.end_col_offset


def _keyword_runs(node):
    start = 0
    while start < len(node.keywords):
        end = start + 1
        if node.keywords[start].arg is not None:
            while end < len(node.keywords) and node.keywords[end].arg is not None:
                end += 1
        yield start, end
        start = end


def _witness_plan(node, instructions):
    """Bounded compiler recognition only, not target evaluation or wire data."""
    if (not isinstance(node, ast.Call) or not any(k.arg is None for k in node.keywords)
            or any(isinstance(a, ast.Starred) for a in node.args)):
        raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, node, "KWARGS_CALL_REQUIRES_FIXED_POSITIONALS_AND_DOUBLE_STAR")
    expected = [("PACK", len(node.args), None)]
    have_dict = False
    for start, end in _keyword_runs(node):
        if node.keywords[start].arg is None:
            if not have_dict:
                expected.append(("BUILD_MAP", 0, None)); have_dict = True
            expected.append(("DICT_MERGE", 1, start))
        else:
            if (end - start) * 2 > 30:
                raise _Unsupported(GapKind.CODE_VERSION, node, "KWARGS_LARGE_KEYWORD_RUN_COMPILER_FRONTIER")
            for index in range(start, end):
                expected.append(("KEY", node.keywords[index].arg, index))
            expected.append(("BUILD_MAP", end - start, None))
            if have_dict:
                expected.append(("DICT_MERGE", 1, start))
            have_dict = True
    expected.append(("CALL_FUNCTION_EX", None, None))
    names = {"LOAD_CONST", "BUILD_TUPLE", "BUILD_LIST", "LIST_APPEND", "LIST_EXTEND", "LIST_TO_TUPLE",
             "BUILD_MAP", "MAP_ADD", "DICT_MERGE", "DICT_UPDATE", "CALL_FUNCTION_EX", "CALL_KW", "CALL"}
    actual = [row for row in instructions if tuple(row.positions) == _span(node) and row.opname in names]
    if len(actual) != len(expected):
        raise _Unsupported(GapKind.CODE_VERSION, node, "KWARGS_EXACT_COMPILER_SEQUENCE_UNAVAILABLE")
    keys, packing = {}, actual[0]
    for row, (name, argument, index) in zip(actual, expected):
        if name == "PACK":
            ok = ((row.opname == "BUILD_TUPLE" and row.arg == argument)
                  or (argument == 0 and row.opname == "LOAD_CONST" and type(row.argval) is tuple and not row.argval))
        elif name == "KEY":
            ok = row.opname == "LOAD_CONST" and type(row.argval) is str and row.argval == argument
            if ok: keys[index] = row
        else:
            ok = row.opname == name and (argument is None or row.arg == argument)
        if not ok:
            raise _Unsupported(GapKind.CODE_VERSION, node, "KWARGS_EXACT_COMPILER_SEQUENCE_UNAVAILABLE")
    return packing, keys


def _instructions(builder, node):
    evidence = builder.language_options.code_evidence
    if evidence is None or evidence.store.document["runtime"]["version"][:3] != [3, 14, 7]:
        raise _Unsupported(GapKind.CODE_VERSION, node, "KWARGS_CPYTHON_3147_CODE_WITNESS_REQUIRED")
    evidence.require_definition(builder.snapshot, builder.function_definition.id, builder.source(builder.functions[builder.entry]))
    return tuple(dis.get_instructions(evidence.code))


def _hold(builder, cursor, node, reference, role):
    builder.frame_transition(cursor, node, ((reference, node, "call-held-" + role),), Kind.FRAME_HOLD_TEMPORARY)
    builder.active_temporaries.append(reference)


def _constant(builder, node, cursor, instruction):
    evidence = builder.language_options.code_evidence
    if type(instruction.arg) is not int or evidence.code.co_consts[instruction.arg] is not instruction.argval:
        raise _Unsupported(GapKind.CODE_VERSION, node, "KWARGS_CODE_CONSTANT_SLOT_DIFFERS")
    identity = builder.fresh(OperationID, "call-code-constant")
    before = builder.use(identity, cursor.state, node, "code-constant-world", 0)
    value = ReferenceValue(builder.fresh(ValueID, "call-code-constant"), builder.function_context,
                           OperationResult(identity, 0))
    builder.add_value(value); builder.link_value(value, node, SourceRole.EXPRESSION)
    operation = Operation(identity, "call code constant", (Behavior.READ,), (before,), (value.id,),
        (StateAccess(builder.world, before.id, AccessMode.READ),), effects_complete=False)
    builder.emit(cursor, operation, node, SourceRole.EXPRESSION)
    builder.protocol(identity, Kind.READ_CODE_CONSTANT, node)
    builder.language_constants.append(CodeConstantSource(identity, builder.source(node), evidence.captured.key,
                                                         (instruction.arg,)))
    return value.id


def _invoke(builder, cursor, node, inputs, kind, normal_consumed=(), *, raise_consumed=None, old=None, result=False):
    if raise_consumed is None:
        raise_consumed = normal_consumed
    def failed(failure, exception):
        saved = tuple(builder.active_temporaries)
        try:
            _transfer(builder, raise_consumed, node)
            builder.finish_exit(failure, node, exception, ExitKind.RAISE)
        finally:
            builder.active_temporaries[:] = saved
    cursor, value, identity = builder.invoke(cursor, node, tuple(inputs), result_type=_REF if result else None,
                                            old=old, failure_handler=failed)
    builder.protocol(identity, kind, node)
    original = builder.operation_records[identity]
    marked = replace(original, behaviors=original.behaviors + (Behavior.MEMORY,))
    builder.operations[builder.operations.index(original)] = marked
    builder.operation_records[identity] = marked
    _transfer(builder, normal_consumed, node)
    return cursor, value, identity


def lower_kwargs_call(builder, node, cursor):
    """Prepare arbitrary mappings, preserving fixed compiler stage boundaries."""
    if not builder.has_language("CALL_KWARGS_314_V1"):
        raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, node, "KWARGS_CAPABILITY_REQUIRED")
    packing, constants = _witness_plan(node, _instructions(builder, node))
    records = builder.old_by_atom.get(builder.source(node).atom_id, ())
    if len(records) > 1 or records and records[0].opcode is not Opcode.CALL:
        raise _Unsupported(GapKind.SOURCE_MAPPING, node, "kwargs Call has ambiguous source computational records")
    old = records[0] if records else None
    definition = _source_definition(builder, node)
    if not is_original_call_definition(builder.semantic, definition, builder.source(node)):
        raise _Unsupported(GapKind.SOURCE_MAPPING, node, "kwargs Call needs its original SG Call definition")
    baseline = len(builder.active_temporaries)
    try:
        cursor, callee = builder.expr(node.func, cursor)
        if cursor is None: return None, None
        _hold(builder, cursor, node.func, callee, "callee")
        parts, inputs = [], []
        for index, child in enumerate(node.args):
            cursor, value = builder.expr(child, cursor)
            if cursor is None: return None, None
            _hold(builder, cursor, child, value, "positional")
            parts.append((child, value)); inputs.append((value, child, "argument", index, None))
        if packing.opname == "LOAD_CONST":
            positional = _constant(builder, node, cursor, packing)
        else:
            cursor, positional, _ = _invoke(builder, cursor, node, inputs, Kind.BUILD_CALL_POSITIONALS,
                tuple(parts), raise_consumed=(), result=True)
        _hold(builder, cursor, node, positional, "positionals")
        receiver = None
        for start, end in _keyword_runs(node):
            keyword = node.keywords[start]
            if keyword.arg is None:
                if receiver is None:
                    cursor, receiver, _ = _invoke(builder, cursor, node, (), Kind.BUILD_MAP, result=True)
                    _hold(builder, cursor, node, receiver, "keywords")
                child = keyword.value
                cursor, update = builder.expr(child, cursor)
                if cursor is None: return None, None
                _hold(builder, cursor, child, update, "update")
                update_source, role = child, "keyword_unpack"
            else:
                held, pairs = [], []
                for index in range(start, end):
                    keyword = node.keywords[index]
                    key = _constant(builder, node, cursor, constants[index])
                    _hold(builder, cursor, node, key, "keyword-name")
                    cursor, value = builder.expr(keyword.value, cursor)
                    if cursor is None: return None, None
                    _hold(builder, cursor, keyword.value, value, "keyword-value")
                    pairs.extend(((key, node, "call-keyword-name", index, None),
                                  (value, keyword.value, "keyword:" + keyword.arg, index, None)))
                    held.extend(((node, key), (keyword.value, value)))
                cursor, update, _ = _invoke(builder, cursor, node, pairs, Kind.BUILD_MAP, tuple(held), result=True)
                _hold(builder, cursor, node, update, "keywords" if receiver is None else "keyword-run")
                if receiver is None:
                    receiver = update
                    continue
                update_source, role = node, "call-keyword-run"
            inputs = ((callee, node.func, "callee", 0, None), (receiver, node, "call-keywords", 0, None),
                      (update, update_source, role, start, None))
            cursor, _, _ = _invoke(builder, cursor, node, inputs, Kind.DICT_MERGE, ((update_source, update),))
        inputs = ((callee, node.func, "callee", 0, None), (positional, node, "call-positionals", 0, None),
                  (receiver, node, "call-keywords", 0, None))
        # This source boundary includes cleanup of its own top-of-stack call
        # operands on an early-no-pop failure. It does NOT claim the raw opcode
        # consumed them on every path, nor that finalizer/monitoring effects are
        # established. The untouched enclosing prefix remains in FRAME_EXIT.
        consumed = ((node.func, callee), (node, positional), (node, receiver))
        cursor, result, identity = _invoke(builder, cursor, node, inputs, Kind.CALL_FUNCTION_EX,
                                          consumed, old=old, result=True)
        if old is None:
            _associate(builder, identity, node, definition, Opcode.CALL)
        builder.pending_targets.append((identity, callee, builder.reference_candidates.get(callee), node))
        builder.gap(GapKind.DYNAMIC_TARGET, node, "kwargs source call is not verified runtime dispatch or expanded actual/formal binding")
        builder.gap(GapKind.EFFECT_SUMMARY, node,
            "kwargs keys/items/hash/equality/error formatting, partial dict mutation and callee effects remain unproved")
        builder.gap(GapKind.FRAME_EFFECT, node,
            "CALL_EX_LOCAL_UNWIND_CONTRACT_UNVERIFIED: call boundary includes its own operand unwind; runtime monitoring, finalizers and whole-frame cleanup remain unproved")
        return cursor, result
    finally:
        del builder.active_temporaries[baseline:]


__all__ = ["lower_kwargs_call"]
