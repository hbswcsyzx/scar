"""Bounded entry namespace candidates without a selected CALL activation.

Only original namespace writes, entry ports and CFG witnesses are composed.
The default common graph supplies the owner path, and a mandatory callback
freshly checks each edge.  No creation-time world becomes an entry-time world;
all external state and temporal correspondence remains an explicit predicate.
"""
from __future__ import annotations

from dataclasses import dataclass, fields, replace

from scar.analysis.static_crossbody_namespace import (StaticNamespaceBody,
    _read_endpoint, _write_endpoint)
from scar.analysis.static_namespace import NamespaceDependencies
from scar.ir.program.dependencies import (DependencyCondition as Condition,
    DependencyContext, DependencyEdge, DependencyEvidence as Evidence,
    DependencyFrontier as Frontier, DependencyKind as K, DependencyMeaning as M,
    DependencyPoint as Point, GraphNamespace)
from scar.ir.program.entry_namespaces import EntryNamespaceOwnerMode as OwnerMode, EntryNamespaceProjection
from scar.ir.program.environments import EnvironmentRole
from scar.ir.program.functions import BodyEntryInterface
from scar.ir.program.ids import UseID, ValueID
from scar.ir.program.model import ReferenceValue, StateVersionValue, TerminatorKind, UseRole
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.static_calls import NamespacePathStart, StaticNamespacePathSegment
from scar.ir.record_codec import decode


@dataclass(frozen=True, slots=True)
class EntryNamespaceBudget:
    max_owner_edges: int = 128
    max_snapshots: int = 128
    max_projections: int = 256
    max_cfg_steps: int = 4096
    max_operations: int = 262144

    def __post_init__(self):
        if any(type(getattr(self, field.name)) is not int or getattr(self, field.name) < 1
               for field in fields(self)):
            raise ValueError("entry namespace budgets must be positive integers")


@dataclass(frozen=True, slots=True)
class EntryNamespaceDerivation:
    projections: tuple[EntryNamespaceProjection, ...] = ()
    frontiers: tuple[Frontier, ...] = ()
    enumerated: bool = False

    def __post_init__(self):
        for rows, kind in ((self.projections, EntryNamespaceProjection), (self.frontiers, Frontier)):
            if type(rows) is not tuple or any(type(item) is not kind for item in rows):
                raise TypeError("entry namespace derivation needs typed immutable results")
        if self.enumerated is not False:
            raise ValueError("initializer candidates never close arbitrary entry namespace contents")


def _body(body):
    if type(body) is not StaticNamespaceBody:
        raise TypeError("entry namespace inputs must be checked original StaticNamespaceBody records")
    # Existing canonical validation is replayed, not a cached successful flag.
    body.__post_init__(None)
    return body


def _reference(point, load_index):
    index = load_index(point.namespace)
    if type(index) is not ProgramIndex:
        raise TypeError("owner-path loader must return the shared original ProgramIndex")
    if type(point.node) is ValueID:
        value = index.values.get(point.node)
    elif type(point.node) is UseID:
        value = index.values.get(index.use_site(point.node).use.value)
    else:
        raise ValueError("namespace owner provenance must use reference Value/Use ports")
    if type(value) is not ReferenceValue:
        raise ValueError("namespace owner provenance changed an original reference into a value/state")
    return index


def _owner_path(path, *, start, end, load_index, validate_owner_edge, budget, check):
    if type(path) is not tuple or not path or any(type(edge) is not DependencyEdge for edge in path):
        raise TypeError("entry namespace derivation needs the original directed reference path")
    if len(path) > budget.max_owner_edges:
        raise OverflowError("entry namespace owner-path budget exhausted")
    if path[0].source != start or path[-1].target != end:
        raise ValueError("namespace owner path changed its original module or entry point/context")
    points = [start]
    for edge in path:
        check(); edge.__post_init__()
        if edge.source != points[-1] or edge.target in points:
            raise ValueError("namespace owner path is disconnected or attempts to seed itself cyclically")
        source_index = _reference(edge.source, load_index)
        _reference(edge.target, load_index)
        if edge.kind is K.VALUE_USE and edge.meaning is M.VALUE:
            if (edge.source.namespace != edge.target.namespace or edge.source.context != edge.target.context
                    or type(edge.source.node) is not ValueID or type(edge.target.node) is not UseID):
                raise ValueError("VALUE_USE owner identity must preserve its original namespace/context")
            site = source_index.use_site(edge.target.node)
            if (site.use.value != edge.source.node
                    or site.use.role in (UseRole.STATE_CONTENT, UseRole.STATE_ORDER)):
                raise ValueError("VALUE_USE owner identity changed its original reference operand")
        elif edge.kind not in (K.ENVIRONMENT, K.ARGUMENT) or edge.meaning is not M.REFERENCE:
            raise ValueError("ordinary operands, computations and state contents are not owner identities")
        if validate_owner_edge(edge) is not True:
            raise ValueError("namespace owner edge was not freshly found in the default common graph")
        points.append(edge.target)


