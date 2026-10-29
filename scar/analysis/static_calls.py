"""Source-only cross-body call linker over retained canonical fragments.

The output contains qualified relationships, never copied graphs or invented
invocations. Candidate cardinality is not target-set closure. Static namespace,
function-state, import and effect assumptions remain explicit frontiers.
"""
from __future__ import annotations

import ast
from collections import Counter, OrderedDict, defaultdict
from dataclasses import dataclass, fields, is_dataclass
import gzip
import hashlib
import io
import json
from pathlib import Path
import time
from types import SimpleNamespace

from scar.ir.record_codec import decode, encode, loads as strict_loads
from scar.ir.program.codec import loads as load_core
from scar.ir.program.functions import (ArgumentKind, BindingOrigin, BodyEntryInterface,
    CallArgument, CallBindingStatus)
from scar.ir.program.ids import OperationID
from scar.ir.program.inventory import SourceContextDigest
from scar.ir.program.model import (BlockArgument, CompletionResult, ExitKind,
    LocalBindingValue, OperationResult, ReferenceValue, StateVersionValue,
    TerminatorKind, UseRole, ValueKind, value_type)
from scar.ir.program.native import ExitPortRef
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.source import LoweringMetadata
from scar.ir.program.source_call_bindings import SourceArgumentPort, SourceBodyNamespace
from scar.ir.program.source_references import SourceArtifactLocator, SourceDefinitionReference
from scar.ir.program.source_returns import SourceReturnSite
from scar.ir.program.static_calls import (StaticCallFrontier, StaticCallShard, StaticCallSite,
    StaticCallTarget, StaticCompletionRoute, StaticStateEntryRoute, StaticTerminalPort, StaticFunctionCreationRoute,
    dumps as dump_relations)
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.semantics_v2 import Opcode, SourceSemanticsGraph
from scar.ir.v2.codec import semantic_from_dict
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import OperationDefinitionID
from scar.ir.v2.semantic import OperationKind, SemanticRelation


@dataclass(frozen=True, slots=True)
class StaticCallBudget:
    max_input_bytes: int = 8_000_000_000
    max_record_bytes: int = 256_000_000
    max_manifest_bytes: int = 256_000_000
    max_bodies: int = 10000
    max_calls: int = 1_000_000
    max_candidates_per_call: int = 64
    max_resolution_steps: int = 4096
    max_cached_bytes: int = 512_000_000
    max_output_bytes: int = 1_000_000_000
    max_seconds: int = 1800
    max_interprocedural_steps: int = 100000
    max_contexts: int = 65536
    max_context_depth: int = 64
    max_namespace_facts: int = 262144

    def __post_init__(self):
        for field in fields(self):
            value = getattr(self, field.name)
            if type(value) is not int or value < 1:
                raise ValueError("static call budget needs positive integer " + field.name)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode() + b"\n"


