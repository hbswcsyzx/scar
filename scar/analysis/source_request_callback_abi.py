"""Read a deferred request ABI from its actual sealed declaration and region.

These inputs are region parameters, not ordinary Python function formals.
No format value, callable creator, globals or cell binding is selected here.
"""
from scar.analysis.source_annotation_code_bridge import _recipe_reference
from scar.analysis.source_namespace_interfaces import NamespacePlanView
from scar.ir.program import normal_graph as G, source_productions as P
from scar.ir.program.control import LanguageCompletionKind as C
from scar.ir.program.model import ValueKind, ValueType
from scar.ir.program.source_observed_codes import ObservedSourceRequestCodeLink, ObservedSourceRequestKind


def request_callback_abi(view, request):
    """Return the original (env, format, world), (value, world) graph ports."""
    if type(request) is not ObservedSourceRequestCodeLink:
        raise TypeError('request callback ABI requires its independent code correspondence')
    body = request.body; source = view.unit(body.unit); material = source.material
    node = material.interfaces['nodes'][body.template]
    if node.origin.plan_sha256 != request.plan_sha256:
        raise ValueError('request callback declaration belongs to another sealed plan')
    plan = material.plans((body.template,))[body.template]
    context = NamespacePlanView(body.unit, plan)
    declarations = {
        ObservedSourceRequestKind.FUNCTION_ANNOTATIONS:P.BuildFunctionAnnotations,
        ObservedSourceRequestKind.CLASS_ANNOTATIONS:P.BuildClassAnnotations,
        ObservedSourceRequestKind.MODULE_ANNOTATIONS:P.BuildScopeAnnotations,
    }
    candidates = [(i, step) for i, step in enumerate(plan.steps) if step.id == request.declaration_step]
    if len(candidates) != 1:
        raise ValueError('request callback lost its original declaration step')
    index, declaration = candidates[0]; instruction = declaration.instruction
    if (type(instruction) is not declarations[request.kind] or instruction.body != body.region
            or instruction.annotations.scope != request.scope.source_scope
            or context.result(declaration) != request.callable
            or _recipe_reference(material, body.template, index) != request.declaration):
        raise ValueError('request callback differs from its real sealed recipe declaration')
    region = context.regions[body.region]
    if (region.kind is not P.ProductionRegionKind.DEFERRED or not region.steps
            or context.owner(region.id) != request.scope):
        raise ValueError('request callback requires its original deferred region and code scope')
    first = context.steps[region.steps[0]]
    parameters = tuple(P.ProductionParameter(region.id, i) for i in range(3))
    reference = ValueType(ValueKind.REFERENCE); world = request.environment.world
    if (type(world) is not ValueType or world.kind is not ValueKind.STATE
            or region.parameters != (reference, reference, world)
            or type(first.instruction) is not P.EnterEvaluationRequest
            or first.instruction.environment != request.environment
            or request.environment.scope != request.scope.source_scope
            or first.arguments != parameters or len(first.completions) != 1
            or first.completions[0].kind is not C.FALLTHROUGH
            or first.completions[0].types != (world,)):
        raise ValueError('request callback original environment/format/world entry ABI differs')
    returns = [completion for completion in region.completions if completion.kind is C.RETURN]
    if len(returns) != 1 or returns[0].target is not None or returns[0].types != (reference, world):
        raise ValueError('request callback requires its original value/world RETURN completion')
    inputs = tuple(context.value(parameter) for parameter in parameters)
    outputs = tuple(context.gp(context.emitter.port(region.id, G.PortKind.RESULT, i, returns[0]))
        for i in range(2))
    return inputs, outputs[0], outputs[1]
