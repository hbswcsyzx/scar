"""Query-local payload support over canonical pending carriers and ports.

Possibility is a separate least fixed point. Source support can therefore use
an all-incoming meet without either mixing different ports or treating an
unseeded case as a proof. These indexes contain only original IDs and edges.
"""
from collections import deque

from .cleanup import CleanupRouteTerminator
from .control import PendingDispatchTerminator, PendingPayload, ProtocolValueKind
from .model import OperationResult, ProtocolValue
from .resumption import SavedInput, SavedRole, saved_actual_use


def _index(ctx):
    found = getattr(ctx, '_pending_payload_index', None)
    if found is None:
        carriers, constructors = {}, {}
        for value in ctx.values.values():
            if isinstance(value, ProtocolValue) and value.protocol is ProtocolValueKind.PENDING_COMPLETION:
                carriers.setdefault(value.region, set()).add(value.id)
        for definition in ctx.graph.pending_completions:
            origin = ctx.values[definition.value].origin
            if type(origin) is OperationResult:
                constructors.setdefault(ctx.region_of[origin.operation], {})[origin.operation] = definition
        found = ({region: frozenset(values) for region, values in carriers.items()}, constructors)
        ctx._pending_payload_index = found
        ctx.preparation['pending_payload_carriers'] = sum(map(len, carriers.values()))
        ctx.preparation['pending_payload_constructors'] = sum(map(len, constructors.values()))
    return found


def has_pending_region(ctx, region):
    return region in _index(ctx)[0]


def prepare_pending_payload_flow(ctx, region, outgoing, incoming, order, guards):
    cache = getattr(ctx, '_pending_payload_flows', None)
    if cache is None:
        cache = ctx._pending_payload_flows = {}
    key = region, guards
    if key not in cache:
        carriers, constructors = _index(ctx)
        result = PendingPayloadFlow(ctx, region, carriers[region], constructors.get(region, {}))
        cache[key] = result if result.prepare(outgoing, incoming, order) else None
    return cache[key]


class PendingPayloadFlow:
    def __init__(self, ctx, region, carriers, constructors):
        self.ctx, self.region = ctx, region
        self.carriers, self.constructors = carriers, constructors
        self.before, self.edges = {}, {}
        self.assignments, self.selectors, self.projections = {}, {}, {}

    def prepare(self, outgoing, incoming, order):
        """Compute current possible (carrier, port) pairs, with bottom edges."""
        ctx = self.ctx
        for block in order:
            for identity, number, target, _ in outgoing[block]:
                operation = ctx.operations[identity]
                term = operation.terminator
                edge = term.successors[number]
                if not ctx.spend('pending_payload_edge_shapes', len(edge.arguments) + 1):
                    return False
                key = identity, number
                assignments, projections = {}, []
                for actual, formal in zip(edge.arguments, ctx.blocks[target].arguments):
                    if type(actual) is PendingPayload:
                        projections.append(formal)
                    if formal not in self.carriers:
                        continue
                    use = saved_actual_use(operation, actual)
                    if type(actual) is SavedInput and term.saved[actual.saved_slot].role is not SavedRole.PENDING_COMPLETION:
                        use = None
                    source = None if use is None else ctx.owned_use(identity, use).value
                    assignments[formal] = source if source in self.carriers else None
                self.assignments[key] = assignments
                self.projections[key] = tuple(projections)
                self.selectors[key] = ((ctx.owned_use(identity, term.pending).value, edge.port)
                    if type(term) in (PendingDispatchTerminator, CleanupRouteTerminator) else None)
                self.edges[key] = None

        queue, queued = deque(order), set(order)
        entry = ctx.regions[self.region].entry
        while queue:
            if not ctx.spend('pending_payload_possible_blocks'):
                return False
            block_id = queue.popleft()
            queued.remove(block_id)
            parents = [self.edges[(edge[0], edge[1])] for _, edge in incoming[block_id]
                       if (edge[0], edge[1]) in self.edges and self.edges[(edge[0], edge[1])] is not None]
            if block_id == entry:
                current = frozenset()
            elif parents:
                if not ctx.spend('pending_payload_possible_meet', sum(map(len, parents))):
                    return False
                current = frozenset.union(*parents)
            else:
                continue
            for identity in ctx.blocks[block_id].operations:
                if not ctx.spend('pending_payload_possible_operations'):
                    return False
                self.before[identity] = current
                operation = ctx.operations[identity]
                killed = self.carriers.intersection(operation.results)
                if killed:
                    if not ctx.spend('pending_payload_possible_kill', len(current)):
                        return False
                    current = frozenset(pair for pair in current if pair[0] not in killed)
                definition = self.constructors.get(identity)
                if definition is not None:
                    current = current.union(((definition.value, definition.port),))
            for identity, number, target, _ in outgoing[block_id]:
                key = identity, number
                if not ctx.spend('pending_payload_possible_edges', len(current) + len(self.assignments[key]) + 1):
                    return False
                renamed = self._rename(key, current, possible=True)
                if self.edges[key] != renamed:
                    self.edges[key] = renamed
                    if target not in queued:
                        queue.append(target)
                        queued.add(target)
        ctx.preparation['pending_payload_prepared_regions'] = len({
            region for region, _ in getattr(ctx, '_pending_payload_flows', {})
        } | {self.region})
        return True

    def _rename(self, key, current, *, possible=False):
        selector = self.selectors[key]
        if selector is not None:
            value, port = selector
            if possible and (value, port) not in current:
                return None
            current = frozenset(pair for pair in current if pair[0] != value or pair[1] == port)
        assignments = self.assignments[key]
        renamed = {pair for pair in current if pair[0] not in assignments}
        by_value = {}
        for value, port in current:
            by_value.setdefault(value, set()).add(port)
        for formal, source in assignments.items():
            renamed.update((formal, port) for port in by_value.get(source, ()))
        return frozenset(renamed)

    def meet(self, parents, supports, *, mode):
        """Only paths on which this exact carrier/port can occur participate."""
        possible = [self.edges[key] for key in parents]
        actual = [supports[key] for key in parents]
        if not self.ctx.spend('pending_payload_support_meet',
                              sum(map(len, possible)) + sum(map(len, actual))):
            return None
        if not possible:
            return frozenset()
        if mode == 'may':
            return frozenset.union(*actual)
        candidates = frozenset.union(*possible)
        bad = frozenset.union(*(choices.difference(good) for choices, good in zip(possible, actual)))
        return candidates.difference(bad)

    def operation(self, identity, copies, support):
        definition = self.constructors.get(identity)
        killed = self.carriers.intersection(self.ctx.operations[identity].results)
        if not killed and definition is None:
            return support
        if not self.ctx.spend('pending_payload_support_operations', len(support) + 1):
            return None
        support = frozenset(pair for pair in support if pair[0] not in killed)
        if definition is not None and definition.payload is not None:
            payload = self.ctx.owned_use(identity, definition.payload).value
            if payload in copies:
                support = support.union(((definition.value, definition.port),))
        return support

    def edge(self, key, support):
        if not self.ctx.spend('pending_payload_support_edges', len(support) + len(self.assignments[key]) + 1):
            return None
        selector = self.selectors[key]
        projected = self.projections[key] if selector is not None and selector in support else ()
        renamed = self._rename(key, support)
        return renamed.intersection(self.edges[key]), projected


__all__ = ['has_pending_region', 'prepare_pending_payload_flow']
