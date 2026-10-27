"""Compose original input recipes with return-aware local copy analyses.

Recipes inventory possible routes. They neither choose an expected source nor
provide copy proofs by themselves. Each segment below checks original Uses.
"""
from .model import TerminatorKind
from .protocol_flow import ProtocolPort
from .protocols import OwnedUse
from .structured import ControlEdgeReference


def _local_guards(ctx, guard, choices, calls, number, region):
    """Recipe CFG choices belong to this exact caller prefix, not all visits."""
    if not ctx.spend('composition_context_prefixes', number + 1):
        return None
    prefix = calls[:number]
    edges = list(ctx.selected_edges(guard, region=region))
    for (context, operation), successor in choices.items():
        if not ctx.spend('composition_guard_choices'):
            return None
        if context == prefix and ctx.region_of[operation] == region:
            edges.append(ControlEdgeReference(operation, successor))
    try:
        selected = ctx.selected_edges(tuple(edges))
    except ValueError:
        return {'conflict': True}
    if ctx.selection_ambiguity(selected) is not None:
        return {'ambiguous': True}
    return selected


def _frame(ctx, step):
    """Validate the recipe against prepared canonical actual/formal ports."""
    operation = ctx.operations[step['caller'].id]
    invoke = operation.terminator is not None and operation.terminator.kind is TerminatorKind.INVOKE
    actuals = operation.invoke_arguments if invoke else operation.call_arguments
    ordinal = step['ordinal']
    if (operation.callee != step['callee'] or ordinal >= len(actuals)
            or actuals[ordinal] != step['actual'].id):
        raise ValueError('composition frame must retain its original call actual ordinal')
    original = ctx.owned_use(operation.id, step['actual'].id)
    formals = ctx.blocks[ctx.regions[operation.callee].entry].arguments
    if original != step['actual'] or formals[ordinal] != step['formal'].id:
        raise ValueError('composition frame must retain its original actual and formal')
    return operation, actuals, formals


def _segment_flow(ctx, port, guard, local):
    """Keep recipe choices scoped to this segment alongside user guards."""
    previous = ctx._returns.guards
    ctx._returns.guards = ctx.selected_edges((*ctx.selected_edges(guard), *local))
    try:
        return ctx._fresh_copies(port, guard=local or None)
    finally:
        ctx._returns.guards = previous


