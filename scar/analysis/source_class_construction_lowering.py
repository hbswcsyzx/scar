"""ClassDef construction in the original parent frame, without target execution.

This profile expands the compiler-known parent protocol. The called builder
remains an actual builtin-namespace read; the shared suite is code provenance,
not an unconditional body execution or a replacement for the class result.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, replace
import dis
from types import CodeType

from scar.analysis.program_lowering import _Unsupported
from scar.analysis.source_call_lowering import _constant, _invoke
from scar.analysis.source_mapping_lowering import _transfer
from scar.analysis.source_language import supports_cpython_compiler
from scar.ir.program.class_construction import (ClassConstruction, ClassDecoratorApplication,
    ImplicitCallArgument, ImplicitCallPorts)
from scar.ir.program.environments import EnvironmentRole
from scar.ir.program.functions import ArgumentKind
from scar.ir.program.model import AccessMode, ExitKind
from scar.ir.program.source import GapKind
from scar.ir.program.state_addresses import AddressEffect, CellContent, NamespaceKey, ReferenceOwner
from scar.ir.program.structured import PythonProtocolKind as K
from scar.ir.v2.semantic import OperationKind
from scar.trace.code_snapshot import code_key


def _span(node):
    return node.lineno, node.end_lineno, node.col_offset, node.end_col_offset


def _unsupported(node, detail):
    raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, node, 'CLASS_CONSTRUCTION_' + detail)


@dataclass(frozen=True, slots=True)
class ClassConstructionPlan:
    lookup: dis.Instruction
    child: dis.Instruction
    name: dis.Instruction
    build: dis.Instruction
    store: dis.Instruction
    closure: tuple[str, ...]
    keyword_names: dis.Instruction | None
    decorator_calls: tuple[dis.Instruction, ...]


def class_construction_plan(node, parent_code):
    """Match the original direct compiler window; never synthesize ast.Call."""
    if type(node) is not ast.ClassDef or type(parent_code) is not CodeType:
        _unsupported(node, 'ORIGINAL_CLASS_AND_PARENT_CODE_REQUIRED')
    if node.type_params or any(isinstance(base, ast.Starred) for base in node.bases) or any(
            keyword.arg is None for keyword in node.keywords):
        _unsupported(node, 'TYPE_PARAMETER_OR_EXPANDED_HEADER_UNIMPLEMENTED')
    instructions = tuple(i for i in dis.get_instructions(parent_code, adaptive=False, show_caches=False)
                         if i.opname != 'EXTENDED_ARG')
    own = [i for i in instructions if tuple(i.positions) == _span(node)]
    lookups = [i for i in own if i.opname == 'LOAD_BUILD_CLASS']
    children = [i for i in own if i.opname == 'LOAD_CONST' and type(i.argval) is CodeType
                and i.argval.co_name == node.name]
    if len(lookups) != 1 or len(children) != 1:
        _unsupported(node, 'EXACT_BUILDER_LOOKUP_AND_CHILD_CODE_REQUIRED')
    lookup, child = lookups[0], children[0]
    stores = [i for i in own if i.offset > child.offset and i.opname in (
        'STORE_NAME', 'STORE_FAST', 'STORE_DEREF', 'STORE_GLOBAL') and i.argval == node.name]
    if len(stores) != 1:
        _unsupported(node, 'EXACT_FRAME_BINDING_REQUIRED')
    store = stores[0]
    own = [i for i in own if lookup.offset <= i.offset <= store.offset]
    makes = [i for i in own if i.opname == 'MAKE_FUNCTION']
    names = [i for i in own if i.opname == 'LOAD_CONST' and type(i.argval) is str and i.argval == node.name]
    builds = [i for i in own if i.opname in ('CALL', 'CALL_KW')]
    if len(makes) != 1 or len(names) != 1 or len(builds) != 1:
        _unsupported(node, 'EXACT_FACTORY_NAME_AND_BUILDER_CALL_REQUIRED')
    build, name = builds[0], names[0]
    if build.arg != 2 + len(node.bases) + len(node.keywords):
        _unsupported(node, 'COMPILER_BUILDER_ARITY_DIFFERS')
    keyword_names = None
    if node.keywords:
        tables = [i for i in own if i.opname == 'LOAD_CONST' and type(i.argval) is tuple
                  and i.argval == tuple(k.arg for k in node.keywords) and name.offset < i.offset < build.offset]
        if build.opname != 'CALL_KW' or len(tables) != 1:
            _unsupported(node, 'COMPILER_KEYWORD_TABLE_DIFFERS')
        keyword_names = tables[0]
    elif build.opname != 'CALL':
        _unsupported(node, 'COMPILER_POSITIONAL_CALL_DIFFERS')
    closure = tuple(child.argval.co_freevars)
    expected = [('LOAD_BUILD_CLASS', None), ('PUSH_NULL', None)]
    if closure:
        expected.extend(('LOAD_FAST_BORROW', n) for n in closure)
        expected.append(('BUILD_TUPLE', len(closure)))
    expected.extend((('LOAD_CONST', child.arg), ('MAKE_FUNCTION', None)))
    if closure: expected.append(('SET_FUNCTION_ATTRIBUTE', 8))
    expected.append(('LOAD_CONST', name.arg))
    # Header expression instructions have their own source positions; the
    # remaining class-positioned instructions are precisely keyword/call/store.
    if keyword_names is not None: expected.append(('LOAD_CONST', keyword_names.arg))
    expected.extend(((build.opname, build.arg), (store.opname, node.name)))
    def matches(row, token):
        op, arg = token
        return row.opname == op and (arg is None or (row.argval == arg if op in (
            'LOAD_FAST_BORROW', 'STORE_NAME', 'STORE_FAST', 'STORE_DEREF', 'STORE_GLOBAL') else row.arg == arg))
    if len(own) != len(expected) or not all(matches(i, e) for i, e in zip(own, expected)):
        _unsupported(node, 'EXACT_PARENT_COMPILER_SEQUENCE_UNAVAILABLE')
    applications = [i for i in instructions if build.offset < i.offset < store.offset
                    and i.opname in ('CALL', 'CALL_KW', 'CALL_FUNCTION_EX')]
    if (len(applications) != len(node.decorator_list) or any(i.opname != 'CALL' or i.arg != 0
            or tuple(i.positions) != _span(d) for i, d in zip(applications, reversed(node.decorator_list)))):
        _unsupported(node, 'EXACT_DECORATOR_APPLICATION_SEQUENCE_UNAVAILABLE')
    return ClassConstructionPlan(lookup, child, name, build, store, closure, keyword_names, tuple(applications))


def _hold(builder, cursor, node, reference):
    builder.frame_transition(cursor, node, ((reference, node, 'class-held-reference'),), K.FRAME_HOLD_TEMPORARY)
    builder.active_temporaries.append(reference)


def _ports(builder, identity, arguments, *, keyword_names=False):
    operation = builder.operation_records[identity]
    normal, raised = operation.terminator.successors
    normal_args = builder.block_arguments[normal.block]
    raised_args = builder.block_arguments[raised.block]
    actuals = tuple(ImplicitCallArgument(operation.uses[index + 1].id, builder.source(node), kind,
        index, keyword) for index, (node, kind, keyword) in enumerate(arguments))
    return ImplicitCallPorts(identity, operation.uses[0].id, actuals, operation.uses[-1].id,
        normal.block, normal_args[0], normal_args[-1], raised.block, *raised_args,
        keyword_names=operation.uses[-2].id if keyword_names else None)


def lower_class_construction(builder, node, cursor):
    evidence = builder.language_options.code_evidence
    if not supports_cpython_compiler(evidence) or not hasattr(evidence, 'to_reference'):
        _unsupported(node, 'STATIC_CPYTHON_3147_PARENT_REQUIRED')
    plan = class_construction_plan(node, evidence.code)
    source = builder.source(node)
    definitions = [d for d in builder.by_atom.get(source.atom_id.wire, ())
                   if d.kind is OperationKind.OPAQUE and d.label == 'class ' + node.name and d.output_slots]
    if len(definitions) != 1:
        _unsupported(node, 'ORIGINAL_CLASS_DEFINITION_REQUIRED')
    definition = definitions[0].id
    suite = replace(evidence.to_reference(), source=source, definition=definition,
        code_path=evidence.code_path + (plan.child.arg,), code_layout_key=code_key(plan.child.argval))
    module = hasattr(builder, 'entry_references')
    globals_reference = (builder.entry_references[1] if module else
        builder.environment_references[EnvironmentRole.GLOBALS_NAMESPACE])
    builtins_reference = (builder.entry_references[2] if module else
        builder.environment_references[EnvironmentRole.BUILTINS_NAMESPACE])
    closure_references = getattr(builder, 'cell_references', {})
    if any(name not in closure_references for name in plan.closure):
        _unsupported(node, 'ORIGINAL_PARENT_CLOSURE_CELL_UNAVAILABLE')
    baseline, first, entry = len(builder.active_temporaries), len(builder.operations), cursor.block
    # A local failure sink releases only this helper's still-owned references,
    # then forwards the same pair and post-release world to its enclosing one.
    sinks = getattr(builder, 'failure_sinks', None)
    def failed(failure, payload):
        saved = tuple(builder.active_temporaries)
        try:
            for value in reversed(builder.active_temporaries[baseline:]):
                builder.frame_transition(failure, node, ((value, node, 'mapping-function-exception-unwind' if module else 'function-exception-unwind'),), K.FRAME_RELEASE_TEMPORARY)
            del builder.active_temporaries[baseline:]
            if not sinks or sinks[-1] is not failed:
                raise ValueError('class construction failure ownership changed')
            sinks.pop()
            try: return builder.finish_exit(failure, node, payload, ExitKind.RAISE)
            finally: sinks.append(failed)
        finally: builder.active_temporaries[:] = saved
    if sinks is not None: sinks.append(failed)
    try:
        decorators = []
        for index, expression in enumerate(node.decorator_list):
            cursor, value = builder.expr(expression, cursor)
            if cursor is None: return None
            _hold(builder, cursor, expression, value); decorators.append((index, expression, value))
        key = builder.literal(node, '__build_class__')
        cursor, selected, lookup = _invoke(builder, cursor, node,
            ((builtins_reference, node, 'class-builder-owner', 0, None), (key, node, 'class-builder-key', 0, None)),
            K.LOAD_BUILD_CLASS_314, result=True)
        operation = builder.operation_records[lookup]
        builder._addresses(lookup, (AddressEffect(ReferenceOwner(operation.uses[0].id),
            (NamespaceKey(operation.uses[1].id),), AccessMode.READ),))
        _hold(builder, cursor, node, selected)
        code = _constant(builder, node, cursor, plan.child); _hold(builder, cursor, node, code)
        factory_inputs = ((code, node, 'class-body-code', 0, None),
            (globals_reference, node, 'class-body-globals', 0, None)) + tuple(
            (closure_references[name], node, 'class-body-closure-cell', index, None)
            for index, name in enumerate(plan.closure))
        cursor, function, factory = _invoke(builder, cursor, node, factory_inputs, K.MAKE_CLASS_BODY_314,
            ((node, code),), result=True)
        factory_operation = builder.operation_records[factory]
        _hold(builder, cursor, node, function)
        name = _constant(builder, node, cursor, plan.name); _hold(builder, cursor, node, name)
        inputs = [(selected, node, 'callee', 0, None), (function, node, 'argument', 0, None),
                  (name, node, 'argument', 1, None)]
        arguments = [(node, ArgumentKind.POSITIONAL, None), (node, ArgumentKind.POSITIONAL, None)]
        consumed = [(node, selected), (node, function), (node, name)]
        for index, expression in enumerate(node.bases):
            cursor, value = builder.expr(expression, cursor)
            if cursor is None: return None
            _hold(builder, cursor, expression, value)
            inputs.append((value, expression, 'argument', index + 2, None))
            arguments.append((expression, ArgumentKind.POSITIONAL, None)); consumed.append((expression, value))
        for index, keyword in enumerate(node.keywords):
            cursor, value = builder.expr(keyword.value, cursor)
            if cursor is None: return None
            _hold(builder, cursor, keyword.value, value)
            inputs.append((value, keyword.value, 'keyword:' + keyword.arg, index, None))
            arguments.append((keyword.value, ArgumentKind.KEYWORD, keyword.arg)); consumed.append((keyword.value, value))
        if plan.keyword_names is not None:
            table = _constant(builder, node, cursor, plan.keyword_names); _hold(builder, cursor, node, table)
            inputs.append((table, node, 'class-keyword-names', 0, None)); consumed.append((node, table))
        cursor, result, call = _invoke(builder, cursor, node, tuple(inputs), K.BUILD_CLASS_CALL_314,
            tuple(consumed), result=True)
        from scar.analysis.source_heap_lowering import _associate
        from scar.ir.semantics_v2 import Opcode
        _associate(builder, call, node, definitions[0], Opcode.OPAQUE)
        call_ports = _ports(builder, call, arguments, keyword_names=plan.keyword_names is not None)
        _hold(builder, cursor, node, result)
        applications = []
        for index, expression, decorator in reversed(decorators):
            cursor, result, identity = _invoke(builder, cursor, expression,
                ((decorator, expression, 'callee', 0, None), (result, node, 'argument', 0, None)),
                K.APPLY_CLASS_DECORATOR_314, ((expression, decorator), (node, result)), result=True)
            applications.append(ClassDecoratorApplication(index, builder.source(expression),
                _ports(builder, identity, ((node, ArgumentKind.POSITIONAL, None),))))
            _hold(builder, cursor, node, result)
        if plan.store.opname == 'STORE_NAME' and module:
            _transfer(builder, ((node, result),), node)
            before = len(builder.operations); cursor = builder.store_name(node, node.name, result, cursor)
            binding = next(op for op in builder.operations[before:] if any(
                row.operation == op.id and row.kind.value == 'STORE_NAME_314' for row in builder.protocols)).id
            binding_use = builder.operation_records[binding].uses[2].id
        elif plan.store.opname == 'STORE_FAST' and node.name in builder.locals:
            before = len(builder.operations)
            builder.frame_transition(cursor, node, ((cursor.env[node.name], node, 'previous-binding'),
                (result, node, 'assigned-reference')), K.FRAME_BIND)
            binding = builder.operations[before].id; binding_use = builder.operation_records[binding].uses[1].id
            builder.define_binding(node.name, cursor, node, result)
            _transfer(builder, ((node, result),), node)
        elif plan.store.opname in ('STORE_DEREF', 'STORE_GLOBAL'):
            cell = plan.store.opname == 'STORE_DEREF'
            if cell and node.name not in closure_references: _unsupported(node, 'BINDING_CELL_UNAVAILABLE')
            inputs = (((closure_references[node.name], node, 'class-binding-owner', 0, None),) if cell else
                ((globals_reference, node, 'class-binding-owner', 0, None),
                 (builder.literal(node, node.name), node, 'class-binding-key', 0, None)))
            cursor, _, binding = _invoke(builder, cursor, node,
                inputs + ((result, node, 'assigned-reference', 0, None),),
                K.STORE_CLASS_CELL_314 if cell else K.STORE_CLASS_GLOBAL_314,
                ((node, result),), raise_consumed=() if cell else None)
            operation = builder.operation_records[binding]; binding_use = operation.uses[-2].id
            path = (CellContent(),) if cell else (NamespaceKey(operation.uses[1].id),)
            builder._addresses(binding, (AddressEffect(ReferenceOwner(operation.uses[0].id), path, AccessMode.WRITE),))
        else: _unsupported(node, 'COMPILER_BINDING_PROFILE_MISMATCH')
        record = ClassConstruction(definition, source, builder.function_context, entry, cursor.block, suite,
            lookup, factory, factory_operation.uses[0].id, factory_operation.uses[1].id,
            tuple(u.id for u in factory_operation.uses[2:-1]), function, call_ports, tuple(applications),
            binding, binding_use, plan.store.opname, result, tuple(op.id for op in builder.operations[first:]))
        builder.class_constructions.append(record)
        builder.gap(GapKind.EFFECT_SUMMARY, node,
            'parent class construction ports are connected; selected builder, prepared namespace, shared-suite execution, '
            'metaclass/hooks/classcell and complete effects remain explicit obligations')
        return cursor
    finally:
        if sinks is not None:
            if not sinks or sinks[-1] is not failed: raise ValueError('class failure sink stack changed')
            sinks.pop()
        del builder.active_temporaries[baseline:]
