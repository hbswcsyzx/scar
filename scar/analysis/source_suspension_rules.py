"""Source yield boundaries, before driver admission and canonical lowering.

These local templates do not claim that a generator is ever driven/resumed.
Caller stack, frame/exception context and escaping cell retention are later
composition obligations, not fabricated captures in an isolated expression.
"""
from scar.analysis.source_expression_rules import _REF, _require
from scar.ir.program import source_productions as P
from scar.ir.program.control import LanguageCompletionKind as C


def emit_yield(b, root, state):
    context = b.rules.source.context.entry_context(b.occurrence)
    owner = context.owner
    syntax = b.rules.source.context.syntax
    constructor = syntax.nodes[owner.occurrence].constructor
    _require(owner.kind in ('FUNCTION_BODY', 'LAMBDA_BODY')
        and constructor in ('FunctionDef', 'AsyncFunctionDef', 'Lambda'),
        'SUSPENSION_CONTEXT_FRONTIER', str(b.occurrence),
        'yield requires an original function/lambda execution owner')
    kind = P.SuspensionKind.ASYNC_YIELD if constructor == 'AsyncFunctionDef' else P.SuspensionKind.YIELD
    site = b.site('value')
    operand = b.value(site)
    if operand.kind == 'NODE':
        b.mark('value', P.ProductionDispositionKind.EVALUATED_CHILD)
        value, state = b.evaluate(root, site, state)
    else:
        _require(operand.kind == 'SCALAR' and operand.scalar.to_python() is None,
            'RULE_SHAPE', str(site), 'bare yield requires an explicit None field')
        value, state = b.literal(root, None, state, site)
    result = emit_suspension(b, root, kind, value, state)
    b.finish(root, result, (_REF, b.world))


def emit_suspension(b, root, kind, value, state, *, delegate=None):
    """A temporal ingress, with driver processing explicit for delegation."""
    sent = b.region(root.source, (_REF, b.world), root, P.ProductionRegionKind.RESUME)
    b.finish(sent, tuple(b.parameter(sent, i) for i in range(2)), (_REF, b.world))
    thrown = b.region(root.source, b.raised, root, P.ProductionRegionKind.RESUME)
    b.transfer(thrown, C.RAISE, tuple(b.parameter(thrown, i) for i in range(len(b.raised))), b.raised)
    return b.emit(root, P.SuspendExecution(kind, b.rules.exception_abi, (
        P.ProductionResumeRoute(C.FALLTHROUGH, sent.id),
        P.ProductionResumeRoute(C.RAISE, thrown.id)), delegate=delegate), (value, state), (_REF, b.world))
