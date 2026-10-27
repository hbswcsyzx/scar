"""Ordered set displays as one stateful allocation/hash/equality interface.

The primitive consumes held element references on both completions; hashing,
equality, partial-set cleanup and finalizers are inside its post-world. It
does not invent ordered set contents, purity, an observed object or aliases.
CPython 3.14 reference contract: Python/bytecodes.c BUILD_SET consumes all
inputs on allocation/add failure as well as success (unlike BUILD_LIST).
https://github.com/python/cpython/blob/v3.14.0/Python/bytecodes.c#L1854-L1878
"""
from __future__ import annotations

import ast

from scar.analysis.program_lowering import _Unsupported, _REF
from scar.analysis.source_heap_lowering import _source_definition, _associate, _hold, expression_for_heap_target
from scar.analysis.source_slice_lowering import _invoke
from scar.analysis.source_language import require_source_tree, function_exception_types
from scar.ir.program.model import (Behavior, CompletionResult, ExitKind, ReferenceValue,
    StateVersionValue, TerminatorKind, value_type)
from scar.ir.program.source import GapKind, SourceRole
from scar.ir.program.source_language import SourceLanguageCapability as C
from scar.ir.program.structured import PythonProtocolKind as K
from scar.ir.semantics_v2 import Opcode
from scar.ir.v2.semantic import OperationKind


def _shape(node):
    return (isinstance(node, ast.Set) and 0 < len(node.elts) <= 30
            and not any(isinstance(n, ast.Starred) for n in node.elts))


def _span(node):
    return node.lineno, node.end_lineno, node.col_offset, node.end_col_offset


def lower_set_display(builder, node, cursor):
    if not _shape(node):
        raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, node,
                           'SET_DISPLAY_STARRED_OR_INCREMENTAL_CONSTRUCTION_UNIMPLEMENTED')
    if builder.language_options.code_evidence is None:
        raise _Unsupported(GapKind.CODE_VERSION, node, 'SET_DISPLAY_READONLY_CODE_WITNESS_REQUIRED')
    definition = _source_definition(builder, node)
    if (definition.kind is not OperationKind.OPERATOR or definition.metadata.get('ast_type') != 'Set'
            or len(definition.output_slots) != 1):
        raise _Unsupported(GapKind.SOURCE_MAPPING, node, 'set display requires its exact original SG output')
    baseline = len(builder.active_temporaries)
    held, inputs = [], []
    try:
        for index, child in enumerate(node.elts):
            cursor, value = expression_for_heap_target(builder, child, cursor)
            if cursor is None:
                return None, None
            _hold(builder, cursor, child, value)
            held.append((child, value)); inputs.append((value, child, 'element', index, None))
        cursor, result, identity = _invoke(builder, cursor, node, inputs, tuple(held),
                                           kind=K.BUILD_SET_DISPLAY, memory=True)
        _associate(builder, identity, node, definition, Opcode.BUILD_SET)
        builder.link_value(builder.values_by_id[result], node, SourceRole.EXPRESSION)
        builder.gap(GapKind.EFFECT_SUMMARY, node,
            'set element evaluation order and construction are connected; allocation/hash/equality, '
            'deduplication, mutation, finalizers, identity and runtime contents remain inside the incomplete world interface')
        return cursor, result
    finally:
        del builder.active_temporaries[baseline:]


def validate_set_displays(model, graph, interface, metadata, semantic, language, *,
                          source_tree=None, options=None, structural_only=False):
    selected = {p.operation: p for p in model.protocols if p.kind is K.BUILD_SET_DISPLAY}
    if not selected:
        return set()
    def need(condition, detail):
        if not condition: raise ValueError('set display: ' + detail)
    need(C.SET_DISPLAY_314_V1 in language.capabilities, 'explicit capability required')
    need(isinstance(source_tree, ast.Module), 'exact retained AST required even for STRUCTURE')
    operations = {r.id:r for r in graph.operations}; values = {r.id:r for r in graph.values}
    links = {r.operation:r for r in metadata.operation_links}
    uses = {(r.operation,r.use):r for r in metadata.use_links}
    world = value_type(values[interface.world])
    for identity, protocol in selected.items():
        link = links[identity]; operation = operations[identity]
        nodes = [n for n in require_source_tree(source_tree, language.source, protocol.source) if isinstance(n,ast.Set)]
        need(len(nodes)==1 and _shape(nodes[0]), 'exact ordinary Set source/shape differs')
        node, = nodes
        definition = semantic.definitions.get(link.semantic_operation)
        need(link.source==protocol.source and link.opcode is Opcode.BUILD_SET
             and definition is not None and definition.kind is OperationKind.OPERATOR
             and definition.metadata.get('ast_type')=='Set' and definition.code_id==link.source.atom_id.wire
             and link.source.atom_id in definition.source_atoms and len(definition.output_slots)==1,
             'original SG/source/output association differs')
        need(operation.terminator is not None and operation.terminator.kind is TerminatorKind.INVOKE
             and operation.callee is None and not operation.effects_complete
             and Behavior.MEMORY in operation.behaviors
             and tuple(u.id for u in operation.uses)==operation.invoke_arguments,
             'construction must be an incomplete allocation/hash/equality invoke')
        args = operation.uses
        need(len(args)==len(node.elts)+1 and all(type(values[u.value]) is ReferenceValue for u in args[:-1])
             and type(values[args[-1].value]) is StateVersionValue
             and values[args[-1].value].location==values[interface.world].location,
             'ordered element references/world differ')
        for index,(child,use) in enumerate(zip(node.elts,args[:-1])):
            source = uses.get((identity,use.id))
            need(source is not None and source.role=='element' and source.index==index
                 and source.source.path==language.source.path and source.source.fingerprint==language.source.fingerprint
                 and (source.source.start_line,source.source.end_line,source.source.start_column,source.source.end_column)==_span(child),
                 'element original Use order/source differs')
        need(tuple((c.kind,c.types)for c in operation.completions)==(
            (ExitKind.NORMAL,(_REF,world)),(ExitKind.RAISE,function_exception_types(language,_REF,world)))
            and tuple(e.kind for e in operation.terminator.successors)==(ExitKind.NORMAL,ExitKind.RAISE)
            and all(edge.arguments==tuple(CompletionResult(i)for i in range(len(c.types)))
                    for edge,c in zip(operation.terminator.successors,operation.completions)),
            'normal/reference and exceptional payloads must retain their own completion/world ports')
    if not structural_only:
        need(options is not None and options.code_evidence is not None, 'independent readonly CodeWitness required')
        options.code_evidence.require_definition(metadata.source,interface.definition,model.source)
    return set(selected)
