"""Join one retained source invocation to existing source/body ports.

The v4 invocation publication is consumed as a receipt-bound static binding
catalog; its former proof owner is not recreated.  Fresh raw frame/operand
records identify a selected direct CALL/entry pair.  Original source,
interface, body and CodeSourceLink records supply the canonical endpoints.
The result uses the existing receiver-aware PythonSourcePortModel, not a new
operation or program graph.
"""
from __future__ import annotations

from bisect import bisect_left
from bisect import bisect_left
from collections import Counter, defaultdict
from dataclasses import dataclass
import gzip
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
import time

from scar.analysis.call_operand_reader import read_call_operands
from scar.analysis.function_binding import bind_call
from scar.analysis.call_edges import _span
from scar.analysis.call_operand_routes import _checked_formal_ports
from scar.ir.program.call_edges import (
    CallLinkStatus, CodeCapture, CodeSourceLink, CapturedSite, InvocationKey,
)
from scar.ir.program.call_operands import CallOperandBudget, CallableKind
from scar.ir.program.call_operands import OperandGap, OperandScopedGap
from scar.ir.program.call_edges import CallEdgeBudget
from scar.ir.program.functions import (
    ArgumentKind, BindingOrigin, BodyEntryInterface,
    CallArgument, FunctionSignature, ParameterBinding, ParameterKind,
)
from scar.ir.program.inventory import CallInventory, BodyInventory, BodyStatus
from scar.ir.program.model import ReferenceValue, StateVersionValue, UseRole, TerminatorKind
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.program.python_call_targets import (
    BoundReceiver, ObservedPythonCallGraph, PythonCallTarget, PythonCodeScope,
    PythonEntryBinding, PythonSourcePortBinding, PythonSourcePortIssue,
    PythonSourcePortModel, PythonTargetKind, ReceiverCondition, ReceiverRole,
    SourceReceiverPort,
)
from scar.ir.program.source import LoweringMetadata
from scar.ir.program.source_call_bindings import SourceArgumentPort, SourceBodyNamespace
from scar.ir.program.source_references import SourceArtifactLocator, SourceDefinitionReference
from scar.ir.program.codec import loads as load_graph
from scar.ir.program.queries import ProgramIndex
from scar.ir.record_codec import decode, encode, loads as strict_loads
from scar.ir.semantics_v2 import Opcode


def _need(ok, detail):
    if not ok:
        raise ValueError("retained source-call ports: " + detail)


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _pointer(document, pointer):
    _need(type(pointer) is str and (pointer == "#" or pointer.startswith("#/")),
          "canonical JSON pointer required")
    value = document
    for token in pointer[2:].split("/") if pointer != "#" else ():
        token = token.replace("~1", "/").replace("~0", "~")
        if type(value) is list:
            _need(token.isdigit() and str(int(token)) == token, "canonical array pointer ordinal required")
            value = value[int(token)]
        else:
            value = value[token]
    return value


