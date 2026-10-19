"""Query-local known-callee copy summaries over original CFG/SSA ports.

This is neither a second value graph nor a runtime identity analysis. Summaries
contain only callee-local projections; caller frames are constructed afresh.
"""
from collections import deque

from .model import CompletionResult, ExitKind, InvokeLiteralResult, OperationResult, TerminatorKind
from .native import ExitPortRef
from .protocol_flow import ProtocolFlow, ProtocolPort
from .protocols import OwnedUse
from .structured import ControlEdgeReference


class _NeedSummary(Exception):
    def __init__(self, key, port, guards, mode):
        self.key, self.port, self.guards, self.mode = key, port, guards, mode


class CallReturns:
    def __init__(self, context):
        self.ctx = context
        self.guards = ()
        self.summaries = {}
        self.summary_evidence = {}
        self.summary_gaps = {}
        self.call_evidence = {}
        self.export_projections = {}
        self.export_bundles = {}
        self.ancestor_relations = {}
        self.gaps = []
        self.gap_events = []
        self.callers = {}
        for operation in context.graph.operations:
            if operation.callee is not None:
                self.callers.setdefault(operation.callee, []).append(operation)
        context.preparation['call_return_caller_sites'] = sum(map(len, self.callers.values()))
        context.preparation['prepared_exit_port_inventory_reused'] = True

    def gap(self, code):
        self.gap_events.append(code)
        if code not in self.gaps:
            self.gaps.append(code)

    def flow(self, port, *, guard=None, mode='must'):
        """Iterative dependency solver; recursion remains an explicit gap."""
        ctx = self.ctx
        previous = self.guards
        self.guards = previous or ctx.selected_edges(guard)
        jobs = [(None, port, guard, mode, len(self.gap_events))]
        active = set()
        try:
            while jobs:
                key, source, choices, current_mode, gap_start = jobs[-1]
                try:
                    before = ProtocolFlow._fresh_copies(ctx, source, guard=choices, mode=current_mode)
                except _NeedSummary as need:
                    # The original flow charges its actual CFG work and has
                    # always reused completed cache hits without recharging.
                    # Charge new dependency scheduling, not an extra graph job
                    # for every already completed local flow lookup.
                    if not ctx.spend('call_return_jobs'):
                        return None
                    if need.key in active:
                        self.gap('call_return_recursion_unresolved')
                        self.summaries[need.key] = None
                        self.summary_gaps[need.key] = ('call_return_recursion_unresolved',)
                    else:
                        active.add(need.key)
                        jobs.append((need.key, need.port, need.guards, need.mode, len(self.gap_events)))
                    continue
                jobs.pop()
                if key is None:
                    return before
                self.summaries[key] = (None if before is None else
                    self.project(ctx.region_of[source.operation], before, current_mode,
                                 summary_key=key))
                self.summary_gaps[key] = tuple(dict.fromkeys(self.gap_events[gap_start:]))
                active.remove(key)
            return None
        finally:
            self.guards = previous

    def project(self, region, before, mode='must', *, summary_key=None, evidence_sink=None):
        """Every original reachable terminal at each kind/slot, no empty proof."""
        ctx, projected, evidence = self.ctx, {}, []
        for exit_ in ctx.regions[region].exits:
            if not ctx.spend('call_return_exit_kinds'):
                return None
            for ordinal in range(len(exit_.types)):
                statuses = []
                port = ExitPortRef(region, exit_.name, ordinal)
                if not ctx.spend('call_return_exit_slots'):
                    return None
                # Use the already prepared original inventory without a new
                # unmetered sort/tuple materialization on a tiny query budget.
                # Its table order is presentation, never execution order.
                sites = ctx.index._exit_ports[(region, exit_.name, ordinal)]
                terminals = []
                for site in sites:
                    if not ctx.spend('call_return_terminal_uses'):
                        return None
                    reached = site.operation in before
                    copied = site.use.value in before[site.operation] if reached else None
                    terminals.append({'use': OwnedUse(site.operation, site.use.id),
                        'value': site.use.value, 'reachable': reached, 'copy': copied})
                    if reached:
                        statuses.append(copied)
                if not statuses:
                    projected[exit_.kind, ordinal] = None
                    self.gap('call_return_terminal_unresolved')
                elif mode == 'may':
                    projected[exit_.kind, ordinal] = any(statuses)
                elif all(statuses):
                    projected[exit_.kind, ordinal] = True
                elif any(statuses):
                    projected[exit_.kind, ordinal] = None
                    self.gap('call_return_mixed_terminals')
                else:
                    projected[exit_.kind, ordinal] = False
                evidence.append({'exit': port, 'kind': exit_.kind, 'slot': ordinal,
                    'terminals': tuple(terminals), 'match': projected[exit_.kind, ordinal]})
        if summary_key is not None:
            self.summary_evidence[summary_key] = {'callee': region,
                'seeds': summary_key[1], 'mode': mode, 'guards': summary_key[3],
                'query_guards': summary_key[4], 'exits': tuple(evidence)}
        if evidence_sink is not None:
            evidence_sink.extend(evidence)
        return projected

    def transfer(self, operation, current, *, mode):
        ctx = self.ctx
        if operation.callee is None or not current:
            return frozenset(), {}
        invoke = operation.terminator is not None and operation.terminator.kind is TerminatorKind.INVOKE
        actuals = operation.invoke_arguments if invoke else operation.call_arguments
        formals = ctx.blocks[ctx.regions[operation.callee].entry].arguments
        if not ctx.spend('call_return_actuals', len(actuals)):
            return None
        seeds = tuple(formal for actual, formal in zip(actuals, formals)
                      if ctx.owned_use(operation.id, actual).value in current)
        if not seeds:
            return frozenset(), {}
        guards = ctx.selected_edges(self.guards, region=operation.callee)
        if guards and len(self.callers[operation.callee]) != 1:
            self.gap('call_return_guard_context_unresolved')
            return self.incomplete_bound(mode, 'call_return_guard_context_unresolved')
        # Descendant-region choices also affect a nested callee's projection.
        # Keeping only this callee's immediate guards would reuse a summary
        # computed under another nested helper's selected branch.
        key = operation.callee, seeds, mode, guards, self.guards
        if getattr(ctx, '_copy_consumer_bounds', False):
            key = (*key, 'copy-consumer-incomplete-bounds')
        if not ctx.spend('call_return_summaries'):
            return None
        if key not in self.summaries:
            entry = ctx.blocks[ctx.regions[operation.callee].entry]
            port = ProtocolPort(None, entry.operations[0], seeds, 'before')
            raise _NeedSummary(key, port, guards or None, mode)
        summary = self.summaries[key]
        for gap in self.summary_gaps.get(key, ()):
            self.gap(gap)
            if (getattr(ctx, '_copy_consumer_bounds', False)
                    and gap != 'call_return_mixed_terminals'):
                ctx._copy_consumer_bound_events.append((mode, gap))
        self.call_evidence[operation.id, key] = {'caller': operation.id,
            'caller_region': ctx.region_of[operation.id], 'callee': operation.callee,
            'summary_key': key, 'actual_formals': tuple((OwnedUse(operation.id, actual), formal)
                for actual, formal in zip(actuals, formals)
                if ctx.owned_use(operation.id, actual).value in current),
            'resolved': summary is not None}
        if summary is None:
            return self.incomplete_bound(mode, 'call_return_summary_unresolved')
        ordinary, completions = set(), {}
        if not invoke:
            for slot, value in enumerate(operation.results):
                if not ctx.spend('call_return_result_slots'):
                    return None
                status = summary.get((ExitKind.NORMAL, slot))
                if status is None:
                    if getattr(ctx, '_copy_consumer_bounds', False):
                        continue
                    return None
                if status:
                    ordinary.add(value)
        else:
            chosen = {edge.operation: edge.successor_index for edge in self.guards}
            for number, edge in enumerate(operation.terminator.successors):
                if not ctx.spend('call_return_completion_edges'):
                    return None
                if operation.id in chosen and chosen[operation.id] != number:
                    continue
                copies = set()
                for actual, formal in zip(edge.arguments, ctx.blocks[edge.block].arguments):
                    if not ctx.spend('call_return_completion_slots'):
                        return None
                    if type(actual) is CompletionResult:
                        status = summary.get((edge.kind, actual.index))
                        if status is None:
                            if getattr(ctx, '_copy_consumer_bounds', False):
                                continue
                            return None
                        if status:
                            copies.add(formal)
                completions[number] = frozenset(copies)
        return frozenset(ordinary), completions

    def incomplete_bound(self, mode, gap):
        """No invented result copies; only consumer queries admit this bound.

        Missing results make the may inventory incomplete. Negative membership
        under such a bound is UNKNOWN, never a non-copy proof. Ordinary binding
        and validation retain their existing all-or-unknown transfer.
        """
        if (not getattr(self.ctx, '_copy_consumer_bounds', False)
                or self.ctx.budget.truncated):
            return None
        self.ctx._copy_consumer_bound_events.append((mode, gap))
        return frozenset(), {}

    def output_ports(self, call, summary):
        """Exact fresh source ports, with slot independent of landing ordinal."""
        ctx = self.ctx
        invoke = call.terminator is not None and call.terminator.kind is TerminatorKind.INVOKE
        if not invoke:
            for slot in range(len(call.results)):
                if not ctx.spend('call_return_export_slots'):
                    return
                yield ExitKind.NORMAL, slot, None, OperationResult(call.id, slot), summary.get((ExitKind.NORMAL, slot))
        else:
            for edge_number, edge in enumerate(call.terminator.successors):
                if not ctx.spend('call_return_export_edges'):
                    return
                for actual in edge.arguments:
                    if not ctx.spend('call_return_export_slots'):
                        return
                    if type(actual) is CompletionResult:
                        port = InvokeLiteralResult(ControlEdgeReference(call.id, edge_number), actual)
                        yield edge.kind, actual.index, edge_number, port, summary.get((edge.kind, actual.index))

    def export_applicable(self, source_region, target_region):
        """Does an original caller ancestry reach the target region?"""
        key = source_region, target_region
        if key in self.ancestor_relations:
            return self.ancestor_relations[key]
        pending, visited = [source_region], set()
        while pending:
            region = pending.pop()
            if region in visited:
                continue
            visited.add(region)
            for call in self.callers.get(region, ()):
                if not self.ctx.spend('call_return_ancestors'):
                    return None
                parent = self.ctx.region_of[call.id]
                if parent == target_region:
                    self.ancestor_relations[key] = True
                    return True
                pending.append(parent)
        self.ancestor_relations[key] = False
        return False

    def export_bundle(self, call, summary, projection, *, guard, key):
        """Reuse one exact caller's ports, never another consumer's answer."""
        ctx = self.ctx
        key = key, call.id
        if key in self.export_bundles:
            return self.export_bundles[key]
        ordinary, completions, outputs, unknown = set(), {}, [], False
        selected = {edge.operation: edge.successor_index for edge in ctx.selected_edges(guard)}
        for kind, slot, edge, result, copied in self.output_ports(call, summary):
            if edge is not None and call.id in selected and selected[call.id] != edge:
                continue
            if copied is None:
                unknown = True
                continue
            if not copied:
                continue
            exact = ctx.port(result)
            if exact is None:
                unknown = True
                continue
            outputs.append({'kind': kind, 'slot': slot, 'edge': edge, 'result': result})
            if edge is None:
                ordinary.update(exact.values)
            else:
                completions.setdefault(edge, set()).update(exact.values)
        if ctx.budget.truncated:
            return None, None, True
        if not outputs:
            bundle = None, None, unknown
        else:
            frame = {'caller': call.id, 'caller_region': ctx.region_of[call.id],
                     'callee': call.callee, 'outputs': tuple(outputs),
                     'guards': ctx.selected_edges(guard, region=call.callee) or None,
                     'projection': tuple(projection)}
            lifted = ProtocolPort(None, call.id, tuple(sorted(ordinary, key=lambda value: value.wire)),
                'edges' if completions else 'after', completion_values=tuple(
                    (edge, tuple(sorted(values, key=lambda value: value.wire)))
                    for edge, values in sorted(completions.items())))
            bundle = lifted, frame, unknown
        self.export_bundles[key] = bundle
        return bundle

    def export(self, expected, port, actual, *, guard=None):
        """Lift an internal source only through unambiguous caller frames.

        A static source does not select one of several callers by inspecting
        the actual. Those cases require an occurrence/call-context contract.
        """
        from .protocol_connection_flow import _answer
        ctx, routes, unresolved = self.ctx, [], False
        pending = deque([(port, (), frozenset())])
        while pending:
            if not ctx.spend('call_return_exports'):
                return _answer(routes=routes, gaps=('call_return_budget_exhausted',),
                               cursor={'phase': 'call_return_exports', 'actual': actual})
            source, frames, visited = pending.popleft()
            region = ctx.region_of[source.operation]
            callers = self.callers.get(region, ())
            if len(callers) != 1:
                self.gap('call_return_caller_context_unresolved')
                unresolved = True
                continue
            call = callers[0]
            if call.id in visited:
                self.gap('call_return_export_cycle_unresolved')
                unresolved = True
                continue
            local = ctx.selected_edges(guard, region=region) or None
            projection_key = (source.operation, source.phase, source.edge, source.values,
                              source.completion_values, ctx.selected_edges(guard))
            if not ctx.spend('call_return_export_projections'):
                return _answer(routes=routes, gaps=('call_return_budget_exhausted',),
                               cursor={'phase': 'call_return_export_projection', 'actual': actual})
            if projection_key not in self.export_projections:
                gap_start = len(self.gap_events)
                before = self.flow(source, guard=local)
                projection = []
                summary = None if before is None else self.project(region, before, evidence_sink=projection)
                if not ctx.budget.truncated:
                    self.export_projections[projection_key] = (
                        summary, tuple(projection), tuple(dict.fromkeys(self.gap_events[gap_start:])))
            else:
                summary, projection, reasons = self.export_projections[projection_key]
                for gap in reasons:
                    self.gap(gap)
            if summary is None:
                unresolved = True
                continue
            lifted, frame, partial = self.export_bundle(call, summary, projection, guard=guard,
                                                        key=projection_key)
            unresolved |= partial
            if lifted is None:
                continue
            path = (*frames, frame)
            if ctx.region_of[call.id] == ctx.region_of[actual.operation]:
                future = (ctx.block_of[call.id] == ctx.block_of[actual.operation]
                          and ctx.positions[call.id] >= ctx.positions[actual.operation])
                local = ctx.selected_edges(guard, region=ctx.region_of[call.id]) or None
                flow = {} if future else self.flow(lifted, guard=local)
                match = None if flow is None else ctx.owned_use(actual.operation, actual.use).value in flow.get(actual.operation, ())
                routes.append({'source': expected, 'actual': actual, 'frames': path,
                               'match': match, 'guard': guard, 'context': None, 'choices': {}})
            else:
                pending.append((lifted, path, visited | {call.id}))
        if ctx.budget.truncated:
            return _answer(routes=routes, gaps=(*self.gaps, 'call_return_budget_exhausted'),
                           cursor={'phase': 'call_return_exports', 'actual': actual})
        # Each path already groups all known copies of this source at one
        # exact call. Different callers never enter this union.
        if any(route['match'] is True for route in routes):
            match = True
        elif unresolved or any(route['match'] is None for route in routes):
            match = None
        else:
            match = False
        return _answer(match, routes=routes, gaps=self.gaps if match is None else ())


