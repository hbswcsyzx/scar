"""Shared, read-only dependency inputs owned by a StaticCallSession.

This adapter does not construct another input session, source basis, body or
ProgramGraph.  Existing body/index/document objects belong to the linker;
only small qualified wrappers and immutable input records are retained here.
The linker's in-progress CALL facts must be supplied explicitly as a provider:
an older saved CALL publication is deliberately never registered or loaded.
"""
from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import fields
import gzip
import hashlib
import io
from pathlib import Path
import time
from types import SimpleNamespace

from scar.analysis.program_dependency_session import (
    ProgramDependencyBudget, ProgramDependencySession, _SharedFragments,
    _UnavailableRelations, _stamp,
)
from scar.ir.program.dependencies import GraphNamespace, context_frames
from scar.ir.program.providers import ProviderArtifact
from scar.ir.program.source_call_bindings import SourceBodyNamespace
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.record_codec import decode, loads as strict_loads


class _BasisInputs(MutableMapping):
    """Registered original basis locators, without an unbounded JSON cache."""
    def __init__(self, view):
        self.view = view
        self.locators = {}

    def __getitem__(self, artifact):
        locator = self.locators[artifact]
        return self.view.read_artifact(locator)

    def __setitem__(self, artifact, document):
        from scar.analysis.static_calls import input_basis_unit
        if (document.get("schema") != "scar.static-call-source-basis"
                or document.get("schema_version") != 1
                or document.get("logical_root") != str(self.view.root)
                or document.get("units") != [input_basis_unit(unit) for unit in self.view.units]):
            raise ValueError("dependency-view source basis differs from owner inputs")
        locator = self.view._locator(artifact.uri, artifact.schema)
        if locator.artifact != artifact:
            raise ValueError("dependency-view basis artifact differs from its registered receipt")
        self.locators[artifact] = locator

    def __delitem__(self, artifact):
        del self.locators[artifact]

    def __iter__(self):
        return iter(self.locators)

    def __len__(self):
        return len(self.locators)

    def __contains__(self, artifact):
        return artifact in self.locators

    def clear(self):
        self.locators.clear()


