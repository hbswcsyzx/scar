"""Validate declared synchronous call-to-activation associations.

All argument and result routes are projections of canonical program ports and
the already validated execution occurrences.  Missing capture remains a gap;
it never causes the validator to select an activation by static identity.
"""
from __future__ import annotations

from collections import deque
from itertools import chain

from scar.ir.program.model import CompletionResult, ExitKind, TerminatorKind

from .common import Unresolved
from .coordinates import InitialEntry, UnresolvedHostThread
from .ids import BlockVisitID, OperationOccurrenceID, RegionActivationID


def _record_gap(ctx, target, code, path, message):
    from .validation import ExecutionIssue

    issue = ExecutionIssue(code, str(path), message)
    if target is not None and issue not in target:
        target.append(issue)
    key = issue.code, issue.path, issue.message
    if key not in ctx._gap_keys:
        ctx._gap_keys.add(key)
        ctx.gaps.append(issue)
    return issue


def _point_scope(ctx, unresolved, activation_id, path, route_gaps):
    """Check a stated unresolved point's known scope against its activation."""
    point = unresolved.point
    ctx.check_point(point, path)
    activation = ctx.activations.get(activation_id)
    if activation is None:
        return
    process = ctx.processes.get(activation.process)
    if process is None:
        return
    if point.run != process.run:
        ctx.issue('call_unresolved_run', path, 'unresolved endpoint is known to belong to another run')
    if point.process is not None and point.process != activation.process:
        ctx.issue('call_unresolved_process', path, 'unresolved endpoint is known to belong to another process')
    elif point.process is None:
        _record_gap(ctx, route_gaps, 'call_endpoint_process_unresolved', path,
                    'unresolved endpoint does not identify a process incarnation')


def _visit_chains(ctx):
    """Index captured linear visit chains once; flow validation bounds degree to one."""
    terminal_occurrences = {}
    for occurrence in ctx.occurrences.values():
        visit = ctx.visits[occurrence.visit]
        block = ctx.blocks[visit.block]
        if block.operations and block.operations[-1] == occurrence.operation:
            terminal_occurrences[visit.id] = occurrence.id
    successors = {}
    for visit_id, operation_id in terminal_occurrences.items():
        transfer = ctx.outgoing.get(operation_id)
        if transfer is not None:
            target = ctx.visits[transfer.target]
            source = ctx.visits[visit_id]
            if ctx.segments[source.segment].activation == ctx.segments[target.segment].activation:
                successors[visit_id] = target.id

    component, rank = {}, {}
    roots = [identity for identity in ctx.visits if identity not in ctx.incoming]
    ordinal = 0
    for root in chain(roots, ctx.visits.keys()):
        if root in component:
            continue
        chain_id = ordinal
        ordinal += 1
        cursor = root
        position = 0
        while cursor not in component:
            component[cursor] = chain_id
            rank[cursor] = position
            position += 1
            following = successors.get(cursor)
            if following is None:
                break
            cursor = following
    return component, rank


def _path_exists(chains, start: BlockVisitID, finish: BlockVisitID) -> bool:
    component, rank = chains
    return (start in component and finish in component
            and component[start] == component[finish] and rank[start] <= rank[finish])


def _check_threads(ctx, caller_segment, child_segments, route_gaps, path):
    """Compare every known segment thread, even when the entry visit is absent."""
    if not child_segments:
        _record_gap(ctx, route_gaps, 'call_thread_unresolved', path,
                    'callee activation has no captured segment thread')
        return
    known_threads = set()
    if type(caller_segment.host_thread) is UnresolvedHostThread:
        _record_gap(ctx, route_gaps, 'call_thread_unresolved', path,
                    'caller thread correspondence is not established')
    else:
        known_threads.add(caller_segment.host_thread)
    for child_segment in child_segments:
        if type(child_segment.host_thread) is UnresolvedHostThread:
            _record_gap(ctx, route_gaps, 'call_thread_unresolved', path,
                        'callee segment thread correspondence is not established')
        else:
            known_threads.add(child_segment.host_thread)
    if len(known_threads) > 1:
        ctx.issue('call_thread', path,
                  'synchronous caller and callee have different known host threads')