def source_binding(index, expected, actual, *, guard=None, budget=4096):
    """Single-source, detached query; never grants transformation authority."""
    from scar.ir.execution.validity_budget import ValidityBudget
    from .protocol_connection_flow import ConnectionContext
    accounting = ValidityBudget(budget)
    ctx = ConnectionContext(index.graph, index=index, budget=accounting)
    port = ctx.port(expected)
    if port is not None and port.gap is None and len(port.values) != 1:
        raise ValueError('source_binding requires exactly one original source slot')
    report = ctx.bind(expected, actual, guard=guard)
    if accounting.truncated:
        report = {**report, 'match': None,
                  'gaps': (*report['gaps'], 'call_return_budget_exhausted'),
                  'cursor': report['cursor'] or {'phase': 'source_binding', 'actual': actual}}
    return {**report, 'budget': {'limit': accounting.limit, 'used': accounting.used,
            'truncated': accounting.truncated, 'costs': dict(accounting.costs)},
            'preparation': dict(ctx.preparation), 'native_applicability_verified': False,
            'selected_guards': ctx.selected_edges(guard), 'conditional': bool(ctx.selected_edges(guard)),
            'call_returns': {'summaries': tuple(ctx._returns.summary_evidence.values()),
                             'calls': tuple(ctx._returns.call_evidence.values())}}


__all__ = ['source_binding']
