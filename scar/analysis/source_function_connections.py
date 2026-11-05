"""Connect conditional source function entries without inventing call ports.

Invocation points belong to the existing solver. Unknown packs retain symbolic
signature conditions and content projections. Ordinary source bodies may be
activated under those conditions; suspended bodies retain creation interfaces.
World/environment routes remain typed rather than reference-value aliases.
"""
from dataclasses import dataclass, replace

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
            return_value: bool = True, conditions: tuple[str, ...] = (),
            on_ready=None) -> T.FunctionConnection | None:
    """Connect a known body under direct or conditional signature admission.

    NORMAL activations propagate ordinary/default reference arguments and the
    Python data result. Class receivers use the existing class projection;
    packs retain ordered dependencies, never a pack-to-formal reference edge.
    State input/output uses Route/returns, matching the original call binder.
    """
    requested_conditions = conditions
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
    positional = list(invocation.positional)
    keyword_items = list(invocation.keywords)
    packs = None
    unknown_positional = unknown_keywords = False
    binding = T.ArgumentBinding.DIRECT
    if invocation.positional_pack is not None or invocation.keyword_pack is not None:
        packs = T.ArgumentPacks(
            None if invocation.positional_pack is None else gp(invocation.positional_pack),
            None if invocation.keyword_pack is None else gp(invocation.keyword_pack),
            None if receiver is None else gp(receiver),
            None if class_receiver is None else gp(class_receiver))
        # A closed side remains usable when the other pack is open. Shape
        # evidence belongs to the original construction, not current contents.
        if invocation.positional_pack is not None:
            expanded = solver.containers.invocation_arguments(replace(invocation,
                positional=(), keywords=(), keyword_pack=None))
            unknown_positional = expanded is None
            if expanded is not None:positional.extend(expanded[0])
        if invocation.keyword_pack is not None:
            expanded = solver.containers.invocation_arguments(replace(invocation,
                positional=(), keywords=(), positional_pack=None))
            unknown_keywords = expanded is None
            if expanded is not None:keyword_items.extend(expanded[1])
        binding = (T.ArgumentBinding.SYMBOLIC_PACK if unknown_positional or unknown_keywords
                   else T.ArgumentBinding.CLOSED_PACK)
        conditions = (*conditions, *(
            ('CALL_SIGNATURE_ACCEPTANCE', 'ARGUMENT_PACK_BINDING_PENDING',
             'ARGUMENT_PACK_SHAPE_OR_KEY_COMPLETENESS_NOT_PROVEN')
            if binding is T.ArgumentBinding.SYMBOLIC_PACK else
            ('ARGUMENT_PACK_SHAPE_FROM_CLOSED_SOURCE_CONSTRUCTION',)))

    keywords = dict(keyword_items)
    if len(keywords) != len(keyword_items):
        return None

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

    # Explicit keyword collisions bound the admissible unknown positional
    # length. Without this bound, f(*open, a=x) could incorrectly satisfy a
    # later required positional parameter by skipping over a.
    slots = {i: slot for slot, i in enumerate(i for i, p in enumerate(params) if p.kind in positional_kinds)}
    occupied = len(positional) + int(project_class)
    has_varargs = any(p.kind is P.DeferredParameterKind.VAR_POSITIONAL for p in params)
    has_kwargs = any(p.kind is P.DeferredParameterKind.VAR_KEYWORD for p in params)
    if occupied > len(slots) and not has_varargs:return None
    positional_limit = None if has_varargs else len(slots) - occupied
    accepted_names = tuple(name for p, name in zip(params, function.parameter_names)
        if p.kind in (P.DeferredParameterKind.POSITIONAL_OR_KEYWORD, P.DeferredParameterKind.KEYWORD_ONLY))
    if not has_kwargs and any(name not in accepted_names for name in keywords):return None
    for index, name in enumerate(function.parameter_names):
        if params[index].kind is P.DeferredParameterKind.POSITIONAL_OR_KEYWORD and name in keywords:
            remaining = slots[index] - occupied
            if remaining < 0:return None
            positional_limit = remaining if positional_limit is None else min(positional_limit, remaining)

    routes, bindings, class_bindings, variadics = [], [], [], []
    projections, projected = [], []

    def project(formal, pack, kind, *, index=None, name=None, excluded_names=(), choices=()):
        projections.append(T.ArgumentProjection(gp(formal), gp(pack), kind,
            index=index, name=name, excluded_names=excluded_names,
            conditions=('CALL_SIGNATURE_ACCEPTANCE', *choices)))
        projected.append((formal, pack, kind, index, name, excluded_names))

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
            if unknown_positional:
                project(formal, invocation.positional_pack, T.ProjectionKind.POSITIONAL_TAIL,
                    index=max(0, len(slots) - occupied), choices=('REMAINING_POSITIONAL_PACK_CONTENT',))
        elif kind is P.DeferredParameterKind.VAR_KEYWORD:
            names, actuals = tuple(keywords), tuple(keywords.values())
            keywords.clear()
            route = T.RouteKind.PACK_KEYWORDS
            if unknown_keywords:
                # Positional-only names are valid residual keyword keys. Only
                # keyword-bindable formals and known explicit keys are removed.
                excluded = tuple(dict.fromkeys((*accepted_names, *(name for name, _ in keyword_items))))
                project(formal, invocation.keyword_pack, T.ProjectionKind.KEYWORD_REMAINDER,
                    excluded_names=excluded, choices=('UNCONSUMED_KEYWORD_PACK_CONTENT',))
        else:
            relative = slots.get(index, occupied) - occupied
            from_pos = (kind in positional_kinds and unknown_positional
                        and (positional_limit is None or relative < positional_limit))
            from_kw = (kind in (P.DeferredParameterKind.POSITIONAL_OR_KEYWORD,
                        P.DeferredParameterKind.KEYWORD_ONLY) and unknown_keywords)
            if from_pos:
                project(formal, invocation.positional_pack, T.ProjectionKind.POSITIONAL_ITEM,
                    index=relative, choices=('POSITIONAL_PACK_HAS_ITEM_AT_INDEX',
                        *(('KEYWORD_PACK_LACKS_PARAMETER_NAME',) if from_kw else ()),
                        *(('INITIAL_DEFAULT_NOT_SELECTED',) if function.defaults[index] is not None else ())))
            if from_kw:
                project(formal, invocation.keyword_pack, T.ProjectionKind.KEYWORD_ITEM,
                    name=name, choices=('KEYWORD_PACK_CONTAINS_PARAMETER_NAME',
                        *(('POSITIONAL_ITEM_ALTERNATIVE_ABSENT',) if from_pos else ()),
                        *(('INITIAL_DEFAULT_NOT_SELECTED',) if function.defaults[index] is not None else ())))
            if function.defaults[index] is not None:
                actuals = (offset + function.defaults[index],)
                route = T.RouteKind.CONDITIONAL_DEFAULT if from_pos or from_kw else T.RouteKind.INITIAL_DEFAULT
            elif not from_pos and not from_kw:
                return None
            else:
                route = None
        if route is not None:routes.append(T.Route(gp(formal), route, tuple(gp(p) for p in actuals), names))
        if route in (T.RouteKind.ARGUMENT, T.RouteKind.INITIAL_DEFAULT, T.RouteKind.CONDITIONAL_DEFAULT):
            bindings.extend((actual, formal) for actual in actuals)
        elif route in (T.RouteKind.PACK_POSITIONALS, T.RouteKind.PACK_KEYWORDS):
            variadics.append((formal, route, actuals, names))
    if position < len(positional) or keywords:
        return None
    if any(route.kind is T.RouteKind.CONDITIONAL_DEFAULT for route in routes):
        conditions = (*conditions, 'CONDITIONAL_DEFAULT_REQUIRES_ALL_ARGUMENT_ALTERNATIVES_ABSENT')
    if binding is T.ArgumentBinding.SYMBOLIC_PACK:
        if hasattr(solver,'body_demand'):solver.body_demand(fid,invocation.callee,'ARGUMENT_PACK_BINDING_OPEN')
        key = (fid, invocation, receiver, class_receiver, environment_source,
               return_value, requested_conditions)

        def retry():
            connection = connect(solver, fid, invocation, receiver,
                class_receiver=class_receiver, environment_source=environment_source,
                return_value=return_value, conditions=requested_conditions, on_ready=on_ready)
            if connection is None:return False
            if on_ready is not None:on_ready(connection)
            return connection.binding is not T.ArgumentBinding.SYMBOLIC_PACK

        solver.containers.watch_invocation(key, invocation, retry)
    elif hasattr(solver,'body_binding_resolved'):
        solver.body_binding_resolved(fid,invocation.callee)

    returned = []
    if activation is T.FunctionActivation.NORMAL:
        if hasattr(solver,'activate_function'):solver.activate_function(fid,invocation.callee)
        for actual, formal in bindings:
            solver.edge(actual, formal)
        for formal, value in class_bindings:
            solver.add(formal, value)
        for formal, route, actuals, names in variadics:
            open_rest = ((route is T.RouteKind.PACK_POSITIONALS and unknown_positional)
                         or (route is T.RouteKind.PACK_KEYWORDS and unknown_keywords))
            origin = (('SYMBOLIC_PACK_PREFIX', fid, invocation, receiver, class_receiver, formal)
                      if open_rest else (fid, invocation, receiver, class_receiver))
            solver.containers.bind_variadic(formal, route, actuals, names,
                origin=origin)
        for formal, pack, kind, index, name, excluded in projected:
            solver.containers.project_argument(formal, pack, kind,
                index=index, name=name, excluded_names=excluded)
        if return_value and invocation.result is not None and function.returns is not None:
            source = offset + function.returns
            solver.edge(source, invocation.result)
            returned.append((gp(source), gp(invocation.result)))
        if function.return_world is not None:
            returned.append((gp(offset + function.return_world), gp(invocation.result_world)))
    elif hasattr(solver,'body_demand'):
        solver.body_demand(fid,invocation.callee,'DEFERRED_BODY_RESUME_OPEN')
    connection=T.FunctionConnection(gp(fid), body, activation, (environment, *routes, state),
                                    tuple(returned), conditions, packs,
                                    projections=tuple(projections), binding=binding)
    if activation is T.FunctionActivation.CREATE_DEFERRED_BODY and hasattr(solver,'generators'):
        solver.generators.create(fid,invocation,receiver,class_receiver,connection)
    return connection
