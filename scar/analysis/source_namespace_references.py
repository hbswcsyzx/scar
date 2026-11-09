"""Connect source namespace writes and import exports without executing them.

Namespace identity/current versions stay open. Every source writer/export is
conditional, and importable file candidates are never selected by class name.
IMPORT_FROM's attribute branch and import-registry fallback remain separate.
"""
from collections import defaultdict, deque

from scar.analysis.source_reference_slice import ReferenceSlicer, source_port, DECLARED
from scar.ir.program import normal_links as F, source_namespace_references as N


_NAMESPACE_GUARDS = (*DECLARED, 'RECORDED_LOOKUP_NAMESPACE_ALTERNATIVE_SELECTED',
    'SOURCE_WRITER_SCOPE_ENTERED_AND_WRITE_COMPLETED', 'CURRENT_SLOT_VERSION_SELECTS_RECORDED_SOURCE_WRITE',
    'LOOKUP_PATH_AND_NAMESPACE_WORLDS_ARE_COMPATIBLE', 'NO_CURRENT_NAMESPACE_OR_REFERENCE_IDENTITY_PROOF')
_IMPORT_GUARDS = (*_NAMESPACE_GUARDS, 'STANDARD_IMPORTER_AND_MODULE_RETURN_SEMANTICS_SELECTED',
    'SOURCE_SEARCH_ROOT_AND_SYS_MODULES_SELECT_RECORDED_PROVIDER_AND_VERSION',
    'MODULE_INITIALIZATION_AND_CURRENT_EXPORT_SELECT_RECORDED_WRITE')


class NamespaceReferenceResolver:
    def __init__(self, snapshot):
        self.snapshot = snapshot; self.slicer = ReferenceSlicer(snapshot); self.units = {}
        self.modules = defaultdict(list)
        store = snapshot.fact_store
        # This is an import candidate index. Compiled exec dictionaries are
        # deliberately excluded, even when they share an original filename.
        for identity in sorted(store.importable_units):
            row = store.rows[identity]; model = store.model_units[identity]
            names = (row.get('module'), *model.get('module_names', ()),
                *(mapping['name'] for mapping in model.get('module_mappings', ())))
            for name in dict.fromkeys(name for name in names if type(name) is str and name):
                self.modules[name].append(identity)

    def unit(self, identity):
        if identity not in self.units:
            unit, _, aliases, reads, writes, formals, terminals = self.slicer.unit(identity)
            owners = defaultdict(set)
            for group in unit.scope_groups:
                for span in group.tables:
                    if span.table is F.FactTable.NAMES:
                        for i in range(span.start, span.stop): owners[i].add(group.owner)
            attributes = defaultdict(list); imports = defaultdict(list); exports = defaultdict(list)
            for i, row in enumerate(unit.attributes):
                if row.action in (F.AttributeAction.GET, F.AttributeAction.IMPORT_MEMBER):
                    attributes[row.value].append((i, row))
            for i, row in enumerate(unit.imports): imports[row.value].append((i, row))
            for i, row in enumerate(unit.names):
                if row.write and row.namespace.kind is F.NamespaceKind.MODULE:
                    exports[row.namespace.name].append((i, row))
            self.units[identity] = unit, aliases, reads, writes, formals, terminals, owners, attributes, imports, exports
        return self.units[identity]

    def resolve(self, point, *, max_states=4000, max_selectors=32):
        return _Query(self, point, max_states, max_selectors).run()