def compose_route(ctx, expected, port, actual, recipe, *, guard, calls, choices, rooted):
    """One complete route, never a cross-recipe ANY/identity assertion."""
    result = {'match': None, 'segments': (), 'gaps': (), 'context_rooted': rooted}
    # An unresolved occurrence cannot supply an exact caller route. Reject
    # that prerequisite before scanning/materializing its entire path; the
    # original recipe remains in the report and in the route denominator.
    if recipe['kind'] == 'STATIC_CYCLE' or not rooted:
        return {**result, 'gaps': ('call_composition_occurrence_context_unresolved',)}
    if not ctx.spend('composition_recipe_steps', len(recipe['path'])):
        return {**result, 'gaps': ('call_composition_budget_exhausted',)}
    steps = tuple(step for step in recipe['path'] if step.get('kind') == 'CALL_ACTUAL_TO_FORMAL')
    result['frame_inventory'] = tuple((step['caller'].id, step['callee'], step['ordinal'],
        OwnedUse(step['caller'].id, step['actual'].id), step['formal'].origin) for step in steps)
    if not steps or len(steps) != len(calls):
        return {**result, 'gaps': ('call_composition_entry_route_unresolved',)}
    caller_regions = tuple(caller_region for _, caller_region, _ in calls)
    if len(set(caller_regions)) != len(caller_regions):
        return {**result, 'gaps': ('call_composition_recursive_context_unresolved',)}
    source_region = ctx.region_of[port.operation]
    anchor = None
    for number, step in enumerate(steps):
        if not ctx.spend('composition_anchor_frames'):
            return {**result, 'gaps': ('call_composition_budget_exhausted',)}
        operation, _, _ = _frame(ctx, step)
        caller_region = ctx.region_of[operation.id]
        if source_region == caller_region:
            anchor = number
        else:
            exported = ctx._returns.export_applicable(source_region, caller_region)
            if exported is None:
                return {**result, 'gaps': ('call_composition_budget_exhausted',)}
            if exported:
                anchor = number
    if anchor is None:
        return {**result, 'match': False}
    segments, source, unresolved = [], port, False
    result['anchor_frame'] = anchor
    for number in range(anchor, len(steps)):
        if not ctx.spend('composition_call_frames'):
            return {**result, 'segments': tuple(segments), 'gaps': ('call_composition_budget_exhausted',)}
        operation, actuals, formals = _frame(ctx, steps[number])
        region = ctx.region_of[operation.id]
        local = _local_guards(ctx, guard, choices, calls, number, region)
        if local is None or type(local) is dict:
            return {**result, 'segments': tuple(segments), 'gaps': (
                'call_composition_budget_exhausted' if local is None else
                'call_composition_cfg_context_unresolved',)}
        # Only actual membership is evidence. A still-available expected
        # source elsewhere in the set cannot stand in for these operands.
        before = None
        if number != anchor:
            before = _segment_flow(ctx, source, guard, local)
            if before is None:
                return {**result, 'segments': tuple(segments), 'gaps': tuple(ctx._returns.gaps)
                        or ('call_composition_local_flow_unresolved',)}
        seeds, bindings = [], []
        for ordinal, (identity, formal) in enumerate(zip(actuals, formals)):
            if not ctx.spend('composition_actual_formals'):
                return {**result, 'segments': tuple(segments), 'gaps': ('call_composition_budget_exhausted',)}
            target = OwnedUse(operation.id, identity)
            if number == anchor:
                # Initial up/down bridge reuses the independently given
                # expected port and existing exact unique-caller export.
                combined = ctx.selected_edges((*ctx.selected_edges(guard), *local))
                support = ctx.bind(expected, target, guard=combined or None)
                match = support['match']
            else:
                support = None
                match = ctx.owned_use(operation.id, identity).value in before.get(operation.id, ())
                if not match and unresolved:
                    match = None
            bindings.append({'ordinal': ordinal, 'actual': target, 'formal': formal,
                             'match': match, 'support': support})
            if match is True:
                seeds.append(formal)
            elif match is None:
                unresolved = True
        segment = {'caller': operation.id, 'caller_region': region, 'callee': operation.callee,
                   'context_prefix': calls[:number + 1], 'guards': local,
                   'recipe_ordinal': steps[number]['ordinal'], 'bindings': tuple(bindings),
                   'seeds': tuple(seeds)}
        segments.append(segment)
        if not seeds:
            return {**result, 'match': None if unresolved else False, 'segments': tuple(segments),
                    'gaps': ('call_composition_input_unresolved',) if unresolved else ()}
        entry = ctx.blocks[ctx.regions[operation.callee].entry]
        source = ProtocolPort(None, entry.operations[0], tuple(seeds), 'before')
    region = ctx.region_of[actual.operation]
    if ctx.region_of[source.operation] != region:
        return {**result, 'segments': tuple(segments), 'gaps': ('call_composition_terminal_region_unresolved',)}
    local = _local_guards(ctx, guard, choices, calls, len(steps), region)
    if local is None or type(local) is dict:
        return {**result, 'segments': tuple(segments), 'gaps': ('call_composition_cfg_context_unresolved',)}
    before = _segment_flow(ctx, source, guard, local)
    if before is None:
        return {**result, 'segments': tuple(segments), 'gaps': tuple(ctx._returns.gaps)
                or ('call_composition_terminal_flow_unresolved',)}
    match = ctx.owned_use(actual.operation, actual.use).value in before.get(actual.operation, ())
    if not match and unresolved:
        match = None
    return {**result, 'match': match, 'segments': tuple(segments), 'terminal_guards': local,
            'gaps': ('call_composition_input_unresolved',) if match is None else ()}


__all__ = ['compose_route']
