"""Original mapping-frame function factories, decorator chains and name writes.

This consumer checks existing source/core/constant records. It neither executes
the deferred function/annotation body nor constructs a second body authority.
The ordinary module reader still owns whole-graph SSA, frame and C0/C1 checks.
"""
from __future__ import annotations

import ast

from scar.analysis.source_mapping_function_lowering import mapping_function_plan
from scar.ir.program.model import (AccessMode, Behavior, BlockArgument, CompletionResult,
    ExitKind, LiteralOrigin, OperationResult, ReferenceValue, StateVersionValue,
    TerminatorKind, ValueKind, ValueType, value_type)
from scar.ir.program.module_entries import FrameBodyProtocolKind as K, FrameCompletionProfile
from scar.ir.program.source import SourceRole
from scar.ir.program.state_addresses import AddressCoverage, AddressEffect, InvokeStateOperand, NamespaceKey, ReferenceOwner
from scar.ir.program.structured import PythonProtocolKind as P
from scar.ir.v2.common import SourceReference
from scar.ir.v2.semantic import OperationKind, SemanticRelation


def _need(condition, detail):
    if not condition:
        raise ValueError("mapping function: " + detail)


def _span(node):
    return node.lineno, node.end_lineno, node.col_offset, node.end_col_offset


def validate_mapping_function(node, *, source, graph, overlay, semantic, code_evidence,
                              globals_namespace, locals_namespace):
    """Check one original definition; return its claimed factory/apply/store IDs."""
    from scar.analysis.source_module_lowering import require_root_evidence
    unit = overlay.declaration.unit
    require_root_evidence(unit, code_evidence)
    plan = mapping_function_plan(node, code_evidence.code)
    _need(type(source) is SourceReference, "function definition requires its original statement SourceReference")
    atom = semantic.source_atoms.get(source.atom_id)
    _need(atom is not None and atom.reference == source and atom.kind == type(node).__name__
          and (source.path, source.fingerprint) == (unit.snapshot.path, unit.snapshot.fingerprint)
          and (source.start_line, source.end_line, source.start_column, source.end_column) == _span(node),
          "definition is not its original source atom/snapshot")
    declarations = [d for d in semantic.definitions.values() if d.code_id == source.atom_id.wire
                    and source.atom_id in d.source_atoms and d.metadata.get("phase") == "definition_time"]
    bodies = [d for d in semantic.definitions.values() if d.code_id == source.atom_id.wire
              and source.atom_id in d.source_atoms and d.metadata.get("phase") == "call_time"
              and d.kind in (OperationKind.FUNCTION, OperationKind.METHOD)]
    _need(len(declarations) == len(bodies) == 1 and bodies[0].label == node.name,
          "creation must retain the original declaration and distinct deferred body definition")
    slots = [semantic.slots[e.target.id] for e in semantic.edges.values()
             if e.source.id == declarations[0].id and e.relation is SemanticRelation.WRITES_SLOT]
    _need(len(slots) == 1 and slots[0].owner == unit.initializer and slots[0].name == node.name,
          "function name must bind its original module slot, never a child fast local")
    operations = {o.id: o for o in graph.operations}
    values = {v.id: v for v in graph.values}
    blocks = {b.id: b for r in graph.regions for b in r.blocks}
    owners = {i: r.id for r in graph.regions for b in r.blocks for i in b.operations}
    positions = {i: (b.id, n) for b in blocks.values() for n, i in enumerate(b.operations)}
    protocols = {p.operation: p for p in overlay.protocols}
    links = {r.operation: r for r in overlay.operation_links}
    uses = {(r.operation, r.use): r for r in overlay.use_links}
    root = next(r for r in graph.regions if r.id == graph.root)
    entry = blocks[root.entry]
    _need(entry.arguments[:2] == (locals_namespace, globals_namespace)
          and all(type(values[v]) is ReferenceValue and values[v].origin == BlockArgument(entry.id, i)
                  for i, v in enumerate((locals_namespace, globals_namespace))),
          "namespace inputs are not the original mapping-frame L/G entry ports")
    world = value_type(values[entry.arguments[-1]])
    ref = ValueType(ValueKind.REFERENCE)
    paired = overlay.completion_profile is FrameCompletionProfile.PROPAGATION_REF_PAIR_314_V1
    _need(paired or overlay.completion_profile is FrameCompletionProfile.RAW_EXCEPTION_REF_314_V1,
          "unknown module exception boundary")
    raised = (ref, ref, world) if paired else (ref, world)

    def invoke(identity, count, results, *, memory):
        op = operations[identity]
        expected = ((ExitKind.NORMAL, (ref,) * results + (world,)), (ExitKind.RAISE, raised))
        _need(owners[identity] == graph.root and op.callee is None and not op.effects_complete
              and op.terminator is not None and op.terminator.kind is TerminatorKind.INVOKE
              and len(op.uses) == count + 1 and op.invoke_arguments == tuple(u.id for u in op.uses)
              and all(type(values[u.value]) is ReferenceValue for u in op.uses[:-1])
              and value_type(values[op.uses[-1].value]) == world and not op.accesses
              and set(op.behaviors) == {Behavior.CONTROL, Behavior.READ, Behavior.WRITE} | ({Behavior.MEMORY} if memory else set())
              and tuple((c.kind, c.types) for c in op.completions) == expected
              and tuple(e.kind for e in op.terminator.successors) == (ExitKind.NORMAL, ExitKind.RAISE)
              and all(e.arguments == tuple(CompletionResult(i) for i in range(len(types)))
                      and tuple(value_type(values[v]) for v in blocks[e.block].arguments) == types
                      for e, (_, types) in zip(op.terminator.successors, expected)),
              "factory/call/write lost exact references, completion-owned results or post-world")
        return op, blocks[op.terminator.successors[0].block]

    def same_source(reference, expression):
        return (type(reference) is SourceReference
                and (reference.path, reference.fingerprint) == (source.path, source.fingerprint)
                and (reference.start_line, reference.end_line, reference.start_column, reference.end_column) == _span(expression))

    def expression_value(expression):
        candidates = set()
        for row in overlay.value_links:
            value = values[row.value]
            if row.role is not SourceRole.EXPRESSION or value.region != graph.root or not same_source(row.source, expression):
                continue
            if type(value) is not ReferenceValue:
                continue
            origin = value.origin
            if isinstance(expression, ast.Constant) and type(origin) is LiteralOrigin:
                if type(origin.value) is type(expression.value) and origin.value == expression.value:
                    candidates.add(value.id)
            elif type(origin) is OperationResult:
                if same_source(links[origin.operation].source, expression):
                    candidates.add(value.id)
            elif type(origin) is BlockArgument and origin.index == 0:
                producers = [op for op in graph.operations if owners[op.id] == graph.root
                             and op.terminator is not None and op.terminator.kind is TerminatorKind.INVOKE
                             and same_source(links[op.id].source, expression)
                             and any(e.kind is ExitKind.NORMAL and e.block == origin.block for e in op.terminator.successors)]
                if len(producers) == 1:
                    candidates.add(value.id)
        _need(len(candidates) == 1, "header expression lacks its unique original literal/producer NORMAL value")
        return next(iter(candidates))

    def hold(value, expression, role):
        found = []
        for p in overlay.protocols:
            if p.kind is not P.FRAME_HOLD_TEMPORARY:
                continue
            op = operations[p.operation]
            if (owners[op.id] == graph.root and len(op.uses) == 2 and op.uses[0].value == value
                    and same_source(p.source, expression)):
                link = uses.get((op.id, op.uses[0].id))
                if link is not None and link.role == "mapping-function-held-" + role and link.index == 0:
                    found.append(op.id)
        _need(len(found) == 1, "source temporary has no unique ordered hold occurrence")
        return found[0]

    constant_rows = [row for row in overlay.constants if row.source == source]
    constants = {row.operation: row for row in constant_rows}
    _need(len(constants) == len(constant_rows), "duplicate definition code-constant provenance")
    claimed_constants = set()
    def constant(value, instruction):
        origin = values[value].origin
        _need(type(origin) is OperationResult and origin.index == 0 and origin.operation in constants,
              "factory input is not its original code-table result")
        op = operations[origin.operation];record = constants[op.id]
        _need(owners[op.id] == graph.root and protocols[op.id].kind is P.READ_CODE_CONSTANT
              and protocols[op.id].source == source and links[op.id].source == source
              and record.code_key == code_evidence.code_layout_key and record.constant_path == (instruction.arg,)
              and code_evidence.code.co_consts[instruction.arg] is instruction.argval
              and op.terminator is None and op.callee is None and not op.effects_complete
              and op.behaviors == (Behavior.READ,) and len(op.uses) == len(op.accesses) == len(op.results) == 1
              and op.results[0] == value and value_type(values[op.uses[0].value]) == world
              and op.accesses[0].before == op.uses[0].id and op.accesses[0].mode is AccessMode.READ
              and op.accesses[0].after is None,
              "factory code/default slot provenance or nonexecuting read differs")
        claimed_constants.add(op.id)

    makes = [p.operation for p in overlay.protocols if p.kind is K.MAKE_FUNCTION_314 and p.source == source]
    _need(len(makes) == 1, "definition must have one original function-creation interface")
    make = makes[0];factory, normal = invoke(make, len(operations[make].uses)-1, 1, memory=True)
    _need(links[make].source == source and links[make].semantic_operation == declarations[0].id
          and links[make].opcode is None, "factory must link definition-time declaration, not execute child")
    operands = factory.uses[:-1]
    _need(len(operands) >= 2 and operands[1].value == globals_namespace,
          "factory must borrow the original module globals")
    for use, role in zip(operands[:2], ("function-code", "function-globals")):
        row = uses[(make, use.id)]
        _need(row.source == source and (row.role, row.index) == (role, 0), "factory code/globals Use differs")
    constant(operands[0].value, plan.child)
    offset = 2;header_holds = [];header_inputs = [];decorators = []
    for index, expression in enumerate(node.decorator_list):
        value = expression_value(expression)
        decorators.append((expression, value, index));header_holds.append(hold(value, expression, "decorator"))
        header_inputs.append((expression,header_holds[-1]))
    if plan.defaults_constant is not None:
        _need(offset < len(operands), "constant defaults tuple missing")
        use = operands[offset];row = uses[(make, use.id)]
        _need(row.source == source and (row.role, row.index) == ("function-defaults-tuple", 0), "defaults tuple Use differs")
        constant(use.value, plan.defaults_constant);offset += 1
    else:
        for index, expression in enumerate(node.args.defaults):
            _need(offset < len(operands), "positional default input missing")
            use = operands[offset];row = uses[(make, use.id)]
            _need(use.value == expression_value(expression) and same_source(row.source, expression)
                  and (row.role, row.index) == ("function-default", index), "positional default value/order/source differs")
            header_holds.append(hold(use.value, expression, "default"))
            header_inputs.append((expression,header_holds[-1]));offset += 1
    for index, (arg, expression) in enumerate(plan.keyword_defaults):
        _need(offset < len(operands), "keyword default input missing")
        use = operands[offset];row = uses[(make, use.id)]
        _need(use.value == expression_value(expression) and same_source(row.source, expression)
              and (row.role, row.index) == ("function-keyword-default:"+arg.arg, index), "keyword default value/order/source differs")
        header_holds.append(hold(use.value, expression, "keyword-default"))
        header_inputs.append((expression,header_holds[-1]));offset += 1
    if plan.annotation is not None:
        _need(offset < len(operands), "lazy annotation code missing")
        use = operands[offset];row = uses[(make, use.id)]
        _need(row.source == source and (row.role, row.index) == ("annotation-code", 0), "annotation code Use differs")
        constant(use.value, plan.annotation);offset += 1
    _need(offset == len(operands) and claimed_constants == set(constants), "unexpected factory inputs or unclaimed definition code reads")
    previous=None
    for expression,held in header_inputs:
        if previous is not None:
            start,end=(expression.lineno,expression.col_offset),(expression.end_lineno,expression.end_col_offset)
            for op in graph.operations:
                original=links[op.id].source
                if (owners[op.id]==graph.root and op.terminator is not None
                        and op.terminator.kind is TerminatorKind.INVOKE
                        and type(original) is SourceReference
                        and (original.path,original.fingerprint)==(source.path,source.fingerprint)
                        and start<=(original.start_line,original.start_column)
                        and (original.end_line,original.end_column)<=end):
                    _need(_world_after(op.uses[-1].value,previous,values,operations,blocks),
                          "header expression effect ran before the preceding decorator/default evaluation")
        record=operations[held]
        _need(len(record.accesses)==1 and record.accesses[0].after is not None,
              "header hold has no actual post-world")
        previous=record.accesses[0].after
    applications = {p.operation for p in overlay.protocols if p.kind is K.APPLY_DECORATOR_314 and p.source == source}
    _need(len(applications) == len(decorators), "decorator application inventory differs")
    stages = [*header_holds, make];current = normal.arguments[0]
    stages.append(hold(current, node, "function"));result_holds={current:stages[-1]};result_consumers={}
    boundaries = [(make, tuple(v for _,v,_ in decorators))]
    for expression, decorator, index in reversed(decorators):
        candidates = [identity for identity in applications
                      if tuple(u.value for u in operations[identity].uses[:-1]) == (decorator, current)]
        _need(len(candidates) == 1, "decorator chain did not consume this original decorator and preceding NORMAL result")
        identity = candidates[0];op, target = invoke(identity, 2, 1, memory=True)
        for use, expected_source, role, position in ((op.uses[0], expression, "decorator", index),
                                                   (op.uses[1], node, "decorated-function", 0)):
            row = uses[(identity,use.id)]
            _need(same_source(row.source, expected_source) and (row.role,row.index)==(role,position), "decorator operand source/order differs")
        _need(links[identity].source == source and links[identity].semantic_operation is None,
              "decorator application cannot substitute for the original child definition")
        result_consumers[current]=(identity,op.uses[1].id)
        stages.append(identity);current=target.arguments[0];stages.append(hold(current,node,"function"))
        _need(current not in result_holds,"factory/decorator NORMAL results must retain distinct original ValueIDs")
        result_holds[current]=stages[-1]
        boundaries.append((identity, tuple(v for _,v,_ in decorators[:index])))
    stores = [p.operation for p in overlay.protocols if p.kind is K.STORE_NAME_314 and p.source == source]
    _need(len(stores) == 1, "definition requires one final mapping name write")
    store=stores[0];write,_=invoke(store,3,0,memory=False)
    _need(write.uses[0].value==locals_namespace and write.uses[2].value==current,
          "STORE_NAME must consume the final decorated reference and original locals mapping")
    assigned=uses.get((store,write.uses[2].id))
    _need(assigned is not None and assigned.source==source
          and (assigned.role,assigned.index)==("assigned-reference",0),
          "STORE_NAME must retain the exact final assigned-reference source Use")
    result_consumers[current]=(store,write.uses[2].id)
    key=values[write.uses[1].value].origin
    _need(type(key) is LiteralOrigin and type(key.value) is str and key.value==node.name, "STORE_NAME key differs from original definition")
    addresses=[r for r in graph.state_address_refinements if r.site.operation==store]
    _need(len(addresses)==1 and addresses[0].site==InvokeStateOperand(store,write.uses[-1].id)
          and addresses[0].coverage is AddressCoverage.PARTIAL and addresses[0].protocol is None
          and addresses[0].effects==(AddressEffect(ReferenceOwner(write.uses[0].id),(NamespaceKey(write.uses[1].id),),AccessMode.WRITE),),
          "function binding lost its exact incomplete mapping address")
    stages.append(store);boundaries.append((store,()))
    for value,held in result_holds.items():
        # A produced function is retained once, then consumed by the next
        # decorator CALL (or the final STORE_NAME) on both outcomes. Do not
        # skip normal-arm lifetime checks merely because the earlier hold is
        # legal: any extra downstream hold/release/forwarding is a stale use.
        expected={(held,operations[held].uses[0].id),result_consumers[value]}
        actual=[(op.id,use.id)for op in graph.operations for use in op.uses if use.value==value]
        _need(len(actual)==2 and set(actual)==expected,
              "factory/decorator result must have only its original hold and next consuming Use")
    _need(len(stages)==len(set(stages)), "definition stages reused an operation/hold")
    own=set(stages)
    for first,second in zip(stages,stages[1:]):
        _next_stage(first,second,own,operations,blocks,positions)
        earlier=operations[first]
        if earlier.terminator is not None:
            post=blocks[earlier.terminator.successors[0].block].arguments[-1]
        else:
            _need(len(earlier.accesses)==1 and earlier.accesses[0].after is not None,
                  "temporary hold has no actual post-world")
            post=earlier.accesses[0].after
        _need(_world_after(operations[second].uses[-1].value,post,values,operations,blocks),
              "later definition stage bypassed the preceding actual normal post-world")
    prefix=None
    for identity,expected in boundaries:
        released,retained=_failure_holds(operations[identity].terminator.successors[1].block,
            operations,protocols,blocks,uses,{r.operation for r in graph.cleanup_enters},source,values)
        if paired:
            _need(released==tuple(reversed(expected)),
                  "local exception unwind released different/reordered decorators or ambient references")
            outer=retained
        else:
            _need(not released and retained is not None
                  and (not expected or len(retained)>=len(expected) and retained[-len(expected):]==expected),
                  "failed definition stage lost or reordered its pending decorators")
            outer=retained[:-len(expected)] if expected else retained
        if outer is not None:
            if prefix is None:prefix=outer
            _need(outer==prefix, "factory/decorator/store failure changed the enclosing pending prefix")
    return {make,*applications,store}


