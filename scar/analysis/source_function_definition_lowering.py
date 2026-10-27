"""Original nested function creation; child code is referenced, never executed."""
from __future__ import annotations

import ast
import dis
from dataclasses import replace
from types import CodeType

from scar.analysis.program_lowering import _Unsupported
from scar.analysis.source_call_lowering import _constant, _invoke
from scar.analysis.source_heap_lowering import expression_for_heap_target
from scar.analysis.source_mapping_lowering import _transfer
from scar.ir.program.environments import EnvironmentRole
from scar.ir.program.ids import OperationID, ValueID
from scar.ir.program.model import AccessMode, Behavior, ExitKind, Operation, OperationResult, StateAccess, StateVersionValue
from scar.ir.program.source import GapKind, SourceRole
from scar.ir.program.state_addresses import AddressEffect, CellContent, ReferenceOwner
from scar.ir.program.structured import PythonProtocolKind as K


def span(node):
    return node.lineno, node.end_lineno, node.col_offset, node.end_col_offset


def unsupported(node, detail):
    raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, node, 'NESTED_FUNCTION_' + detail)


def compiler_plan(node, code):
    """Exact original creation window; no compilation, target import or eval."""
    if not isinstance(node, ast.FunctionDef):
        unsupported(node, 'ASYNC_DEFINITION_UNIMPLEMENTED')
    if node.decorator_list:
        unsupported(node, 'DECORATOR_APPLICATION_UNIMPLEMENTED')
    if node.type_params:
        unsupported(node, 'TYPE_PARAMETER_SCOPE_UNIMPLEMENTED')
    if any(x is not None for x in node.args.kw_defaults):
        unsupported(node, 'KEYWORD_DEFAULTS_UNIMPLEMENTED')
    rows = tuple(dis.get_instructions(code))
    own = [r for r in rows if tuple(r.positions) == span(node)]
    children = [r for r in own if r.opname == 'LOAD_CONST' and type(r.argval) is CodeType
                and r.argval.co_name == node.name and r.argval.co_firstlineno == node.lineno
                and r.argval.co_qualname == code.co_qualname + '.<locals>.' + node.name]
    if len(children) != 1:
        unsupported(node, 'ORIGINAL_CHILD_CODE_OCCURRENCE_UNAVAILABLE')
    child = children[0]
    stores = [r for r in own if r.offset > child.offset and r.opname in ('STORE_FAST', 'STORE_DEREF', 'STORE_GLOBAL')
              and r.argval == node.name]
    if len(stores) != 1:
        unsupported(node, 'ORIGINAL_NAME_STORE_OCCURRENCE_UNAVAILABLE')
    stop = stores[0]
    own = [r for r in own if r.offset <= stop.offset]
    expected, stages = [], []
    def constant(row, role):
        expected.append(('LOAD_CONST', row.arg)); stages.append(('constant', role, row))
    defaults = None
    if node.args.defaults:
        candidates = [r for r in own if r.opname == 'LOAD_CONST' and type(r.argval) is tuple
                      and len(r.argval) == len(node.args.defaults)]
        exact = [r for r in candidates if all(isinstance(n, ast.Constant) and type(n.value) is type(v) and n.value == v
                                            for n, v in zip(node.args.defaults, r.argval))]
        if exact:
            if len(exact) != 1:
                unsupported(node, 'DEFAULT_TUPLE_CONSTANT_AMBIGUOUS')
            defaults = exact[0]; constant(defaults, 'defaults')
        else:
            expected.append(('BUILD_TUPLE', len(node.args.defaults)))
            stages.append(('tuple', 'defaults', tuple(node.args.defaults)))
    args = (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
    annotated = (node.returns is not None or any(a.annotation is not None for a in args)
                 or any(a is not None and a.annotation is not None for a in (node.args.vararg, node.args.kwarg)))
    annotation = None
    if annotated:
        annotations = [r for r in own if r.opname == 'LOAD_CONST' and type(r.argval) is CodeType
                       and r.argval.co_name == '__annotate__' and r.offset < child.offset
                       and r.argval.co_firstlineno == node.lineno]
        if len(annotations) != 1:
            unsupported(node, 'DEFERRED_ANNOTATION_CODE_UNAVAILABLE')
        annotation = annotations[0]
    def function(load, role):
        names = tuple(load.argval.co_freevars)
        if names:
            expected.extend(('LOAD_FAST_BORROW', name) for name in names)
            expected.append(('BUILD_TUPLE', len(names)))
            stages.append(('tuple', role + '-closure', names))
        constant(load, role + '-code')
        expected.append(('MAKE_FUNCTION', None)); stages.append(('make', role, None))
        if names:
            expected.append(('SET_FUNCTION_ATTRIBUTE', 8)); stages.append(('set', role + '-closure', None))
    if annotation is not None:
        function(annotation, 'annotation')
    function(child, 'function')
    if annotation is not None:
        expected.append(('SET_FUNCTION_ATTRIBUTE', 16)); stages.append(('set', 'annotation', None))
    if node.args.defaults:
        expected.append(('SET_FUNCTION_ATTRIBUTE', 1)); stages.append(('set', 'defaults', None))
    expected.append((stop.opname, node.name)); stages.append(('bind', stop.opname, None))
    def matches(row, token):
        name, arg = token
        return row.opname == name and (row.argval == arg if name.startswith(('LOAD_FAST', 'STORE_')) else row.arg == arg)
    if len(own) != len(expected) or not all(matches(r, t) for r, t in zip(own, expected)):
        unsupported(node, 'EXACT_COMPILER_CREATION_SEQUENCE_UNAVAILABLE')
    return tuple(stages), child, annotation


def _hold(builder, cursor, node, reference, role):
    builder.frame_transition(cursor, node, ((reference, node, 'function-held-' + role),), K.FRAME_HOLD_TEMPORARY)
    builder.active_temporaries.append(reference)


def _code_reference(builder, node, cursor, instruction, role):
    value = _constant(builder, node, cursor, instruction)
    identity = builder.values_by_id[value].origin.operation
    old = builder.operation_records[identity]
    marked = replace(old, label='original function ' + role + ' reference')
    builder.operations[builder.operations.index(old)] = marked
    builder.operation_records[identity] = marked
    return value


def lower_function_definition(builder, node, cursor):
    evidence = builder.language_options.code_evidence
    if evidence is None or evidence.store.document['runtime']['version'][:3] != [3, 14, 7]:
        unsupported(node, 'READONLY_CPYTHON_3147_CODE_REQUIRED')
    evidence.require_definition(builder.snapshot, builder.function_definition.id, builder.source(builder.functions[builder.entry]))
    stages, child, annotation = compiler_plan(node, evidence.code)
    baseline = len(builder.active_temporaries)
    try:
        # Defaults are real source operations. Code/creation staging is the
        # contract for one semantic interface, not a repeated child-body graph.
        default_constant = next((row for action, role, row in stages if action == 'constant' and role == 'defaults'), None)
        defaults = []
        if default_constant is None:
            for index, source in enumerate(node.args.defaults):
                cursor, value = expression_for_heap_target(builder, source, cursor)
                if cursor is None:
                    return None
                _hold(builder, cursor, source, value, 'default')
                defaults.append((value, source, 'function-default', index, None))
        else:
            value = _code_reference(builder, node, cursor, default_constant, 'defaults')
            defaults.append((value, node, 'function-defaults-tuple', 0, None))
        main_code = _code_reference(builder, node, cursor, child, 'code')
        inputs = [(main_code, node, 'function-code', 0, None),
                  (builder.environment_references[EnvironmentRole.GLOBALS_NAMESPACE], node, 'function-globals', 0, None)]
        inputs.extend(defaults)
        for role, load in (('function', child), ('annotation', annotation)):
            if load is None:
                continue
            if role == 'annotation':
                inputs.append((_code_reference(builder, node, cursor, load, 'annotation code'), node, 'annotation-code', 0, None))
            for index, name in enumerate(load.argval.co_freevars):
                if name not in builder.cell_references:
                    unsupported(node, 'CAPTURE_HAS_NO_ACTUAL_PARENT_CELL')
                inputs.append((builder.cell_references[name], node, role + '-closure-cell', index, None))
        consumed = tuple((source, value) for value, source, _, _, _ in defaults) if default_constant is None else ()
        # The boundary owns construction, attribute initialization and unwinding
        # of its unpublished temporaries. Closure cells/globals are borrowed
        # identities, never eager cell-content reads. Both post-worlds remain
        # incomplete; no runtime callable/code identity or purity is granted.
        cursor, function, identity = _invoke(builder, cursor, node, tuple(inputs),
            K.MAKE_NESTED_FUNCTION, consumed, result=True)
        old = builder.operation_records[identity]
        marked = replace(old, label='create function ' + node.name)
        builder.operations[builder.operations.index(old)] = marked
        builder.operation_records[identity] = marked
        declarations = [d for d in builder.by_atom.get(builder.source(node).atom_id.wire, ())
                        if d.metadata.get('phase') == 'definition_time']
        if len(declarations) != 1:
            unsupported(node, 'ORIGINAL_DEFINITION_TIME_DECLARATION_UNAVAILABLE')
        i = next(i for i, link in enumerate(builder.operation_links) if link.operation == identity)
        builder.operation_links[i] = replace(builder.operation_links[i], semantic_operation=declarations[0].id)
        _hold(builder, cursor, node, function, 'function')
        store = stages[-1][1]
        if store == 'STORE_FAST' and node.name in builder.locals:
            builder.frame_transition(cursor, node, ((cursor.env[node.name], node, 'previous-binding'),
                (function, node, 'assigned-reference')), K.FRAME_BIND)
            builder.define_binding(node.name, cursor, node, function)
            _transfer(builder, ((node, function),), node)
        elif store == 'STORE_DEREF' and node.name in builder.cell_references:
            cursor, _, identity = _invoke(builder, cursor, node,
                ((builder.cell_references[node.name], node, 'definition-cell', 0, None),
                 (function, node, 'defined-function', 0, None)),
                K.STORE_NESTED_FUNCTION_CELL, ((node, function),), raise_consumed=())
            operation = builder.operation_records[identity]
            builder._addresses(identity, (AddressEffect(ReferenceOwner(operation.uses[0].id), (CellContent(),), AccessMode.WRITE),))
        else:
            unsupported(node, 'NAME_BINDING_INTERFACE_UNIMPLEMENTED')
        builder.gap(GapKind.CODE_VERSION, node, 'nested function creation references original code; runtime function/code instance identity remains unproved')
        builder.gap(GapKind.EFFECT_SUMMARY, node, 'definition-time construction and ordered captures are connected; saved builtins resolution, finalizers and runtime annotation/call effects remain unproved')
        return cursor
    finally:
        del builder.active_temporaries[baseline:]
