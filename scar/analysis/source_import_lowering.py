"""Function import interfaces over original source, environment and world.

Import machinery remains a stateful language boundary, not an executed import
or an invented module/locals object. The active frame's runtime f_locals view
is within this boundary's coarse world; it is never replaced by literal None.
"""
from __future__ import annotations

import ast
import dis
from collections import defaultdict

from scar.analysis.program_lowering import _Unsupported, _REF
from scar.analysis.source_language import function_exception_types, require_source_tree, supports_cpython_compiler
from scar.ir.program.environments import EnvironmentRole as E
from scar.ir.program.model import (AccessMode, CompletionResult, ExitKind, LiteralOrigin,
    OperationResult, ReferenceValue, StateVersionValue, TerminatorKind, value_type)
from scar.ir.program.source import GapKind
from scar.ir.program.source_language import SourceLanguageCapability as C, FUNCTION_IMPORT_PROTOCOLS
from scar.ir.program.state_addresses import (AddressCoverage, AddressEffect, InvokeStateOperand,
    NamespaceKey, ReferenceOwner)
from scar.ir.program.structured import PythonProtocolKind as K


def _span(node):
    return node.lineno, node.end_lineno, node.col_offset, node.end_col_offset


def compiler_import(node, code):
    """Recognize the exact original import operands and ordered local stores."""
    if not isinstance(node, (ast.Import, ast.ImportFrom)) or any(a.name == '*' for a in node.names):
        raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, node, 'FUNCTION_IMPORT_STAR_BINDING_UNIMPLEMENTED')
    if isinstance(node, ast.Import) and any('.' in a.name and a.asname for a in node.names):
        raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, node, 'FUNCTION_IMPORT_DOTTED_ALIAS_TRAVERSAL_UNIMPLEMENTED')
    names = tuple(a.asname or (a.name.split('.')[0] if isinstance(node, ast.Import) else a.name) for a in node.names)
    rows = tuple(r for r in dis.get_instructions(code) if tuple(r.positions) == _span(node))
    relevant = tuple((r.opname, r.argval) for r in rows if r.opname.startswith('IMPORT_') or r.opname.startswith('STORE_'))
    expected = []
    for alias, name in zip(node.names, names):
        if isinstance(node, ast.Import): expected.append(('IMPORT_NAME', alias.name))
        elif not expected: expected.append(('IMPORT_NAME', node.module or ''))
        if isinstance(node, ast.ImportFrom): expected.append(('IMPORT_FROM', alias.name))
        expected.append(('STORE_FAST', name))
    if relevant != tuple(expected):
        raise _Unsupported(GapKind.CODE_VERSION, node, 'FUNCTION_IMPORT_EXACT_LOCAL_COMPILER_SEQUENCE_UNAVAILABLE')
    return names


