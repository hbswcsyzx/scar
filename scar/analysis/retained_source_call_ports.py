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
from collections import Counter, OrderedDict, defaultdict
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
    CallLinkStatus, CodeCapture, CodeSourceLink, CapturedSite,
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
        raise _NeedError("retained source-call ports: " + detail)


class _NeedError(ValueError):
    """A typed record/scope condition, distinct from an implementation exception."""


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
            raise _NeedError("raw process-wide gap intersects selected CALL-to-entry interval")
        if any(self._between(self.invocation_gaps.get((process, invocation)), start, end)
               for invocation in invocations):
            raise _NeedError("raw invocation gap intersects selected CALL-to-entry interval")
        if any(self._between(self.scoped_gaps.get((process, code)), start, end) for code in codes):
            raise _NeedError("raw code-scoped gap intersects selected CALL-to-entry interval")
        if self.process_issues.get(process):
            raise _NeedError("operand reader has process-wide issue")
        for invocation in invocations:
            for issue in self.invocation_issues.get((process, invocation), ((), ()))[0]:
                if issue.anchor is not None and start <= issue.anchor.index <= end:
                    raise _NeedError("raw operand reader issue intersects selected CALL-to-entry interval")


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
                 expected_bindings_sha256, *, body_limit=128_000_000,
                 max_live_body_decoded_bytes=64_000_000):
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
        self.report_sha256 = expected_report_sha256
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
        self.max_live_body_views = 32
        self.max_live_body_programs = 8
        _need(type(max_live_body_decoded_bytes) is int and max_live_body_decoded_bytes > 0,
              "positive live decoded body-cache ceiling required")
        self.max_live_body_decoded_bytes = max_live_body_decoded_bytes
        self._body_cache = OrderedDict()
        self._body_program_keys = {}
        self._program_cache = OrderedDict()
        self._program_cache_decoded_bytes = 0
        self._file_cache = OrderedDict()
        self.max_inventory_partitions = 16
        self._signatures = None
        self._calls = OrderedDict()
        self.max_call_partitions = 32
        self._code_links = {}
        self.stats = Counter()

    def process_id(self, requested):
        pids = {m["process_id"] for m in self.report["collection_metadata"]}
        _need(len(pids) == 1, "report must identify exactly one captured process")
        pid, = pids
        _need(requested is None or requested == pid, "requested process differs from original v4 run")
        return pid

    def _drop_program(self, key):
        cached = self._program_cache.pop(key, None)
        if cached is None:
            return
        self._program_cache_decoded_bytes -= cached[-1]
        for body_key, program_key in tuple(self._body_program_keys.items()):
            if program_key == key:
                self._body_cache.pop(body_key, None)
                self._body_program_keys.pop(body_key, None)
        self.stats["body_program_cache_evictions"] += 1

    def _store_program(self, key, value, decoded_bytes):
        if decoded_bytes > self.max_live_body_decoded_bytes:
            self.stats["body_programs_too_large_to_cache"] += 1
            return False
        while (len(self._program_cache) >= self.max_live_body_programs
               or self._program_cache_decoded_bytes + decoded_bytes > self.max_live_body_decoded_bytes):
            oldest, _ = next(iter(self._program_cache.items()))
            self._drop_program(oldest)
        self._program_cache[key] = (*value, decoded_bytes)
        self._program_cache_decoded_bytes += decoded_bytes
        self.stats["body_program_cache_admissions"] += 1
        return True

    def _manifest(self):
        if "manifest" in self._file_cache:
            self.stats["inventory_manifest_cache_hits"] += 1
            self._file_cache.move_to_end("manifest")
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
        self.stats["inventory_manifest_reads"] += 1
        self.stats["inventory_manifest_stored_bytes"] += receipt["raw_bytes"]
        return path, document

    def signatures(self):
        if self._signatures is not None:
            self.stats["interface_component_cache_hits"] += 1
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
        self.stats["interface_component_reads"] += 1
        self.stats["interface_component_stored_bytes"] += receipt["physical_bytes"]
        self.stats["interface_component_decoded_bytes"] += len(raw)
        return self._signatures

    def _code_link(self, row, definition):
        key = row["process_id"], row["code"]
        if key in self._code_links:
            self.stats["code_witness_cache_hits"] += 1
            return self._code_links[key]
        capture = decode(CodeCapture, row["code_capture"])
        locator = row["code_source_witness_locator"]
        artifact = locator["artifact"]
        a_path = Path(artifact["uri"])
        raw = _read(a_path, stored_sha256=artifact["physical_sha256"],
            stored_bytes=artifact["physical_bytes"], decoded_sha256=artifact["decoded_sha256"],
            decoded_bytes=artifact["decoded_bytes"], compressed=a_path.suffix == ".gz", limit=32_000_000)
        self.stats["code_witness_reads"] += 1
        self.stats["code_witness_stored_bytes"] += artifact["physical_bytes"]
        self.stats["code_witness_decoded_bytes"] += len(raw)
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
            self._body_cache.move_to_end(key)
            self.stats["body_view_cache_hits"] += 1
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
        program_key = (source_locator.artifact.uri, source_locator.artifact.sha256,
            source_locator.artifact.size_bytes, source_locator.artifact.schema,
            source_locator.decoded_sha256, source_locator.decoded_bytes,
            source_locator.representation, source_locator.pointer)
        cached_program = self._program_cache.get(program_key)
        if cached_program is None:
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
            _need(metadata.source == definition.snapshot
                  and metadata.entry == row["body"]["namespace"]["body"]["entry"]
                  and interface.definition == definition.definition and graph.root == interface.region
                  and definition.definition == link.definition and definition.source == link.source,
                  "source-program, source snapshot, code witness and original body namespace differ")
            if checkpoint:
                _need(program.get("source") == encode(definition.source)
                      and program.get("entry") == metadata.entry
                      and program.get("structured", {}).get("source") == encode(definition.source),
                      "body-construction checkpoint source/entry differs from its source definition")
            graph_version = graph_doc["schema_version"]
            index = ProgramIndex(graph)
            cacheable = self._store_program(program_key,
                (graph, metadata, interface, definition, index, graph_version), len(raw))
            self.stats["body_artifact_reads"] += 1
            self.stats["body_artifact_stored_bytes"] += source_locator.artifact.size_bytes
            self.stats["body_artifact_decoded_bytes"] += len(raw)
        else:
            graph, metadata, interface, cached_definition, index, graph_version, _ = cached_program
            self._program_cache.move_to_end(program_key)
            cacheable = True
            _need(cached_definition == definition,
                  "one original body locator was assigned conflicting source definitions")
            _need(metadata.source == definition.snapshot and metadata.entry == row["body"]["namespace"]["body"]["entry"]
                  and interface.definition == definition.definition and graph.root == interface.region
                  and definition.definition == link.definition and definition.source == link.source,
                  "cached source-program, source snapshot, code witness and body namespace differ")
            self.stats["body_artifact_cache_hits"] += 1
        declared = ProviderFactReference(self.binding_artifact,
            f"#/bindings/{row['binding_index']}/body/canonical_locator")
        locator = SourceArtifactLocator(source_locator.artifact, source_locator.decoded_sha256,
            source_locator.decoded_bytes, source_locator.representation, source_locator.pointer, declared)
        namespace = SourceBodyNamespace(locator, "scar.program-graph/" + str(graph_version),
            definition.definition, definition.source, metadata.entry, graph.root)
        _need(namespace.original_namespace() == row["body"]["namespace"],
              "v4 group row does not declare this original body namespace")
        inventory = self._inventory_file(row)
        body = _Body(row, definition, locator, namespace, graph, metadata, interface,
                     link, inventory, index)
        if cacheable:
            self._body_cache[key] = body
            self._body_program_keys[key] = program_key
            while len(self._body_cache) > self.max_live_body_views:
                old_key, _ = self._body_cache.popitem(last=False)
                self._body_program_keys.pop(old_key, None)
                self.stats["body_view_cache_evictions"] += 1
        return body

    def _inventory_file(self, row):
        loc = row["body"].get("inventory_locator")
        _need(type(loc) is dict and type(loc.get("artifact")) is dict,
              "original partitioned file-inventory locator is required")
        a = loc["artifact"]
        cache_key = (a["uri"], a["physical_sha256"], a["decoded_sha256"])
        if cache_key in self._file_cache:
            self.stats["inventory_partition_cache_hits"] += 1
            self._file_cache.move_to_end(cache_key)
            return self._file_cache[cache_key]
        path = Path(a["uri"])
        raw = _read(path, stored_sha256=a["physical_sha256"], stored_bytes=a["physical_bytes"],
            decoded_sha256=a["decoded_sha256"], decoded_bytes=a["decoded_bytes"],
            compressed=path.suffix == ".gz", limit=32_000_000)
        document = strict_loads(raw.decode("utf-8"))
        schema_version = document.get("schema_version")
        _need(document.get("schema") == "scar.partitioned-file-inventory"
              and type(schema_version) is int and schema_version in (1, 2)
              and a.get("representation") == f"scar.partitioned-file-inventory/{schema_version}",
              "source inventory locator does not name a supported partitioned file record")
        self._file_cache[cache_key] = document
        partition_keys = [key for key in self._file_cache if key != "manifest"]
        while len(partition_keys) > self.max_inventory_partitions:
            oldest = next(key for key in self._file_cache if key != "manifest")
            del self._file_cache[oldest]
            partition_keys.remove(oldest)
            self.stats["inventory_partition_cache_evictions"] += 1
        self.stats["inventory_partition_reads"] += 1
        self.stats[f"inventory_partition_v{schema_version}_reads"] += 1
        self.stats["inventory_partition_stored_bytes"] += a["physical_bytes"]
        self.stats["inventory_partition_decoded_bytes"] += len(raw)
        return document

    def call(self, row):
        key = row["process_id"], row["code"]
        if key in self._calls:
            self.stats["source_call_partition_cache_hits"] += 1
            self._calls.move_to_end(key)
            return self._calls[key]
        document = self._inventory_file(row)
        file = document["file"]
        _need(document.get("file_index") == row["body"]["reference"]["file_index"]
              and file["snapshot"] == row["snapshot"],
              "original source-call partition differs from qualified body file/snapshot")
        calls = tuple(decode(CallInventory, raw) for raw in file["calls"])
        self._calls[key] = calls
        while len(self._calls) > self.max_call_partitions:
            self._calls.popitem(last=False)
            self.stats["source_call_partition_cache_evictions"] += 1
        return calls

    def signature(self, definition):
        matches = [item for item in self.signatures() if item.definition == definition]
        _need(len(matches) == 1, "original source interface must have one exact function signature")
        return matches[0]

    def source_text(self, body, cache):
        snapshot = body.definition.snapshot
        key = snapshot.path, snapshot.fingerprint
        if key in cache:
            if hasattr(cache, "move_to_end"):
                cache.move_to_end(key)
            self.stats["source_syntax_cache_hits"] += 1
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
        source_tree_limit = 8
        while len(cache) > source_tree_limit:
            cache.popitem(last=False)
            self.stats["source_syntax_cache_evictions"] += 1
        self.stats["source_file_reads"] += 1
        self.stats["source_file_bytes"] += len(raw)
        return tree