class _Query:
    def __init__(self, resolver, point, max_states, max_selectors):
        resolver.slicer.local(point)
        if type(max_states) is not int or max_states < 1 or type(max_selectors) is not int or max_selectors < 1:
            raise ValueError('namespace source query needs positive state and selector limits')
        self.resolver = resolver; self.max_states = max_states; self.max_selectors = max_selectors
        root = N.NamespaceReferenceState(point)
        self.states = [root]; self.ids = {root: 0}; self.pending = deque((0,))
        self.edges = []; self.origins = []; self.frontiers = []; self.frontier_ids = set()

    def frontier(self, state, reason, evidence=()):
        key = state, reason, tuple(evidence)
        if key not in self.frontier_ids:
            self.frontier_ids.add(key); self.frontiers.append(N.NamespaceReferenceFrontier(*key))

    def edge(self, state, point, selectors, kind, evidence, conditions):
        if len(selectors) > self.max_selectors:
            self.frontier(state, 'NAMESPACE_SELECTOR_DEPTH_FRONTIER', evidence); return
        value = N.NamespaceReferenceState(point, selectors)
        if value not in self.ids:
            if len(self.states) >= self.max_states:
                self.frontier(state, 'NAMESPACE_REFERENCE_STATE_BUDGET_FRONTIER', evidence); return
            self.ids[value] = len(self.states); self.states.append(value); self.pending.append(self.ids[value])
        self.edges.append(N.NamespaceReferenceEdge(state, self.ids[value], kind, tuple(evidence), tuple(conditions)))

    def module(self, state, symbol, selectors, evidence, conditions):
        providers = tuple(self.resolver.modules.get(symbol, ()))
        if not selectors:
            self.origins.append(N.NamespaceReferenceOrigin(state, N.NamespaceOriginKind.MODULE_CANDIDATE,
                tuple(evidence), tuple(conditions), symbol, providers))
            if not providers: self.frontier(state, 'IMPORTED_MODULE_SOURCE_PROVIDER_NOT_RETAINED', evidence)
            return
        selected, rest = selectors[0], selectors[1:]
        guards = (*conditions, 'MODULE_ATTRIBUTE_READ_RETURNS_RECORDED_STORED_REFERENCE')
        found = False
        for identity in providers:
            unit, *_, exports = self.resolver.unit(identity)
            for ordinal, writer in exports.get(selected.member, ()):
                found = True
                ref = self.resolver.slicer.fact(unit, 'names', ordinal)
                self.edge(state, source_port(unit, writer.value), rest, N.NamespaceEdgeKind.MODULE_EXPORT,
                    (*evidence, selected.access, ref), guards)
        self.frontier(state, 'CURRENT_MODULE_EXPORT_VERSION_OR_DYNAMIC_ATTRIBUTE_PATH_OPEN', (*evidence, selected.access))
        if not found: self.frontier(state, 'DECLARED_MODULE_EXPORT_SOURCE_UNRESOLVED', (*evidence, selected.access))
        if selected.import_from:
            # IMPORT_FROM may recover a registered submodule after its normal
            # attribute path. It does not turn every member into a submodule.
            self.module(state, symbol+'.'+selected.member, rest, (*evidence, selected.access),
                (*conditions, 'IMPORT_FROM_ATTRIBUTE_PATH_MISSES_AND_REGISTRY_FALLBACK_SELECTED',
                    'IMPORT_REGISTRY_ENTRY_IS_RECORDED_MODULE_NAMESPACE'))

    def run(self):
        r = self.resolver
        while self.pending:
            index = self.pending.popleft(); state = self.states[index]
            unit, local = r.slicer.local(state.port)
            unit, aliases, reads, writes, formals, terminals, owners, attributes, imports, _ = r.unit(unit.unit)
            before = len(self.edges); before_origins = len(self.origins); before_frontiers = len(self.frontiers)
            for source, ordinal in aliases.get(local, ()):
                self.edge(index, source_port(unit, source), state.selectors, N.NamespaceEdgeKind.ALIAS,
                    (r.slicer.fact(unit, 'aliases', ordinal),), DECLARED)
            for namespace, ordinal in reads.get(local, ()):
                read = r.slicer.fact(unit, 'names', ordinal)
                if namespace.kind is F.NamespaceKind.BUILTINS:
                    self.frontier(index, 'BUILTIN_MAPPING_SLOT_BINDING_NOT_RESOLVED', (read,)); continue
                if namespace.kind is F.NamespaceKind.LEXICAL:
                    kind = N.NamespaceEdgeKind.LEXICAL_WRITE
                    if len(owners[ordinal]) != 1:
                        self.frontier(index, 'LEXICAL_READ_SCOPE_UNRESOLVED', (read,)); continue
                    guards = (*_NAMESPACE_GUARDS, 'SAME_LEXICAL_FRAME_AND_WRITE_VERSION_SELECTED')
                elif namespace.kind is F.NamespaceKind.MODULE:
                    kind = N.NamespaceEdgeKind.GLOBAL_WRITE
                    compiled = unit.unit in r.snapshot.fact_store.original_source_units
                    guards = (*_NAMESPACE_GUARDS, 'CURRENT_FRAME_GLOBALS_SELECT_RECORDED_COMPILE_CONTEXT_DICT' if compiled
                        else 'CURRENT_FRAME_GLOBALS_SELECT_RECORDED_SOURCE_MODULE_NAMESPACE')
                    self.frontier(index, 'CURRENT_GLOBAL_NAMESPACE_IDENTITY_AND_CONTENTS_OPEN', (read,))
                else:
                    kind = N.NamespaceEdgeKind.CLASS_WRITE
                    guards = (*_NAMESPACE_GUARDS, 'CLASS_NAMESPACE_MAPPING_SELECTS_RECORDED_SOURCE_WRITE')
                    self.frontier(index, 'CURRENT_CLASS_NAMESPACE_MAPPING_AND_VERSION_OPEN', (read,))
                found = False
                for source, writer in writes.get(namespace, ()):
                    if namespace.kind is F.NamespaceKind.LEXICAL and owners[writer] != owners[ordinal]:
                        self.frontier(index, 'CAPTURE_CREATION_FRAME_NOT_SELECTED', (read,)); continue
                    found = True
                    self.edge(index, source_port(unit, source), state.selectors, kind,
                        (r.slicer.fact(unit, 'names', writer), read), guards)
                if not found: self.frontier(index, 'DECLARED_NAMESPACE_WRITER_UNRESOLVED', (read,))
            for ordinal, attribute in attributes.get(local, ()):
                ref = r.slicer.fact(unit, 'attributes', ordinal)
                selector = N.NamespaceSelector(attribute.name, attribute.action is F.AttributeAction.IMPORT_MEMBER, ref)
                self.edge(index, source_port(unit, attribute.receiver), (selector, *state.selectors),
                    N.NamespaceEdgeKind.ATTRIBUTE_RECEIVER, (ref,),
                    (*DECLARED, 'PENDING_ATTRIBUTE_SELECTION_IS_NOT_RECEIVER_RESULT_ALIAS'))
            for ordinal, imported in imports.get(local, ()):
                ref = r.slicer.fact(unit, 'imports', ordinal)
                self.module(index, imported.module, state.selectors, (ref,), _IMPORT_GUARDS)
            if local in terminals:
                kind, table, ordinal = terminals[local]; ref = r.slicer.fact(unit, table, ordinal)
                if state.selectors:
                    self.frontier(index, 'ATTRIBUTE_OF_CLASS_OR_VALUE_REQUIRES_DESCRIPTOR_OR_MEMBER_MODEL', (ref,))
                else:
                    self.origins.append(N.NamespaceReferenceOrigin(index, N.NamespaceOriginKind(kind), (ref,),
                        (*DECLARED, 'SOURCE_DEFINITION_CREATION_AND_REFERENCE_PATH_SELECTED')))
            if local in formals:
                self.frontier(index, 'FUNCTION_PARAMETER_REQUIRES_SELECTED_CALL_CONTEXT')
            if (len(self.edges), len(self.origins), len(self.frontiers)) == (before, before_origins, before_frontiers):
                self.frontier(index, 'SOURCE_REFERENCE_PRODUCER_UNRESOLVED')
        r.snapshot.validate_parents()
        return N.NamespaceReferenceSlice(tuple(self.states), tuple(self.edges), tuple(self.origins), tuple(self.frontiers))
