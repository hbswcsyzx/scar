"""Independent port/order/lifetime checks for source-compiled annotations."""
from __future__ import annotations

from scar.ir.program.module_entries import ModuleAnnotationMode as Mode, FrameBodyProtocolKind as K
from scar.ir.program.structured import PythonProtocolKind as P
from scar.ir.program.model import LiteralOrigin, StateVersionValue, ReferenceValue, Behavior, ExitKind
from scar.ir.program.state_addresses import (
    InvokeStateOperand,ReferenceOwner,AddressCoverage,Element,WholeOwner,
)


def _need(condition,detail):
    if not condition:raise ValueError('module annotation: '+detail)


def empty_dict_result(node,plan,*,source_reference,overlay,protocols,operations,invoke,ref_type,state_type):
    source=source_reference(node)
    matches=[operations[p.operation] for p in overlay.protocols if p.kind is P.BUILD_MAP and p.source==source]
    _need(plan.empty_dict is not None and len(matches)==1,'empty RHS must have its exact BUILD_MAP 0 allocation')
    operation=matches[0]
    _need(len(operation.uses)==1 and operation.callee is None,'empty dict cannot use children or a fixed target')
    normal,_=invoke(operation,(ref_type,state_type),memory=True)
    return normal.arguments[0]


def validate_module_annotation(node,expansion,plan,*,overlay,blocks,operations,values,protocols,
        expression_value,invoke,source_reference,normal_path,exception_holds,namespace_refs,
        ref_type,state_type,refinements):
    """Replay only the original annotation stages over canonical graph ports."""
    _need(expansion.compiler_annotation==plan.witness,'source/compiler statement receipt differs')
    path=normal_path(expansion,blocks,operations)
    _need(bool(path),'annotation has no normal corridor')
    use_links={(row.operation,row.use):row for row in overlay.use_links}
    local_refs=[];failure_checks=[]
    def kind(op):
        marker=protocols.get(op.id)
        return marker.kind if marker else None
    def literal(value,expected):
        record=values[value]
        _need(type(record.origin) is LiteralOrigin and type(record.origin.value) is type(expected)
              and record.origin.value==expected,'compiler literal/index changed')
    def consumed_on_failure(block,expected):
        failure_checks.append((block,tuple(expected)))
    def transition(op,before):
        _need(op.terminator is None and len(op.uses)==2 and len(op.accesses)==1
              and set(op.behaviors)=={Behavior.READ,Behavior.WRITE,Behavior.MEMORY}
              and not op.effects_complete and op.callee is None
              and op.uses[-1].value==before and op.accesses[0].before==op.uses[-1].id
              and op.accesses[0].mode.value=='READ_WRITE' and not op.accesses[0].full_overwrite
              and op.accesses[0].after is not None and op.results==(op.accesses[0].after,)
              and type(values[op.results[0]]) is StateVersionValue,
              'temporary transition changed its incoming/post world')
        return op.results[0]
    # Recover the current state at this exact statement entry, including
    # preceding frame transitions in the same canonical block.
    state=blocks[expansion.entry].arguments[-1]
    for identity in blocks[expansion.entry].operations:
        if identity==path[0].id:break
        for result in operations[identity].results:
            if type(values[result]) is StateVersionValue:state=result
    for operation in path:
        worlds=[use.value for use in operation.uses if type(values[use.value]) is StateVersionValue]
        _need(worlds and all(world==state for world in worlds),'normal corridor bypassed its preceding world')
        if operation.terminator is not None:
            edge=next(edge for edge in operation.terminator.successors if edge.kind is ExitKind.NORMAL)
            state=blocks[edge.block].arguments[-1]
        else:
            states=[result for result in operation.results if type(values[result]) is StateVersionValue]
            if states:
                _need(len(states)==1,'annotation normal action has multiple unmodeled post-worlds')
                state=states[0]
    start=0
    if node.value is not None:
        stores=[op for op in path if kind(op) in (K.STORE_NAME_314,P.STORE_GLOBAL)
                and protocols[op.id].source==source_reference(node.target)]
        _need(len(stores)==1,'RHS must feed exactly its original namespace store')
        store=stores[0]
        _need(store.uses[2].value==expression_value(node.value),'RHS did not feed its namespace store')
        start=path.index(store)+1
    macro=path[start:];position=0;held=[]
    def take(expected):
        nonlocal position
        _need(position<len(macro),'annotation stages ended early')
        operation=macro[position];position+=1
        _need(kind(operation) is expected,'annotation stages are reordered or contain an extra action')
        return operation
    def constant(instruction,source):
        operation=take(P.READ_CODE_CONSTANT)
        constants=[row for row in overlay.constants if row.operation==operation.id]
        _need(len(constants)==1 and constants[0].source==source
              and constants[0].constant_path==(instruction.arg,)
              and constants[0].code_key==plan.witness.root_code_layout_key,
              'annotation reference lost its exact original code constant slot')
        _need(len(operation.results)==1,'compiler constant has no unique reference result')
        _need(operation.terminator is None and operation.callee is None and not operation.effects_complete
              and set(operation.behaviors)=={Behavior.READ} and len(operation.uses)==1
              and len(operation.accesses)==1 and operation.accesses[0].before==operation.uses[0].id
              and operation.accesses[0].mode.value=='READ' and operation.accesses[0].after is None
              and type(values[operation.results[0]]) is ReferenceValue,
              'annotation constant must read the original code-slot reference without fabricating an invoke')
        return operation.results[0]
    def hold(reference,role):
        operation=take(P.FRAME_HOLD_TEMPORARY)
        row=use_links.get((operation.id,operation.uses[0].id)) if operation.uses else None
        _need(operation.uses[0].value==reference and protocols[operation.id].source==expansion.source
              and row is not None and row.role==role,'annotation temporary owner/role changed')
        transition(operation,operation.uses[-1].value);held.append(reference)
    def lookup(expected_holds):
        operation=take(K.LOAD_NAME_314)
        _need(protocols[operation.id].source==expansion.source and len(operation.uses)==5
              and tuple(use.value for use in operation.uses[:3])==tuple(namespace_refs),
              'implicit annotation lookup lost actual L/G/savedB ports')
        literal(operation.uses[3].value,plan.lookup.argval)
        normal,failure=invoke(operation,(ref_type,state_type))
        consumed_on_failure(failure.id,expected_holds)
        reference=normal.arguments[0];local_refs.append(reference)
        return reference
    def update(operation,expected_inputs,expected_holds):
        _need(protocols[operation.id].source==expansion.source
              and tuple(use.value for use in operation.uses[:-1])==tuple(expected_inputs)
              and operation.callee is None,'annotation update changed its actual operand references')
        _,failure=invoke(operation,(state_type,),memory=True)
        consumed_on_failure(failure.id,expected_holds)
        refinement=refinements.get(operation.id)
        _need(refinement is not None and type(refinement.site) is InvokeStateOperand
              and refinement.site.state_use==operation.uses[-1].id
              and refinement.coverage is AddressCoverage.PARTIAL and len(refinement.effects)==1,
              'annotation update needs its partial attempted address on the actual invoke state')
        effect=refinement.effects[0]
        _need(type(effect.owner) is ReferenceOwner and effect.owner.use==operation.uses[0].id
              and len(effect.path)==1,'annotation update changed its actual attempted owner')
        return effect
    if plan.witness.mode is Mode.LAZY_SET:
        owner=lookup(())
        hold(owner,'annotation-set-owner')
        if plan.value.opname=='LOAD_CONST':index=constant(plan.value,expansion.source)
        else:
            operation=macro[position]
            _need(kind(operation) is K.SET_ADD_314 and len(operation.uses)==3,
                  'annotation integer must feed its original SET_ADD')
            index=operation.uses[1].value;literal(index,plan.value.argval)
        operation=take(K.SET_ADD_314)
        effect=update(operation,(owner,index),(owner,))
        _need(type(effect.path[0]) is WholeOwner and effect.mode.value=='READ_WRITE',
              'set insertion is a whole-set partial update, not indexed storage')
        release=take(P.FRAME_RELEASE_TEMPORARY)
        row=use_links.get((release.id,release.uses[0].id)) if release.uses else None
        _need(release.uses[0].value==owner and row is not None and row.role=='annotation-set-owner'
              and protocols[release.id].source==expansion.source,'annotation POP_TOP lost its retained set owner')
        transition(release,release.uses[-1].value);held.pop()
    else:
        annotation=constant(plan.value,source_reference(node.annotation));local_refs.append(annotation)
        hold(annotation,'annotation-string')
        owner=lookup((annotation,));hold(owner,'annotation-mapping-owner')
        key=constant(plan.key,expansion.source)
        operation=take(P.STORE_SUBSCRIPT)
        effect=update(operation,(owner,key,annotation),())
        _need(type(effect.path[0]) is Element and effect.path[0].index==operation.uses[1].id
              and effect.mode.value=='WRITE','annotation STORE_SUBSCR key/write address changed')
        held.clear()  # The original STORE_SUBSCR consumes all three inputs on both outcomes.
    _need(position==len(macro) and not held,'annotation stages leaked a temporary or added a runtime action')
    for block,expected in failure_checks:
        actual=exception_holds(block,operations,protocols,blocks,use_links)
        _need(tuple(reference for reference in actual if reference in local_refs)==expected,
              'annotation exceptional handoff changed pending/consumed reference cleanup')
