"""Check nested function creation as a source-level interface, not bytecode IR."""
from __future__ import annotations

import ast

from scar.analysis.source_language import function_exception_types, require_source_tree
from scar.ir.program.bindings import BindingState
from scar.ir.program.environments import EnvironmentRole
from scar.ir.program.model import (AccessMode, Behavior, CompletionResult, ExitKind, LocalBindingValue,
    ReferenceValue, StateVersionValue, TerminatorKind, ValueKind, ValueType, value_type)
from scar.ir.program.source_language import SourceLanguageCapability as C, NESTED_FUNCTION_PROTOCOLS
from scar.ir.program.state_addresses import AddressCoverage, AddressEffect, CellContent, InvokeStateOperand, ReferenceOwner
from scar.ir.program.structured import PythonProtocolKind as K
from scar.ir.v2.semantic import OperationKind, SemanticRelation


def need(value, detail):
    if not value:
        raise ValueError('function definition: ' + detail)


def span(node):
    return node.lineno, node.end_lineno, node.col_offset, node.end_col_offset


def refspan(source):
    return source.start_line, source.end_line, source.start_column, source.end_column


def validate_function_definitions(model, graph, interface, metadata, semantic, language,
                                  *, source_tree=None, options=None, structural_only=False):
    protocols = {r.operation: r for r in model.protocols}
    selected = {key for key, row in protocols.items() if row.kind.value in NESTED_FUNCTION_PROTOCOLS}
    if not selected:
        return set()
    need(C.NESTED_FUNCTION_314_V1 in language.capabilities and isinstance(source_tree, ast.Module),
         'explicit capability and exact retained original AST required')
    operations = {r.id: r for r in graph.operations}
    values = {r.id: r for r in graph.values}
    blocks = {r.id: r for region in graph.regions for r in region.blocks}
    links = {r.operation: r for r in metadata.operation_links}
    sources = {(r.operation, r.use): r for r in metadata.use_links}
    constants = {r.operation: r for r in language.constants}
    addresses = {r.site.operation: r for r in graph.state_address_refinements}
    environments = [r for r in graph.environments if r.region == interface.region]
    need(len(environments) == 1, 'one original parent environment required')
    environment = environments[0]
    globals_ref = next(r.reference for r in environment.members if r.role is EnvironmentRole.GLOBALS_NAMESPACE)
    cell_values = [blocks[operations[r.operation].terminator.successors[0].block].arguments[0]
                   for r in model.protocols if r.kind is K.MAKE_CELL]
    free_values = [r.reference for r in environment.members if r.role is EnvironmentRole.CAPTURED_CELL]
    available_cells = set(cell_values + free_values)
    cells_by_name = None
    if not structural_only:
        from scar.analysis.environment_lowering import captured_cell_slot
        evidence = options.code_evidence
        need(evidence is not None and evidence.store.document['runtime']['version'][:3] == [3, 14, 7],
             'independent pinned readonly parent compiler witness required')
        transient = {r.name for r in language.compiler_locals if r.category == 'COMPREHENSION_TRANSIENT'}
        names = tuple(n for n in evidence.code.co_cellvars if n not in transient)
        need(len(names) == len(cell_values) and len(evidence.code.co_freevars) == len(free_values),
             'actual parent cells differ from the complete original compiler layout')
        cells_by_name = dict(zip(names, cell_values))
        for name, member in zip(evidence.code.co_freevars, environment.members[5:]):
            need(member.cell_slot == captured_cell_slot(interface.definition, name), 'free cell name/position differs')
            cells_by_name[name] = member.reference
    world = value_type(values[interface.world])
    reference = ValueType(ValueKind.REFERENCE)
    covered = set()

    def invoke(identity, count, results):
        op = operations[identity]
        need(op.callee is None and op.terminator is not None and op.terminator.kind is TerminatorKind.INVOKE
             and not op.effects_complete and len(op.uses) == count + 1
             and op.invoke_arguments == tuple(u.id for u in op.uses)
             and all(type(values[u.value]) is ReferenceValue for u in op.uses[:-1])
             and type(values[op.uses[-1].value]) is StateVersionValue
             and values[op.uses[-1].value].location == values[interface.world].location
             and tuple((s.kind, s.types) for s in op.completions) ==
                 ((ExitKind.NORMAL, (reference,) * results + (world,)),
                  (ExitKind.RAISE, function_exception_types(language, reference, world)))
             and tuple(s.kind for s in op.terminator.successors) == (ExitKind.NORMAL, ExitKind.RAISE)
             and all(e.arguments == tuple(CompletionResult(i) for i in range(len(s.types)))
                     for e, s in zip(op.terminator.successors, op.completions)),
             'creation/write lost its original references, world or normal/raise interface')
        need(len(op.accesses) == 1 and op.accesses[0].mode is AccessMode.READ_WRITE
             and op.accesses[0].before == op.uses[-1].id and not op.accesses[0].full_overwrite,
             'creation/write does not retain its incomplete input and post-world')
        return op, blocks[op.terminator.successors[0].block]

    makes = [r.operation for r in model.protocols if r.kind is K.MAKE_NESTED_FUNCTION]
    need(len({protocols[i].source for i in makes}) == len(makes), 'source definition has duplicate creation interfaces')
    for identity in makes:
        covered.add(identity)
        source = protocols[identity].source
        nodes = [n for n in require_source_tree(source_tree, language.source, source) if isinstance(n, ast.FunctionDef)]
        need(len(nodes) == 1, 'creation has no exact original FunctionDef AST')
        node = nodes[0]
        need(not node.decorator_list and not node.type_params and not any(x is not None for x in node.args.kw_defaults),
             'unsupported decorator/type-parameter/keyword-default form entered a body')
        declarations = [r for r in semantic.definitions.values() if r.code_id == source.atom_id.wire
                        and source.atom_id in r.source_atoms and r.metadata.get('phase') == 'definition_time']
        bodies = [r for r in semantic.definitions.values() if r.code_id == source.atom_id.wire
                  and source.atom_id in r.source_atoms and r.metadata.get('phase') == 'call_time'
                  and r.kind in (OperationKind.FUNCTION, OperationKind.METHOD)]
        need(len(declarations) == len(bodies) == 1 and bodies[0].label == node.name
             and links[identity].source == source and links[identity].semantic_operation == declarations[0].id
             and links[identity].opcode is None, 'creation must link declaration, never execute the child body')
        slots = [semantic.slots[e.target.id] for e in semantic.edges.values()
                 if e.source.id == declarations[0].id and e.relation is SemanticRelation.WRITES_SLOT]
        need(len(slots) == 1 and slots[0].owner == interface.definition and slots[0].name == node.name,
             'definition name has no exact original parent lexical slot')
        operation, normal = invoke(identity, len(operations[identity].uses) - 1, 1)
        uses = [sources[(identity, u.id)] for u in operation.uses[:-1]]
        refs = [u.value for u in operation.uses[:-1]]
        need([(u.role, u.index) for u in uses[:2]] == [('function-code', 0), ('function-globals', 0)]
             and refs[1] == globals_ref, 'function factory changed original code/globals inputs')
        own_constants = {r.operation: r for r in language.constants if r.source == source}
        by_reference = {operations[i].results[0]: r for i, r in own_constants.items()}
        need(refs[0] in by_reference, 'function code is not the original code-table reference')
        annotated = (node.returns is not None or any(a.annotation is not None for a in
            (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)) or
            any(a is not None and a.annotation is not None for a in (node.args.vararg, node.args.kwarg)))
        roles = [(u.role, u.index) for u in uses]
        cursor = 2
        if node.args.defaults:
            if cursor < len(uses) and uses[cursor].role == 'function-defaults-tuple':
                need(uses[cursor].index == 0 and refs[cursor] in by_reference and uses[cursor].source == source,
                     'default tuple lacks original constant provenance')
                cursor += 1
            else:
                for index, default in enumerate(node.args.defaults):
                    need(cursor < len(uses) and roles[cursor] == ('function-default', index)
                         and refspan(uses[cursor].source) == span(default), 'default value/source order differs')
                    cursor += 1
        captures = {}
        for role in ('function', 'annotation'):
            if role == 'annotation':
                if not annotated:
                    break
                need(cursor < len(uses) and roles[cursor] == ('annotation-code', 0)
                     and refs[cursor] in by_reference, 'deferred annotation code reference missing')
                cursor += 1
            captured = []
            while cursor < len(uses) and uses[cursor].role == role + '-closure-cell':
                need(uses[cursor].index == len(captured) and uses[cursor].source == source
                     and refs[cursor] in available_cells, 'capture substituted cell contents or changed original cell order')
                captured.append(refs[cursor]); cursor += 1
            captures[role] = tuple(captured)
        need(cursor == len(uses), 'unexpected or duplicated creation input')
        used_constants = {refs[i] for i, u in enumerate(uses) if u.role in
                          ('function-code', 'annotation-code', 'function-defaults-tuple')}
        need(used_constants == set(by_reference), 'orphan/foreign function constant table read')
        if not structural_only:
            from scar.analysis.source_function_definition_lowering import compiler_plan
            stages, child, annotation = compiler_plan(node, evidence.code)
            required = {'function-code': child.arg}
            if annotation is not None:
                required['annotation-code'] = annotation.arg
            default = next((row for action, role, row in stages if action == 'constant' and role == 'defaults'), None)
            if default is not None:
                required['function-defaults-tuple'] = default.arg
            for role, index in required.items():
                selected_uses = [i for i, u in enumerate(uses) if u.role == role]
                need(len(selected_uses) == 1 and by_reference[refs[selected_uses[0]]].constant_path == (index,),
                     'creation input differs from exact original compiler constant index')
            need(('function-defaults-tuple' in required) == any(u.role == 'function-defaults-tuple' for u in uses),
                 'default tuple packing differs from original compiler')
            for role, load in (('function', child), ('annotation', annotation)):
                if load is not None:
                    need(captures[role] == tuple(cells_by_name[n] for n in load.argval.co_freevars),
                         'creation did not capture exact compiler-ordered parent cell identities')
        function = normal.arguments[0]
        following = [operations[i] for i in normal.operations]
        need(len(following) >= 2 and protocols.get(following[0].id) is not None
             and protocols[following[0].id].kind is K.FRAME_HOLD_TEMPORARY
             and following[0].uses[0].value == function, 'created function is not retained until its actual name write')
        binding = following[1]
        marker = protocols.get(binding.id)
        need(marker is not None and marker.source == source, 'name binding lost its exact FunctionDef source')
        if marker.kind is K.FRAME_BIND:
            need(len(binding.uses) == 3 and type(values[binding.uses[0].value]) is LocalBindingValue
                 and values[binding.uses[0].value].slot == slots[0].slot_id and binding.uses[1].value == function
                 and len(following) >= 3, 'fast-local definition binding changed its original slot/function')
            definition = following[2]
            need(len(definition.results) == 1 and type(values[definition.results[0]]) is LocalBindingValue
                 and values[definition.results[0]].slot == slots[0].slot_id
                 and len(definition.uses) == 1 and definition.uses[0].value == function
                 and any(r.value == definition.results[0] and r.state is BindingState.BOUND for r in graph.binding_definitions),
                 'created function was not the original bound SSA payload')
        else:
            need(marker.kind is K.STORE_NESTED_FUNCTION_CELL, 'definition has an unsupported name-write interface')
            covered.add(binding.id)
            op, _ = invoke(binding.id, 2, 0)
            need(op.uses[0].value in available_cells and op.uses[1].value == function,
                 'cell binding changed original cell/function inputs')
            if not structural_only:
                need(cells_by_name[node.name] == op.uses[0].value, 'definition stored into a different compiler cell')
            row = addresses.get(op.id)
            need(row is not None and row.site == InvokeStateOperand(op.id, op.uses[-1].id)
                 and row.coverage is AddressCoverage.PARTIAL and row.protocol is None
                 and row.effects == (AddressEffect(ReferenceOwner(op.uses[0].id), (CellContent(),), AccessMode.WRITE),),
                 'definition cell write lacks exact original owner/content/post-world')
    need(covered == selected, 'orphan function creation/name-write protocol')
    return selected
