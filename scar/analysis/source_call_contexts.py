"""Trace references through selected incoming source interfaces.

An unselected outer caller is a boundary. It never licenses merging every
actual ever passed to the same function. Calls returning references push the
exact candidate interface; its own parameters pop that same interface only.
"""
from collections import defaultdict, deque

from scar.analysis.source_reference_slice import ReferenceSlicer, source_port, DECLARED
from scar.ir.program import source_call_contexts as X, source_reference_slices as R
from scar.ir.program import normal_targets as T, normal_links as F, source_productions as P


class ContextReferenceEngine:
    def __init__(self, snapshot):
        self.snapshot = snapshot; self.slicer = ReferenceSlicer(snapshot)
        self.interfaces = []; self.ids = {}; self.indexed = set(); self.returns = defaultdict(list)
        self.by_result = defaultdict(list); self.locals = {}

    def admit(self, evidence, link):
        """Register a certified historical or declared source interface."""
        if evidence in self.ids:
            identity = self.ids[evidence]
            if self.interfaces[identity].link != link: raise ValueError('source interface evidence has conflicting records')
            return identity
        identity = len(self.interfaces); self.ids[evidence] = identity
        self.interfaces.append(X.CallInterfaceRecord(evidence, link)); self.by_result[link.result].append(identity)
        if link.mode not in ('SOURCE_CONSTRUCTION', 'SOURCE_INIT', 'SOURCE_NEW', 'CREATE_DEFERRED_BODY'):
            for origin, result in link.returns:
                if result == link.result and link.body is not None and link.source_callable is not None:
                    self.returns[result].append((identity, origin))
        return identity

    def index(self, units):
        """One full receipt-checked scan for each newly requested unit batch."""
        units = set(units)-self.indexed
        if not units: return
        for _, link, evidence in self.snapshot.rows('calls', lambda w: w['result']['unit'] in units, T.CallLink):
            self.admit(evidence, link)
        self.indexed.update(units)

    def unit(self, identity):
        if identity not in self.locals:
            unit, _, aliases, reads, writes, formals, terminals = self.slicer.unit(identity)
            owners = defaultdict(set)
            for group in unit.scope_groups:
                for span in group.tables:
                    if span.table is F.FactTable.NAMES:
                        for i in range(span.start, span.stop): owners[i].add(group.owner)
            self.locals[identity] = unit, aliases, reads, writes, formals, terminals, owners, {c.result for c in unit.calls}
        return self.locals[identity]

    def solve(self, requests, *, max_states=4000, max_depth=24):
        """Batch (incoming-interface ordinal, queried GlobalPort) requests.

        Indexing is deferred and batched when a reference reaches a previously
        unread call-result unit. Queries retain their worklist between scans.
        The stack contains static interface IDs, never dynamic invocations.
        """
        queries = [_Query(self, incoming, port, max_states, max_depth) for incoming, port in requests]
        while True:
            waiting = defaultdict(list)
            for query in queries: query.advance(waiting)
            if not waiting: break
            self.index(waiting)
            for unit, work in waiting.items():
                for query, state in work: query.pending.append(state)
        self.snapshot.validate_parents()
        return tuple(q.finish() for q in queries)