class StaticCallDependencyView(ProgramDependencySession):
    """Dependency-provider protocol over one existing linker read lifetime.

    Receipt, source-definition and class helpers are reused from the public
    reader.  Its constructor/body decoder/cache/IO/close are not used. All
    reads and cache bytes are charged to ``owner``. ``budget`` optionally
    tightens the default owner-derived limits field by field. Input bytes and
    time use the owner's entire read lifetime, including its earlier work;
    stricter view limits never modify the owner's own access permissions.
    """
    def __init__(self, owner, *, budget=None, class_index_directory=None):
        from scar.analysis.static_calls import StaticCallSession
        if not isinstance(owner, StaticCallSession):
            raise TypeError("dependency view requires its owning StaticCallSession")
        owner._check()
        self.owner = owner
        self.root, self.units, self.manifest = owner.logical_root, owner.units, owner.manifest
        limits = owner.budget
        ceiling = ProgramDependencyBudget(
                max_manifest_bytes=limits.max_manifest_bytes,
                max_record_bytes=limits.max_record_bytes,
                max_input_bytes=limits.max_input_bytes,
                max_cached_bytes=limits.max_cached_bytes,
                max_graphs=limits.max_bodies,
                max_shards=limits.max_bodies,
                max_routing_shards=limits.max_bodies,
                max_routing_references=limits.max_namespace_facts,
                max_origin_candidates=limits.max_candidates_per_call,
                max_origin_depth=limits.max_context_depth,
                max_entry_owner_edges=min(128, limits.max_resolution_steps),
                max_entry_snapshots=min(128, limits.max_namespace_facts),
                max_entry_projections=min(256, limits.max_namespace_facts),
                max_seconds=limits.max_seconds)
        if budget is not None and type(budget) is not ProgramDependencyBudget:
            raise TypeError("dependency view budget must be ProgramDependencyBudget")
        self.budget = ceiling if budget is None else ProgramDependencyBudget(**{
            field.name: min(getattr(ceiling, field.name), getattr(budget, field.name))
            for field in fields(ceiling)})
        self.started, self.closed = owner.started, False
        self._stamps = owner._stamps
        self._artifacts, self._logical, self._descriptor_aliases = {}, {}, {}
        self._implementation_graphs = {}
        self._uris_by_key = {}
        self._bases = _BasisInputs(self)
        self._body_paths = dict(owner._body_locations)
        self._unit_numbers = {id(unit): number for number, unit in enumerate(self.units)}
        self._input_parts = {}
        self._seen_graphs, self._seen_shards = set(), set()
        self._call_routing, self._origin_discovery = None, None
        self._entry_namespace_provider = None
        self._unpack_projection_provider = None
        self._environment_facts = owner._environment_facts
        self._cache_prefix = ("static-call-dependency-view", id(self))
        self.fragments = _SharedFragments(self)
        manifest_path = owner.root / "manifest.json"
        manifest_stamp = self._stamps.get(manifest_path)
        if manifest_stamp is None:
            raise ValueError("owner did not pin its original manifest")
        if manifest_stamp[2] > self.budget.max_manifest_bytes:
            raise OverflowError("dependency-view original manifest exceeds its byte ceiling")
        self.manifest_artifact = ProviderArtifact(str(manifest_path),
            owner.manifest_sha256, manifest_stamp[2], "scar.static-program")
        for number, unit in enumerate(self.units):
            for name, descriptor in unit["artifacts"].items():
                self._register_model(descriptor)
                uri = str(self.root / descriptor["path"])
                self._input_parts.setdefault(uri, []).append((number, name))
            for row in unit.get("bodies", ()):
                if "artifact" in row:
                    self._register_model(row["artifact"])
        for descriptor in self.manifest.get("artifacts", {}).values():
            self._register_model(descriptor)
        basis_rows = [row for row in owner.artifacts if row.get("kind") == "BASIS"]
        if len(basis_rows) != 1:
            raise ValueError("owner does not have one original source basis")
        basis_descriptor = basis_rows[0]
        self._register(owner.basis.uri, owner.out / basis_descriptor["path"], basis_descriptor)
        self._bases[owner.basis] = self.read_artifact(self._locator(owner.basis.uri, owner.basis.schema))
        self.call_publication = None
        self._call_items, self._call_by_namespace = {}, {}
        self.class_publication = self.manifest.get("static_classes")
        self._class_items, self._class_by_namespace, self._class_shard_order = {}, {}, {}
        if self.class_publication is not None:
            if class_index_directory is None:
                basis = decode(ProviderArtifact, self.class_publication["source_model"])
                logical_index = Path(basis.uri).parent
                if not logical_index.is_relative_to(self.root):
                    raise ValueError("class publication is outside the owner's logical model")
                class_index_directory = owner.root / logical_index.relative_to(self.root)
            self._register_publication(self.class_publication, class_index_directory, "classes")

    @property
    def input_bytes(self):
        return self.owner.input_bytes

    def check(self):
        if self.closed:
            raise ValueError("static call dependency view is closed")
        self.owner._check()
        if self.owner.input_bytes > self.budget.max_input_bytes:
            raise OverflowError("dependency-view owner-relative cumulative input budget exhausted")
        if (not self.owner._finalizing and
                time.monotonic() - self.started > self.budget.max_seconds):
            raise TimeoutError("dependency-view discovery exceeded its owner-relative time allowance")

    def _preflight_reads(self, descriptors):
        """Refuse cold owner reads before spending stored or decoded bytes."""
        self.check()
        cost = 0
        record_limit = min(self.budget.max_record_bytes, self.owner.budget.max_record_bytes)
        for descriptor in descriptors:
            stored, decoded = descriptor["bytes"], descriptor["decoded_bytes"]
            if (type(stored) is not int or type(decoded) is not int
                    or stored < 1 or decoded < 1):
                raise ValueError("dependency-view read needs exact positive original byte counts")
            if max(stored, decoded) > record_limit:
                raise OverflowError("dependency-view original stored/decoded record exceeds its byte ceiling")
            path = Path(descriptor["path"])
            uri = str(path) if path.is_absolute() else str(self.root / path)
            key = self._logical.get(uri, str(path) if path.is_absolute() else None)
            if key not in self._artifacts:
                raise ValueError("dependency-view cold read has no registered original descriptor")
            if self._pin(self._artifacts[key][0])[2] != stored:
                raise ValueError("dependency-view original stored byte receipt differs before read")
            cost += stored + decoded
        if self.owner.input_bytes + cost > min(
                self.budget.max_input_bytes, self.owner.budget.max_input_bytes):
            raise OverflowError("dependency-view cold input exceeds its owner-relative byte budget")

    def _owner_unit(self, number):
        self.check()
        if ("unit", number) not in self.owner._cache:
            artifacts = self.units[number]["artifacts"]
            required = ("source", "lexical", "semantic", "semantics", "control")
            # Preserve the owner's precise missing-context error rather than
            # inventing a descriptor for an unavailable original fragment.
            if all(name in artifacts for name in required):
                self._preflight_reads(artifacts[name] for name in required)
        context = self.owner._unit(number)
        self.check()
        return context

    def _register_model(self, descriptor):
        relative = Path(descriptor["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("dependency-view input escapes the original model")
        self._register(str(self.root / relative), self.owner.root / relative, descriptor)

    def _register(self, uri, physical, descriptor):
        ProgramDependencySession._register(self, uri, physical, descriptor)
        self._uris_by_key.setdefault(str(physical), {})[uri] = None

    def register_implementation_graph(self, locator, representation, graph):
        """Share explicit derived graph IO with this view's original owner.

        The existing generic registered-read branch already uses owner byte
        budgets, stamps, strict gzip JSON decoding and its prefixed LRU. No
        additional reader or large graph store is introduced here.
        """
        if type(locator) is not SourceArtifactLocator:
            raise TypeError('implementation registration needs SourceArtifactLocator')
        key = locator.artifact.uri
        previous = self._uris_by_key.get(key)
        if previous is not None and any(uri in self._body_paths for uri in previous):
            raise ValueError('implementation registration cannot relabel an original source body')
        previous = None if previous is None else dict(previous)
        try:
            return ProgramDependencySession.register_implementation_graph(self, locator, representation, graph)
        except BaseException:
            if previous is None:
                self._uris_by_key.pop(key, None)
            else:
                self._uris_by_key[key] = previous
            raise

    def read(self, descriptor):
        relative = Path(descriptor["path"])
        if ".." in relative.parts:
            raise ValueError("dependency-view descriptor escapes its original owner")
        uri = str(relative) if relative.is_absolute() else str(self.root / relative)
        key = self._logical.get(uri)
        if key is None:
            raise ValueError("dependency-view descriptor is not an original registered input")
        registered = self._artifacts[key][1]
        if any(descriptor[name] != registered[name]
                for name in ("bytes", "sha256", "decoded_bytes", "decoded_sha256")):
            raise ValueError("dependency-view descriptor differs from its registered receipt")
        return self._read_registered(key)

    def _get(self, key):
        self.check()
        owned = (*self._cache_prefix, key)
        cached = self.owner._cache.get(owned)
        if cached is None:
            return None
        self.owner._cache.move_to_end(owned)
        return cached[0]

    def _put(self, key, value, size):
        self.check()
        if type(size) is not int or size < 0:
            raise ValueError("dependency-view cache needs an explicit byte estimate")
        owned = (*self._cache_prefix, key)
        old = self.owner._cache.pop(owned, None)
        if old is not None:
            self.owner._cache_bytes -= old[1]
        if size > min(self.budget.max_cached_bytes, self.owner.budget.max_cached_bytes):
            return value
        self.owner._remember(owned, value, size)
        # Both the global owner and this provider's optional smaller cache
        # allowance apply.  Entries are original inputs, never proof/PASS flags.
        def ours(item):
            return type(item) is tuple and item[:2] == self._cache_prefix
        used = sum(row[1] for item, row in self.owner._cache.items() if ours(item))
        for item in tuple(self.owner._cache):
            if used <= self.budget.max_cached_bytes:
                break
            if ours(item):
                _, removed = self.owner._cache.pop(item)
                self.owner._cache_bytes -= removed
                used -= removed
        return value

    def _pin(self, physical):
        if physical.is_symlink() or physical.resolve() != physical or not physical.is_file():
            raise ValueError("dependency-view original input is absent or traverses symlinks")
        stamp = _stamp(physical)
        if physical in self._stamps and self._stamps[physical] != stamp:
            raise ValueError("dependency-view original input changed during owner analysis")
        return stamp

    def _read_registered(self, key, *, cache_document=True):
        self.check()
        physical, descriptor = self._artifacts[key]
        before = self._pin(physical)
        # The owner has already decoded these exact bodies and source-unit
        # documents. Reuse those objects; do not start a second core decoder.
        uris = self._uris_by_key[key]
        for uri in uris:
            location = self._body_paths.get(uri)
            if location is not None:
                document = self._base_body(*location).document
                if self._pin(physical) != before:
                    raise ValueError("shared original body changed during access")
                return document
            for number, name in self._input_parts.get(uri, ()):
                if name in ("source", "lexical", "semantic", "semantics", "control"):
                    document = (self._catalog(number) if name == "lexical"
                        else self._owner_unit(number).docs[name])
                    if self._pin(physical) != before:
                        raise ValueError("shared original source context changed during access")
                    return document
        cache_key = ("document", key, descriptor["sha256"])
        found = self._get(cache_key) if cache_document else None
        if found is not None:
            return found
        if before[2] != descriptor["bytes"]:
            raise ValueError("dependency-view original stored byte receipt differs")
        self._preflight_reads((descriptor,))
        maximum = descriptor["decoded_bytes"]
        if (type(maximum) is not int or maximum < 1
                or maximum > min(self.budget.max_record_bytes, self.owner.budget.max_record_bytes)):
            raise OverflowError("dependency-view original decoded record exceeds its byte ceiling")
        reread = physical in self._stamps
        stored = self.owner._read_file(physical,
            min(self.budget.max_record_bytes, self.owner.budget.max_record_bytes))
        if len(stored) != descriptor["bytes"] or hashlib.sha256(stored).hexdigest() != descriptor["sha256"]:
            raise ValueError("dependency-view original stored receipt differs")
        if self.owner.input_bytes + maximum > min(
                self.budget.max_input_bytes, self.owner.budget.max_input_bytes):
            raise OverflowError("dependency-view decoded input exceeds its owner-relative byte budget")
        with gzip.GzipFile(fileobj=io.BytesIO(stored)) as stream:
            raw = stream.read(maximum + 1)
        self.owner.input_bytes += len(raw)
        if len(raw) != maximum or hashlib.sha256(raw).hexdigest() != descriptor["decoded_sha256"]:
            raise ValueError("dependency-view original decoded receipt differs")
        if self._pin(physical) != before:
            raise ValueError("dependency-view original record changed during read")
        document = strict_loads(raw.decode())
        self.owner.counts["fragment_reads"] += 1
        self.owner.counts["fragment_rereads"] += int(reread)
        self.owner.counts["fragment_stored_bytes_read"] += len(stored)
        self.owner.counts["fragment_decoded_bytes_read"] += len(raw)
        return self._put(cache_key, document, maximum) if cache_document else document

    def _catalog(self, number):
        self.check()
        self._preflight_reads((self.units[number]["artifacts"]["lexical"],))
        catalog = self.owner._catalog(number)
        self.check()
        return catalog

    def _base_body(self, number, position):
        self.check()
        key = ("body", number, position)
        if key not in self._seen_graphs and len(self._seen_graphs) >= self.budget.max_graphs:
            raise OverflowError("dependency-view original body budget exhausted")
        context = self._owner_unit(number)
        row = self.units[number]["bodies"][position]
        if ("body", number, position) not in self.owner._cache and "artifact" in row:
            self._preflight_reads((row["artifact"],))
        original = self.owner._body(context, position, row)
        self.check()
        if original is None:
            raise ValueError("dependency-view source entry has no original canonical body")
        self._seen_graphs.add(key)
        # Explicit fields, all pointing at the owner's checked original
        # objects. No unchecked namespace/declaration is copied from a client.
        return SimpleNamespace(graph=original.graph, index=original.index,
            document=original.document, metadata=original.metadata,
            namespace=original.namespace, interface=original.interface,
            module=original.module, class_entry=original.class_entry,
            context=context, unit=context.unit, unit_number=number,
            body_position=position, row=row, catalog=context.catalog,
            dependencies=self.owner._namespace_for(original),
            operation_links=original.operation_links, use_links=original.use_links,
            links_by_op=original.links_by_op, uses_by_op=original.uses_by_op,
            call_source_bases=original.call_source_bases)

    def load_body(self, namespace):
        if type(namespace) is not SourceBodyNamespace:
            raise TypeError("dependency-view body lookup requires an original source namespace")
        namespace.__post_init__()
        location = self._body_paths.get(namespace.graph.artifact.uri)
        if location is None:
            raise ValueError("dependency-view body is outside the owner's original inputs")
        number, position = location
        self._declaration(namespace, number, position)
        self.read_artifact(namespace.graph)
        original = self._base_body(number, position)
        if (namespace.graph.pointer != "#/graph" or namespace.graph.artifact.schema != "scar.static-body/1"
                or namespace.graph_representation != original.namespace.graph_representation
                or namespace.definition != original.namespace.definition
                or namespace.source != original.namespace.source
                or namespace.entry != original.namespace.entry or namespace.region != original.graph.root):
            raise ValueError("dependency-view namespace changed original source/body endpoints")
        self._environment_facts.body(original.graph, original.document, namespace, index=original.index)
        original.namespace = namespace
        return original

    def source_text(self, owner):
        number = owner.unit_number if hasattr(owner, "unit_number") else self._unit_numbers[id(owner)]
        return self._owner_unit(number).docs["source"]["text"]

    def source_context(self, body):
        context = self._owner_unit(body.unit_number)
        return context.tree, context.semantic, context.docs["source"]["text"]

    def class_bindings_for(self, point):
        """Reuse original class material, freshly checking each chosen binding."""
        from scar.analysis.static_class_builder import validate_class_builder_expansion
        from scar.analysis.static_class_links import _constructions
        from scar.ir.program.class_builder import ClassBuilderExpansion, StaticClassBuilderBinding
        if self.class_publication is None:
            raise ValueError("CLASS_RELATIONS_NOT_PUBLISHED: no saved class relationships were supplied")
        if point.namespace.source_body is not None and not (
                self._class_interface_point(point, True) or self._class_interface_point(point, False)):
            return
        selected = {point.namespace}
        for frame in context_frames(point.context):
            selected.update((frame.caller, frame.target))
        uris = dict.fromkeys(uri for namespace in selected
            for uri in self._class_by_namespace.get(namespace, ()))
        for uri in sorted(uris, key=self._class_shard_order.__getitem__):
            self._admit_shard(uri)
            item = self._class_items[uri]
            parent = decode(SourceBodyNamespace, item["parent"])
            locator = self._locator(uri, "scar.static-class-bindings/1")
            document = self.read_artifact(locator)
            if (document.get("schema") != "scar.static-class-bindings" or document.get("schema_version") != 1
                    or document.get("source_model") != self.class_publication["source_model"]
                    or document.get("parent") != item["parent"]):
                raise ValueError("dependency-view class relationship schema/basis/parent differs")
            for number, raw in enumerate(document["bindings"]):
                binding = decode(StaticClassBuilderBinding, raw)
                if binding.parent != parent:
                    raise ValueError("dependency-view class binding has another original parent")
                parent_body, suite = self.load_body(binding.parent), self.load_body(binding.suite)
                if binding.construction not in _constructions(parent_body):
                    raise ValueError("dependency-view class binding is not an original parent construction")
                provider = self.load_provider(binding.provider)
                values = {field.name: getattr(binding, field.name) for field in fields(binding)
                    if field.name != "provider"}
                validate_class_builder_expansion(ClassBuilderExpansion(**values, provider=provider),
                    parent_graph=parent_body.graph, suite_graph=suite.graph, suite_overlay=suite.class_entry)
                from dataclasses import replace
                yield binding, replace(locator, pointer="#/bindings/" + str(number))

    def graph(self):
        from scar.analysis.program_dependencies import ProgramDependencyGraph
        from scar.analysis.program_class_dependencies import ClassDependencyProvider
        from scar.analysis.program_function_origin_discovery import AutomaticFactoryEntryOrigins
        from scar.analysis.program_function_origin_dependencies import FactoryEntryOriginDependencyProvider
        from scar.analysis.program_entry_namespace_dependencies import EntryNamespaceDependencyProvider
        from scar.analysis.program_unpack_dependencies import UnpackProjectionProvider
        graph = getattr(self, "_view", None)
        if graph is None:
            classes = (ClassDependencyProvider(self.class_bindings_for, self.index, self.load_provider,
                coverage=self._class_relation_coverage) if self.class_publication is not None else
                _UnavailableRelations("CLASS_RELATIONS_NOT_PUBLISHED",
                    "No saved class relationships were supplied for this original class interface.",
                    self._class_interface_point, relation_kinds=ClassDependencyProvider.relation_kinds))
            origins = self._origin_discovery = AutomaticFactoryEntryOrigins(self)
            factories = FactoryEntryOriginDependencyProvider(origins_for=origins.origins_for,
                load_index=self.index, validate_origin=origins.validate_origin,
                interface_scope=origins.interface_scope, contexts_for=origins.contexts_for,
                discovery_frontiers=origins.frontiers_for)
            entries = self._entry_namespace_provider = EntryNamespaceDependencyProvider(self)
            if self._unpack_projection_provider is None:
                self._unpack_projection_provider = UnpackProjectionProvider(self)
            graph = self._view = ProgramDependencyGraph(self.index,
                providers=(classes, factories, entries, self._unpack_projection_provider))
        return graph

    def measurements(self):
        return {"input_bytes": self.owner.input_bytes,
            "registered_implementation_graphs": len(self._implementation_graphs),
            "cache_accounted_bytes": self.owner._cache_bytes + self._environment_facts.bytes,
            "shared_original_bodies": sum(key[0] == "body" for key in self._seen_graphs),
            "relationship_shards_read": len(self._seen_shards),
            "factory_origin_discovery": (self._origin_discovery.measurements()
                if self._origin_discovery is not None else None),
            "entry_namespace_discovery": (self._entry_namespace_provider.measurements()
                if self._entry_namespace_provider is not None else None),
            "unpack_projection": (self._unpack_projection_provider.measurements()
                if self._unpack_projection_provider is not None else None),
            "input_and_cache_owner": "STATIC_CALL_SESSION", "saved_call_publication_loaded": False,
            "seconds": time.monotonic() - self.started, "target_executed": False}

    def close(self):
        if self.closed:
            return
        failure = None
        try:
            for namespace in self._implementation_graphs.values():
                self._pin(Path(namespace.graph.artifact.uri))
        except BaseException as error:
            failure = error
        if self._origin_discovery is not None:
            self._origin_discovery.clear()
        if self._entry_namespace_provider is not None:
            self._entry_namespace_provider.clear()
        if self._unpack_projection_provider is not None:
            self._unpack_projection_provider.clear()
        graph = getattr(self, "_view", None)
        if graph is not None:
            graph.providers.clear()
        for key in tuple(self.owner._cache):
            if type(key) is tuple and key[:2] == self._cache_prefix:
                _, size = self.owner._cache.pop(key)
                self.owner._cache_bytes -= size
        self._bases.clear()
        self._implementation_graphs.clear()
        self.closed = True
        if failure is not None:
            raise failure


__all__ = ["StaticCallDependencyView"]
