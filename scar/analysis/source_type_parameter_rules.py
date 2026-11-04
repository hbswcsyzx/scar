"""Generic factory activation and sequential type-parameter creation.

Lazy expressions are captured as original evaluator interfaces; their bodies
are not executed while creating TypeVar/TypeVarTuple/ParamSpec objects.
"""
from scar.analysis.source_expression_rules import _REF
from scar.ir.program import source_productions as P
from scar.ir.program.signature_patterns import CountBinding
from scar.ir.program.structured import PythonProtocolKind as K


def lazy_factory(b,region,expression,world):
    owner=P.ProductionOccurrence(expression.source.occurrence)
    globals_ref,world=b.environment(region,P.GlobalsEnvironment(b.rules.source.context.material.root_context.environment),world,source=owner)
    captures=[]
    for relay in expression.captures:
        capture,world=b.environment(region,P.ClosureEnvironment(relay),world,source=owner)
        captures.append(capture)
    b.slots[expression.source]=P.ProductionDispositionKind.DEFERRED_CHILD
    return b.emit(region,P.BuildLazyExpression(expression,b.rules.exception_abi),
        (globals_ref,*captures,world),(_REF,b.world),source=expression.source)


def emit_type_parameters(b,region,world,environment):
    values=[]
    for parameter in environment.parameters:
        owner=P.ProductionOccurrence(parameter.name.occurrence)
        for name in b.role.fields[b.rules.source.context.syntax.nodes[parameter.name.occurrence].constructor]:
            b.auxiliary(parameter.name.occurrence,name,P.ProductionDispositionKind.METADATA)
        b.slots[parameter.name]=P.ProductionDispositionKind.ROLE_PORT
        bound=()
        if parameter.bound is not None:
            evaluator,world=lazy_factory(b,region,parameter.bound,world)
            bound=(evaluator,)
        value,world=b.emit(region,P.CreateTypeParameter(parameter,b.rules.exception_abi),(*bound,world),(_REF,b.world),source=owner)
        if parameter.default is not None:
            evaluator,world=lazy_factory(b,region,parameter.default,world)
            world,=b.emit(region,P.SetTypeParameterDefault(parameter,b.rules.exception_abi),
                (value,evaluator,world),(b.world,),source=owner)
        world,=b.emit(region,P.BindTypeParameter(parameter,b.rules.exception_abi),(value,world),(b.world,),source=owner)
        values.append(value)
    result,world=b.protocol(region,K.BUILD_CALL_POSITIONALS,tuple(values),world,
        (CountBinding('item_count',len(values)),),selectors=(b.site('type_params'),))
    return result,world


def enter_factory(b,root,world,inputs):
    environment=b.rules.source.type_parameters.environment(b.occurrence,b.world,b.rules.exception_abi)
    captures=[]
    for relay in environment.captures:
        capture,world=b.environment(root,P.ClosureEnvironment(relay),world)
        captures.append(capture)
    arguments=(*captures,*inputs,world)
    region=b.region(b.site('type_params'),(*(_REF for _ in range(len(arguments)-1)),b.world),root,P.ProductionRegionKind.TYPE_PARAMETERS)
    result=b.emit(root,P.InvokeTypeParameterFactory(P.ProductionRegionCall(region.id,arguments),environment),(),(_REF,b.world))
    active,=b.emit(region,P.EnterTypeParameters(environment),tuple(b.parameter(region,i) for i in range(len(region.parameters))),
        (b.world,),may_raise=False)
    parameters,active=emit_type_parameters(b,region,active,environment)
    passed=tuple(b.parameter(region,len(captures)+i) for i in range(len(inputs)))
    b.mark('type_params',P.ProductionDispositionKind.DEFERRED_CHILD)
    return result,region,parameters,passed,active
