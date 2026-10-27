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
    if builder.has_language('COMPREHENSION_TARGETS_314_V1') and isinstance(target,ast.Name):
        from scar.analysis.source_comprehension_lowering import scoped_target
        if scoped_target(builder,target) is not None:return
    if isinstance(target, (ast.Tuple, ast.List)) and isinstance(target.ctx, ast.Store):
        for child in target.elts:
            _check(builder, child)
    elif builder.has_language('UNPACK_TARGETS_314_V1'):
        if (isinstance(target, ast.Name) and isinstance(target.ctx, ast.Store)
                and target.id in (set(builder.locals) | set(builder.cell_references) | set(builder.global_names))):
            return
        if isinstance(target, (ast.Attribute, ast.Subscript)) and isinstance(target.ctx, ast.Store):
            if any(isinstance(n,(ast.BoolOp,ast.IfExp,ast.Lambda,ast.NamedExpr,ast.Starred,
                                 ast.ListComp,ast.SetComp,ast.DictComp,ast.GeneratorExp)) for n in ast.walk(target)):
                raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX,target,'UNPACK_TARGET_CONTROL_FLOW_OR_EXPANSION_UNIMPLEMENTED')
            return
        raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX,target,'UNPACK_TARGET_STARRED_OR_BINDING_UNIMPLEMENTED')
    elif not (isinstance(target, ast.Name) and isinstance(target.ctx, ast.Store) and target.id in builder.locals):
        raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, target,
            "UNPACK_FIXED requires fixed tuple/list ordinary-local leaves; starred/effectful targets remain unimplemented")


def lower_unpack_target(builder, target, rhs, cursor, *, rhs_held=False):
    _check(builder, target)
    if builder.has_language('UNPACK_TARGETS_314_V1') and builder.language_options.code_evidence is None:
        raise _Unsupported(GapKind.CODE_VERSION,target,'UNPACK_TARGET_READONLY_CODE_WITNESS_REQUIRED')
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
        if builder.has_language("GENEXPR_314_V1"):
            from dataclasses import replace
            from scar.analysis.source_generator_lowering import unpack_callee
            callee = unpack_callee(builder, target, rhs)
            if callee is not None:
                original = builder.operation_records[operation]
                connected = replace(original, callee=callee)
                builder.operations[builder.operations.index(original)] = connected
                builder.operation_records[operation] = connected
        _transfer(builder, consumed, target)
        # Normal results are published stack references; reverse holds put
        # the first target on top. No extra INCREF or allocation is asserted.
        for child, value in reversed(tuple(zip(target.elts, values))):
            _hold(builder, cursor, child, value)
        for child, value in zip(target.elts, values):
            if isinstance(child, (ast.Tuple, ast.List)):
                cursor = lower_unpack_target(builder, child, value, cursor, rhs_held=True)
            elif builder.has_language('UNPACK_TARGETS_314_V1') and isinstance(child,(ast.Attribute,ast.Subscript)):
                # The published result already owns its pending reference.
                # Reuse that hold through receiver/key evaluation and both
                # store completions; never invent an extra stack copy.
                from scar.analysis.source_heap_lowering import store_heap_target
                cursor = store_heap_target(builder,child,value,cursor,rhs_held=True)
            else:
                scoped=None
                if builder.has_language('COMPREHENSION_TARGETS_314_V1'):
                    from scar.analysis.source_comprehension_lowering import scoped_target
                    scoped=scoped_target(builder,child)
                cursor = scoped.bind(child,value,cursor) if scoped is not None else builder.store(child, value, cursor)
                _transfer(builder, ((child, value),), child)
            if cursor is None:
                return None
        builder.gap(GapKind.EFFECT_SUMMARY, target,
            "fixed unpack order/arity/ports are connected; iterator dispatch, aliasing, finalizers and runtime implementation remain unproved")
        return cursor
    finally:
        del builder.active_temporaries[baseline:]