def _next_stage(first, expected, own, operations, blocks, positions):
    op=operations[first];block,index=positions[first]
    pending=[(op.terminator.successors[0].block,0)] if op.terminator is not None else [(block,index+1)]
    seen=set();found=set()
    while pending:
        position=pending.pop()
        if position in seen:continue
        seen.add(position)
        _need(len(seen)<=len(operations)*2+1, "normal staging traversal exceeded graph")
        block,index=position;_need(index<len(blocks[block].operations), "normal stage falls out of block")
        identity=blocks[block].operations[index]
        if identity in own:found.add(identity);continue
        term=operations[identity].terminator
        if term is None:pending.append((block,index+1))
        elif term.kind is TerminatorKind.INVOKE:pending.append((term.successors[0].block,0))
        elif term.kind in (TerminatorKind.JUMP,TerminatorKind.BRANCH):pending.extend((e.block,0)for e in term.successors)
        else:_need(False,"normal path skips a later definition stage")
    _need(found=={expected}, "definition evaluation/application/write order changed")


def _failure_holds(block,operations,protocols,blocks,use_links,cleanup_enters,source,values):
    """Inspect actual releases before the existing frame close/cleanup entry."""
    seen=set();cursor=(block,0);released=[];post=blocks[block].arguments[-1]
    while cursor not in seen:
        seen.add(cursor);block,index=cursor
        _need(index<len(blocks[block].operations), "failure falls out of its actual unwind corridor")
        op=operations[blocks[block].operations[index]];p=protocols.get(op.id)
        local=[u for u in op.uses if (row:=use_links.get((op.id,u.id))) is not None
               and row.role=="mapping-function-exception-unwind"]
        if local:
            _need(p is not None and p.kind is P.FRAME_RELEASE_TEMPORARY and p.source==source
                  and len(local)==1 and len(op.uses)==2 and op.uses[0]==local[0]
                  and type(values[local[0].value]) is ReferenceValue
                  and use_links[(op.id,local[0].id)].source==source
                  and use_links[(op.id,local[0].id)].index==0
                  and op.terminator is None and not op.effects_complete
                  and len(op.accesses)==1 and op.accesses[0].mode is AccessMode.READ_WRITE
                  and op.accesses[0].before==op.uses[-1].id and op.accesses[0].after is not None,
                  "local exception release lost its exact reference Use/source/post-world")
            _need(_world_after(op.uses[-1].value,post,values,operations,blocks),
                  "local exception release bypassed the preceding actual raise post-world")
            post=op.accesses[0].after
            released.append(local[0].value)
        if op.id in cleanup_enters:
            _need(op.uses and _world_after(op.uses[-1].value,post,values,operations,blocks),
                  "outer cleanup entry lost the actual local-unwind world")
            return tuple(released),None
        if p is not None and p.kind in (P.FRAME_EXIT,K.FRAME_EXIT_EXCEPTION_PACKET):
            _need(op.uses and _world_after(op.uses[-1].value,post,values,operations,blocks),
                  "frame close lost the actual local-unwind world")
            tail=[operations[i]for i in blocks[block].operations[index+1:]]
            _need(len(tail)==1 and tail[0].terminator is not None and tail[0].terminator.kind is TerminatorKind.RAISE,
                  "definition failure must close the current frame before its real RAISE")
            retained=tuple(u.value for u in op.uses if (row:=use_links.get((op.id,u.id))) is not None and row.role=="held-temporary")
            return tuple(released),retained
        term=op.terminator
        if term is None:cursor=(block,index+1)
        elif term.kind in (TerminatorKind.JUMP,TerminatorKind.PENDING_DISPATCH,TerminatorKind.CLEANUP_ROUTE) and len(term.successors)==1:
            cursor=(term.successors[0].block,0)
        else:_need(False,"definition failure does not follow its original unambiguous frame close")
    _need(False,"definition failure corridor cycles")