def _read(path, *, stored_sha256, stored_bytes, decoded_sha256=None,
          decoded_bytes=None, compressed=False, limit=128_000_000):
    path = Path(path).absolute()
    _need(not path.is_symlink() and path.is_file(), "receipt-bound regular input required: " + str(path))
    before = path.stat()
    _need(before.st_size <= limit and (stored_bytes is None or before.st_size == stored_bytes),
          "stored size differs or exceeds limit: " + str(path))
    _need(decoded_bytes is None or decoded_bytes <= limit, "declared decoded size exceeds limit: " + str(path))
    raw_stored = path.read_bytes()
    _need(len(raw_stored) == before.st_size and sha256(raw_stored).hexdigest() == stored_sha256,
          "stored SHA/size differs: " + str(path))
    if compressed:
        with gzip.GzipFile(fileobj=BytesIO(raw_stored), mode="rb") as stream:
            raw = stream.read(limit + 1)
    else:
        raw = raw_stored
    _need(len(raw) <= limit, "decoded input exceeds limit: " + str(path))
    after = path.stat()
    _need((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
          == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
          "input changed while being read: " + str(path))
    if decoded_sha256 is not None:
        _need(sha256(raw).hexdigest() == decoded_sha256 and len(raw) == decoded_bytes,
              "decoded SHA/size differs: " + str(path))
    return raw


def _locator(raw):
    _need(type(raw) is dict, "source locator must be an object")
    if set(raw) == {
        "artifact", "decoded_sha256", "decoded_bytes", "representation", "pointer", "declaration"
    }:
        a = raw["artifact"]
        _need(type(a) is dict and set(a) == {"uri", "sha256", "size_bytes", "schema"},
              "unsupported typed source artifact declaration")
        return SourceArtifactLocator(ProviderArtifact(a["uri"], a["sha256"], a["size_bytes"], a["schema"]),
            raw["decoded_sha256"], raw["decoded_bytes"], raw["representation"], raw["pointer"],
            None if raw["declaration"] is None else decode(ProviderFactReference, raw["declaration"])), None
    # Retained v4 rows also use the original publication locator shape for a
    # SourceProgram/5 file or its body-construction checkpoint.
    _need(set(raw) == {"artifact", "namespace", "pointer"},
          "unsupported retained source artifact locator")
    a = raw["artifact"]
    _need(type(a) is dict and set(a) == {
        "uri", "physical_sha256", "physical_bytes", "decoded_sha256", "decoded_bytes", "representation"
    }, "unsupported retained source artifact declaration")
    representation = "gzip-canonical-json" if a["uri"].endswith(".gz") else "canonical-json"
    locator = SourceArtifactLocator(
        ProviderArtifact(a["uri"], a["physical_sha256"], a["physical_bytes"], a["representation"]),
        a["decoded_sha256"], a["decoded_bytes"], representation, raw["pointer"], None)
    return locator, raw["namespace"]


def _receipt_row(row):
    return row["process_id"], row["family"], row["path"], row["raw_sha256"], row["raw_bytes"], row["lines"]


def _source_positions(source):
    return source.start_line, source.end_line, source.start_column, source.end_column


class _OperandBoundaryIndex:
    """One-pass indexes for interval-scoped gaps and read issues."""

    def __init__(self, operands):
        invocation_gaps, process_gaps, scoped_gaps = defaultdict(list), defaultdict(list), defaultdict(list)
        invocation_issues, process_issues = defaultdict(list), defaultdict(list)
        for event in operands.events:
            if type(event) in (OperandGap, OperandScopedGap):
                invocation = event.invocation
                if invocation is not None:
                    invocation_gaps[event.process_id, invocation].append(event)
                elif type(event) is OperandScopedGap:
                    scoped_gaps[event.process_id, event.code].append(event)
                else:
                    process_gaps[event.process_id].append(event)
        for issue in operands.issues:
            if issue.invocation is None:
                process_issues[issue.process_id].append(issue)
            else:
                invocation_issues[issue.process_id, issue.invocation].append(issue)
        self.invocation_gaps = self._freeze(invocation_gaps)
        self.process_gaps = self._freeze(process_gaps)
        self.scoped_gaps = self._freeze(scoped_gaps)
        self.invocation_issues = self._freeze(invocation_issues)
        self.process_issues = self._freeze(process_issues)

    @staticmethod
    def _freeze(groups):
        frozen = {}
        for key, items in groups.items():
            ordered = tuple(sorted(items, key=lambda item: item.index if hasattr(item, "index")
                                   else (item.anchor.index if item.anchor is not None else -1)))
            indices = tuple(item.index if hasattr(item, "index")
                            else (item.anchor.index if item.anchor is not None else -1) for item in ordered)
            frozen[key] = (ordered, indices)
        return frozen

    @staticmethod
    def _between(indexed, start, end):
        if indexed is None:
            return False
        _, indices = indexed
        offset = bisect_left(indices, start)
        return offset < len(indices) and indices[offset] <= end

    def check_interval(self, process, invocations, codes, start, end):
        if self._between(self.process_gaps.get(process), start, end):
            raise ValueError("raw process-wide gap intersects selected CALL-to-entry interval")
        if any(self._between(self.invocation_gaps.get((process, invocation)), start, end)
               for invocation in invocations):
            raise ValueError("raw invocation gap intersects selected CALL-to-entry interval")
        if any(self._between(self.scoped_gaps.get((process, code)), start, end) for code in codes):
            raise ValueError("raw code-scoped gap intersects selected CALL-to-entry interval")
        if self.process_issues.get(process):
            raise ValueError("operand reader has process-wide issue")
        for invocation in invocations:
            for issue in self.invocation_issues.get((process, invocation), ((), ()))[0]:
                if issue.anchor is not None and start <= issue.anchor.index <= end:
                    raise ValueError("raw operand reader issue intersects selected CALL-to-entry interval")


@dataclass(frozen=True, slots=True)
class _Body:
    row: dict
    definition: SourceDefinitionReference
    source_locator: SourceArtifactLocator
    namespace: SourceBodyNamespace
    graph: object
    metadata: LoweringMetadata
    interface: BodyEntryInterface
    code_link: CodeSourceLink
    inventory: dict
    index: ProgramIndex


class _Inputs:
    def __init__(self, source_report_path, bindings_path, expected_report_sha256,
                 expected_bindings_sha256, *, body_limit=128_000_000):
        report_path, bindings_path = Path(source_report_path).absolute(), Path(bindings_path).absolute()
        report_raw = _read(report_path, stored_sha256=expected_report_sha256,
            stored_bytes=None, limit=32_000_000)
        self.report = strict_loads(report_raw.decode("utf-8"))
        _need(self.report.get("schema") == "scar.source-invocations"
              and type(self.report.get("schema_version")) is int
              and self.report["schema_version"] == 4,
              "retained source report v4 required")
        _need(self.report.get("current_capture_raw_scan_verified") is True
              and self.report.get("old_capture_dynamic_facts_used_for_current_run") is False
              and self.report.get("first_stage_complete") is False
              and self.report.get("transformation_authorized") is False,
              "retained report does not have the expected open static-source scope")
        _need(self.report.get("witness_mode") == "same_capture"
              and self.report.get("source_definition_reference_format") == "scar.source-definition-reference.v1",
              "same-capture qualified source witness required")
        receipt = self.report["bindings"]
        _need(receipt.get("path") == "bindings.json" and bindings_path.name == "bindings.json"
              and bindings_path.parent == report_path.parent
              and receipt.get("raw_sha256") == expected_bindings_sha256,
              "binding document must be the report's adjacent qualified artifact")
        binding_raw = _read(bindings_path, stored_sha256=expected_bindings_sha256,
            stored_bytes=receipt.get("raw_bytes"), limit=32_000_000)
        self.document = strict_loads(binding_raw.decode("utf-8"))
        _need(self.document.get("schema") == "scar.source-invocation-bindings"
              and type(self.document.get("schema_version")) is int
              and self.document["schema_version"] == 4
              and self.document.get("witness_mode") == "same_capture"
              and self.document.get("transformation_authorized") is False
              and self.document.get("source_inputs") == self.report.get("source_inputs"),
              "v4 binding header/source parent differs from the retained report")
        _need(self.document.get("actual_formal_routing_established") is False
              and self.document.get("return_value_routing_established") is False
              and self.document.get("effects_established") is False,
              "retained invocation rows must remain static association only")
        self.report_path, self.bindings_path = report_path, bindings_path
        self.binding_sha256, self.binding_bytes = expected_bindings_sha256, len(binding_raw)
        self.binding_artifact = ProviderArtifact(str(bindings_path), expected_bindings_sha256,
            len(binding_raw), "scar.source-invocation-bindings/4")
        self.rows = self.document["bindings"]
        _need(type(self.rows) is list and len(self.rows) == self.report["summary"]["entered_code_groups"],
              "binding group denominator differs")
        self.by_group = {}
        for i, row in enumerate(self.rows):
            key = row["process_id"], row["code"]
            _need(row.get("binding_index") == i and key not in self.by_group,
                  "source group index/identity is duplicate or misordered")
            self.by_group[key] = row
        self.body_limit = body_limit
        self._body_cache = {}
        self._file_cache = {}
        self._signatures = None
        self._calls = {}
        self._code_links = {}

    def process_id(self, requested):
        pids = {m["process_id"] for m in self.report["collection_metadata"]}
        _need(len(pids) == 1, "report must identify exactly one captured process")
        pid, = pids
        _need(requested is None or requested == pid, "requested process differs from original v4 run")
        return pid

    def _manifest(self):
        if "manifest" in self._file_cache:
            return self._file_cache["manifest"]
        receipt = self.report["inventory"]
        path = Path(receipt["path"]).absolute()
        raw = _read(path, stored_sha256=receipt["raw_sha256"], stored_bytes=receipt["raw_bytes"],
                    limit=16_000_000)
        document = strict_loads(raw.decode("utf-8"))
        _need(document.get("schema") == "scar.partitioned-program-inventory"
              and document.get("schema_version") == 2,
              "retained inventory source catalog has unexpected header")
        self._file_cache["manifest"] = (path, document)
        return path, document

    def signatures(self):
        if self._signatures is not None:
            return self._signatures
        path, manifest = self._manifest()
        receipt = manifest["components"]["interfaces"]
        component_path = Path(receipt["uri"])
        if not component_path.is_absolute():
            component_path = path.parent / component_path
        raw = _read(component_path, stored_sha256=receipt["physical_sha256"],
            stored_bytes=receipt["physical_bytes"], decoded_sha256=receipt["decoded_sha256"],
            decoded_bytes=receipt["decoded_bytes"], compressed=receipt["representation"].endswith("/1"),
            limit=32_000_000)
        component = strict_loads(raw.decode("utf-8"))
        _need(component.get("schema") == "scar.inventory-component"
              and component.get("schema_version") == 1 and component.get("name") == "interfaces",
              "original typed interfaces component required")
        self._signatures = tuple(decode(FunctionSignature, item)
                                 for item in component["value"]["signatures"])
        return self._signatures

    def _code_link(self, row, definition):
        key = row["process_id"], row["code"]
        if key in self._code_links:
            return self._code_links[key]
        capture = decode(CodeCapture, row["code_capture"])
        locator = row["code_source_witness_locator"]
        artifact = locator["artifact"]
        a_path = Path(artifact["uri"])
        raw = _read(a_path, stored_sha256=artifact["physical_sha256"],
            stored_bytes=artifact["physical_bytes"], decoded_sha256=artifact["decoded_sha256"],
            decoded_bytes=artifact["decoded_bytes"], compressed=a_path.suffix == ".gz", limit=32_000_000)
        document = strict_loads(raw.decode("utf-8"))
        link = decode(CodeSourceLink, _pointer(document, locator["pointer"]))
        _need(row["complete_descriptor_match"] is True and capture.code.key == row["code"]
              and encode(capture) == row["code_capture"] and link.status is CallLinkStatus.VERIFIED
              and link.code == row["code"] and link.definition == definition.definition
              and link.snapshot == definition.snapshot and link.source == definition.source,
              "original complete CodeSourceLink/definition witness differs")
        self._code_links[key] = link
        return link

    def body(self, process, row):
        key = process, row["code"]
        if key in self._body_cache:
            return self._body_cache[key]
        _need(row.get("status") == "BODY_LINKED_REUSED_WITNESS"
              and row.get("complete_descriptor_match") is True
              and row.get("body") is not None and row.get("definition") is not None,
              "selected source group has no admitted qualified body")
        definition = decode(SourceDefinitionReference, row["definition"])
        link = self._code_link(row, definition)
        source_locator, legacy_namespace = _locator(row["body"]["canonical_locator"])
        _need(source_locator.artifact.schema in ("scar.source-program/5", "scar.body-construction-checkpoint/1")
              and source_locator.representation == "gzip-canonical-json"
              and source_locator.pointer == "#/graph" and source_locator.declaration is None,
              "original SourceProgram/5 or body-checkpoint/1 graph locator required")
        if legacy_namespace is not None:
            _need(legacy_namespace == row["body"]["namespace"],
                  "legacy canonical locator and retained body namespace differ")
        raw = _read(source_locator.artifact.uri, stored_sha256=source_locator.artifact.sha256,
            stored_bytes=source_locator.artifact.size_bytes, decoded_sha256=source_locator.decoded_sha256,
            decoded_bytes=source_locator.decoded_bytes, compressed=True, limit=self.body_limit)
        program = strict_loads(raw.decode("utf-8"))
        source_program = (program.get("schema") == "scar.source-program"
            and type(program.get("schema_version")) is int and program["schema_version"] == 5
            and source_locator.artifact.schema == "scar.source-program/5")
        checkpoint = (program.get("schema") == "scar.body-construction-checkpoint"
            and type(program.get("schema_version")) is int and program["schema_version"] == 1
            and source_locator.artifact.schema == "scar.body-construction-checkpoint/1"
            and program.get("whole_program_established") is False)
        _need(source_program or checkpoint,
              "selected artifact is neither retained SourceProgram/5 nor exact body-construction checkpoint/1")
        graph_doc = _pointer(program, source_locator.pointer)
        graph = load_graph(_canonical(graph_doc).decode("utf-8"))
        metadata = decode(LoweringMetadata, program["metadata"])
        interface = decode(BodyEntryInterface, program["interface"])
        _need(metadata.source == definition.snapshot and metadata.entry == row["body"]["namespace"]["body"]["entry"]
              and interface.definition == definition.definition and graph.root == interface.region
              and definition.definition == link.definition and definition.source == link.source,
              "source-program, source snapshot, code witness and original body namespace differ")
        if checkpoint:
            _need(program.get("source") == encode(definition.source)
                  and program.get("entry") == metadata.entry
                  and program.get("structured", {}).get("source") == encode(definition.source),
                  "body-construction checkpoint source/entry differs from its source definition")
        declared = ProviderFactReference(self.binding_artifact,
            f"#/bindings/{row['binding_index']}/body/canonical_locator")
        locator = SourceArtifactLocator(source_locator.artifact, source_locator.decoded_sha256,
            source_locator.decoded_bytes, source_locator.representation, source_locator.pointer, declared)
        namespace = SourceBodyNamespace(locator, "scar.program-graph/" + str(graph_doc["schema_version"]),
            definition.definition, definition.source, metadata.entry, graph.root)
        _need(namespace.original_namespace() == row["body"]["namespace"],
              "v4 group row does not declare this original body namespace")
        inventory = self._inventory_file(row)
        index = ProgramIndex(graph)
        body = _Body(row, definition, locator, namespace, graph, metadata, interface,
                     link, inventory, index)
        self._body_cache[key] = body
        return body

    def _inventory_file(self, row):
        loc = row["body"].get("inventory_locator")
        _need(type(loc) is dict and type(loc.get("artifact")) is dict,
              "original partitioned file-inventory locator is required")
        a = loc["artifact"]
        cache_key = (a["uri"], a["physical_sha256"], a["decoded_sha256"])
        if cache_key in self._file_cache:
            return self._file_cache[cache_key]
        path = Path(a["uri"])
        raw = _read(path, stored_sha256=a["physical_sha256"], stored_bytes=a["physical_bytes"],
            decoded_sha256=a["decoded_sha256"], decoded_bytes=a["decoded_bytes"],
            compressed=path.suffix == ".gz", limit=32_000_000)
        document = strict_loads(raw.decode("utf-8"))
        _need(document.get("schema") == "scar.partitioned-file-inventory"
              and type(document.get("schema_version")) is int and document["schema_version"] == 2,
              "source inventory locator does not name a partitioned file record")
        self._file_cache[cache_key] = document
        return document

    def call(self, row):
        key = row["process_id"], row["code"]
        if key in self._calls:
            return self._calls[key]
        document = self._inventory_file(row)
        file = document["file"]
        _need(document.get("file_index") == row["body"]["reference"]["file_index"]
              and file["snapshot"] == row["snapshot"],
              "original source-call partition differs from qualified body file/snapshot")
        calls = tuple(decode(CallInventory, raw) for raw in file["calls"])
        self._calls[key] = calls
        return calls

    def signature(self, definition):
        matches = [item for item in self.signatures() if item.definition == definition]
        _need(len(matches) == 1, "original source interface must have one exact function signature")
        return matches[0]

    def source_text(self, body, cache):
        snapshot = body.definition.snapshot
        key = snapshot.path, snapshot.fingerprint
        if key in cache:
            return cache[key]
        path = Path(snapshot.path)
        _need(path.is_absolute() and not path.is_symlink() and path.is_file(),
              "original captured source file must be available as a regular file")
        raw = path.read_bytes()
        expected = snapshot.fingerprint.removeprefix("sha256:")
        _need(len(raw) <= 16_000_000 and sha256(raw).hexdigest() == expected,
              "original source bytes no longer match the retained fingerprint")
        text = raw.decode(snapshot.encoding)
        import ast
        tree = ast.parse(text, filename=snapshot.path)
        cache[key] = tree
        return tree


def _find_call(tree, source):
    import ast
    span = _source_positions(source)
    matches = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and _span(node) == span]
    _need(len(matches) == 1, "original exact source span must select one AST Call")
    return matches[0]