def lower_import(builder, node, cursor):
    evidence = builder.language_options.code_evidence
    if not supports_cpython_compiler(evidence):
        raise _Unsupported(GapKind.CODE_VERSION, node, 'FUNCTION_IMPORT_READONLY_3147_CODE_REQUIRED')
    names = compiler_import(node, evidence.code)
    if any(name not in builder.locals or name in builder.cell_references for name in names):
        raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, node, 'FUNCTION_IMPORT_NONFAST_BINDING_UNIMPLEMENTED')
    from scar.analysis.source_slice_lowering import _constant
    baseline = len(builder.active_temporaries)

    def hold(value):
        builder.frame_transition(cursor, node, ((value, node, 'import-held-reference'),), K.FRAME_HOLD_TEMPORARY)
        builder.active_temporaries.append(value)

    def release(value):
        assert builder.active_temporaries[-1] == value
        builder.active_temporaries.pop()
        builder.frame_transition(cursor, node, ((value, node, 'import-stack-reference'),), K.FRAME_RELEASE_TEMPORARY)

    def bind(name, value):
        builder.frame_transition(cursor, node, ((cursor.env[name], node, 'previous-binding'),
            (value, node, 'assigned-reference')), K.FRAME_BIND)
        builder.define_binding(name, cursor, node, value)

    try:
        for ordinal, alias in enumerate(node.names if isinstance(node, ast.Import) else (None,)):
            requested = builder.literal(node, alias.name if alias else node.module or '')
            level = builder.literal(node, 0 if alias else node.level)
            if alias: fromlist = builder.literal(node, None)
            else: cursor, fromlist = _constant(builder, node, cursor)
            key = builder.literal(node, '__import__')
            inputs = (builder.environment_references[E.GLOBALS_NAMESPACE],
                builder.environment_references[E.BUILTINS_NAMESPACE], requested, level, fromlist, key)
            cursor, imported, identity = builder.invoke(cursor, node,
                tuple((v, node, 'function-import-input', i, None) for i, v in enumerate(inputs)))
            builder.protocol(identity, K.FUNCTION_IMPORT_NAME, node)
            op = builder.operation_records[identity]
            builder._addresses(identity, (AddressEffect(ReferenceOwner(op.uses[1].id),
                (NamespaceKey(op.uses[5].id),), AccessMode.READ),))
            hold(imported)
            if alias:
                bind(names[ordinal], imported)
            else:
                for member, name in zip(node.names, names):
                    key = builder.literal(node, member.name)
                    cursor, value, identity = builder.invoke(cursor, node,
                        ((imported, node, 'from-owner', 0, None), (key, node, 'from-key', 0, None)))
                    builder.protocol(identity, K.FUNCTION_IMPORT_FROM, node)
                    hold(value); bind(name, value); release(value)
            release(imported)
        builder.gap(GapKind.EFFECT_SUMMARY, node,
            'import uses saved builtins/globals and active function-frame locals under the coarse world; '
            'importer dispatch, module registry/content, f_locals view, frame interposition and finalizers remain unproved')
        return cursor
    finally:
        del builder.active_temporaries[baseline:]


