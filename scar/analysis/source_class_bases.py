"""Project original class base-expression operands and their source paths.

UnitFacts.Class.bases retains the evaluated source operands of the class-build
call after its hidden prefix, before runtime __mro_entries__/metaclass/MRO
selection. A bases_pack is the whole packed class-build positional ABI, which
also contains hidden body/name operands; it cannot be enumerated as bases.
"""
from collections import defaultdict

from scar.analysis.source_address_paths import AddressResolver
from scar.analysis.source_reference_slice import ReferenceSlicer, source_port, DECLARED
from scar.analysis.source_namespace_references import NamespaceReferenceResolver
from scar.ir.program import normal_links as F, normal_targets as T
from scar.ir.program import source_address_paths as A, source_class_bases as B
from scar.ir.program.source_namespace_references import NamespaceOriginKind


_CONDITIONS = (*DECLARED,
    'SOURCE_CLASS_CREATION_SCOPE_AND_BASE_INPUT_VERSIONS_SELECTED',
    'SOURCE_CLASS_RESULT_AND_NAMESPACE_VERSIONS_SELECTED',
    'BASE_OPERANDS_ARE_EVALUATED_SOURCE_EXPRESSIONS_NOT_RESOLVED_RUNTIME_BASES',
    'METACLASS_MRO_ENTRIES_AND_RUNTIME_MRO_SELECTION_NOT_ESTABLISHED',
)
_SLOT_CONDITIONS = ('BASE_CLASS_CANDIDATE_REQUIRES_SELECTED_ADDRESS_AND_NAMESPACE_PATH_GUARDS',
    'NO_CLASS_IDENTITY_FROM_SELECTOR_CALL_IMPORT_OR_IDENTIFIER_SPELLING')


def _port(unit, local):
    if type(local) is not int or not 0 <= local < len(unit.ports):
        raise ValueError('class base operand is outside its original source port table')
    return source_port(unit, local)


def project_class_bases(snapshot, source_classes):
    """Project requested classes only, preserving ordered original operands.

    Definitions are sorted by original unit/port coordinates for stable output
    even when the caller supplies a set. Class-definition candidates reference
    original ports; they do not imply resolved runtime inheritance. Namespace
    writes/exports add conditional sources with their own evidence; current
    slot versions and imported provider selection stay open. No class is
    selected by identifier spelling and no relation table is scanned.
    """
    points = tuple(source_classes)
    if any(type(point) is not T.GlobalPort for point in points):
        raise TypeError('class base projection requires original source-class GlobalPorts')
    namespace_resolver = NamespaceReferenceResolver(snapshot)
    slicer = namespace_resolver.slicer; requested = []
    for point in dict.fromkeys(points):
        unit, local = slicer.local(point)
        matches = [(ordinal, cls) for ordinal, cls in enumerate(unit.classes) if cls.value == local]
        if len(matches) != 1:
            raise ValueError('class base source is not one original class declaration')
        ordinal, cls = matches[0]
        requested.append((unit.unit, local, point, unit, ordinal, cls))
    requested.sort(key=lambda row: (row[0], row[1]))
    owners = {}; resolvers = {}; declarations = []; slots = []; frontiers = []; frontier_ids = set()

    def frontier(owner, slot, reason):
        if (owner, slot, reason) not in frontier_ids:
            frontier_ids.add((owner, slot, reason)); frontiers.append(B.ClassBaseFrontier(owner, slot, reason))

    def paths_for(resolver, local):
        # Source transport often has several copy wires per expression. The
        # ordinary resolver preserves its own state/depth/cycle frontiers.
        return resolver.paths(local, max_states=1000, max_depth=128)

    for _, _, point, unit, ordinal, cls in requested:
        if unit.unit not in owners:
            covered = defaultdict(set)
            for group in unit.scope_groups:
                for span in group.tables:
                    if span.table is F.FactTable.CLASSES:
                        for index in range(span.start, span.stop): covered[index].add(group.owner)
            owners[unit.unit] = covered
        creators = owners[unit.unit][ordinal]
        if len(creators) != 1:
            raise ValueError('class declaration has no unique original creation code scope')
        creator = next(iter(creators))
        if type(creator) is not F.CodeScopeRef or creator.unit != unit.unit:
            raise ValueError('class creation code scope belongs to a different source unit')
        # cls.body_scope selects the class suite. Base expressions belong to
        # the surrounding scope that owns this CLASSES fact, not that suite.
        if creator not in resolvers:
            resolvers[creator] = AddressResolver(snapshot.fact_store, unit, creator)
        resolver = resolvers[creator]; owner = len(declarations)
        bases = tuple(_port(unit, base) for base in cls.bases)
        pack = None if cls.bases_pack is None else _port(unit, cls.bases_pack)
        pack_paths = () if cls.bases_pack is None else paths_for(resolver, cls.bases_pack)
        no_explicit = not bases and pack is None
        declarations.append(B.ClassBaseDeclaration(point, slicer.fact(unit, 'classes', ordinal), creator,
            bases, pack, pack_paths, no_explicit, _CONDITIONS))
        if pack is not None:
            frontier(owner, None, 'PACKED_CLASS_BUILD_ABI_INCLUDES_HIDDEN_OPERANDS_BASE_ITEMS_UNRESOLVED')
            for path in pack_paths:
                if path.frontier is not None: frontier(owner, None, path.frontier)
        elif no_explicit:
            frontier(owner, None, 'NO_EXPLICIT_BASE_ARGUMENTS_DOES_NOT_ESTABLISH_RUNTIME_OBJECT_BASE_OR_MRO')
        for index, expression in enumerate(bases):
            paths = paths_for(resolver, cls.bases[index]); candidates = []
            namespace = namespace_resolver.resolve(expression)
            for path in paths:
                if (path.root_kind is A.AddressRootKind.CLASS_DEFINITION
                        and not path.selectors and path.frontier is None):
                    if path.root not in candidates: candidates.append(path.root)
            for origin in namespace.origins:
                state = namespace.states[origin.state]
                if origin.kind is NamespaceOriginKind.CLASS_DEFINITION and not state.selectors:
                    if state.port not in candidates: candidates.append(state.port)
            slot = len(slots)
            slots.append(B.ClassBaseSlot(owner, index, expression, paths, tuple(candidates), _SLOT_CONDITIONS, namespace))
            if not candidates:
                frontier(owner, slot, 'BASE_EXPRESSION_DECLARED_CLASS_SOURCE_UNRESOLVED')
            # Original address boundaries remain in paths. This pass reports
            # the additional namespace model's still-open fields separately.
            for value in namespace.frontiers: frontier(owner, slot, value.reason)
    return B.ClassBaseGraph(tuple(declarations), tuple(slots), tuple(frontiers))