def _terminal_kind(ctx, row, operation):
    if type(row.completion) is Unresolved:
        return None
    occurrence = ctx.occurrences.get(row.completion)
    if occurrence is None:
        ctx.issue('call_completion_occurrence', row.id, 'completion references an unknown operation occurrence')
        return None
    if ctx.activation_of(occurrence.id) != row.activation:
        ctx.issue('call_completion_activation', row.id, 'completion is outside the linked callee activation')
        return None
    completion_op = ctx.core_operations[occurrence.operation]
    term = completion_op.terminator
    if term is None or term.kind not in (TerminatorKind.RETURN, TerminatorKind.RAISE):
        ctx.issue('call_completion_kind', row.id, 'callee completion must be an actual RETURN or RAISE occurrence')
        return None
    activation = ctx.activations[row.activation]
    region = ctx.regions[activation.region]
    expected = ExitKind.NORMAL if term.kind is TerminatorKind.RETURN else ExitKind.RAISE
    port = next((candidate for candidate in region.exits if candidate.name == term.exit), None)
    if port is None or port.kind is not expected:
        ctx.issue('call_completion_exit', row.id, 'completion does not match a canonical callee exit port')
        return None
    if operation.terminator is None or operation.terminator.kind is not TerminatorKind.INVOKE:
        if expected is not ExitKind.NORMAL:
            ctx.issue('call_completion_raise', row.id, 'ordinary CALL only has a normal callee completion')
            return None
    return expected


def _inputs(ctx, row, caller, operation, callee_region, route_gaps):
    args = (operation.invoke_arguments if operation.terminator is not None
            and operation.terminator.kind is TerminatorKind.INVOKE else operation.call_arguments)
    entry_block = next((block for block in callee_region.blocks if block.id == callee_region.entry), None)
    formals = () if entry_block is None else entry_block.arguments
    result = []
    for ordinal, (actual_id, formal_id) in enumerate(zip(args, formals)):
        static_use = ctx.core_uses.get(actual_id)
        actual_definition = None if static_use is None else static_use[1]
        actual_occurrence = ctx.uses.get((caller.id, actual_id))
        actual_value = None
        if actual_occurrence is None:
            _record_gap(ctx, route_gaps, 'call_actual_unobserved', row.id,
                        f'caller actual Use {actual_id} has no dynamic occurrence')
        elif type(actual_occurrence.value) is Unresolved:
            actual_value = actual_occurrence.value
            _record_gap(ctx, route_gaps, 'call_actual_unresolved', row.id,
                        f'caller actual Use {actual_id} has an explicit unresolved value')
        else:
            actual_value = ctx.values.get(actual_occurrence.value)
            if actual_value is None:
                _record_gap(ctx, route_gaps, 'call_actual_value_unobserved', row.id,
                            f'caller actual ValueOccurrence for Use {actual_id} is missing')
        formal_occurrence = None
        if type(row.entry) is BlockVisitID:
            formal_occurrence = ctx.results.get((row.entry, formal_id))
            if formal_occurrence is None:
                _record_gap(ctx, route_gaps, 'call_formal_unobserved', row.id,
                            f'callee formal {formal_id} has no dynamic entry value')
        result.append({
            'ordinal': ordinal,
            'formal_definition': ctx.core_values[formal_id],
            'formal': formal_occurrence,
            'actual_definition': actual_definition,
            'actual': actual_occurrence,
            'actual_value': actual_value,
        })
    if len(args) != len(formals):
        # Program validation normally catches this. Keep this layer robust when
        # handed a ProgramGraph that has not been prevalidated.
        ctx.issue('call_static_arity', row.id, 'call association ports have inconsistent static arity')
    return tuple(result)


