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
    StaticCallTarget, StaticCompletionRoute, StaticStateEntryRoute, StaticTerminalPort,
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
    max_manifest_bytes: int = 128_000_000
    max_bodies: int = 10000
    max_calls: int = 1_000_000
    max_candidates_per_call: int = 64
    max_resolution_steps: int = 4096
    max_cached_bytes: int = 512_000_000
    max_output_bytes: int = 1_000_000_000
    max_seconds: int = 1800

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
        if time.monotonic() - self.started > self.budget.max_seconds:
            raise TimeoutError("static call wall budget exhausted")

    def _read_file(self, path, maximum):
        self._check()
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
        if document.get("module") is not None:
            from scar.ir.program.module_entries import decode_frame_body, StaticModuleEntryDeclaration
            from scar.ir.program.source_subjects import ModuleUnitSource, FrameKind, SourceCompilationCodeRef
            overlay = decode_frame_body(document["module"])
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
        result.operation_links = tuple(result.module.operation_links) if result.module is not None else metadata.operation_links
        result.use_links = tuple(result.module.use_links) if result.module is not None else metadata.use_links
        self._check_source_references(context, (graph, metadata, result.module,
            document.get("structured"), document.get("language"), document.get("frame"),
            document.get("static_compilation")))
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

    def _import_candidates(self, context, spec):
        names = [spec.requested]
        if spec.relative_level:
            names = []
            for module in context.unit.get("module_names", ()):
                package = module if Path(context.unit["path"]).name == "__init__.py" else module.rpartition(".")[0]
                parts = package.split(".") if package else []
                if spec.relative_level <= len(parts):
                    prefix = parts[:len(parts) - spec.relative_level + 1]
                    names.append(".".join((*prefix, spec.requested)) if spec.requested else ".".join(prefix))
        found = []
        if spec.symbol is None or spec.symbol == "*":
            return found
        for name in names:
            for number in self._module_units.get(name, ()):
                target = self._unit(number)
                for definition in target.exports.get(spec.symbol, ()):
                    found.append((number, definition, "IMPORT_CANDIDATE_NOT_LOADER_PROOF"))
        return found

    def _source_candidates(self, body, operation, source, semantic_call):
        context = body.context
        candidates, frontiers = {}, []
        def admit(number, definition, basis):
            if len(candidates) >= self.budget.max_candidates_per_call and (number, definition) not in candidates:
                frontiers.append(_front("CANDIDATE_BUDGET", "Candidate set was truncated; it remains open.", source))
                return
            candidate_context = context if number == context.number else self._unit(number)
            if definition in candidate_context.definitions:
                candidates.setdefault((number, definition), set()).add(basis)
        for target in body.metadata.call_targets:
            if target.operation == operation.id and target.source_definition is not None:
                admit(context.number, target.source_definition, "ORIGINAL_CALL_TARGET_METADATA")
        if semantic_call is not None:
            old = context.semantics.operations.get(semantic_call)
            if old is not None and (old.opcode is not Opcode.CALL or old.source != source):
                raise ValueError("candidate resolution requires its exact existing CALL overlay")
            if old is not None:
                for definition in context.calls_to_defs.get(semantic_call, ()):
                    admit(context.number, definition, "SOURCE_GRAPH_DECLARED_CANDIDATE")
            if old is not None and old.callee is not None:
                admit(context.number, old.callee, "SOURCE_SEMANTICS_DECLARED_CANDIDATE")
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
                    admit(context.number, definition, "FUNCTION_SOURCE_CREATION_CANDIDATE")
                if producer.opcode is Opcode.READ:
                    use = context.semantics.uses[producer.binding_use]
                    pending.extend(context.semantics.bindings[binding].value for binding in (*use.reaching, *use.conditional_reaching))
                    if not use.reaching:
                        frontiers.append(_front("SOURCE_BINDING_OPEN", "Deferred/global/cell binding is not made exact by a same-name definition.", producer.source))
                elif producer.opcode is Opcode.ALIAS:
                    pending.extend(operand.value for operand in producer.operands)
                elif producer.opcode is Opcode.IMPORT and producer.import_spec is not None:
                    for number, definition, basis in self._import_candidates(context, producer.import_spec):
                        admit(number, definition, basis)
                    frontiers.append(_front("IMPORT_ENVIRONMENT_OPEN", "Import candidates retain loader/package/export mutation conditions.", producer.source))
        # Follow only canonical binding payload/phi/creation references, never
        # every input of arbitrary computation as an alias to its result.
        links = defaultdict(list)
        for link in body.operation_links:
            links[link.operation].append(link)
        reads = {row.normal_result: row for row in body.graph.binding_reads if row.normal_result is not None}
        bindings = {row.value: row for row in body.graph.binding_definitions}
        incoming = defaultdict(list)
        for op in body.graph.operations:
            term = op.terminator
            if term is not None and term.kind in (TerminatorKind.JUMP, TerminatorKind.BRANCH):
                for edge in term.successors:
                    incoming[edge.block].append(edge)
        callee_uses = {row.use for row in body.uses_by_op.get(operation.id, ()) if row.role == "callee"}
        callee = next((use.value for use in operation.uses if use.id in callee_uses), None)
        pending, seen = [callee] if callee is not None else [], set()
        while pending:
            value_id = pending.pop()
            if value_id in seen:
                continue
            seen.add(value_id)
            if len(seen) > self.budget.max_resolution_steps:
                frontiers.append(_front("CANONICAL_ALIAS_BUDGET", "Canonical binding traversal remains partial.", source))
                break
            value = body.index.values[value_id]
            if value_id in reads:
                pending.append(body.index.use_site(reads[value_id].binding).use.value)
            elif value_id in bindings and bindings[value_id].payload is not None:
                pending.append(body.index.use_site(bindings[value_id].payload).use.value)
            elif isinstance(value.origin, BlockArgument):
                for edge in incoming[value.origin.block]:
                    if value.origin.index < len(edge.arguments):
                        argument = edge.arguments[value.origin.index]
                        if not isinstance(argument, CompletionResult):
                            pending.append(body.index.use_site(argument).use.value)
            elif isinstance(value.origin, OperationResult):
                for link in links.get(value.origin.operation, ()):
                    if type(link.source) is SourceReference:
                        for definition in context.defs_by_atom.get(link.source.atom_id, ()):
                            admit(context.number, definition, "CANONICAL_FUNCTION_CREATION_SOURCE")
        if body.call_source_bases.get(operation.id) == "OPAQUE_SOURCE_REFINEMENT":
            for bases in candidates.values():
                bases.add("VERIFIED_CANONICAL_CALL_REFINES_OPAQUE_SOURCE")
        return candidates, frontiers

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

    def _target(self, caller, operation, source, semantic_call, actuals, number, definition, basis):
        context = caller.context if number == caller.context.number else self._unit(number)
        qualified, signature, entry, body_row = context.definitions[definition]
        from scar.analysis.function_binding import bind_call
        binding = bind_call(signature, call=semantic_call, target=definition, source=source, arguments=actuals) if semantic_call is not None and source is not None else None
        frontiers = [_front("TARGET_AND_FUNCTION_STATE_CONDITIONAL", "Raw function identity/code/defaults, no external namespace mutation and argument completion conditions are not discharged.", qualified.source)]
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
        caller_entry_world = caller.index.values[caller.interface.world]
        if type(caller_entry_world) is not StateVersionValue:
            raise ValueError("caller interface world is not its original state value")
        states = [use for use in operation.uses
                  if type(caller.index.values[use.value]) is StateVersionValue
                  and caller.index.values[use.value].location == caller_entry_world.location
                  and use.role is UseRole.STATE_CONTENT and use.id in operation.invoke_arguments]
        state_entry = None
        if len(states) == 1:
            before, after = caller.index.values[states[0].value], callee.index.values[callee.interface.world]
            state_entry = StaticStateEntryRoute(states[0].id, before.id, before.location, after.id, after.location)
        else:
            frontiers.append(_front("CALL_STATE_ENTRY_OPEN", "CALL has no unique STATE_CONTENT invoke argument in its caller's coarse-world location; the current SSA version need not equal the entry version."))
        frontiers.append(_front("ENVIRONMENT_PROJECTIONS_OPEN", "Callee function-object/G/saved-B/defaults/cells are existing ports; projections and cell content/state must be linked separately, not borrowed from caller or equated by names."))
        frontiers.append(_front("FINE_EFFECTS_OPEN", "State interface correspondence is not a closed mod/ref, alias, escape or ready summary."))
        return StaticCallTarget(qualified, callee.namespace, tuple(sorted(basis)), binding,
            tuple(arguments), returns, completions, state_entry, tuple(frontiers))

    def _calls(self, body):
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
            self._check()
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
            node = body.context.call_nodes.get(link.source.atom_id)
            actuals, issues = self._actuals(body, operation, node)
            frontier.extend(issues)
            if body.call_source_bases.get(op_id) == "OPAQUE_SOURCE_REFINEMENT":
                frontier.append(_front("SOURCE_VIEW_REFINEMENT",
                    "Original SG opaque Call/source_operation is refined by the retained canonical CALL; the older computational overlay has no CALL record or invented operand values.", link.source))
                self.counts["source_view_refined_calls"] += 1
            if body.module is not None:
                frontier.append(_front("MODULE_CALL_ADAPTER", "Mapping-frame CALL is counted with original Use/source ports; function target/environment/completion linkage is not yet admitted.", link.source))
                self.counts["module_canonical_calls_processed"] += 1
                self.counts["canonical_calls_with_adapter_frontier"] += 1
                yield StaticCallSite(body.namespace, op_id, link.source, link.semantic_operation,
                    callee_use.id if callee_use else None, callee_use.value if callee_use else None,
                    (), tuple(dict.fromkeys(frontier)))
                continue
            if link.semantic_operation is None:
                # Keep the original CALL/actual interface in the denominator,
                # but never invent a semantic-call ID or a name-only target.
                candidates, issues = {}, [_front("CALL_SEMANTIC_LINK_UNAVAILABLE",
                    "Canonical CALL has no exact retained semantic CALL link; candidate/binding derivation is deferred.", link.source)]
            else:
                candidates, issues = self._source_candidates(body, operation, link.source, link.semantic_operation)
            frontier.extend(issues)
            targets = []
            for (number, definition), basis in sorted(candidates.items(), key=lambda item: (item[0][0], item[0][1].wire)):
                targets.append(self._target(body, operation, link.source, link.semantic_operation,
                                            actuals, number, definition, basis))
            if not targets:
                frontier.append(_front("TARGET_SET_UNRESOLVED", "No qualified function candidate follows from retained reaching/creation/import facts; no global name-only fallback.", link.source))
            frontier.append(_front("TARGET_SET_CLOSURE_OPEN", "This bounded direct/alias resolver is not whole-program points-to/effects closure.", link.source))
            self.counts["calls_with_candidates"] += bool(targets)
            self.counts["candidate_edges"] += len(targets)
            self.counts["argument_port_edges"] += sum(len(target.arguments) for target in targets)
            self.counts["normal_return_sites"] += sum(len(target.normal_returns) for target in targets)
            self.counts["completion_routes"] += sum(len(target.completions) for target in targets)
            yield StaticCallSite(body.namespace, op_id, link.source, link.semantic_operation,
                callee_use.id if callee_use else None, callee_use.value if callee_use else None,
                tuple(targets), tuple(dict.fromkeys(frontier)))

    def iter_calls(self):
        self._check()
        if self._iterated:
            raise ValueError("a static call session enumerates its source scope once")
        self._iterated = True
        for number, unit in enumerate(self.units):
            self._check()
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
                    calls = tuple(self._calls(body))
                    self.body_summaries.append({"unit": number, "body": row_number,
                        "entry_key": row["entry_key"], "calls": len(calls), "caller": encode(body.namespace)})
                    for call in calls:
                        self.relation_frontier_counts.update(front.kind for front in call.frontiers)
                        for target in call.targets:
                            self.relation_frontier_counts.update(front.kind for front in target.frontiers)
                        yield call
                except (OverflowError, TimeoutError):
                    raise
                except (ValueError, KeyError, TypeError) as error:
                    self.frontiers.append({"kind": "CANONICAL_BODY_UNREADABLE", "unit": number,
                                           "body": row_number, "entry_key": row["entry_key"], "detail": str(error)})

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
    return {"schema": "scar.static-call-publication", "schema_version": 1,
            "source_model": encode(session.basis), "input_manifest_sha256": session.manifest_sha256,
            "artifacts": session.artifacts, "shards": shards, "counts": dict(session.counts),
            "published_calls": published_calls,
            "complete": issue is None and not session.frontiers,
            "status": "ENUMERATED_WITH_RELATION_FRONTIERS" if issue is None and not session.frontiers else "PARTIAL_ENUMERATION",
            "frontiers": session.frontiers + ([issue] if issue else []),
            "relation_frontier_counts": dict(session.relation_frontier_counts),
            "scope": {"declared_body_artifacts": session.counts["declared_body_artifacts"],
                      "processed_body_artifacts": session.counts["body_artifacts_processed"],
                      "remaining_body_artifacts": session.counts["declared_body_artifacts"] - session.counts["body_artifacts_processed"],
                      "canonical_bodies_processed": session.counts["canonical_bodies_processed"],
                      "canonical_call_denominator_complete": issue is None and not session.frontiers,
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
