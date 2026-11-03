"""Module assertions retain source branches and real propagation-pair ports."""
from __future__ import annotations

import ast

from scar.ir.program.model import ExitKind, StateVersionValue, TerminatorKind, ValueKind, ValueType
from scar.ir.program.structured import PythonProtocolKind as K


def _need(condition, detail):
    if not condition:
        raise ValueError('module assertion: ' + detail)


def validate_module_assertion(node,expansion,*,context,code_evidence,profile,overlay,
        blocks,operations,values,protocols,invoke,expression_value,source_reference,
        exception_holds,ref_type,state_type):
    from scar.analysis.source_module_lowering import mapping_assertion_supported
    _need(mapping_assertion_supported(context,code_evidence,node,profile=profile),
        'the original compiler did not retain this supported assertion layout')
    source=source_reference(node)
    allowed=set(expansion.operations)
    links={row.operation:row for row in overlay.operation_links}
    use_links={(row.operation,row.use):row for row in overlay.use_links}

    def marked(kind,reference):
        rows=[operations[row.operation] for row in overlay.protocols
            if row.kind is kind and row.source==reference]
        _need(len(rows)==1 and rows[0].id in allowed,'missing/extra assertion primitive '+kind.value)
        _need(links[rows[0].id].semantic_operation is None and rows[0].callee is None,
            'assertion primitive acquired a guessed source callee')
        return rows[0]

    def corridor(start,stop):
        cursor,seen,path=start,set(),[]
        while cursor not in seen:
            seen.add(cursor)
            local=[operations[identity] for identity in blocks[cursor].operations if identity in allowed]
            _need(local,'assertion corridor escaped its original statement')
            for operation in local:
                path.append(operation)
                if operation.id==stop:
                    state=None
                    for action in path:
                        worlds=[use.value for use in action.uses if type(values[use.value]) is StateVersionValue]
                        if worlds:
                            state=worlds[0] if state is None else state
                            _need(all(value==state for value in worlds),'action bypassed preceding assertion world')
                        term=action.terminator
                        if term is not None and term.kind is TerminatorKind.INVOKE:
                            edge,=(edge for edge in term.successors if edge.kind is ExitKind.NORMAL)
                            state=blocks[edge.block].arguments[-1]
                        else:
                            states=[value for value in action.results if type(values[value]) is StateVersionValue]
                            if states:
                                _need(len(states)==1,'assertion action has ambiguous state results')
                                state=states[0]
                    return path
            term=local[-1].terminator
            edges=([edge for edge in term.successors if edge.kind is ExitKind.NORMAL]
                if term is not None and term.kind is TerminatorKind.INVOKE else list(term.successors)
                if term is not None and term.kind is TerminatorKind.JUMP else [])
            _need(len(edges)==1,'assertion corridor has no unique normal continuation')
            cursor=edges[0].block
        raise ValueError('module assertion: normal corridor cycles')

    truth=marked(K.TRUTH,source_reference(node.test))
    _need(len(truth.uses)==2 and truth.uses[0].value==expression_value(node.test),
        'test must feed exactly one truth conversion')
    truth_normal,_=invoke(truth,(ValueType(ValueKind.DATA,'builtins.bool'),state_type))
    corridor(expansion.entry,truth.id)
    branch=operations[truth_normal.operations[-1]]
    _need(branch.id in allowed and branch.terminator is not None
        and branch.terminator.kind is TerminatorKind.BRANCH and len(branch.uses)==3
        and branch.terminator.condition==branch.uses[0].id
        and branch.uses[0].value==truth_normal.arguments[0]
        and all(use.value==truth_normal.arguments[-1] for use in branch.uses[1:])
        and len(branch.terminator.successors)==2,
        'assertion lost its test-dependent branch and post-truth world')
    yes,no=branch.terminator.successors
    _need(yes.block==expansion.normal and yes.arguments==(branch.uses[1].id,)
        and no.arguments==(branch.uses[2].id,), 'assertion success/failure arms are swapped or disconnected')
    constructor=marked(K.MAKE_ASSERTION_ERROR,source)
    message=None if node.msg is None else expression_value(node.msg)
    _need(tuple(use.value for use in constructor.uses[:-1])==(() if node.msg is None else (message,)),
        'AssertionError must use exactly the failed-arm source message')
    constructed,construction_failure=invoke(constructor,(ref_type,state_type),memory=True)
    failed_path=corridor(no.block,constructor.id)
    normalizer=marked(K.FUNCTION_START_PROPAGATION,source)
    _need(len(normalizer.uses)==2 and normalizer.uses[0].value==constructed.arguments[0],
        'propagation must consume the newly constructed assertion exception')
    _,normalization_failure=invoke(normalizer,(ref_type,ref_type,state_type))
    normalized_path=corridor(constructed.id,normalizer.id)
    if node.msg is not None:
        held=[operation for operation in failed_path if operation.id in protocols
            and protocols[operation.id].kind is K.FRAME_HOLD_TEMPORARY
            and operation.uses[0].value==message
            and use_links[operation.id,operation.uses[0].id].role=='statement-held-reference']
        released=[operation for operation in normalized_path if operation.id in protocols
            and protocols[operation.id].kind is K.FRAME_RELEASE_TEMPORARY
            and operation.uses[0].value==message
            and use_links[operation.id,operation.uses[0].id].role=='statement-released-reference']
        _need(len(held)==len(released)==1,'message stack reference must be held then released exactly once')
        for block,expected in ((construction_failure.id,(message,)),(normalization_failure.id,())):
            pending=exception_holds(block,operations,protocols,blocks,use_links)
            _need(tuple(value for value in pending if value==message)==expected,
                'message retention differs between construction failure and post-release propagation')
    reachable,queue=set(),[no.block]
    while queue:
        block=queue.pop()
        _need(block!=expansion.normal,'failed assertion reached its success continuation')
        for identity in blocks[block].operations:
            if identity not in allowed or identity in reachable:
                continue
            reachable.add(identity)
            term=operations[identity].terminator
            if term is not None:
                queue.extend(edge.block for edge in term.successors
                    if any(child in allowed for child in blocks[edge.block].operations)
                    or edge.block==expansion.normal)
    if node.msg is not None:
        message_sources={source_reference(child) for child in ast.walk(node.msg) if isinstance(child,ast.expr)}
        _need(all(identity in reachable for identity in allowed if links[identity].source in message_sources),
            'message has operations outside the assertion failure arm')