def _find_call(tree, source):
    import ast
    span = _source_positions(source)
    matches = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and _span(node) == span]
    _need(len(matches) == 1, "original exact source span must select one AST Call")
    return matches[0]


@dataclass(frozen=True, slots=True)
class _ReceiverTemplate:
    actual_body: SourceBodyNamespace
    operation: object
    callable_use: object
    callable_value: object
    formal_body: SourceBodyNamespace
    formal_slot: object
    formal_value: object
    formal_name: str
    explicit_positional: int


@dataclass(frozen=True, slots=True)
class _SourcePortTemplate:
    """Static checked endpoints only; no raw occurrence refs, arg0 or anchors."""
    kind: PythonTargetKind
    layout: object
    scope: PythonCodeScope
    caller_code: CodeSourceLink
    callee_code: CodeSourceLink
    call: object
    caller_body: SourceBodyNamespace
    callee_body: SourceBodyNamespace
    receiver: _ReceiverTemplate | None
    arguments: tuple[SourceArgumentPort, ...]
    candidate: object
    conditions: tuple


def _call_template_key(attempt, caller_entry, callee_entry):
    return (caller_entry.code, callee_entry.code, attempt.site.offset,
            attempt.site.position, attempt.site.opname)


def _make_template(binding):
    receiver = binding.receiver
    receiver_template = None if receiver is None else _ReceiverTemplate(
        receiver.actual_body, receiver.operation, receiver.callable_use, receiver.callable_value,
        receiver.formal_body, receiver.formal_slot, receiver.formal_value, receiver.formal_name,
        receiver.observed.explicit_positional)
    return _SourcePortTemplate(binding.target.kind, binding.target.layout, binding.target.scope,
        binding.caller_code, binding.callee_code, binding.call, binding.caller_body,
        binding.callee_body, receiver_template, binding.arguments, binding.candidate,
        binding.conditions)


