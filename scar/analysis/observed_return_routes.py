"""Conservative compiler value forwarding into original cleanup continuations.

This is a normal-flow stack slice, not a bytecode interpreter or observed
cleanup trace. A branch/handler boundary or unsupported instruction stays open.
Canonical source/cleanup validity is supplied by the existing body owner.
"""
from __future__ import annotations

import dis

from scar.ir.program.cleanup import CleanupRouteTerminator
from scar.ir.program.control import LanguageCompletionKind, PendingDispatchTerminator
from scar.ir.program.model import BlockArgument, OperationResult, ReferenceValue


_LOADS = {'LOAD_CONST', 'LOAD_FAST', 'LOAD_FAST_BORROW', 'LOAD_DEREF', 'LOAD_NAME',
    'LOAD_CLOSURE', 'LOAD_COMMON_CONSTANT', 'LOAD_FAST_CHECK'}
_RESULTS = {'CALL', 'CALL_KW', 'CALL_FUNCTION_EX', 'BINARY_OP', 'BINARY_SUBSCR',
    'UNARY_NEGATIVE', 'UNARY_POSITIVE', 'UNARY_NOT', 'UNARY_INVERT', 'TO_BOOL',
    'BUILD_LIST', 'BUILD_TUPLE', 'BUILD_SET', 'BUILD_MAP', 'BUILD_CONST_KEY_MAP'}
_STORES = {'STORE_FAST', 'STORE_DEREF', 'STORE_NAME', 'STORE_GLOBAL', 'STORE_ATTR',
    'STORE_SUBSCR', 'STORE_FAST_STORE_FAST', 'POP_TOP'}
_IDLE = {'NOP', 'RESUME', 'CACHE', 'EXTENDED_ARG', 'COPY_FREE_VARS'}


def compiler_return_producer(code, offset, *, max_steps=1024):
    """Find a returned expression producer through one proven linear tail.

    Depth is relative to stack top. SWAP/COPY are inverted exactly; values
    below a call's output move by its compiler-declared stack effect. Calls
    and other expression results are producers, never assumed transparent.
    """
    instructions = tuple(dis.get_instructions(code))
    selected = [number for number, instruction in enumerate(instructions) if instruction.offset == offset]
    if len(selected) != 1:
        return None
    number, = selected
    result = instructions[number]
    if result.opname == 'RETURN_CONST':
        return result
    if result.opname != 'RETURN_VALUE' or result.is_jump_target:
        return None
    handlers = {entry.target for entry in dis.Bytecode(code).exception_entries}
    depth = 0
    for instruction in reversed(instructions[max(0, number - max_steps):number]):
        if instruction.is_jump_target or instruction.offset in handlers:
            return None
        name, argument = instruction.opname, instruction.arg
        if name == 'SWAP':
            if argument is None or argument < 1:
                return None
            if depth == 0:
                depth = argument - 1
            elif depth == argument - 1:
                depth = 0
            continue
        if name == 'COPY':
            if argument is None or argument < 1:
                return None
            depth = argument - 1 if depth == 0 else depth - 1
            continue
        if name in _LOADS or name in _RESULTS:
            pushes, expression = 1, True
        elif name == 'LOAD_GLOBAL':
            pushes, expression = 1 + (argument & 1), True
        elif name == 'LOAD_ATTR':
            pushes, expression = 1 + (argument & 1), not (argument & 1)
        elif name == 'PUSH_NULL':
            pushes, expression = 1, False
        elif name == 'LOAD_SPECIAL':
            pushes, expression = 2, False
        elif name in _STORES or name in _IDLE:
            pushes, expression = 0, False
        else:
            return None
        if depth < pushes:
            return instruction if depth == 0 and expression else None
        try:
            effect = dis.stack_effect(instruction.opcode, argument) if argument is not None else dis.stack_effect(instruction.opcode)
        except (TypeError, ValueError):
            return None
        depth -= effect
        if not 0 <= depth <= 4096:
            return None
    return None


def cleanup_continuation(body, terminal, source):
    """Require this source Return's original typed post-cleanup continuation.

    Existing source_function_try_validation checks the return carrier through
    actual SSA Uses filtered by this port. Here admission additionally needs
    its pending tag, a real resume/replacement, and the original dispatch edge.
    """
    graph, index = body.graph, body.index
    links = {link.operation: link.source for link in body.operation_links}
    if links.get(terminal.operation) != source:
        return False
    value = index.values[terminal.value]
    if type(value) is not ReferenceValue or type(value.origin) is not BlockArgument or value.origin.block != terminal.block:
        return False
    ports = [port for port in graph.control_ports if port.kind is LanguageCompletionKind.FALLTHROUGH
        and port.block == terminal.block]
    if len(ports) != 1:
        return False
    port, = ports
    pendings = [pending for pending in graph.pending_completions if pending.port == port.id
        and type(index.values[pending.value].origin) is OperationResult
        and links.get(index.values[pending.value].origin.operation) == source]
    if len(pendings) != 1:
        return False
    pending, = pendings
    incoming = []
    for operation in graph.operations:
        term = operation.terminator
        if type(term) is PendingDispatchTerminator:
            for edge in term.successors:
                if edge.port == port.id and edge.block == terminal.block:
                    operand = edge.arguments[value.origin.index]
                    if operand in {use.id for use in operation.uses}:
                        incoming.append(operation)
    if not incoming:
        return False
    # Forwarding enters a cleanup with this pending tag. An overriding return
    # instead becomes a CleanupReplace's exact new pending operand.
    for operation in graph.operations:
        term = operation.terminator
        if type(term) is not CleanupRouteTerminator or index.use_site(term.pending).use.value != pending.value:
            continue
        for edge in term.successors:
            interfaces = [item for item in graph.cleanup_interfaces if item.entry == edge.block]
            if edge.port == port.id and any(resume.cleanup == item.scope
                    for item in interfaces for resume in graph.cleanup_resumes):
                return True
    return any(index.use_site(replacement.replacement).use.value == pending.value
        for replacement in graph.cleanup_replacements)


__all__ = ['compiler_return_producer', 'cleanup_continuation']
