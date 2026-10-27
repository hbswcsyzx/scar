"""Conditional reachability from an exact original iterator qualification.

These are bounded query views, not new CFG edges or native identity facts.
Syntactically present but infeasible accepting legs stay in the inventory.
"""
from .evaluated_sources import evaluated_sources
from .model import ExitKind, InvokeLiteralResult, TerminatorKind
from .protocol_await_records import AwaitAcquisition, AwaitIteratorQualification, ExpandedAwaitCallee
from .protocol_connections import ProtocolOperationRef
from .protocols import OwnedUse, StaticProtocolGap
from .resumption import ResumableKind
from .structured import ControlEdgeReference


BAD_ITERATORS = (ResumableKind.COROUTINE, ResumableKind.GENERATOR_COROUTINE,
                ResumableKind.ASYNC_GENERATOR, 'NON_ITERATOR')


def _ref(row):
    return ProtocolOperationRef(row.scope, row.clause, row.operation, row.slot)


def _flags():
    return {'source_runtime_verified': False, 'runtime_identity_verified': False,
            'value_identity_verified': False, 'transformation_authorized': False}


def qualification_view(ctx, row, choices=()):
    """Interpret all source cases without certifying a native implementation."""
    choices = ctx.selected_edges(choices)
    if not hasattr(ctx, '_await_qualification_views'):
        ctx._await_qualification_views = {}
    key = _ref(row), choices
    if key in ctx._await_qualification_views:
        return ctx._await_qualification_views[key]
    contract = row.contract
    source = evaluated_sources(ctx, contract.expected,
        OwnedUse(row.operation, contract.input_use), choices, role='GENERAL_RETURN')
    if contract.branch is not None:
        branch = ctx.operations[contract.branch]
        edge = ControlEdgeReference(branch.id, 0 if contract.accepts_true else 1)
        boolean = ctx.bind(contract.result, OwnedUse(branch.id, branch.terminator.condition),
                           guard=choices or None)
    else:
        boolean, edge = None, None
        for sibling in ctx.rows_by_clause.get((row.scope, row.clause), ()):
            if sibling.operation != row.operation:
                continue
            port = sibling.contract.result
            if (type(port) is InvokeLiteralResult and ctx.operations[row.operation].terminator.
                    successors[port.edge.successor_index].kind is ExitKind.NORMAL):
                edge = port.edge
                break
    valid = (source['binding']['match'] is True
             and (boolean is None or boolean['match'] is True))
    cases = []
    for case in source['cases']:
        accepts = None
        if valid and case['current'] is True:
            accepts = (False if case['kind'] in BAD_ITERATORS else
                       True if case['kind'] is ResumableKind.GENERATOR else None)
        cases.append({'source_case': case, 'accepts': accepts,
            'reason': 'known_non_iterator_for_general_await' if accepts is False else
                      'declared_generator_iterator' if accepts is True else 'qualification_unproved'})
    complete = source['classification_complete'] and valid and not ctx.budget.truncated
    values = {case['accepts'] for case in cases}
    acceptance = next(iter(values)) if complete and len(values) == 1 else None
    declared_boolean, predicate_conflict = None, False
    if contract.branch is not None:
        from scar.ir.literals import LiteralKind, PythonLiteral
        from .evaluated_sources import _prepare
        literal = _prepare(ctx)[1].get(contract.result)
        if (literal is not None and type(literal.literal) is PythonLiteral
                and literal.literal.kind is LiteralKind.BOOL):
            declared_boolean = literal.literal.payload
            expected_boolean = acceptance if contract.accepts_true else (
                None if acceptance is None else not acceptance)
            predicate_conflict = (expected_boolean is not None
                                  and declared_boolean is not expected_boolean)
    result = {'record': row, 'source': source, 'accepting_edge': edge,
        'bool_binding': boolean, 'cases': tuple(cases), 'acceptance': acceptance,
        'declared_boolean': declared_boolean, 'predicate_conflict': predicate_conflict,
        'known_inventory_complete': complete, 'conditions': (
            'qualification native semantics and source correspondence remain conditional',), **_flags()}
    ctx._await_qualification_views[key] = result
    return result


def _controlled(ctx, edge, targets):
    """An original accepting edge controls every stated success target.

    Remove the edge from the original graph, without assuming its selection.
    A reachable bypass is a counterexample; budget exhaustion is unknown.
    """
    key = edge, tuple(targets)
    if not hasattr(ctx, '_await_qualification_control'):
        ctx._await_qualification_control = {}
    if key in ctx._await_qualification_control:
        return ctx._await_qualification_control[key]
    region = ctx.region_of[edge.operation]
    _, outgoing, _, reached, _ = ctx._edges(region)
    wanted = {ctx.block_of[target] for target in targets}
    if not wanted or not wanted.issubset(reached):
        return None
    if ctx.block_of[edge.operation] not in reached:
        return False
    pending, seen = [ctx.regions[region].entry], set()
    while pending:
        if not ctx.spend('await_qualification_control_blocks'):
            return None
        block = pending.pop()
        if block in seen:
            continue
        seen.add(block)
        if block in wanted:
            ctx._await_qualification_control[key] = False
            return False
        for operation, number, target, _ in outgoing[block]:
            if not ctx.spend('await_qualification_control_edges'):
                return None
            if (operation, number) != (edge.operation, edge.successor_index):
                pending.append(target)
    ctx._await_qualification_control[key] = True
    return True


