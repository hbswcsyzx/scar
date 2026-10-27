"""Small, versioned decoder for the load occurrences B1 can observe.

This is intentionally narrower than a Python bytecode interpreter.  It only
names ordinary local loads, the measured 3.14 dual-borrow local load, and
global-name loads.  In particular, it does not infer stack effects for mixed
load/store instructions, attributes, closures, or packed call forms.
"""
from __future__ import annotations

import dis
from types import CodeType


_FAST_LOADS = frozenset({"LOAD_FAST", "LOAD_FAST_BORROW"})
_DUAL_BORROW = "LOAD_FAST_BORROW_LOAD_FAST_BORROW"
_GLOBAL_LOADS = frozenset({"LOAD_GLOBAL"})
CALL_FAMILY_PREFIX = "CALL"


def load_slots(code, instruction):
    """Return ordered supported load slots for one exact disassembly record.

    The result is ``(suboperand, namespace, name, slot_index)`` tuples.
    ``namespace`` is ``FAST_LOCAL`` or ``GLOBAL``; a runtime global lookup can
    resolve to either the globals or builtins dictionary.  ``()`` means this
    instruction is not a load.  ``None`` means it is a load shape this rule
    does not decode.

    CPython 3.14.7 encodes ``LOAD_FAST_BORROW_LOAD_FAST_BORROW`` as the first
    local index in the high nibble and the second index in the low nibble.
    Both indexes are checked against ``argval`` and ``co_varnames`` so a
    changed or unfamiliar encoding fails closed.
    """
    if type(code) is not CodeType or type(instruction) is not dis.Instruction:
        raise TypeError("load_slots requires exact CodeType and dis.Instruction values")

    opname = instruction.opname
    if opname in _FAST_LOADS:
        index = instruction.arg
        name = instruction.argval
        if (type(index) is not int or index < 0 or index >= code.co_nlocals
                or type(name) is not str or index >= len(code.co_varnames)
                or code.co_varnames[index] != name):
            return None
        return ((0, "FAST_LOCAL", name, index),)

    if opname == _DUAL_BORROW:
        packed = instruction.arg
        names = instruction.argval
        if type(packed) is not int or not 0 <= packed <= 0xFF:
            return None
        if type(names) is not tuple or len(names) != 2 or any(type(name) is not str for name in names):
            return None
        indexes = (packed >> 4, packed & 0xF)
        result = []
        for ordinal, (index, name) in enumerate(zip(indexes, names)):
            if (index >= code.co_nlocals or index >= len(code.co_varnames)
                    or code.co_varnames[index] != name):
                return None
            result.append((ordinal, "FAST_LOCAL", name, index))
        return tuple(result)

    if opname in _GLOBAL_LOADS:
        name = instruction.argval
        if type(name) is not str or not name:
            return None
        return ((0, "GLOBAL", name, None),)

    if opname.startswith("LOAD_"):
        return None
    return ()


def call_family_offsets(code, instructions=None):
    """Return the logical offsets of all CPython ``CALL*`` instructions.

    This set is a sparse capture selection only.  It does not mean that each
    opcode dispatches a Python callable; for example ``CALL_INTRINSIC_*`` is
    included as a bytecode location but is not an operand-route candidate.
    """
    code, instructions = _checked_instructions(code, instructions)
    return frozenset(item.offset for item in instructions
                     if item.opname.startswith(CALL_FAMILY_PREFIX))


def call_window_selection(code, instructions=None):
    """Select exact straight-line bytecode windows for fixed positional calls.

    A returned mapping is keyed by a plain ``CALL`` offset and contains the
    complete logical instruction offsets from the first required name load
    through that ``CALL``.  Every intervening instruction must be a supported
    load, ``PUSH_NULL``, or ``NOP``.  A control-flow or exception-handler edge
    may enter at the first instruction, but not inside the window.

    ``expiry_offsets`` contains the normal successor of every ``CALL*``
    instruction and every exception-table handler target.  These locations
    must remain monitored so a pending call attempt can be expired on a
    normal continuation or exception path, even when no attempt was pending
    the first time the location ran.

    This is a bytecode candidate filter, not a source or runtime proof.  The
    source matcher must independently replay the code and match each window
    to the exact source call and ordered name occurrences.
    """
    code, instructions = _checked_instructions(code, instructions)
    by_offset = {item.offset: index for index, item in enumerate(instructions)}
    jump_targets = {item.offset for item in instructions if item.is_jump_target}
    call_offsets = {
        index for index, item in enumerate(instructions)
        if item.opname.startswith(CALL_FAMILY_PREFIX)
    }
    expiry_offsets = set()
    for index in call_offsets:
        if index + 1 < len(instructions):
            expiry_offsets.add(instructions[index + 1].offset)

    try:
        exception_entries = dis.Bytecode(code).exception_entries
    except BaseException as error:
        raise ValueError("cannot decode CPython exception table for call windows") from error
    exception_targets = set()
    for entry in exception_entries:
        target = entry.target
        if type(target) is not int or target < 0:
            raise ValueError("exception table has a noncanonical handler target")
        if target not in by_offset:
            raise ValueError("exception table handler is not a logical instruction offset")
        exception_targets.add(target)
        expiry_offsets.add(target)

    windows = {}
    for position, call in enumerate(instructions):
        if call.opname != "CALL" or type(call.arg) is not int or call.arg < 0:
            continue
        required_loads = call.arg + 1
        count = 0
        reversed_window = []
        valid = True
        # Walk the shared instruction tuple by index.  A slice per CALL makes
        # a many-call code object allocate/copy every preceding prefix.
        for previous_position in range(position - 1, -1, -1):
            instruction = instructions[previous_position]
            slots = load_slots(code, instruction)
            if slots is None:
                valid = False
                break
            if slots:
                count += len(slots)
            elif instruction.opname not in ("PUSH_NULL", "NOP"):
                valid = False
                break
            reversed_window.append(instruction)
            if count >= required_loads:
                break
        if not valid or count != required_loads:
            continue
        window = tuple(item.offset for item in reversed(reversed_window)) + (call.offset,)
        if len(set(window)) != len(window) or tuple(sorted(window)) != window:
            continue
        interior = set(window[1:])
        if interior & (jump_targets | exception_targets):
            continue
        windows[call.offset] = window

    # Keep this sanity check close to disassembly decoding: callback sites
    # must always correspond to an instruction in the same exact code object.
    if any(offset not in by_offset for offsets in windows.values() for offset in offsets):
        raise ValueError("call-window plan contains an unknown instruction offset")
    return windows, frozenset(expiry_offsets)


def _checked_instructions(code, instructions):
    if type(code) is not CodeType:
        raise TypeError("call-window selection requires an exact CodeType")
    if instructions is None:
        instructions = tuple(dis.get_instructions(code))
    elif type(instructions) in (tuple, list):
        instructions = tuple(instructions)
    else:
        raise TypeError("instructions must be a list/tuple of exact dis.Instruction values")
    previous = -1
    for item in instructions:
        if type(item) is not dis.Instruction:
            raise TypeError("instructions must contain exact dis.Instruction values")
        if type(item.offset) is not int or item.offset <= previous:
            raise ValueError("disassembly instruction offsets must be strictly increasing")
        if type(item.opname) is not str:
            raise ValueError("disassembly opcode name must be exact text")
        previous = item.offset
    return code, instructions


__all__ = ["CALL_FAMILY_PREFIX", "call_family_offsets", "call_window_selection", "load_slots"]
