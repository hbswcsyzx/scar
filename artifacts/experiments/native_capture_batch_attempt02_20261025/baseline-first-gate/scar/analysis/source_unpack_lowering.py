"""Fixed arity over original local ports, with no synthetic tuple/getitem loop."""
from __future__ import annotations

import ast

from scar.analysis.program_lowering import _REF, _Unsupported
from scar.analysis.source_heap_lowering import _hold
from scar.analysis.source_mapping_lowering import _transfer
from scar.ir.program.model import ExitKind
from scar.ir.program.source import GapKind, SourceRole
from scar.ir.program.source_language import UnpackShape
from scar.ir.program.structured import PythonProtocolKind


def _check(builder, target):
    if isinstance(target, (ast.Tuple, ast.List)) and isinstance(target.ctx, ast.Store):
        for child in target.elts:
            _check(builder, child)
    elif not (isinstance(target, ast.Name) and isinstance(target.ctx, ast.Store) and target.id in builder.locals):
        raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, target,
            "UNPACK_FIXED requires fixed tuple/list ordinary-local leaves; starred/effectful targets remain unimplemented")


def lower_unpack_target(builder, target, rhs, cursor, *, rhs_held=False):
    _check(builder, target)
    if not isinstance(target, (ast.Tuple, ast.List)):
        raise _Unsupported(GapKind.SOURCE_MAPPING, target, "unpack root is not a tuple/list target")
    if rhs_held and (not builder.active_temporaries or builder.active_temporaries[-1] != rhs):
        raise _Unsupported(GapKind.SOURCE_MAPPING, target, "nested unpack does not own its exact pending RHS")
    baseline = len(builder.active_temporaries) - int(rhs_held)
    if not rhs_held:
        _hold(builder, cursor, target, rhs)
    consumed = ((target, rhs),)

    def failed(failure, exception):
        pending = tuple(builder.active_temporaries)
        try:
            _transfer(builder, consumed, target)
            builder.finish_exit(failure, target, exception, ExitKind.RAISE)
        finally:
            builder.active_temporaries[:] = pending

    try:
        cursor, values, operation = builder.invoke_results(cursor, target,
            ((rhs, target, "unpack-source", 0, None),), role=SourceRole.LOCAL_BINDING,
            result_types=(_REF,) * len(target.elts), failure_handler=failed)
        builder.protocol(operation, PythonProtocolKind.UNPACK_FIXED, target)
        builder.language_unpackings.append(UnpackShape(operation, builder.source(target),
            tuple(builder.source(child) for child in target.elts)))
        _transfer(builder, consumed, target)
        # Normal results are published stack references; reverse holds put
        # the first target on top. No extra INCREF or allocation is asserted.
        for child, value in reversed(tuple(zip(target.elts, values))):
            _hold(builder, cursor, child, value)
        for child, value in zip(target.elts, values):
            if isinstance(child, (ast.Tuple, ast.List)):
                cursor = lower_unpack_target(builder, child, value, cursor, rhs_held=True)
            else:
                cursor = builder.store(child, value, cursor)
                _transfer(builder, ((child, value),), child)
        builder.gap(GapKind.EFFECT_SUMMARY, target,
            "fixed unpack order/arity/ports are connected; iterator dispatch, aliasing, finalizers and runtime implementation remain unproved")
        return cursor
    finally:
        del builder.active_temporaries[baseline:]


__all__ = ["lower_unpack_target"]
