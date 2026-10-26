"""Bounded retained source-context queries over separately qualified models.

Only the owned builder scans the completed association stream, once to EOF.
Queries read checksum-bound derived chunks and selected original EEG records.
Retained ancestry is not a direct call, object identity, content or completion
proof. Historical SCAR collector execution bytes remain an explicit assumption.
"""
from __future__ import annotations

from bisect import bisect_left
from collections import Counter
from dataclasses import dataclass, fields
from enum import Enum
import gzip
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import re
import time

from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.program.call_edges import InvocationKey
from scar.ir.program.source_references import SourceDefinitionReference
from scar.ir.record_codec import decode, encode, loads
from scar.ir.execution.ids import OperationOccurrenceID
from scar.ir.execution.model import OccurrenceEvidenceBinding
from scar.ir.execution.fragment_relations import QualifiedOccurrenceRef


SCHEMA = "scar.source-native-context-navigation"
VERSION = 1
PROFILE = "PINNED_TORCH_NATIVE_PORT_HELD_SUBSET_V2"
HISTORICAL_ASSUMPTION = "HISTORICAL_SCAR_COLLECTOR_EXECUTION_SOURCE_UNRECORDED"
_SHA = re.compile(r"[0-9a-f]{64}")
_NODE = re.compile(r"#/nodes/([0-9]+)")


def _need(ok, message):
    if not ok:
        raise ValueError("source/native context: " + message)


def _json(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False,
                       separators=(",", ":"), allow_nan=False) + "\n").encode()


def _positive(value):
    return type(value) is int and value > 0


@dataclass(frozen=True, slots=True)
class NativeContextInputs:
    source_report: ProviderArtifact
    dispatch_source_report: ProviderArtifact
    native_final_batch_report: ProviderArtifact
    original_native_manifest: ProviderArtifact
    source_coordinates: ProviderArtifact
    native_coordinates: ProviderArtifact
    scope_ledger_manifest: ProviderArtifact
    scope_revision: str

    def __post_init__(self):
        for f in fields(self):
            value = getattr(self, f.name)
            if f.name != "scope_revision":
                _need(type(value) is ProviderArtifact, "inputs require exact artifact records")
                value.__post_init__()
        _need(type(self.scope_revision) is str and re.fullmatch(r"scope_revision:[0-9a-f]{64}", self.scope_revision),
              "invalid original ledger revision")


@dataclass(frozen=True, slots=True)
class NavigationBudget:
    max_decoded_bytes: int = 1_000_000_000
    max_stored_bytes: int = 256_000_000
    max_output_bytes: int = 256_000_000
    max_rows: int = 200_000
    max_chunks: int = 1000
    max_record_bytes: int = 1_000_000
    max_metadata_bytes: int = 32_000_000
    max_chunk_bytes: int = 8_000_000
    max_chunk_rows: int = 1000
    max_seconds: int = 120

    def __post_init__(self):
        _need(all(_positive(getattr(self, f.name)) for f in fields(self)), "invalid navigation budget")
        _need(self.max_chunk_bytes <= 8_000_000 and self.max_chunk_rows <= 1000
              and self.max_record_bytes <= self.max_chunk_bytes, "navigation hard bounds exceeded")


@dataclass(frozen=True, slots=True)
class NativeContextQueryBudget:
    max_decoded_bytes: int = 64_000_000
    max_stored_bytes: int = 64_000_000
    max_metadata_bytes: int = 32_000_000
    max_record_bytes: int = 1_000_000
    max_index_chunks: int = 2
    max_data_chunks: int = 4
    max_archive_chunks: int = 2
    max_seconds: int = 10

    def __post_init__(self):
        _need(all(_positive(getattr(self, f.name)) for f in fields(self)), "invalid query budget")
        _need(self.max_index_chunks <= 2 and self.max_data_chunks <= 4 and self.max_archive_chunks <= 2,
              "query hard chunk bounds exceeded")


class NativeContextStatus(str, Enum):
    RETAINED_CONTEXT = "RETAINED_CONTEXT"
    CONTEXT_UNRESOLVED = "CONTEXT_UNRESOLVED"
    NATIVE_FRONTIER = "NATIVE_FRONTIER"
    SEQUENCE_NOT_OBSERVED = "SEQUENCE_NOT_OBSERVED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"


class ContextRelationship(str, Enum):
    RETAINED_SOURCE_CONTEXT = "RETAINED_SOURCE_CONTEXT"


@dataclass(frozen=True, slots=True)
class SourceAssociationRef:
    declaration: ProviderFactReference
    original_stream_uri: str
    line: int
    line_sha256: str

    def __post_init__(self):
        _need(type(self.declaration) is ProviderFactReference and _positive(self.line)
              and type(self.line_sha256) is str and _SHA.fullmatch(self.line_sha256), "invalid source row reference")
        self.declaration.__post_init__()
        _path(self.original_stream_uri)


@dataclass(frozen=True, slots=True)
class RetainedSourceContext:
    phase: str
    association: SourceAssociationRef
    invocation: InvocationKey | None
    definition: SourceDefinitionReference | None
    invocation_fact: ProviderFactReference | None
    binding_fact: ProviderFactReference | None
    # Exact fields of the retained association, not new body/activation IDs.
    namespace_field: str | None
    activation_fact: ProviderFactReference | None


@dataclass(frozen=True, slots=True)
class NativeContextResult:
    navigation: ProviderArtifact
    inputs: NativeContextInputs
    scope_revision: str
    sequence: int
    status: NativeContextStatus
    relationship: ContextRelationship | None
    source_contexts: tuple[RetainedSourceContext, ...]
    native_facts: tuple[ProviderFactReference, ...]
    invoke: QualifiedOccurrenceRef | None
    normal_return: QualifiedOccurrenceRef | None
    frontiers: tuple[str, ...]
    assumptions: tuple[str, ...]
    cursor: str | None
    costs: dict

    def __post_init__(self):
        _need(self.scope_revision == self.inputs.scope_revision, "result original scope differs")
        _need((self.relationship is ContextRelationship.RETAINED_SOURCE_CONTEXT)
              == (self.status is NativeContextStatus.RETAINED_CONTEXT), "frontier cannot assert a relationship")


