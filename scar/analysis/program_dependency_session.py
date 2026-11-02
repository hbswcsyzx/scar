"""One bounded read session for the original sharded program-dependency view.

No collector, target import or graph builder is started. Core graphs and their
indices are shared across local and cross-body adapters; stored relations are
replayed against their original inputs before use. Missing publications are
open boundaries, never empty dependency proofs.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, replace
import ast
import hashlib
import json
from pathlib import Path
import time
from types import SimpleNamespace

from scar.ir.program.dependencies import GraphNamespace
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.program.source_call_bindings import SourceBodyNamespace
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.record_codec import decode, encode


@dataclass(frozen=True, slots=True)
class ProgramDependencyBudget:
    max_manifest_bytes: int = 256 * 1024 * 1024
    max_record_bytes: int = 256 * 1024 * 1024
    max_input_bytes: int = 512 * 1024 * 1024
    max_cached_bytes: int = 128 * 1024 * 1024
    max_graphs: int = 16
    max_shards: int = 256
    max_routing_shards: int = 10000
    max_routing_references: int = 1000000
    max_seconds: int = 60

    def __post_init__(self):
        from dataclasses import fields
        for field in fields(self):
            value = getattr(self, field.name)
            if type(value) is not int or value < 1:
                raise ValueError("dependency budget requires positive " + field.name)


class _CoreGraphs:
    """Existing verifier's graph lookup delegates to the one core owner."""
    def __init__(self, owner):
        self.owner = owner

    def get(self, path, default=None):
        location = self.owner._body_paths.get(str(self.owner.root / path))
        return self.owner._base_body(*location).graph if location is not None else default


class _SharedFragments:
    def __init__(self, owner):
        self.owner, self.root = owner, owner.root
        self.core_graphs = _CoreGraphs(owner)
        self.receipts = []

    def read(self, descriptor):
        return self.owner.read(descriptor)


def _stamp(path):
    info = path.stat()
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


