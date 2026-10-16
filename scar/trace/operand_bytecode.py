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


__all__ = ["load_slots"]