class _BudgetExceeded(Exception):
    pass


class _Meter:
    def __init__(self, limits):
        limits.__post_init__()
        self.limits, self.start, self.costs, self.phase = limits, time.monotonic(), Counter(), "metadata"

    def charge(self, key, count):
        if time.monotonic() - self.start > self.limits.max_seconds:
            raise _BudgetExceeded(self.phase + ":wall")
        maximum = getattr(self.limits, "max_" + key, None)
        if maximum is not None and self.costs[key] + count > maximum:
            raise _BudgetExceeded(self.phase + ":" + key)
        self.costs[key] += count

    def record_read(self, key, count):
        # A bounded decoder may return one receipt-check sentinel byte. Keep
        # actual returned bytes even when its budget or wall check then fails.
        self.costs[key] += count
        self.charge(key, 0)


def _path(uri):
    p = Path(uri)
    _need(p.is_absolute() and p.resolve() == p and not p.is_symlink(), "path is not original/canonical")
    return p


def _raw(artifact, meter, *, limit=None):
    artifact.__post_init__()
    maximum = meter.limits.max_metadata_bytes if limit is None else limit
    if artifact.size_bytes > maximum:
        raise _BudgetExceeded(meter.phase + ":artifact_bytes")
    meter.charge("stored_bytes", artifact.size_bytes)
    meter.charge("decoded_bytes", artifact.size_bytes)
    path = _path(artifact.uri)
    _need(path.is_file() and path.stat().st_size == artifact.size_bytes, "artifact stored size mismatch")
    with path.open("rb") as stream:
        raw = stream.read(artifact.size_bytes + 1)
    _need(len(raw) == artifact.size_bytes and sha256(raw).hexdigest() == artifact.sha256, "artifact SHA mismatch")
    return raw


def _document(artifact, meter):
    value = loads(_raw(artifact, meter).decode())
    _need(type(value) is dict, "root must be a JSON object")
    return value


def _artifact(path, raw, schema):
    return ProviderArtifact(str(Path(path).absolute()), sha256(raw).hexdigest(), len(raw), schema)


def _child(root, name):
    p = Path(name)
    _need(not p.is_absolute() and ".." not in p.parts and len(p.parts) == 1, "unsafe declared stream path")
    return _path(str(Path(root).parent / p))


def _run(doc):
    return doc["run"]["id"]["value"]


