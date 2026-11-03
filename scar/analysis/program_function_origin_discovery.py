"""Bounded, unit-local discovery of original conditional factory references.

There is no collector, new source basis, copied program graph or publication.
The shared session owns original reads and input-fact caches.  Compiler products
exist only on an ephemeral extractor context during one generator/replay.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType, SimpleNamespace

from scar.analysis.program_class_dependencies import class_dependency_frames
from scar.analysis.program_lowering import _Unsupported
from scar.analysis.program_source_definitions import SourceDefinitionUnavailable
from scar.analysis.static_function_creation import extract_function_creation
from scar.analysis.static_function_origins import (
    derive_factory_entry_origins, factory_entry_origin_evidence,
    factory_entry_origin_ports, validate_factory_entry_origin,
)
from scar.analysis.static_namespace import normal_reference, protocol_kinds
from scar.ir.program.dependencies import (
    DependencyFrontier, DependencyPoint, GraphNamespace, context_push,
)
from scar.ir.program.function_origins import StaticFactoryEntryOrigin
from scar.ir.program.source_call_bindings import SourceBodyNamespace
from scar.ir.record_codec import decode, encode
from scar.ir.v2.ids import OperationDefinitionID


_FUNCTION_KINDS = frozenset(("FUNCTION", "ASYNC_FUNCTION", "LAMBDA"))
_MAKES = frozenset(("MAKE_FUNCTION_314", "MAKE_NESTED_FUNCTION"))


@dataclass(frozen=True, slots=True)
class _UnitCatalog:
    entries: Mapping
    rows: Mapping
    definitions: Mapping


class _LazyDefinitions(Mapping):
    """Only a selected original canonical child is loaded by the extractor."""
    def __init__(self, owner, creator, catalog):
        self.owner, self.creator, self.catalog = owner, creator, catalog
        self.loaded = {}

    def __iter__(self):
        return iter(self.catalog.definitions)

    def __len__(self):
        return len(self.catalog.definitions)

    def __contains__(self, definition):
        return definition in self.catalog.definitions

    def body_for(self, definition):
        if definition not in self.loaded:
            entry = self.catalog.definitions[definition]
            body = self.owner._entry_body(self.creator.unit_number, entry["entry_key"])
            if body.namespace.definition != definition or encode(body.namespace.source) != entry.get("source_ref"):
                raise ValueError("factory child canonical body differs from its original catalog definition/source")
            self.loaded[definition] = body
        return self.loaded[definition]

    def __getitem__(self, definition):
        entry = self.catalog.definitions[definition]
        body = self.body_for(definition)
        qualified = self.owner.session.source_definition_reference(body.namespace)
        # This is the existing extractor tuple, not a second definition table.
        return qualified, None, entry, (body.body_position, body.row)


class AutomaticFactoryEntryOrigins:
    """Demand origin adapters over one owned ProgramDependencySession.

    Origin records are derived and validated on demand.  The cached objects
    below are only original port/catalog input facts, never successful proofs.
    Query notes are bounded to the current synchronous provider request, and
    frontiers_for performs no additional I/O or budget check.
    """
    def __init__(self, session):
        self.session = session
        self._counts = Counter()
        self._note_point = None
        self._notes = {False: {}, True: {}}

    def _begin(self, point):
        if point != self._note_point:
            self._note_point = point
            self._notes = {False: {}, True: {}}

    def _note(self, point, outgoing, kind, detail):
        self._begin(point)
        row = DependencyFrontier(point, kind, detail)
        self._notes[outgoing][row] = None

    def _body(self, namespace):
        body = self.session.load(namespace)
        return body if type(body.namespace) is SourceBodyNamespace else None

    def _ports(self, body):
        namespace = GraphNamespace.from_source(body.namespace)
        key = ("automatic-factory-origin-ports", namespace.identity, body.namespace.definition)
        found = self.session._get(key)
        if found is None:
            found = factory_entry_origin_ports(graph=body.graph, document=body.document,
                namespace=body.namespace, index=body.index)
            self.session._put(key, found, 128 + 64 * sum(map(len, found)))
            self._counts["port_indexes_built"] += 1
        else:
            self._counts["port_index_hits"] += 1
        return found

    def interface_scope(self, point, outgoing):
        if type(point) is not DependencyPoint or type(outgoing) is not bool:
            raise TypeError("automatic factory scope needs a typed point and direction")
        body = self._body(point.namespace)
        if body is None:
            return False
        return point.node in self._ports(body)[1 if outgoing else 0]

    def _catalog(self, body):
        unit = body.unit
        descriptor = unit.get("artifacts", {}).get("lexical")
        if descriptor is None:
            raise SourceDefinitionUnavailable("SOURCE_DEFINITION_CONTEXT_UNAVAILABLE",
                "The original creator/child has no retained lexical catalog.", ("lexical",))
        # Read validates the registered file even when the compact maps hit.
        original = self.session.read(descriptor)
        catalog = self.session._catalog(body.unit_number)
        if catalog != original:
            raise ValueError("factory discovery catalog differs from its retained original fragment")
        key = ("automatic-factory-origin-catalog", unit["key"], unit["namespace_root"],
            descriptor["sha256"], descriptor["decoded_sha256"])
        found = self.session._get(key)
        if found is not None:
            return found
        entries = {entry["entry_key"]: entry for entry in catalog["entries"]}
        if len(entries) != len(catalog["entries"]):
            raise ValueError("factory discovery found duplicate original lexical entry keys")
        rows = {row["entry_key"]: (position, row) for position, row in enumerate(unit["bodies"])}
        if len(rows) != len(unit["bodies"]):
            raise ValueError("factory discovery found duplicate original body declarations")
        definitions = {}
        for entry in entries.values():
            if entry["kind"] not in _FUNCTION_KINDS:
                continue
            for wire in entry.get("semantic_definition_ids") or ():
                definition = decode(OperationDefinitionID, wire)
                if definition in definitions:
                    raise ValueError("one original function definition belongs to multiple source entries")
                definitions[definition] = entry
        found = _UnitCatalog(MappingProxyType(entries), MappingProxyType(rows), MappingProxyType(definitions))
        self.session._put(key, found, descriptor["decoded_bytes"] + 128 * len(rows))
        self._counts["unit_catalogs_indexed"] += 1
        return found

    def _entry_body(self, number, entry_key):
        unit = self.session.units[number]
        matches = [(position, row) for position, row in enumerate(unit["bodies"]) if row["entry_key"] == entry_key]
        if not matches:
            raise SourceDefinitionUnavailable("SOURCE_DEFINITION_CONTEXT_UNAVAILABLE",
                "Original source entry " + str(entry_key) + " has no body declaration.", ("body_declaration",))
        if len(matches) != 1:
            raise ValueError("factory source entry has multiple original body declarations")
        position, row = matches[0]
        if "artifact" not in row or row.get("status") != "LOWERED_WITH_GAPS":
            raise SourceDefinitionUnavailable("SOURCE_DEFINITION_CONTEXT_UNAVAILABLE",
                "Original entry " + entry_key + " has no saved canonical body (" + str(row.get("status")) + ").",
                ("canonical_body",))
        loaded = self.session._base_body(number, position)
        return self.session.load_body(loaded.namespace)

    def _extractor_body(self, creator, catalog):
        tree, semantic, text = self.session.source_context(creator)
        definitions = _LazyDefinitions(self, creator, catalog)
        by_atom = defaultdict(list)
        for definition, entry in catalog.definitions.items():
            original = semantic.definitions.get(definition)
            if original is None:
                raise ValueError("factory catalog definition is absent from its original semantic graph")
            if original.metadata.get("phase") == "call_time":
                for atom in original.source_atoms:
                    by_atom[atom].append(definition)
        context = SimpleNamespace(tree=tree, semantic=semantic, docs={"source": {"text": text}},
            unit=creator.unit, definitions=definitions, defs_by_atom=by_atom)
        sources = creator.module if creator.module is not None else creator.metadata
        links, uses = defaultdict(list), defaultdict(list)
        for row in sources.operation_links:
            links[row.operation].append(row)
        for row in sources.use_links:
            uses[row.operation].append(row)
        wrapper = SimpleNamespace(**{**vars(creator), "context": context,
            "links_by_op": links, "uses_by_op": uses})
        return wrapper, definitions, text

    def _creator_keys(self, target, catalog):
        entry = catalog.entries.get(target.row["entry_key"])
        if entry is None:
            raise ValueError("factory target is absent from its original lexical catalog")
        owner = entry.get("definition_owner") or entry.get("lexical_parent")
        if owner is None:
            return ()
        if type(owner) is not str or owner not in catalog.entries:
            raise ValueError("factory source owner does not reference an original lexical entry")
        return (owner,)

    def _candidate_operations(self, creator, target, source_node):
        protocols = protocol_kinds(creator.document)
        sources = creator.module if creator.module is not None else creator.metadata
        links = defaultdict(list)
        for row in sources.operation_links:
            links[row.operation].append(row)
        uses = defaultdict(list)
        for row in sources.use_links:
            uses[row.operation].append(row)
        for operation in creator.graph.operations:
            if protocols.get(operation.id) not in _MAKES:
                continue
            if target is not None and creator.class_entry is not None:
                factories = [row for row in getattr(creator.class_entry, "factories", ())
                    if row.operation == operation.id]
                if not any(row.definition == target.namespace.definition for row in factories):
                    # A generated annotation factory can share the enclosing
                    # FunctionDef span.  Its own missing DefinitionID is not
                    # an alternative raw factory for this user function.
                    continue
            normal = normal_reference(creator.index, operation.id)
            if normal is None:
                continue
            if target is not None and not any(row.source == target.namespace.source for row in links[operation.id]):
                continue
            if source_node is not None and source_node != normal[1] and not any(
                    row.use == source_node and row.role == "function-globals" for row in uses[operation.id]):
                continue
            yield operation, normal

    def origins_for(self, point):
        if type(point) is not DependencyPoint:
            raise TypeError("factory discovery needs an original typed query point")
        self._begin(point)
        outgoing = False
        try:
            current = self._body(point.namespace)
            if current is None:
                return
            incoming_ports, outgoing_ports = self._ports(current)
            if point.node in incoming_ports:
                target = current
                catalog = self._catalog(current)
                keys = self._creator_keys(target, catalog)
                if not keys:
                    self._note(point, False, "FACTORY_ORIGIN_CREATOR_SCOPE_UNAVAILABLE",
                        "The original function entry has no declared creator frame.")
                    return
                creators = (self._entry_body(current.unit_number, key) for key in keys)
                source_node = None
            elif point.node in outgoing_ports:
                outgoing = True
                target = None
                catalog = self._catalog(current)
                creators, source_node = (current,), point.node
            else:
                return
            admitted = 0
            matched = False
            for creator in creators:
                wrapper, definitions, text = self._extractor_body(creator, catalog)
                for operation, (edge, value) in self._candidate_operations(creator, target, source_node):
                    self.session.check()
                    if admitted >= self.session.budget.max_origin_candidates:
                        raise OverflowError("factory origin candidate budget exhausted")
                    admitted += 1
                    self._counts["factory_candidates_examined"] += 1
                    try:
                        creation = extract_function_creation(wrapper, operation, value, edge)
                        if creation is None:
                            generated = (creator.class_entry is not None and any(
                                row.operation == operation.id and row.definition is None
                                for row in getattr(creator.class_entry, "factories", ())))
                            self._note(point, outgoing,
                                "FACTORY_ORIGIN_GENERATED_FACTORY_WITHOUT_USER_DEFINITION" if generated else
                                "FACTORY_ORIGIN_SOURCE_COMPILER_UNCONNECTED",
                                "Original factory " + operation.id.wire + (" is a compiler-generated child without a user DefinitionID."
                                    if generated else " has no supported source/compiler child proof."))
                            continue
                        child = definitions.body_for(creation.definition.definition)
                        if target is not None and GraphNamespace.from_source(child.namespace) != GraphNamespace.from_source(target.namespace):
                            raise ValueError("factory extraction selected a different original target body")
                        self.session.validate_source_definition_reference(creation.definition, child.namespace)
                        origins = derive_factory_entry_origins(creator_graph=creator.graph, creator_document=creator.document,
                            creator_namespace=creator.namespace, creator_index=creator.index, body_graph=child.graph,
                            body_document=child.document, body_namespace=child.namespace, body_index=child.index,
                            creation=creation, source_text=text)
                    except SourceDefinitionUnavailable as error:
                        self._note(point, outgoing, "FACTORY_ORIGIN_CHILD_SCOPE_UNAVAILABLE",
                            operation.id.wire + ": " + error.kind + ": " + error.detail)
                        continue
                    except _Unsupported as error:
                        self._note(point, outgoing, "FACTORY_ORIGIN_SOURCE_RULE_UNSUPPORTED",
                            operation.id.wire + ": " + error.kind + ": " + error.detail)
                        continue
                    for origin in origins:
                        if (origin.source_use or origin.source_value) != source_node and outgoing:
                            continue
                        if not outgoing and origin.member.reference != point.node:
                            continue
                        matched = True
                        self._counts["origins_derived"] += 1
                        yield origin, factory_entry_origin_evidence(origin,
                            creator_document=creator.document, body_document=child.document)
            if not matched:
                self._note(point, outgoing, "FACTORY_ORIGIN_NO_JOINED_SOURCE_FACTORY",
                    "No original factory normal/capture and exact source/compiler child were joined for this port.")
        except SourceDefinitionUnavailable as error:
            self._note(point, outgoing, "FACTORY_ORIGIN_SOURCE_SCOPE_UNAVAILABLE",
                error.kind + ": " + error.detail + " Missing: " + ", ".join(error.missing_fields))
        except (OverflowError, TimeoutError) as error:
            self._note(point, outgoing, "FACTORY_ORIGIN_DISCOVERY_BUDGET", type(error).__name__ + ": " + str(error))
            # Loading the original body/ports may stop before the direction is
            # known.  Let the querying provider retain the yielded prefix and
            # attach the budget frontier to its actual traversal direction.
            raise

    def validate_origin(self, origin):
        if type(origin) is not StaticFactoryEntryOrigin:
            raise TypeError("automatic factory validation requires its typed derived record")
        creator = self.session.load_body(origin.creator)
        body = self.session.load_body(origin.body)
        if creator.unit_number != body.unit_number:
            raise ValueError("automatic factory origin crosses distinct original source-unit interpretations")
        self.session.validate_source_definition_reference(origin.creation.definition, origin.body)
        catalog = self._catalog(creator)
        wrapper, _, text = self._extractor_body(creator, catalog)
        operation = creator.index.operations.get(origin.creation.factory)
        if operation is None:
            raise ValueError("factory origin lost its original creator operation")
        replay = extract_function_creation(wrapper, operation, origin.creation.normal_value, origin.creation.normal_edge)
        if replay is None:
            raise ValueError("factory origin no longer has its original source/compiler proof")
        if (replay.definition.definition != origin.creation.definition.definition
                or replay.definition.source != origin.creation.definition.source
                or replay.definition.snapshot != origin.creation.definition.snapshot
                or replay.definition.context != origin.creation.definition.context):
            raise ValueError("factory origin extractor changed its exact original qualified child definition")
        # The source reference's independently checked authority can differ
        # from the current body's chosen authority without changing the source.
        from dataclasses import replace
        if replace(replay, definition=origin.creation.definition) != origin.creation:
            raise ValueError("factory origin extraction changed its original creator/code ports")
        self._counts["fresh_origin_validations"] += 1
        return validate_factory_entry_origin(origin, creator_graph=creator.graph, creator_document=creator.document,
            creator_namespace=creator.namespace, creator_index=creator.index, body_graph=body.graph,
            body_document=body.document, body_namespace=body.namespace, body_index=body.index, source_text=text)

    def _class_contexts(self, creator, query, depth, seen):
        namespace = GraphNamespace.from_source(creator.namespace)
        if namespace.identity in seen:
            raise ValueError("factory class creator lexical scopes form an invalid cycle")
        if depth >= self.session.budget.max_origin_depth:
            raise OverflowError("factory origin enclosing-class depth budget exhausted")
        if creator.class_entry is None:
            yield None
            return
        catalog = self._catalog(creator)
        keys = self._creator_keys(creator, catalog)
        if not keys:
            self._note(query, False, "FACTORY_ORIGIN_CLASS_PARENT_SCOPE_UNAVAILABLE",
                "The original class suite has no retained parent creator declaration.")
            return
        from scar.analysis.static_class_links import _constructions
        for key in keys:
            parent_body = self._entry_body(creator.unit_number, key)
            constructions = [row for row in _constructions(parent_body)
                if row.definition == creator.namespace.definition and row.source == creator.namespace.source]
            if not constructions:
                self._note(query, False, "FACTORY_ORIGIN_CLASS_CONSTRUCTION_UNCONNECTED",
                    "Parent entry " + key + " has no saved construction for class " + creator.namespace.definition.wire + ".")
                continue
            for construction in constructions:
                self.session.check()
                point = DependencyPoint(GraphNamespace.from_source(parent_body.namespace), construction.builder_call.operation, None)
                matched = False
                for binding, locator in self.session.class_bindings_for(point):
                    if (binding.construction != construction
                            or GraphNamespace.from_source(binding.suite) != namespace):
                        continue
                    provider = self.session.load_provider(binding.provider)
                    _, _, suite, outer, inner = class_dependency_frames(binding, provider, self.session.index)
                    if suite != namespace:
                        raise ValueError("factory class binding selected a different suite namespace")
                    matched = True
                    self._counts["class_context_bindings_replayed"] += 1
                    for parent_context in self._class_contexts(parent_body, query, depth + 1, (*seen, namespace.identity)):
                        yield context_push(parent_context, outer, inner)
                if not matched:
                    self._note(query, False, "FACTORY_ORIGIN_CLASS_BINDING_UNAVAILABLE",
                        "No saved parent/provider/suite binding selects class " + creator.namespace.definition.wire + ".")

    def contexts_for(self, origin, query, outgoing):
        if type(origin) is not StaticFactoryEntryOrigin or type(query) is not DependencyPoint or type(outgoing) is not bool:
            raise TypeError("factory origin context lookup needs an original origin/query/direction")
        if outgoing:
            yield query.context, None
            return
        # Preserve a useful unknown-context reference before any optional
        # class publication/body traversal can run out of budget.
        yield None, query.context
        try:
            creator = self.session.load_body(origin.creator)
            if creator.class_entry is None:
                return
            for context in self._class_contexts(creator, query, 0, ()):
                if context is not None:
                    yield context, query.context
        except SourceDefinitionUnavailable as error:
            self._note(query, False, "FACTORY_ORIGIN_CLASS_SCOPE_UNAVAILABLE", error.kind + ": " + error.detail)
        except (OverflowError, TimeoutError) as error:
            self._note(query, False, "FACTORY_ORIGIN_CONTEXT_BUDGET", type(error).__name__ + ": " + str(error))
        except ValueError as error:
            if str(error).startswith("CLASS_RELATIONS_NOT_PUBLISHED:"):
                self._note(query, False, "FACTORY_ORIGIN_CLASS_RELATIONS_NOT_PUBLISHED", str(error))
            else:
                raise

    def frontiers_for(self, point, outgoing):
        if point != self._note_point:
            return ()
        return tuple(self._notes[outgoing])

    def measurements(self):
        return {**dict(self._counts), "scope": "DEMAND_CURRENT_UNIT_AND_REQUIRED_CREATOR_BODIES",
            "compiler_cache_lifetime": "GENERATOR_OR_FRESH_REPLAY_ONLY", "target_executed": False,
            "origin_set_complete": False, "published": False}

    def clear(self):
        self._note_point = None
        self._notes = {False: {}, True: {}}