def _selected_binding(inputs, operands, boundary_index, pid, attempt, handshake, caller_entry, callee_entry,
                      caller_row, callee_row, source_tree_cache):
    _need(attempt.dispatch.kind is CallableKind.EXACT_FUNCTION
          and attempt.dispatch.code == callee_entry.code
          and attempt.site.code == caller_entry.code
          and len(callee_entry.path) == 1 and callee_entry.path[0] == attempt.site
          and callee_entry.caller_invocation == caller_entry.invocation
          and handshake.invocation == callee_entry.invocation
          and handshake.entry_index == callee_entry.anchor.index
          and handshake.thread_id == attempt.thread_id
          and handshake.hook_epoch == attempt.hook_epoch,
          "raw attempt/handshake is not one exact direct function entry")
    _need(callee_entry.path_complete and callee_entry.caller == attempt.site
          and not caller_entry.suspended and not callee_entry.suspended,
          "suspended/incomplete frame path is outside the synchronous source-call rule")
    process_meta = next(item for item in operands.metadata if item.process_id == pid)
    _need(not process_meta.errors and not process_meta.io_failed
          and not process_meta.dropped_events and not process_meta.previous_profile,
          "operand process capture has errors, dropped events or previous profile")
    invocations = {attempt.invocation, callee_entry.invocation}
    code_keys = {caller_entry.code, callee_entry.code}
    boundary_index.check_interval(pid, invocations, code_keys, attempt.index, handshake.index)
    caller = inputs.body(pid, caller_row)
    callee = inputs.body(pid, callee_row)
    _need(attempt.site.position is not None and attempt.site.opname == "CALL"
          and attempt.site.code == caller.code_link.code
          and callee.code_link.code == callee_entry.code,
          "raw CALL site/CodeSourceLink scope differs")
    calls = [c for c in inputs.call(caller_row)
             if c.execution_owner == caller.definition.definition
             and _source_positions(c.source) == attempt.site.position]
    _need(len(calls) == 1, "original source inventory must identify one exact owner CALL")
    source_call, = calls
    call_node = _find_call(inputs.source_text(caller, source_tree_cache), source_call.source)
    _need(not call_node.keywords and not any(isinstance(arg, __import__("ast").Starred) for arg in call_node.args),
          "only explicit fixed positional source arguments are supported")
    call_links = [link for link in caller.metadata.operation_links
        if link.source == source_call.source and link.opcode is Opcode.CALL
        and link.semantic_operation == source_call.semantic_operation]
    _need(len(call_links) == 1 and source_call.semantic_operation is not None,
          "one original core CALL OperationSource must match the source inventory link")
    call_link, = call_links
    op_map = {op.id: op for op in caller.graph.operations}
    use_map = {use.id: use for op in caller.graph.operations for use in op.uses}
    op = op_map[call_link.operation]
    _need(op.terminator is not None and op.terminator.kind is TerminatorKind.INVOKE
          and len(op.invoke_arguments) == len(call_node.args) + 2,
          "canonical caller Operation must expose exact callee/actual/world Use partition")
    callee_use_links = [link for link in caller.metadata.use_links
        if link.operation == op.id and link.role == "callee"]
    _need(len(callee_use_links) == 1 and callee_use_links[0].use == op.invoke_arguments[0],
          "original CALL callee Use link differs")
    callee_use = use_map[callee_use_links[0].use]
    _need(callee_use.role is UseRole.REFERENCE and type(next(v for v in caller.graph.values if v.id == callee_use.value)) is ReferenceValue,
          "original CALL callee endpoint is not a ReferenceValue")
    world = use_map[op.invoke_arguments[-1]]
    value_map = {value.id: value for value in caller.graph.values}
    _need(world.role is UseRole.STATE_CONTENT and type(value_map[world.value]) is StateVersionValue
          and all(use_map[u].role is UseRole.REFERENCE and type(value_map[use_map[u].value]) is ReferenceValue
                  for u in op.invoke_arguments[:-1]),
          "caller actuals/world do not retain the source CALL reference/state roles")
    actual_links = sorted((link for link in caller.metadata.use_links
        if link.operation == op.id and link.role == "argument"), key=lambda item: item.index)
    _need(len(actual_links) == len(call_node.args)
          and tuple(link.index for link in actual_links) == tuple(range(len(actual_links)))
          and tuple(link.use for link in actual_links) == tuple(op.invoke_arguments[1:-1]),
          "original ordered actual Use/source links differ from the AST CALL")
    _need(tuple(_source_positions(link.source) for link in actual_links)
          == tuple(_span(arg) for arg in call_node.args),
          "ordered caller actual Uses do not name the original source argument occurrences")

    signature = inputs.signature(callee.definition.definition)
    _need(signature.source == callee.definition.source and signature.definition == callee.definition.definition
          and callee.interface.definition == signature.definition
          and tuple(port.slot for port in callee.interface.parameters)
              == tuple(param.slot for param in signature.parameters)
          and tuple(param.name for param in signature.parameters) == attempt.dispatch.layout.parameters
          and callee_entry.parameters_complete
          and tuple(p.name for p in callee_entry.parameters) == attempt.dispatch.layout.parameters,
          "target signature, body entry and captured code layout differ")
    _checked_formal_ports(BodyInventory(callee.definition.definition, BodyStatus.LOWERED_WITH_GAPS,
        callee.graph, callee.metadata, "retained exact body", 0), callee.interface, signature,
        {v.id: v for v in callee.graph.values},
        {b.id: b for region in callee.graph.regions for b in region.blocks},
        callee.definition.definition)
    arity = attempt.dispatch.layout.argcount
    if arity == len(call_node.args):
        target_kind = PythonTargetKind.FUNCTION
        receiver = None
        receiver_formal = None
    elif (arity == len(call_node.args) + 1 and isinstance(call_node.func, __import__("ast").Attribute)
          and not attempt.arg0_missing and callee.interface.parameters):
        target_kind = PythonTargetKind.NORMALIZED_RECEIVER_FUNCTION
        _need(attempt.arg0 is not None and callee_entry.parameters[0].ref == attempt.arg0,
              "captured CALL arg0 does not match the callee's first observed receiver parameter")
        observed = BoundReceiver(ReceiverRole.IMPLICIT_CALL_RECEIVER, attempt.arg0,
            explicit_positional=len(call_node.args),
            conditions=(ReceiverCondition.NO_INTERVENING_CALL_LAYOUT_MUTATION,))
        receiver = SourceReceiverPort(caller.namespace, op.id, callee_use.id, callee_use.value,
            callee.namespace, signature.parameters[0].slot, callee.interface.parameters[0].value,
            signature.parameters[0].name, observed)
        receiver_formal = signature.parameters[0]
    else:
        raise ValueError("unsupported source CALL/function positional ABI")
    _need(not attempt.dispatch.layout.kwonlyargcount
          and not attempt.dispatch.layout.flags & (4 | 8)
          and signature.kind.value == "SYNC" and not signature.decorators,
          "variadic, keyword-only, decorated or suspended target remains outside this rule")
    if target_kind is PythonTargetKind.FUNCTION:
        args = tuple(CallArgument(i, link.source, ArgumentKind.POSITIONAL, use=link.use)
                     for i, link in enumerate(actual_links))
        candidate = bind_call(signature, call=source_call.operation,
            target=callee.definition.definition, source=source_call.source, arguments=args)
        _need(candidate.status.value == "CONDITIONAL", "original source signature has no conditional positional binding")
        routes = {route.slot: route for route in candidate.routes}
        param_positions = {parameter.slot: parameter for parameter in signature.parameters}
        mapped = [(param_positions[r.slot], r) for r in candidate.routes]
        ports = []
        for i, link in enumerate(actual_links):
            route = next(route for route in candidate.routes if route.argument_indices == (i,))
            parameter = param_positions[route.slot]
            formal = next(port for port in callee.interface.parameters if port.slot == parameter.slot)
            ports.append(SourceArgumentPort(i, caller.namespace, op.id, link.source, link.use,
                use_map[link.use].value, callee.namespace, parameter.slot, formal.value,
                parameter.name, route))
        receiver_port = None
    else:
        candidate = None
        ports = []
        for i, link in enumerate(actual_links):
            parameter = signature.parameters[i + 1]
            formal = callee.interface.parameters[i + 1]
            route = ParameterBinding(parameter.slot, BindingOrigin.ARGUMENT, (i,))
            ports.append(SourceArgumentPort(i, caller.namespace, op.id, link.source, link.use,
                use_map[link.use].value, callee.namespace, parameter.slot, formal.value,
                parameter.name, route))
        receiver_port = receiver
    call_site = __import__("scar.ir.program.call_edges", fromlist=["CallSiteLink"]).CallSiteLink(
        attempt.site, CallLinkStatus.VERIFIED, source_call.source, source_call.operation,
        source_call.execution_owner, caller.graph.root, op.id, callee_use.id, callee_use.value)
    source_path = Path(callee.definition.source.path).absolute()
    project_path = Path(inputs.report["collection_metadata"][0]["project_root"]).absolute()
    try:
        source_path.relative_to(project_path)
        code_scope = PythonCodeScope.PROJECT
    except ValueError:
        code_scope = PythonCodeScope.OBSERVED_EXTERNAL_PYTHON
    target = PythonCallTarget(attempt.index, caller_entry.invocation, target_kind,
        attempt.dispatch.reference, attempt.dispatch.reference, attempt.dispatch.code,
        attempt.dispatch.layout, (None if receiver is None else receiver.observed),
        code_scope)
    entry = PythonEntryBinding(attempt.index, caller_entry.invocation, callee_entry.invocation,
        callee_entry.anchor.index, callee_entry.code,
        None if receiver_formal is None else 0,
        None if receiver_formal is None else attempt.arg0)
    binding = PythonSourcePortBinding(target, attempt.anchor, entry, callee_entry.anchor,
        attempt.anchor, callee_entry.anchor, caller.code_link, callee.code_link, call_site,
        caller.namespace, callee.namespace, receiver_port, tuple(ports), candidate)
    return target, entry, binding


