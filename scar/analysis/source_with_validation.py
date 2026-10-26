"""Source/world/control checks for the synchronous context-scope interface."""
from __future__ import annotations

import ast

from scar.analysis.program_lowering import _REF, _BOOL
from scar.analysis.source_language import function_exception_types, require_source_tree
from scar.ir.program.control import LanguageCompletionKind as L
from scar.ir.program.model import (CompletionResult, DataValue, ExitKind, LiteralOrigin,
    ReferenceValue, StateVersionValue, TerminatorKind, value_type)
from scar.ir.program.source_language import SourceLanguageCapability as C, FUNCTION_WITH_PROTOCOLS
from scar.ir.program.structured import PythonProtocolKind as K


def validate_with(model, graph, interface, metadata, semantic, language,
                  *, source_tree=None, options=None, structural_only=False):
    def need(ok, detail):
        if not ok: raise ValueError('function With: ' + detail)
    selected = [p for p in model.protocols if p.kind.value in FUNCTION_WITH_PROTOCOLS]
    if not selected: return set()
    need(C.FUNCTION_WITH_314_V1 in language.capabilities and C.FUNCTION_TRY_314_V1 in language.capabilities
         and isinstance(source_tree, ast.Module), 'explicit With/paired propagation and original AST required')
    values = {v.id:v for v in graph.values}; operations = {o.id:o for o in graph.operations}
    blocks = {b.id:b for r in graph.regions for b in r.blocks}
    scopes = {s.id:s for s in graph.control_scopes}; owners = {b:s.id for s in graph.control_scopes for b in s.blocks}
    operation_blocks = {o:b.id for b in blocks.values() for o in b.operations}
    links = {r.operation:r for r in metadata.operation_links}; use_links = {(r.operation,r.use):r for r in metadata.use_links}
    uses = {u.id:u for o in graph.operations for u in o.uses}
    ports = {p.id:p for p in graph.control_ports}; pending = {p.value:p for p in graph.pending_completions}
    packets = {p.value:p for p in graph.exception_packets}
    world = value_type(values[interface.world])
    groups = {}
    for p in selected: groups.setdefault(p.source, []).append(p)

    def reachable(start, cleanup):
        seen, todo = set(), [start]
        while todo:
            b = todo.pop()
            if b in seen or owners[b] != cleanup: continue
            seen.add(b)
            todo.extend(e.block for e in operations[blocks[b].operations[-1]].terminator.successors)
        return seen

    for source, protocols in groups.items():
        nodes = [n for n in require_source_tree(source_tree, language.source, source) if isinstance(n, ast.With)]
        need(len(nodes)==1, 'exact original synchronous With required'); node, = nodes
        from scar.analysis.source_with_lowering import with_shape, check_compiler_with
        with_shape(node)
        if not structural_only:
            need(options is not None and options.code_evidence is not None, 'independent readonly compiler witness required')
            check_compiler_with(node, options.code_evidence.code)
        by_kind = {kind:[p for p in protocols if p.kind is kind] for kind in
                   (K.WITH_ENTER_CONTEXT,K.WITH_EXIT_NORMAL,K.WITH_EXIT_EXCEPTION)}
        need(all(len(p)==1 for p in by_kind.values()), 'one enter, normal exit and exceptional exit per lexical scope required')
        enter = operations[by_kind[K.WITH_ENTER_CONTEXT][0].operation]
        normal_exit = operations[by_kind[K.WITH_EXIT_NORMAL][0].operation]
        exception_exit = operations[by_kind[K.WITH_EXIT_EXCEPTION][0].operation]
        cleanup_rows = [r for r in graph.cleanup_interfaces if scopes[r.scope].source==source]
        need(len(cleanup_rows)==1, 'With has no unique original C1 cleanup')
        cleanup, = cleanup_rows; entry = blocks[cleanup.entry]
        need(scopes[cleanup.protected].source==source and len(entry.arguments)>=4
             and entry.arguments[-4]==cleanup.pending_argument and type(values[entry.arguments[-3]]) is DataValue
             and values[entry.arguments[-3]].data_type=='builtins.bool'
             and type(values[entry.arguments[-2]]) is ReferenceValue, 'With pending/mode/carrier partition differs')
        # No synthetic bound-method object: the saved special exit binding is
        # activation-local frame state reached only after this enter's NORMAL.
        enter_normal = enter.terminator.successors[0]
        arm = operations[blocks[enter_normal.block].operations[-1]]
        need(arm.terminator.kind is TerminatorKind.JUMP and len(arm.terminator.successors)==1
             and owners[arm.terminator.successors[0].block]==cleanup.protected
             and owners[operation_blocks[enter.id]]==scopes[cleanup.scope].parent,
             'cleanup must arm only after the exact enter NORMAL, before as binding/body')
        branch = operations[entry.operations[-1]]
        need(branch.terminator.kind is TerminatorKind.BRANCH
             and uses[branch.terminator.condition].value==entry.arguments[-3], 'cleanup classification must use its actual CFG mode')
        raised_blocks = reachable(branch.terminator.successors[0].block, cleanup.scope)
        ordinary_blocks = reachable(branch.terminator.successors[1].block, cleanup.scope)
        need(operation_blocks[exception_exit.id] in raised_blocks-ordinary_blocks
             and operation_blocks[normal_exit.id] in ordinary_blocks-raised_blocks,
             'normal and exceptional exit calls crossed the original classification branch')
        routes = [o for o in graph.operations if any(e.block==entry.id for e in getattr(o.terminator,'successors',()))]
        need(bool(routes), 'With cleanup has no original incoming completion')
        for route in routes:
            need(route.terminator.kind is TerminatorKind.CLEANUP_ROUTE, 'With cleanup must use canonical C1 routing')
            for edge in route.terminator.successors:
                if edge.block != entry.id: continue
                flag = values[uses[edge.arguments[-3]].value]
                need(type(flag) is DataValue and type(flag.origin) is LiteralOrigin and type(flag.origin.value) is bool
                     and flag.origin.value == (ports[edge.port].kind is L.RAISE),
                     'raise mode must match this exact original pending port, not an unproved flag')
                original = pending.get(uses[route.terminator.pending].value)
                need(original is not None and original.port==edge.port,
                     'With entry must forward its own original pending constructor')
                if flag.origin.value:
                    packet = packets.get(uses[original.payload].value) if original.payload is not None else None
                    need(packet is not None and uses[packet.exception].value==uses[edge.arguments[-2]].value,
                         'caught carrier must be this same original ExceptionPacket exception Use')
        for op in (enter,normal_exit,exception_exit):
            need(op.terminator is not None and op.terminator.kind is TerminatorKind.INVOKE
                 and op.callee is None and not op.effects_complete and links[op.id].source==source
                 and links[op.id].semantic_operation is None and tuple(u.id for u in op.uses)==op.invoke_arguments
                 and all(type(values[u.value]) is ReferenceValue for u in op.uses[:-1])
                 and type(values[op.uses[-1].value]) is StateVersionValue,
                 'context interface must retain ordinary incomplete reference/world call boundaries')
            need(tuple((s.kind,s.types)for s in op.completions)==
                 ((ExitKind.NORMAL,(_REF,world)),(ExitKind.RAISE,function_exception_types(language,_REF,world)))
                 and all(e.arguments==tuple(CompletionResult(i)for i in range(len(s.types)))
                         for e,s in zip(op.terminator.successors,op.completions)), 'context call payload or post-world differs')
        need(len(enter.uses)==2 and len(normal_exit.uses)==4 and len(exception_exit.uses)==2,
             'context enter/exit arity differs')
        expr = node.items[0].context_expr; link = use_links[(enter.id,enter.uses[0].id)]
        need((link.source.start_line,link.source.end_line,link.source.start_column,link.source.end_column)==
             (expr.lineno,expr.end_lineno,expr.col_offset,expr.end_col_offset), 'manager input is not the one original context expression')
        for i,use in enumerate(normal_exit.uses[:-1]):
            origin = values[use.value].origin; link = use_links[(normal_exit.id,use.id)]
            need(type(origin) is LiteralOrigin and origin.value is None and link.role=='exit-none' and link.index==i,
                 'nonexception exit must receive the three original None operands')
        need(exception_exit.uses[0].value==entry.arguments[-2]
             and use_links[(exception_exit.id,exception_exit.uses[0].id)].role=='caught-exception',
             'exception exit must use this exact caught reference; type/current traceback stay inside its interface')
        truth = [operations[p.operation]for p in model.protocols if p.source==source and p.kind is K.TRUTH]
        need(len(truth)==1 and truth[0].uses[0].value==blocks[exception_exit.terminator.successors[0].block].arguments[0],
             'only the exceptional exit result may control suppression')
        truth_normal = blocks[truth[0].terminator.successors[0].block]
        truth_branch = operations[truth_normal.operations[-1]]
        need(truth_branch.terminator.kind is TerminatorKind.BRANCH
             and uses[truth_branch.terminator.condition].value==truth_normal.arguments[0],
             'suppression must branch on this exact truth completion result')
        true_blocks = reachable(truth_branch.terminator.successors[0].block, cleanup.scope)
        false_blocks = reachable(truth_branch.terminator.successors[1].block, cleanup.scope)
        replacements = [r for r in graph.cleanup_replacements if r.cleanup==cleanup.scope]
        suppress = [r for r in replacements if ports[pending[uses[r.replacement].value].port].kind is L.FALLTHROUGH]
        need(len(suppress)==1 and operation_blocks[suppress[0].operation] in true_blocks-false_blocks,
             'only truth-true may replace original pending with fallthrough')
        resumes = [r for r in graph.cleanup_resumes if r.cleanup==cleanup.scope]
        need(len(resumes)==2 and sum(operation_blocks[r.operation] in false_blocks-true_blocks for r in resumes)==1
             and sum(operation_blocks[r.operation] in ordinary_blocks-raised_blocks for r in resumes)==1,
             'ordinary exit and truth-false exceptional exit must each resume the exact original pending')
    return {p.operation for p in selected}
