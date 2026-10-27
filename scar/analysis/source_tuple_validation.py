"""Independent, bounded checks of tuple-key ports and modeled pending refs.

This is a query/validator over the existing graph, not a second lifetime IR.
An unknown intermediate consumption rule retains a frontier; it never grants
purity, runtime code-instance identity, or whole-frame lifetime correctness.
"""
from __future__ import annotations

import ast
from collections import deque
import dis

from scar.analysis.source_language import SourceLanguageOptions, require_source_tree, function_exception_types
from scar.ir.program.model import (
    Behavior, BlockArgument, CompletionResult, ExitKind, OperationResult,
    ReferenceValue, StateVersionValue, TerminatorKind, ValueKind, ValueType, value_type,
)
from scar.ir.program.structured import PythonProtocolKind as Kind
from scar.ir.semantics_v2 import Opcode
from scar.ir.v2.semantic import OperationKind


def _need(condition, detail):
    if not condition:
        raise ValueError("tuple key ownership: " + detail)


def validate_tuple_key_ownership(model, graph, interface, metadata, semantic, *,
                                 source_tree=None, options=None, structural_only=False, language=None):
    """Check exact tuple-key sources/ports and success-only input transfer.

    Held instances retain their FRAME_HOLD operation identity and order, even
    when several holds refer to the same ValueID. The local BUILD_TUPLE failure
    suffix is mandatory. Full outer-prefix/normal-continuation claims require
    an independently recoverable pending path, otherwise a frontier is returned.
    """
    _need(type(structural_only) is bool, "verification mode must be explicit")
    if not structural_only:
        _need(isinstance(source_tree, ast.Module) and type(options) is SourceLanguageOptions
              and options.code_evidence is not None,
              "source/code checking requires independent exact SourceLanguageOptions")
        options.code_evidence.require_definition(metadata.source, interface.definition, model.source)
    operations = {row.id: row for row in graph.operations}
    values = {row.id: row for row in graph.values}
    blocks = {block.id: block for region in graph.regions for block in region.blocks}
    protocols = {row.operation: row for row in model.protocols}
    links = {row.operation: row for row in metadata.operation_links}
    use_links = {(row.operation, row.use): row for row in metadata.use_links}
    tuples = {key for key, row in links.items() if row.opcode is Opcode.BUILD_TUPLE}
    normal_producers = {}
    for operation in graph.operations:
        if operation.terminator is not None and operation.terminator.kind is TerminatorKind.INVOKE:
            for edge in operation.terminator.successors:
                if edge.kind is ExitKind.NORMAL:
                    normal_producers.setdefault(edge.block, []).append(operation.id)

    def producer(identity):
        origin = values[identity].origin
        if type(origin) is OperationResult:
            return origin.operation
        if type(origin) is BlockArgument:
            choices = normal_producers.get(origin.block, ())
            return choices[0] if origin.index == 0 and len(choices) == 1 else None
        return None

    selected, pending = set(), []
    for operation in graph.operations:
        link, protocol = links[operation.id], protocols.get(operation.id)
        key_role = ("index" if link.opcode is Opcode.INDEX else
                    "element-key" if protocol is not None and protocol.kind is Kind.STORE_SUBSCRIPT else None)
        if key_role is not None:
            for use in operation.uses:
                source_use = use_links.get((operation.id, use.id))
                if source_use is not None and source_use.role == key_role:
                    key = producer(use.value)
                    if key in tuples:
                        pending.append(key)
    while pending:
        identity = pending.pop()
        if identity in selected:
            continue
        selected.add(identity)
        for use in operations[identity].uses:
            if type(values[use.value]) is ReferenceValue:
                child = producer(use.value)
                if child in tuples:
                    pending.append(child)
    if not selected:
        return {"tuple_keys": 0, "records": [], "frontiers": [],
                "modeled_pending_refs_verified": True, "whole_lifetime_verified": False}

    records, operands_by_id = {}, {}
    state_type = value_type(values[interface.world])
    ref_type = ValueType(ValueKind.REFERENCE)
    from scar.ir.program.source_language import SourceLanguageCapability
    paired = language is not None and SourceLanguageCapability.FUNCTION_TRY_314_V1 in language.capabilities
    raise_types = function_exception_types(language, ref_type, state_type)
    failure_holds = {}
    if paired:
        from scar.analysis.source_function_try_validation import (
            exception_handoff_holds, validate_function_try_protocols)
        # The public query must not infer packet/cleanup ownership merely
        # from a three-port shape. Reuse the original paired dataflow and
        # C0/C1 source checks before following its actual unwind corridor.
        validate_function_try_protocols(model, graph, interface, metadata, semantic, language,
                                        source_tree=source_tree)
    for identity in sorted(selected, key=lambda key: key.wire):
        operation, link = operations[identity], links[identity]
        definition = semantic.definitions.get(link.semantic_operation)
        atom = semantic.source_atoms.get(link.source.atom_id)
        _need(definition is not None and definition.kind is OperationKind.OPERATOR
              and definition.metadata.get("ast_type") == "Tuple" and len(definition.output_slots) == 1
              and definition.code_id == link.source.atom_id.wire and link.source.atom_id in definition.source_atoms
              and atom is not None and atom.reference == link.source and atom.kind == "Tuple",
              "tuple lost its unique original SG/source/output-slot correspondence")
        _need(operation.terminator is not None and operation.terminator.kind is TerminatorKind.INVOKE
              and operation.callee is None and not operation.effects_complete
              and Behavior.MEMORY in operation.behaviors
              and tuple(use.id for use in operation.uses) == operation.invoke_arguments,
              "BUILD_TUPLE must retain its incomplete allocation invoke and exact Uses")
        operands = operation.uses[:-1]
        _need(all(type(values[use.value]) is ReferenceValue for use in operands)
              and type(values[operation.uses[-1].value]) is StateVersionValue
              and values[operation.uses[-1].value].location == values[interface.world].location,
              "tuple references/world do not retain their original typed ports")
        expected = ((ExitKind.NORMAL, (ref_type, state_type)), (ExitKind.RAISE, raise_types))
        _need(tuple((row.kind, row.types) for row in operation.completions) == expected
              and tuple(edge.kind for edge in operation.terminator.successors) == (ExitKind.NORMAL, ExitKind.RAISE)
              and all(edge.arguments == tuple(CompletionResult(index) for index in range(len(types)))
                      and tuple(value_type(values[value]) for value in blocks[edge.block].arguments) == types
                      for edge, (_, types) in zip(operation.terminator.successors, expected)),
              "tuple normal/raise payloads must be their own ordered CompletionResults")
        child_sources = []
        for index, use in enumerate(operands):
            row = use_links.get((identity, use.id))
            child = semantic.source_atoms.get(row.source.atom_id) if row is not None else None
            _need(row is not None and row.role == "element" and row.index == index
                  and child is not None and child.reference == row.source,
                  "tuple elements lost their original ordered child Uses")
            child_sources.append(row.source)
        if not structural_only:
            _need(source_tree is not None and options is not None and options.code_evidence is not None,
                  "tuple construction requires independent exact source and CodeWitness inputs")
            nodes = [node for node in require_source_tree(source_tree, metadata.source, link.source)
                     if isinstance(node, ast.Tuple)]
            _need(len(nodes) == 1 and isinstance(nodes[0].ctx, ast.Load)
                  and not any(isinstance(child, ast.Starred) for child in nodes[0].elts),
                  "tuple construction is not one exact fixed-arity Load expression")
            node, = nodes
            _need(tuple((child.lineno, child.end_lineno, child.col_offset, child.end_col_offset)
                        for child in node.elts)
                  == tuple((row.start_line, row.end_line, row.start_column, row.end_column)
                           for row in child_sources), "tuple child sequence differs from exact source")
            instructions = [row for row in dis.get_instructions(options.code_evidence.code)
                if tuple(row.positions) == (node.lineno, node.end_lineno, node.col_offset, node.end_col_offset)]
            _need(not any(row.opname == "LOAD_CONST" and type(row.argval) is tuple for row in instructions),
                  "compiler constant tuple cannot be modeled as a new BUILD_TUPLE allocation")
            _need(sum(row.opname == "BUILD_TUPLE" and row.arg == len(operands) for row in instructions) == 1,
                  "tuple has no unique exact BUILD_TUPLE arity/position witness")
        operands_by_id[identity] = tuple((use.value, source) for use, source in zip(operands, child_sources))
        failure = blocks[operation.terminator.successors[1].block]
        if paired:
            held = exception_handoff_holds(failure.id, operations, protocols, blocks, use_links)
        else:
            _need(len(failure.operations) == 2 and protocols.get(failure.operations[0]) is not None
                  and protocols[failure.operations[0]].kind is Kind.FRAME_EXIT
                  and operations[failure.operations[1]].terminator.kind is TerminatorKind.RAISE,
                  "tuple failure must retain the original no-handler FrameExit/RAISE path")
            cleanup = operations[failure.operations[0]]
            held = tuple(use.value for use in cleanup.uses
                         if (row := use_links.get((cleanup.id, use.id))) is not None and row.role == "held-temporary")
        failure_holds[identity] = held
        parts = tuple(use.value for use in operands)
        _need(not parts or len(held) >= len(parts) and held[-len(parts):] == parts,
              "BUILD_TUPLE failure dropped/reordered pending element references before ERROR_NO_POP unwind")
        records[identity] = {"operation": identity.wire, "ordered_source_ports_verified": True,
            "code_witness_verified": not structural_only, "raise_element_retention_verified": True,
            "outer_pending_verified": False, "normal_pending_verified": True,
            "normal_cleanup_sites": set(), "frontiers": []}

    # Abstract pending states are derived from graph/control/source records,
    # never a lowerer-reported consumed set. Unknown contracts remain explicit.
    frontiers, frontier_seen = [], set()
    def frontier(kind, operation, affected):
        key = kind, operation.wire
        if key not in frontier_seen:
            frontier_seen.add(key); frontiers.append({"kind": kind, "operation": operation.wire})
        for identity in affected:
            row = records[identity]
            if key not in row["frontiers"]:
                row["frontiers"].append(key)
            row["normal_pending_verified"] = False

    region = next(row for row in graph.regions if row.id == graph.root)
    # hold tuple=(original FRAME_HOLD operation, original reference, source).
    states, queue = {region.entry: ((), frozenset(), frozenset())}, deque((region.entry,))
    preserving = frozenset((Kind.LOOKUP_GLOBAL, Kind.READ_FREE_CELL, Kind.READ_LOCAL_CELL,
        Kind.MAKE_CELL, Kind.GET_ITERATOR, Kind.ADVANCE_ITERATOR, Kind.TRUTH,
        Kind.MAKE_UNBOUND_LOCAL_ERROR, Kind.MATCH_STOP_ITERATION, Kind.READ_CODE_CONSTANT))
    maximum = max(128, len(blocks) * (len(selected) + 4))
    visits = 0
    def send(block, stack, unknown, affected):
        incoming = stack, frozenset(unknown), frozenset(affected)
        old = states.get(block)
        if old is not None:
            if old[0] != stack:
                common = []
                for left, right in zip(old[0], stack):
                    if left != right:
                        break
                    common.append(left)
                stack = tuple(common)
                token = ("UNRESOLVED_PENDING_JOIN", blocks[block].operations[0])
                unknown = frozenset(unknown) | old[1] | frozenset((token,))
                frontier(*token, old[2] | frozenset(affected))
            incoming = stack, old[1] | frozenset(unknown), old[2] | frozenset(affected)
        if old != incoming:
            states[block] = incoming; queue.append(block)

    while queue:
        visits += 1
        if visits > maximum:
            frontier("PENDING_DATAFLOW_BUDGET", next(iter(selected)), selected)
            break
        block_id = queue.popleft()
        stack, unknown, affected = states[block_id]
        for identity in blocks[block_id].operations:
            operation, protocol = operations[identity], protocols.get(identity)
            kind = protocol.kind if protocol is not None else None
            refs = tuple(use.value for use in operation.uses if type(values[use.value]) is ReferenceValue)
            if kind is Kind.FRAME_HOLD_TEMPORARY:
                _need(len(refs) == 1, "temporary hold has no unique reference")
                stack += ((identity, refs[0], protocol.source),)
            elif kind is Kind.FRAME_RELEASE_TEMPORARY:
                _need(len(refs) == 1, "temporary release has no unique reference")
                if stack and stack[-1][1] == refs[0]:
                    stack = stack[:-1]
                else:
                    token = ("UNRECOVERED_TEMPORARY_RELEASE", identity)
                    unknown |= frozenset((token,)); frontier(*token, affected)
            elif kind is Kind.FRAME_EXIT or paired and kind is Kind.FUNCTION_FRAME_EXIT_EXCEPTION_PACKET:
                held = tuple(use.value for use in operation.uses
                    if (row := use_links.get((identity, use.id))) is not None and row.role == "held-temporary")
                if affected and not unknown:
                    _need(held == tuple(item[1] for item in stack),
                          "normal/raise FrameExit lost, duplicated or reordered a modeled pending hold")
                    for key in affected:
                        records[key]["normal_cleanup_sites"].add(identity.wire)
            terminator = operation.terminator
            if terminator is None:
                continue
            if terminator.kind is TerminatorKind.INVOKE:
                normal_stack, failure_stack = stack, stack
                normal_affected, failure_affected = affected, affected
                if identity in selected:
                    expected = operands_by_id[identity]
                    parts = tuple(item[1:] for item in stack[-len(expected):]) if expected else ()
                    _need(unknown or parts == expected, "tuple inputs are not their ordered pending hold instances")
                    row = records[identity]
                    row["outer_pending_verified"] = not unknown
                    for token in unknown:
                        frontier(*token, (identity,))
                    normal_stack = stack[:-len(expected)] if expected else stack
                    normal_affected |= frozenset((identity,))
                    if not unknown:
                        held = failure_holds[identity]
                        _need(held == tuple(item[1] for item in stack),
                              "tuple failure changed its pending outer prefix or element hold instances")
                elif stack and kind not in preserving:
                    # Existing slice/index/map adapters have an input-transfer
                    # convention but are not independently proven here. Apply
                    # their structural suffix only to continue the query,
                    # retaining UNKNOWN instead of certifying that convention.
                    token = ("INTERMEDIATE_PRIMITIVE_CONSUMPTION_UNVERIFIED", identity)
                    unknown |= frozenset((token,)); frontier(*token, affected)
                    consumed = ()
                    if kind is Kind.BUILD_SLICE or links[identity].opcode is Opcode.INDEX:
                        consumed = refs
                    elif kind is Kind.UNPACK_FIXED:
                        consumed = refs[:1]
                    elif kind is Kind.BUILD_MAP:
                        consumed = refs
                    elif kind is Kind.MAP_ADD:
                        consumed = refs[-2:]
                    elif kind is Kind.DICT_UPDATE:
                        consumed = refs[-1:]
                    if consumed and tuple(item[1] for item in stack[-len(consumed):]) == consumed:
                        normal_stack = failure_stack = stack[:-len(consumed)]
                send(terminator.successors[0].block, normal_stack, unknown, normal_affected)
                send(terminator.successors[1].block, failure_stack, unknown, failure_affected)
            elif terminator.kind in (TerminatorKind.JUMP, TerminatorKind.BRANCH):
                for edge in terminator.successors:
                    send(edge.block, stack, unknown, affected)
            elif terminator.kind not in (TerminatorKind.RETURN, TerminatorKind.RAISE):
                frontier("UNSUPPORTED_PENDING_CONTROL", identity, affected)
            break
    rows = list(records.values())
    for row in rows:
        row["normal_cleanup_sites"] = sorted(row["normal_cleanup_sites"])
        row["normal_pending_verified"] &= bool(row["normal_cleanup_sites"])
        row["frontiers"] = [{"kind": kind, "operation": operation} for kind, operation in row["frontiers"]]
    return {"tuple_keys": len(rows), "records": rows, "frontiers": frontiers,
            "modeled_pending_refs_verified": not frontiers and all(
                row["outer_pending_verified"] and row["normal_pending_verified"] for row in rows),
            "whole_lifetime_verified": False, "runtime_code_instance_established": False,
            "physical_allocation_events_established": False}


__all__ = ["validate_tuple_key_ownership"]