class _Roots:
    def __init__(self, inputs, meter):
        from scar.ir.modeling_scope_codec import from_dict
        inputs.__post_init__()
        self.inputs = inputs
        docs = {f.name: _document(getattr(inputs, f.name), meter) for f in fields(inputs) if f.name != "scope_revision"}
        self.source, self.dispatch, self.native = (docs[k] for k in
            ("source_report", "dispatch_source_report", "native_final_batch_report"))
        s, d, n = self.source, self.dispatch, self.native
        _need(s.get("schema") == "scar.source-invocations" and s.get("schema_version") == 3
              and d.get("schema") == "scar.dispatch-source-associations" and d.get("schema_version") == 3,
              "source root profile mismatch")
        _need(s.get("current_capture_raw_scan_verified") is True
              and s.get("old_capture_dynamic_facts_used_for_current_run") is False
              and s.get("transformation_authorized") is False,
              "source publication profile lacks its retained current-scan contract")
        _need(n.get("schema") == "scar.native-capture-batch" and n.get("schema_version") == 2
              and n.get("profile") == PROFILE and n.get("status") in
              ("SOURCE_DOMAIN_ACCOUNTED_WITH_PORT_GAPS", "OPEN_SOURCE_DOMAIN_MISMATCH")
              and n.get("unvisited_actual_groups") == 0, "final native batch root required; partial roots are rejected")
        _need(d["source_report"] == encode(inputs.source_report), "dispatch source report root differs")
        for key, declaration, schema in (("source_bindings", "bindings", "scar.source-invocation-bindings"),
                                         ("source_invocations", "invocations", "scar.source-invocations.events.v3")):
            desc = s[declaration]
            expected = ProviderArtifact(str(_child(inputs.source_report.uri, desc["path"])),
                                        desc["raw_sha256"], desc["raw_bytes"], schema)
            _need(d[key] == encode(expected), "source report endpoint declaration differs")
        _need(d["coordinate_binding"] == s["coordinate_binding"] == encode(inputs.source_coordinates)
              and n["coordinates"] == encode(inputs.native_coordinates), "coordinate artifact identity differs")
        sc, nc = docs["source_coordinates"], docs["native_coordinates"]
        _need(sc.get("schema") == nc.get("schema") == "scar.capture-coordinates"
              and sc.get("schema_version") == nc.get("schema_version") == 1
              and sc["run"] == nc["run"] == s["run"] == d["run"]
              and n["run"] == _run(sc) and sc["target_process"] == nc["target_process"], "Run/process roots differ")
        self.run, self.process = _run(sc), sc["target_process"]
        processes = [p for p in sc["processes"] if p["id"] == self.process]
        native_processes = [p for p in nc["processes"] if p["id"] == self.process]
        _need(len(processes) == 1 and processes == native_processes and _positive(processes[0]["pid"])
              and processes[0]["run"] == sc["run"]["id"], "target process absent/ambiguous")
        self.pid = processes[0]["pid"]
        sd, nd = sc["dispatch_collector_declaration"], nc["dispatch_collector_declaration"]
        _need(sd == nd and sd["process_id"] == self.pid and re.fullmatch(r"[0-9a-f]{32}", sd["nonce"]),
              "dispatch lifecycle declaration differs")
        self.nonce = sd["nonce"]
        self.members = {}
        for schema in ("scar.dispatch-observation.events.v1", "pytorch.execution-trace.v1", "pytorch.kineto.chrome-trace.v1"):
            a = [m["artifact"] for m in sc["membership"] if m["artifact"]["schema"] == schema]
            b = [m["artifact"] for m in nc["membership"] if m["artifact"]["schema"] == schema]
            _need(len(a) == len(b) == 1 and a == b, "original provider member differs/ambiguous")
            self.members[schema] = decode(ProviderArtifact, a[0])
        dispatch = self.members["scar.dispatch-observation.events.v1"]
        _need((sd["file"]["path"], sd["file"]["raw_sha256"], sd["file"]["raw_bytes"])
              == (dispatch.uri, dispatch.sha256, dispatch.size_bytes), "dispatch declaration differs from original member")
        original = inputs.original_native_manifest
        _need(n["source_manifest"] == {"path": original.uri, "physical_sha256": original.sha256,
                                      "physical_bytes": original.size_bytes}, "original native namespace root differs")
        bundle = docs["original_native_manifest"]
        _need(bundle.get("schema") == "scar.partitioned-ir-bundle" and bundle.get("schema_version") == 1
              and bundle.get("status") == "PUBLISHED", "unsupported original EEG manifest")
        ledger = docs["scope_ledger_manifest"]
        _need(ledger.get("schema") == "scar.partitioned-modeling-scope-ledger" and ledger.get("schema_version") == 2
              and ledger.get("status") == "PUBLISHED", "original scope ledger root mismatch")
        scope = from_dict(ledger["scope"])
        _need(scope.revision == inputs.scope_revision and scope.run.value == self.run,
              "original ledger scope/Run differs")
        bound = set()
        def collect(value):
            if type(value) is dict:
                if {"uri", "sha256", "size_bytes", "schema"} <= value.keys():
                    bound.add((value["uri"], value["sha256"], value["size_bytes"], value["schema"]))
                for child in value.values(): collect(child)
            elif type(value) is list:
                for child in value: collect(child)
        collect(ledger["scope"])
        _need(all((a.uri, a.sha256, a.size_bytes, a.schema) in bound
                  for a in (inputs.source_report, inputs.original_native_manifest)), "original scope lacks original input roots")
        inventories = {ref.artifact for obs in scope.observability if obs.domain.value == "SOURCE_DEFINITIONS"
                       for ref in obs.sources if ref.artifact.original.schema == "scar.partitioned-program-inventory"}
        _need(len(inventories) == 1, "original source inventory namespace absent/ambiguous")
        inventory = next(iter(inventories))
        _need(s["inventory"] == {"path": inventory.original.uri, "raw_sha256": inventory.original.sha256,
              "raw_bytes": inventory.original.size_bytes, "decoded_bytes": inventory.decoded_bytes},
              "source report original inventory namespace differs")
        self.eto = self.members["pytorch.execution-trace.v1"]
        self.native_scope = "native:" + sha256(_json({"eto": self.eto.sha256,
            "kineto": self.members["pytorch.kineto.chrome-trace.v1"].sha256,
            "revision": "cf30153c4c131c8164ee7798e5022d810682e2cb", "pid": self.pid}).rstrip(b"\n")).hexdigest()
        _need(sd.get("provider_revision") == "cf30153c4c131c8164ee7798e5022d810682e2cb", "provider ABI differs")
        self.sequences = n["actual_sequence_ids"]
        _need(type(self.sequences) is list and all(_positive(x) for x in self.sequences)
              and self.sequences == sorted(set(self.sequences))
              and len(self.sequences) == n["enumerated_dispatch_groups"], "actual native sequence denominator differs")
        self.association_path = _child(inputs.dispatch_source_report.uri, d["observations"]["path"])
        self.inventory_artifact = decode(ProviderArtifact, n["dispatch_inventory"])
        self.inventory = _document(self.inventory_artifact, meter)
        t = self.inventory
        _need(t.get("schema") == "scar.native-capture-table-chunks" and t.get("schema_version") == 1
              and t.get("row_schema_version") == 2 and t.get("profile") == PROFILE
              and t.get("rows") == len(self.sequences), "native inventory profile/denominator differs")
        ordinal = 0
        for descriptor in t["chunks"]:
            _need(descriptor["first_row_ordinal"] == ordinal and _positive(descriptor["rows"])
                  and descriptor["last_row_ordinal"] == ordinal + descriptor["rows"] - 1,
                  "native inventory chunk ordinal differs")
            decode(ProviderArtifact, descriptor["artifact"])
            ordinal += descriptor["rows"]
        _need(ordinal == t["rows"], "native inventory chunk denominator differs")

    def source_row(self, row, sequence=None):
        _need(type(row) is dict and _positive(row.get("sequence")) and row.get("phase") in ("span", "output")
              and (sequence is None or sequence == row["sequence"])
              and row.get("relationship") == "RETAINED_ANCESTOR_CONTEXT"
              and row.get("direct_callsite_established") is False, "source association sequence/phase/relationship differs")
        fact = decode(ProviderFactReference, row["marker_reference"])
        _need(fact.artifact == self.eto and _NODE.fullmatch(fact.locator), "source marker ordinal/artifact differs")
        _need(re.fullmatch(r"opinst:" + re.escape(self.native_scope) + r":eto:[1-9][0-9]*", row["marker_instance"]),
              "source marker instance namespace differs")
        invocation = None if row.get("invocation") is None else decode(InvocationKey, row["invocation"])
        if invocation is not None:
            _need(invocation.process_id == self.pid, "source invocation process differs")
            for key, root in (("source_invocation_reference", "source_invocations"), ("source_binding_reference", "source_bindings")):
                ref = decode(ProviderFactReference, row[key])
                _need(encode(ref.artifact) == self.dispatch[root], "source endpoint original artifact differs")
            _need(re.fullmatch(r"#/lines/[1-9][0-9]*", row["source_invocation_reference"]["locator"])
                  and re.fullmatch(r"#/bindings/[0-9]+", row["source_binding_reference"]["locator"])
                  and _SHA.fullmatch(row["source_invocation_line_sha256"]), "source endpoint locator/hash differs")
        if row.get("definition") is not None:
            definition = decode(SourceDefinitionReference, row["definition"])
            if row.get("body") is not None:
                namespace = row["body"]["namespace"]
                _need(row.get("region_namespace") == namespace
                      and namespace["body"]["definition"] == encode(definition.definition), "source body namespace differs")
        if row.get("region_activation_reference") is not None:
            ref = row["region_activation_reference"]
            _need(row.get("region_activation") is not None
                  and ref["artifact"] == self.dispatch["source_invocations"]
                  and ref["locator"] == row["source_invocation_reference"]["locator"] + "/region_activation",
                  "source activation original reference differs")
        for key in ("frontiers", "source_frontiers", "source_interface_frontiers"):
            _need(type(row.get(key, [])) is list and all(type(v) is str for v in row.get(key, [])), "source frontier inventory differs")
        return row