def _segment(body, witness):
    return StaticNamespacePathSegment(body.namespace, NamespacePathStart.ENTRY, witness.entry, None,
        witness.entry_owner, witness.query_operation, witness.query_owner, witness.query_world,
        witness.key, witness.path, witness.intervening_operations, witness.conditions)


def derive_entry_namespace_projections(*, entry, module, owner_path, read_result,
        read_slot, module_context: DependencyContext, load_index, validate_owner_edge,
        allow_module_owner_alias=False, initialization_contract=False, budget=None, check=None):
    """Return possible initializer payloads at this original entry/read point.

    ``allow_module_owner_alias`` adds a *conditional* alias branch alongside
    the independent G branch. Its L/G kill domain is used only with the named
    multi-endpoint alias premise.  A bool alone cannot provide an independent
    standard-import interpretation; that optional mode remains unsupported.
    ``load_index`` and ``validate_owner_edge`` must use the owning read session.
    """
    if type(read_result) is not Point or type(read_result.node) is not ValueID:
        raise TypeError("entry namespace query must be its original read-result Point")
    if type(read_slot) is not int or read_slot < 0:
        raise TypeError("entry namespace query needs its original lookup-owner ordinal")
    if type(allow_module_owner_alias) is not bool or type(initialization_contract) is not bool:
        raise TypeError("module alias/import interpretations must be explicit flags")
    if not callable(load_index) or not callable(validate_owner_edge):
        raise TypeError("entry projection requires original-index and fresh owner-edge callbacks")
    budget = budget or EntryNamespaceBudget()
    if type(budget) is not EntryNamespaceBudget:
        raise TypeError("expected EntryNamespaceBudget")
    check = check or (lambda: None)
    if not callable(check):
        raise TypeError("entry projection check must be a bounded session callback")
    projections, frontiers = {}, {}

    def note(kind, detail):
        frontiers[Frontier(read_result, kind, detail)] = None

    try:
        check(); entry = _body(entry); module = _body(module)
        entry_ns, module_ns = GraphNamespace.from_source(entry.namespace), GraphNamespace.from_source(module.namespace)
        if read_result.namespace != entry_ns:
            raise ValueError("entry query belongs to another original source body")
        if module.document.get('module') is None or len(module.graph.frame_roots) != 1:
            note('ENTRY_NAMESPACE_SOURCE_NOT_MODULE', 'Owner provenance has no original single module-frame initializer.')
            return EntryNamespaceDerivation((), tuple(frontiers))
        if entry.document.get('interface') is None:
            note('ENTRY_NAMESPACE_INTERFACE_UNSUPPORTED', 'No original bound function entry world is retained.')
            return EntryNamespaceDerivation((), tuple(frontiers))
        interface = decode(BodyEntryInterface, entry.document['interface'])
        if interface.region != entry.namespace.region or interface.definition != entry.namespace.definition:
            raise ValueError("entry namespace interface changed its original region/definition")
        world = entry.index.values.get(interface.world)
        if type(world) is not StateVersionValue or world.region != interface.region:
            raise ValueError("entry world is not the original interface state value")
        members = [member for environment in entry.graph.environments
            if environment.region == interface.region for member in environment.members
            if member.role is EnvironmentRole.GLOBALS_NAMESPACE]
        if len(members) != 1:
            note('ENTRY_NAMESPACE_GLOBALS_INTERFACE_UNSUPPORTED', 'No unique original function G member is retained.')
            return EntryNamespaceDerivation((), tuple(frontiers))
        globals_member = members[0]
        root = module.graph.frame_roots[0]
        module_g = Point(module_ns, root.entry.globals_namespace, module_context)
        module_l = Point(module_ns, root.entry.locals_namespace, module_context)
        entry_g = Point(entry_ns, globals_member.reference, read_result.context)
        entry_world = Point(entry_ns, interface.world, read_result.context)
        _owner_path(owner_path, start=module_g, end=entry_g, load_index=load_index,
            validate_owner_edge=validate_owner_edge, budget=budget, check=check)
        # Private demand-local CFG caches hold input derivations, not PASS.
        local = NamespaceDependencies(entry.graph, entry.document, index=entry.index,
            max_steps=budget.max_cfg_steps, check=check)
        source = NamespaceDependencies(module.graph, module.document, index=module.index,
            max_steps=budget.max_cfg_steps, check=check)
        read = local.by_result.get(read_result.node)
        if read is None or not 0 <= read_slot < len(read.owners):
            raise ValueError("entry projection changed an original namespace-read result/slot")
        if entry.index.use_site(read.owners[read_slot]).use.value != globals_member.reference:
            note('ENTRY_NAMESPACE_OWNER_NOT_GLOBALS', 'This original lookup slot is not the function G interface; saved B is not substituted.')
            return EntryNamespaceDerivation((), tuple(frontiers))
        key = local._string(read.keys[read_slot])
        if key is None:
            note('ENTRY_NAMESPACE_KEY_UNSUPPORTED', 'The original lookup key lacks an exact builtin-string literal.')
            return EntryNamespaceDerivation((), tuple(frontiers))
        entries = local.entry_paths_to_read(read, read_slot, entry_owner=globals_member.reference)
        if not entries:
            note('ENTRY_NAMESPACE_LOCAL_WRITE_BLOCKS_ENTRY', 'No original path preserves the entry binding to this read; committed local writes are not bypassed.')
            return EntryNamespaceDerivation((), tuple(frontiers))
        for witness in entries:
            local.validate_entry_path(witness, entry_owner=globals_member.reference)
        if initialization_contract:
            note('ENTRY_NAMESPACE_IMPORT_INTERPRETATION_UNSUPPORTED', 'A boolean flag is not an independently checked standard-import initialization route; no import contract is invented.')
            return EntryNamespaceDerivation((), tuple(frontiers))
        qualified_read = _read_endpoint(StaticNamespaceBody(entry.graph, entry.document, entry.namespace,
            entry.index, local), read, read_slot)
        modes = [(OwnerMode.GLOBALS_ONLY, (module_g.node,))]
        if allow_module_owner_alias and module_l.node != module_g.node:
            modes.append((OwnerMode.CONDITIONAL_L_G_ALIAS, (module_l.node, module_g.node)))
        inherited_conditions = tuple(dict.fromkeys(c for edge in owner_path for c in edge.conditions))
        inherited_evidence = tuple(dict.fromkeys(e for edge in owner_path for e in edge.evidence))
        checked_module = StaticNamespaceBody(module.graph, module.document, module.namespace, module.index, source)
        snapshots = 0
        for ordinal, terminal in enumerate(module.graph.operations):
            check()
            if ordinal >= budget.max_operations:
                raise OverflowError("entry namespace initializer operation budget exhausted")
            if (terminal.terminator is None or terminal.terminator.kind is not TerminatorKind.RETURN
                    or source.owners.get(terminal.id, (None,))[0] != module.namespace.region):
                continue
            snapshots += 1
            if snapshots > budget.max_snapshots:
                raise OverflowError("entry namespace initializer snapshot budget exhausted")
            worlds = [use for use in terminal.uses if type(module.index.values[use.value]) is StateVersionValue]
            if len(worlds) != 1:
                note('ENTRY_NAMESPACE_SNAPSHOT_WORLD_UNSUPPORTED', 'An original module terminal has no unique world Use; no initializer world is synthesized.')
                continue
            snapshot_operation = Point(module_ns, terminal.id, module_context)
            snapshot_world = Point(module_ns, worlds[0].id, module_context)
            read_operation = Point(entry_ns, read.operation, read_result.context)
            read_world = Point(entry_ns, read.world, read_result.context)
            read_key = Point(entry_ns, read.keys[read_slot], read_result.context)
            for mode, equivalent in modes:
                for binding in source.bindings_at(module_g.node, key, terminal.id, worlds[0].id,
                        equivalent_owners=equivalent):
                    check(); source.validate_binding(binding)
                    qualified_write = _write_endpoint(checked_module, binding.write)
                    writer = Point(module_ns, binding.write.operation, module_context)
                    owner = Point(module_ns, binding.write.owners[0], module_context)
                    write_key = Point(module_ns, binding.write.keys[0], module_context)
                    write_world = Point(module_ns, binding.write.world, module_context)
                    conditions = list(inherited_conditions)

                    def predicate(name, subject, operands):
                        conditions.append(Condition('scar.entry-namespace', name, subject, operands=operands))

                    predicate('SOURCE_INITIALIZER_COMPLETES_NORMALLY', snapshot_operation,
                        (module_g, snapshot_world))
                    predicate('SOURCE_SNAPSHOT_PRECEDES_FUNCTION_ENTRY', entry_world,
                        (module_g, snapshot_operation, snapshot_world, entry_g))
                    predicate('MODULE_BINDING_PRESERVED_UNTIL_FUNCTION_ENTRY', entry_g,
                        (module_g, write_key, snapshot_world, entry_world, read_key))
                    predicate('ENTRY_NAMESPACE_OWNER_PATH_SELECTED', entry_g,
                        (module_g, snapshot_world, entry_world))
                    if mode is OwnerMode.CONDITIONAL_L_G_ALIAS:
                        predicate('MODULE_INITIALIZER_LOCALS_ALIASES_GLOBALS', module_g,
                            (module_l, snapshot_world, entry_g, entry_world, read_key))
                    for condition in binding.conditions:
                        conditions.append(replace(Condition.from_enum(condition), subject=snapshot_operation,
                            operands=(writer, owner, write_key, write_world, snapshot_world)))
                    for witness in entries:
                        entry_conditions = tuple(replace(Condition.from_enum(condition), subject=read_operation,
                            operands=(entry_g, entry_world, Point(entry_ns, read.owners[read_slot], read_result.context),
                                read_key, read_world)) for condition in witness.conditions)
                        evidence = Evidence('ENTRY_NAMESPACE_SOURCE_SNAPSHOT_PROJECTION_V1',
                            tuple(dict.fromkeys((module.namespace.graph, entry.namespace.graph))),
                            (module_g, module_l, writer, owner, write_key, write_world,
                                snapshot_operation, snapshot_world, entry_g, entry_world,
                                read_operation, read_key, read_world, read_result))
                        projection = EntryNamespaceProjection(owner_path, qualified_read, read_slot,
                            entry_world, _segment(entry, witness), module_l, qualified_write,
                            snapshot_operation, snapshot_world, binding.path, binding.intervening_operations,
                            equivalent, key, mode, tuple(dict.fromkeys((*conditions, *entry_conditions))),
                            tuple(dict.fromkeys((*inherited_evidence, evidence))))
                        if projection not in projections and len(projections) >= budget.max_projections:
                            raise OverflowError("entry namespace projection count budget exhausted")
                        projections[projection] = None
        if not snapshots:
            note('ENTRY_NAMESPACE_INITIALIZER_TERMINAL_UNAVAILABLE', 'No original module-root normal terminal supplies an initializer snapshot.')
        elif not projections:
            note('ENTRY_NAMESPACE_INITIALIZER_BINDING_UNAVAILABLE', 'No supported original writer for this exact key reaches an initializer snapshot under the selected owner interpretations.')
        note('ENTRY_NAMESPACE_TEMPORAL_STATE_OPEN', 'Initializer completion, ordering before entry and preservation between distinct original worlds remain explicit predicates; G reference provenance does not prove entry contents.')
        if allow_module_owner_alias:
            note('ENTRY_NAMESPACE_MODULE_OWNER_ALIAS_OPEN', 'L/G ports stay independent; a separate conditional alias branch permits their joint writer-kill domain without proving aliasing or a standard import.')
    except (OverflowError, TimeoutError) as error:
        note('ENTRY_NAMESPACE_PROJECTION_BUDGET', type(error).__name__ + ': ' + str(error))
    return EntryNamespaceDerivation(tuple(projections), tuple(frontiers))