def _stamp(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def _span(node):
    return type(node).__name__, node.lineno, node.end_lineno, node.col_offset, node.end_col_offset


def _front(kind, detail, source=None):
    return StaticCallFrontier(kind, detail, source)


def input_basis_unit(unit):
    """Pure projection of every per-unit input consumed by this linker.

    Writer and query must use this same projection. Namespace/module lookup is
    an input, not an inference from filename or a runtime import assertion.
    Descriptor and row order are retained for original JSON-pointer locators.
    Extending the resolver's input fields requires extending this projection.
    """
    result = {name: unit[name] for name in (
        "key", "path", "namespace_root", "decoded_sha256", "raw_sha256", "encoding",
        "source_bytes", "module_names", "module_mappings", "root_is_package", "namespace_policy")
        if name in unit}
    result["artifacts"] = {name: dict(unit["artifacts"][name]) for name in
                           ("source", "lexical", "semantic", "semantics", "control")
                           if name in unit["artifacts"]}
    result["bodies"] = [{name: row[name] for name in (
        "entry_key", "kind", "definitions", "source", "status", "artifact", "cache_key") if name in row}
        for row in unit["bodies"]]
    return result


class StaticCallSession:
    """One bounded reader/index lifetime with immutable input/basis receipts.

    ``out`` is fresh relationship storage, not another program root. A caller
    doing atomic publication supplies its final ``logical_root`` explicitly.
    ``iter_calls`` visits each admitted canonical caller body once. Cache entries
    are private typed reads; they are never serialized successful validations.
    """
    def __init__(self, directory, *, out, logical_root=None, expected_manifest_sha256=None, budget=None):
        self.budget = budget or StaticCallBudget()
        if type(self.budget) is not StaticCallBudget:
            raise TypeError("budget must be StaticCallBudget")
        self.started = time.monotonic()
        self.root = Path(directory).absolute()
        self.logical_root = Path(logical_root).absolute() if logical_root is not None else self.root
        if self.root.resolve() != self.root or self.root.is_symlink():
            raise ValueError("static root must not traverse symlinks")
        self.out = Path(out).absolute()
        if (self.out.resolve() != self.out or self.out.is_symlink()
                or self.out.exists() and (not self.out.is_dir() or any(self.out.iterdir()))):
            raise FileExistsError("static call output must be a fresh or empty canonical directory")
        try:
            self.logical_out = self.logical_root / self.out.relative_to(self.root)
        except ValueError:
            self.logical_out = self.out
        self.input_bytes = self.output_bytes = 0
        self._stamps, self._cache = {}, OrderedDict()
        self._cache_bytes = 0
        self._closed = False
        self._iterated = False
        self._finalizing = False
        self._interprocedural = None
        self._call_records = {}
        self._worklist_iterations = 0
        self._worklist_stable = False
        self._enumeration_complete = False
        self.counts = Counter()
        self.relation_frontier_counts = Counter()
        self.frontiers = []
        self.artifacts = []
        self.body_summaries = []
        self._caller_keys = {}
        self._catalog_counted_units = set()
        raw = self._read_file(self.root / "manifest.json", self.budget.max_manifest_bytes)
        self.manifest_sha256 = hashlib.sha256(raw).hexdigest()
        if expected_manifest_sha256 is not None and self.manifest_sha256 != expected_manifest_sha256:
            raise ValueError("input manifest SHA differs")
        self.manifest = strict_loads(raw.decode())
        if (self.manifest.get("schema") != "scar.static-program"
                or self.manifest.get("schema_version") != 1 or type(self.manifest.get("units")) is not list):
            raise ValueError("unsupported source-only model manifest")
        self.units = self.manifest["units"]
        self._body_locations = {str(self.logical_root / row["artifact"]["path"]): (number, position)
            for number, unit in enumerate(self.units) for position, row in enumerate(unit.get("bodies", ()))
            if "artifact" in row}
        self._module_units = defaultdict(list)
        for number, unit in enumerate(self.units):
            for name in unit.get("module_names", ()):
                self._module_units[name].append(number)
        self.counts["source_units"] = len(self.units)
        self.counts["source_lexical_entries"] = sum(len(unit.get("bodies", ())) for unit in self.units)
        declared_calls = [unit.get("lexical_summary", {}).get("calls") for unit in self.units]
        self.source_call_sites_declared = sum(declared_calls) if all(type(value) is int for value in declared_calls) else None
        self.counts["declared_body_artifacts"] = sum("artifact" in body for unit in self.units for body in unit.get("bodies", ()))
        self.out.mkdir(parents=True, exist_ok=True)
        basis_units = [input_basis_unit(unit) for unit in self.units]
        basis = {"schema": "scar.static-call-source-basis", "schema_version": 1,
                 "logical_root": str(self.logical_root), "input_manifest_sha256": self.manifest_sha256,
                 "units": basis_units}
        descriptor = self._write("basis.json.gz", _canonical(basis))
        descriptor["kind"] = "BASIS"
        self.basis = self._artifact(self.logical_out / descriptor["path"], descriptor,
                                    "scar.static-call-source-basis/1")

    def _check(self):
        if self._closed:
            raise ValueError("static call session is closed")
        if not self._finalizing and time.monotonic() - self.started > self.budget.max_seconds:
            raise TimeoutError("static call wall budget exhausted")

    def _read_file(self, path, maximum):
        self._check()
        if self._finalizing:
            raise ValueError("finalizing static relations cannot read new program inputs")
        if path.is_symlink() or path.resolve() != path or not path.is_file():
            raise ValueError("input is absent, symlinked or outside its exact physical path: " + str(path))
        before = _stamp(path)
        if before[2] > maximum or self.input_bytes + before[2] > self.budget.max_input_bytes:
            raise OverflowError("static call input/record byte budget exhausted")
        with path.open("rb") as stream:
            raw = stream.read(before[2] + 1)
        self.input_bytes += len(raw)
        if len(raw) != before[2] or _stamp(path) != before:
            raise ValueError("input changed during read: " + str(path))
        old = self._stamps.setdefault(path, before)
        if old != before:
            raise ValueError("previous input changed: " + str(path))
        return raw

    def _read(self, descriptor):
        relative = Path(descriptor["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("source fragment escapes model")
        stored = self._read_file(self.root / relative, self.budget.max_record_bytes)
        if len(stored) != descriptor["bytes"] or hashlib.sha256(stored).hexdigest() != descriptor["sha256"]:
            raise ValueError("original stored receipt differs")
        maximum = descriptor["decoded_bytes"]
        if type(maximum) is not int or maximum < 1 or maximum > self.budget.max_record_bytes:
            raise OverflowError("original decoded record exceeds byte ceiling")
        if self.input_bytes + maximum > self.budget.max_input_bytes:
            raise OverflowError("static call decoded input budget exhausted")
        with gzip.GzipFile(fileobj=io.BytesIO(stored)) as stream:
            raw = stream.read(maximum + 1)
        self.input_bytes += len(raw)
        if len(raw) != maximum or hashlib.sha256(raw).hexdigest() != descriptor["decoded_sha256"]:
            raise ValueError("original decoded receipt differs")
        return strict_loads(raw.decode())

    def _write(self, relative, raw):
        self._check()
        if len(raw) > self.budget.max_record_bytes:
            raise OverflowError("static relation decoded shard exceeds ceiling")
        stored = gzip.compress(raw, compresslevel=3, mtime=0)
        if self.output_bytes + len(stored) > self.budget.max_output_bytes:
            raise OverflowError("static call output budget exhausted")
        path = self.out / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(stored)
        self.output_bytes += len(stored)
        descriptor = {"path": relative, "bytes": len(stored), "sha256": hashlib.sha256(stored).hexdigest(),
                      "decoded_bytes": len(raw), "decoded_sha256": hashlib.sha256(raw).hexdigest()}
        self.artifacts.append(descriptor)
        return descriptor

    @staticmethod
    def _artifact(path, descriptor, schema):
        return ProviderArtifact(str(path), descriptor["sha256"], descriptor["bytes"], schema)

    def _locator(self, descriptor, schema, pointer, declaration):
        return SourceArtifactLocator(self._artifact(self.logical_root / descriptor["path"], descriptor, schema),
                                     descriptor["decoded_sha256"], descriptor["decoded_bytes"],
                                     "gzip-canonical-json", pointer,
                                     ProviderFactReference(self.basis, declaration))

    def _remember(self, key, value, size):
        self._cache[key] = (value, size)
        self._cache_bytes += size
        while self._cache and self._cache_bytes > self.budget.max_cached_bytes:
            _, (_, old_size) = self._cache.popitem(last=False)
            self._cache_bytes -= old_size
        return value

    def _load_body_namespace(self, namespace):
        """Load a relationship endpoint through its original bounded receipt."""
        location = self._body_locations.get(namespace.graph.artifact.uri)
        if location is None:
            raise ValueError("qualified body is outside the retained source model")
        number, position = location
        context = self._unit(number)
        body = self._body(context, position, self.units[number]["bodies"][position])
        if body is None or body.namespace != namespace:
            raise ValueError("qualified body changed its original source/artifact namespace")
        return body

    def _namespace_for(self, body):
        from scar.analysis.static_namespace import NamespaceDependencies
        dependency = getattr(body, "namespace_dependencies", None)
        if dependency is None:
            dependency = NamespaceDependencies(body.graph, body.document, index=body.index,
                max_steps=self.budget.max_resolution_steps, check=self._check)
            body.namespace_dependencies = dependency
        return dependency

    def _dependencies(self):
        if self._interprocedural is None:
            from scar.analysis.static_interprocedural import InterproceduralDependencies
            self._interprocedural = InterproceduralDependencies(load_body=self._load_body_namespace,
                namespace_for=self._namespace_for, max_contexts=self.budget.max_contexts,
                max_depth=self.budget.max_context_depth, max_facts=self.budget.max_namespace_facts,
                check=self._check)
        return self._interprocedural

    def _unit(self, number):
        key = ("unit", number)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key][0]
        unit = self.units[number]
        required = ("source", "lexical", "semantic", "semantics", "control")
        if any(name not in unit["artifacts"] for name in required):
            raise ValueError("source unit lacks retained source/context fragments")
        docs = {name: self._read(unit["artifacts"][name]) for name in required}
        source = docs["source"]
        fp = "sha256:" + unit["decoded_sha256"]
        if (source["path"] != unit["path"] or source["namespace_root"] != unit["namespace_root"]
                or hashlib.sha256(source["text"].encode()).hexdigest() != unit["decoded_sha256"]):
            raise ValueError("source text/namespace differs from original unit")
        semantic = semantic_from_dict(docs["semantic"])
        semantics = SourceSemanticsGraph.from_dict(docs["semantics"], semantic=semantic)
        if unit["path"] not in semantics.sources or semantics.sources[unit["path"]].fingerprint != fp:
            raise ValueError("source-semantics snapshot differs")
        catalog = docs["lexical"]
        if catalog["path"] != unit["path"] or catalog["fingerprint"] != fp or catalog["namespace_root"] != unit["namespace_root"]:
            raise ValueError("lexical catalog namespace differs")
        if number not in self._catalog_counted_units:
            self._catalog_counted_units.add(number)
            self.counts["source_call_sites_cataloged"] += len(catalog["calls"])
            self.counts["source_call_units_cataloged"] += 1
        tree = ast.parse(source["text"], filename=unit["path"], type_comments=True)
        refs = {(a.kind, a.reference.start_line, a.reference.end_line, a.reference.start_column, a.reference.end_column): a.reference
                for a in semantic.source_atoms.values()}
        call_nodes = {refs[_span(node)].atom_id: node for node in ast.walk(tree)
                      if isinstance(node, ast.Call) and _span(node) in refs}
        nodes = {refs[_span(node)].atom_id: node for node in ast.walk(tree)
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)) and _span(node) in refs}
        from scar.analysis.source_layers import _digest as context_digest
        context = SourceContextDigest(unit["namespace_root"], *(context_digest(docs[name])
                                    for name in ("semantic", "semantics", "control")))
        base = SourceArtifactLocator(self.basis, self.artifacts[0]["decoded_sha256"], self.artifacts[0]["decoded_bytes"],
                                     "gzip-canonical-json", f"#/units/{number}")
        providers = tuple(self._locator(unit["artifacts"][name], "scar.static-source-fragment/1", "#",
                                       f"#/units/{number}/artifacts/{name}") for name in required)
        semantic_positions = {decode(OperationDefinitionID, row["id"]): index for index, row in enumerate(docs["semantic"]["definitions"])}
        definitions, entry_ids = {}, {}
        body_rows = {body["entry_key"]: (index, body) for index, body in enumerate(unit["bodies"])}
        from scar.analysis.function_interfaces import extract_signature
        module_entries = {entry["entry_key"] for entry in catalog["entries"] if entry["kind"] == "MODULE"}
        exports = defaultdict(list)
        for entry in catalog["entries"]:
            if entry.get("source_ref") is None or entry["kind"] not in {"FUNCTION", "ASYNC_FUNCTION", "LAMBDA"}:
                continue
            reference = decode(SourceReference, entry["source_ref"])
            for encoded in entry.get("semantic_definition_ids") or ():
                definition = decode(OperationDefinitionID, encoded)
                if definition not in semantic.definitions or reference.atom_id not in semantic.definitions[definition].source_atoms:
                    raise ValueError("catalog definition is not in its original semantic source")
                graph_ref = self._locator(unit["artifacts"]["semantic"], "scar.ir.v2.semantic", f"#/definitions/{semantic_positions[definition]}",
                                          f"#/units/{number}/artifacts/semantic")
                qualified = SourceDefinitionReference(base, providers, graph_ref, semantics.sources[unit["path"]],
                                                       context, definition, reference)
                node = nodes.get(reference.atom_id)
                signature = None
                if node is not None:
                    try:
                        signature = extract_signature(SimpleNamespace(semantic=semantic),
                            SimpleNamespace(id=definition, source=reference), node=node, sources=refs)
                    except (ValueError, KeyError, TypeError):
                        # Missing signature does not remove a source definition
                        # or prevent unrelated callers from being cataloged.
                        signature = None
                definitions[definition] = (qualified, signature, entry, body_rows.get(entry["entry_key"]))
                entry_ids[entry["entry_key"]] = definition
                if entry["lexical_parent"] in module_entries:
                    exports[entry["name"]].append(definition)
        calls_to_defs, defs_by_atom, opaque_calls = defaultdict(list), defaultdict(list), defaultdict(list)
        for edge in semantic.edges.values():
            if edge.relation is SemanticRelation.CALLS:
                calls_to_defs[edge.source.id].append(edge.target.id)
        for definition, (qualified, _, _, _) in definitions.items():
            defs_by_atom[qualified.source.atom_id].append(definition)
        for definition in semantic.definitions.values():
            if (definition.kind is OperationKind.OPAQUE and definition.metadata.get("ast_type") == "Call"
                    and len(definition.output_slots) == 1):
                for atom_id in definition.source_atoms:
                    atom = semantic.source_atoms.get(atom_id)
                    if atom is not None and atom.kind == "Call" and definition.code_id == atom_id.wire:
                        opaque_calls[atom_id].append(definition.id)
        result = SimpleNamespace(number=number, unit=unit, semantic=semantic, semantics=semantics,
            catalog=catalog, tree=tree, refs=refs, call_nodes=call_nodes, definitions=definitions,
            entry_ids=entry_ids, exports=exports, body_rows=body_rows, docs=docs,
            calls_to_defs=calls_to_defs, defs_by_atom=defs_by_atom,
            opaque_call_definitions=opaque_calls)
        return self._remember(key, result, sum(unit["artifacts"][name]["decoded_bytes"] for name in required))

    def _body(self, context, row_number, row):
        key = ("body", context.number, row_number)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key][0]
        if "artifact" not in row:
            return None
        document = self._read(row["artifact"])
        if (document.get("schema") != "scar.static-body" or document.get("schema_version") != 1
                or document.get("entry_key") != row["entry_key"] or document.get("cache_key") != row.get("cache_key")
                or document.get("status") != row["status"]):
            raise ValueError("canonical body container differs from its original declaration")
        if document.get("graph") is None:
            return None
        if row["status"] != "LOWERED_WITH_GAPS":
            raise ValueError("graph-bearing static body must declare LOWERED_WITH_GAPS")
        expected_inputs = {name: context.unit["artifacts"].get(name) for name in ("source", "semantic", "semantics", "control")}
        if document.get("inputs") != expected_inputs:
            raise ValueError("body uses a different source/context snapshot")
        graph = load_core(json.dumps(document["graph"], allow_nan=False))
        metadata = decode(LoweringMetadata, document["metadata"])
        index = ProgramIndex(graph)
        class_entry=None
        if document.get("class") is not None:
            from scar.ir.program.class_entries import (
                decode_class_entry_overlay, validate_class_entry_core, ClassSuiteOverlay, ClassSuiteMethodOverlay,
            )
            from scar.ir.program.source_subjects import FrameKind,SourceCompilationFrameRoot
            class_entry=decode_class_entry_overlay(document["class"])
            validate_class_entry_core(class_entry,graph,metadata)
            entries=[entry for entry in context.catalog["entries"] if entry["entry_key"]==row["entry_key"]]
            if (len(entries)!=1 or entries[0]["kind"]!="CLASS"
                    or encode(class_entry.definition) not in (entries[0].get("semantic_definition_ids") or ())
                    or encode(class_entry.source)!=entries[0]["source_ref"]
                    or metadata.source!=context.semantics.sources[context.unit["path"]]
                    or type(class_entry) not in (ClassSuiteOverlay, ClassSuiteMethodOverlay) and class_entry.required_expansion.region!=graph.root
                    or len(graph.frame_roots)!=1
                    or type(graph.frame_roots[0]) is not SourceCompilationFrameRoot
                    or graph.frame_roots[0].kind is not FrameKind.CLASS
                    or graph.frame_roots[0].entry!=class_entry.interface
                    or graph.frame_roots[0].code!=class_entry.compilation):
                raise ValueError("class frame source/compiler namespace differs from original entry")
            locator=self._locator(row["artifact"],"scar.static-body/1","#/graph",
                f"#/units/{context.number}/bodies/{row_number}/artifact")
            namespace=SourceBodyNamespace(locator,"scar.program-graph/"+str(document["graph"]["schema_version"]),
                class_entry.definition,class_entry.source,metadata.entry,graph.root)
            result=SimpleNamespace(index=index,graph=graph,metadata=metadata,interface=None,
                namespace=namespace,document=document,context=context,module=None)
        elif document.get("module") is not None:
            from scar.ir.program.module_entries import decode_frame_body, StaticModuleEntryDeclaration
            from scar.ir.program.source_subjects import ModuleUnitSource, FrameKind, SourceCompilationCodeRef
            overlay = decode_frame_body(document["module"])
            from scar.ir.program.module_entries import CompilerStructuredFrameBodyOverlay
            if type(overlay) is CompilerStructuredFrameBodyOverlay:
                from scar.analysis.source_module_compiler_lowering import validate_compiler_prologue_core
                validate_compiler_prologue_core(overlay, graph)
            roots = [module.initializer for module in context.semantic.modules.values()
                     if module.path == context.unit["path"] and module.fingerprint == metadata.source.fingerprint]
            if len(roots) != 1 or metadata.source != context.semantics.sources[context.unit["path"]]:
                raise ValueError("module body is not its original source initializer")
            expected_unit = ModuleUnitSource(context.semantics.sources[context.unit["path"]],
                                             context.unit["namespace_root"], roots[0])
            if type(overlay.declaration) is not StaticModuleEntryDeclaration:
                raise ValueError("dynamic module declaration is unsupported by the source-only linker")
            if overlay.declaration.unit != expected_unit:
                raise ValueError("module overlay namespace/snapshot/initializer differs")
            frame_roots = graph.frame_roots
            if (len(frame_roots) != 1 or frame_roots[0].kind is not FrameKind.MODULE
                    or type(frame_roots[0].code) is not SourceCompilationCodeRef
                    or frame_roots[0].code != overlay.declaration.compilation
                    or frame_roots[0].scope != overlay.root_scope):
                raise ValueError("module graph lacks its unique matching static compilation root")
            locator = self._locator(row["artifact"], "scar.static-body/1", "#/graph",
                                    f"#/units/{context.number}/bodies/{row_number}/artifact")
            namespace = SourceBodyNamespace(locator, "scar.program-graph/" + str(document["graph"]["schema_version"]),
                                            roots[0], None, metadata.entry, graph.root)
            # The module overlay is the original mapping-frame source index;
            # no fake function interface/metadata is created for it.
            result = SimpleNamespace(index=index, graph=graph, metadata=metadata, interface=None,
                namespace=namespace, document=document, context=context, module=overlay)
        else:
            result = self._function_body(context, row_number, row, document, graph, metadata, index)
        result.class_entry=class_entry
        result.operation_links = tuple(result.module.operation_links) if result.module is not None else metadata.operation_links
        result.use_links = tuple(result.module.use_links) if result.module is not None else metadata.use_links
        self._check_source_references(context, (graph, metadata, result.module,
            document.get("structured"), document.get("language"), document.get("frame"),
            document.get("static_compilation"),class_entry))
        result.links_by_op, result.uses_by_op = defaultdict(list), defaultdict(list)
        declared_calls = {target.operation for target in metadata.call_targets}
        for link in result.operation_links:
            if link.operation not in index.operations:
                raise ValueError("source operation link is not in original graph")
            if type(link.source) is SourceReference and (link.source.path != metadata.source.path or link.source.fingerprint != metadata.source.fingerprint):
                raise ValueError("source operation link belongs to another snapshot")
            if link.opcode is Opcode.CALL or link.operation in declared_calls:
                if type(link.source) is not SourceReference:
                    raise ValueError("canonical CALL needs an original source atom, not a module-unit placeholder")
            result.links_by_op[link.operation].append(link)
        for link in result.use_links:
            if index.use_site(link.use).operation != link.operation:
                raise ValueError("source Use link is not owned by original operation")
            result.uses_by_op[link.operation].append(link)
        result.call_source_bases = {}
        for link in result.operation_links:
            if link.opcode is Opcode.CALL or link.operation in declared_calls:
                result.call_source_bases[link.operation] = self._call_source_basis(result, link)
        self._caller_keys[result.namespace] = row["entry_key"]
        return self._remember(key, result, row["artifact"]["decoded_bytes"])

    def _call_source_basis(self, body, link):
        """Distinguish an original CALL overlay from a canonical refinement.

        An SG operation ID is an original source anchor even when the older
        computational view has no record. It must never be treated as a newly
        invented computational value or as an unrelated source operation.
        """
        context = body.context
        if type(link.source) is not SourceReference:
            raise ValueError("canonical CALL needs an original source atom")
        atom = context.semantic.source_atoms.get(link.source.atom_id)
        node = context.call_nodes.get(link.source.atom_id)
        if (atom is None or atom.kind != "Call" or atom.reference != link.source
                or not isinstance(node, ast.Call) or context.refs.get(_span(node)) != link.source):
            raise ValueError("canonical CALL is not its exact original AST Call/source atom")
        if link.semantic_operation is None:
            return "CANONICAL_CALL_WITHOUT_SOURCE_OPERATION"
        definition = context.semantic.definitions.get(link.semantic_operation)
        if (definition is None or definition.code_id != link.source.atom_id.wire
                or link.source.atom_id not in definition.source_atoms):
            raise ValueError("canonical CALL names an unrelated original SG operation")
        original = context.semantics.operations.get(link.semantic_operation)
        if original is not None:
            if original.opcode is not Opcode.CALL or original.source != link.source:
                raise ValueError("canonical CALL conflicts with the existing computational opcode/source")
            return "EXISTING_CALL_OVERLAY"
        if (definition.kind is not OperationKind.OPAQUE
                or context.opaque_call_definitions.get(link.source.atom_id) != [definition.id]):
            raise ValueError("missing computational CALL requires the exact original opaque Call definition")
        operation = body.index.operations[link.operation]
        if operation.terminator is None or operation.terminator.kind is not TerminatorKind.INVOKE:
            raise ValueError("opaque-source refinement lacks its canonical INVOKE")
        callees = [row for row in body.uses_by_op.get(operation.id, ()) if row.role == "callee"]
        expected = context.refs.get(_span(node.func))
        if len(callees) != 1 or expected is None or callees[0].source != expected or callees[0].index != 0:
            raise ValueError("opaque-source refinement lacks its exact original callee source Use")
        site = body.index.use_site(callees[0].use)
        if (site.operation != operation.id or not operation.invoke_arguments
                or operation.invoke_arguments[0] != site.use.id):
            raise ValueError("opaque-source refinement changed its original callee invoke port")
        value = body.index.values[site.use.value]
        kind = value_type(value).kind
        if not ((kind is ValueKind.REFERENCE and site.use.role is UseRole.REFERENCE)
                or (kind is ValueKind.DATA and site.use.role is UseRole.DATA)):
            raise ValueError("opaque-source refinement has a non-value callee operand")
        return "OPAQUE_SOURCE_REFINEMENT"

    def _check_source_references(self, context, records):
        """Check original atoms in typed and wire overlays without semantic replay.

        Wire overlays may tag SourceReference variants. Only the closed source
        fields are decoded; normal overlay/core readers retain tag validation.
        No saved source link is accepted merely because its file hash matches.
        """
        source_fields = {"atom_id", "path", "fingerprint", "start_line", "end_line", "start_column", "end_column"}
        pending, seen = [records], set()
        def check(reference):
            atom = context.semantic.source_atoms.get(reference.atom_id)
            if atom is None or atom.reference != reference:
                raise ValueError("body SourceReference is absent from or differs from its original source atom")
        while pending:
            value = pending.pop()
            if id(value) in seen:
                continue
            if type(value) is SourceReference:
                check(value)
                seen.add(id(value))
            elif isinstance(value, dict):
                seen.add(id(value))
                if source_fields <= value.keys():
                    # Check this temporary decoded value immediately; retaining
                    # only its id in ``seen`` would allow later id reuse.
                    check(decode(SourceReference, {name: value[name] for name in source_fields}))
                else:
                    pending.extend(value.values())
            elif isinstance(value, (tuple, list)):
                seen.add(id(value))
                pending.extend(value)
            elif is_dataclass(value) and not isinstance(value, type):
                seen.add(id(value))
                pending.extend(getattr(value, field.name) for field in fields(value))

    def _function_body(self, context, row_number, row, document, graph, metadata, index):
        interface = decode(BodyEntryInterface, document["interface"])
        definition = context.entry_ids.get(row["entry_key"])
        if definition is None or interface.definition != definition or interface.region != graph.root:
            raise ValueError("body interface is not this original definition/root")
        reference, signature, entry, _ = context.definitions[definition]
        if metadata.source != reference.snapshot:
            raise ValueError("body metadata source differs")
        from scar.analysis.function_interfaces import validate_body_interface
        if signature is None:
            raise ValueError("canonical function lacks a source-matched signature")
        validate_body_interface(SimpleNamespace(graph=graph, metadata=metadata), interface, signature)
        locator = self._locator(row["artifact"], "scar.static-body/1", "#/graph",
                                f"#/units/{context.number}/bodies/{row_number}/artifact")
        namespace = SourceBodyNamespace(locator, "scar.program-graph/" + str(document["graph"]["schema_version"]),
                                        definition, reference.source, metadata.entry, graph.root)
        return SimpleNamespace(index=index, graph=graph, metadata=metadata, interface=interface,
                               namespace=namespace, document=document, context=context, module=None)

    def _import_candidates(self, context, spec, *, source=None):
        names = [spec.requested]
        if spec.relative_level:
            names = []
            for module in context.unit.get("module_names", ()):
                package = module if Path(context.unit["path"]).name == "__init__.py" else module.rpartition(".")[0]
                parts = package.split(".") if package else []
                if spec.relative_level <= len(parts):
                    prefix = parts[:len(parts) - spec.relative_level + 1]
                    names.append(".".join((*prefix, spec.requested)) if spec.requested else ".".join(prefix))
        found, frontiers = [], []
        if spec.symbol is None or spec.symbol == "*":
            return found, frontiers
        for name in names:
            for number in self._module_units.get(name, ()):
                unit = self.units[number]
                if any(key not in unit["artifacts"] for key in ("source", "lexical", "semantic", "semantics", "control")):
                    kind = "IMPORT_DECLARATION_ONLY" if Path(unit["path"]).suffix == ".pyi" else "IMPORT_SOURCE_CONTEXT_UNAVAILABLE"
                    frontiers.append(_front(kind,
                        "Import candidate retains source/declarations but has no canonical execution context: " + unit["path"], source))
                    continue
                target = self._unit(number)
                for definition in target.exports.get(spec.symbol, ()):
                    found.append((number, definition, "IMPORT_CANDIDATE_NOT_LOADER_PROOF"))
        return found, frontiers

    def _class_function_creation(self, body, operation, value, normal_edge):
        """Join a class-suite factory through its original lexical code path.

        Annotation factories without a user DefinitionID retain their compiler
        provenance, but cannot manufacture a SourceDefinitionReference. The
        returned route is only the creation relation, not closure/default state
        or evidence that any decorator returned this function unchanged.
        """
        from scar.ir.program.class_entries import ClassSuiteOverlay, ClassSuiteMethodOverlay
        from scar.analysis.static_compilation import _scope_nodes
        from scar.trace.code_snapshot import code_key
        from scar.analysis.static_namespace import normal_reference
        overlay=body.class_entry
        if type(overlay) not in (ClassSuiteOverlay, ClassSuiteMethodOverlay):return None
        factories=[record for record in overlay.factories if record.operation==operation.id]
        if len(factories)!=1:raise ValueError('class factory lacks its unique original creation record')
        factory=factories[0]
        if factory.definition is None:return None
        context=body.context
        if factory.definition not in context.definitions:
            return None  # A source declaration without a qualified function interface stays open.
        links=body.links_by_op.get(operation.id,())
        qualified,_,_,_=context.definitions[factory.definition]
        source=factory.source
        normal=normal_reference(body.index,operation.id)
        if (len(links)!=1 or links[0].source!=source or qualified.source!=source
                or factory.reference!=value or normal!=(normal_edge,value)):
            raise ValueError('class factory source/normal result differs from its original qualified body')
        declarations=[d for d in context.semantic.definitions.values()
            if d.id==links[0].semantic_operation and d.metadata.get('phase')=='definition_time'
            and d.code_id==source.atom_id.wire and source.atom_id in d.source_atoms]
        definition=context.semantic.definitions.get(factory.definition)
        if (len(declarations)!=1 or definition is None or definition.metadata.get('phase')!='call_time'
                or definition.code_id!=source.atom_id.wire or source.atom_id not in definition.source_atoms):
            raise ValueError('class factory did not retain its original declaration/call-time definition')
        codes=[row for row in body.uses_by_op.get(operation.id,())if row.role=='function-code']
        if len(codes)!=1:raise ValueError('class factory lacks its actual code Use')
        code_use=body.index.use_site(codes[0].use).use
        origin=body.index.values[code_use.value].origin
        records=[r for r in overlay.constants if isinstance(origin,OperationResult)
                 and r.operation==origin.operation and r.reference==code_use.value]
        if (code_use.value!=factory.code_reference or len(records)!=1
                or records[0].constant_path!=factory.constant_path or len(factory.constant_path)!=1):
            raise ValueError('class factory code does not come from its original constant slot')
        parent=getattr(context,'compiled_module_for_namespace',None)
        if parent is None:
            parent=compile(context.docs['source']['text'],context.unit['path'],'exec',
                           flags=0,dont_inherit=True,optimize=0)
            context.compiled_module_for_namespace=parent
            context.compiled_module_layout_for_namespace=code_key(parent)
        if context.compiled_module_layout_for_namespace!=overlay.compilation.root_code_layout_key:
            raise ValueError('class factory module layout differs from retained source compilation')
        scopes=getattr(context,'compiled_scope_paths_for_namespace',None)
        if scopes is None:
            found={};issues=[]
            _scope_nodes(context.tree,parent,(),ast.Module,found,issues)
            scopes={span:tuple(rows)for span,rows in found.items()}
            context.compiled_scope_paths_for_namespace=scopes
        class_span=(overlay.source.start_line,overlay.source.end_line,overlay.source.start_column,overlay.source.end_column)
        parents=[row for row in scopes.get(class_span,())
                 if row[0]==overlay.compilation.code_path and isinstance(row[2],ast.ClassDef)]
        if len(parents)!=1 or code_key(parents[0][1])!=overlay.compilation.code_layout_key:
            raise ValueError('class factory parent code is not its original ClassDef compiler scope')
        span=(source.start_line,source.end_line,source.start_column,source.end_column)
        full_path=overlay.compilation.code_path+factory.constant_path
        children=[row for row in scopes.get(span,())if row[0]==full_path
                  and isinstance(row[2],(ast.FunctionDef,ast.AsyncFunctionDef))]
        if len(children)!=1:
            raise ValueError('class factory child is not a unique original lexical source function')
        child_path,child,node=children[0]
        parent_code=parents[0][1]
        if (parent_code.co_consts[factory.constant_path[0]] is not child
                or child.co_name!=node.name or child.co_qualname!=parent_code.co_qualname+'.'+node.name
                or child.co_firstlineno!=min([node.lineno]+[d.lineno for d in node.decorator_list])
                or tuple(child.co_freevars)!=factory.free_names):
            raise ValueError('class factory child slot/name/qualname/firstline/closure layout differs')
        return StaticFunctionCreationRoute(operation.id,normal_edge,value,code_use.id,
            origin.operation,overlay.compilation.code_layout_key,factory.constant_path,qualified)

    def _function_creation(self, body, operation, value, normal_edge):
        """Join an explicit factory's code slot to its original shared body.

        This never treats APPLY_DECORATOR or an arbitrary same-source result as
        the original function. Compilation is of retained text, never exec.
        """
        if body.module is None:
            if body.class_entry is not None:
                return self._class_function_creation(body,operation,value,normal_edge)
            from scar.analysis.static_nested_creation import verify_nested_function_creation
            return verify_nested_function_creation(body,operation,value,normal_edge)
        from scar.analysis.source_mapping_function_lowering import mapping_function_plan
        from scar.trace.code_snapshot import code_key
        from scar.ir.program.model import OperationResult
        context = body.context
        links = body.links_by_op.get(operation.id, ())
        if len(links) != 1 or type(links[0].source) is not SourceReference:
            raise ValueError("module factory lacks its unique original declaration source")
        source = links[0].source
        declarations = [d for d in context.semantic.definitions.values()
                        if d.id == links[0].semantic_operation and d.metadata.get("phase") == "definition_time"
                        and d.code_id == source.atom_id.wire and source.atom_id in d.source_atoms]
        definitions = [definition for definition in context.defs_by_atom.get(source.atom_id, ())
                       if context.semantic.definitions[definition].metadata.get("phase") == "call_time"]
        nodes = [n for n in ast.walk(context.tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and (n.lineno,n.end_lineno,n.col_offset,n.end_col_offset) ==
                 (source.start_line,source.end_line,source.start_column,source.end_column)]
        if len(declarations) != 1 or len(definitions) != 1 or len(nodes) != 1:
            raise ValueError("module factory declaration/body source join is not exact")
        codes = [row for row in body.uses_by_op.get(operation.id, ()) if row.role == "function-code"]
        if len(codes) != 1:
            raise ValueError("module factory does not have its original code Use")
        code_use = body.index.use_site(codes[0].use).use
        origin = body.index.values[code_use.value].origin
        if type(origin) is not OperationResult:
            raise ValueError("module factory code is not its original constant operation result")
        records = [row for row in body.module.constants if row.operation == origin.operation]
        if len(records) != 1 or len(records[0].constant_path) != 1 or records[0].source != source:
            raise ValueError("module factory code constant does not retain its exact slot/source")
        parent = getattr(context, "compiled_module_for_namespace", None)
        if parent is None:
            parent = compile(context.docs["source"]["text"], context.unit["path"], "exec",
                             flags=0, dont_inherit=True, optimize=0)
            context.compiled_module_for_namespace = parent
            context.compiled_module_layout_for_namespace = code_key(parent)
        record = records[0]
        if context.compiled_module_layout_for_namespace != record.code_key or record.code_key != body.module.declaration.compilation.code_layout_key:
            raise ValueError("module factory code-slot layout differs from retained source compilation")
        plan = mapping_function_plan(nodes[0], parent)
        if record.constant_path != (plan.child.arg,) or parent.co_consts[plan.child.arg] is not plan.child.argval:
            raise ValueError("module factory code slot does not select this source function's compiled child")
        definition = definitions[0]
        return StaticFunctionCreationRoute(operation.id, normal_edge, value, code_use.id,
            origin.operation, record.code_key, record.constant_path, context.definitions[definition][0])

    def _source_candidates(self, body, operation, source, semantic_call):
        context = body.context
        candidates, frontiers = {}, []
        hints = {}
        namespace_flows, creations = [], []
        qualified_flows, qualified_creations, crossflows = [], [], []
        mapping_caller = body.module is not None or body.class_entry is not None
        def admit(number, definition, basis):
            if len(candidates) >= self.budget.max_candidates_per_call and (number, definition) not in candidates:
                frontiers.append(_front("CANDIDATE_BUDGET", "Candidate set was truncated; it remains open.", source))
                return
            candidate_context = context if number == context.number else self._unit(number)
            if definition in candidate_context.definitions:
                candidates.setdefault((number, definition), set()).add(basis)
        def hint(number, definition, basis):
            # Catalog declarations can guide a search. They do not establish
            # which callable the actual SSA callee reference denotes now.
            candidate_context = context if number == context.number else self._unit(number)
            if definition in candidate_context.definitions:
                hints.setdefault((number, definition), set()).add(basis)
        for target in body.metadata.call_targets:
            if target.operation == operation.id and target.source_definition is not None:
                hint(context.number, target.source_definition, "ORIGINAL_CALL_TARGET_METADATA")
        if semantic_call is not None and not mapping_caller:
            old = context.semantics.operations.get(semantic_call)
            if old is not None and (old.opcode is not Opcode.CALL or old.source != source):
                raise ValueError("candidate resolution requires its exact existing CALL overlay")
            if old is not None:
                for definition in context.calls_to_defs.get(semantic_call, ()):
                    hint(context.number, definition, "SOURCE_GRAPH_DECLARED_CANDIDATE")
            if old is not None and old.callee is not None:
                hint(context.number, old.callee, "SOURCE_SEMANTICS_DECLARED_CANDIDATE")
            pending = [operand.value for operand in old.operands if operand.role == "callee"] if old is not None else []
            seen = set()
            while pending:
                self._check()
                value_id = pending.pop()
                if value_id in seen:
                    continue
                seen.add(value_id)
                if len(seen) > self.budget.max_resolution_steps:
                    frontiers.append(_front("RESOLUTION_BUDGET", "Source reaching/alias traversal stopped with remaining work.", source))
                    break
                value = context.semantics.values.get(value_id)
                producer = context.semantics.operations.get(value.producer) if value is not None else None
                if producer is None:
                    continue
                for definition in context.defs_by_atom.get(producer.source.atom_id, ()):
                    hint(context.number, definition, "FUNCTION_SOURCE_CREATION_CANDIDATE")
                if producer.opcode is Opcode.READ:
                    use = context.semantics.uses[producer.binding_use]
                    pending.extend(context.semantics.bindings[binding].value for binding in (*use.reaching, *use.conditional_reaching))
                    if not use.reaching:
                        frontiers.append(_front("SOURCE_BINDING_OPEN", "Deferred/global/cell binding is not made exact by a same-name definition.", producer.source))
                elif producer.opcode is Opcode.ALIAS:
                    pending.extend(operand.value for operand in producer.operands)
                elif producer.opcode is Opcode.IMPORT and producer.import_spec is not None:
                    imported, import_frontiers = self._import_candidates(context, producer.import_spec, source=producer.source)
                    for number, definition, basis in imported:
                        admit(number, definition, basis)
                    frontiers.extend(import_frontiers)
                    frontiers.append(_front("IMPORT_ENVIRONMENT_OPEN", "Import candidates retain loader/package/export mutation conditions.", producer.source))
        # Follow only canonical binding payload/phi/creation references, never
        # every input of arbitrary computation as an alias to its result.
        from scar.analysis.static_namespace import normal_reference
        from scar.ir.program.static_calls import StaticQualifiedNamespaceFlow, StaticQualifiedFunctionCreation
        callee_uses = {row.use for row in body.uses_by_op.get(operation.id, ()) if row.role == "callee"}
        callee = next((use.value for use in operation.uses if use.id in callee_uses), None)
        pending, seen = [(body, callee)] if callee is not None else [], set()
        while pending:
            self._check()
            current, value_id = pending.pop()
            key = current.namespace, value_id
            if key in seen:
                continue
            seen.add(key)
            if len(seen) > self.budget.max_resolution_steps:
                frontiers.append(_front("CANONICAL_ALIAS_BUDGET", "Canonical binding traversal remains partial.", source))
                break
            namespace = self._namespace_for(current)
            alias = getattr(current, "qualified_alias_index", None)
            if alias is None:
                reads = {row.normal_result: row for row in current.graph.binding_reads if row.normal_result is not None}
                bindings = {row.value: row for row in current.graph.binding_definitions}
                incoming = defaultdict(list)
                for op in current.graph.operations:
                    term = op.terminator
                    if term is not None and term.kind in (TerminatorKind.JUMP, TerminatorKind.BRANCH):
                        for edge in term.successors:
                            incoming[edge.block].append(edge)
                normal_producers = {}
                for producer in current.graph.operations:
                    normal = normal_reference(current.index, producer.id, blocks=namespace.blocks)
                    if normal is not None:
                        normal_producers[normal[1]] = (producer, normal[0])
                alias = current.qualified_alias_index = reads, bindings, incoming, normal_producers
            reads, bindings, incoming, normal_producers = alias
            value = current.index.values[value_id]
            if value_id in reads:
                pending.append((current, current.index.use_site(reads[value_id].binding).use.value))
            elif value_id in bindings and bindings[value_id].payload is not None:
                pending.append((current, current.index.use_site(bindings[value_id].payload).use.value))
            elif isinstance(value.origin, BlockArgument):
                routes = namespace.flows(value.id)
                for flow in routes:
                    namespace.validate(flow)
                    if current.namespace == body.namespace:
                        namespace_flows.append(flow)
                    else:
                        qualified_flows.append(StaticQualifiedNamespaceFlow(current.namespace, flow))
                    pending.append((current, current.index.use_site(flow.assigned_reference).use.value))
                for inherited in self._dependencies().sources(current, value.id):
                    origin_body = self._load_body_namespace(inherited.body_namespace)
                    crossflows.extend(inherited.crossflows)
                    pending.append((origin_body, inherited.value))
                producer = normal_producers.get(value.id)
                if producer is not None:
                    primitive, edge = producer
                    kind = namespace.protocols.get(primitive.id)
                    if kind == "APPLY_DECORATOR_314":
                        frontiers.append(_front("DECORATOR_RETURN_RELATION_OPEN",
                            "The actual decorator result is a distinct value; no code/body alias follows from a shared definition source.",
                            current.links_by_op[primitive.id][0].source))
                    elif kind in ("MAKE_FUNCTION_314", "MAKE_NESTED_FUNCTION"):
                        creation = self._function_creation(current, primitive, value.id, edge)
                        if creation is not None:
                            if current.namespace == body.namespace:
                                creations.append(creation)
                            else:
                                qualified_creations.append(StaticQualifiedFunctionCreation(current.namespace, creation))
                            admit(current.context.number, creation.definition.definition,
                                  "VERIFIED_SOURCE_COMPILATION_FACTORY" if current.namespace == body.namespace
                                  else "QUALIFIED_NAMESPACE_FACTORY_SOURCE")
                        elif current.class_entry is not None:
                            frontiers.append(_front("CLASS_FUNCTION_CREATION_BODY_OPEN",
                                "The original class factory/code-slot result has no qualified user source body; generated or unmapped child provenance is retained without inventing a function definition.",
                                current.links_by_op[primitive.id][0].source))
                for edge in incoming[value.origin.block]:
                    if value.origin.index < len(edge.arguments):
                        argument = edge.arguments[value.origin.index]
                        if not isinstance(argument, CompletionResult):
                            pending.append((current, current.index.use_site(argument).use.value))
            elif isinstance(value.origin, OperationResult) and current.module is None and current.class_entry is None:
                for link in current.links_by_op.get(value.origin.operation, ()):
                    if type(link.source) is SourceReference:
                        for definition in current.context.defs_by_atom.get(link.source.atom_id, ()):
                            hint(current.context.number, definition, "CANONICAL_FUNCTION_CREATION_SOURCE")
        if body.call_source_bases.get(operation.id) == "OPAQUE_SOURCE_REFINEMENT":
            for bases in candidates.values():
                bases.add("VERIFIED_CANONICAL_CALL_REFINES_OPAQUE_SOURCE")
        if namespace_flows:
            frontiers.append(_front("CONDITIONAL_NAMESPACE_FLOW",
                "Original write/read ports and CFG paths are connected under explicit mapping, lookup and intervening-effect conditions; not content equality.", source))
        for key, bases in hints.items():
            if key not in candidates:
                frontiers.append(_front("SOURCE_TARGET_HINT_UNCONNECTED",
                    "Original declaration hint " + key[1].wire + " (" + ", ".join(sorted(bases)) +
                    ") has no joined callee binding/factory provenance; it cannot supply target argument, state or return ports.", source))
        return (candidates, frontiers, tuple(dict.fromkeys(namespace_flows)), tuple(dict.fromkeys(creations)),
                tuple(dict.fromkeys(qualified_flows)), tuple(dict.fromkeys(qualified_creations)), tuple(dict.fromkeys(crossflows)))

    def _actuals(self, body, operation, node):
        if node is None:
            return (), [_front("CALL_AST_UNAVAILABLE", "Original canonical CALL has no exact retained Call AST.")]
        result, frontiers = [], []
        arguments = [(value.value if isinstance(value, ast.Starred) else value,
                      ArgumentKind.STARRED if isinstance(value, ast.Starred) else ArgumentKind.POSITIONAL, None)
                     for value in node.args]
        arguments += [(keyword.value, ArgumentKind.DOUBLE_STARRED if keyword.arg is None else ArgumentKind.KEYWORD, keyword.arg)
                      for keyword in node.keywords]
        links = body.uses_by_op.get(operation.id, ())
        for number, (value, kind, keyword) in enumerate(arguments):
            reference = body.context.refs.get(_span(value))
            if reference is None:
                raise ValueError("actual argument lacks its original source atom")
            matches = [row.use for row in links if row.source == reference and row.role != "callee"
                       and row.use in operation.invoke_arguments and body.index.use_site(row.use).use.role.value != "STATE_CONTENT"]
            use = matches[0] if len(matches) == 1 else None
            if use is None:
                frontiers.append(_front("ACTUAL_USE_UNRECOVERED", "Expanded/ambiguous operand retains source but has no unique direct CALL Use.", reference))
            result.append(CallArgument(number, reference, kind, keyword, use))
        return tuple(result), frontiers

    def _completion_routes(self, caller, operation, callee):
        completions, returns, frontiers = [], [], []
        root = next(region for region in callee.graph.regions if region.id == callee.graph.root)
        blocks = {block.id: block for region in caller.graph.regions for block in region.blocks}
        for edge_number, edge in enumerate(operation.terminator.successors):
            signatures = [row for row in operation.completions if row.kind is edge.kind]
            ports = [port for port in root.exits if port.kind is edge.kind]
            if len(signatures) != 1 or len(ports) != 1:
                frontiers.append(_front("COMPLETION_INTERFACE_OPEN", "No unique matching caller completion/callee exit declaration."))
                continue
            signature, exit_port = signatures[0], ports[0]
            if len(signature.types) != len(exit_port.types):
                frontiers.append(_front("COMPLETION_PAYLOAD_ADAPTER_REQUIRED", "Exception/traceback/state payload arities differ; no packet is synthesized."))
                continue
            for index, (caller_type, callee_type) in enumerate(zip(signature.types, exit_port.types)):
                if caller_type.kind is not callee_type.kind or caller_type.kind is ValueKind.DATA and caller_type.data_type != callee_type.data_type:
                    frontiers.append(_front("COMPLETION_TYPE_ADAPTER_REQUIRED", "Caller/callee completion payload types differ."))
                    continue
                positions = [number for number, argument in enumerate(edge.arguments)
                             if type(argument) is CompletionResult and argument.index == index]
                if len(positions) != 1:
                    frontiers.append(_front("COMPLETION_LANDING_UNRECOVERED", "Produced result has no unique original caller landing formal."))
                    continue
                terminal_ports = []
                port = ExitPortRef(root.id, exit_port.name, index)
                for block in root.blocks:
                    for op_id in block.operations:
                        op = callee.index.operations[op_id]
                        term = op.terminator
                        if term is None or term.kind not in (TerminatorKind.RETURN, TerminatorKind.RAISE) or term.exit != exit_port.name:
                            continue
                        if index >= len(term.values):
                            raise ValueError("callee terminal has a missing declared payload")
                        site = callee.index.use_site(term.values[index])
                        terminal_ports.append(StaticTerminalPort(port, block.id, op.id, site.use.id, site.use.value))
                        if edge.kind is ExitKind.NORMAL and index == 0 and caller_type.kind is ValueKind.REFERENCE:
                            returns.append(SourceReturnSite(port, block.id, op.id, site.use.id, site.use.value, 0))
                if not terminal_ports:
                    frontiers.append(_front("CALLEE_EXIT_SITE_OPEN", "Declared exit has no ordinary terminal site; special control/noncompletion remains explicit."))
                    continue
                completions.append(StaticCompletionRoute(edge.kind, caller_type.kind,
                    ControlEdgeReference(operation.id, edge_number), index, edge.block,
                    blocks[edge.block].arguments[positions[0]], port, tuple(terminal_ports)))
        return tuple(completions), tuple(dict.fromkeys(returns)), frontiers

    @staticmethod
    def _caller_world(caller):
        """Return the caller's original world port across its real frame ABI."""
        from scar.ir.program.source_subjects import (
            ClassFrameABI, FrameKind, MappingFramePorts, SourceCompilationFrameRoot,
        )
        if caller.module is not None:
            roots = caller.graph.frame_roots
            if (len(roots) != 1 or type(roots[0]) is not SourceCompilationFrameRoot
                    or roots[0].kind is not FrameKind.MODULE
                    or type(roots[0].entry) is not MappingFramePorts
                    or roots[0].scope != caller.module.root_scope
                    or roots[0].code != caller.module.declaration.compilation):
                return None, "MODULE_CALLER_FRAME_WORLD_UNRESOLVED"
            world_id = roots[0].entry.world
        elif caller.class_entry is not None:
            roots = caller.graph.frame_roots
            if (len(roots) != 1 or type(roots[0]) is not SourceCompilationFrameRoot
                    or roots[0].kind is not FrameKind.CLASS
                    or type(roots[0].entry) is not ClassFrameABI
                    or roots[0].scope != caller.class_entry.root_scope
                    or roots[0].entry != caller.class_entry.interface
                    or roots[0].code != caller.class_entry.compilation):
                return None, "CLASS_CALLER_FRAME_WORLD_UNRESOLVED"
            world_id = roots[0].entry.mapping.world
        elif caller.interface is not None:
            if caller.interface.region != caller.graph.root:
                return None, "FUNCTION_CALLER_FRAME_WORLD_UNRESOLVED"
            world_id = caller.interface.world
        else:
            return None, "CALLER_FRAME_WORLD_UNRESOLVED"
        value = caller.index.values.get(world_id)
        if type(value) is not StateVersionValue:
            return None, "CALLER_FRAME_WORLD_NOT_STATE_VERSION"
        return value, None

    def _target(self, caller, operation, source, semantic_call, actuals, number, definition, basis, *,
                creations=(), qualified_creations=()):
        context = caller.context if number == caller.context.number else self._unit(number)
        qualified, signature, entry, body_row = context.definitions[definition]
        from scar.analysis.function_binding import bind_call
        normalized_method = any(record.operation == operation.id
                                for record in getattr(caller.class_entry, "method_calls", ()))
        binding = (bind_call(signature, call=semantic_call, target=definition, source=source, arguments=actuals)
                   if semantic_call is not None and source is not None and not normalized_method else None)
        frontiers = [_front("TARGET_AND_FUNCTION_STATE_CONDITIONAL", "Raw function identity/code/defaults, no external namespace mutation and argument completion conditions are not discharged.", qualified.source)]
        if normalized_method:
            frontiers.append(_front("METHOD_SELF_SELECTION_ADAPTER_OPEN",
                "Original callable/optional-self/boolean ports are retained. Conditional implicit self must be adapted before binding explicit AST arguments to this signature.", source))
        if binding is None or binding.status is not CallBindingStatus.CONDITIONAL:
            frontiers.append(_front("ARGUMENT_BINDING_INCOMPLETE", "Signature/layout/expansion has no complete conditional parameter plan.", source))
        callee = self._body(context, *body_row) if body_row is not None else None
        if callee is None:
            frontiers.append(_front("CALLEE_BODY_UNAVAILABLE", "Original definition is cataloged, but no canonical body is available.", qualified.source))
            return StaticCallTarget(qualified, None, tuple(sorted(basis)), binding, frontiers=tuple(frontiers))
        arguments = []
        if binding is not None and binding.status is CallBindingStatus.CONDITIONAL:
            formals = {port.slot: port for port in callee.interface.parameters}
            names = {parameter.slot: parameter.name for parameter in signature.parameters}
            for parameter in binding.routes:
                if parameter.origin is not BindingOrigin.ARGUMENT:
                    frontiers.append(_front(parameter.origin.value + "_DEPENDENCY_OPEN", "Default reads require original function-state ports; varargs/kwargs need packing dependency, never an invented actual Use.", parameter.default_source))
                    continue
                actual = actuals[parameter.argument_indices[0]]
                if actual.use is None:
                    continue
                formal = formals[parameter.slot]
                site = caller.index.use_site(actual.use)
                arguments.append(SourceArgumentPort(actual.index, caller.namespace, operation.id,
                    actual.source, actual.use, site.use.value, callee.namespace,
                    formal.slot, formal.value, names[formal.slot], parameter))
        completions, returns, completion_gaps = self._completion_routes(caller, operation, callee)
        frontiers.extend(completion_gaps)
        state_entry = None
        caller_entry_world, world_issue = self._caller_world(caller)
        if world_issue is not None:
            frontiers.append(_front(world_issue,
                "Original caller frame has no unique validated world StateVersion port; state-entry routing is left open.", source))
        else:
            states = [use for use in operation.uses
                      if type(caller.index.values[use.value]) is StateVersionValue
                      and caller.index.values[use.value].location == caller_entry_world.location
                      and use.role is UseRole.STATE_CONTENT and use.id in operation.invoke_arguments]
            if len(states) == 1:
                before, after = caller.index.values[states[0].value], callee.index.values[callee.interface.world]
                state_entry = StaticStateEntryRoute(states[0].id, before.id, before.location, after.id, after.location)
            else:
                frontiers.append(_front("CALL_STATE_ENTRY_OPEN", "CALL has no unique STATE_CONTENT invoke argument in its caller's coarse-world location; the current SSA version need not equal the entry version."))
        from scar.analysis.static_function_environment import derive_function_environment_routes
        callee_uses = [row.use for row in caller.uses_by_op.get(operation.id, ()) if row.role == "callee"]
        environment_routes, environment_frontiers = derive_function_environment_routes(
            caller_graph=caller.graph, caller_document=caller.document, caller_namespace=caller.namespace,
            callee_graph=callee.graph, callee_document=callee.document, callee_namespace=callee.namespace,
            definition=qualified, call_operation=operation.id,
            callee_use=callee_uses[0] if len(callee_uses) == 1 else None,
            creations=tuple(creations), caller_index=caller.index, callee_index=callee.index,
            qualified_creations=tuple(qualified_creations), load_creation_body=self._load_body_namespace)
        frontiers.extend(environment_frontiers)
        frontiers.append(_front("ENVIRONMENT_PROJECTIONS_OPEN", "Emitted function-environment routes retain their explicit creation, target and field-state conditions; saved-builtins selection, mutable field contents and remaining environment projections are not closed."))
        frontiers.append(_front("FINE_EFFECTS_OPEN", "State interface correspondence is not a closed mod/ref, alias, escape or ready summary."))
        return StaticCallTarget(qualified, callee.namespace, tuple(sorted(basis)), binding,
            tuple(arguments), returns, completions, state_entry, tuple(frontiers),
            environment_routes=environment_routes)

    def _calls(self, body, *, operations=None):
        selected = {}
        for link in body.operation_links:
            if link.opcode is Opcode.CALL:
                previous = selected.setdefault(link.operation, link)
                if previous.source != link.source:
                    raise ValueError("canonical CALL has conflicting original source atoms")
        for target in body.metadata.call_targets:
            if target.operation not in selected:
                links = body.links_by_op.get(target.operation, ())
                if len(links) != 1:
                    raise ValueError("CallTarget has no unique original operation source")
                selected[target.operation] = links[0]
        for op_id, link in selected.items():
            if operations is not None and op_id not in operations:
                continue
            self._check()
            if (body.namespace, op_id) not in self._call_records:
                if self.counts["canonical_calls_processed"] >= self.budget.max_calls:
                    raise OverflowError("canonical CALL count budget exhausted")
                self.counts["canonical_calls_processed"] += 1
            operation = body.index.operations[op_id]
            if operation.terminator is None or operation.terminator.kind is not TerminatorKind.INVOKE:
                raise ValueError("source CALL lacks its original normal/raise INVOKE boundary")
            uses = [body.index.use_site(row.use).use for row in body.uses_by_op.get(op_id, ()) if row.role == "callee"]
            frontier = []
            callee_use = uses[0] if len(uses) == 1 else None
            if callee_use is None:
                frontier.append(_front("CALLEE_USE_UNRECOVERED", "Original CALL has no unique direct callee Use.", link.source))
            else:
                self._dependencies().register_call(body, operation, callee_use.id)
            node = body.context.call_nodes.get(link.source.atom_id)
            actuals, issues = self._actuals(body, operation, node)
            frontier.extend(issues)
            if body.call_source_bases.get(op_id) == "OPAQUE_SOURCE_REFINEMENT":
                frontier.append(_front("SOURCE_VIEW_REFINEMENT",
                    "Original SG opaque Call/source_operation is refined by the retained canonical CALL; the older computational overlay has no CALL record or invented operand values.", link.source))
                self.counts["source_view_refined_calls"] += 1
            if body.module is not None:
                self.counts["module_canonical_calls_processed"] += 1
                frontier.append(_front("MODULE_CALLER_NAMESPACE_PROJECTIONS_OPEN",
                    "Original module locals/globals/builtins/world ports remain distinct; no module local is treated as callee globals or loader state.",
                    link.source))
            elif body.class_entry is not None:
                self.counts["class_canonical_calls_processed"] += 1
                frontier.append(_front("CLASS_CALLER_NAMESPACE_AND_CLOSURE_PROJECTIONS_OPEN",
                    "Original class locals/globals/builtins and ordered closure-cell ports remain unmapped to callee globals/cells.",
                    link.source))
            if link.semantic_operation is None:
                # Keep the original CALL/actual interface in the denominator,
                # but never invent a semantic-call ID or a name-only target.
                resolved = self._source_candidates(body, operation, link.source, None)
            else:
                resolved = self._source_candidates(body, operation, link.source, link.semantic_operation)
            candidates, issues, namespace_flows, creations, qualified_flows, qualified_creations, crossflows = resolved
            if link.semantic_operation is None:
                issues.append(_front("CALL_SEMANTIC_LINK_UNAVAILABLE",
                    "Canonical CALL has no exact retained semantic CALL link; canonical namespace ports remain independently eligible.", link.source))
            frontier.extend(issues)
            targets = []
            for (number, definition), basis in sorted(candidates.items(), key=lambda item: (item[0][0], item[0][1].wire)):
                targets.append(self._target(body, operation, link.source, link.semantic_operation,
                                            actuals, number, definition, basis, creations=creations,
                                            qualified_creations=qualified_creations))
            if not targets:
                frontier.append(_front("TARGET_SET_UNRESOLVED", "No qualified function candidate follows from retained reaching/creation/import facts; no global name-only fallback.", link.source))
            frontier.append(_front("TARGET_SET_CLOSURE_OPEN", "Qualified namespace propagation does not establish whole-program points-to, function-state or effects closure.", link.source))
            self.counts["calls_with_candidates"] += bool(targets)
            self.counts["candidate_edges"] += len(targets)
            self.counts["namespace_flow_edges"] += len(namespace_flows)
            self.counts["function_creation_routes"] += len(creations)
            self.counts["argument_port_edges"] += sum(len(target.arguments) for target in targets)
            self.counts["normal_return_sites"] += sum(len(target.normal_returns) for target in targets)
            self.counts["completion_routes"] += sum(len(target.completions) for target in targets)
            self.counts["function_environment_routes"] += sum(len(target.environment_routes) for target in targets)
            yield StaticCallSite(body.namespace, op_id, link.source, link.semantic_operation,
                callee_use.id if callee_use else None, callee_use.value if callee_use else None,
                tuple(targets), tuple(dict.fromkeys(frontier)), namespace_flows=namespace_flows, function_creations=creations,
                qualified_namespace_flows=qualified_flows, qualified_function_creations=qualified_creations,
                cross_body_namespace_flows=crossflows)

    def _store_call(self, call):
        key = call.caller, call.operation
        if self._call_records.get(key) == call:
            return False
        self._call_records[key] = call
        if call.callee_use is not None:
            for target in call.targets:
                self._dependencies().activate_target(key, target)
        return True

    def _seed_calls(self):
        for number, unit in enumerate(self.units):
            self._check()
            if (Path(unit["path"]).suffix == ".pyi"
                    and any(key not in unit["artifacts"] for key in ("semantic", "semantics", "control"))):
                self.frontiers.append({"kind": "SOURCE_DECLARATION_ONLY", "unit": number,
                    "detail": "Stub source remains in the catalog; no execution body is asserted."})
                continue
            try:
                context = self._unit(number)
            except (OverflowError, TimeoutError):
                raise
            except (ValueError, KeyError, TypeError, SyntaxError) as error:
                self.frontiers.append({"kind": "SOURCE_UNIT_UNREADABLE", "unit": number, "detail": str(error)})
                continue
            for row_number, row in enumerate(unit["bodies"]):
                if "artifact" not in row:
                    self.counts["bodies_without_artifact"] += 1
                    continue
                if self.counts["body_artifacts_processed"] >= self.budget.max_bodies:
                    raise OverflowError("body count budget exhausted")
                self.counts["body_artifacts_processed"] += 1
                try:
                    body = self._body(context, row_number, row)
                    if body is None:
                        self.counts["body_artifacts_without_graph"] += 1
                        continue
                    self.counts["canonical_bodies_processed"] += 1
                    calls = []
                    for call in self._calls(body):
                        self._store_call(call)
                        calls.append(call)
                    self.body_summaries.append({"unit": number, "body": row_number,
                        "entry_key": row["entry_key"], "calls": len(calls), "caller": encode(body.namespace)})
                except (OverflowError, TimeoutError):
                    raise
                except (ValueError, KeyError, TypeError) as error:
                    self.frontiers.append({"kind": "CANONICAL_BODY_UNREADABLE", "unit": number,
                                           "body": row_number, "entry_key": row["entry_key"], "detail": str(error)})
        self._enumeration_complete = not any(row["kind"] in ("SOURCE_UNIT_UNREADABLE", "CANONICAL_BODY_UNREADABLE")
                                             for row in self.frontiers)

    def _settle_namespace_calls(self):
        if self._interprocedural is None:
            self._worklist_stable = True
            return
        while True:
            self._check()
            key = self._interprocedural.pop_affected()
            if key is None:
                self._worklist_stable = True
                return
            if key not in self._call_records:
                continue
            if self._worklist_iterations >= self.budget.max_interprocedural_steps:
                raise OverflowError("qualified namespace worklist step budget exhausted")
            self._worklist_iterations += 1
            body = self._load_body_namespace(key[0])
            for call in self._calls(body, operations=(key[1],)):
                self._store_call(call)

    def _recount_relations(self):
        # Refinement visits are analysis work, never additional source CALLs.
        names = ("canonical_calls_processed", "calls_with_candidates", "candidate_edges", "namespace_flow_edges",
                 "function_creation_routes", "qualified_namespace_flow_edges", "qualified_function_creation_routes",
                 "cross_body_namespace_flows", "argument_port_edges", "normal_return_sites", "completion_routes",
                 "function_environment_routes", "source_view_refined_calls", "module_canonical_calls_processed",
                 "class_canonical_calls_processed")
        for name in names:
            self.counts[name] = 0
        self.relation_frontier_counts.clear()
        for call in self._call_records.values():
            self.counts["canonical_calls_processed"] += 1
            self.counts["calls_with_candidates"] += bool(call.targets)
            self.counts["candidate_edges"] += len(call.targets)
            self.counts["namespace_flow_edges"] += len(call.namespace_flows)
            self.counts["function_creation_routes"] += len(call.function_creations)
            self.counts["qualified_namespace_flow_edges"] += len(call.qualified_namespace_flows)
            self.counts["qualified_function_creation_routes"] += len(call.qualified_function_creations)
            self.counts["cross_body_namespace_flows"] += len(call.cross_body_namespace_flows)
            self.counts["source_view_refined_calls"] += any(row.kind == "SOURCE_VIEW_REFINEMENT" for row in call.frontiers)
            number, position = self._body_locations[call.caller.graph.artifact.uri]
            kind = self.units[number]["bodies"][position]["kind"]
            self.counts["module_canonical_calls_processed"] += kind == "MODULE"
            self.counts["class_canonical_calls_processed"] += kind == "CLASS"
            self.relation_frontier_counts.update(row.kind for row in call.frontiers)
            for target in call.targets:
                self.counts["argument_port_edges"] += len(target.arguments)
                self.counts["normal_return_sites"] += len(target.normal_returns)
                self.counts["completion_routes"] += len(target.completions)
                self.counts["function_environment_routes"] += len(target.environment_routes)
                self.relation_frontier_counts.update(row.kind for row in target.frontiers)

    def iter_calls(self):
        """Seed source calls, consume qualified dependencies, then publish facts."""
        self._check()
        if self._iterated:
            raise ValueError("a static call session enumerates its source scope once")
        self._iterated = True
        try:
            self._seed_calls()
        except (OverflowError, TimeoutError) as error:
            self.frontiers.append({"kind": type(error).__name__, "stage": "CALL_ENUMERATION", "detail": str(error)})
        try:
            self._settle_namespace_calls()
        except (OverflowError, TimeoutError) as error:
            self.frontiers.append({"kind": type(error).__name__, "stage": "QUALIFIED_NAMESPACE_WORKLIST", "detail": str(error)})
        if self._interprocedural is not None:
            self.frontiers.extend({"kind": row.kind, "detail": row.detail,
                                   "source": None if row.source is None else encode(row.source)}
                                  for row in self._interprocedural.frontiers)
        self._recount_relations()
        # The computation deadline cannot discard already validated facts.
        # Finalization only serializes those records; no new input read occurs.
        self._finalizing = True
        yield from self._call_records.values()

    def close(self):
        if self._closed:
            return
        try:
            for path, stamp in self._stamps.items():
                if not path.is_file() or path.is_symlink() or _stamp(path) != stamp:
                    raise ValueError("original static input changed: " + str(path))
        finally:
            self._cache.clear()
            self._cache_bytes = 0
            self._closed = True

    def __enter__(self):
        self._check()
        return self

    def __exit__(self, *unused):
        self.close()


def build_static_call_links(directory, out, *, logical_root=None, expected_manifest_sha256=None, budget=None):
    """Write relationship-only gzip shards and return registry descriptors.

    Descriptor paths are relative to ``out``. The caller registers them in the
    same program manifest (e.g. indexes/calls/), atomically with publication.
    There is deliberately no second graph root or self-referential manifest URI.
    """
    session = StaticCallSession(directory, out=out, logical_root=logical_root,
                                expected_manifest_sha256=expected_manifest_sha256, budget=budget)
    shards, pending, caller, issue = [], [], None, None
    def flush():
        nonlocal pending
        if not pending:
            return
        shard = StaticCallShard(session.basis, pending[0].caller, tuple(pending))
        descriptor = session._write(f"calls/{len(shards):06d}.json.gz", dump_relations(shard).encode() + b"\n")
        shards.append({"artifact": descriptor, "artifact_path": descriptor["path"],
                       "caller_entry_key": session._caller_keys[shard.caller],
                       "caller": encode(shard.caller), "calls": len(pending)})
        pending = []
    try:
        with session:
            for call in session.iter_calls():
                if caller is not None and call.caller != caller:
                    flush()
                caller = call.caller
                pending.append(call)
            flush()
    except (OverflowError, TimeoutError) as error:
        issue = {"kind": type(error).__name__, "detail": str(error)}
        # Already closed relationship shards remain published. The incomplete
        # caller in memory is not silently counted as a completed shard.
    published_calls = sum(shard["calls"] for shard in shards)
    return {"schema": "scar.static-call-publication", "schema_version": 4,
            "source_model": encode(session.basis), "input_manifest_sha256": session.manifest_sha256,
            "artifacts": session.artifacts, "shards": shards, "counts": dict(session.counts),
            "published_calls": published_calls,
            "complete": issue is None and session._enumeration_complete,
            "status": "ENUMERATED_WITH_RELATION_FRONTIERS" if issue is None and session._enumeration_complete else "PARTIAL_ENUMERATION",
            "frontiers": session.frontiers + ([issue] if issue else []),
            "relation_frontier_counts": dict(session.relation_frontier_counts),
            "scope": {"declared_body_artifacts": session.counts["declared_body_artifacts"],
                      "processed_body_artifacts": session.counts["body_artifacts_processed"],
                      "remaining_body_artifacts": session.counts["declared_body_artifacts"] - session.counts["body_artifacts_processed"],
                      "canonical_bodies_processed": session.counts["canonical_bodies_processed"],
                      "canonical_call_denominator_complete": issue is None and session._enumeration_complete,
                      "namespace_worklist_quiescent_for_processed_scope": session._worklist_stable,
                      "namespace_worklist_iterations": session._worklist_iterations,
                      "namespace_cross_body_fact_count": session._interprocedural.fact_count if session._interprocedural else 0,
                      "target_resolution_complete": False, "whole_program_model_complete": False},
            "denominators": {"source_call_sites_declared": session.source_call_sites_declared,
                             "source_call_sites_cataloged": session.counts["source_call_sites_cataloged"],
                             "source_call_units_cataloged": session.counts["source_call_units_cataloged"],
                             "canonical_calls_processed": session.counts["canonical_calls_processed"],
                             "canonical_calls_published": published_calls,
                             "qualification": "Source syntax includes defaults/annotations/decorators and unlowered bodies; canonical CALL scope is separate and does not cover all source calls."},
            "measurements": {"input_bytes": session.input_bytes, "output_bytes": session.output_bytes,
                             "seconds": time.monotonic() - session.started},
            "qualification": "Conditional source relations over original qualified ports. SOURCE_VIEW_REFINEMENT identifies canonical CALL refinement of an original SG opaque Call, not a preexisting computational CALL overlay. No invocation, content identity, independent language replay, closed effects or runtime completion is established."}


__all__ = ["StaticCallBudget", "StaticCallSession", "build_static_call_links", "input_basis_unit"]
