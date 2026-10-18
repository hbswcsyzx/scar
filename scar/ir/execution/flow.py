"""Derive host occurrence flow from canonical ports, never a second SSA graph.

One block visit is one traversal of its static block. A static loop therefore
has fresh visits and fresh definitions on each traversal. Absent observations
are gaps, not fictitious writes, values, edges, or device ordering guarantees.
"""
from collections import deque

from scar.ir.program.model import BlockArgument, LiteralOrigin, OperationResult, StateVersionValue, TerminatorKind
from scar.ir.program.resumption import SuspendTerminator
from .common import Unresolved
from .coordinates import CaptureIngress, InitialEntry, ResumeIngress


def _transfers(ctx):
    for transfer in ctx.model.transfers:
        occurrence = ctx.occurrences.get(transfer.operation)
        target = ctx.visits.get(transfer.target)
        if occurrence is None or target is None:
            ctx.issue('transfer_endpoint', 'transfers', 'transfer needs existing source occurrence and target visit')
            continue
        op = ctx.core_operations[occurrence.operation]
        term = op.terminator
        if term is None or transfer.successor_index >= len(term.successors):
            ctx.issue('transfer_successor', occurrence.id, 'transfer does not select a canonical successor')
            continue
        successor = term.successors[transfer.successor_index]
        if target.block != successor.block:
            ctx.issue('transfer_block', occurrence.id, 'target visit is not the selected successor block')
        if ctx.activation_of(occurrence.id) != ctx.segments[target.segment].activation:
            ctx.issue('transfer_activation', occurrence.id, 'ordinary and resume edges stay in their body activation')
        source_segment = ctx.visits[occurrence.visit].segment
        if type(term) is SuspendTerminator:
            ingress = ctx.segments[target.segment].ingress
            if (source_segment == target.segment or type(ingress) is not ResumeIngress
                    or ingress.suspension != occurrence.id
                    or ingress.successor_index != transfer.successor_index):
                ctx.issue('transfer_resume', occurrence.id, 'temporal edge requires its exact new resume segment')
        elif source_segment != target.segment:
            ctx.issue('transfer_segment', occurrence.id, 'ordinary CFG edge cannot switch execution segments')
        if occurrence.id in ctx.outgoing:
            ctx.issue('transfer_fork', occurrence.id, 'one occurrence cannot take two transfers')
        if target.id in ctx.incoming:
            ctx.issue('transfer_join', target.id, 'one visit cannot have two incoming executions')
        ctx.outgoing[occurrence.id] = transfer
        ctx.incoming[target.id] = transfer


def _ordered_visits(ctx):
    children = {key: [] for key in ctx.visits}
    indegree = {key: 0 for key in ctx.visits}
    for transfer in ctx.model.transfers:
        source = ctx.occurrences[transfer.operation].visit
        children[source].append(transfer.target)
        indegree[transfer.target] += 1
    queue = deque(key for key, degree in indegree.items() if not degree)
    result = []
    while queue:
        identity = queue.popleft()
        result.append(identity)
        for child in children[identity]:
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    if len(result) != len(ctx.visits):
        ctx.issue('visit_cycle', 'transfers', 'an execution cycle must use new visits, not revisit the same occurrence identity')
    return result


def _segments(ctx):
    initial = set()
    for segment in ctx.model.segments:
        ingress = segment.ingress
        visits = [row for row in ctx.model.visits if row.segment == segment.id]
        if type(ingress) is InitialEntry:
            if segment.activation in initial:
                ctx.issue('activation_reentry', segment.id, 'one activation cannot have two initial entries')
            initial.add(segment.activation)
            entry = ctx.regions[ctx.activations[segment.activation].region].entry
            roots = [row for row in visits if row.id not in ctx.incoming]
            if not roots or not any(row.block == entry for row in roots):
                ctx.gap('initial_entry_unobserved', segment.id, 'initial region entry visit has not been recorded')
            elif sum(row.block == entry for row in roots) > 1:
                ctx.gap('initial_entry_ambiguous', segment.id, 'multiple disconnected entry visits have no unique initial-entry correspondence')
        elif type(ingress) is ResumeIngress:
            source = ctx.occurrences.get(ingress.suspension)
            if source is None:
                ctx.issue('resume_source', segment.id, 'resume refers to a missing suspension occurrence')
                continue
            op = ctx.core_operations[source.operation]
            if (type(op.terminator) is not SuspendTerminator
                    or ingress.successor_index >= len(op.terminator.successors)
                    or ctx.activation_of(source.id) != segment.activation):
                ctx.issue('resume_source', segment.id, 'resume needs a canonical suspension and successor in this activation')
                continue
            transfer = ctx.outgoing.get(source.id)
            if transfer is None:
                ctx.gap('resume_transfer_unobserved', segment.id, 'resume ingress has no recorded temporal transfer')
            elif ctx.visits[transfer.target].segment != segment.id or transfer.successor_index != ingress.successor_index:
                ctx.issue('resume_transfer', segment.id, 'resume ingress does not match the actual transfer')
        # An unmatched block is representable as a capture gap, never an implied path.
        for visit in visits:
            if visit.id in ctx.incoming:
                continue
            is_entry = (type(ingress) is InitialEntry
                        and visit.block == ctx.regions[ctx.activations[segment.activation].region].entry)
            if not is_entry:
                ctx.gap('visit_ingress_unobserved', visit.id, 'no recorded incoming path establishes this visit')


