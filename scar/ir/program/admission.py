"""Read-only predicate attachments on original operations and branches.

These queries distinguish a known wrong bool route from missing support for a
historical state read.  Neither a native phase nor a transformation is proved.
Call after canonical CFG/SSA validation; no additional state graph is stored.
"""
from .drivers import BodyResume, BodyStart
from .model import (AccessMode, Behavior, DataValue, ReferenceValue,
                    StateVersionValue, TerminatorKind)
from .protocols import (BodyStateCondition, BodyStatePredicateRule, OwnedUse,
                        ReferenceIsNoneCondition)
from .structured import ControlEdgeReference


def admission_errors(ctx, row):
    contract, operation = row.contract, ctx.operations[row.operation]
    issues = []

    def error(code, message):
        issues.append((code, str(row.operation), message))

    if (operation.terminator is not None or operation.callee is not None
            or operation.call_arguments or operation.invoke_arguments or operation.completions
            or not operation.effects_complete
            or not set(operation.behaviors).issubset({Behavior.CONTROL, Behavior.COMPUTE, Behavior.READ})
            or any(access.mode is not AccessMode.READ or access.after is not None
                   for access in operation.accesses)):
        error('admission_effect', 'admission predicate is a declared callback-free read-only ordinary primitive')
    try:
        produced = ctx.port(contract.result)
        if produced.operation != operation.id or row.slot != 0:
            error('admission_result', 'predicate must name its own ordinary result at row slot zero')
        if not produced.values or any(not isinstance(ctx.values[value], DataValue)
                or ctx.values[value].data_type != 'builtins.bool' for value in produced.values):
            error('admission_result', 'predicate result must be the original bool Data result')
        branch = ctx.operations.get(contract.branch)
        if (branch is None or branch.terminator is None
                or branch.terminator.kind is not TerminatorKind.BRANCH
                or ctx.region_of[branch.id] != ctx.region_of[operation.id]):
            error('admission_branch', 'predicate branch must be a real BRANCH in the same region')
        elif ctx.forwards(contract.result, OwnedUse(branch.id, branch.terminator.condition)) is False:
            error('admission_bool_source', 'branch condition is not this evaluation of the predicate bool')
        subject = contract.subject
        identity = subject.instance_use if type(subject) is BodyStateCondition else subject.input_use
        value = ctx.values[ctx.owned_use(operation.id, identity).value]
        if not isinstance(value, ReferenceValue):
            error('admission_input', 'predicate input must be its original Reference Use')
        if type(subject) is ReferenceIsNoneCondition:
            if operation.accesses:
                error('admission_effect', 'reference-is-None does not read heap/state domains')
        else:
            for site in subject.state_sites:
                if site.operation != operation.id or site.index >= len(operation.accesses):
                    error('admission_read', 'predicate state site must name its own original read')
            interface = ctx.interfaces.get(ctx.region_of[operation.id])
            if interface is not None and value.id not in ctx.driver_roles(interface.region)[0]:
                error('admission_owner', 'body predicate input is not the bound driver receiver role')
    except (KeyError, TypeError, ValueError) as exc:
        error('admission_reference', str(exc))
    return tuple(issues)