def _world_after(value,ancestor,values,operations,blocks,seen=frozenset()):
    """Follow only actual state access/CFG operands, never names or shapes."""
    if value==ancestor:return True
    if value in seen or type(values[value]) is not StateVersionValue:return False
    origin=values[value].origin;before=[]
    if type(origin) is OperationResult:
        op=operations[origin.operation];own={u.id:u.value for u in op.uses}
        before=[own[a.before]for a in op.accesses if a.after==value and a.before in own]
    elif type(origin) is BlockArgument:
        for op in operations.values():
            for edge in getattr(op.terminator,"successors",()):
                if edge.block!=origin.block:continue
                argument=edge.arguments[origin.index]
                if type(argument) is CompletionResult:
                    signatures=[s for s in op.completions if s.kind is edge.kind]
                    if (len(signatures)!=1 or argument.index!=len(signatures[0].types)-1
                            or value_type(values[value])!=signatures[0].types[argument.index]):return False
                    before.extend(u.value for u in op.uses if type(values[u.value]) is StateVersionValue)
                else:
                    own={u.id:u.value for u in op.uses}
                    if argument not in own:return False
                    before.append(own[argument])
    return bool(before) and all(_world_after(v,ancestor,values,operations,blocks,seen|{value})for v in before)


__all__=["validate_mapping_function"]