def _operand(ctx, occurrence, use, environment, definitions):
    binding = ctx.uses.get((occurrence.id, use.id))
    if binding is None:
        ctx.gap('use_unobserved', occurrence.id, f'no binding for canonical Use {use.id}')
        return
    if type(binding.value) is Unresolved:
        return
    actual = ctx.values[binding.value]
    static = ctx.core_values[use.value]
    expected_visit = definitions.get(use.value)
    actual_visit = (ctx.occurrences[actual.origin].visit
                    if actual.origin in ctx.occurrences else actual.origin)
    if expected_visit is not None and actual_visit != expected_visit:
        ctx.issue('stale_incarnation', use.id, 'operand comes from an older definition traversal, even if its current producer was not captured')
        return
    # A formal and a result redefined in this block cannot denote an older
    # traversal, even if this producer itself was omitted from the capture.
    if isinstance(static.origin, BlockArgument) and static.origin.block == ctx.visits[occurrence.visit].block:
        if actual.origin != occurrence.visit:
            ctx.issue('stale_incarnation', use.id, 'operand binds a formal from another block traversal')
            return
    if isinstance(static.origin, OperationResult):
        block = ctx.operation_blocks[static.origin.operation]
        if block.id == ctx.visits[occurrence.visit].block:
            producer = ctx.occurrences.get(actual.origin)
            if producer is None or producer.visit != occurrence.visit:
                ctx.issue('stale_incarnation', use.id, 'operand binds a result from another block traversal')
                return
    expected = environment.get(use.value)
    if expected is None:
        ctx.gap('definition_unobserved', use.id, 'the current definition is not established along the captured path')
    elif expected != binding.value:
        ctx.issue('stale_incarnation', use.id, 'operand is not the current canonical definition on this dynamic path')


def derive_flow(ctx):
    _transfers(ctx)
    if ctx.issues:
        return
    ordered = _ordered_visits(ctx)
    _segments(ctx)
    if ctx.issues:
        return
    occurrences = {(row.visit, row.operation): row for row in ctx.model.operations}
    literals = {}
    for row in ctx.model.values:
        if isinstance(ctx.core_values[row.value].origin, LiteralOrigin):
            literals.setdefault(row.origin, {})[row.value] = row.id
    end_env, end_state, end_definitions, end_state_definitions = {}, {}, {}, {}
    for identity in ordered:
        visit = ctx.visits[identity]
        activation = ctx.segments[visit.segment].activation
        incoming = ctx.incoming.get(identity)
        predecessor = None if incoming is None else ctx.occurrences[incoming.operation].visit
        environment = {} if predecessor is None else dict(end_env[predecessor])
        state = {} if predecessor is None else dict(end_state[predecessor])
        definitions = {} if predecessor is None else dict(end_definitions[predecessor])
        state_definitions = {} if predecessor is None else dict(end_state_definitions[predecessor])
        environment.update(literals.get(activation, {}))
        definitions.update({value: activation for value in literals.get(activation, {})})
        block = ctx.blocks[visit.block]
        # Results and formals are killed before each new traversal of a block.
        for op_id in block.operations:
            for result in ctx.core_operations[op_id].results:
                environment[result] = None
                definitions[result] = visit.id
        for formal in block.arguments:
            row = ctx.results.get((visit.id, formal))
            environment[formal] = None if row is None else row.id
            definitions[formal] = visit.id
            if row is None:
                ctx.gap('formal_unobserved', visit.id, f'no occurrence for block formal {formal}')
            value = ctx.core_values[formal]
            if isinstance(value, StateVersionValue):
                state[value.location] = None if row is None else row.id
                state_definitions[value.location] = (formal, visit.id)
        ctx.visit_environments[identity] = dict(environment)
        if incoming is not None:
            ctx.edges[incoming.operation, incoming.successor_index] = dict(state)
            ctx.state_definitions_edges[incoming.operation, incoming.successor_index] = dict(state_definitions)
        for static_id in block.operations:
            op = ctx.core_operations[static_id]
            occurrence = occurrences.get((visit.id, op.id))
            if occurrence is None:
                ctx.gap('operation_unobserved', visit.id, f'no occurrence for canonical operation {op.id}')
            else:
                ctx.before[occurrence.id] = dict(state)
                ctx.state_definitions_before[occurrence.id] = dict(state_definitions)
                for use in op.uses:
                    _operand(ctx, occurrence, use, environment, definitions)
            for value_id in op.results:
                row = None if occurrence is None else ctx.results.get((occurrence.id, value_id))
                environment[value_id] = None if row is None else row.id
                if row is None and occurrence is not None:
                    ctx.gap('result_unobserved', occurrence.id, f'no occurrence for result {value_id}')
            for access in op.accesses:
                if access.after is not None:
                    state[access.location] = environment.get(access.after)
                    state_definitions[access.location] = (access.after, visit.id)
            if op.terminator is not None and op.terminator.kind in (TerminatorKind.INVOKE, TerminatorKind.BODY_DRIVE):
                # Outcomes have different state ports. There is no ordinary
                # common AFTER state, including on a failing/partial call.
                state = {location: None for location in state}
                state_definitions = {location: None for location in state_definitions}
            if occurrence is not None:
                ctx.after[occurrence.id] = dict(state)
                ctx.state_definitions_after[occurrence.id] = dict(state_definitions)
        end_env[identity], end_state[identity] = environment, state
        end_definitions[identity] = definitions
        end_state_definitions[identity] = state_definitions


__all__ = ['derive_flow']