class _Query:
    def __init__(self, engine, incoming, port, max_states, max_depth):
        if (type(incoming) is not int or not 0 <= incoming < len(engine.interfaces)
                or type(port) is not T.GlobalPort or type(max_states) is not int or max_states < 1
                or type(max_depth) is not int or max_depth < 1):
            raise ValueError('context reference query requires an original incoming interface and positive limits')
        link = engine.interfaces[incoming].link
        if link.body is None or link.source_callable is None or link.body.unit != port.unit:
            raise ValueError('context reference seed has no matching source body')
        self.engine = engine; self.max_states = max_states; self.max_depth = max_depth
        root = X.ContextReferenceState(port, (incoming,))
        self.states = [root]; self.ids = {root: 0}; self.pending = deque((0,))
        self.edges = []; self.origins = []; self.frontiers = []; self.frontier_ids = set()

    def frontier(self, state, reason):
        if (state, reason) not in self.frontier_ids:
            self.frontier_ids.add((state, reason)); self.frontiers.append(R.ReferenceFrontier(state, reason))

    def edge(self, state, port, stack, kind, evidence, conditions):
        value = X.ContextReferenceState(port, stack)
        if value not in self.ids:
            if len(self.states) >= self.max_states:
                self.frontier(state, 'CONTEXT_REFERENCE_STATE_BUDGET_FRONTIER'); return
            self.ids[value] = len(self.states); self.states.append(value); self.pending.append(self.ids[value])
        self.edges.append(R.ReferenceTransition(state, self.ids[value], kind, tuple(evidence), tuple(conditions)))

    def advance(self, waiting):
        engine = self.engine
        while self.pending:
            index = self.pending.popleft(); state = self.states[index]; point = state.port; stack = state.interfaces
            if type(point) is not T.GlobalPort:
                self.frontier(index, 'CONSTRUCTION_ENDPOINT_REQUIRES_SEPARATE_PROTOCOL_FRAME'); continue
            unit, local = engine.slicer.local(point)
            unit, aliases, reads, writes, formals, terminals, owners, results = engine.unit(unit.unit)
            if local in results and point.unit not in engine.indexed:
                waiting[point.unit].append((self, index)); continue
            before = len(self.edges); before_frontiers = len(self.frontiers); terminal = False
            for source, ordinal in aliases.get(local, ()):
                self.edge(index, source_port(unit, source), stack, R.ReferenceTransitionKind.DECLARED_ALIAS,
                    (engine.slicer.fact(unit, 'aliases', ordinal),), DECLARED)
            for namespace, ordinal in reads.get(local, ()):
                if namespace.kind is not F.NamespaceKind.LEXICAL:
                    self.frontier(index, 'NON_LEXICAL_LOOKUP_REQUIRES_FRAME_NAMESPACE'); continue
                if len(owners[ordinal]) != 1:
                    self.frontier(index, 'LEXICAL_READ_CODE_SCOPE_UNRESOLVED'); continue
                accepted = False
                for source, writer in writes.get(namespace, ()):
                    if owners[writer] != owners[ordinal]:
                        self.frontier(index, 'CAPTURE_CREATION_FRAME_NOT_SELECTED'); continue
                    accepted = True
                    self.edge(index, source_port(unit, source), stack, R.ReferenceTransitionKind.LEXICAL_MAY_BINDING,
                        (engine.slicer.fact(unit, 'names', writer), engine.slicer.fact(unit, 'names', ordinal)),
                        (*DECLARED, 'SAME_CODE_SCOPE_LEXICAL_WRITE_SELECTED_NOT_CURRENT_VERSION'))
                if not accepted: self.frontier(index, 'LEXICAL_BINDING_PRODUCER_UNRESOLVED')
            if local in formals:
                fn = formals[local]
                if not stack:
                    self.frontier(index, 'OUTER_CALL_CONTEXT_NOT_SELECTED')
                else:
                    record = engine.interfaces[stack[-1]]; link = record.link
                    if (link.body != T.Body(unit.unit, fn.template, fn.body)
                            or link.source_callable != source_port(unit, fn.value)):
                        self.frontier(index, 'FORMAL_BELONGS_TO_UNSELECTED_CAPTURE_FRAME')
                    else:
                        routes = [r for r in link.parameters if r.formal == point]
                        if not routes: self.frontier(index, 'SELECTED_INTERFACE_HAS_NO_PARAMETER_ROUTE')
                        for route in routes:
                            if route.kind not in (T.RouteKind.ARGUMENT, T.RouteKind.INITIAL_DEFAULT):
                                self.frontier(index, 'NON_REFERENCE_PARAMETER_ROUTE_'+route.kind.value); continue
                            for actual in route.actuals:
                                guards = (*link.conditions, 'ONLY_SELECTED_INCOMING_INTERFACE_PARAMETER_ROUTE',
                                    'PARENT_CALL_CONTEXT_SELECTED_NOT_RUNTIME_INVOCATION')
                                if route.kind is T.RouteKind.INITIAL_DEFAULT:
                                    guards = (*guards, 'FUNCTION_DEFAULT_VERSION_MATCHES_DECLARATION')
                                self.edge(index, actual, stack[:-1], R.ReferenceTransitionKind(route.kind.value),
                                    (record.evidence,), guards)
            for identity, origin in engine.returns.get(point, ()):
                if len(stack) >= self.max_depth:
                    self.frontier(index, 'CONTEXT_REFERENCE_CALL_DEPTH_FRONTIER'); continue
                record = engine.interfaces[identity]
                self.edge(index, origin, (*stack, identity), R.ReferenceTransitionKind.DATA_RETURN_ENTER_CALL,
                    (record.evidence,), (*record.link.conditions, 'RETURN_AND_PARAMETER_USE_SAME_SELECTED_INTERFACE'))
            if local in results and not engine.returns.get(point):
                self.frontier(index, 'SOURCE_CALL_RESULT_OR_PROTOCOL_UNRESOLVED')
            if local in terminals:
                kind, table, ordinal = terminals[local]
                self.origins.append(R.ReferenceOrigin(index, R.ReferenceOriginKind(kind), None,
                    (engine.slicer.fact(unit, table, ordinal),), DECLARED)); terminal = True
            if len(self.edges) == before and not terminal and len(self.frontiers) == before_frontiers:
                self.frontier(index, 'REFERENCE_PRODUCER_OR_FRAME_INTERFACE_UNRESOLVED')

    def finish(self):
        return X.ContextReferenceSlice(tuple(self.states), tuple(self.edges), tuple(self.origins), tuple(self.frontiers))