def _reuse_binding_template(template, attempt, caller_entry, callee_entry):
    _need(attempt.site.position is not None and attempt.site.opname in ("CALL", "CALL_KW")
          and template.call.site == attempt.site
          and template.caller_code.code == attempt.site.code
          and template.callee_code.code == attempt.dispatch.code == callee_entry.code
          and template.layout == attempt.dispatch.layout,
          "cached source-call template scope differs from this original occurrence")
    _need(callee_entry.parameters_complete
          and tuple(item.name for item in callee_entry.parameters) == attempt.dispatch.layout.parameters,
          "occurrence entry lacks the original complete function layout")
    if template.receiver is not None:
        _need(template.kind is PythonTargetKind.NORMALIZED_RECEIVER_FUNCTION
              and not attempt.arg0_missing and attempt.arg0 is not None
              and attempt.dispatch.layout.argcount >= template.receiver.explicit_positional + 1
              and callee_entry.parameters
              and callee_entry.parameters[0].ref == attempt.arg0,
              "current observed receiver does not satisfy the cached method layout")
        observed = BoundReceiver(ReceiverRole.IMPLICIT_CALL_RECEIVER, attempt.arg0,
            explicit_positional=template.receiver.explicit_positional,
            conditions=(ReceiverCondition.NO_INTERVENING_CALL_LAYOUT_MUTATION,))
        receiver = SourceReceiverPort(template.receiver.actual_body, template.receiver.operation,
            template.receiver.callable_use, template.receiver.callable_value,
            template.receiver.formal_body, template.receiver.formal_slot,
            template.receiver.formal_value, template.receiver.formal_name, observed)
        receiver_parameter_index, receiver_reference = 0, attempt.arg0
    else:
        _need(template.kind is PythonTargetKind.FUNCTION
              and attempt.dispatch.layout.argcount >= len(template.arguments),
              "current observed function layout differs from cached source call")
        observed, receiver = None, None
        receiver_parameter_index, receiver_reference = None, None
    target = PythonCallTarget(attempt.index, caller_entry.invocation, template.kind,
        attempt.dispatch.reference, attempt.dispatch.reference, attempt.dispatch.code,
        template.layout, observed,
        template.scope)
    entry = PythonEntryBinding(attempt.index, caller_entry.invocation, callee_entry.invocation,
        callee_entry.anchor.index, callee_entry.code, receiver_parameter_index, receiver_reference)
    binding = PythonSourcePortBinding(target, attempt.anchor, entry, callee_entry.anchor,
        attempt.anchor, callee_entry.anchor, template.caller_code, template.callee_code,
        template.call, template.caller_body, template.callee_body, receiver,
        template.arguments, template.candidate, template.conditions)
    return target, entry, binding