def admission_view(ctx, row):
    """Original bool/branch plus bounded current support; no writable facts."""
    contract, operation = row.contract, ctx.operations[row.operation]
    branch = ctx.operations[contract.branch]
    result = ctx.port(contract.result)
    target = OwnedUse(branch.id, branch.terminator.condition)
    copied = ctx.forwards(contract.result, target)
    gaps, support = [], []
    if copied is not True:
        gaps.append('admission_bool_route_unresolved')
    # Every actual read remains a dependency, including reads not selected as
    # the native phase site.  Do not silently discard ancillary state inputs.
    for access in operation.accesses:
        if not ctx.spend('admission_reads'):
            gaps.append('protocol_budget_exhausted')
            break
        current_uses = tuple(OwnedUse(branch.id, use.id) for use in branch.uses
            if isinstance(ctx.values[use.value], StateVersionValue)
            and ctx.values[use.value].location == access.location)
        matches = tuple(ctx.forwards(OwnedUse(operation.id, access.before), current)
                        for current in current_uses)
        current = bool(matches) and all(match is True for match in matches)
        if not current:
            gaps.append('admission_read_currentness_unproved')
        support.append({'access': access, 'before': OwnedUse(operation.id, access.before),
                        'branch_inputs': current_uses, 'must_copy': matches, 'current': current})
    subject = contract.subject
    identity = subject.instance_use if type(subject) is BodyStateCondition else subject.input_use
    routes = admission_routes(ctx, row)
    gaps.extend(routes['gaps'])
    return {'predicate': row, 'operation': operation, 'subject': subject,
            'input': ctx.owned_use(operation.id, identity), 'result': result,
            'branch': branch, 'condition': ctx.owned_use(branch.id, branch.terminator.condition),
            'bool_must_copy': copied, 'state_support': tuple(support),
            'successors': tuple(enumerate(branch.terminator.successors)),
            'control_routes': routes,
            'status': 'PARTIAL' if gaps else 'DECLARED', 'gaps': tuple(dict.fromkeys(gaps)),
            'native_phase_verified': False, 'source_runtime_verified': False,
            'transformation_authorized': False}


def _phase_target(rule, truth, target):
    """Compatibility at one unchanged read snapshot, not a native gate proof."""
    if rule is BodyStatePredicateRule.IS_CREATED:
        return isinstance(target, BodyStart) == truth
    if rule is BodyStatePredicateRule.IS_SUSPENDED:
        return isinstance(target, BodyResume) == truth
    if truth and rule in (BodyStatePredicateRule.IS_RUNNING, BodyStatePredicateRule.IS_CLOSED):
        return False
    return True