def _outputs(ctx, row, caller, operation, completion_kind, route_gaps):
    if type(row.completion) is Unresolved:
        return ()
    occurrence = ctx.occurrences.get(row.completion)
    if occurrence is None:
        return ()
    child_op = ctx.core_operations[occurrence.operation]
    term = child_op.terminator
    if term is None or term.kind not in (TerminatorKind.RETURN, TerminatorKind.RAISE):
        return ()
    caller_transfer = None
    successor = None
    landing_visit = None
    invoke = operation.terminator is not None and operation.terminator.kind is TerminatorKind.INVOKE
    if invoke:
        caller_transfer = ctx.outgoing.get(caller.id)
        if caller_transfer is None:
            _record_gap(ctx, route_gaps, 'call_transfer_unobserved', row.id,
                        'callee completion is recorded but the caller INVOKE successor was not captured')
        else:
            successor = operation.terminator.successors[caller_transfer.successor_index]
            if successor.kind is not completion_kind:
                ctx.issue('call_transfer_kind', row.id,
                          'caller INVOKE took a completion kind different from the actual callee exit')
            landing_visit = ctx.visits.get(caller_transfer.target)

    outputs = []
    for ordinal, use_id in enumerate(term.values):
        static_use_pair = ctx.core_uses.get(use_id)
        static_use = None if static_use_pair is None else static_use_pair[1]
        dynamic_use = ctx.uses.get((occurrence.id, use_id))
        if dynamic_use is None:
            _record_gap(ctx, route_gaps, 'call_exit_use_unobserved', row.id,
                        f'callee exit Use {use_id} has no dynamic occurrence')
        elif type(dynamic_use.value) is Unresolved:
            _record_gap(ctx, route_gaps, 'call_exit_value_unresolved', row.id,
                        f'callee exit Use {use_id} has an explicit unresolved value')
        caller_result_definition = None
        caller_result = None
        caller_formal_definition = None
        caller_formal = None
        edge_argument = None
        if not invoke:
            if ordinal < len(operation.results):
                caller_result_definition = ctx.core_values[operation.results[ordinal]]
                caller_result = ctx.results.get((caller.id, operation.results[ordinal]))
                if caller_result is None:
                    _record_gap(ctx, route_gaps, 'call_result_unobserved', row.id,
                                f'caller result at position {ordinal} has no dynamic occurrence')
        elif successor is not None and landing_visit is not None:
            for arg_position, argument in enumerate(successor.arguments):
                if type(argument) is CompletionResult and argument.index == ordinal:
                    edge_argument = argument
                    landing_block = ctx.blocks[landing_visit.block]
                    if arg_position < len(landing_block.arguments):
                        formal_id = landing_block.arguments[arg_position]
                        caller_formal_definition = ctx.core_values[formal_id]
                        caller_formal = ctx.results.get((landing_visit.id, formal_id))
                        if caller_formal is None:
                            _record_gap(ctx, route_gaps, 'call_landing_formal_unobserved', row.id,
                                        f'caller completion formal at position {arg_position} is unobserved')
                    break
            if edge_argument is None:
                ctx.issue('call_completion_result', row.id,
                          f'actual caller successor does not route completion result {ordinal}')
        outputs.append({
            'ordinal': ordinal,
            'callee_exit': occurrence,
            'callee_use_definition': static_use,
            'callee_use': dynamic_use,
            'caller_result_definition': caller_result_definition,
            'caller_result': caller_result,
            'caller_transfer': caller_transfer,
            'caller_formal_definition': caller_formal_definition,
            'caller_formal': caller_formal,
            'edge_argument': edge_argument,
        })
    return tuple(outputs)


