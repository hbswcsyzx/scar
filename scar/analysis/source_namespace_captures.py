"""Extract actual globals operands from original function-creation steps.

These are source relations, not bindings of a scope to an exec dictionary.
Decorators and later callable/environment selection retain their own edges.
"""
from scar.ir.program import source_productions as P, source_namespaces as N
from scar.ir.program.structured import PythonProtocolKind as K


_FACTORIES = frozenset((K.MAKE_LAMBDA_FUNCTION,K.MAKE_GENEXPR_FUNCTION,K.MAKE_NESTED_FUNCTION))


def extract_captures(view) -> tuple[tuple[N.GlobalsEnvironmentReference, ...],
        tuple[N.FunctionGlobalsCapture, ...], tuple[N.NamespaceGraphObligation, ...]]:
    """Return globals references, function captures, and unresolved factories.

    ``view`` resolves only original plan ports and compilation-scope witnesses.
    A factory's code operand must name its local DeferRegion result. Otherwise
    retain an obligation instead of guessing from a scope or source spelling.
    """
    references,captures,obligations = [],[],[]
    for step in view.plan.steps:
        instruction = step.instruction
        if type(instruction) is P.ReferenceEnvironment:
            if type(instruction.source) is P.GlobalsEnvironment:
                world_in,world_out = view.worlds(step)
                references.append(N.GlobalsEnvironmentReference(view.site(step),view.owner(step.region),
                    instruction.source.scope,view.result(step),world_in,world_out))
            continue
        factory = (type(instruction) is P.BuildFunction or
            type(instruction) is P.ApplyPythonProtocol and instruction.protocol in _FACTORIES)
        if not factory:
            continue

        def unresolved(reason):
            obligations.append(N.NamespaceGraphObligation(view.site(step),reason))

        # The existing factory ABI is code, globals, remaining references,
        # world. Neither globals nor the code is the callable result itself.
        if len(step.arguments) < 3:
            unresolved('FUNCTION_GLOBALS_FACTORY_ARGUMENTS_UNRESOLVED')
            continue
        code = step.arguments[0]
        if type(code) is not P.ProductionResult or code.index != 0:
            unresolved('FUNCTION_GLOBALS_CODE_DECLARATION_UNRESOLVED')
            continue
        declaration_step = view.steps.get(code.step)
        if declaration_step is None or type(declaration_step.instruction) is not P.DeferRegion:
            unresolved('FUNCTION_GLOBALS_CODE_DECLARATION_UNRESOLVED')
            continue
        declaration = declaration_step.instruction
        if type(instruction) is P.BuildFunction and instruction.environment != declaration.environment:
            unresolved('FUNCTION_GLOBALS_DECLARATION_ENVIRONMENT_MISMATCH')
            continue
        scope = declaration.environment.globals_scope
        if type(scope) is not int or scope < 0:
            unresolved('FUNCTION_GLOBALS_DECLARATION_SCOPE_UNRESOLVED')
            continue
        try:
            body = view.owner(declaration.body)
        except KeyError:
            unresolved('FUNCTION_GLOBALS_BODY_OWNER_UNRESOLVED')
            continue
        world_in,world_out = view.worlds(step)
        captures.append(N.FunctionGlobalsCapture(view.site(step),view.owner(step.region),
            view.result(step),view.value(code),view.value(step.arguments[1]),body,scope,world_in,world_out))
    return tuple(references),tuple(captures),tuple(obligations)