def _write(path, raw):
    with Path(path).open("xb") as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())


class _Sink:
    def __init__(self, root, family, meter):
        self.root, self.family, self.meter = root, family, meter
        (root / family).mkdir()
        self.descriptors, self.pending, self.size, self.total = [], [], 0, 0

    def add(self, raw):
        b = self.meter.limits
        _need(raw.endswith(b"\n") and len(raw) <= b.max_record_bytes, "transport record bound exceeded")
        self.meter.charge("rows", 1)
        if self.pending and (self.size + len(raw) > b.max_chunk_bytes or len(self.pending) == b.max_chunk_rows):
            self.close()
        result = {"chunk": len(self.descriptors), "line": len(self.pending), "sha256": sha256(raw).hexdigest()}
        self.pending.append(raw); self.size += len(raw); self.total += 1
        return result

    def close(self):
        if not self.pending: return
        raw = b"".join(self.pending); stored = gzip.compress(raw, mtime=0)
        self.meter.charge("chunks", 1)
        self.meter.charge("output_bytes", len(stored))
        uri = self.family + "/" + str(len(self.descriptors)).zfill(6) + ".jsonl.gz"
        _write(self.root / uri, stored)
        self.descriptors.append({"uri": uri, "rows": len(self.pending), "stored_bytes": len(stored),
            "stored_sha256": sha256(stored).hexdigest(), "decoded_bytes": len(raw),
            "decoded_sha256": sha256(raw).hexdigest()})
        self.pending, self.size = [], 0


class _PhysicalReader:
    def __init__(self, stream, meter):
        self.stream, self.meter, self.size, self.digest = stream, meter, 0, sha256()

    def read(self, count=-1):
        _need(0 <= count <= 1_048_576, "unexpected unbounded compressed read")
        raw = self.stream.read(count)
        self.meter.charge("stored_bytes", len(raw)); self.size += len(raw); self.digest.update(raw)
        return raw


def _gzip_rows(path, declaration, meter):
    before = path.stat()
    digest, size, count = sha256(), 0, 0
    with path.open("rb") as stream:
        physical = _PhysicalReader(stream, meter)
        with gzip.GzipFile(fileobj=physical) as decoded:
            while True:
                raw = decoded.readline(meter.limits.max_record_bytes + 1)
                if not raw: break
                _need(raw.endswith(b"\n") and len(raw) <= meter.limits.max_record_bytes, "source line bound/terminator differs")
                meter.charge("decoded_bytes", len(raw)); digest.update(raw); size += len(raw); count += 1
                _need(size <= declaration["raw_bytes"] and count <= declaration["rows"], "source stream exceeds declaration")
                yield count, raw
        _need(physical.read(1) == b"", "source compressed stream not fully consumed")
    after = path.stat()
    _need((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
          == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns), "source retention changed")
    _need(physical.size == before.st_size
          and (count, size, digest.hexdigest()) == (declaration["rows"], declaration["raw_bytes"], declaration["raw_sha256"]),
          "source complete EOF receipt mismatch")
    return {"original_uri": str(path), "stored_bytes": physical.size, "stored_sha256": physical.digest.hexdigest(),
            "decoded_bytes": size, "decoded_sha256": digest.hexdigest(), "rows": count}


def _producer():
    path = Path(__file__).resolve(); raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": sha256(raw).hexdigest()}


