"""Definition-time function creation in a module mapping frame.

The factory is one incomplete compound interface: default packing, the lazy
annotation-function factory and SET_FUNCTION_ATTRIBUTE belong inside it. It
returns only the function reference/world, never executes either child body,
and owns cleanup of the default inputs on both outcomes. Decorator evaluation,
application and the final mapping write remain separate source operations.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, replace
import dis
import inspect
from types import CodeType

from scar.analysis.program_lowering import _Unsupported
from scar.analysis.source_call_lowering import _constant, _invoke
from scar.analysis.source_mapping_lowering import _transfer
from scar.ir.program.source import GapKind
from scar.ir.program.model import ExitKind
from scar.ir.program.structured import PythonProtocolKind


def _span(node):
    return node.lineno, node.end_lineno, node.col_offset, node.end_col_offset


def _unsupported(node, detail):
    raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, node, "MAPPING_FUNCTION_" + detail)


@dataclass(frozen=True, slots=True)
class MappingFunctionPlan:
    child: dis.Instruction
    annotation: dis.Instruction | None
    defaults_constant: dis.Instruction | None
    keyword_defaults: tuple[tuple[ast.arg, ast.expr], ...]
    attributes: tuple[int, ...]
    decorator_calls: tuple[dis.Instruction, ...]
    store: dis.Instruction


def mapping_function_plan(node, parent_code):
    """Check the exact original module creation window; never execute code."""
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        _unsupported(node, "FUNCTION_DEFINITION_REQUIRED")
    if type(parent_code) is not CodeType or parent_code.co_name != "<module>" or parent_code.co_freevars:
        _unsupported(node, "EXACT_MODULE_CODE_REQUIRED")
    if node.type_params:
        _unsupported(node, "TYPE_PARAMETER_SCOPE_UNIMPLEMENTED")
    # dis has already incorporated EXTENDED_ARG into each following oparg;
    # prefix words are compiler encoding, not additional definition stages.
    rows = tuple(row for row in dis.get_instructions(parent_code, adaptive=False, show_caches=False)
                 if row.opname != "EXTENDED_ARG")
    own = [row for row in rows if tuple(row.positions) == _span(node)]
    children = [row for row in own if row.opname == "LOAD_CONST" and type(row.argval) is CodeType
                and row.argval.co_name == node.name and row.argval.co_qualname == node.name
                and row.argval.co_firstlineno == min([node.lineno] + [n.lineno for n in node.decorator_list])]
    if len(children) != 1:
        _unsupported(node, "ORIGINAL_CHILD_CONSTANT_SLOT_UNAVAILABLE")
    child, = children
    async_flags = inspect.CO_COROUTINE | inspect.CO_ASYNC_GENERATOR
    if bool(child.argval.co_flags & async_flags) != isinstance(node, ast.AsyncFunctionDef):
        _unsupported(node, "CHILD_ASYNC_KIND_DIFFERS")
    if child.argval.co_freevars:
        _unsupported(node, "CHILD_CLOSURE_BINDING_UNIMPLEMENTED")
    stores = [row for row in own if row.offset > child.offset and row.opname == "STORE_NAME"
              and row.argval == node.name]
    if len(stores) != 1:
        _unsupported(node, "ORIGINAL_MAPPING_STORE_UNAVAILABLE")
    store, = stores
    own = [row for row in own if row.offset <= store.offset]
    args = (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs,
            *((node.args.vararg,) if node.args.vararg else ()),
            *((node.args.kwarg,) if node.args.kwarg else ()))
    annotated = node.returns is not None or any(arg.annotation is not None for arg in args)
    annotations = [row for row in own if row.opname == "LOAD_CONST" and type(row.argval) is CodeType
                   and row.argval.co_name == "__annotate__" and row.offset < child.offset]
    if len(annotations) != int(annotated):
        _unsupported(node, "DEFERRED_ANNOTATION_FACTORY_UNAVAILABLE")
    annotation = annotations[0] if annotations else None
    if annotation is not None and annotation.argval.co_freevars:
        _unsupported(node, "ANNOTATION_CLOSURE_BINDING_UNIMPLEMENTED")
    defaults_constant = None
    expected = []
    if node.args.defaults:
        candidates = [row for row in own if row.opname == "LOAD_CONST" and type(row.argval) is tuple]
        exact = [row for row in candidates if len(row.argval) == len(node.args.defaults)
                 and all(isinstance(n, ast.Constant) and type(n.value) is type(value) and n.value == value
                         for n, value in zip(node.args.defaults, row.argval))]
        if exact:
            if len(exact) != 1:
                _unsupported(node, "DEFAULT_CONSTANT_TUPLE_AMBIGUOUS")
            defaults_constant = exact[0]
            expected.append(("LOAD_CONST", defaults_constant.arg))
        else:
            expected.append(("BUILD_TUPLE", len(node.args.defaults)))
    keyword = tuple((arg, value) for arg, value in zip(node.args.kwonlyargs, node.args.kw_defaults)
                    if value is not None)
    if keyword:
        builds = [row for row in own if row.opname == "BUILD_MAP"]
        incremental = len(builds) == 1 and builds[0].arg == 0
        if incremental:
            expected.append(("BUILD_MAP", 0))
        for arg, _ in keyword:
            keys = [row for row in own if row.opname == "LOAD_CONST" and type(row.argval) is str
                    and row.argval == arg.arg]
            if len(keys) != 1:
                _unsupported(node, "KEYWORD_DEFAULT_KEY_UNAVAILABLE")
            expected.append(("LOAD_CONST", keys[0].arg))
            if incremental:
                expected.append(("MAP_ADD", 1))
        if not incremental:
            expected.append(("BUILD_MAP", len(keyword)))
    for load in (annotation, child):
        if load is not None:
            expected.extend((("LOAD_CONST", load.arg), ("MAKE_FUNCTION", None)))
    attributes = tuple(flag for present, flag in ((annotated, 16), (bool(keyword), 2),
                                                  (bool(node.args.defaults), 1)) if present)
    expected.extend(("SET_FUNCTION_ATTRIBUTE", flag) for flag in attributes)
    expected.append(("STORE_NAME", store.arg))
    actual = [(row.opname, row.arg) for row in own]
    if actual != expected:
        _unsupported(node, "EXACT_PACK_FACTORY_ATTRIBUTE_SEQUENCE_UNAVAILABLE")
    make = rows[rows.index(child) + 1]
    applications = [row for row in rows if make.offset < row.offset < store.offset
                    and row.opname in ("CALL", "CALL_KW", "CALL_FUNCTION_EX")]
    if (len(applications) != len(node.decorator_list)
            or any(row.opname != "CALL" or row.arg != 0 or tuple(row.positions) != _span(decorator)
                   for row, decorator in zip(applications, reversed(node.decorator_list)))):
        _unsupported(node, "DECORATOR_APPLICATION_SEQUENCE_UNAVAILABLE")
    return MappingFunctionPlan(child, annotation, defaults_constant, keyword,
                               attributes, tuple(applications), store)


def _hold(builder, cursor, node, value, role):
    builder.frame_transition(cursor, node, ((value, node, "mapping-function-held-" + role),),
                             PythonProtocolKind.FRAME_HOLD_TEMPORARY)
    builder.active_temporaries.append(value)


def lower_mapping_function(builder, node, cursor):
    """Create and bind one function through the original mapping-frame ABI."""
    from scar.analysis.source_module_lowering import require_root_evidence
    from scar.ir.program.module_entries import FrameBodyProtocolKind as K
    from scar.ir.v2.semantic import OperationKind
    evidence = builder.evidence
    require_root_evidence(builder.unit, evidence)
    plan = mapping_function_plan(node, evidence.code)
    source = builder.source(node)
    declarations = [d for d in builder.by_atom.get(source.atom_id.wire, ())
                    if d.metadata.get("phase") == "definition_time"]
    bodies = [d for d in builder.by_atom.get(source.atom_id.wire, ())
              if d.metadata.get("phase") == "call_time"
              and d.kind in (OperationKind.FUNCTION, OperationKind.METHOD)]
    if len(declarations) != 1 or len(bodies) != 1:
        _unsupported(node, "ORIGINAL_DECLARATION_AND_BODY_REQUIRED")
    baseline = len(builder.active_temporaries)
    sinks = getattr(builder, "failure_sinks", None)
    def local_failure(failure, payload):
        saved = tuple(builder.active_temporaries)
        try:
            for value in reversed(builder.active_temporaries[baseline:]):
                builder.frame_transition(failure, node,
                    ((value, node, "mapping-function-exception-unwind"),),
                    PythonProtocolKind.FRAME_RELEASE_TEMPORARY)
            del builder.active_temporaries[baseline:]
            # Forward the same exception/traceback pair with the actual
            # post-release world. Temporarily remove only our own sink, so
            # the existing outer handler/C0/C1 path receives it normally.
            if not sinks or sinks[-1] is not local_failure:
                raise ValueError("mapping function failure-sink ownership changed")
            sinks.pop()
            try:
                return builder.finish_exit(failure, node, payload, ExitKind.RAISE)
            finally:
                sinks.append(local_failure)
        finally:
            builder.active_temporaries[:] = saved
    if sinks is not None:
        sinks.append(local_failure)
    try:
        decorators = []
        for index, expression in enumerate(node.decorator_list):
            cursor, value = builder.expr(expression, cursor)
            if cursor is None:
                return None
            _hold(builder, cursor, expression, value, "decorator")
            decorators.append((expression, value, index))
        inputs = []
        consumed = []
        if plan.defaults_constant is not None:
            inputs.append((_constant(builder, node, cursor, plan.defaults_constant), node,
                           "function-defaults-tuple", 0, None))
        else:
            for index, expression in enumerate(node.args.defaults):
                cursor, value = builder.expr(expression, cursor)
                if cursor is None:
                    return None
                _hold(builder, cursor, expression, value, "default")
                consumed.append((expression, value))
                inputs.append((value, expression, "function-default", index, None))
        for index, (arg, expression) in enumerate(plan.keyword_defaults):
            cursor, value = builder.expr(expression, cursor)
            if cursor is None:
                return None
            _hold(builder, cursor, expression, value, "keyword-default")
            consumed.append((expression, value))
            inputs.append((value, expression, "function-keyword-default:" + arg.arg, index, None))
        code = _constant(builder, node, cursor, plan.child)
        inputs = [(code, node, "function-code", 0, None),
                  (builder.entry_references[1], node, "function-globals", 0, None), *inputs]
        if plan.annotation is not None:
            inputs.append((_constant(builder, node, cursor, plan.annotation), node, "annotation-code", 0, None))
        # The compound boundary takes default operands, including cleanup of
        # partially packed/unpublished attributes on RAISE. Decorator holds
        # remain outside it. Both actual post-worlds stay incomplete.
        cursor, function, identity = _invoke(builder, cursor, node, tuple(inputs), K.MAKE_FUNCTION_314,
                                            tuple(consumed), result=True)
        position = next(i for i, link in enumerate(builder.operation_links) if link.operation == identity)
        builder.operation_links[position] = replace(builder.operation_links[position], semantic_operation=declarations[0].id)
        _hold(builder, cursor, node, function, "function")
        for expression, decorator, index in reversed(decorators):
            cursor, function, _ = _invoke(builder, cursor, node,
                ((decorator, expression, "decorator", index, None),
                 (function, node, "decorated-function", 0, None)),
                K.APPLY_DECORATOR_314, ((expression, decorator), (node, function)), result=True)
            _hold(builder, cursor, node, function, "function")
        # STORE_NAME consumes its stack operand on both outcomes. Remove the
        # modeled pending hold before its invoke, never release it a second
        # time on the failing mapping-write arm.
        _transfer(builder, ((node, function),), node)
        cursor = builder.store_name(node, node.name, function, cursor)
        builder.gap(GapKind.EFFECT_SUMMARY, node,
            "function construction/default attributes, decorators and mapping name write retain ordered source/world; "
            "child/annotation bodies remain deferred shared definitions, with runtime fields/identity/effects unresolved")
        return cursor
    finally:
        if sinks is not None:
            if not sinks or sinks[-1] is not local_failure:
                raise ValueError("mapping function failure-sink stack changed")
            sinks.pop()
        del builder.active_temporaries[baseline:]


__all__ = ["MappingFunctionPlan", "mapping_function_plan", "lower_mapping_function"]
