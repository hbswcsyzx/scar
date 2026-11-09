"""Resolve bounded source selector alternatives without executing lookups.

Aliases, lexical bindings and original GET facts are the only traversed
producers. A call result remains an opaque reference root; neither its
arguments nor a library name can establish address or content equality.
"""
from collections import defaultdict, deque
from types import SimpleNamespace

from scar.analysis.source_reference_slice import DECLARED, ReferenceSlicer, source_port
from scar.ir.program import normal_links as F, source_address_paths as A
from scar.ir.literals import PythonLiteral


_PATH_GUARDS = (*DECLARED, 'SOURCE_ADDRESS_PATH_ALTERNATIVE_SELECTED',
    'NO_RUNTIME_ADDRESS_OR_CONTENT_EQUALITY_PROOF')
_LEXICAL_GUARDS = ('FLOW_INSENSITIVE_LEXICAL_BINDING_NOT_CURRENT_FRAME_VERSION',
    'CURRENT_LEXICAL_READ_SELECTS_SAME_CODE_SCOPE_DECLARED_WRITE')
_FIELD_GUARDS = ('SOURCE_ACCESS_SCOPES_ENTERED', 'DEFAULT_PYTHON_ATTRIBUTE_SLOT_SELECTED',
    'CURRENT_ATTRIBUTE_LOOKUP_SELECTS_RECORDED_FIELD', 'ATTRIBUTE_GET_COMPLETES_NORMALLY',
    'ATTRIBUTE_GET_RESULT_IS_SELECTED_SLOT_REFERENCE')
_ITEM_GUARDS = ('SOURCE_ACCESS_SCOPES_ENTERED', 'DEFAULT_PYTHON_INDEX_SLOT_SELECTED',
    'CURRENT_ITEM_LOOKUP_SELECTS_RECORDED_KEY', 'ITEM_GET_COMPLETES_NORMALLY',
    'ITEM_GET_RESULT_IS_SELECTED_SLOT_REFERENCE')


def _guards(*groups):
    return tuple(dict.fromkeys(item for group in groups for item in group))