class ProgramDependencySession:
    def __init__(self, directory, *, budget=None, call_publication=None, call_index_directory=None,
                 class_publication=None, class_index_directory=None):
        self.root = Path(directory).absolute()
        if self.root.resolve() != self.root or self.root.is_symlink():
            raise ValueError("dependency model must not traverse symlinks")
        self.budget = budget or ProgramDependencyBudget()
        if type(self.budget) is not ProgramDependencyBudget:
            raise TypeError("budget must be ProgramDependencyBudget")
        self.started, self.input_bytes, self.closed = time.monotonic(), 0, False
        self._stamps, self._artifacts, self._logical, self._bases = {}, {}, {}, {}
        self._descriptor_aliases = {}
        self._cache, self._cache_bytes = OrderedDict(), 0
        self._seen_graphs, self._seen_shards = set(), set()
        self._call_routing = None
        from scar.analysis.static_function_environment import _EnvironmentFacts
        self._environment_facts = _EnvironmentFacts(max_bodies=self.budget.max_graphs,
            max_bytes=max(1, min(32 * 1024 * 1024, self.budget.max_cached_bytes // 4)))
        manifest_path = self.root / "manifest.json"
        if manifest_path.resolve() != manifest_path or manifest_path.is_symlink():
            raise ValueError("dependency manifest must not traverse symlinks")
        before = _stamp(manifest_path)
        if before[2] > self.budget.max_manifest_bytes or before[2] > self.budget.max_input_bytes:
            raise OverflowError("dependency manifest byte budget exhausted")
        with manifest_path.open("rb") as stream:
            raw = stream.read(before[2] + 1)
        if len(raw) != before[2] or _stamp(manifest_path) != before:
            raise ValueError("dependency manifest changed during read")
        self.input_bytes += len(raw)
        self._stamps[manifest_path] = before
        self.manifest = json.loads(raw)
        if (self.manifest.get("schema") != "scar.static-program" or self.manifest.get("schema_version") != 1
                or type(self.manifest.get("units")) is not list):
            raise ValueError("unsupported original static program model")
        self.manifest_artifact = ProviderArtifact(str(manifest_path), hashlib.sha256(raw).hexdigest(), len(raw), "scar.static-program")
        self.units = self.manifest["units"]
        self._body_paths, self._unit_numbers = {}, {}
        for number, unit in enumerate(self.units):
            self._unit_numbers[id(unit)] = number
            for descriptor in unit["artifacts"].values():
                self._register_model(descriptor)
            for position, row in enumerate(unit.get("bodies", ())):
                if "artifact" in row:
                    self._register_model(row["artifact"])
                    uri = str(self.root / row["artifact"]["path"])
                    if uri in self._body_paths:
                        raise ValueError("original body artifact has multiple owners")
                    self._body_paths[uri] = number, position
        for descriptor in self.manifest.get("artifacts", {}).values():
            self._register_model(descriptor)
        self.fragments = _SharedFragments(self)
        self.call_publication = call_publication if call_publication is not None else self.manifest.get("static_calls")
        self.class_publication = class_publication if class_publication is not None else self.manifest.get("static_classes")
        self._call_items, self._class_items = {}, {}
        self._call_by_namespace, self._class_by_namespace = {}, {}
        self._class_shard_order = {}
        if self.call_publication is not None:
            self._register_publication(self.call_publication, call_index_directory, "calls")
        if self.class_publication is not None:
            self._register_publication(self.class_publication, class_index_directory, "classes")

    def check(self):
        if self.closed:
            raise ValueError("dependency session is closed")
        if time.monotonic() - self.started > self.budget.max_seconds:
            raise TimeoutError("dependency session wall budget exhausted")

    def _register_model(self, descriptor):
        relative = Path(descriptor["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("original fragment escapes model")
        self._register(str(self.root / relative), self.root / relative, descriptor)

    def _register(self, uri, physical, descriptor):
        key = str(physical)
        receipt = {name: descriptor[name] for name in ("bytes", "sha256", "decoded_bytes", "decoded_sha256")}
        previous = self._artifacts.get(key)
        if previous is not None and {name: previous[1][name] for name in receipt} != receipt:
            raise ValueError("one artifact path has conflicting receipts")
        self._artifacts[key] = physical, {**receipt, "path": str(physical.relative_to(self.root))
            if physical.is_relative_to(self.root) else str(physical)}
        old = self._logical.get(uri)
        if old is not None and old != key:
            raise ValueError("one logical artifact has conflicting physical owners")
        self._logical[uri] = key

    def _register_publication(self, publication, index_directory, family):
        from scar.analysis.static_calls import input_basis_unit
        expected = "scar.static-call-publication" if family == "calls" else "scar.static-class-publication"
        if publication.get("schema") != expected:
            raise ValueError("unsupported " + family + " dependency publication")
        artifact = decode(ProviderArtifact, publication["source_model"])
        logical_index = Path(artifact.uri).parent
        physical_index = Path(index_directory).absolute() if index_directory is not None else logical_index
        normalized = {}
        by_relative = {}
        for descriptor in publication["artifacts"]:
            relative = Path(descriptor["path"])
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("relationship artifact escapes its index")
            candidate = self.root / relative
            logical = candidate if candidate.is_relative_to(logical_index) else logical_index / relative
            suffix = logical.relative_to(logical_index)
            self._register(str(logical), physical_index / suffix, descriptor)
            by_relative[suffix.as_posix()] = str(logical)
            normalized[str(logical)] = {**descriptor, "path": logical.relative_to(self.root).as_posix()
                if logical.is_relative_to(self.root) else str(logical)}
        basis = self.read_artifact(SourceArtifactLocator(artifact,
            next(d["decoded_sha256"] for d in publication["artifacts"] if d.get("kind") == "BASIS"),
            next(d["decoded_bytes"] for d in publication["artifacts"] if d.get("kind") == "BASIS"), "gzip-canonical-json"))
        if (basis.get("schema") != "scar.static-call-source-basis" or basis.get("schema_version") != 1
                or basis.get("logical_root") != str(self.root)
                or basis.get("units") != [input_basis_unit(unit) for unit in self.units]):
            raise ValueError("relationship source basis differs from original current units")
        self._bases[artifact] = basis
        items = self._call_items if family == "calls" else self._class_items
        adjacency = self._call_by_namespace if family == 'calls' else self._class_by_namespace
        for item in publication.get("shards", ()):
            relative = item.get("artifact_path") or item["artifact"]["path"]
            if relative not in by_relative:
                # Published wrappers may prefix descriptors but shard paths
                # remain relative to their original index.
                suffix = Path(relative)
                if suffix.is_relative_to(Path("indexes") / family):
                    relative = suffix.relative_to(Path("indexes") / family).as_posix()
            uri = by_relative.get(relative)
            if uri is None:
                raise ValueError("relationship shard is absent from publication artifacts")
            if uri in items:
                raise ValueError('duplicate original relationship shard header')
            owner = decode(SourceBodyNamespace, item['caller' if family == 'calls' else 'parent'])
            namespace = GraphNamespace.from_source(owner)
            adjacency.setdefault(namespace, []).append(uri)
            if family == 'classes':
                self._class_shard_order[uri] = len(items)
            items[uri] = item
            if family == "calls":
                # The existing verifier addresses shards through this display
                # prefix. Only descriptor lookup is adapted; original graph,
                # source-basis and relation locators keep their actual URIs.
                alias = "indexes/calls/" + (item.get("artifact_path") or item["artifact"]["path"])
                physical_key = self._logical[uri]
                previous = self._descriptor_aliases.get(str(self.root / alias))
                if previous is not None and previous != physical_key:
                    raise ValueError("call verifier descriptor aliases conflict")
                self._descriptor_aliases[str(self.root / alias)] = physical_key
                normalized[uri] = {**normalized[uri], "path": alias}
        if family == "calls":
            self._call_verify_publication = {**publication, "artifacts": list(normalized.values())}

    def _get(self, key):
        item = self._cache.get(key)
        if item is None:
            return None
        self._cache.move_to_end(key)
        return item[0]

    def _put(self, key, value, size):
        old = self._cache.pop(key, None)
        if old is not None:
            self._cache_bytes -= old[1]
        if size <= self.budget.max_cached_bytes:
            self._cache[key] = value, size
            self._cache_bytes += size
            while self._cache and self._cache_bytes > self.budget.max_cached_bytes:
                _, (_, removed) = self._cache.popitem(last=False)
                self._cache_bytes -= removed
        return value

    def _read_registered(self, key, *, cache_document=True):
        self.check()
        from scar.analysis.static_query import _Fragments
        physical, descriptor = self._artifacts[key]
        if physical.resolve() != physical or physical.is_symlink() or not physical.is_file():
            raise ValueError("dependency artifact is absent or traverses symlinks")
        before = _stamp(physical)
        old = self._stamps.setdefault(physical, before)
        if old != before:
            raise ValueError("dependency artifact changed within this read session")
        cache_key = "document", key, descriptor["sha256"]
        cached = self._get(cache_key)
        if cached is not None:
            return cached
        cost = descriptor["bytes"] + descriptor["decoded_bytes"]
        if max(descriptor["bytes"], descriptor["decoded_bytes"]) > self.budget.max_record_bytes:
            raise OverflowError("dependency record byte budget exhausted")
        if self.input_bytes + cost > self.budget.max_input_bytes:
            raise OverflowError("dependency total input budget exhausted")
        self.input_bytes += cost
        reader = SimpleNamespace(root=physical.parent, receipts=self.fragments.receipts)
        document = _Fragments.read(reader, {**descriptor, "path": physical.name})
        if _stamp(physical) != before:
            raise ValueError("dependency artifact changed during read")
        return self._put(cache_key, document, descriptor["decoded_bytes"]) if cache_document else document

    def read(self, descriptor):
        relative = Path(descriptor["path"])
        if ".." in relative.parts:
            raise ValueError("dependency descriptor escapes its original registered owner")
        if relative.is_absolute():
            key = self._logical.get(str(relative))
        else:
            key = str(self.root / relative)
            key = self._descriptor_aliases.get(key, key)
        if key not in self._artifacts:
            raise ValueError("dependency descriptor is not registered")
        registered = self._artifacts[key][1]
        if any(descriptor[name] != registered[name] for name in ("bytes", "sha256", "decoded_bytes", "decoded_sha256")):
            raise ValueError("dependency descriptor receipt differs from its registered owner")
        return self._read_registered(key)

    def _locator(self, uri, schema, pointer="#", declaration=None):
        if uri not in self._logical:
            raise ValueError("dependency locator has no registered owner")
        descriptor = self._artifacts[self._logical[uri]][1]
        return SourceArtifactLocator(ProviderArtifact(uri, descriptor["sha256"], descriptor["bytes"], schema),
            descriptor["decoded_sha256"], descriptor["decoded_bytes"], "gzip-canonical-json", pointer, declaration)

    def read_artifact(self, locator):
        locator.__post_init__()
        uri = locator.artifact.uri
        if uri not in self._logical:
            raise ValueError("dependency artifact is outside registered original inputs")
        descriptor = self._artifacts[self._logical[uri]][1]
        if (locator.artifact.sha256 != descriptor["sha256"] or locator.artifact.size_bytes != descriptor["bytes"]
                or locator.decoded_sha256 != descriptor["decoded_sha256"] or locator.decoded_bytes != descriptor["decoded_bytes"]
                or locator.representation != "gzip-canonical-json"):
            raise ValueError("dependency locator differs from its original stored/decoded receipt")
        self._artifact_declaration(locator)
        return self._read_registered(self._logical[uri])

    def _artifact_declaration(self, locator):
        """A cache identity does not confer authority on a new declaration."""
        declaration = locator.declaration
        if declaration is None:
            return
        if declaration.artifact == self.manifest_artifact:
            value = self.manifest
        elif declaration.artifact in self._bases:
            key = self._logical.get(declaration.artifact.uri)
            if key is None:
                raise ValueError("declaration basis has no registered immutable artifact")
            physical = self._artifacts[key][0]
            if physical.is_symlink() or physical.resolve() != physical or _stamp(physical) != self._stamps[physical]:
                raise ValueError("original declaration basis changed during query")
            # Whole-basis input correspondence was checked at registration;
            # retain those original inputs, not a remembered proof boolean.
            value = self._bases[declaration.artifact]
        else:
            raise ValueError("artifact declaration is outside registered original bases")
        pointer = declaration.locator
        if not pointer.startswith("#/"):
            raise ValueError("artifact declaration needs an original descriptor pointer")
        try:
            for token in pointer[2:].split("/"):
                token = token.replace("~1", "/").replace("~0", "~")
                value = value[int(token)] if type(value) is list else value[token]
        except (ValueError, TypeError, KeyError, IndexError):
            raise ValueError("artifact declaration points outside its original basis") from None
        if (type(value) is not dict or "path" not in value
                or str(self.root / value["path"]) != locator.artifact.uri
                or value.get("sha256") != locator.artifact.sha256
                or value.get("bytes") != locator.artifact.size_bytes
                or value.get("decoded_sha256") != locator.decoded_sha256
                or value.get("decoded_bytes") != locator.decoded_bytes):
            raise ValueError("artifact declaration does not describe this original fragment")

    def _declaration(self, namespace, number, position):
        declaration = namespace.graph.declaration
        if declaration is None or declaration.locator != f"#/units/{number}/bodies/{position}/artifact":
            raise ValueError("body namespace declaration points to a different original entry")
        if declaration.artifact == self.manifest_artifact:
            return
        basis = self._bases.get(declaration.artifact)
        if basis is None:
            raise ValueError("body namespace declaration is outside registered immutable bases")

    def _catalog(self, number):
        from scar.analysis.static_query import _catalog
        key = "catalog", number
        cached = self._get(key)
        if cached is not None:
            return cached
        unit = self.units[number]
        value = _catalog(unit, self.fragments)
        if value is None:
            raise ValueError("original lexical catalog is not available")
        return self._put(key, value, unit["artifacts"]["lexical"]["decoded_bytes"])

    def _base_body(self, number, position):
        from scar.analysis.static_function_environment import validate_static_body_namespace
        from scar.analysis.static_namespace import NamespaceDependencies
        from scar.ir.program.codec import loads as load_core
        from scar.ir.program.queries import ProgramIndex
        from scar.ir.program.source import LoweringMetadata
        from scar.ir.program.module_entries import decode_frame_body
        from scar.ir.program.class_entries import decode_class_entry_overlay
        from scar.ir.program.functions import BodyEntryInterface
        from scar.ir.v2.common import SourceReference
        key = "body", number, position
        cached = self._get(key)
        if cached is not None:
            return cached
        unit, row = self.units[number], self.units[number]["bodies"][position]
        if "artifact" not in row:
            raise ValueError("original source entry has no canonical graph")
        descriptor = row["artifact"]
        document = self.read(descriptor)
        if (document.get("schema") != "scar.static-body" or document.get("schema_version") != 1
                or document.get("entry_key") != row["entry_key"] or document.get("cache_key") != row.get("cache_key")
                or document.get("status") != row["status"] or row["status"] != "LOWERED_WITH_GAPS"
                or document.get("graph") is None
                or document.get("inputs") != {name: unit["artifacts"].get(name) for name in ("source", "semantic", "semantics", "control")}):
            raise ValueError("canonical graph differs from original source/body ledger")
        if key not in self._seen_graphs and len(self._seen_graphs) >= self.budget.max_graphs:
            raise OverflowError("dependency graph-read budget exhausted")
        self._seen_graphs.add(key)
        graph = load_core(json.dumps(document["graph"], allow_nan=False))
        metadata = decode(LoweringMetadata, document["metadata"])
        catalog = self._catalog(number)
        matches = [entry for entry in catalog["entries"] if entry["entry_key"] == row["entry_key"]]
        if len(matches) != 1:
            raise ValueError("canonical graph lacks its original lexical entry")
        entry = matches[0]
        module = decode_frame_body(document["module"]) if document.get("module") is not None else None
        class_entry = decode_class_entry_overlay(document["class"]) if document.get("class") is not None else None
        interface = decode(BodyEntryInterface, document["interface"]) if module is None and class_entry is None else None
        definition = (module.declaration.unit.initializer if module is not None else
                      class_entry.definition if class_entry is not None else interface.definition)
        source = None if module is not None else decode(SourceReference, entry["source_ref"])
        uri = str(self.root / descriptor["path"])
        locator = self._locator(uri, "scar.static-body/1", "#/graph",
            ProviderFactReference(self.manifest_artifact, f"#/units/{number}/bodies/{position}/artifact"))
        namespace = SourceBodyNamespace(locator, "scar.program-graph/" + str(document["graph"]["schema_version"]),
                                        definition, source, metadata.entry, graph.root)
        if encode(definition) not in (entry.get("semantic_definition_ids") or ()):
            raise ValueError("canonical graph differs from original lexical definition")
        validate_static_body_namespace(graph, document, namespace)
        if metadata.source.path != unit["path"] or metadata.source.fingerprint != "sha256:" + unit["decoded_sha256"]:
            raise ValueError("canonical graph uses another source snapshot")
        index = ProgramIndex(graph)
        body = SimpleNamespace(graph=graph, index=index, document=document, namespace=namespace, metadata=metadata,
            unit=unit, row=row, unit_number=number, body_position=position, catalog=catalog, module=module,
            class_entry=class_entry, interface=interface, dependencies=NamespaceDependencies(graph, document, index=index))
        return self._put(key, body, 2 * descriptor["decoded_bytes"])

    def load_body(self, namespace):
        if type(namespace) is not SourceBodyNamespace:
            raise TypeError("body lookup requires an original SourceBodyNamespace")
        namespace.__post_init__()
        location = self._body_paths.get(namespace.graph.artifact.uri)
        if location is None:
            raise ValueError("qualified body is absent from the current model")
        number, position = location
        self._declaration(namespace, number, position)
        self.read_artifact(namespace.graph)
        body = self._base_body(number, position)
        self._environment_facts.body(body.graph, body.document, namespace, index=body.index)
        while self._cache and self._cache_bytes + self._environment_facts.bytes > self.budget.max_cached_bytes:
            _, (_, size) = self._cache.popitem(last=False)
            self._cache_bytes -= size
        if (namespace.definition != body.namespace.definition or namespace.source != body.namespace.source
                or namespace.region != body.graph.root):
            raise ValueError("body namespace relabels original source ownership")
        # Old validators compare the full source namespace. The wrapper retains
        # each original declaration while sharing the one core/index/document.
        return body if namespace == body.namespace else SimpleNamespace(**{**vars(body), "namespace": namespace})

    def load(self, namespace):
        if type(namespace) is SourceBodyNamespace:
            return self.load_body(namespace)
        if type(namespace) is not GraphNamespace:
            raise TypeError("graph lookup needs a qualified original graph namespace")
        if namespace.source_body is not None:
            body = self.load_body(namespace.source_body)
        elif namespace.graph.pointer == "#/provider/graph":
            original = self._provider_record(replace(namespace.graph, pointer="#/provider"))
            body = SimpleNamespace(**vars(original), namespace=namespace)
        else:
            location = self._body_paths.get(namespace.graph.artifact.uri)
            if location is None:
                raise ValueError("graph namespace is outside original canonical artifacts")
            body = self._base_body(*location)
            # Validate the supplied graph declaration independently of cache
            # identity; it must not borrow a previous namespace's authority.
            source = replace(body.namespace, graph=namespace.graph)
            body = self.load_body(source)
        if body.graph.root != namespace.root:
            raise ValueError("graph namespace changed its original root")
        expected = ("scar.static-class-provider/1:ProgramGraph" if namespace.graph.pointer == "#/provider/graph"
                    else "scar.program-graph/" + str(body.document["graph"]["schema_version"]))
        if namespace.representation != expected:
            raise ValueError("graph namespace changed its actual representation")
        return body

    def index(self, namespace):
        return self.load(namespace).index

    def point(self, *, file=None, entry=None, kind=None, node, context=()):
        """Resolve one exact original endpoint; never guess a whole-body root."""
        from scar.ir.program.dependencies import DependencyPoint, NODE_TYPES
        locations = self.body_locations(file=file, entry=entry, kind=kind)
        if len(locations) != 1:
            raise ValueError("dependency query must select exactly one original body")
        body = self._base_body(*locations[0])
        if type(node) is str:
            prefix, separator, value = node.partition(":")
            constructors = [cls for cls in NODE_TYPES if cls.prefix == prefix]
            if not separator or not value or len(constructors) != 1:
                raise ValueError("node must be an original complete typed ID wire")
            node = constructors[0](value)
        if type(node) not in NODE_TYPES:
            raise TypeError("query node must have its original canonical ID type")
        index = body.index
        registries = (index.operations, index.values, index.regions, index.locations,
                      index._uses, index._block_records)
        extras = (*body.graph.resources, *body.graph.resource_requirements, *body.graph.environments,
                  *body.graph.control_ports, *body.graph.provider_envelopes, *body.graph.native_boundaries)
        if not any(node in registry for registry in registries) and not any(node == record.id for record in extras):
            raise ValueError("query node is absent from its original graph fragment")
        return DependencyPoint(GraphNamespace.from_source(body.namespace), node, context)

    def load_graph(self, namespace):
        return self.load(namespace).graph

    def namespace_for(self, body):
        return body.dependencies

    def body_locations(self, *, file=None, entry=None, kind=None):
        """Select declaration rows before reading any canonical fragment."""
        from scar.analysis.static_query import _file_matches
        candidates = []
        for number, unit in enumerate(self.units):
            if not _file_matches(unit["path"], file):
                continue
            for position, row in enumerate(unit.get("bodies", ())):
                if entry is not None and entry != row["entry_key"] and entry not in row.get("name", ""):
                    continue
                if kind is not None and row["kind"].casefold() != kind.casefold():
                    continue
                if "artifact" in row:
                    candidates.append((number, position))
        if entry is not None:
            exact = [(number, position) for number, position in candidates if entry in (
                self.units[number]["bodies"][position]["entry_key"], self.units[number]["bodies"][position].get("name"))]
            if exact:
                candidates = exact
        return tuple(candidates)

    def select_bodies(self, *, file=None, entry=None, kind=None):
        for number, position in self.body_locations(file=file, entry=entry, kind=kind):
            yield self._base_body(number, position).namespace

    def source_text(self, owner):
        unit = owner.unit if hasattr(owner, "unit") else owner
        source = self.read(unit["artifacts"]["source"])
        text = source.get("text")
        if (source.get("path") != unit["path"] or source.get("namespace_root") != unit["namespace_root"]
                or source.get("raw_sha256") != unit["raw_sha256"] or source.get("decoded_sha256") != unit["decoded_sha256"]
                or type(text) is not str or hashlib.sha256(text.encode()).hexdigest() != unit["decoded_sha256"]):
            raise ValueError("source text differs from original snapshot")
        return text

    def source_context(self, body):
        from scar.ir.v2.codec import semantic_from_dict
        key = "source-context", body.unit["key"]
        found = self._get(key)
        if found is None:
            text = self.source_text(body)
            document = self.read(body.unit["artifacts"]["semantic"])
            found = (ast.parse(text, filename=body.unit["path"], type_comments=True), semantic_from_dict(document), text)
            self._put(key, found, body.unit["artifacts"]["semantic"]["decoded_bytes"] + len(text.encode()))
        return found

    def signature_for(self, definition, body):
        from scar.analysis.function_interfaces import extract_signature
        if (definition.context.namespace_root != body.unit["namespace_root"]
                or definition.snapshot.path != body.unit["path"]
                or definition.snapshot.fingerprint != "sha256:" + body.unit["decoded_sha256"]):
            raise ValueError("source signature belongs to another original source context")
        self.read_artifact(definition.graph)
        tree, semantic, _ = self.source_context(body)
        return extract_signature(SimpleNamespace(tree=tree, semantic=semantic),
            SimpleNamespace(id=definition.definition, source=definition.source))

    def module_bodies(self, name):
        for number, unit in enumerate(self.units):
            names = set(unit.get("module_names", ())) | {m["name"] for m in unit.get("module_mappings", ())}
            if name in names:
                for position, row in enumerate(unit.get("bodies", ())):
                    if row["kind"] == "MODULE" and "artifact" in row:
                        yield self._base_body(number, position)

    def load_provider(self, locator):
        return self._provider_record(locator).provider

    def _provider_record(self, locator):
        from scar.ir.program.class_builder import ClassBuilderProvider
        from scar.ir.program.queries import ProgramIndex
        if locator.pointer != "#/provider" or locator.artifact.schema != "scar.static-class-provider/1":
            raise ValueError("class provider locator must retain its original #/provider record")
        document = self.read_artifact(locator)
        if document.get("schema") != "scar.static-class-provider" or document.get("schema_version") != 1:
            raise ValueError("unsupported original class provider")
        key = "provider-record", locator.artifact.uri, locator.decoded_sha256
        record = self._get(key)
        if record is None:
            if key not in self._seen_graphs and len(self._seen_graphs) >= self.budget.max_graphs:
                raise OverflowError("dependency graph-read budget exhausted")
            self._seen_graphs.add(key)
            provider = decode(ClassBuilderProvider, document["provider"])
            record = self._put(key, SimpleNamespace(provider=provider, graph=provider.graph,
                index=ProgramIndex(provider.graph)), 3 * locator.decoded_bytes)
        return record

    def load_call_shard(self, locator):
        from scar.analysis.static_query import _call_relations
        from scar.ir.program.static_calls import loads
        item = self._call_items.get(locator.artifact.uri)
        if item is None or locator.pointer != "#/relations":
            raise ValueError("call relation locator has no original registered shard")
        self._admit_shard(locator.artifact.uri)
        document = self.read_artifact(locator)
        key = "call-shard", locator.artifact.uri, locator.decoded_sha256
        cached = self._get(key)
        if cached is not None:
            # Retain typed immutable inputs within this pinned read scope,
            # while checking each supplied namespace/declaration independently.
            self.load_body(cached.caller)
            return cached
        shard = loads(json.dumps(document, allow_nan=False))
        body = self.load_body(shard.caller)
        entries = [entry for entry in body.catalog["entries"] if entry["entry_key"] == body.row["entry_key"]]
        view = {**self.manifest, "static_calls": self._call_verify_publication}
        checked = _call_relations(view, body.unit, entries, self.fragments, 1, body_loader=self.load_body)
        if not checked.get("qualified_dependencies_revalidated"):
            raise ValueError("original call relationship inputs were not freshly revalidated")
        return self._put(key, shard, locator.decoded_bytes)

    def _admit_shard(self, uri):
        self.check()
        if uri not in self._seen_shards and len(self._seen_shards) >= self.budget.max_shards:
            raise OverflowError("dependency relationship-shard budget exhausted")
        self._seen_shards.add(uri)

    def relation_shards(self, namespace=None):
        if self.call_publication is None:
            raise ValueError("CALL_RELATIONS_NOT_PUBLISHED: no saved call relationships were supplied")
        if type(namespace) is SourceBodyNamespace:
            namespace = GraphNamespace.from_source(namespace)
        if namespace is not None and type(namespace) is not GraphNamespace:
            raise TypeError('relationship lookup needs an original graph namespace')
        uris = self._call_items if namespace is None else self._call_by_namespace.get(namespace, ())
        for uri in uris:
            locator = self._locator(uri, "scar.static-call-shard/" + str(self.call_publication["schema_version"]), "#/relations")
            yield self.load_call_shard(locator), locator

    iter_call_shards = relation_shards

    def outbound_call_locators(self, point):
        """Route over every saved raw interface; fresh-check selected shards.

        Raw routing consumes its own bounded shard/reference counts plus the
        ordinary input/time budgets.  It does not consume a typed graph/shard
        admission or retain 6697 decoded documents in the graph cache.
        """
        from scar.analysis.program_relation_routing import RawCallRelationRouting
        if self.call_publication is None:
            raise ValueError("CALL_RELATIONS_NOT_PUBLISHED: no saved call relationships were supplied")
        if self._call_routing is None:
            self._call_routing = RawCallRelationRouting(items=self._call_items,
                source_model=self.call_publication["source_model"], version=self.call_publication["schema_version"],
                read=lambda uri: self._read_registered(self._logical[uri], cache_document=False), check=self.check,
                max_shards=self.budget.max_routing_shards, max_references=self.budget.max_routing_references)
        result = self._call_routing.lookup(point.namespace)
        locators = tuple(self._locator(uri, "scar.static-call-shard/" + str(self.call_publication["schema_version"]),
            "#/relations") for uri in result.uris)
        return locators, result.complete, result.issue

    def call_shards_for(self, point):
        selected = {point.namespace}
        for frame in point.context or ():
            selected.update((frame.caller, frame.target))
        seen = set()
        for namespace in selected:
            for shard, locator in self.relation_shards(namespace):
                if locator.artifact.uri not in seen:
                    seen.add(locator.artifact.uri)
                    yield shard, locator

    def class_bindings_for(self, point):
        from scar.analysis.static_class_builder import validate_class_builder_expansion
        from scar.ir.program.class_builder import ClassBuilderExpansion, StaticClassBuilderBinding
        from scar.ir.program.source_language import decode_language_overlay
        from dataclasses import fields
        if self.class_publication is None:
            raise ValueError("CLASS_RELATIONS_NOT_PUBLISHED: no saved class relationships were supplied")
        if point.namespace.source_body is not None and not (
                self._class_interface_point(point, True) or self._class_interface_point(point, False)):
            return
        selected = {point.namespace}
        for frame in point.context or ():
            selected.update((frame.caller, frame.target))
        selected_uris = dict.fromkeys(uri for namespace in selected
            for uri in self._class_by_namespace.get(namespace, ()))
        for uri in sorted(selected_uris, key=self._class_shard_order.__getitem__):
            item = self._class_items[uri]
            parent = decode(SourceBodyNamespace, item["parent"])
            self._admit_shard(uri)
            locator = self._locator(uri, "scar.static-class-bindings/1")
            document = self.read_artifact(locator)
            if (document.get("schema") != "scar.static-class-bindings" or document.get("schema_version") != 1
                    or document.get("source_model") != self.class_publication["source_model"]
                    or document.get("parent") != item["parent"]):
                raise ValueError("class relationship shard differs from original schema/basis/parent")
            for number, raw in enumerate(document["bindings"]):
                binding_key = "class-binding", uri, locator.decoded_sha256, number
                binding = self._get(binding_key)
                checked_in_scope = binding is not None
                if binding is None:
                    binding = decode(StaticClassBuilderBinding, raw)
                if binding.parent != parent:
                    raise ValueError("class binding belongs to another original parent")
                parent_body, suite = self.load_body(binding.parent), self.load_body(binding.suite)
                if parent_body.module is not None:
                    constructions = getattr(parent_body.module, "class_constructions", ())
                else:
                    language = parent_body.document.get("language")
                    constructions = decode_language_overlay(language).class_constructions if language is not None else ()
                if binding.construction not in constructions:
                    raise ValueError("class binding is not an original parent construction")
                provider = self.load_provider(binding.provider)
                if not checked_in_scope:
                    values = {field.name: getattr(binding, field.name) for field in fields(binding) if field.name != "provider"}
                    expansion = ClassBuilderExpansion(**values, provider=provider)
                    validate_class_builder_expansion(expansion, parent_graph=parent_body.graph,
                        suite_graph=suite.graph, suite_overlay=suite.class_entry)
                    self._put(binding_key, binding, locator.decoded_bytes)
                yield binding, replace(locator, pointer="#/bindings/" + str(number))

    def graph(self):
        """Return the shared local/call/class dependency interface, without I/O."""
        from scar.analysis.program_dependencies import ProgramDependencyGraph
        from scar.analysis.program_call_dependencies import StaticCallDependencyProvider
        from scar.analysis.program_class_dependencies import ClassDependencyProvider
        graph = getattr(self, "_view", None)
        if graph is None:
            calls = StaticCallDependencyProvider(self)
            classes = (ClassDependencyProvider(self.class_bindings_for, self.index, self.load_provider,
                    coverage=self._class_relation_coverage)
                if self.class_publication is not None else _UnavailableRelations("CLASS_RELATIONS_NOT_PUBLISHED",
                    "No saved class relationships were supplied for this original class interface.",
                    self._class_interface_point, relation_kinds=ClassDependencyProvider.relation_kinds))
            graph = self._view = ProgramDependencyGraph(self.index, providers=(calls, classes))
        return graph

    def _class_relation_coverage(self, point, *, incoming, bindings):
        """Missing published class mappings are not empty dependency proofs.

        Compare only original interface occurrences in this body. A partial
        publication elsewhere does not poison unrelated literals or a fully
        mapped parent. The bindings have already passed this session's fresh
        original-input checks; this callback does not rescan relationship IO.
        """
        from scar.analysis.static_class_links import _constructions
        from scar.ir.program.dependencies import DependencyFrontier, DependencyNeighborhood
        if not self._class_interface_point(point, incoming):
            return DependencyNeighborhood()
        body = self.load(point.namespace)
        if not hasattr(body, "document"):
            return DependencyNeighborhood()
        known = {binding.construction for binding in bindings
                 if GraphNamespace.from_source(binding.parent) == point.namespace}
        missing = []
        for construction in _constructions(body):
            call = construction.builder_call
            if incoming:
                ports = (call.result, call.normal_world, call.exception, call.traceback, call.raised_world)
            else:
                ports = (call.operation, call.callee, call.world, *(arg.use for arg in call.arguments), call.keyword_names)
            if point.node in ports and construction not in known:
                missing.append(DependencyFrontier(point, "CLASS_RELATION_INTERFACE_OPEN",
                    "This original builder interface has no published parent/provider/suite mapping."))
        return DependencyNeighborhood(frontiers=tuple(dict.fromkeys(missing)), enumerated=not missing)

    def _class_interface_point(self, point, incoming):
        """Limit a missing-publication frontier to actual interface endpoints."""
        from scar.analysis.static_class_links import _constructions
        from scar.ir.program.ids import UseID, ValueID
        from scar.ir.program.model import TerminatorKind
        body = self.load(point.namespace)
        if not hasattr(body, "document"):
            return False
        key = "class-interface-scope", body.unit_number, body.body_position
        scope = self._get(key)
        if scope is None:
            inputs, outputs = set(), set()
            for construction in _constructions(body):
                call = construction.builder_call
                inputs.update((call.operation, call.callee, call.world, *(arg.use for arg in call.arguments)))
                if call.keyword_names is not None:
                    inputs.add(call.keyword_names)
                outputs.update((call.result, call.normal_world, call.exception, call.traceback, call.raised_world))
            if body.class_entry is not None:
                root = body.index.regions[body.graph.root]
                block = next(block for block in root.blocks if block.id == root.entry)
                outputs.update((root.id, *block.arguments))
                for block in root.blocks:
                    for identity in block.operations:
                        operation = body.index.operations[identity]
                        if operation.terminator is not None and operation.terminator.kind in (TerminatorKind.RETURN, TerminatorKind.RAISE):
                            inputs.update(operation.terminator.values)
            scope = self._put(key, (frozenset(outputs), frozenset(inputs)),
                              64 * (len(inputs) + len(outputs)))
        return point.node in scope[0 if incoming else 1]

    def measurements(self):
        routing = self._call_routing
        return {"input_bytes": self.input_bytes, "cache_accounted_bytes": self._cache_bytes + self._environment_facts.bytes,
                "graphs_read": len(self._seen_graphs), "relationship_shards_read": len(self._seen_shards),
                "routing_shards_read": routing.shards if routing is not None else 0,
                "routing_references": routing.references if routing is not None else 0,
                "routing_complete": routing.complete if routing is not None else False,
                "seconds": time.monotonic() - self.started, "target_executed": False}

    def close(self):
        if self.closed:
            return
        try:
            for path, stamp in self._stamps.items():
                if not path.is_file() or path.is_symlink() or _stamp(path) != stamp:
                    raise ValueError("original dependency input changed during query")
        finally:
            self._cache.clear()
            self._cache_bytes = 0
            self._environment_facts.bodies.clear()
            self._environment_facts.bytes = 0
            self._call_routing = None
            self.closed = True

    def __enter__(self):
        self.check()
        return self

    def __exit__(self, *unused):
        self.close()


class _UnavailableRelations:
    def __init__(self, kind, detail, applicable, *, relation_kinds=None):
        self.kind, self.detail, self.applicable = kind, detail, applicable
        self.relation_kinds = relation_kinds

    def _neighborhood(self, point, incoming):
        from scar.ir.program.dependencies import DependencyFrontier, DependencyNeighborhood
        if not self.applicable(point, incoming):
            return DependencyNeighborhood()
        return DependencyNeighborhood(frontiers=(DependencyFrontier(point, self.kind, self.detail),), enumerated=False)

    def incoming(self, point):
        return self._neighborhood(point, True)

    def outgoing(self, point):
        return self._neighborhood(point, False)


def query_program_dependencies(directory, *, file=None, entry=None, kind=None, node=None, roots=None,
                               context=(), direction="incoming", kinds=None, max_points=4096,
                               max_edges=16384, max_depth=128, include_structure=False, budget=None,
                               call_publication=None, call_index_directory=None,
                               class_publication=None, class_index_directory=None):
    """Read a typed dependency walk; callers may export its normalized tables.

    Select an exact original typed ``node`` (or its complete wire ID) inside a
    unique file/entry/kind body, or provide already-qualified ``roots``. There
    is intentionally no implicit Region root standing in for a whole-program
    slice. A context of None remains unknown, distinct from an empty stack.
    """
    from scar.ir.program.dependencies import DependencyPoint, NODE_TYPES
    with ProgramDependencySession(directory, budget=budget, call_publication=call_publication,
            call_index_directory=call_index_directory, class_publication=class_publication,
            class_index_directory=class_index_directory) as session:
        if roots is None:
            if node is None:
                raise ValueError("select an original typed node; a Region root is not an implicit program slice")
            roots = (session.point(file=file, entry=entry, kind=kind, node=node, context=context),)
        return session.graph().walk(roots, direction=direction, kinds=kinds, max_points=max_points,
            max_edges=max_edges, max_depth=max_depth, include_structure=include_structure)