def validate_entry_namespace_projection(projection, *, entry, module, load_index,
        validate_owner_edge, budget=None, check=None, allow_module_owner_alias=False,
        initialization_contract=False):
    """Freshly replay original bodies, owner edges, endpoints and CFG kills.

    Budget interruption cannot validate by membership in a retained prefix.
    Input receipts are the owning session loader's responsibility on each call.
    """
    if type(projection) is not EntryNamespaceProjection:
        raise TypeError("expected typed EntryNamespaceProjection")
    projection.__post_init__()
    replay = derive_entry_namespace_projections(entry=entry, module=module,
        owner_path=projection.owner_path, read_result=projection.target,
        read_slot=projection.read_slot, module_context=projection.snapshot_operation.context,
        load_index=load_index, validate_owner_edge=validate_owner_edge,
        allow_module_owner_alias=allow_module_owner_alias,
        initialization_contract=initialization_contract, budget=budget, check=check)
    if any(frontier.kind == 'ENTRY_NAMESPACE_PROJECTION_BUDGET' for frontier in replay.frontiers):
        raise OverflowError("fresh entry namespace replay did not complete its original bounded demand")
    if projection not in replay.projections:
        raise ValueError("entry namespace source/read/world/owner/path/conditions differ from fresh original inputs")
    return True


__all__ = ['EntryNamespaceBudget', 'EntryNamespaceDerivation',
    'derive_entry_namespace_projections', 'validate_entry_namespace_projection']
