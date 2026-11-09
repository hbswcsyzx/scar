"""Reuse source descriptor binding along conditional, witnessed base paths."""
from collections import defaultdict, deque
from dataclasses import replace

from scar.analysis.source_class_bases import project_class_bases
from scar.analysis.source_constructor_members import ConstructorMemberResolver
from scar.analysis.source_reference_slice import ReferenceSlicer
from scar.ir.program import normal_targets as T, source_address_paths as A
from scar.ir.program import source_class_bases as B, source_inherited_members as I
from scar.ir.program.source_namespace_references import NamespaceOriginKind


_INHERITANCE_GUARDS = (
    'CURRENT_RUNTIME_BASES_SELECT_RECORDED_SOURCE_BASES',
    'CURRENT_MRO_SELECTS_RECORDED_BASE_PATH',
    'ALL_EARLIER_MRO_CLASSES_AND_INSTANCE_SLOTS_DO_NOT_SHADOW_MEMBER',
    'NO_C3_MRO_EXACT_RUNTIME_CLASS_OR_ALLOCATION_PROOF',
)


def _guards(*groups):
    return tuple(dict.fromkeys(value for group in groups for value in group))


class InheritedMemberResolver(ConstructorMemberResolver):
    """Keep receiver classes intact while looking up source base alternatives.

    descriptors() is compatible with expand_contexts(). lookup() returns the
    corresponding evidence records. A record-selection condition makes every
    returned DescriptorReference identifiable in graph().descriptors; the
    inherited conditions also enter the original binder's connection/edge.
    """

    def __init__(self, slicer, bases=None, *, max_classes=256, max_depth=32, max_states=4000):
        super().__init__(slicer)
        if any(type(n) is not int or n < 1 for n in (max_classes, max_depth, max_states)):
            raise ValueError('inherited lookup requires positive class, depth and state budgets')
        self.max_classes, self.max_depth, self.max_states = max_classes, max_depth, max_states
        self._base_queries = []; self._classes = {}; self._slots = {}
        self._lookups = {}; self._records = []; self._record_ids = {}
        self._frontiers = []; self._frontier_ids = set(); self._step_cache = {}
        if bases is not None:
            self._add_query(bases)

    @property
    def base_queries(self):
        return tuple(self._base_queries)

    @property
    def frontiers(self):
        return tuple(self._frontiers)

    def graph(self):
        return I.InheritedMemberGraph(self.base_queries, tuple(self._records), self.frontiers)

    def _frontier(self, receiver, member, reason):
        record = I.InheritedMemberFrontier(receiver, member, reason)
        if record not in self._frontier_ids:
            self._frontier_ids.add(record); self._frontiers.append(record)

    def _add_query(self, graph):
        if type(graph) is not B.ClassBaseGraph:
            raise TypeError('base queries must be original typed ClassBaseGraph projections')
        query = len(self._base_queries); classes = {}
        for owner, declaration in enumerate(graph.declarations):
            if declaration.source_class in self._classes or declaration.source_class in classes:
                raise ValueError('class has more than one original base query')
            classes[declaration.source_class] = query, owner
        slots = defaultdict(list)
        for ordinal, slot in enumerate(graph.slots):
            if not 0 <= slot.owner < len(graph.declarations):
                raise ValueError('base slot owner lies outside its original query')
            declaration = graph.declarations[slot.owner]
            if (not 0 <= slot.ordinal < len(declaration.bases)
                    or declaration.bases[slot.ordinal] != slot.expression):
                raise ValueError('base slot differs from its original ordered expression')
            slots[slot.owner].append(ordinal)
        for owner in range(len(graph.declarations)):
            indices = sorted(slots[owner], key=lambda i: graph.slots[i].ordinal)
            if tuple(graph.slots[i].ordinal for i in indices) != tuple(range(len(graph.declarations[owner].bases))):
                raise ValueError('base query omits or repeats an ordered base slot')
            self._slots[query, owner] = tuple(indices)
        self._base_queries.append(graph); self._classes.update(classes)

    def _class_query(self, source_class, receiver, member):
        if source_class not in self._classes:
            if len(self._classes) >= self.max_classes:
                self._frontier(receiver, member, 'CLASS_BASE_QUERY_BUDGET_FRONTIER'); return None
            self._add_query(project_class_bases(self.slicer.snapshot, (source_class,)))
        return self._classes[source_class]

    def _base_steps(self, query, slot_index):
        """Retain each supported alternative, including its namespace route."""
        key = query, slot_index
        if key in self._step_cache:
            return self._step_cache[key]
        graph = self._base_queries[query]; slot = graph.slots[slot_index]
        declaration = graph.declarations[slot.owner]; result = []; reasons = []
        common = _guards(declaration.conditions, slot.conditions,
            ('RECORDED_BASE_EXPRESSION_SELECTS_SOURCE_CLASS_CANDIDATE',))
        for ordinal, path in enumerate(slot.paths):
            if (path.root in slot.source_classes and path.root_kind is A.AddressRootKind.CLASS_DEFINITION
                    and not path.selectors and path.frontier is None):
                result.append(I.BasePathStep(query, slot_index, declaration.source_class, path.root,
                    address_path=ordinal, conditions=_guards(common, path.conditions)))
        namespace = slot.namespace
        if namespace is not None:
            if not namespace.states or namespace.states[0].port != slot.expression:
                raise ValueError('base namespace query root differs from its source expression')
            origins = defaultdict(list); edges = defaultdict(list)
            for ordinal, origin in enumerate(namespace.origins):
                if not 0 <= origin.state < len(namespace.states):
                    raise ValueError('namespace origin state lies outside its original query')
                state = namespace.states[origin.state]
                if (origin.kind is NamespaceOriginKind.CLASS_DEFINITION and not state.selectors
                        and state.port in slot.source_classes):
                    origins[origin.state].append((ordinal, origin))
            for ordinal, edge in enumerate(namespace.edges):
                if not (0 <= edge.downstream < len(namespace.states) and 0 <= edge.upstream < len(namespace.states)):
                    raise ValueError('namespace edge lies outside its original query')
                edges[edge.downstream].append((ordinal, edge))
            pending = deque(((0, (), (), frozenset((0,))),)); admitted = 1
            while pending:
                state, route, conditions, seen = pending.popleft()
                for ordinal, origin in origins.get(state, ()):
                    result.append(I.BasePathStep(query, slot_index, declaration.source_class,
                        namespace.states[state].port, namespace_origin=ordinal, namespace_edges=route,
                        conditions=_guards(common, conditions, origin.conditions)))
                for ordinal, edge in edges.get(state, ()):
                    if edge.upstream in seen:
                        reasons.append('CLASS_BASE_NAMESPACE_CYCLE_FRONTIER'); continue
                    if admitted >= self.max_states:
                        reasons.append('CLASS_BASE_NAMESPACE_PATH_BUDGET_FRONTIER'); continue
                    admitted += 1
                    pending.append((edge.upstream, (*route, ordinal), _guards(conditions, edge.conditions),
                        seen | {edge.upstream}))
        supported = {step.target_class for step in result}
        if any(candidate not in supported for candidate in slot.source_classes):
            reasons.append('BASE_CLASS_CANDIDATE_HAS_NO_COMPLETE_SOURCE_WITNESS')
        if not slot.source_classes:
            reasons.append('DECLARED_BASE_CLASS_SOURCE_UNRESOLVED')
        value = tuple(dict.fromkeys(result)), tuple(dict.fromkeys(reasons))
        self._step_cache[key] = value
        return value

    def _record(self, receiver, member, owner, path, descriptor):
        key = receiver, member, owner, path, descriptor
        if key not in self._record_ids:
            ordinal = len(self._records)
            extra = _guards(*(step.conditions for step in path), _INHERITANCE_GUARDS if path else (),
                (self.record_guard(ordinal),))
            selected = replace(descriptor, conditions=_guards(descriptor.conditions, extra))
            self._record_ids[key] = ordinal
            self._records.append(I.InheritedDescriptor(receiver, member, owner, path, selected))
        return self._records[self._record_ids[key]]

    @staticmethod
    def record_guard(ordinal):
        return 'SOURCE_MEMBER_LOOKUP_ALTERNATIVE_'+str(ordinal)+'_SELECTED'

    def lookup(self, source_class, member):
        if type(source_class) is not T.GlobalPort or type(member) is not str or not member:
            raise TypeError('member lookup needs an original source class and member name')
        key = source_class, member
        if key in self._lookups:
            return self._lookups[key]
        pending = deque(((source_class, (), frozenset((source_class,))),)); admitted = 1; result = []
        self._frontier(source_class, member, 'CURRENT_RUNTIME_BASES_MRO_AND_SHADOWING_UNPROVEN')
        while pending:
            owner, path, seen = pending.popleft()
            for descriptor in super().descriptors(owner, member):
                record = self._record(source_class, member, owner, path, descriptor)
                if record not in result: result.append(record)
            indexed = self._class_query(owner, source_class, member)
            if indexed is None: continue
            query, declaration = indexed; bases = self._base_queries[query]
            for frontier in bases.frontiers:
                if frontier.owner == declaration:
                    self._frontier(source_class, member, frontier.reason)
            for slot in self._slots[indexed]:
                steps, reasons = self._base_steps(query, slot)
                for reason in reasons: self._frontier(source_class, member, reason)
                for step in steps:
                    if step.target_class in seen:
                        self._frontier(source_class, member, 'SOURCE_CLASS_BASE_CYCLE_FRONTIER'); continue
                    if len(path) >= self.max_depth:
                        self._frontier(source_class, member, 'SOURCE_CLASS_BASE_DEPTH_FRONTIER'); continue
                    if admitted >= self.max_states:
                        self._frontier(source_class, member, 'SOURCE_CLASS_BASE_PATH_BUDGET_FRONTIER'); continue
                    admitted += 1
                    pending.append((step.target_class, (*path, step), seen | {step.target_class}))
        self._lookups[key] = tuple(result)
        return self._lookups[key]

    def descriptors(self, source_class, member):
        return tuple(record.descriptor for record in self.lookup(source_class, member))


def lookup_inherited_members(snapshot, source_class, member, *, bases=None, **limits):
    """One pure source lookup; parent receipt validation remains caller-owned."""
    resolver = InheritedMemberResolver(ReferenceSlicer(snapshot), bases, **limits)
    resolver.lookup(source_class, member)
    return resolver.graph()