def admission_routes(ctx, row):
    """Walk original successors to the first gate, host exit or reevaluation.

    A state read is compared with gate *inputs*, never gate-produced state.
    Changed support is a gap: a historical bool remains a valid program value.
    Even an unchanged snapshot does not prove how an opaque gate implements
    its check or whether its NORMAL edge occurs on the selected runtime path.
    """
    contract, operation = row.contract, ctx.operations[row.operation]
    branch = ctx.operations[contract.branch]
    gates = ctx.gates
    frontiers, gaps = [], []
    for ordinal, successor in enumerate(branch.terminator.successors):
        edge = ControlEdgeReference(branch.id, ordinal)
        pending, seen, traversed = [], set(), {}
        if not ctx.spend('admission_route_candidates'):
            gaps.append('protocol_budget_exhausted')
            break
        pending.append(successor.block)
        while pending:
            if not ctx.spend('admission_route_blocks'):
                gaps.append('protocol_budget_exhausted')
                break
            block_id = pending.pop()
            if block_id in seen:
                continue
            seen.add(block_id)
            block = ctx.blocks[block_id]
            stopped = False
            for identity in block.operations:
                if not ctx.spend('admission_route_operations'):
                    gaps.append('protocol_budget_exhausted')
                    stopped = True
                    break
                current = ctx.operations[identity]
                if identity == operation.id:
                    gaps.append('admission_predicate_reevaluation_cut')
                    frontiers.append({'edge': edge, 'kind': 'REEVALUATION', 'operation': current})
                    stopped = True
                    break
                if identity in gates:
                    gate = gates[identity]
                    support, support_complete = [], True
                    for access in operation.accesses:
                        if not ctx.spend('admission_gate_reads'):
                            support_complete = False
                            gaps.append('protocol_budget_exhausted')
                            break
                        selected = []
                        for use_id in current.invoke_arguments:
                            if not ctx.spend('admission_gate_arguments'):
                                support_complete = False
                                gaps.append('protocol_budget_exhausted')
                                break
                            value = ctx.values[ctx.owned_use(identity, use_id).value]
                            if isinstance(value, StateVersionValue) and value.location == access.location:
                                selected.append(OwnedUse(identity, use_id))
                        actuals = tuple(selected)
                        matches = tuple(ctx.forwards(OwnedUse(operation.id, access.before), actual)
                                        for actual in actuals)
                        support.append({'access': access, 'gate_inputs': actuals, 'must_copy': matches,
                                        'current': bool(matches) and all(item is True for item in matches)})
                    unchanged = support_complete and all(item['current'] for item in support)
                    if not unchanged:
                        gaps.append('admission_gate_support_changed_or_unresolved')
                    target = ctx.drives[gate.drive].target
                    phase = (contract.subject.rule if type(contract.subject) is BodyStateCondition else None)
                    compatible = (_phase_target(phase, ordinal == 0, target)
                                  if unchanged and phase is not None else None)
                    if compatible is False:
                        gaps.append('admission_phase_target_incompatible_at_snapshot')
                    frontiers.append({'edge': edge, 'kind': 'FINAL_GATE', 'operation': current,
                        'gate': gate, 'drive': ctx.drives[gate.drive], 'state_support': tuple(support),
                        'read_snapshot_current': unchanged, 'target_compatible_at_snapshot': compatible,
                        'native_gate_verified': False})
                    stopped = True
                    break
                if identity in ctx.drives:
                    gaps.append('admission_drive_without_observed_gate')
                    frontiers.append({'edge': edge, 'kind': 'BODY_DRIVE', 'operation': current})
                    stopped = True
                    break
                if current.terminator is not None and current.terminator.kind in (
                        TerminatorKind.RETURN, TerminatorKind.RAISE):
                    frontiers.append({'edge': edge, 'kind': 'HOST_EXIT', 'operation': current})
                    stopped = True
                    break
            if stopped:
                traversed[block_id] = ()
                continue
            terminator = ctx.operations[block.operations[-1]]
            traversed[block_id] = []
            for outgoing in terminator.terminator.successors:
                if not ctx.spend('admission_route_candidates'):
                    gaps.append('protocol_budget_exhausted')
                    break
                traversed[block_id].append(outgoing.block)
                pending.append(outgoing.block)
        # Check only the visited original CFG between these cuts. A reachable
        # cycle with another exiting alternative is still an unselected visit;
        # finding one frontier never proves every path reaches that frontier.
        indegree = {identity: 0 for identity in seen}
        for outgoing in traversed.values():
            for destination in outgoing:
                if not ctx.spend('admission_route_cycle_edges'):
                    gaps.append('protocol_budget_exhausted')
                    break
                if destination in indegree:
                    indegree[destination] += 1
        ready = [identity for identity, count in indegree.items() if count == 0]
        removed = 0
        while ready:
            if not ctx.spend('admission_route_cycle_nodes'):
                gaps.append('protocol_budget_exhausted')
                break
            identity = ready.pop()
            removed += 1
            for destination in traversed.get(identity, ()):
                if not ctx.spend('admission_route_cycle_edges'):
                    gaps.append('protocol_budget_exhausted')
                    break
                if destination in indegree:
                    indegree[destination] -= 1
                    if indegree[destination] == 0:
                        ready.append(destination)
        if removed != len(seen):
            gaps.append('admission_route_cycle_or_budget_unresolved')
        # A cycle that reaches no frontier is still an unresolved obligation.
        if not any(item['edge'] == edge for item in frontiers):
            gaps.append('admission_route_frontier_unresolved')
    return {'frontiers': tuple(frontiers), 'gaps': tuple(dict.fromkeys(gaps)),
            'scope': 'SUPPLIED_STATIC_CFG', 'dynamic_path_selected': False,
            'native_gate_verified': False, 'transformation_authorized': False}


__all__ = ['admission_errors', 'admission_view', 'admission_routes']