def protected_advance(ctx, candidate_source, iterator, choices=()):
    """An exact check covers this candidate and this original success route.

    The native predicate can exclude a bad case only after current copies and
    control coverage are established. A nearby or bypassed check is insufficient.
    """
    from .protocol_await import _kind, _prepare, _result_copy, _selected, success_source
    rows = _prepare(ctx)[0][AwaitIteratorQualification]
    if not rows or iterator is None:
        return {'match': False, 'guards': (), 'gaps': ()}
    choices = ctx.selected_edges(choices)
    if not hasattr(ctx, '_await_protected_advances'):
        ctx._await_protected_advances = {}
    key = candidate_source, iterator, choices
    if key in ctx._await_protected_advances:
        return ctx._await_protected_advances[key]
    guarded, unknown = [], []
    for row in rows:
        if not ctx.spend('await_qualification_guards'):
            unknown.append('await_qualification_guard_budget')
            break
        accepted, forced = success_source(ctx, row)
        edge = (ControlEdgeReference(row.contract.branch, 0 if row.contract.accepts_true else 1)
                if row.contract.branch is not None else
                row.contract.result.edge if type(row.contract.result) is InvokeLiteralResult else None)
        if accepted is None or edge is None:
            continue
        try:
            selected = _selected(ctx, choices, forced, edge)
        except ValueError:
            # This request selects the rejecting leg, not this protection.
            continue
        region = ctx.region_of[row.operation]
        paths = []
        if region == ctx.region_of[iterator.operation]:
            copied = ctx.bind(accepted, iterator, guard=selected or None)
            if copied['match'] is not False:
                paths.append({'bindings': (copied,),
                    'controlled': _controlled(ctx, edge, (iterator.operation,))})
        else:
            for parent in ctx._await_qualification_parents.get(_ref(row), ()):
                if not ctx.spend('await_qualification_parent_sites'):
                    unknown.append('await_qualification_parent_budget')
                    break
                if (type(parent.contract) is not AwaitAcquisition
                        or type(parent.contract.expansion) is not ExpandedAwaitCallee
                        or parent.contract.expansion.qualification != _ref(row)
                        or ctx.operations[parent.operation].callee != region
                        or _kind(ctx, parent.contract.result) is not ExitKind.NORMAL):
                    continue
                delivered = ctx.bind(parent.contract.result, iterator, guard=selected or None)
                if delivered['match'] is False:
                    continue
                terminals = ctx._await_normal_terminals.get(region, ())
                if not ctx.spend('await_qualification_success_terminals', len(terminals)):
                    unknown.append('await_qualification_terminal_budget')
                    break
                paths.append({'parent': parent, 'bindings': (
                    _result_copy(ctx, accepted, parent.contract.result, selected),
                    delivered),
                    'controlled': _controlled(ctx, edge, terminals)})
        # Unrelated predicates have no path skeleton to this iterator. Their
        # unknown external input cannot weaken a known unqualified rejection.
        paths = [path for path in paths if path['controlled'] is not False
                 and all(binding['match'] is not False for binding in path['bindings'])]
        if not paths:
            continue
        view = qualification_view(ctx, row, choices)
        if view['predicate_conflict']:
            continue
        input_report = ctx.bind(candidate_source, OwnedUse(row.operation, row.contract.input_use),
                                guard=choices or None)
        if input_report['match'] is False:
            continue
        if (input_report['match'] is None or view['source']['binding']['match'] is not True
                or view['bool_binding'] is not None and view['bool_binding']['match'] is not True):
            unknown.append('await_qualification_input_unproved')
            continue
        for path in paths:
            bindings = (input_report, *path['bindings'])
            checks = (path['controlled'], *(binding['match'] for binding in bindings))
            if all(check is True for check in checks):
                guarded.append({'qualification': row, 'feasibility': view, **path, 'bindings': bindings})
            elif False not in checks:
                unknown.append('await_qualification_path_unproved')
    result = {'match': None if unknown else True if guarded else False,
              'guards': tuple(guarded), 'gaps': tuple(dict.fromkeys(unknown))}
    ctx._await_protected_advances[key] = result
    return result


__all__ = ['BAD_ITERATORS', 'qualification_view', 'protected_advance']
