"""Budgeted projections of original execution ports, never another use graph.

This internal query does not detach: the public composition query owns its one
final copy.  DERIVED means the supplied observed rows were scanned, not that
capture, effects, identity, or the whole program has been proved complete.
"""
from __future__ import annotations

from scar.ir.program.control import PendingPayload
from scar.ir.program.drivers import BodyDriveResult
from scar.ir.program.driver_flow import body_outcome_uses
from scar.ir.program.ids import UseID
from scar.ir.program.model import BlockArgument, CompletionResult
from scar.ir.program.resumption import ResumeInput, SavedInput, saved_actual_use

from .common import Unresolved
from .validity_budget import ValidityBudget
from .validation import ExecutionIssue


class _Routes:
    def __init__(self, ctx, budget):
        if type(budget) is not ValidityBudget:
            raise TypeError('routes requires an exact shared ValidityBudget')
        self.ctx, self.budget = ctx, budget
        self.operations, self.values, self.transfers, self.calls = [], [], [], []
        self.gaps, self.cursor = [], None
        self.visited = {'operations': 0, 'values': 0, 'transfers': 0, 'calls': 0,
                        'uses': 0, 'results': 0, 'accesses': 0, 'arguments': 0,
                        'call_inputs': 0, 'call_outputs': 0, 'call_scan': 0}

    def spend(self, kind, path):
        if self.cursor is not None:
            return False
        if self.budget.spend('composition_' + kind, path=path):
            return True
        self.cursor = {'stage': kind, 'path': path}
        self.gaps.append(ExecutionIssue('composition_budget_exhausted', path,
                         'shared traversal budget exhausted; unvisited rows remain in the inventory'))
        return False

    def gap(self, code, path, message):
        self.gaps.append(ExecutionIssue(code, str(path), message))

    def value(self, identity):
        return identity if type(identity) is Unresolved else self.ctx.values.get(identity)

    def use(self, occurrence, identity):
        definition = self.ctx.core_uses[identity][1]
        actual = self.ctx.uses.get((occurrence, identity))
        value = None if actual is None else self.value(actual.value)
        if actual is None:
            self.gap('composition_use_unobserved', occurrence,
                     f'original input port {identity} has no captured UseOccurrence')
        elif type(actual.value) is Unresolved:
            self.gap('composition_use_unresolved', occurrence,
                     f'original input port {identity} has an unresolved actual')
        return {'definition': definition, 'actual': actual, 'value': value}

    def argument(self, occurrence, operation, successor, argument, destination):
        """Keep projections with no copy Use as real typed boundary relations."""
        source = saved_actual_use(operation, argument)
        result = {'argument': argument, 'kind': type(argument).__name__,
                  'source': None if source is None else self.use(occurrence.id, source),
                  'projection': None}
        if isinstance(argument, UseID) or type(argument) is SavedInput:
            return result
        if type(argument) is CompletionResult:
            signature = next((row for row in operation.completions
                              if row.kind is successor.kind), None)
            result['projection'] = {'completion': signature, 'index': argument.index,
                                    'exit_kind': successor.kind}
        elif type(argument) is BodyDriveResult:
            original = self.ctx.core_operations[successor.source]
            identity = body_outcome_uses(original)[argument.index]
            result['projection'] = {'operation': original,
                'use': self.ctx.core_uses[identity][1], 'index': argument.index,
                'dynamic_occurrence': None}
        elif type(argument) is ResumeInput:
            result['projection'] = {'slot': successor.inputs[argument.resume_slot],
                'index': argument.resume_slot,
                'ingress': self.ctx.segments[destination.segment].ingress}
        elif type(argument) is PendingPayload:
            pending = operation.terminator.pending
            result['projection'] = {'pending': self.use(occurrence.id, pending),
                                    'port': successor.port}
        else:
            self.gap('composition_argument_unsupported', occurrence.id,
                     f'original {type(argument).__name__} marker retained without an interpretation')
        return result

    def scan_operations(self):
        ctx = self.ctx
        for number, row in enumerate(ctx.model.operations):
            path = f'operations[{number}]'
            if not self.spend('operations', path):
                return
            self.visited['operations'] += 1
            definition = ctx.core_operations[row.operation]
            visit = ctx.visits[row.visit]
            segment = ctx.segments[visit.segment]
            item = {'occurrence': row, 'definition': definition, 'visit': visit,
                'segment': segment, 'activation': ctx.activations[segment.activation],
                'uses': [], 'results': [], 'accesses': [],
                'before': ctx.before.get(row.id), 'after': ctx.after.get(row.id),
                'effects_complete': definition.effects_complete, 'scan_complete': False}
            self.operations.append(item)
            for ordinal, use in enumerate(definition.uses):
                if not self.spend('uses', f'{path}.uses[{ordinal}]'):
                    return
                self.visited['uses'] += 1
                item['uses'].append({'ordinal': ordinal, **self.use(row.id, use.id)})
            for ordinal, identity in enumerate(definition.results):
                if not self.spend('results', f'{path}.results[{ordinal}]'):
                    return
                self.visited['results'] += 1
                actual = ctx.results.get((row.id, identity))
                item['results'].append({'ordinal': ordinal,
                    'definition': ctx.core_values[identity], 'actual': actual})
                if actual is None:
                    self.gap('composition_result_unobserved', row.id,
                             f'original result port {identity} has no captured value')
            for index, access in enumerate(definition.accesses):
                if not self.spend('accesses', f'{path}.accesses[{index}]'):
                    return
                self.visited['accesses'] += 1
                item['accesses'].append({'index': index, 'access': access,
                    'before': self.use(row.id, access.before),
                    'reference': None if access.reference is None else self.use(row.id, access.reference),
                    'after_definition': None if access.after is None else ctx.core_values[access.after],
                    'after': None if access.after is None else ctx.results.get((row.id, access.after))})
            item['scan_complete'] = True

    def scan_values(self):
        ctx = self.ctx
        for number, row in enumerate(ctx.model.values):
            path = f'values[{number}]'
            if not self.spend('values', path):
                return
            self.visited['values'] += 1
            definition = ctx.core_values[row.value]
            # Exactly the original definition endpoint: never an identity union.
            producer = (ctx.occurrences.get(row.origin) or ctx.visits.get(row.origin)
                        or ctx.activations.get(row.origin))
            route = None
            if isinstance(definition.origin, BlockArgument):
                visit = ctx.visits[row.origin]
                transfer = ctx.incoming.get(row.origin)
                route = {'transfer': transfer, 'argument': None,
                         'ordinal': definition.origin.index,
                         'ingress': ctx.segments[visit.segment].ingress}
                if transfer is not None:
                    occurrence = ctx.occurrences[transfer.operation]
                    operation = ctx.core_operations[occurrence.operation]
                    successor = operation.terminator.successors[transfer.successor_index]
                    route = {'transfer': transfer,
                        'argument': successor.arguments[definition.origin.index],
                        'ordinal': definition.origin.index,
                        'ingress': ctx.segments[visit.segment].ingress}
            self.values.append({'value': row, 'definition': definition,
                                'producer': producer, 'formal_route': route})

    def scan_transfers(self):
        ctx = self.ctx
        for number, transfer in enumerate(ctx.model.transfers):
            path = f'transfers[{number}]'
            if not self.spend('transfers', path):
                return
            self.visited['transfers'] += 1
            occurrence = ctx.occurrences[transfer.operation]
            operation = ctx.core_operations[occurrence.operation]
            successor = operation.terminator.successors[transfer.successor_index]
            destination = ctx.visits[transfer.target]
            block = ctx.blocks[destination.block]
            item = {'transfer': transfer, 'occurrence': occurrence,
                'operation': operation, 'terminator': operation.terminator,
                'successor': successor, 'destination': destination,
                'arguments': [], 'state': ctx.edges.get((occurrence.id, transfer.successor_index)),
                'scan_complete': False}
            self.transfers.append(item)
            for ordinal, argument in enumerate(successor.arguments):
                if not self.spend('arguments', f'{path}.arguments[{ordinal}]'):
                    return
                self.visited['arguments'] += 1
                identity = block.arguments[ordinal]
                item['arguments'].append({'ordinal': ordinal,
                    'formal_definition': ctx.core_values[identity],
                    'formal': ctx.results.get((destination.id, identity)),
                    **self.argument(occurrence, operation, successor, argument, destination)})
            item['scan_complete'] = True

    def scan_calls(self):
        ctx = self.ctx
        # Iterate original observed calls, preserving the empty-link case.
        for number, caller in enumerate(ctx.model.operations):
            if not self.spend('call_scan', f'call_scan[{number}]'):
                return
            self.visited['call_scan'] += 1
            operation = ctx.core_operations[caller.operation]
            links = ctx.call_activations_by_caller.get(caller.id, ())
            if operation.callee is None and not links:
                continue
            if not links:
                if not self.spend('calls', f'calls[{caller.id}]'):
                    return
                self.visited['calls'] += 1
                gap = ExecutionIssue('call_activation_missing', str(caller.id),
                                     'static callee has no declared dynamic activation link')
                self.calls.append({'caller': caller, 'operation': operation,
                    'callee': ctx.regions[operation.callee], 'association': None,
                    'status': 'MISSING', 'inputs': (), 'outputs': (), 'gaps': (gap,),
                    'scan_complete': True})
                continue
            for identity in links:
                path = f'calls[{identity}]'
                if not self.spend('calls', path):
                    return
                self.visited['calls'] += 1
                original = ctx.resolved_call_activations[identity]
                item = {**original, 'operation': operation,
                    'callee': ctx.regions[operation.callee],
                    'inputs': [], 'outputs': [], 'status': 'DECLARED', 'scan_complete': False}
                self.calls.append(item)
                for kind in ('inputs', 'outputs'):
                    for ordinal, route in enumerate(original[kind]):
                        if not self.spend('call_' + kind, f'{path}.{kind}[{ordinal}]'):
                            return
                        self.visited['call_' + kind] += 1
                        item[kind].append(route)
                item['scan_complete'] = True

    def result(self):
        ctx = self.ctx
        for collection in (self.operations, self.transfers, self.calls):
            for row in collection:
                for name in ('uses', 'results', 'accesses', 'arguments', 'inputs', 'outputs'):
                    if name in row and type(row[name]) is list:
                        row[name] = tuple(row[name])
        return {'operations': tuple(self.operations), 'values': tuple(self.values),
            'transfers': tuple(self.transfers), 'calls': tuple(self.calls),
            'gaps': tuple(self.gaps), 'status': 'TRUNCATED' if self.cursor is not None else 'DERIVED',
            'visited': self.visited,
            'pending': {'operations': len(ctx.model.operations) - self.visited['operations'],
                        'values': len(ctx.model.values) - self.visited['values'],
                        'transfers': len(ctx.model.transfers) - self.visited['transfers'],
                        'call_scan': len(ctx.model.operations) - self.visited['call_scan']},
            'cursor': self.cursor, 'budget_used': self.budget.used,
            'source_runtime_verified': False, 'runtime_identity_verified': False,
            'value_identity_verified': False, 'transformation_authorized': False}


def routes(ctx, *, budget: ValidityBudget) -> dict:
    """Project supplied observed ports; caller retains the complete inventory.

    All stages consume the same budget. Pending counts exclude partially read
    rows; ``cursor`` and each row's ``scan_complete`` flag retain that distinction.
    This function neither chooses roots nor classifies unreachable work as dead.
    """
    view = _Routes(ctx, budget)
    for scan in (view.scan_operations, view.scan_values, view.scan_transfers, view.scan_calls):
        if view.cursor is not None:
            break
        scan()
    return view.result()


__all__ = ['routes']
