"""Bounded immutable chunks of existing IRBundle records, without giant JSON.

Only the explicit SG/EEG/Value/Correspondence tables are supported. Producer
validation happens once before export; the reader verifies storage receipts,
not whole-bundle semantic validity, and never assembles a complete bundle.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
import gzip
from hashlib import sha256
import io
import json
import math
import os
from pathlib import Path
import secrets

from scar.ir.record_codec import loads as strict_loads


SCHEMA = "scar.partitioned-ir-bundle"
VERSION = 1
TABLES = {
    "semantic": ("packages", "modules", "source_atoms", "definitions", "slots",
                 "controls", "contracts", "effects", "resources", "edges"),
    "evidence": ("instances", "observations", "provider_references", "measurements",
                 "control_events", "external_references", "edges"),
    "values": ("logical_values", "versions", "provenance", "allocations", "regions",
               "materializations", "objects", "bindings"),
    "correspondence": ("records",),
}
_GRAPH_SCHEMAS = {
    "semantic": ("scar.ir.v2.semantic", (2,)),
    "evidence": ("scar.ir.v2.evidence", (3, 4, 5, 6)),
    "values": ("scar.ir.v2.values", (1, 2)),
    "correspondence": ("scar.ir.v2.correspondence", (1,)),
}


@dataclass(frozen=True)
class BundleBudgets:
    max_chunk_decoded_bytes: int = 16000000
    max_chunk_stored_bytes: int = 17000000
    max_record_bytes: int = 4000000
    max_total_decoded_bytes: int = 16000000000
    max_total_stored_bytes: int = 4000000000
    max_records: int = 10000000
    max_chunks: int = 100000
    max_manifest_bytes: int = 4000000
    max_json_depth: int = 128
    max_json_items: int = 2000000

    def __post_init__(self):
        if any(type(getattr(self, field.name)) is not int or getattr(self, field.name) < 1
               for field in fields(self)):
            raise ValueError("bundle partition budgets must be positive exact integers")
        if self.max_record_bytes > self.max_chunk_decoded_bytes:
            raise ValueError("one record must fit within an independent decoded chunk budget")


def _budgets(value):
    if value is None:
        return BundleBudgets()
    if type(value) is dict:
        return BundleBudgets(**value)
    if type(value) is not BundleBudgets:
        raise TypeError("budgets must be BundleBudgets or its exact keyword dictionary")
    value.__post_init__()
    return value


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _line(value, limits):
    # Preflight builtins only, before an encoder can escape one giant string.
    # This is storage validation, not a scan for semantic identity/edges.
    stack, items = [(iter((value,)), 0)], 0
    while stack:
        iterator, depth = stack[-1]
        try:
            item = next(iterator)
        except StopIteration:
            stack.pop()
            continue
        items += 1
        _require(items <= limits.max_json_items and depth <= limits.max_json_depth,
                 "record JSON traversal budget exceeded")
        kind = type(item)
        if kind is str:
            _require(len(item) <= limits.max_record_bytes, "record scalar exceeds byte lower bound")
        elif kind in (dict, list, tuple):
            _require(len(item) <= limits.max_json_items, "record container budget exceeded")
            if kind is dict:
                _require(all(type(key) is str for key in item), "record JSON keys must be strings")
                for key in item:
                    _require(len(key) <= limits.max_record_bytes, "record key budget exceeded")
                stack.append((iter(item.values()), depth + 1))
            else:
                stack.append((iter(item), depth + 1))
        elif kind is float:
            _require(math.isfinite(item), "record has a nonfinite scalar")
        else:
            _require(item is None or kind in (bool, int), "record has unsupported non-JSON content")
    pending = bytearray()
    encoder = json.JSONEncoder(sort_keys=True, ensure_ascii=False, allow_nan=False,
                               separators=(",", ":"))
    for text in encoder.iterencode(value):
        data = text.encode("utf-8")
        _require(len(pending) + len(data) + 1 <= limits.max_record_bytes,
                 "individual bundle record byte budget exceeded")
        pending.extend(data)
    pending.extend(b"\n")
    return pending


class _Sink:
    def __init__(self, stream, totals, limits):
        self.stream, self.totals, self.limits = stream, totals, limits
        self.digest, self.size = sha256(), 0

    def write(self, data):
        _require(self.size + len(data) <= self.limits.max_chunk_stored_bytes,
                 "independent compressed chunk budget exceeded")
        _require(self.totals["stored_bytes"] + len(data) <= self.limits.max_total_stored_bytes,
                 "total compressed bundle budget exceeded")
        offset = 0
        while offset < len(data):
            size = self.stream.write(data[offset:])
            if size is None or size <= 0:
                raise OSError("bundle compressed chunk made no write progress")
            self.digest.update(data[offset:offset + size])
            self.size += size
            self.totals["stored_bytes"] += size
            offset += size
        return len(data)

    def flush(self):
        self.stream.flush()


class _Chunk:
    def __init__(self, out, graph, table, number, first, totals, limits):
        _require(totals["chunks"] < limits.max_chunks, "total chunk count budget exceeded")
        self.uri = f"{graph}/{table}/{number:06d}.jsonl.gz"
        self.path = out / self.uri
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.raw = self.path.open("xb")
        self.sink = _Sink(self.raw, totals, limits)
        self.compressed = gzip.GzipFile(fileobj=self.sink, mode="wb", filename="",
                                       mtime=0, compresslevel=1)
        self.digest, self.decoded_bytes, self.lines = sha256(), 0, 0
        self.first, self.totals = first, totals
        self.closed = False
        totals["chunks"] += 1

    def write(self, data):
        self.compressed.write(data)
        self.digest.update(data)
        self.decoded_bytes += len(data)
        self.lines += 1
        self.totals["decoded_bytes"] += len(data)
        self.totals["records"] += 1

    def close(self):
        if not self.closed:
            self.closed = True
            try:
                self.compressed.close()
            finally:
                self.raw.close()
        _require(self.path.stat().st_size == self.sink.size, "compressed write receipt size mismatch")
        return {"uri": self.uri, "compression": "gzip",
            "physical_sha256": self.sink.digest.hexdigest(), "physical_bytes": self.sink.size,
            "decoded_sha256": self.digest.hexdigest(), "decoded_bytes": self.decoded_bytes,
            "lines": self.lines, "first_ordinal": self.first,
            "last_ordinal": self.first + self.lines - 1}


def _records(graph_name, table_name, collection):
    if graph_name == "evidence" and table_name == "control_events":
        _require(type(collection) is set, "control_events must retain its original set")
        for value in collection:
            yield value
    elif graph_name == "evidence" and table_name == "external_references":
        _require(type(collection) is set, "external_references must retain its original set")
        for kind, wire in collection:
            yield {"kind": kind.value, "wire": wire}
    else:
        expected = list if (graph_name, table_name) == ("values", "bindings") else dict
        _require(type(collection) is expected, "bundle table container differs from its explicit contract")
        source = collection.values() if expected is dict else collection
        for record in source:
            yield record.as_dict()


def publish_bundle(bundle, fresh_out, budgets=None, progress=None):
    """Write only existing records; call public bundle.assert_valid exactly once.

    The caller must hold the bundle stable throughout validation/export. Output
    is a fresh directory; only an atomic final manifest publishes it. A failed
    build leaves partial chunks and no manifest, preserving every input.
    """
    from scar.ir.v2.schemas import IRBundle
    from scar.ir.v2.semantic import SemanticGraph
    from scar.ir.v2.evidence import EvidenceGraph
    from scar.ir.v2.values import ValueGraph
    from scar.ir.v2.correspondence import CorrespondenceGraph
    limits = _budgets(budgets)
    _require(type(bundle) is IRBundle, "bundle partition writer needs the original IRBundle")
    _require(bundle.optimization is None and bundle.source_semantics is None,
             "optimization/source_semantics are not supported and cannot be silently omitted")
    _require(progress is None or callable(progress), "progress must be callable or None")
    types = {"semantic": SemanticGraph, "evidence": EvidenceGraph,
             "values": ValueGraph, "correspondence": CorrespondenceGraph}
    for name, graph_type in types.items():
        graph = getattr(bundle, name)
        if name == "correspondence" and graph is None:
            continue
        _require(type(graph) is graph_type and set(vars(graph)) == set(TABLES[name]),
                 "unsupported graph type/table set; refusing to lose fields")
    if progress is not None:
        progress({"phase": "VALIDATION_BEGIN"})
    validation = bundle.assert_valid()
    out = Path(fresh_out).absolute()
    out.mkdir(mode=0o700, parents=False, exist_ok=False)
    totals = {"records": 0, "chunks": 0, "decoded_bytes": 0, "stored_bytes": 0}
    graphs, active = {}, None
    try:
        for graph_name in TABLES:
            graph = getattr(bundle, graph_name)
            if graph is None:
                graphs[graph_name] = None
                continue
            report = validation["graphs"][graph_name]
            _require(report["valid"] is True, "public bundle validation did not validate graph")
            descriptor = {"schema": report["schema"], "schema_version": report["schema_version"],
                          "counts": {}, "tables": {}, "validation": report}
            graphs[graph_name] = descriptor
            for table_name in TABLES[graph_name]:
                collection = getattr(graph, table_name)
                expected_count, ordinal, chunks = len(collection), 0, []
                if progress is not None:
                    progress({"phase": "TABLE_BEGIN", "graph": graph_name,
                              "table": table_name, "table_records_expected": expected_count, **totals})
                for record in _records(graph_name, table_name, collection):
                    _require(totals["records"] < limits.max_records, "total bundle record budget exceeded")
                    data = _line({"ordinal": ordinal, "record": record}, limits)
                    _require(totals["decoded_bytes"] + len(data) <= limits.max_total_decoded_bytes,
                             "total decoded bundle budget exceeded")
                    if active is not None and active.decoded_bytes + len(data) > limits.max_chunk_decoded_bytes:
                        chunks.append(active.close())
                        active = None
                        if progress is not None:
                            progress({"phase": "CHUNK_CLOSED", "graph": graph_name,
                                      "table": table_name, "table_records": ordinal, **totals})
                    if active is None:
                        active = _Chunk(out, graph_name, table_name, len(chunks), ordinal, totals, limits)
                    active.write(data)
                    ordinal += 1
                if active is not None:
                    chunks.append(active.close())
                    active = None
                _require(ordinal == expected_count == len(collection), "live bundle table changed during export")
                if table_name in report["counts"]:
                    _require(report["counts"][table_name] == ordinal, "exported count differs from public validation")
                else:
                    _require(ordinal == 0, "public validation lacks a nonempty exported table count")
                descriptor["counts"][table_name] = ordinal
                descriptor["tables"][table_name] = {"records": ordinal, "chunks": chunks,
                    "order": "source container iteration; ordinal is archive-local, not old to_dict array position"}
                if progress is not None:
                    progress({"phase": "TABLE_COMPLETE", "graph": graph_name,
                              "table": table_name, "table_records": ordinal, **totals})
            _require(set(report["counts"]) <= set(TABLES[graph_name]), "public graph validation has an unhandled table count")
        _require(bundle.optimization is None and bundle.source_semantics is None,
                 "unsupported bundle fields changed during export")
        for name, tables in TABLES.items():
            graph = getattr(bundle, name)
            _require((graph is None) == (graphs[name] is None), "optional graph changed during export")
            if graph is not None:
                _require(set(vars(graph)) == set(tables)
                         and all(len(getattr(graph, table)) == graphs[name]["counts"][table]
                                 for table in tables), "final live graph table counts changed during export")
        document = {"schema": SCHEMA, "schema_version": VERSION, "status": "PUBLISHED",
            "bundle": {"schema": bundle.SCHEMA, "schema_version": bundle.SCHEMA_VERSION},
            "graphs": graphs, "validation": validation, "totals": totals,
            "limits": {field.name: getattr(limits, field.name) for field in fields(limits)},
            "optimization": None, "source_semantics": None,
            "public_bundle_validation_performed": True,
            "reader_semantic_revalidation_performed": False,
            "whole_program_established": False, "transformation_authorized": False,
            "scope": "existing SG/EEG/Value/Correspondence records; raw provider artifacts are unchanged",
            "stability_assumption": "caller holds bundle and record metadata stable throughout validation/export"}
        payload = (json.dumps(document, sort_keys=True, ensure_ascii=False,
                              allow_nan=False, separators=(",", ":")) + "\n").encode("utf-8")
        _require(len(payload) <= limits.max_manifest_bytes, "bundle manifest byte budget exceeded")
        temporary = out / f".manifest.{secrets.token_hex(16)}.tmp"
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        # An atomic hard link publishes the exact closed manifest without
        # replacing any existing file. The temporary file is our own artifact.
        os.link(temporary, out / "manifest.json")
        try:
            temporary.unlink()
        except OSError:
            pass
        return {**document, "manifest_receipt": {"path": str(out / "manifest.json"),
            "physical_sha256": sha256(payload).hexdigest(), "physical_bytes": len(payload)}}
    finally:
        if active is not None and not active.closed:
            active.close()


class BundlePartitions:
    """Receipt verification and bounded selected-table iteration, not IR loading."""
    def __init__(self, manifest, budgets=None):
        self.limits = _budgets(budgets)
        path = Path(manifest).resolve()
        if path.is_dir():
            path = path / "manifest.json"
        _require(path.is_file() and not path.is_symlink(), "published bundle manifest is absent/not regular")
        with path.open("rb") as stream:
            payload = stream.read(self.limits.max_manifest_bytes + 1)
        _require(len(payload) <= self.limits.max_manifest_bytes, "bundle manifest read budget exceeded")
        self.manifest = strict_loads(payload.decode("utf-8"))
        self.root = path.parent
        self.manifest_receipt = {"path": str(path), "physical_sha256": sha256(payload).hexdigest(),
                                 "physical_bytes": len(payload)}
        m = self.manifest
        _require(type(m) is dict and m.get("schema") == SCHEMA
                 and type(m.get("schema_version")) is int and m["schema_version"] == VERSION
                 and m.get("status") == "PUBLISHED", "unsupported/unpublished partitioned bundle")
        _require(type(m.get("bundle")) is dict
                 and type(m["bundle"].get("schema_version")) is int
                 and m["bundle"] == {"schema": "scar.ir.v2.bundle", "schema_version": 2}
                 and m.get("optimization") is None and m.get("source_semantics") is None
                 and m.get("public_bundle_validation_performed") is True,
                 "unsupported original bundle fields/producer validation claim")
        _require(type(m.get("graphs")) is dict and set(m["graphs"]) == set(TABLES),
                 "partitioned bundle graph table set mismatch")
        totals = {"records": 0, "chunks": 0, "decoded_bytes": 0, "stored_bytes": 0}
        uris = set()
        for name, tables in TABLES.items():
            graph = m["graphs"][name]
            if graph is None:
                _require(name == "correspondence", "required graph is absent")
                continue
            _require(type(graph) is dict and set(graph["tables"]) == set(tables)
                     and set(graph["counts"]) == set(tables), "graph collection set mismatch")
            schema, versions = _GRAPH_SCHEMAS[name]
            _require(graph.get("schema") == schema and type(graph.get("schema_version")) is int
                     and graph["schema_version"] in versions
                     and graph["validation"].get("valid") is True
                     and graph["validation"].get("schema") == schema
                     and graph["validation"].get("schema_version") == graph["schema_version"],
                     "original graph schema/version/validation declaration mismatch")
            for table in tables:
                desc, ordinal = graph["tables"][table], 0
                for number, chunk in enumerate(desc["chunks"]):
                    expected = f"{name}/{table}/{number:06d}.jsonl.gz"
                    _require(chunk.get("uri") == expected and expected not in uris
                             and chunk.get("compression") == "gzip", "chunk URI/order/compression mismatch")
                    uris.add(expected)
                    for field in ("lines", "physical_bytes", "decoded_bytes"):
                        _require(type(chunk.get(field)) is int and chunk[field] > 0,
                                 "chunk counters must be positive exact integers")
                    _require(type(chunk.get("first_ordinal")) is int and chunk["first_ordinal"] == ordinal
                             and type(chunk.get("last_ordinal")) is int
                             and chunk["last_ordinal"] == ordinal + chunk["lines"] - 1,
                             "chunk ordinal ranges are not exact/contiguous")
                    _require(chunk["physical_bytes"] <= self.limits.max_chunk_stored_bytes
                             and chunk["decoded_bytes"] <= self.limits.max_chunk_decoded_bytes,
                             "chunk exceeds independent reader budget")
                    ordinal += chunk["lines"]
                    totals["chunks"] += 1
                    totals["stored_bytes"] += chunk["physical_bytes"]
                    totals["decoded_bytes"] += chunk["decoded_bytes"]
                _require(type(desc["records"]) is int and type(graph["counts"][table]) is int
                         and ordinal == desc["records"] == graph["counts"][table],
                         "table ordinal/record counts disagree")
                totals["records"] += ordinal
            declared_counts = graph["validation"]["counts"]
            _require(set(declared_counts) <= set(tables)
                     and all(type(value) is int and value == graph["counts"][table]
                             for table, value in declared_counts.items())
                     and all(table in declared_counts or graph["counts"][table] == 0
                             for table in tables), "producer validation/table counts disagree")
        _require(type(m.get("totals")) is dict and set(m["totals"]) == set(totals)
                 and all(type(value) is int for value in m["totals"].values())
                 and totals == m["totals"], "manifest graph/chunk total counters disagree")
        _require(totals["records"] <= self.limits.max_records and totals["chunks"] <= self.limits.max_chunks
                 and totals["stored_bytes"] <= self.limits.max_total_stored_bytes
                 and totals["decoded_bytes"] <= self.limits.max_total_decoded_bytes,
                 "manifest exceeds reader aggregate budgets")

    def _chunk(self, descriptor):
        relative = Path(descriptor["uri"])
        _require(not relative.is_absolute() and ".." not in relative.parts, "chunk URI must stay inside archive")
        path = self.root
        for part in relative.parts:
            path = path / part
            _require(not path.is_symlink(), "bundle chunk path may not traverse symlinks")
        _require(path.is_file(), "bundle chunk is not a retained regular file")
        with path.open("rb") as stream:
            physical = stream.read(self.limits.max_chunk_stored_bytes + 1)
        _require(len(physical) == descriptor["physical_bytes"]
                 and sha256(physical).hexdigest() == descriptor["physical_sha256"],
                 "compressed chunk SHA/byte receipt mismatch")
        with gzip.GzipFile(fileobj=io.BytesIO(physical), mode="rb") as stream:
            decoded = stream.read(self.limits.max_chunk_decoded_bytes + 1)
        _require(len(decoded) == descriptor["decoded_bytes"]
                 and sha256(decoded).hexdigest() == descriptor["decoded_sha256"]
                 and decoded.endswith(b"\n") and decoded.count(b"\n") == descriptor["lines"],
                 "decoded chunk SHA/byte/line receipt mismatch")
        return decoded

    def iter_records(self, graph, table):
        """Yield existing wire records with verified whole-chunk byte receipts.

        One compressed and one decoded bounded chunk are read before yielding;
        current row ordinal is checked before yield. This does not run record
        codecs or cross-graph semantic validation, nor join chunks into a graph.
        """
        _require(graph in TABLES and table in TABLES[graph], "unknown explicit bundle graph/table")
        descriptor = self.manifest["graphs"][graph]
        if descriptor is None:
            return
        for chunk in descriptor["tables"][table]["chunks"]:
            decoded = self._chunk(chunk)
            stream = io.BytesIO(decoded)
            for local_line in range(chunk["lines"]):
                line = stream.readline(self.limits.max_record_bytes + 1)
                _require(len(line) <= self.limits.max_record_bytes and line.endswith(b"\n"),
                         "record line exceeds its independent reader budget")
                row = strict_loads(line.decode("utf-8"))
                ordinal = chunk["first_ordinal"] + local_line
                _require(type(row) is dict and set(row) == {"ordinal", "record"}
                         and type(row["ordinal"]) is int and row["ordinal"] == ordinal,
                         "record envelope/ordinal mismatch")
                yield {**row, "locator": {"artifact": dict(chunk), "line": local_line + 1,
                    "pointer_within_line": "/record", "manifest_receipt": dict(self.manifest_receipt)},
                    "verification": {"whole_chunk_stored_sha_verified": True,
                        "whole_chunk_decoded_sha_verified": True, "current_row_ordinal_verified": True,
                        "record_semantics_revalidated": False, "whole_bundle_revalidated": False}}
            _require(stream.read(1) == b"", "unexpected extra data after declared chunk rows")


__all__ = ["BundleBudgets", "BundlePartitions", "publish_bundle", "SCHEMA", "VERSION", "TABLES"]