class AddressResolver:
    """Read source paths in one CodeScopeRef, distinct from namespace owners.

    ``local`` in :meth:`paths` is an original unit port-table ordinal. Selectors
    are ordered from the retained root toward that query port. Depth counts
    every followed alias, name binding or GET, including syntactic copies.
    """

    def __init__(self, store, unit, code_scope):
        identity = unit if type(unit) is str else unit.unit
        if type(code_scope) is F.CodeScopeWitness:
            code_scope = code_scope.owner
        if type(code_scope) is not F.CodeScopeRef or code_scope.unit != identity:
            raise ValueError('address paths need an original unit-qualified code scope')
        self.store = store; self.code_scope = code_scope
        # Primitive/collection SourceFactStore has no composite parent adapter.
        # Resolve its actual primitive parent without changing any fact receipt.
        source = store
        if not hasattr(store, '_source_parents'):
            while source.parents:
                source = source.parents[source.unit_parent[identity]]
            fact_store = SimpleNamespace(load=store.load, rows=store.rows, _source_parents={identity: source})
        else:
            fact_store = store
        self.slicer = ReferenceSlicer(SimpleNamespace(fact_store=fact_store))
        self.unit, _, self.aliases, self.reads, self.writes, _, _ = self.slicer.unit(identity)
        if type(unit) is not str and unit != self.unit:
            raise ValueError('address unit facts differ from the original source catalog')
        scopes = {group.owner for group in self.unit.scope_groups}
        if code_scope not in scopes:
            raise ValueError('address code scope is absent from the original source facts')
        self.name_owners = defaultdict(set)
        for group in self.unit.scope_groups:
            for span in group.tables:
                if span.table is F.FactTable.NAMES:
                    for index in range(span.start, span.stop):
                        self.name_owners[index].add(group.owner)
        self.attributes = defaultdict(list); self.items = defaultdict(list)
        for index, access in enumerate(self.unit.attributes):
            if access.action is F.AttributeAction.GET:
                self.attributes[access.value].append((index, access))
        for index, access in enumerate(self.unit.items):
            if access.write is False:
                self.items[access.value].append((index, access))
        self.roots = defaultdict(list)
        for index, fn in enumerate(self.unit.functions):
            if fn.body_scope is not None and fn.body_scope.owner == code_scope:
                for formal in fn.formals[1:-1]:
                    self.roots[formal].append((A.AddressRootKind.FUNCTION_PARAMETER, 'functions', index))
        for table, kind in (('calls', A.AddressRootKind.CALL_RESULT),
                            ('constants', A.AddressRootKind.SOURCE_LITERAL),
                            ('classes', A.AddressRootKind.CLASS_DEFINITION),
                            ('functions', A.AddressRootKind.FUNCTION_DEFINITION)):
            for index, row in enumerate(getattr(self.unit, table)):
                self.roots[row.result if table == 'calls' else row.value].append((kind, table, index))
        self.open_producers = defaultdict(list)
        for table in ('imports', 'containers', 'operations', 'iterations'):
            for index, row in enumerate(getattr(self.unit, table, ())):
                self.open_producers[row.result if table == 'operations' else row.value].append((table, index))

    def _port(self, local):
        if type(local) is not int or not 0 <= local < len(self.unit.ports):
            raise ValueError('address reference is outside its original source port table')
        return source_port(self.unit, local)

    def _fact(self, table, ordinal):
        return self.slicer.fact(self.unit, table, ordinal)

    def paths(self, local, max_states=1000, max_depth=16):
        """Return conditional alternatives, including every encountered cut.

        A budget frontier retains the partial selector path and its unresolved
        upstream source port. Such a path cannot identify a complete address.
        """
        self._port(local)
        if type(max_states) is not int or max_states < 1 or type(max_depth) is not int or max_depth < 0:
            raise ValueError('address paths require positive states and nonnegative depth budgets')
        pending = deque(((local, (), (), _PATH_GUARDS, frozenset((local,)), 0),))
        admitted = 1; result = []; unique = set()

        def emit(point, selectors, evidence, guards, kind=A.AddressRootKind.OPEN_PRODUCER, frontier=None):
            row = A.AddressPath(self._port(point), kind, selectors, tuple(dict.fromkeys(evidence)),
                _guards(guards), frontier)
            if row not in unique:
                unique.add(row); result.append(row)

        while pending:
            point, selectors, evidence, guards, visited, depth = pending.popleft()
            roots = self.roots.get(point, ())
            if roots:
                for kind, table, ordinal in roots:
                    extra = ('CALL_RESULT_REFERENCE_IS_OPAQUE',) if kind is A.AddressRootKind.CALL_RESULT else ()
                    emit(point, selectors, (*evidence, self._fact(table, ordinal)), _guards(guards, extra), kind)
                continue
            candidates = []
            for source, ordinal in self.aliases.get(point, ()):
                candidates.append((source, selectors, (self._fact('aliases', ordinal),), DECLARED))
            for namespace, read_index in self.reads.get(point, ()):
                read_ref = self._fact('names', read_index)
                if namespace.kind is not F.NamespaceKind.LEXICAL:
                    emit(point, selectors, (*evidence, read_ref), guards,
                        frontier='NON_LEXICAL_NAMESPACE_CONTENT_UNRESOLVED')
                    continue
                if self.name_owners[read_index] != {self.code_scope}:
                    emit(point, selectors, (*evidence, read_ref),
                        _guards(guards, ('CAPTURE_CREATION_CONTEXT_NOT_PROVEN',)),
                        frontier='CAPTURE_CONTEXT_UNRESOLVED')
                    continue
                writes = self.writes.get(namespace, ())
                if not writes:
                    emit(point, selectors, (*evidence, read_ref), guards,
                        frontier='LEXICAL_BINDING_PRODUCER_UNRESOLVED')
                foreign = False
                for source, write_index in writes:
                    if self.name_owners[write_index] != {self.code_scope}:
                        foreign = True
                        continue
                    candidates.append((source, selectors,
                        (self._fact('names', write_index), read_ref), (*DECLARED, *_LEXICAL_GUARDS)))
                if foreign:
                    emit(point, selectors, (*evidence, read_ref),
                        _guards(guards, ('CAPTURE_CREATION_CONTEXT_NOT_PROVEN',)),
                        frontier='CAPTURE_CONTEXT_UNRESOLVED')
            for ordinal, access in self.attributes.get(point, ()):
                candidates.append((access.receiver, (A.FieldSelector(access.name), *selectors),
                    (self._fact('attributes', ordinal),), _FIELD_GUARDS))
            for ordinal, access in self.items.get(point, ()):
                key = access.key if type(access.key) is PythonLiteral else self._port(access.key)
                extra = () if type(key) is PythonLiteral else ('DYNAMIC_ITEM_KEY_VALUE_AND_EQUALITY_UNRESOLVED',)
                candidates.append((access.receiver, (A.ItemSelector(key), *selectors),
                    (self._fact('items', ordinal),), (*_ITEM_GUARDS, *extra)))
            if not candidates:
                # Namespace frontiers above already record the available fact;
                # other producers retain their original evidence as open roots.
                producers = self.open_producers.get(point, ())
                if producers:
                    for table, ordinal in producers:
                        emit(point, selectors, (*evidence, self._fact(table, ordinal)), guards,
                            frontier='SOURCE_PRODUCER_SEMANTICS_UNRESOLVED')
                elif not self.reads.get(point):
                    emit(point, selectors, evidence, guards, frontier='SOURCE_PRODUCER_UNRESOLVED')
                continue
            if depth >= max_depth:
                emit(point, selectors, evidence, guards, frontier='ADDRESS_DEPTH_BUDGET_FRONTIER')
                continue
            for source, path, refs, extra in candidates:
                next_evidence = (*evidence, *refs); next_guards = _guards(guards, extra)
                if source in visited:
                    emit(source, path, next_evidence, next_guards, frontier='REFERENCE_CYCLE_UNRESOLVED')
                    continue
                if admitted >= max_states:
                    emit(point, selectors, evidence, guards, frontier='ADDRESS_STATE_BUDGET_FRONTIER')
                    break
                self._port(source)
                admitted += 1
                pending.append((source, path, next_evidence, next_guards, visited | {source}, depth+1))
        if hasattr(self.store, 'validate_parents'):
            self.store.validate_parents()
        return tuple(result)