def build_retained_source_call_ports(*, source_report_path, bindings_path,
        expected_report_sha256, expected_bindings_sha256, trace_root=None,
        pid=None, max_selected_calls=1, build_report_path=None,
        body_limit=128_000_000):
    """Build a bounded selected-scope model from original retained inputs.

    ``max_selected_calls`` caps successfully linked calls.  The returned model
    contains only selected targets; the optional build report retains the full
    fresh raw-reader denominator and the exact selected range.
    """
    _need(type(max_selected_calls) is int and max_selected_calls > 0,
          "positive selected-call ceiling required")
    inputs = _Inputs(source_report_path, bindings_path, expected_report_sha256,
                     expected_bindings_sha256, body_limit=body_limit)
    captured_pid = inputs.process_id(pid)
    default_trace = inputs.report["attachment_capture_checks"][0]["trace_directory"]
    trace_root = Path(default_trace if trace_root is None else trace_root).absolute()
    _need(str(trace_root) == default_trace, "trace root must be the v4 report's exact capture")
    project_root = inputs.report["collection_metadata"][0]["project_root"]
    raw_budget = inputs.report["call_budget"]
    frame_budget = CallEdgeBudget(
        max_raw_bytes=raw_budget["max_raw_bytes"], max_lines=raw_budget["max_lines"],
        max_line_bytes=raw_budget["max_line_bytes"], max_processes=raw_budget["max_processes"],
        max_codes=raw_budget["max_codes"], max_events=raw_budget["max_events"],
        max_source_files=raw_budget["max_source_files"], max_source_bytes=raw_budget["max_source_bytes"],
        max_references=raw_budget["max_references"], max_path=raw_budget["max_path"])
    operand_budget = CallOperandBudget(max_raw_bytes=256_000_000, max_lines=1_000_000,
        max_line_bytes=2_000_000, max_processes=128, max_events=1_000_000,
        max_loads=1_000_000, max_references=2_000_000, max_metadata_bytes=2_000_000)
    started = time.monotonic()
    operands = read_call_operands(trace_root, project_root, budget=operand_budget,
                                  frame_budget=frame_budget)
    raw_read_seconds = time.monotonic() - started
    report_files = sorted(_receipt_row(row) for row in inputs.report["trace_files"])
    current_files = sorted((f.process_id, f.family, f.path, f.raw_sha256, f.raw_bytes, f.lines)
                           for f in operands.frame_scan.files)
    _need(report_files == current_files
          and list(operands.frame_scan.metadata) == inputs.report["collection_metadata"]
          and len(operands.entries) == inputs.report["summary"]["invocations"]
          and len(operands.exits) == inputs.report["summary"]["exits"]
          and len(operands.frame_scan.captures) == inputs.report["summary"]["code_captures"],
          "fresh raw frame scan differs from original v4 receipt/denominators")
    rows = inputs.by_group
    grouped = Counter((entry.invocation.process_id, entry.code) for entry in operands.entries)
    _need(set(grouped) == set(rows)
          and all(grouped[key] == row["entered_invocations"] for key, row in rows.items()),
          "fresh frame-entry code groups differ from retained v4 source denominator")
    captures = {(item.process_id, item.code.key): item for item in operands.frame_scan.captures}
    entries = {item.invocation: item for item in operands.entries}
    handshakes = defaultdict(list)
    for item in operands.handshakes:
        handshakes[item.process_id, item.attempt_index].append(item)
    meta = {item.process_id: item for item in operands.metadata}
    boundary_index = _OperandBoundaryIndex(operands)
    selected_targets, selected_entries, bindings = [], [], []
    selected_indices, candidate_issues = [], Counter()
    candidate_count = 0
    source_tree_cache = {}
    selected_attempts = set()
    for attempt in operands.attempts:
        if attempt.process_id != captured_pid:
            continue
        matches = handshakes.get((attempt.process_id, attempt.index), ())
        if len(matches) != 1:
            continue
        handshake, = matches
        caller_entry = entries.get(attempt.invocation)
        callee_entry = entries.get(handshake.invocation)
        if caller_entry is None or callee_entry is None:
            continue
        caller_row = rows.get((captured_pid, caller_entry.code))
        callee_row = rows.get((captured_pid, callee_entry.code))
        if (caller_row is None or callee_row is None
                or caller_row.get("status") != "BODY_LINKED_REUSED_WITNESS"
                or callee_row.get("status") != "BODY_LINKED_REUSED_WITNESS"):
            continue
        candidate_count += 1
        try:
            for group_row, entry_record in ((caller_row, caller_entry), (callee_row, callee_entry)):
                capture = captures.get((captured_pid, entry_record.code))
                _need(capture is not None and encode(capture) == group_row["code_capture"],
                      "current complete captured descriptor differs from the retained source group")
            target, entry, binding = _selected_binding(inputs, operands, boundary_index, captured_pid,
                attempt, handshake, caller_entry, callee_entry, caller_row, callee_row,
                source_tree_cache)
            if attempt.index in selected_attempts:
                raise ValueError("duplicate selected raw attempt")
            selected_attempts.add(attempt.index)
            selected_targets.append(target); selected_entries.append(entry); bindings.append(binding)
            selected_indices.append(attempt.index)
            if len(bindings) >= max_selected_calls:
                break
        except Exception as exc:
            detail = str(exc).removeprefix("retained source-call ports: ").split(":", 1)[0]
            candidate_issues[f"{type(exc).__name__}: {detail}"] += 1
    operand_file = next(f for f in operands.files if f.process_id == captured_pid and f.family == "operands")
    graph = ObservedPythonCallGraph(operand_file.path, operand_file.raw_sha256,
        tuple(selected_targets), tuple(selected_entries), (),
        tuple(binding.attempt for binding in bindings), tuple(binding.entry_anchor for binding in bindings))
    model = PythonSourcePortModel(graph, tuple(bindings), ())
    if build_report_path is not None:
        source_stamps = {}
        for name, source_path in (("retained_source_call_ports.py", Path(__file__)),
                                  ("source_return_bindings.py", Path(__file__).with_name("source_return_bindings.py"))):
            source_stamps[name] = {"path": str(source_path), "sha256": sha256(source_path.read_bytes()).hexdigest()}
        report = {
            "schema": "scar.retained-source-call-port-build",
            "schema_version": 1,
            "source_report": {"path": str(inputs.report_path), "sha256": expected_report_sha256,
                              "bytes": inputs.report_path.stat().st_size, "schema_version": 4},
            "bindings": {"path": str(inputs.bindings_path), "sha256": expected_bindings_sha256,
                         "bytes": inputs.binding_bytes, "schema_version": 4},
            "capture": {"trace_root": str(trace_root), "process_id": captured_pid,
                "project_root": project_root,
                "frame_entries": len(operands.entries), "frame_exits": len(operands.exits),
                "attempts_total": len(operands.attempts), "handshakes": len(operands.handshakes),
                "raw_reader_seconds": raw_read_seconds,
                "operand_instructions": len(operands.instructions),
                "frame_files": [encode_file(f) for f in operands.frame_scan.files],
                "operand_files": [encode_file(f) for f in operands.files]},
            "selection": {"status": "SELECTED_PORTS_BUILT" if bindings else "TRANSPORT_ONLY_ZERO_LINKS",
                "max_selected_calls": max_selected_calls,
                "direct_body_linked_candidate_pairs_examined": candidate_count,
                "selected_attempt_indices": selected_indices,
                "unmodeled_attempts": len(operands.attempts) - len(selected_indices),
                "candidate_issues": dict(sorted(candidate_issues.items()))},
            "summary": model.summary(),
            "producer_sources": source_stamps,
            "claims": {"actual_formal_routing_established": False,
                "normal_return_selected": False, "runtime_callable_environment_established": False,
                "receiver_identity_established": False, "content_or_effect_equivalence_established": False,
                "full_attempt_denominator_connected": False, "whole_program_graph_established": False,
                "transformation_authorized": False},
            "limitations": [
                "selected ports connect original source/core Uses and formal values only under the existing conditional source ABI",
                "captured entry is an observed call/entry association, not a proof of callable environment",
                "the receiver record is a reference projection, not object-content or alias proof",
                "normal return is a source/body conditional view and does not select the runtime return",
                "attempts outside selected_attempt_indices are not materialized in this output",
                "candidate_issues identify builder/interface compatibility and scoped eligibility; they are not source proof conclusions",
            ],
        }
        out = Path(build_report_path).absolute()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(_canonical(report) + b"\n")
    return model


def encode_file(item):
    return {"path": item.path, "family": item.family, "process_id": item.process_id,
            "raw_sha256": item.raw_sha256, "raw_bytes": item.raw_bytes, "lines": item.lines}


__all__ = ["build_retained_source_call_ports"]
