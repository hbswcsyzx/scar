"""Shared SEND / suspension loops from the fixed CPython source compiler.

Native SEND classifies item vs final value. A delegated temporal boundary
declares its iterator explicitly; throw/close processing is driver-side and
is not fabricated as ordinary Python calls inside this body. Its post-driver
StopIteration completes the expression; other errors remain exceptional.
"""
from scar.analysis.source_expression_rules import _REF, _require
from scar.analysis.source_suspension_rules import emit_suspension
from scar.ir.program import source_productions as P
from scar.ir.program.control import LanguageCompletionKind as C
from scar.ir.program.structured import PythonProtocolKind as K


def emit_delegation(b, root, state):
    context = b.rules.source.context.entry_context(b.occurrence)
    owner = context.owner
    syntax = b.rules.source.context.syntax
    constructor = syntax.nodes[owner.occurrence].constructor
    awaiting = b.node.constructor == 'Await'
    allowed = ((owner.kind == 'FUNCTION_BODY' and constructor == 'AsyncFunctionDef')
        or owner.kind in ('COMPREHENSION', 'GENERATOR_EXPRESSION')) if awaiting else (
        owner.kind in ('FUNCTION_BODY', 'LAMBDA_BODY') and constructor in ('FunctionDef', 'Lambda'))
    _require(allowed, 'SUSPENSION_CONTEXT_FRONTIER', str(b.occurrence),
        'delegation requires an original compiler-accepted resumable execution owner')
    b.mark('value', P.ProductionDispositionKind.EVALUATED_CHILD)
    value, state = b.evaluate(root, b.site('value'), state)
    delegate, state = b.delegation(root, P.DelegationProtocolKind.AWAITABLE_ITER if awaiting
        else P.DelegationProtocolKind.YIELD_FROM_ITER, (value,), state)
    initial, state = b.literal(root, None, state)
    # Only a real pending send value is carried. There is no fake iterator item
    # before the first SEND; its initial request is exactly None.
    loop = b.region(root.source, (_REF, _REF, b.world), root, P.ProductionRegionKind.LOOP)
    result = b.emit(root, P.ApplyRegion(P.ProductionRegionCall(loop.id, (delegate, initial, state))), (), (_REF, b.world))
    b.finish(root, result, (_REF, b.world))
    body = b.region(root.source, loop.parameters, loop, P.ProductionRegionKind.LOOP_BODY)
    b.emit(loop, P.LoopControl(P.RepeatCondition(), body.id, invariant_count=1),
        tuple(b.parameter(loop, i) for i in range(3)), (_REF, b.world))
    delegate, pending, current = (b.parameter(body, i) for i in range(3))
    done, value, current = b.delegation(body, P.DelegationProtocolKind.SEND, (delegate, pending), current)
    completed = b.region(root.source, (_REF, b.world), body)
    b.transfer(completed, C.BREAK, tuple(b.parameter(completed, i) for i in range(2)), (_REF, b.world), loop.id)
    yielded = b.region(root.source, (_REF, _REF, b.world), body)
    # No catching SEND's own errors here: SEND has already distinguished its
    # normal PYGEN_RETURN from PYGEN_NEXT. CLEANUP_THROW handles only the
    # delegated suspension's post-driver exception path.
    outputs = (P.ProductionCompletion(C.FALLTHROUGH, (_REF, b.world)),
        P.ProductionCompletion(C.RAISE, b.raised), P.ProductionCompletion(C.BREAK, (_REF, b.world), loop.id))
    b.control(body, P.BranchControl(P.ProductionRegionCall(completed.id, (value, current)),
        P.ProductionRegionCall(yielded.id, (delegate, value, current))), (done,), outputs)
    protected = b.region(root.source, yielded.parameters, yielded)
    delegate, value, current = (b.parameter(protected, i) for i in range(3))
    kind = P.SuspensionKind.AWAIT if awaiting else P.SuspensionKind.YIELD_FROM
    resumed = emit_suspension(b, protected, kind, value, current, delegate=delegate)
    b.finish(protected, resumed, (_REF, b.world))
    handler = b.region(root.source, b.raised, yielded, P.ProductionRegionKind.HANDLER)
    exception, current = b.parameter(handler, 0), b.parameter(handler, len(b.raised)-1)
    exhausted, = b.protocol(handler, K.MATCH_STOP_ITERATION, (exception,), current)
    finished = b.region(root.source, b.raised, handler)
    current = b.parameter(finished, len(b.raised)-1)
    result, = b.delegation(finished, P.DelegationProtocolKind.STOP_ITERATION_VALUE,
        (b.parameter(finished, 0),), current)
    b.transfer(finished, C.BREAK, (result, current), (_REF, b.world), loop.id)
    failed = b.region(root.source, b.raised, handler)
    b.transfer(failed, C.RAISE, tuple(b.parameter(failed, i) for i in range(len(b.raised))), b.raised)
    values = tuple(b.parameter(handler, i) for i in range(len(b.raised)))
    handler_outputs = (outputs[1], outputs[2])
    b.control(handler, P.BranchControl(P.ProductionRegionCall(finished.id, values),
        P.ProductionRegionCall(failed.id, values)), (exhausted,), handler_outputs)
    b.control(yielded, P.HandleCompletions(P.ProductionRegionCall(protected.id,
        tuple(b.parameter(yielded, i) for i in range(3))), (P.CompletionRoute(C.RAISE, None, handler.id),)), (), outputs)