def call_errors(ctx) -> None:
    """Add call association checks and canonical route views to one context."""
    ctx.resolved_call_activations = {}
    rows_by_caller = {}
    caller_owner = {}
    activation_owner = {}
    dependency_edges = []
    segments_by_activation = {}
    for segment in ctx.segments.values():
        segments_by_activation.setdefault(segment.activation, []).append(segment)
    terminal_occurrences_by_activation = {}
    for occurrence in ctx.occurrences.values():
        operation = ctx.core_operations[occurrence.operation]
        term = operation.terminator
        if term is None or term.kind not in (TerminatorKind.RETURN, TerminatorKind.RAISE):
            continue
        activation_id = ctx.activation_of(occurrence.id)
        if activation_id is not None:
            terminal_occurrences_by_activation.setdefault(activation_id, []).append(occurrence)
    visit_chains = _visit_chains(ctx) if ctx.model.call_activations else ({}, {})

    for row in ctx.model.call_activations:
        rows_by_caller.setdefault(row.caller, []).append(row.id)
        route_gaps = []
        caller = ctx.occurrences.get(row.caller)
        if caller is None:
            ctx.issue('call_caller_occurrence', row.id, 'association references an unknown caller occurrence')
            continue
        operation = ctx.core_operations[caller.operation]
        if operation.callee is None:
            ctx.issue('call_static_callee', row.id, 'association requires an original static callee')
            continue
        callee = ctx.regions.get(operation.callee)
        activation = ctx.activations.get(row.activation)
        if callee is None:
            ctx.issue('call_static_callee', row.id, 'caller references an unknown static callee region')
            continue
        if activation is None:
            ctx.issue('call_activation_owner', row.id, 'association references an unknown callee activation')
            continue
        if activation.region != callee.id:
            ctx.issue('call_activation_region', row.id, 'callee activation region differs from the original static callee')

        if row.caller in caller_owner:
            ctx.issue('call_caller_reused', row.id, 'one caller occurrence cannot select multiple callee activations')
        else:
            caller_owner[row.caller] = row.id
        if row.activation in activation_owner:
            ctx.issue('call_activation_reused', row.id, 'one activation cannot be selected by multiple caller occurrences')
        else:
            activation_owner[row.activation] = row.id

        parent_activation = ctx.activation_of(caller.id)
        parent = ctx.activations[parent_activation]
        if parent.process != activation.process:
            ctx.issue('call_process', row.id, 'synchronous caller and callee must be in the same process incarnation')
        parent_process = ctx.processes.get(parent.process)
        child_process = ctx.processes.get(activation.process)
        if parent_process is not None and child_process is not None and parent_process.run != child_process.run:
            ctx.issue('call_run', row.id, 'synchronous caller and callee must be in the same run')
        dependency_edges.append((parent_activation, row.activation, row.id))

        caller_segment = ctx.segments[ctx.visits[caller.visit].segment]
        _check_threads(ctx, caller_segment, segments_by_activation.get(row.activation, ()),
                       route_gaps, row.id)
        if type(row.entry) is BlockVisitID:
            entry_visit = ctx.visits.get(row.entry)
            if entry_visit is None:
                ctx.issue('call_entry_visit', row.id, 'entry references an unknown block visit')
            else:
                entry_segment = ctx.segments[entry_visit.segment]
                if entry_segment.activation != row.activation:
                    ctx.issue('call_entry_activation', row.id, 'entry visit belongs to another activation')
                if type(entry_segment.ingress) is not InitialEntry:
                    ctx.issue('call_entry_ingress', row.id, 'callee entry must be its initial entry visit, not resume/capture ingress')
                if entry_visit.block != callee.entry:
                    ctx.issue('call_entry_block', row.id, 'entry visit is not the canonical callee region entry block')
                if entry_visit.id in ctx.incoming:
                    ctx.issue('call_entry_predecessor', row.id, 'initial callee entry visit cannot be selected through an ordinary backedge')
        else:
            _point_scope(ctx, row.entry, row.activation, row.id, route_gaps)
            _record_gap(ctx, route_gaps, 'call_entry_unobserved', row.id,
                        'callee initial entry visit is unresolved')

        completion_kind = _terminal_kind(ctx, row, operation)
        captured_terminals = terminal_occurrences_by_activation.get(row.activation, ())
        if len(captured_terminals) > 1:
            ctx.issue('call_multiple_completion', row.id,
                      'one synchronous activation cannot have multiple captured RETURN/RAISE occurrences')
        if type(row.completion) is Unresolved:
            _point_scope(ctx, row.completion, row.activation, row.id, route_gaps)
            _record_gap(ctx, route_gaps, 'call_completion_unobserved', row.id,
                        'callee actual RETURN/RAISE occurrence is unresolved')

        if type(row.entry) is BlockVisitID and type(row.completion) is OperationOccurrenceID:
            completion_occ = ctx.occurrences.get(row.completion)
            if completion_occ is not None and ctx.activation_of(completion_occ.id) == row.activation:
                if not _path_exists(visit_chains, row.entry, completion_occ.visit):
                    _record_gap(ctx, route_gaps, 'call_path_unobserved', row.id,
                                'no captured CFG path connects the callee initial entry and actual completion')

        _record_gap(ctx, route_gaps, 'call_source_runtime_unverified', row.id,
                    'association provenance does not establish runtime identity or value correspondence')

        inputs = _inputs(ctx, row, caller, operation, callee, route_gaps)
        outputs = _outputs(ctx, row, caller, operation, completion_kind, route_gaps)
        entry_record = None if type(row.entry) is Unresolved else ctx.visits.get(row.entry)
        completion_record = (None if type(row.completion) is Unresolved
                             else ctx.occurrences.get(row.completion))
        ctx.resolved_call_activations[row.id] = {
            'association': row,
            'caller': caller,
            'activation': activation,
            'entry': entry_record,
            'completion': completion_record,
            'inputs': inputs,
            'outputs': outputs,
            'gaps': tuple(route_gaps),
        }

    for caller_id, occurrence in ctx.occurrences.items():
        operation = ctx.core_operations[occurrence.operation]
        if operation.callee is not None and caller_id not in rows_by_caller:
            ctx.gap('call_activation_missing', caller_id,
                    'static callee occurrence has no declared dynamic activation association')
        if len(rows_by_caller.get(caller_id, ())) > 1:
            ctx.issue('call_caller_reused', caller_id, 'one caller occurrence has multiple call activation records')
    ctx.call_activations_by_caller = {key: tuple(value) for key, value in rows_by_caller.items()}

    # Dynamic synchronous nesting must be acyclic, but static recursion is
    # legal because each recursive invocation receives a fresh activation.
    activations = set(ctx.activations)
    children = {identity: [] for identity in activations}
    indegree = {identity: 0 for identity in activations}
    for parent, child, row_id in dependency_edges:
        if parent not in activations or child not in activations:
            continue
        children[parent].append((child, row_id))
        indegree[child] += 1
    ready = deque(identity for identity, degree in indegree.items() if degree == 0)
    visited = 0
    while ready:
        parent = ready.popleft()
        visited += 1
        for child, _row_id in children[parent]:
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
    if visited != len(activations):
        cyclic = {identity for identity, degree in indegree.items() if degree > 0}
        ctx.issue('call_activation_cycle', 'call_activations',
                  'dynamic synchronous call nesting must use distinct acyclic activation frames')


__all__ = ['call_errors']
