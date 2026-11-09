"""Project retained values using original callback interfaces and ports."""
from scar.ir.program import source_productions as P, normal_graph as G
from scar.ir.program.control import LanguageCompletionKind as Completion
from scar.ir.program.model import ValueKind, ValueType
from scar.ir.program.source_environment_values import ClassTypeParameterProjection
from scar.ir.program.ids import UseID
from scar.ir.program.dependencies import (
    DependencyPoint as Point, DependencyCondition as Condition,
    DependencyKind as Kind, DependencyMeaning as Meaning)


def identify_class_type_parameters(source, context, step, operation):
    if type(step.instruction) is not P.ReadClassTypeParameters:
        return None
    interface=step.instruction.interface
    if (context.steps.get(step.id)!=step or interface.type_parameters is None
            or context.owner(step.region).source_scope!=interface.scope):
        raise ValueError('class type tuple projection lost its original callback selector/scope')
    reference=ValueType(ValueKind.REFERENCE)
    arguments=tuple(context.emitter.value(v)[1] for v in step.arguments)
    if (len(arguments)!=2 or arguments[0]!=reference
            or type(arguments[1]) is not ValueType or arguments[1].kind is not ValueKind.STATE
            or len(step.completions)!=1 or step.completions[0].kind is not Completion.FALLTHROUGH
            or step.completions[0].types!=(reference,arguments[1])):
        raise ValueError('class type tuple environment/result/world ABI differs')
    use=source.port(context.emitter.port(step.id,G.PortKind.ARGUMENT,0))
    if type(use.node) is not UseID:
        raise TypeError('class callback environment needs its original owned Use')
    before,after=context.worlds(step)
    return ClassTypeParameterProjection(operation,interface,context.value(step.arguments[0]),
        use.node,context.result(step,0),before,after)


def attach_class_type_parameters(state, projection):
    """Attach dependence only; no physical slot, alias or purity is inferred."""
    operation=Point(state.namespace,projection.operation,None)
    environment=state.view.source_port(projection.environment)
    result=state.view.source_port(projection.result)
    owned=Point(state.namespace,projection.environment_use,None)
    selected=Condition('scar.source-environment.value',
        'CURRENT_ACTIVATION_USES_SELECTED_CLASS_CALLBACK_ENVIRONMENT',operation,None,(environment,owned))
    state._edge(owned,result,Kind.PROJECTION,Meaning.DEPENDENCE,(selected,),
        'scar.source-environment.class-type-parameter-tuple.v1')