def build_native_context_navigation(inputs, fresh_output, *, budgets=NavigationBudget()):
    """Own a single complete retained-output pass; never invoke raw producers.

    Explicitly calling this builder is the separate indexing operation. Merely
    opening/querying a navigation manifest never scans the association gzip.
    """
    _need(type(inputs) is NativeContextInputs and type(budgets) is NavigationBudget, "typed builder inputs/budgets required")
    adapter = _producer()
    meter = _Meter(budgets); roots = _Roots(inputs, meter)
    out = Path(fresh_output).absolute(); out.mkdir(parents=False, exist_ok=False)
    building = _json({"schema": SCHEMA, "inputs": encode(inputs)})
    meter.charge("output_bytes", len(building)); _write(out / "BUILDING.json", building)
    try:
        source, native, index = (_Sink(out, name, meter) for name in ("source", "native", "index"))
        lookup, phases = {}, {}
        d = roots.dispatch
        path = _child(inputs.dispatch_source_report.uri, d["index"]["path"])
        # The original marker index is small metadata, not the source transcript.
        before = path.stat()
        _need(path.is_file() and before.st_size <= budgets.max_metadata_bytes,
              "original marker index stored bound exceeded")
        meter.charge("stored_bytes", before.st_size)
        with path.open("rb") as stream:
            raw = stream.read(before.st_size)
        after = path.stat()
        _need(len(raw) == before.st_size and (before.st_dev, before.st_ino, before.st_size,
              before.st_mtime_ns, before.st_ctime_ns) == (after.st_dev, after.st_ino, after.st_size,
              after.st_mtime_ns, after.st_ctime_ns), "original marker index retention changed")
        expected_decoded = d["index"]["raw_bytes"]
        _need(type(expected_decoded) is int and 0 <= expected_decoded <= budgets.max_metadata_bytes,
              "original marker index decoded bound exceeded")
        if meter.costs["decoded_bytes"] + expected_decoded > budgets.max_decoded_bytes:
            raise _BudgetExceeded(meter.phase + ":decoded_bytes")
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
            decoded = stream.read(expected_decoded + 1)
        meter.record_read("decoded_bytes", len(decoded))
        _need((len(decoded), sha256(decoded).hexdigest()) == (d["index"]["raw_bytes"], d["index"]["raw_sha256"]),
              "original marker index receipt differs")
        marker_index = loads(decoded.decode())
        _need(marker_index.get("schema") == "scar.dispatch-source-index" and marker_index.get("schema_version") == 1,
              "original marker index profile differs")
        meter.phase = "source_associations"
        stream = _gzip_rows(roots.association_path, d["observations"], meter)
        while True:
            try: line, raw = next(stream)
            except StopIteration as end:
                retention = end.value; break
            row = roots.source_row(loads(raw.decode()))
            seq, phase = row["sequence"], row["phase"]
            _need((seq, phase) not in phases and marker_index["markers"].get(row["marker_instance"])
                  == {"line": line, "line_sha256": sha256(raw).hexdigest()}, "original source marker index/phase differs")
            phases[seq, phase] = {**source.add(raw), "original_line": line}
        _need(len(phases) == len(marker_index["markers"]), "source marker denominator differs")
        source.close()
        meter.phase = "native_inventory"
        native_artifact = roots.inventory_artifact
        table = roots.inventory
        _need(table.get("schema") == "scar.native-capture-table-chunks" and table.get("schema_version") == 1
              and table.get("row_schema_version") == 2 and table.get("profile") == PROFILE,
              "native inventory profile differs")
        counts, ordinal = Counter(), 0
        for descriptor in table["chunks"]:
            _need(descriptor["first_row_ordinal"] == ordinal, "native chunk ordinal gap")
            a = decode(ProviderArtifact, descriptor["artifact"])
            raw = _raw(a, meter, limit=budgets.max_chunk_bytes)
            rows = raw.splitlines(keepends=True)
            _need(len(rows) == descriptor["rows"] and descriptor["last_row_ordinal"] == ordinal + len(rows) - 1,
                  "native inventory row denominator differs")
            for local, line in enumerate(rows, 1):
                row = loads(line.decode()); seq = row["sequence"]
                _need(_positive(seq) and seq not in lookup and row.get("state") in
                      ("FRONTIER", "MODELED_COMPLETE_REFERENCE", "MODELED_PARTIAL_REFERENCE"), "native classification/sequence differs")
                _inventory_scope(roots, row)
                lookup[seq] = {"sequence": seq, "inventory": {**native.add(line), "original": encode(ProviderFactReference(a, "#/lines/" + str(local)))},
                    "source": {phase: phases[seq, phase] for phase in ("span", "output") if (seq, phase) in phases}}
                counts[row["state"]] += 1; ordinal += 1
        _need(ordinal == table["rows"] == len(roots.sequences) and sorted(lookup) == roots.sequences
              and {seq for seq, phase in phases} <= set(lookup), "actual native/source denominator differs")
        _need(all(counts[state] == roots.native[field] for state, field in (
            ("FRONTIER", "unmodeled_frontier_dispatches"), ("MODELED_COMPLETE_REFERENCE", "modeled_complete_reference_dispatches"),
            ("MODELED_PARTIAL_REFERENCE", "modeled_partial_reference_dispatches"))), "final native classification counts differ")
        native.close(); meter.phase = "navigation_index"
        for seq in sorted(lookup): index.add(_json(lookup[seq]))
        index.close()
        # Index ranges are derived transport coordinates, never source identity.
        at = 0; ids = sorted(lookup)
        for desc in index.descriptors:
            desc.update(first_sequence=ids[at], last_sequence=ids[at + desc["rows"] - 1]); at += desc["rows"]
        _need(adapter == _producer(), "adapter source changed during navigation build")
        manifest = {"schema": SCHEMA, "schema_version": VERSION, "status": "PUBLISHED", "inputs": encode(inputs),
            "adapter": adapter, "historical_assumption": HISTORICAL_ASSUMPTION,
            "source_retention": retention, "source_declaration": encode(ProviderFactReference(inputs.dispatch_source_report, "#/observations")),
            "source_marker_index_declaration": d["index"], "native_inventory": encode(native_artifact),
            "counts": {"source_associations": len(phases), "native_sequences": len(lookup), "classifications": dict(counts)},
            "chunks": {"source": source.descriptors, "native": native.descriptors, "index": index.descriptors},
            "costs": dict(meter.costs)}
        raw = _json(manifest); _need(len(raw) <= budgets.max_metadata_bytes, "navigation manifest bound exceeded")
        meter.charge("output_bytes", len(raw))
        temporary = out / ".manifest.json"; _write(temporary, raw)
        os.link(temporary, out / "manifest.json"); temporary.unlink()
        return _artifact(out / "manifest.json", raw, SCHEMA)
    except BaseException as error:
        failure = _json({"schema": SCHEMA, "status": "FAILED_RETAINED",
            "reason": type(error).__name__ + ": " + str(error), "costs": dict(meter.costs)})
        # Diagnostics also fit the output ceiling. If it is exhausted, retain
        # BUILDING and already-closed chunks without publishing another file.
        if meter.costs["output_bytes"] + len(failure) <= budgets.max_output_bytes:
            meter.costs["output_bytes"] += len(failure)
            _write(out / "FAILED.json", failure)
        raise


def _inventory_scope(roots, row):
    for records in row["source_rows"].values():
        for record in records:
            _need(record["artifact"] == encode(roots.members["scar.dispatch-observation.events.v1"])
                  and record["locator"] == "#line/" + str(record["index"]) and _positive(record["index"]),
                  "native inventory original dispatch fact differs")