def validate_imports(model, graph, interface, metadata, semantic, language,
                     *, source_tree=None, options=None, structural_only=False):
    def need(ok, detail):
        if not ok: raise ValueError('function import: ' + detail)
    selected = [r for r in model.protocols if r.kind.value in FUNCTION_IMPORT_PROTOCOLS]
    if not selected: return set()
    need(C.FUNCTION_IMPORT_314_V1 in language.capabilities and isinstance(source_tree, ast.Module),
        'explicit capability and original source AST required')
    operations = {r.id: r for r in graph.operations}; values = {r.id: r for r in graph.values}
    blocks = {r.id: r for region in graph.regions for r in region.blocks}
    links = {r.operation: r for r in metadata.operation_links}
    use_links = {(r.operation, r.use): r for r in metadata.use_links}
    environment, = graph.environments
    refs = {r.role: r.reference for r in environment.members}
    world = value_type(values[interface.world])
    constants = {r.operation: r for r in language.constants}
    addresses = {r.site.operation: r for r in graph.state_address_refinements}
    all_uses = {u.id: u for op in graph.operations for u in op.uses}
    bindings_by_payload = defaultdict(list)
    for row in graph.binding_definitions:
        if row.payload is not None: bindings_by_payload[all_uses[row.payload].value].append(row)
    groups = defaultdict(list)
    for protocol in selected: groups[protocol.source].append(protocol)

    def literal(use, expected):
        origin = values[use.value].origin
        need(type(origin) is LiteralOrigin and type(origin.value) is type(expected) and origin.value == expected,
            'original import literal/ordinal differs')

    for source, protocols in groups.items():
        nodes = [n for n in require_source_tree(source_tree, language.source, source) if isinstance(n, (ast.Import, ast.ImportFrom))]
        need(len(nodes) == 1, 'exact original import statement required'); node, = nodes
        if not structural_only:
            need(options is not None and options.code_evidence is not None, 'independent compiler witness required')
            names = compiler_import(node, options.code_evidence.code)
        else: names = tuple(a.asname or (a.name.split('.')[0] if isinstance(node, ast.Import) else a.name) for a in node.names)
        expected = ([(K.FUNCTION_IMPORT_NAME, a.name, name) for a, name in zip(node.names, names)]
            if isinstance(node, ast.Import) else [(K.FUNCTION_IMPORT_NAME, node.module or '', None)] +
            [(K.FUNCTION_IMPORT_FROM, a.name, name) for a, name in zip(node.names, names)])
        need([p.kind for p in protocols] == [kind for kind, _, _ in expected], 'import/from interfaces lost source order')
        imported = None
        for protocol, (kind, name, bound_name) in zip(protocols, expected):
            op = operations[protocol.operation]; uses = op.uses
            need(links[op.id].source == source and links[op.id].semantic_operation is None
                 and op.callee is None and op.terminator is not None and op.terminator.kind is TerminatorKind.INVOKE
                 and not op.effects_complete and tuple(u.id for u in uses) == op.invoke_arguments
                 and all(type(values[u.value]) is ReferenceValue for u in uses[:-1])
                 and type(values[uses[-1].value]) is StateVersionValue,
                 'import must remain its original incomplete reference/world invoke')
            need(tuple((s.kind, s.types) for s in op.completions) ==
                 ((ExitKind.NORMAL, (_REF, world)), (ExitKind.RAISE, function_exception_types(language, _REF, world)))
                 and tuple(e.kind for e in op.terminator.successors) == (ExitKind.NORMAL, ExitKind.RAISE)
                 and all(e.arguments == tuple(CompletionResult(i) for i in range(len(s.types)))
                         for e, s in zip(op.terminator.successors, op.completions)),
                 'import lost NORMAL/RAISE payloads or original post-worlds')
            normal = op.terminator.successors[0]; result = blocks[normal.block].arguments[0]
            if kind is K.FUNCTION_IMPORT_NAME:
                need(len(uses) == 7 and (uses[0].value, uses[1].value) ==
                    (refs[E.GLOBALS_NAMESPACE], refs[E.BUILTINS_NAMESPACE]), 'saved globals/builtins changed')
                literal(uses[2], name); literal(uses[3], node.level if isinstance(node, ast.ImportFrom) else 0)
                literal(uses[5], '__import__')
                if isinstance(node, ast.Import): literal(uses[4], None)
                else:
                    origin = values[uses[4].value].origin
                    need(type(origin) is OperationResult and origin.operation in constants
                        and constants[origin.operation].source == source, 'fromlist is not its original code constant')
                    if not structural_only:
                        path = constants[origin.operation].constant_path
                        need(len(path) == 1 and options.code_evidence.code.co_consts[path[0]] == tuple(a.name for a in node.names),
                             'import fromlist differs from original names')
                row = addresses.get(op.id)
                need(row is not None and row.site == InvokeStateOperand(op.id, uses[-1].id)
                    and row.coverage is AddressCoverage.PARTIAL and row.protocol is None
                    and row.effects == (AddressEffect(ReferenceOwner(uses[1].id), (NamespaceKey(uses[5].id),), AccessMode.READ),),
                    'saved builtins import lookup must retain its partial attempted address')
                imported = result
            else:
                need(len(uses) == 3 and uses[0].value == imported, 'IMPORT_FROM changed its actual imported owner')
                literal(uses[1], name)
            for i, use in enumerate(uses[:-1]):
                row = use_links[(op.id, use.id)]
                need(row.source == source and row.role == ('function-import-input' if kind is K.FUNCTION_IMPORT_NAME
                    else 'from-owner' if i == 0 else 'from-key') and row.index == (i if kind is K.FUNCTION_IMPORT_NAME else 0),
                    'import input source/Use order differs')
            if bound_name is not None:
                bindings = bindings_by_payload[result]
                need(len(bindings) == 1 and semantic.slots[values[bindings[0].value].slot].name == bound_name
                    and semantic.slots[values[bindings[0].value].slot].owner == interface.definition
                    and links[values[bindings[0].value].origin.operation].source == source,
                    'normal imported reference has no exact original local binding')
    return {p.operation for p in selected}
