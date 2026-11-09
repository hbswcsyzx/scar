"""Trace derived returns only in their recorded complete caller stacks.

Historical interfaces remain general may alternatives. A namespace/member
interface derived in one parent frame is not reusable as a return candidate
in another frame merely because both share an original source result port.
"""
from collections import defaultdict

from scar.analysis.source_call_contexts import ContextReferenceEngine, _Query
from scar.analysis.source_reference_slice import source_port, DECLARED
from scar.ir.program import source_call_contexts as X, source_reference_slices as R
from scar.ir.program import normal_targets as T, normal_links as F


class StackedReferenceEngine(ContextReferenceEngine):
    def __init__(self, snapshot):
        super().__init__(snapshot)
        self._general = set(); self._allowed = defaultdict(set)
        self._scopes = []; self._scope_ids = set()

    @property
    def scopes(self):
        """Stable (incoming interface ordinal, complete allowed caller stack).

        General/historical admission takes precedence over these restrictions.
        Replay general records with admit(), and derived records with
        admit_contextual(); admitting every record generally cannot later be
        undone by adding scope records.
        """
        return tuple(self._scopes)

    def _stack(self, values):
        stack = tuple(values)
        if any(type(i) is not int or not 0 <= i < len(self.interfaces) for i in stack):
            raise ValueError('selected caller stack contains an absent interface')
        return stack

    def admit(self, evidence, link):
        """Preserve ordinary admission, including historical batch indexing."""
        incoming = super().admit(evidence, link)
        self._general.add(incoming)
        return incoming

    def admit_contextual(self, evidence, link, outer):
        """Accumulate allowed caller stacks without narrowing a general row."""
        outer = self._stack(outer)
        # Deliberately bypass our general-admission override. The base method
        # preserves IDs and still rejects conflicting links for one evidence.
        incoming = super().admit(evidence, link)
        self._allowed[incoming].add(outer)
        record = incoming, outer
        if record not in self._scope_ids:
            self._scope_ids.add(record); self._scopes.append(record)
        return incoming

    def selected_returns(self, point, stack):
        """Return general candidates or exact complete-caller-stack matches."""
        stack = self._stack(stack)
        return tuple((incoming, origin) for incoming, origin in self.returns.get(point, ())
            if incoming in self._general or stack in self._allowed.get(incoming, ()))

    def _unselected_derived_returns(self, point, stack):
        return any(incoming not in self._general and stack not in self._allowed.get(incoming, ())
            for incoming, _ in self.returns.get(point, ()))

    def solve(self, requests, *, max_states=4000, max_depth=24):
        """The inherited two-field request API must use the same filtering."""
        return self.solve_stacks(((incoming, point, ()) for incoming, point in requests),
            max_states=max_states, max_depth=max_depth)

    def solve_stacks(self, requests, *, max_states=4000, max_depth=24):
        queries = []
        for incoming, point, outer in requests:
            outer = self._stack(outer)
            query = _StackedQuery(self, incoming, point, max_states, max_depth)
            root = X.ContextReferenceState(point, (*outer, incoming))
            query.states = [root]; query.ids = {root: 0}; queries.append(query)
        while True:
            waiting = defaultdict(list)
            for query in queries: query.advance(waiting)
            if not waiting: break
            self.index(waiting)
            for work in waiting.values():
                for query, state in work: query.pending.append(state)
        self.snapshot.validate_parents()
        return tuple(query.finish() for query in queries)


class _StackedQuery(_Query):
    def advance(self, waiting):
        """Keep the frozen query's rules, replacing its two return lookups.

        The original _Query.advance reads engine.returns directly and offers
        no return-selection hook. An explicit copy keeps the original formal
        pop, scope/capture, construction and budget boundaries unchanged while
        routing both return iteration and missing-return handling through the
        caller-stack filter. The old producer and its pins remain untouched.
        """
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
            candidates = engine.selected_returns(point, stack)
            for identity, origin in candidates:
                if len(stack) >= self.max_depth:
                    self.frontier(index, 'CONTEXT_REFERENCE_CALL_DEPTH_FRONTIER'); continue
                record = engine.interfaces[identity]
                self.edge(index, origin, (*stack, identity), R.ReferenceTransitionKind.DATA_RETURN_ENTER_CALL,
                    (record.evidence,), (*record.link.conditions, 'RETURN_AND_PARAMETER_USE_SAME_SELECTED_INTERFACE'))
            if not candidates and engine._unselected_derived_returns(point, stack):
                self.frontier(index, 'DERIVED_RETURN_CALLER_CONTEXT_NOT_SELECTED')
            elif local in results and not candidates:
                self.frontier(index, 'SOURCE_CALL_RESULT_OR_PROTOCOL_UNRESOLVED')
            if local in terminals:
                kind, table, ordinal = terminals[local]
                self.origins.append(R.ReferenceOrigin(index, R.ReferenceOriginKind(kind), None,
                    (engine.slicer.fact(unit, table, ordinal),), DECLARED)); terminal = True
            if len(self.edges) == before and not terminal and len(self.frontiers) == before_frontiers:
                self.frontier(index, 'REFERENCE_PRODUCER_OR_FRAME_INTERFACE_UNRESOLVED')