class NativeContextIndex:
    """Public checksum-bound reader; no raw session or ownership factory."""
    @classmethod
    def open(cls, manifest, *, expected_inputs, budgets=NativeContextQueryBudget()):
        _need(type(manifest) is ProviderArtifact and manifest.schema == SCHEMA
              and type(expected_inputs) is NativeContextInputs and type(budgets) is NativeContextQueryBudget,
              "typed navigation root/inputs/query budget required")
        meter = _Meter(budgets)
        m = _document(manifest, meter)
        _need(set(m) == {"schema", "schema_version", "status", "inputs", "adapter", "historical_assumption",
              "source_retention", "source_declaration", "source_marker_index_declaration", "native_inventory", "counts", "chunks", "costs"}
              and m["schema"] == SCHEMA and m["schema_version"] == VERSION and m["status"] == "PUBLISHED",
              "unsupported/unpublished navigation root")
        _need(m["inputs"] == encode(expected_inputs) and m["adapter"] == _producer()
              and m["historical_assumption"] == HISTORICAL_ASSUMPTION, "navigation inputs/adapter differ")
        roots = _Roots(expected_inputs, meter)
        _need(m["source_declaration"] == encode(ProviderFactReference(expected_inputs.dispatch_source_report, "#/observations"))
              and m["native_inventory"] == roots.native["dispatch_inventory"]
              and m["source_marker_index_declaration"] == roots.dispatch["index"]
              and m["source_retention"]["original_uri"] == str(roots.association_path)
              and m["source_retention"]["decoded_sha256"] == roots.dispatch["observations"]["raw_sha256"]
              and m["source_retention"]["decoded_bytes"] == roots.dispatch["observations"]["raw_bytes"],
              "navigation original stream/declaration differs")
        _need(set(m["chunks"]) == {"source", "native", "index"}, "navigation chunk family differs")
        for family, descriptors in m["chunks"].items():
            for number, d in enumerate(descriptors):
                expected = {"uri", "rows", "stored_bytes", "stored_sha256", "decoded_bytes", "decoded_sha256"}
                if family == "index": expected |= {"first_sequence", "last_sequence"}
                _need(set(d) == expected and d["uri"] == family + "/" + str(number).zfill(6) + ".jsonl.gz"
                      and _positive(d["rows"]) and d["rows"] <= 1000
                      and _positive(d["stored_bytes"]) and d["stored_bytes"] <= 8_000_000
                      and _positive(d["decoded_bytes"]) and d["decoded_bytes"] <= 8_000_000
                      and _SHA.fullmatch(d["stored_sha256"]) and _SHA.fullmatch(d["decoded_sha256"]), "navigation chunk descriptor differs")
        ranges = m["chunks"]["index"]
        _need(all(_positive(d["first_sequence"]) and _positive(d["last_sequence"])
                  and d["first_sequence"] <= d["last_sequence"] for d in ranges)
              and all(a["last_sequence"] < b["first_sequence"] for a, b in zip(ranges, ranges[1:])), "index sequence ranges overlap")
        _need(sum(d["rows"] for d in ranges) == sum(d["rows"] for d in m["chunks"]["native"])
              == m["counts"]["native_sequences"] == len(roots.sequences)
              and sum(d["rows"] for d in m["chunks"]["source"]) == m["counts"]["source_associations"]
              == roots.dispatch["observations"]["rows"], "navigation row denominators differ")
        self = cls.__new__(cls)
        self._manifest, self._artifact, self._inputs, self._budgets = m, manifest, expected_inputs, budgets
        self._ends = [d["last_sequence"] for d in ranges]
        return self

    def _chunk(self, family, number, meter, cache):
        key = family, number
        if key in cache: return cache[key]
        meter.phase = family
        meter.charge("index_chunks" if family == "index" else "data_chunks", 1)
        table = self._manifest["chunks"][family]
        _need(type(number) is int and 0 <= number < len(table), "navigation chunk coordinate invalid")
        d = table[number]
        meter.charge("stored_bytes", d["stored_bytes"]); meter.charge("decoded_bytes", d["decoded_bytes"])
        path = _path(str(Path(self._artifact.uri).parent / d["uri"]))
        _need(path.stat().st_size == d["stored_bytes"], "navigation stored chunk size mismatch")
        with path.open("rb") as stream:
            raw = stream.read(d["stored_bytes"] + 1)
        _need(len(raw) == d["stored_bytes"] and sha256(raw).hexdigest() == d["stored_sha256"], "navigation stored chunk SHA mismatch")
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
            decoded = stream.read(8_000_001)
        _need((len(decoded), sha256(decoded).hexdigest()) == (d["decoded_bytes"], d["decoded_sha256"]), "navigation decoded chunk receipt mismatch")
        lines = decoded.splitlines(keepends=True)
        _need(len(lines) == d["rows"] and all(x.endswith(b"\n") and len(x) <= meter.limits.max_record_bytes for x in lines),
              "navigation row bound/denominator differs")
        cache[key] = lines; return lines

    def _row(self, family, pointer, meter, cache):
        rows = self._chunk(family, pointer["chunk"], meter, cache)
        _need(type(pointer["line"]) is int and 0 <= pointer["line"] < len(rows), "navigation line coordinate invalid")
        raw = rows[pointer["line"]]
        _need(sha256(raw).hexdigest() == pointer["sha256"], "navigation row SHA differs")
        return loads(raw.decode())

    def native_context(self, sequence):
        _need(_positive(sequence), "query sequence must be a positive exact integer")
        meter, cache = _Meter(self._budgets), {}
        contexts, native_facts, invoked, returned, gaps = [], [], None, None, []
        status, relation, cursor = NativeContextStatus.CONTEXT_UNRESOLVED, None, None
        try:
            # Check the exact published navigation again; selected roots/chunks
            # remain immutable references, never a new runtime evidence lease.
            _raw(self._artifact, meter)
            roots = _Roots(self._inputs, meter)
            number = bisect_left(self._ends, sequence)
            if number == len(self._ends) or sequence < self._manifest["chunks"]["index"][number]["first_sequence"]:
                _need(sequence not in roots.sequences, "index range omitted an observed sequence")
                status = NativeContextStatus.SEQUENCE_NOT_OBSERVED
            else:
                rows = [loads(raw.decode()) for raw in self._chunk("index", number, meter, cache)]
                ids = [r["sequence"] for r in rows]
                _need(ids == sorted(set(ids)), "navigation sequence index is unordered/duplicate")
                candidates = [r for r in rows if r["sequence"] == sequence]
                if not candidates:
                    _need(sequence not in roots.sequences, "index omitted an observed sequence")
                    status = NativeContextStatus.SEQUENCE_NOT_OBSERVED
                else:
                    pointer = candidates[0]
                    inventory = self._row("native", pointer["inventory"], meter, cache)
                    _need(inventory["sequence"] == sequence, "navigation points to another native sequence")
                    _inventory_scope(roots, inventory)
                    inventory_fact = decode(ProviderFactReference, pointer["inventory"]["original"])
                    declared_chunks = [c for c in roots.inventory["chunks"] if c["artifact"] == encode(inventory_fact.artifact)]
                    line = re.fullmatch(r"#/lines/([1-9][0-9]*)", inventory_fact.locator)
                    _need(len(declared_chunks) == 1 and line is not None and int(line[1]) <= declared_chunks[0]["rows"],
                          "native inventory original locator differs")
                    native_facts.append(inventory_fact)
                    original_rows = {}
                    for phase, p in pointer["source"].items():
                        expected_line = 1 + sum(c["rows"] for c in self._manifest["chunks"]["source"][:p["chunk"]]) + p["line"]
                        _need(p["original_line"] == expected_line, "source original row ordinal differs")
                        row = roots.source_row(self._row("source", p, meter, cache), sequence)
                        _need(row["phase"] == phase, "navigation source phase differs")
                        original_rows[phase] = row
                        ref = SourceAssociationRef(ProviderFactReference(self._inputs.dispatch_source_report, "#/observations"),
                            str(roots.association_path), p["original_line"], p["sha256"])
                        invocation = None if row.get("invocation") is None else decode(InvocationKey, row["invocation"])
                        optional = lambda key: None if row.get(key) is None else decode(ProviderFactReference, row[key])
                        contexts.append(RetainedSourceContext(phase, ref, invocation,
                            None if row.get("definition") is None else decode(SourceDefinitionReference, row["definition"]),
                            optional("source_invocation_reference"), optional("source_binding_reference"),
                            "#/lines/" + str(ref.line) + "/region_namespace" if row.get("region_namespace") is not None else None,
                            optional("region_activation_reference")))
                        for key in ("frontiers", "source_frontiers", "source_interface_frontiers"):
                            gaps.extend(row.get(key, []))
                    if inventory["state"] == "FRONTIER":
                        status = NativeContextStatus.NATIVE_FRONTIER
                        gaps.append(inventory["reason"])
                    else:
                        invoked, returned, actual_facts = _native_endpoints(roots, inventory, original_rows, meter)
                        native_facts.extend(actual_facts)
                        if any(c.phase == "span" and c.invocation is not None for c in contexts):
                            status, relation = NativeContextStatus.RETAINED_CONTEXT, ContextRelationship.RETAINED_SOURCE_CONTEXT
                        else: gaps.append("RETAINED_SOURCE_CONTEXT_UNAVAILABLE")
            meter.charge("completed_queries", 1)
        except _BudgetExceeded as error:
            status, relation, cursor = NativeContextStatus.BUDGET_EXHAUSTED, None, str(error)
            gaps.append("NATIVE_CONTEXT_BUDGET_EXHAUSTED")
        gaps.append(HISTORICAL_ASSUMPTION)
        return NativeContextResult(self._artifact, self._inputs, self._inputs.scope_revision, sequence, status, relation,
            tuple(contexts), tuple(native_facts), invoked, returned, tuple(dict.fromkeys(gaps)),
            (HISTORICAL_ASSUMPTION,), cursor, {**meter.costs, "wall_seconds": time.monotonic() - meter.start})