def validate_unpack_targets(model, graph, interface, metadata, semantic, language, *,
                            source_tree=None, options=None, structural_only=False):
    """Follow the original targets through their linear NORMAL continuations.

    This supplements (never replaces) the ordinary heap/cell address and CFG
    validators. All N results must already be held before target evaluation;
    each original result is assigned once in source order. Potentially raising
    receiver/key/store operations retain their own RAISE post-world. No later
    target is visited before the earlier target's NORMAL completion.
    """
    from scar.analysis.source_language import require_source_tree
    from scar.ir.program.model import ReferenceValue, LocalBindingValue, TerminatorKind
    def need(condition,detail):
        if not condition:raise ValueError('unpack targets: '+detail)
    need(isinstance(source_tree,ast.Module),'exact retained target AST is required')
    operations={r.id:r for r in graph.operations};values={r.id:r for r in graph.values}
    blocks={b.id:b for r in graph.regions for b in r.blocks}
    protocols={r.operation:r for r in model.protocols};links={r.operation:r for r in metadata.operation_links}
    use_links={(r.operation,r.use):r for r in metadata.use_links}
    shapes={r.operation:r for r in language.unpackings};visiting=set()
    from scar.analysis.source_comprehension_lowering import scoped_target_slots
    scoped_slots=scoped_target_slots(semantic,source_tree,language)
    def kind(key):
        p=protocols.get(key)
        return None if p is None else p.kind
    def inside(source,target):
        return (source.path==target.path and source.fingerprint==target.fingerprint
                and (target.start_line,target.start_column)<=(source.start_line,source.start_column)
                and (source.end_line,source.end_column)<=(target.end_line,target.end_column))
    def normal(operation):
        need(operation.terminator is not None and operation.terminator.kind is TerminatorKind.INVOKE,
             'effectful target lost its invoke boundary')
        edges=[e for e in operation.terminator.successors if e.kind is ExitKind.NORMAL]
        need(len(edges)==1,'effectful target must have one NORMAL continuation')
        return blocks[edges[0].block],0
    def find_store(block,position,reference,expected):
        seen=set()
        while True:
            need((block.id,position)not in seen,'cyclic target evaluation')
            seen.add((block.id,position));need(position<len(block.operations),'target store is missing')
            identity=block.operations[position];operation=operations[identity]
            if kind(identity) in expected and protocols[identity].source==reference:
                return operation,block,position
            need(inside(links[identity].source,reference),'target evaluation escaped its original target subtree')
            need(kind(identity)not in (PythonProtocolKind.FRAME_BIND,PythonProtocolKind.STORE_CELL,
                    PythonProtocolKind.STORE_GLOBAL,PythonProtocolKind.STORE_ATTRIBUTE,PythonProtocolKind.STORE_SUBSCRIPT),
                 'another target was stored before the current original target')
            if operation.terminator is None:position+=1
            else:block,position=normal(operation)
    def stores(identity):
        need(identity not in visiting,'cyclic original unpack shape');visiting.add(identity)
        shape=shapes[identity];operation=operations[identity];block,position=normal(operation)
        original_results=block.arguments[:-1]
        need(len(original_results)==len(shape.child_targets),'unpack result arity differs')
        position=len(shape.child_targets)  # Common language validator checks exact reverse result holds.
        for index,reference in enumerate(shape.child_targets):
            nodes=require_source_tree(source_tree,language.source,reference)
            nodes=[n for n in nodes if isinstance(n,(ast.Name,ast.Attribute,ast.Subscript,ast.Tuple,ast.List))]
            need(len(nodes)==1 and isinstance(nodes[0].ctx,ast.Store),'original Store target is absent/ambiguous')
            node,=nodes;value=original_results[index]
            if isinstance(node,(ast.Tuple,ast.List)):
                need(position<len(block.operations),'nested unpack missing')
                key=block.operations[position]
                need(key in shapes and shapes[key].source==reference,'nested target order/source differs')
                current=operations[key];own={u.id:u for u in current.uses}
                need(own[current.invoke_arguments[0]].value==value,'nested unpack lost the corresponding original result')
                block,position=stores(key)
                continue
            allowed=((PythonProtocolKind.FRAME_BIND,PythonProtocolKind.STORE_CELL,PythonProtocolKind.STORE_GLOBAL)
                     if isinstance(node,ast.Name)else(PythonProtocolKind.STORE_ATTRIBUTE,)
                     if isinstance(node,ast.Attribute)else(PythonProtocolKind.STORE_SUBSCRIPT,))
            current,block,position=find_store(block,position,reference,allowed)
            assigned=[u for u in current.uses if (s:=use_links.get((current.id,u.id)))is not None
                      and s.role=='assigned-reference' and s.source==reference]
            need(len(assigned)==1 and assigned[0].value==value,'target did not receive its exact original unpack result')
            if kind(current.id)is PythonProtocolKind.FRAME_BIND:
                need(position+1<len(block.operations),'local target binding definition missing')
                binding=operations[block.operations[position+1]]
                need(len(binding.results)==1 and type(values[binding.results[0]])is LocalBindingValue
                     and len(binding.uses)==1 and binding.uses[0].value==value
                     and (semantic.slots[values[binding.results[0]].slot].owner==interface.definition
                          or scoped_slots.get(reference)==values[binding.results[0]].slot),
                     'ordinary local target changed its original reference/lexical slot')
                position+=2
            else:
                block,position=normal(current)
                if kind(current.id)in(PythonProtocolKind.STORE_ATTRIBUTE,PythonProtocolKind.STORE_SUBSCRIPT):
                    refs=[u.value for u in current.uses[:-1]]
                    released=([refs[1]]if isinstance(node,ast.Subscript)else[])+[refs[0],value]
                    for expected in released:
                        need(position<len(block.operations),'heap target normal release missing')
                        release=operations[block.operations[position]]
                        need(kind(release.id)is PythonProtocolKind.FRAME_RELEASE_TEMPORARY
                             and [u.value for u in release.uses if type(values[u.value])is ReferenceValue]==[expected],
                             'heap target must release key/receiver/exact assigned result in original order')
                        position+=1
        visiting.remove(identity)
        return block,position
    for identity in shapes:stores(identity)
    if not structural_only:
        need(options is not None and options.code_evidence is not None,'independent readonly code evidence required')
        options.code_evidence.require_definition(metadata.source,interface.definition,model.source)


__all__ = ["lower_unpack_target", "validate_unpack_targets"]