def _selected_binding(inputs, operand_metadata, boundary_index, template_cache, pid, attempt, handshake,
                      caller_entry, callee_entry, caller_row, callee_row, source_tree_cache):
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
    process_meta = next(item for item in operand_metadata if item.process_id == pid)
    _need(not process_meta.errors and not process_meta.io_failed
          and not process_meta.dropped_events and not process_meta.previous_profile,
          "operand process capture has errors, dropped events or previous profile")
    invocations = {attempt.invocation, callee_entry.invocation}
    code_keys = {caller_entry.code, callee_entry.code}
    boundary_index.check_interval(pid, invocations, code_keys, attempt.index, handshake.index)
    _need(attempt.site.position is not None and attempt.site.opname in ("CALL", "CALL_KW"),
          "captured CALL/CALL_KW site lacks the original source position/opcode")
    template_key = _call_template_key(attempt, caller_entry, callee_entry)
    template = template_cache.get(template_key)
    if template is not None:
        if hasattr(template_cache, "move_to_end"):
            template_cache.move_to_end(template_key)
        return _reuse_binding_template(template, attempt, caller_entry, callee_entry)
    caller = inputs.body(pid, caller_row)
    callee = inputs.body(pid, callee_row)
    _need(attempt.site.position is not None and attempt.site.opname in ("CALL", "CALL_KW")
          and attempt.site.code == caller.code_link.code
          and callee.code_link.code == callee_entry.code,
          "raw CALL site/CodeSourceLink scope differs")
    calls = [c for c in inputs.call(caller_row)
             if c.execution_owner == caller.definition.definition
             and _source_positions(c.source) == attempt.site.position]
    _need(len(calls) == 1, "original source inventory must identify one exact owner CALL")
    source_call, = calls
    call_node = _find_call(inputs.source_text(caller, source_tree_cache), source_call.source)
    _need(not any(isinstance(arg, __import__("ast").Starred) for arg in call_node.args)
          and all(item.arg is not None for item in call_node.keywords),
          "starred or double-starred source arguments are outside this ABI rule")
    _need(attempt.site.opname == ("CALL_KW" if call_node.keywords else "CALL"),
          "captured CALL opcode does not match the original source keyword shape")
    call_links = [link for link in caller.metadata.operation_links
        if link.source == source_call.source and link.opcode is Opcode.CALL
        and link.semantic_operation == source_call.semantic_operation]
    _need(len(call_links) == 1 and source_call.semantic_operation is not None,
          "one original core CALL OperationSource must match the source inventory link")
    call_link, = call_links
    op_map = {op.id: op for op in caller.graph.operations}
    use_map = {use.id: use for op in caller.graph.operations for use in op.uses}
    op = op_map[call_link.operation]
    actual_specs = [(ArgumentKind.POSITIONAL, None, node) for node in call_node.args]
    actual_specs.extend((ArgumentKind.KEYWORD, item.arg, item.value) for item in call_node.keywords)
    _need(op.terminator is not None and op.terminator.kind is TerminatorKind.INVOKE
          and len(op.invoke_arguments) == len(actual_specs) + 2,
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
    candidate_actual_links = [link for link in caller.metadata.use_links
        if link.operation == op.id and (link.role == "argument" or link.role.startswith("keyword:"))]
    actual_links = []
    for index, (kind, keyword, node) in enumerate(actual_specs):
        expected_role = "argument" if kind is ArgumentKind.POSITIONAL else "keyword:" + keyword
        expected_span = _span(node)
        matches = [link for link in candidate_actual_links
            if link.role == expected_role and _source_positions(link.source) == expected_span]
        _need(len(matches) == 1,
              "original caller Use/source link must uniquely identify each positional or keyword expression")
        actual_links.append(matches[0])
    actual_links = tuple(actual_links)
    _need(len(candidate_actual_links) == len(actual_links)
          and tuple(link.use for link in actual_links) == tuple(op.invoke_arguments[1:-1]),
          "original ordered positional/keyword Uses differ from the AST CALL")

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
    positional_parameters = tuple(parameter for parameter in signature.parameters
        if parameter.kind in (ParameterKind.POSITIONAL_ONLY, ParameterKind.POSITIONAL))
    keyword_names = {keyword.arg for keyword in call_node.keywords}
    is_attribute_call = isinstance(call_node.func, __import__("ast").Attribute)
    first_formal_reference_matches = (bool(positional_parameters) and bool(callee_entry.parameters)
        and callee_entry.parameters[0].name == positional_parameters[0].name
        and not attempt.arg0_missing and attempt.arg0 is not None
        and callee_entry.parameters[0].ref == attempt.arg0)
    legacy_fixed_receiver_shape = (is_attribute_call and not call_node.keywords
        and attempt.dispatch.layout.argcount == len(call_node.args) + 1)
    legacy_function_shape = (not call_node.keywords and attempt.site.opname == "CALL"
        and attempt.dispatch.layout.argcount == len(call_node.args))
    if legacy_fixed_receiver_shape:
        _need(first_formal_reference_matches,
              "fixed-arity attribute CALL receiver does not match the captured first formal")
        receiver_positional = len(call_node.args)
        target_kind = PythonTargetKind.NORMALIZED_RECEIVER_FUNCTION
    elif (is_attribute_call and not call_node.args and bool(positional_parameters)
          and positional_parameters[0].name not in keyword_names
          and positional_parameters[0].default_source is None
          and first_formal_reference_matches):
        receiver_positional = 0
        target_kind = PythonTargetKind.NORMALIZED_RECEIVER_FUNCTION
    elif (is_attribute_call and call_node.args and first_formal_reference_matches
          and attempt.dispatch.layout.argcount > len(call_node.args)):
        raise _NeedError("attribute call with positional actuals has unresolved receiver-versus-function ABI")
    elif legacy_function_shape:
        receiver_positional = None
        target_kind = PythonTargetKind.FUNCTION
    else:
        raise _NeedError("source CALL/function positional ABI remains outside the retained rule")

    if target_kind is PythonTargetKind.NORMALIZED_RECEIVER_FUNCTION:
        _need(attempt.dispatch.layout.argcount >= 1
              and tuple(item.name for item in signature.parameters) == attempt.dispatch.layout.parameters,
              "normalized receiver function layout lacks its first formal")
        observed = BoundReceiver(ReceiverRole.IMPLICIT_CALL_RECEIVER, attempt.arg0,
            explicit_positional=receiver_positional,
            conditions=(ReceiverCondition.NO_INTERVENING_CALL_LAYOUT_MUTATION,))
        receiver = SourceReceiverPort(caller.namespace, op.id, callee_use.id, callee_use.value,
            callee.namespace, signature.parameters[0].slot, callee.interface.parameters[0].value,
            signature.parameters[0].name, observed)
        receiver_formal = signature.parameters[0]
    else:
        receiver = None
        receiver_formal = None
    _need(not attempt.dispatch.layout.kwonlyargcount
          and not attempt.dispatch.layout.flags & (4 | 8)
          and signature.kind.value == "SYNC" and not signature.decorators,
          "variadic, keyword-only, decorated or suspended target remains outside this rule")
    if target_kind is PythonTargetKind.FUNCTION:
        args = tuple(CallArgument(i, link.source, kind, keyword=keyword, use=link.use)
                     for i, ((kind, keyword, _), link) in enumerate(zip(actual_specs, actual_links)))
        candidate = bind_call(signature, call=source_call.operation,
            target=callee.definition.definition, source=source_call.source, arguments=args)
        _need(candidate.status.value == "CONDITIONAL", "original source signature has no conditional explicit-argument binding")
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
        assigned = {signature.parameters[0].slot}
        if receiver_positional:
            _need(not call_node.keywords and receiver_positional == len(call_node.args),
                  "fixed-arity receiver route must preserve its ordered positional operands")
            for i, link in enumerate(actual_links):
                parameter_index = i + 1
                _need(parameter_index < len(signature.parameters),
                      "fixed-arity receiver route exceeds the original positional signature")
                parameter = signature.parameters[parameter_index]
                _need(parameter.kind in (ParameterKind.POSITIONAL_ONLY, ParameterKind.POSITIONAL),
                      "receiver positional route does not select an original positional formal")
                _need(parameter.slot not in assigned, "duplicate receiver-call positional route")
                assigned.add(parameter.slot)
                formal = callee.interface.parameters[parameter_index]
                route = ParameterBinding(parameter.slot, BindingOrigin.ARGUMENT, (i,))
                ports.append(SourceArgumentPort(i, caller.namespace, op.id, link.source, link.use,
                    use_map[link.use].value, callee.namespace, parameter.slot, formal.value,
                    parameter.name, route))
        else:
            _need(not call_node.args,
                  "default/keyword receiver route does not accept explicit positional operands")
            for i, ((kind, keyword, _), link) in enumerate(zip(actual_specs, actual_links)):
                _need(kind is ArgumentKind.KEYWORD,
                      "default/keyword receiver route accepts only explicit keyword operands")
                matches = [parameter for parameter in signature.parameters[1:]
                    if parameter.name == keyword and parameter.kind is ParameterKind.POSITIONAL]
                _need(len(matches) == 1, "receiver call keyword does not select one positional formal")
                parameter, = matches
                _need(parameter.slot not in assigned, "duplicate receiver-call keyword route")
                assigned.add(parameter.slot)
                formal_index = signature.parameters.index(parameter)
                formal = callee.interface.parameters[formal_index]
                route = ParameterBinding(parameter.slot, BindingOrigin.ARGUMENT, (i,))
                ports.append(SourceArgumentPort(i, caller.namespace, op.id, link.source, link.use,
                    use_map[link.use].value, callee.namespace, parameter.slot, formal.value,
                    parameter.name, route))
        for parameter in signature.parameters[1:]:
            if parameter.slot not in assigned:
                _need(parameter.default_source is not None,
                      "receiver call omits a required formal without a default declaration")
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
    template_cache[template_key] = _make_template(binding)
    while len(template_cache) > 512:
        template_cache.popitem(last=False)
    return target, entry, binding


@dataclass(frozen=True, slots=True)
class _RawCandidate:
    ordinal: int
    attempt: object
    handshake: object
    caller_entry: object
    callee_entry: object
    caller_row: dict
    callee_row: dict


@dataclass(frozen=True, slots=True)
class RetainedSourceCallPortBatch:
    model: PythonSourcePortModel
    report: dict


def _candidate_issue(exc):
    detail = str(exc).removeprefix("retained source-call ports: ")
    lowered = detail.lower()
    if isinstance(exc, _NeedError):
        if any(token in lowered for token in ("unsupported", "neither retained", "not supported")):
            category = "UNSUPPORTED_SOURCE_OR_ABI_FORMAT"
        elif any(token in lowered for token in ("gap intersects", "suspended", "variadic", "keyword-only",
                                                 "decorated", "outside the synchronous", "call site lacks")):
            category = "OBSERVATION_OR_ABI_SCOPE_BOUNDARY"
        elif any(token in lowered for token in ("differs", "mismatch", "duplicate", "conflicting")):
            category = "RECEIPT_OR_NAMESPACE_INCONSISTENCY"
        else:
            category = "MISSING_OR_UNRESOLVED_SOURCE_FACT"
    elif isinstance(exc, (OSError, gzip.BadGzipFile, EOFError)):
        category = "RETAINED_ARTIFACT_IO_OR_DECODE_FAILURE"
    else:
        category = "BUILDER_IMPLEMENTATION_EXCEPTION"
    return {"category": category, "exception_type": type(exc).__name__, "detail": detail}


class RetainedSourceCallPortSession:
    """Own one receipt-checked raw read and build bounded typed batches from it.

    The live ``CallOperandTrace`` and its original records stay in this object;
    only returned models and receipts are serializable. No proof owner is
    recreated from an older JSON artifact.
    """

    def __init__(self, *, source_report_path, bindings_path, expected_report_sha256,
            expected_bindings_sha256, trace_root=None, pid=None,
            max_candidate_pairs=512, body_limit=128_000_000,
            max_live_body_decoded_bytes=64_000_000):
        _need(max_candidate_pairs is None or type(max_candidate_pairs) is int and max_candidate_pairs > 0,
              "positive total direct-candidate ceiling or None required")
        self.inputs = _Inputs(source_report_path, bindings_path, expected_report_sha256,
                              expected_bindings_sha256, body_limit=body_limit,
                              max_live_body_decoded_bytes=max_live_body_decoded_bytes)
        self.captured_pid = self.inputs.process_id(pid)
        default_trace = self.inputs.report["attachment_capture_checks"][0]["trace_directory"]
        self.trace_root = Path(default_trace if trace_root is None else trace_root).absolute()
        _need(str(self.trace_root) == default_trace,
              "trace root must be the v4 report's exact capture")
        self.project_root = self.inputs.report["collection_metadata"][0]["project_root"]
        raw_budget = self.inputs.report["call_budget"]
        self.frame_budget = CallEdgeBudget(
            max_raw_bytes=raw_budget["max_raw_bytes"], max_lines=raw_budget["max_lines"],
            max_line_bytes=raw_budget["max_line_bytes"], max_processes=raw_budget["max_processes"],
            max_codes=raw_budget["max_codes"], max_events=raw_budget["max_events"],
            max_source_files=raw_budget["max_source_files"], max_source_bytes=raw_budget["max_source_bytes"],
            max_references=raw_budget["max_references"], max_path=raw_budget["max_path"])
        self.operand_budget = CallOperandBudget(max_raw_bytes=256_000_000, max_lines=1_000_000,
            max_line_bytes=2_000_000, max_processes=128, max_events=1_000_000,
            max_loads=1_000_000, max_references=2_000_000, max_metadata_bytes=2_000_000)
        started = time.monotonic()
        self.operands = read_call_operands(self.trace_root, self.project_root,
            budget=self.operand_budget, frame_budget=self.frame_budget)
        self.raw_reader_seconds = time.monotonic() - started
        self.entries = self.operands.entries
        self.exits = self.operands.exits
        self.attempts = self.operands.attempts
        self.handshakes = self.operands.handshakes
        self.instructions = self.operands.instructions
        self._validate_raw_receipts()
        self.denominators = {
            "frame_entries": len(self.entries), "frame_exits": len(self.exits),
            "attempts": len(self.attempts), "handshakes": len(self.handshakes),
            "operand_instructions": len(self.instructions), "operand_events": len(self.operands.events),
            "operand_gaps": sum(type(item) in (OperandGap, OperandScopedGap) for item in self.operands.events),
            "code_captures": len(self.operands.frame_scan.captures),
        }
        self.captures = {(item.process_id, item.code.key): item
                         for item in self.operands.frame_scan.captures}
        self.entries_by_invocation = {item.invocation: item for item in self.entries}
        handshakes = defaultdict(list)
        for item in self.handshakes:
            handshakes[item.process_id, item.attempt_index].append(item)
        self.handshakes_by_attempt = dict(handshakes)
        self.boundary_index = _OperandBoundaryIndex(self.operands)
        self.candidates, self.candidate_funnel = self._make_candidates()
        self.total_direct_candidates = len(self.candidates)
        self.candidate_ordinal_by_attempt = {item.attempt.index: item.ordinal for item in self.candidates}
        self.max_candidate_pairs = (self.total_direct_candidates if max_candidate_pairs is None
                                     else min(max_candidate_pairs, self.total_direct_candidates))
        self.cursor = 0
        self.batch_number = 0
        self.selected_attempt_indices = []
        self.cumulative_candidate_issues = Counter()
        self.candidate_outcomes = {}
        self.source_tree_cache = OrderedDict()
        self.static_template_cache = OrderedDict()
        self.producer_sources = self._producer_stamps()

    def _validate_raw_receipts(self):
        report_files = sorted(_receipt_row(row) for row in self.inputs.report["trace_files"])
        current_files = sorted((f.process_id, f.family, f.path, f.raw_sha256, f.raw_bytes, f.lines)
                               for f in self.operands.frame_scan.files)
        _need(report_files == current_files
              and list(self.operands.frame_scan.metadata) == self.inputs.report["collection_metadata"]
              and len(self.entries) == self.inputs.report["summary"]["invocations"]
              and len(self.exits) == self.inputs.report["summary"]["exits"]
              and len(self.operands.frame_scan.captures) == self.inputs.report["summary"]["code_captures"],
              "fresh raw frame scan differs from original v4 receipt/denominators")
        grouped = Counter((entry.invocation.process_id, entry.code) for entry in self.entries)
        rows = self.inputs.by_group
        _need(set(grouped) == set(rows)
              and all(grouped[key] == row["entered_invocations"] for key, row in rows.items()),
              "fresh frame-entry code groups differ from retained v4 source denominator")

    def _make_candidates(self):
        candidates, funnel = [], Counter()
        rows = self.inputs.by_group
        for attempt in self.attempts:
            if attempt.process_id != self.captured_pid:
                continue
            funnel["attempts_in_process"] += 1
            matches = self.handshakes_by_attempt.get((attempt.process_id, attempt.index), ())
            if len(matches) != 1:
                funnel["missing_or_ambiguous_entry_handshake"] += 1
                continue
            handshake, = matches
            caller_entry = self.entries_by_invocation.get(attempt.invocation)
            callee_entry = self.entries_by_invocation.get(handshake.invocation)
            if caller_entry is None or callee_entry is None:
                funnel["missing_frame_entry_record"] += 1
                continue
            caller_row = rows.get((self.captured_pid, caller_entry.code))
            callee_row = rows.get((self.captured_pid, callee_entry.code))
            if (caller_row is None or callee_row is None
                    or caller_row.get("status") != "BODY_LINKED_REUSED_WITNESS"
                    or callee_row.get("status") != "BODY_LINKED_REUSED_WITNESS"):
                funnel["source_body_not_linked_in_retained_catalog"] += 1
                continue
            candidates.append(_RawCandidate(len(candidates), attempt, handshake,
                caller_entry, callee_entry, caller_row, callee_row))
        funnel["direct_body_linked_candidates"] = len(candidates)
        return tuple(candidates), dict(sorted(funnel.items()))

    def _producer_stamps(self):
        result = {}
        for name, path in (("retained_source_call_ports.py", Path(__file__)),
                           ("source_return_bindings.py", Path(__file__).with_name("source_return_bindings.py"))):
            result[name] = {"path": str(path), "sha256": sha256(path.read_bytes()).hexdigest()}
        return result

    def _raw_files(self):
        return {
            "frame_files": [encode_file(f) for f in self.operands.frame_scan.files],
            "operand_files": [encode_file(f) for f in self.operands.files],
        }

    def _candidate_limit_scope(self):
        return {
            "total_direct_body_linked_candidates": self.total_direct_candidates,
            "bounded_candidate_limit": self.max_candidate_pairs,
            "candidate_limit_is_complete": self.max_candidate_pairs == self.total_direct_candidates,
            "next_candidate_ordinal": self.cursor,
            "remaining_direct_candidates_total": max(0, self.total_direct_candidates - self.cursor),
            "remaining_candidate_attempt_index_range": (
                None if self.cursor >= self.total_direct_candidates
                else [self.candidates[self.cursor].attempt.index,
                      self.candidates[self.total_direct_candidates - 1].attempt.index]),
            "remaining_outside_session_candidate_bound": max(
                0, self.total_direct_candidates - self.max_candidate_pairs),
        }

    def build_batch(self, *, max_selected_calls=32, max_candidate_pairs=64):
        _need(type(max_selected_calls) is int and max_selected_calls > 0,
              "positive per-batch selected-call ceiling required")
        _need(max_candidate_pairs is None or type(max_candidate_pairs) is int and max_candidate_pairs > 0,
              "positive per-batch candidate ceiling or None required")
        start = self.cursor
        stop = self.max_candidate_pairs if max_candidate_pairs is None else min(
            self.max_candidate_pairs, start + max_candidate_pairs)
        targets, entries, bindings = [], [], []
        selected_indices, candidate_issues, examined = [], [], []
        batch_outcomes = {}
        cursor = start
        while cursor < stop and len(bindings) < max_selected_calls:
            candidate = self.candidates[cursor]
            cursor += 1
            examined.append(candidate)
            try:
                for group_row, entry_record in ((candidate.caller_row, candidate.caller_entry),
                                                (candidate.callee_row, candidate.callee_entry)):
                    capture = self.captures.get((self.captured_pid, entry_record.code))
                    _need(capture is not None and encode(capture) == group_row["code_capture"],
                          "current complete captured descriptor differs from the retained source group")
                target, entry, binding = _selected_binding(self.inputs, self.operands.metadata,
                    self.boundary_index, self.static_template_cache, self.captured_pid,
                    candidate.attempt, candidate.handshake, candidate.caller_entry,
                    candidate.callee_entry, candidate.caller_row, candidate.callee_row,
                    self.source_tree_cache)
                _need(candidate.attempt.index not in self.candidate_outcomes
                      and candidate.attempt.index not in batch_outcomes,
                      "duplicate selected raw attempt")
                targets.append(target); entries.append(entry); bindings.append(binding)
                selected_indices.append(candidate.attempt.index)
                batch_outcomes[candidate.attempt.index] = {
                    "status": "CONNECTED", "candidate_ordinal": candidate.ordinal,
                    "batch_index": self.batch_number,
                }
            except Exception as exc:
                issue = {"candidate_ordinal": candidate.ordinal,
                    "attempt_index": candidate.attempt.index, **_candidate_issue(exc)}
                candidate_issues.append(issue)
                batch_outcomes[candidate.attempt.index] = {
                    "status": "CANDIDATE_ISSUE", **issue,
                }
        operand_file = next(f for f in self.operands.files
                            if f.process_id == self.captured_pid and f.family == "operands")
        graph = ObservedPythonCallGraph(operand_file.path, operand_file.raw_sha256,
            tuple(targets), tuple(entries), (),
            tuple(binding.attempt for binding in bindings), tuple(binding.entry_anchor for binding in bindings))
        model = PythonSourcePortModel(graph, tuple(bindings), ())
        processed = len(examined)
        if processed:
            self.cursor = cursor
            self.selected_attempt_indices.extend(selected_indices)
            self.batch_number += 1
            self.candidate_outcomes.update(batch_outcomes)
            for issue in candidate_issues:
                self.cumulative_candidate_issues[(issue["category"], issue["exception_type"], issue["detail"])] += 1
        candidate_ordinals = [item.ordinal for item in examined]
        attempt_indices = [item.attempt.index for item in examined]
        scope = {
            "candidate_ordinal_start": start,
            "candidate_ordinal_end_exclusive": cursor,
            "candidate_ordinals": candidate_ordinals,
            "attempt_indices_examined": attempt_indices,
            "selected_attempt_indices": selected_indices,
            "accepted_attempt_indices": selected_indices,
            "missing_attempt_indices": [issue["attempt_index"] for issue in candidate_issues],
            "candidate_issue_categories": [
                {"attempt_index": issue["attempt_index"], "category": issue["category"],
                 "exception_type": issue["exception_type"]}
                for issue in candidate_issues],
            "max_selected_calls": max_selected_calls,
            "max_candidate_pairs_this_batch": max_candidate_pairs,
            "total_direct_body_linked_candidates": self.total_direct_candidates,
            "bounded_candidate_limit": self.max_candidate_pairs,
            "candidate_limit_is_complete": self.max_candidate_pairs == self.total_direct_candidates,
            "remaining_direct_candidates_total": max(0, self.total_direct_candidates - cursor),
            "remaining_candidate_attempt_index_range": (
                None if cursor >= self.total_direct_candidates
                else [self.candidates[cursor].attempt.index,
                      self.candidates[self.total_direct_candidates - 1].attempt.index]),
            "remaining_outside_session_candidate_bound": max(
                0, self.total_direct_candidates - self.max_candidate_pairs),
        }
        report = {
            "schema": "scar.retained-source-call-port-batch",
            "schema_version": 1,
            "status": "SELECTED_PORTS_BUILT" if bindings else (
                "CANDIDATES_EXAMINED_NO_LINKS" if processed else "NO_CANDIDATES_REMAIN"),
            "batch_index": self.batch_number - (1 if processed else 0),
            "source_report": {"path": str(self.inputs.report_path),
                "sha256": self.inputs.report_sha256,
                "bytes": self.inputs.report_path.stat().st_size, "schema_version": 4},
            "bindings": {"path": str(self.inputs.bindings_path), "sha256": self.inputs.binding_sha256,
                "bytes": self.inputs.binding_bytes, "schema_version": 4},
            "capture": {"trace_root": str(self.trace_root), "process_id": self.captured_pid,
                "project_root": self.project_root, **self.denominators,
                "raw_reader_seconds": self.raw_reader_seconds, **self._raw_files()},
            "candidate_funnel": self.candidate_funnel,
            "candidate_scope": scope,
            "candidate_issues": candidate_issues,
            "model_summary": model.summary(),
            "cache_state": self.cache_state(),
            "claims": {"actual_formal_routing_established": False,
                "normal_return_selected": False, "runtime_callable_environment_established": False,
                "receiver_identity_established": False, "content_or_effect_equivalence_established": False,
                "whole_program_graph_established": False, "full_attempt_denominator_connected": False,
                "transformation_authorized": False},
        }
        self._last_batch_report = report
        return RetainedSourceCallPortBatch(model, report)

    def cache_state(self):
        return {"inputs": dict(sorted(self.inputs.stats.items())),
            "body_program_cache_entries": len(self.inputs._program_cache),
            "body_program_cache_live_decoded_bytes": self.inputs._program_cache_decoded_bytes,
            "body_program_cache_limits": {"entries": self.inputs.max_live_body_programs,
                "decoded_bytes": self.inputs.max_live_body_decoded_bytes},
            "body_view_cache_entries": len(self.inputs._body_cache),
            "body_view_cache_limit": self.inputs.max_live_body_views,
            "inventory_partition_cache_entries": sum(key != "manifest" for key in self.inputs._file_cache),
            "inventory_partition_cache_limit": self.inputs.max_inventory_partitions,
            "source_call_partition_cache_entries": len(self.inputs._calls),
            "source_call_partition_cache_limit": self.inputs.max_call_partitions,
            "static_source_call_templates": len(self.static_template_cache),
            "source_syntax_trees": len(self.source_tree_cache)}

    def inspect_attempt(self, attempt_index):
        _need(type(attempt_index) is int and attempt_index >= 1, "positive original attempt index required")
        candidate_ordinal = self.candidate_ordinal_by_attempt.get(attempt_index)
        if candidate_ordinal is None:
            return {"attempt_index": attempt_index, "status": "NOT_A_DIRECT_BODY_LINKED_CANDIDATE"}
        result = self.candidate_outcomes.get(attempt_index)
        if result is not None:
            return {"attempt_index": attempt_index, **result}
        return {"attempt_index": attempt_index,
            "candidate_ordinal": candidate_ordinal,
            "status": "PENDING_IN_RETAINED_SESSION" if candidate_ordinal >= self.cursor
                      else "OUTCOME_NOT_RECORDED"}

    def summary(self):
        return {
            "schema": "scar.retained-source-call-port-session-summary",
            "schema_version": 1,
            "process_id": self.captured_pid,
            "trace_root": str(self.trace_root),
            "source_report": {"path": str(self.inputs.report_path),
                "sha256": self.inputs.report_sha256, "schema_version": 4},
            "bindings": {"path": str(self.inputs.bindings_path),
                "sha256": self.inputs.binding_sha256, "bytes": self.inputs.binding_bytes,
                "schema_version": 4},
            "capture_denominators": self.denominators,
            "raw_reader_seconds": self.raw_reader_seconds,
            "candidate_funnel": self.candidate_funnel,
            "candidate_scope": self._candidate_limit_scope(),
            "batches_emitted": self.batch_number,
            "selected_attempt_indices": list(self.selected_attempt_indices),
            "candidate_issues": [
                {"category": key[0], "exception_type": key[1], "detail": key[2], "count": count}
                for key, count in sorted(self.cumulative_candidate_issues.items())],
            "cache_state": self.cache_state(),
            "producer_sources": self.producer_sources,
            "full_candidate_coverage": self.cursor >= self.total_direct_candidates,
            "full_attempt_coverage": False,
        }


def build_retained_source_call_ports(*, source_report_path, bindings_path,
        expected_report_sha256, expected_bindings_sha256, trace_root=None,
        pid=None, max_selected_calls=1, build_report_path=None,
        body_limit=128_000_000):
    """Compatibility one-batch wrapper; use RetainedSourceCallPortSession for batching."""
    session = RetainedSourceCallPortSession(source_report_path=source_report_path,
        bindings_path=bindings_path, expected_report_sha256=expected_report_sha256,
        expected_bindings_sha256=expected_bindings_sha256, trace_root=trace_root,
        pid=pid, max_candidate_pairs=None, body_limit=body_limit)
    batch = session.build_batch(max_selected_calls=max_selected_calls, max_candidate_pairs=None)
    if build_report_path is not None:
        report = {**batch.report, "session": session.summary(),
            "limitations": [
                "selected ports are conditional source-call interfaces, not runtime callable or identity proof",
                "normal return/world views remain unselected until a SourceReturnSession query",
                "attempts outside this selected batch are not materialized",
            ]}
        out = Path(build_report_path).absolute()
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("xb") as stream:
            stream.write(_canonical(report) + b"\n")
    return batch.model

def encode_file(item):
    return {"path": item.path, "family": item.family, "process_id": item.process_id,
            "raw_sha256": item.raw_sha256, "raw_bytes": item.raw_bytes, "lines": item.lines}


__all__ = ["build_retained_source_call_ports"]
