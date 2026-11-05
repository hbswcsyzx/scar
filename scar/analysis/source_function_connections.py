"""Connect conditional source function entries without inventing call ports.

Invocation points belong to the existing solver. Argument admission is planned
before any reference propagation; unknown packs and deferred creation retain
interfaces without executing a shared body. World/environment routes remain
typed interface connections rather than reference-value aliases.
"""
from dataclasses import dataclass

from scar.ir.program import normal_targets as T, source_productions as P


@dataclass(frozen=True, slots=True)
class Invocation:
    callee: int
    positional: tuple[int, ...]
    keywords: tuple[tuple[str, int], ...]
    result: int | None
    world: int
    result_world: int
    positional_pack: int | None = None
    keyword_pack: int | None = None


def connect(solver, fid: int, invocation: Invocation, receiver: int | None = None, *,
            class_receiver: int | None = None, environment_source: int | None = None,
            return_value: bool = True, conditions: tuple[str, ...] = ()) -> T.FunctionConnection | None:
    """Return a shared-body connection after admitting the complete signature.

    NORMAL activations propagate ordinary/default reference arguments and the
    Python data result. Class receivers use the existing class projection;
    packs retain ordered dependencies, never a pack-to-formal reference edge.
    State input/output uses Route/returns, matching the original call binder.
    """
    unit, function = solver.functions[fid]
    offset = solver.offsets[unit.unit]
    params = function.environment.parameters
    if (len(params) != len(function.parameter_names)
            or len(params) != len(function.defaults)
            or len(function.formals) != len(params) + 2):
        return None
    gp = solver.gp
    environment_source = invocation.callee if environment_source is None else environment_source
    conditions = ('SOURCE_STATIC_CANDIDATE', 'CURRENT_CALLABLE_DESCRIPTOR',
                  'STANDARD_MODULE_NAMESPACES', *conditions)
    activation = (T.FunctionActivation.NORMAL
                  if function.environment.kind is P.DeferredBodyKind.FUNCTION
                  else T.FunctionActivation.CREATE_DEFERRED_BODY)
    environment = T.Route(gp(offset + function.formals[0]), T.RouteKind.FUNCTION_ENVIRONMENT,
                          (gp(environment_source),))
    state = T.Route(gp(offset + function.formals[-1]), T.RouteKind.STATE, (gp(invocation.world),))
    body = T.Body(unit.unit, function.template, function.body)
    keywords = dict(invocation.keywords)
    if len(keywords) != len(invocation.keywords):
        return None
    if invocation.positional_pack is not None or invocation.keyword_pack is not None:
        if hasattr(solver,'body_demand'):solver.body_demand(fid,invocation.callee,'ARGUMENT_PACK_BINDING_OPEN')
        packs = T.ArgumentPacks(
            None if invocation.positional_pack is None else gp(invocation.positional_pack),
            None if invocation.keyword_pack is None else gp(invocation.keyword_pack),
            None if receiver is None else gp(receiver),
            None if class_receiver is None else gp(class_receiver))
        return T.FunctionConnection(gp(fid), body, activation, (environment, state), (),
            (*conditions, 'ARGUMENT_PACK_BINDING_PENDING'), packs)

    positional = list(invocation.positional)
    positional_kinds = (P.DeferredParameterKind.POSITIONAL_ONLY,
                        P.DeferredParameterKind.POSITIONAL_OR_KEYWORD,
                        P.DeferredParameterKind.INITIAL_ITERATOR)
    project_class = class_receiver is not None
    if project_class:
        if not params:
            return None
        if params[0].kind is P.DeferredParameterKind.VAR_POSITIONAL:
            # The class is one dependency of the varargs tuple, not its type
            # or the identity of the whole tuple. Reuse its existing point.
            positional.insert(0, class_receiver)
            project_class = False
        elif params[0].kind not in positional_kinds:
            return None
    elif receiver is not None:
        positional.insert(0, receiver)

    routes, bindings, class_bindings = [], [], []
    position = 0
    for index, (parameter, name) in enumerate(zip(params, function.parameter_names)):
        formal = offset + function.formals[index + 1]
        kind = parameter.kind
        actuals, names, route = (), (), T.RouteKind.ARGUMENT
        if project_class and index == 0:
            if kind is P.DeferredParameterKind.POSITIONAL_OR_KEYWORD and name in keywords:
                return None
            class_bindings.append((formal, ('class', class_receiver)))
            route = T.RouteKind.CLASS_RECEIVER
            actuals = () if receiver is None else (receiver,)
        elif kind in positional_kinds and position < len(positional):
            if kind is P.DeferredParameterKind.POSITIONAL_OR_KEYWORD and name in keywords:
                return None
            actuals = (positional[position],)
            position += 1
        elif kind in (P.DeferredParameterKind.POSITIONAL_OR_KEYWORD,
                      P.DeferredParameterKind.KEYWORD_ONLY) and name in keywords:
            actuals = (keywords.pop(name),)
        elif kind is P.DeferredParameterKind.VAR_POSITIONAL:
            actuals = tuple(positional[position:])
            position = len(positional)
            route = T.RouteKind.PACK_POSITIONALS
        elif kind is P.DeferredParameterKind.VAR_KEYWORD:
            names, actuals = tuple(keywords), tuple(keywords.values())
            keywords.clear()
            route = T.RouteKind.PACK_KEYWORDS
        elif function.defaults[index] is not None:
            actuals = (offset + function.defaults[index],)
            route = T.RouteKind.INITIAL_DEFAULT
        else:
            return None
        routes.append(T.Route(gp(formal), route, tuple(gp(p) for p in actuals), names))
        if route in (T.RouteKind.ARGUMENT, T.RouteKind.INITIAL_DEFAULT):
            bindings.extend((actual, formal) for actual in actuals)
    if position < len(positional) or keywords:
        return None

    returned = []
    if activation is T.FunctionActivation.NORMAL:
        if hasattr(solver,'activate_function'):solver.activate_function(fid,invocation.callee)
        for actual, formal in bindings:
            solver.edge(actual, formal)
        for formal, value in class_bindings:
            solver.add(formal, value)
        if return_value and invocation.result is not None and function.returns is not None:
            source = offset + function.returns
            solver.edge(source, invocation.result)
            returned.append((gp(source), gp(invocation.result)))
        if function.return_world is not None:
            returned.append((gp(offset + function.return_world), gp(invocation.result_world)))
    elif hasattr(solver,'body_demand'):
        solver.body_demand(fid,invocation.callee,'DEFERRED_BODY_RESUME_OPEN')
    return T.FunctionConnection(gp(fid), body, activation, (environment, *routes, state),
                                tuple(returned), conditions)