def _native_endpoints(roots, inventory, source_rows, meter):
    from scar.ir.execution.codec import loads as execution_loads
    from scar.ir.program.codec import loads as program_loads
    from scar.ir.program.model import TerminatorKind, ExitKind
    from scar.store.bundle_partitions import BundlePartitions
    n = roots.native
    execution_artifact = decode(ProviderArtifact, inventory["execution"])
    shards = [s for s in n["shards"] if s["execution"] == encode(execution_artifact) and inventory["sequence"] in s["sequences"]]
    _need(len(shards) == 1, "modeled native sequence has no unique original shard")
    shard = shards[0]
    shared = decode(ProviderArtifact, n["shared_program"])
    meter.phase = "native_execution"
    execution = execution_loads(_raw(execution_artifact, meter, limit=meter.limits.max_decoded_bytes).decode())
    program = program_loads(_raw(shared, meter, limit=meter.limits.max_decoded_bytes).decode())
    _need(execution.snapshot.artifact == shared and encode(execution.snapshot) == shard["program_snapshot"], "native ProgramSnapshot differs")
    runs = [r for r in execution.runs if r.id.value == roots.run]
    processes = [p for p in execution.processes if encode(p.id) == roots.process]
    _need(len(runs) == len(processes) == 1 and processes[0].run == runs[0].id and processes[0].pid == roots.pid,
          "native execution Run/process declaration differs")
    begins = inventory["source_rows"].get("DISPATCH_BEGIN", [])
    _need(inventory.get("outcome") == "RETURNED" and inventory.get("begin_count") == inventory.get("end_count") == 1
          and len(begins) == len(inventory["source_rows"].get("DISPATCH_END", [])) == 1,
          "modeled native dispatch normal phase inventory differs")
    activation = [a for a in execution.activations if a.id.value == inventory["activation_id"]]
    _need(len(activation) == 1 and encode(activation[0].process) == roots.process
          and activation[0].entry.run.value == roots.run and encode(activation[0].entry.process) == roots.process,
          "native activation Run/process differs")
    _need(encode(activation[0].entry.source) == {"artifact": begins[0]["artifact"], "locator": begins[0]["locator"]},
          "native activation original BEGIN fact differs")
    segments = [s for s in execution.segments if s.activation == activation[0].id]
    _need(len(segments) == 1, "native initial segment is ambiguous")
    visits = {v.id: v for v in execution.visits if v.segment == segments[0].id}
    static = {o.id: o for o in program.operations}
    actual = [o for o in execution.operations if o.visit in visits]
    invokes = [o for o in actual if static[o.operation].terminator and static[o.operation].terminator.kind is TerminatorKind.INVOKE]
    returns = [o for o in actual if static[o.operation].terminator and static[o.operation].terminator.kind is TerminatorKind.RETURN]
    _need(len(invokes) == len(returns) == 1, "native invoke/normal Return missing/ambiguous")
    invoke, returned = invokes[0], returns[0]
    region = next(r for r in program.regions if r.id == activation[0].region)
    normal = [(i, edge) for i, edge in enumerate(static[invoke.operation].terminator.successors) if edge.kind is ExitKind.NORMAL]
    blocks = {block.id: block for block in region.blocks}
    _need(visits[invoke.visit].block == region.entry and len(normal) == 1
          and visits[returned.visit].block == normal[0][1].block
          and invoke.operation in blocks[region.entry].operations
          and returned.operation in blocks[normal[0][1].block].operations
          and static[returned.operation].terminator.exit == "normal", "native normal Return block differs")
    transfers = [t for t in execution.transfers if t.operation == invoke.id]
    _need(len(transfers) == 1 and transfers[0].target == returned.visit and transfers[0].successor_index == normal[0][0],
          "native normal completion transfer differs")
    bindings = []
    for occurrence in (invoke, returned):
        found = [b for b in execution.evidence_bindings if b.operation == occurrence.id]
        _need(len(found) == 1, "native occurrence producer binding missing/ambiguous")
        bindings.append(found[0])
    a, b = bindings
    _need(encode(a.legacy.artifact) == shard["evidence_projection"] and a.legacy == b.legacy
          and type(a.source) is ProviderFactReference and type(b.source) is ProviderFactReference
          and a.source.artifact == b.source.artifact == roots.eto and _NODE.fullmatch(a.source.locator)
          and b.source.locator == a.source.locator + "/outputs", "native invoke/Return producer/phase differs")
    projected = _document(a.legacy.artifact, meter)
    _need(projected.get("schema") == "scar.ir.v2.evidence" and projected.get("schema_version") in (3, 4, 5, 6),
          "native projected evidence artifact differs")
    projected_instances = {row["id"]["wire"]: row for row in projected["instances"]}
    _need(len(projected_instances) == len(projected["instances"]), "duplicate projected native instance")
    ordinals = {int(_NODE.fullmatch(a.source.locator)[1])}
    for row in source_rows.values(): ordinals.add(int(_NODE.fullmatch(row["marker_reference"]["locator"])[1]))
    class Selected(BundlePartitions):
        def _chunk(self, descriptor):
            meter.phase = "selected_original_eeg"
            meter.charge("archive_chunks", 1)
            meter.charge("stored_bytes", descriptor["physical_bytes"])
            meter.charge("decoded_bytes", descriptor["decoded_bytes"])
            return super()._chunk(descriptor)
    # Constructor rereads this small original manifest and must be charged too.
    meter.charge("stored_bytes", roots.inputs.original_native_manifest.size_bytes)
    meter.charge("decoded_bytes", roots.inputs.original_native_manifest.size_bytes)
    selected = Selected(roots.inputs.original_native_manifest.uri).selected_records("evidence", "instances", tuple(sorted(ordinals)))
    records = {r["ordinal"]: r["record"] for r in selected}
    for ordinal, record in records.items():
        meta = record["metadata"]
        _need(meta["provider"] == "ETO" and record["process_id"] == roots.pid
              and record["id"]["value"] == roots.native_scope + ":eto:" + str(meta["node_id"])
              and meta["raw_reference"] == "sha256:" + roots.eto.sha256 + "#/nodes/" + str(ordinal),
              "selected original EEG namespace/node ordinal differs")
        _need(projected_instances.get(record["id"]["wire"]) == record,
              "native evidence projection lost its exact original instance")
    child = records[int(_NODE.fullmatch(a.source.locator)[1])]
    _need(encode(a.legacy.instance) == child["id"], "native binding points to another original ETO instance")
    span = source_rows.get("span")
    if span is not None:
        parent = records[int(_NODE.fullmatch(span["marker_reference"]["locator"])[1])]
        thread = lambda record: record["metadata"].get("eto_tid", record["metadata"]["raw_tid"])
        _need(parent["id"]["wire"] == span["marker_instance"] and child["parent"] == parent["id"]
              and child["metadata"]["ctrl_deps"] == parent["metadata"]["node_id"]
              and thread(child) == thread(parent), "native child/source span parent/thread differs")
        output = source_rows.get("output")
        if output is not None:
            result = records[int(_NODE.fullmatch(output["marker_reference"]["locator"])[1])]
            _need(result["id"]["wire"] == output["marker_instance"] and result["parent"] == parent["id"]
                  and result["metadata"]["ctrl_deps"] == parent["metadata"]["node_id"]
                  and thread(result) == thread(parent), "native output/source span phase/thread differs")
    return (QualifiedOccurrenceRef(execution_artifact, invoke.id, a), QualifiedOccurrenceRef(execution_artifact, returned.id, b),
            [a.source, b.source, *(decode(ProviderFactReference, r["marker_reference"]) for r in source_rows.values())])


__all__ = ["NativeContextInputs", "NavigationBudget", "NativeContextQueryBudget", "NativeContextStatus",
    "ContextRelationship", "SourceAssociationRef", "QualifiedOccurrenceRef", "RetainedSourceContext",
    "NativeContextResult", "build_native_context_navigation", "NativeContextIndex"]
