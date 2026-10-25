"""One verified native acquisition, shared typed interfaces, bounded executions.

SQLite contains disposable navigation envelopes, never a second IR or restored
authority. Public artifacts use the existing program/execution/value/evidence
codecs. Per-dispatch accounting is derived from actual source rows.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import codecs
from dataclasses import dataclass
import gzip
from hashlib import sha256
import hmac
import json
from pathlib import Path
import resource
import secrets
import sqlite3
import time

from scar.ir.record_codec import decode, encode
from scar.ir.program.providers import ProviderArtifact
from scar.ir.execution.native_port_protocol import (
    PROFILE, _make_evidence, _own_capture, attributes, canonical, need, replay_interfaces,
)
from scar.trace.native_protocol import (
    NativeProtocolWindowResult, _artifact, _build_execution, _build_program,
    _members, _metadata, _prepare_projection, _write,
)
from scar.trace.native_schema import PROVIDER_REVISION
from scar.store.bundle_partitions import BundlePartitions


@dataclass(frozen=True)
class NativeCaptureBatchBudget:
    max_source_raw_bytes: int = 600_000_000
    max_metadata_bytes: int = 4_000_000
    max_record_bytes: int = 4_000_000
    max_index_bytes: int = 4_000_000_000
    max_program_bytes: int = 64_000_000
    max_interface_bytes: int = 16_000_000
    max_inventory_bytes: int = 256_000_000
    max_report_bytes: int = 16_000_000
    max_shard_attempts: int = 256
    max_shard_execution_bytes: int = 64_000_000
    max_shard_values_bytes: int = 64_000_000
    max_shard_evidence_bytes: int = 128_000_000
    max_shard_receipt_bytes: int = 256_000_000
    max_shard_source_bytes: int = 64_000_000
    max_shard_tensor_leaves: int = 4096
    max_shard_flat_leaves: int = 8192
    max_output_bytes: int = 8_000_000_000
    max_wall_seconds: int = 1800
    max_shard_seconds: int = 60
    max_rss_kib: int = 2 * 1024 * 1024

    def __post_init__(self):
        need(all(type(v) is int and v > 0 for v in vars(self).values()), "batch budgets must be positive exact integers")
        need(self.max_shard_attempts <= 256 and self.max_source_raw_bytes <= 600_000_000
             and self.max_program_bytes <= 64_000_000, "batch source/program/attempt hard bounds exceeded")


@dataclass(frozen=True)
class NativeCaptureBatchResult:
    directory: Path
    program: object
    report: dict
    first_shard: object | None


class _MissingDependency(ValueError):
    """Original source lacks a required witness; not an identity contradiction."""


def _pairs(items):
    result = {}
    for key, value in items:
        need(key not in result, "duplicate JSON key in native source")
        result[key] = value
    return result


def _json(data):
    def bad(value):
        raise ValueError("non-finite JSON number in source: " + value)
    return json.loads(data, object_pairs_hook=_pairs, parse_constant=bad)


class _RawReader:
    def __init__(self, owner, artifact, path):
        self.owner, self.artifact, self.path = owner, artifact, path
        self.digest, self.size, self.lines = sha256(), 0, 0
        self.stream = gzip.open(path, "rb") if path.suffix == ".gz" else path.open("rb")

    def read(self, size):
        data = self.stream.read(size)
        self.size += len(data)
        self.digest.update(data)
        self.lines += data.count(b"\n")
        self.owner.raw_returned += len(data)
        need(self.owner.raw_returned <= self.owner.budget.max_source_raw_bytes, "combined native raw budget exceeded")
        self.owner.check()
        return data

    def close(self):
        self.stream.close()

    def finish(self):
        need(self.read(1) == b"", "native parser did not consume source EOF")
        need(self.size == self.artifact.size_bytes and self.digest.hexdigest() == self.artifact.sha256,
             "complete native source SHA/bytes changed")
        receipt = {"artifact": encode(self.artifact), "raw_bytes_read": self.size,
                   "stored_bytes_read": self.path.stat().st_size, "newlines": self.lines,
                   "complete_raw_sha_verified": True, "complete_semantic_parse_performed": True}
        self.owner.raw_receipts.append(receipt)
        self.owner.emit({"stage": "native_source_verified", "schema": self.artifact.schema,
                         "raw_bytes": self.size, "lines": self.lines})


class _JSONStream:
    """Bounded incremental JSON tokens; no full ETO document is assembled."""
    def __init__(self, reader, maximum):
        self.reader, self.maximum = reader, maximum
        self.buffer, self.at, self.eof = "", 0, False
        self.utf8 = codecs.getincrementaldecoder("utf-8")()
        self.decoder = json.JSONDecoder(object_pairs_hook=_pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError("non-finite JSON source: " + value)))

    def more(self):
        self.buffer = self.buffer[self.at:]
        self.at = 0
        data = self.reader.read(65_536)
        self.eof = not data
        self.buffer += self.utf8.decode(data, final=self.eof)
        need(len(self.buffer.encode("utf-8")) <= self.maximum + 65_536, "ETO source record budget exceeded")

    def peek(self):
        while True:
            while self.at < len(self.buffer) and self.buffer[self.at] in " \t\r\n":
                self.at += 1
            if self.at < len(self.buffer):
                return self.buffer[self.at]
            if self.eof:
                return ""
            self.more()

    def take(self, token):
        need(self.peek() == token, "malformed complete ETO JSON delimiter: expected " + token)
        self.at += 1

    def value(self):
        self.peek()
        while True:
            try:
                value, end = self.decoder.raw_decode(self.buffer, self.at)
            except json.JSONDecodeError:
                need(not self.eof, "malformed/truncated complete ETO JSON value")
                self.more()
                continue
            if end == len(self.buffer) and not self.eof:
                self.more()
                continue
            # raw_decode may accept only the integer prefix of a split decimal
            # or exponent (e.g. the current buffer ends in "1e"). A complete
            # value requires a real JSON token boundary, not just decode success.
            if end < len(self.buffer) and self.buffer[end] not in ",]}: \t\r\n":
                need(not self.eof, "invalid JSON token boundary")
                self.more()
                continue
            need(len(self.buffer[self.at:end].encode("utf-8")) <= self.maximum, "ETO value budget exceeded")
            self.at = end
            return value


class _SourceIndex:
    """Live writer-owned, authenticated private navigation; no load constructor."""
    def __init__(self, out, budget, progress):
        self.out, self.budget, self.progress = out, budget, progress
        self.started = time.monotonic()
        self.raw_returned, self.spool_returned = 0, 0
        self.raw_receipts, self.archive_receipts = [], []
        self._key = secrets.token_bytes(32)
        self._expected_keys = defaultdict(set)
        self._closed_source = False
        private = out / "private"
        private.mkdir()
        self.path = private / "navigation.sqlite"
        self.db = sqlite3.connect(self.path)
        self.db.execute("PRAGMA journal_mode=OFF")
        self.db.execute("PRAGMA synchronous=OFF")
        self.db.execute("PRAGMA page_size=4096")
        page_size = self.db.execute("PRAGMA page_size").fetchone()[0]
        max_pages = budget.max_index_bytes // page_size
        need(max_pages >= 4, "private index budget cannot fit the SQLite header/table")
        actual_limit = self.db.execute("PRAGMA max_page_count=" + str(max_pages)).fetchone()[0]
        need(actual_limit == max_pages, "SQLite could not enforce the private index page cap")
        self.db.execute("CREATE TABLE records(kind TEXT,key TEXT,ordinal INTEGER,payload BLOB,mac BLOB,PRIMARY KEY(kind,key)) WITHOUT ROWID")
        self.parents, self.node_ordinals = {}, {}
        self.names, self.children, self.groups = defaultdict(list), defaultdict(list), defaultdict(list)
        self.physical_markers, self.births = {}, defaultdict(list)
        self.signatures, self.representatives = {}, {}
        self.classifications = {}
        self.declared_attempts = None
        self.operations = 0

    def emit(self, row):
        if self.progress:
            self.progress({"elapsed_s": time.monotonic() - self.started, **row})

    def check(self):
        need(time.monotonic() - self.started <= self.budget.max_wall_seconds, "batch whole wall budget exceeded")
        need(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss <= self.budget.max_rss_kib, "batch RSS budget exceeded")

    def put(self, kind, key, ordinal, record):
        self.check()
        key = str(key)
        raw = canonical(record)
        need(len(raw) <= self.budget.max_record_bytes, "private record envelope exceeds budget")
        seal = hmac.digest(self._key, canonical([kind, str(key), ordinal]) + b"\0" + raw, "sha256")
        try:
            self.db.execute("INSERT INTO records VALUES(?,?,?,?,?)", (kind, str(key), ordinal, raw, seal))
        except sqlite3.IntegrityError as error:
            raise ValueError("duplicate original indexed identity: " + kind + ":" + str(key)) from error
        self._expected_keys[kind].add(key)
        self.operations += 1
        if self.operations % 4096 == 0:
            self.db.commit()
            need(self.path.stat().st_size <= self.budget.max_index_bytes, "private index byte budget exceeded")
            self.check()

    def get(self, kind, key, optional=False):
        self.check()
        row = self.db.execute("SELECT ordinal,payload,mac FROM records WHERE kind=? AND key=?", (kind, str(key))).fetchone()
        if row is None:
            need(str(key) not in self._expected_keys[kind], "private navigation record disappeared")
            need(optional, "original indexed source record missing: " + kind + ":" + str(key))
            return None
        ordinal, raw, seal = row
        expected = hmac.digest(self._key, canonical([kind, str(key), ordinal]) + b"\0" + raw, "sha256")
        need(hmac.compare_digest(expected, seal), "private spool bytes or locator changed")
        self.spool_returned += len(raw)
        return _json(raw)

    def read_eto(self, artifact, path, pid):
        reader = _RawReader(self, artifact, path)
        parser = _JSONStream(reader, self.budget.max_record_bytes)
        header, keys, ordinal = {}, set(), 0
        try:
            parser.take("{")
            while parser.peek() != "}":
                key = parser.value()
                need(type(key) is str and key not in keys, "duplicate/non-string ETO document key")
                keys.add(key)
                parser.take(":")
                if key == "nodes":
                    parser.take("[")
                    while parser.peek() != "]":
                        node = parser.value()
                        need(type(node) is dict and type(node.get("id")) is int and type(node.get("ctrl_deps")) is int
                             and type(node.get("name")) is str, "invalid complete ETO node identity")
                        node_id = node["id"]
                        need(node_id not in self.parents, "duplicate ETO node ID")
                        attributes(node)
                        self.put("node", node_id, ordinal, node)
                        self.parents[node_id], self.node_ordinals[node_id] = node["ctrl_deps"], ordinal
                        self.names[node["name"]].append(node_id)
                        self.children[node["ctrl_deps"]].append(node_id)
                        ordinal += 1
                        if parser.peek() != ",":
                            break
                        parser.take(",")
                        need(parser.peek() != "]", "ETO nodes trailing comma")
                    parser.take("]")
                else:
                    header[key] = parser.value()
                if parser.peek() != ",":
                    break
                parser.take(",")
                need(parser.peek() != "}", "ETO document trailing comma")
            parser.take("}")
            need(parser.peek() == "", "unexpected data after complete ETO document")
            need("nodes" in keys and type(header.get("pid")) is int and header["pid"] == pid
                 and header.get("schema") == "1.1.1-chakra.0.0.4",
                 "complete ETO header/profile differs")
            reader.finish()
        finally:
            reader.close()
        root = self.get("node", 1)
        need(root["ctrl_deps"] == 1 and root["name"] == "[pytorch|profiler|execution_trace|process]"
             and attributes(root).get("rf_id") == 0 and attributes(root).get("tid") == 0
             and attributes(root).get("scope") == 7, "original ETO root sentinel differs")
        done = set()
        for node_id in self.parents:
            chain, seen, current = [], set(), node_id
            while current not in done:
                need(current in self.parents and current not in seen, "original ETO parent missing or cyclic")
                seen.add(current)
                chain.append(current)
                parent = self.parents[current]
                if parent == current:
                    need(current == 1, "unexpected original self-parent ETO root")
                    break
                current = parent
            done.update(chain)

    def read_lines(self, kind, artifact, path, pid, nonce=None):
        reader = _RawReader(self, artifact, path)
        pending, index = bytearray(), 0
        try:
            while data := reader.read(65_536):
                pending.extend(data)
                while (end := pending.find(b"\n")) >= 0:
                    raw = bytes(pending[:end + 1])
                    del pending[:end + 1]
                    need(len(raw) <= self.budget.max_record_bytes, "native JSONL record byte budget exceeded")
                    row = _json(raw)
                    index += 1
                    need(type(row) is dict and type(row.get("index")) is int and row["index"] == index
                         and type(row.get("process_id")) is int and row["process_id"] == pid,
                         "native JSONL ordinal/process differs")
                    if nonce is not None:
                        need(row.get("nonce") == nonce and row.get("schema") == "scar.tensor-physical-observation"
                             and row.get("schema_version") == 1, "physical row nonce/schema differs")
                    self.put(kind, index, index, row)
                    if kind == "dispatch":
                        seq = row.get("sequence")
                        need(type(seq) is int and seq > 0, "dispatch source sequence is not a positive exact integer")
                        self.groups[seq].append(index)
                    elif row.get("kind") == "MARKER":
                        marker = row.get("marker")
                        need(type(marker) is str and marker not in self.physical_markers, "duplicate/non-string original physical marker")
                        self.physical_markers[marker] = index
                    elif row.get("kind") == "ALLOCATION" and row.get("alloc_size", 0) > 0:
                        epoch = (row["device"]["text"], row["provider_allocation_id"])
                        self.births[epoch].append(index)
                need(len(pending) <= self.budget.max_record_bytes, "unterminated native JSONL record over budget")
            need(not pending, "native JSONL final line is not closed")
            reader.finish()
        finally:
            reader.close()
        return index

    def scan_archive(self, partitions):
        for graph, table in (("evidence", "instances"), ("values", "objects"), ("values", "regions"), ("values", "allocations")):
            chunks = partitions.manifest["graphs"][graph]["tables"][table]["chunks"]
            for row in partitions.iter_records(graph, table):
                record = row["record"]
                meta = record.get("metadata", {})
                key = None
                if table == "instances" and meta.get("provider") == "ETO":
                    key = meta.get("node_id")
                elif table == "objects":
                    key = meta.get("weak_token")
                elif table == "regions" and type(meta.get("physical_observation")) is str:
                    key = meta["physical_observation"] + ":" + str(meta["argument_ordinal"])
                elif table == "allocations":
                    key = record["id"]["value"]
                if key is not None:
                    self.put("archive:" + table, key, row["ordinal"], row)
            self.archive_receipts.append({"graph": graph, "table": table, "chunks": len(chunks),
                "decoded_bytes": sum(c["decoded_bytes"] for c in chunks),
                "stored_bytes": sum(c["physical_bytes"] for c in chunks),
                "whole_chunks_verified_by_BundlePartitions": True})
            self.emit({"stage": "archive_table_indexed", **self.archive_receipts[-1]})
        self.db.commit()
        need(self.path.stat().st_size <= self.budget.max_index_bytes, "closed private index over budget")

    def source_for(self, sequences, definitions=False):
        need(self._closed_source, "live native source acquisition has not closed")
        need(sequences and tuple(sorted(set(sequences))) == tuple(sequences), "shard sequence selection differs")
        dispatch = [self.get("dispatch", line) for seq in sequences for line in self.groups[seq]]
        selected_nodes, physical_lines = set(), set()
        for row in dispatch:
            marker = row.get("marker")
            for node_id in self.names.get(marker, ()):
                selected_nodes.add(node_id)
                if row.get("kind") == "DISPATCH_BEGIN":
                    selected_nodes.update(self.children.get(node_id, ()))
            if marker in self.physical_markers:
                physical_lines.add(self.physical_markers[marker])
        for node_id in tuple(selected_nodes):
            current = node_id
            while True:
                selected_nodes.add(current)
                parent = self.parents[current]
                if parent == current:
                    break
                current = parent
        physical = [self.get("physical", line) for line in sorted(physical_lines)]
        births = set()
        for row in physical:
            for argument in row.get("arguments", ()):
                metadata = argument.get("metadata") or {}
                epoch = ((metadata.get("device") or {}).get("text"), metadata.get("provider_allocation_id"))
                births.update(self.births.get(epoch, ()))
        physical.extend(self.get("physical", line) for line in sorted(births - physical_lines))
        source = {**self.base, "first_sequence": sequences[0],
            "max_sequences": sequences[-1] - sequences[0] + 1,
            "nodes": [self.get("node", n) for n in sorted(selected_nodes, key=self.node_ordinals.__getitem__)],
            "root_node": self.get("node", 1), "dispatch": dispatch, "physical": physical,
            "node_ordinals": {str(n): self.node_ordinals[n] for n in selected_nodes}}
        if definitions:
            source["definition_signatures"] = self.signatures
        need(len(canonical(source)) <= self.budget.max_shard_source_bytes, "shard detached raw closure byte budget exceeded")
        return source

    def selected(self, source, interfaces):
        selected = {("evidence", "instances"): [], ("values", "objects"): [],
                    ("values", "regions"): [], ("values", "allocations"): []}
        for node in source["nodes"]:
            row = self.get("archive:instances", node["id"], optional=True)
            if row is None:
                raise _MissingDependency("original ETO archive instance missing")
            need(row["ordinal"] == self.node_ordinals[node["id"]],
                 "original ETO archive ordinal differs from actual nodes-array position")
            selected["evidence", "instances"].append(row)
        keys = {"objects": set(), "regions": set(), "allocations": set()}
        for interface in interfaces:
            for ports in interface["ports"].values():
                for port in ports:
                    if not port["tensor"]:
                        continue
                    held = port["held"]
                    keys["objects"].add(held["weak_token"])
                    locator = "sha256:" + source["artifacts"]["physical"]["sha256"] + "#line/" + str(held["physical_line"]) + "/arguments/" + str(held["marker_ordinal"])
                    key = locator + ":" + str(held["marker_ordinal"])
                    keys["regions"].add(key)
                    row = self.get("archive:regions", key, optional=True)
                    if row is None:
                        raise _MissingDependency("original physical region record missing")
                    keys["allocations"].add(row["record"]["allocation"]["value"])
                    epoch = (held["metadata"]["device"]["text"], held["metadata"]["provider_allocation_id"])
                    births = self.births.get(epoch, ())
                    if not births:
                        raise _MissingDependency("physical epoch has no original positive birth")
                    need(len(births) == 1, "physical epoch has contradictory duplicate original positive births")
        for table, table_keys in keys.items():
            for key in sorted(table_keys):
                row = self.get("archive:" + table, key, optional=True)
                if row is None:
                    raise _MissingDependency("original projected " + table + " record missing")
                selected["values", table].append(row)
        for rows in selected.values():
            rows.sort(key=lambda row: row["ordinal"])
        return selected

    def inventory(self, seq):
        rows = [self.get("dispatch", line) for line in self.groups[seq]]
        roles = {}
        for row in rows:
            roles.setdefault(row.get("kind", "UNKNOWN"), []).append({"artifact": self.base["artifacts"]["dispatch"],
                "locator": "#line/" + str(row["index"]), "index": row["index"]})
        begins = [r for r in rows if r.get("kind") == "DISPATCH_BEGIN"]
        ends = [r for r in rows if r.get("kind") == "DISPATCH_END"]
        return {"sequence": seq, "source_rows": roles,
            "operator": begins[0].get("operator") if len(begins) == 1 else None,
            "outcome": ends[0].get("outcome") if len(ends) == 1 else None,
            "begin_count": len(begins), "end_count": len(ends)}


def _acquire(coordinates, capture_directory, manifest, capture_model_path, out, budget,
             expected_manifest_sha256, expected_capture_model_sha256, progress, owner):
    root = Path(capture_directory).resolve()
    inputs = _members(coordinates, root)
    partitions = BundlePartitions(manifest)
    need(partitions.manifest_receipt["physical_sha256"] == expected_manifest_sha256, "native archive manifest changed")
    model, model_raw = _metadata(Path(capture_model_path).resolve(), budget.max_metadata_bytes)
    need(sha256(model_raw).hexdigest() == expected_capture_model_sha256, "capture-model hint changed")
    native = model["native"]
    need(native["provider_revision"] == PROVIDER_REVISION and native["pid"] == coordinates.target_process.pid,
         "native archive process/provider differs")
    documents = {}
    for schema in ("scar.execution-evidence-collection", "scar.dispatch-observation-trace", "scar.tensor-physical-trace"):
        artifact, path = inputs[schema]
        doc, raw = _metadata(path, budget.max_metadata_bytes)
        need(len(raw) == artifact.size_bytes and sha256(raw).hexdigest() == artifact.sha256,
             "participating source metadata bytes changed")
        documents[schema] = doc
    collector, dispatch, physical = (documents[s] for s in (
        "scar.execution-evidence-collection", "scar.dispatch-observation-trace", "scar.tensor-physical-trace"))
    need(collector.get("status") == "CLOSED" and not collector.get("failures")
         and collector["provider"]["torch_git_version"] == PROVIDER_REVISION
         and dispatch.get("profile") == "scar.dispatch-marker-collector-v1"
         and dispatch.get("provider_revision") == PROVIDER_REVISION and not dispatch.get("gaps")
         and not dispatch.get("errors") and dispatch.get("dropped_events") == 0
         and physical.get("profile") == "scar.tensor-physical-event-tree-v1"
         and physical.get("provider_revision") == PROVIDER_REVISION and physical.get("traversal_completed") is True
         and physical.get("marker_ordered_slot_correspondence_established") is True
         and physical.get("allocation_receipt_traversal_complete") is True
         and not physical.get("errors") and not physical.get("gaps") and physical.get("frontier") is None,
         "participating collector/profile is not closed and qualified")
    pid, nonce = dispatch["process_id"], dispatch["nonce"]
    need(pid == physical["process_id"] == collector["pid"] == coordinates.target_process.pid
         and nonce == physical["nonce"], "participating metadata process/nonce differs")
    schemas = {"eto": "pytorch.execution-trace.v1", "dispatch": "scar.dispatch-observation.events.v1",
               "physical": "scar.tensor-physical-observation.v1"}
    for label, schema in (("native_manifest", "scar.execution-evidence-collection"),
                          ("dispatch_metadata", "scar.dispatch-observation-trace"),
                          ("dispatch_observations", schemas["dispatch"])):
        declaration, artifact = physical["inputs"][label], inputs[schema][0]
        need((declaration["path"], declaration["raw_sha256"], declaration["raw_bytes"])
             == (artifact.uri, artifact.sha256, artifact.size_bytes), "physical metadata exact input link differs")
    declaration, artifact = dispatch["native_manifest"], inputs["scar.execution-evidence-collection"][0]
    need((declaration["path"], declaration["raw_sha256"], declaration["raw_bytes"])
         == (artifact.uri, artifact.sha256, artifact.size_bytes), "dispatch native manifest link differs")
    for key, doc in (("dispatch", dispatch), ("physical", physical)):
        artifact, declared = inputs[schemas[key]][0], doc["file"]
        need((declared["path"], declared["raw_sha256"], declared["raw_bytes"])
             == (artifact.uri, artifact.sha256, artifact.size_bytes), "closed source declaration differs")
    kineto = [r["artifact"] for r in coordinates.report["membership"] if r["artifact"]["schema"] == "pytorch.kineto.chrome-trace.v1"]
    need(len(kineto) == 1, "source has no unique Kineto coordinate member")
    scope = "native:" + sha256(canonical({"eto": inputs[schemas["eto"]][0].sha256,
        "kineto": kineto[0]["sha256"], "revision": PROVIDER_REVISION, "pid": pid})).hexdigest()
    physical_scope = "tensor-physical:" + sha256(canonical({"native_scope": scope,
        "profile": physical["profile"], "artifact": encode(inputs[schemas["physical"]][0]),
        "metadata": encode(inputs["scar.tensor-physical-trace"][0])})).hexdigest()
    need(scope == native["scope"] and physical_scope == native["tensor_physical"]["scope"], "original qualified source namespace differs")
    total = sum(inputs[s][0].size_bytes for s in schemas.values())
    need(total <= budget.max_source_raw_bytes, "native declared raw budget exceeded")
    owner.declared_attempts = dispatch["dispatch_attempts"]
    need(type(owner.declared_attempts) is int and owner.declared_attempts >= 0, "declared dispatch count is not an exact nonnegative integer")
    owner.base = {"pid": pid, "nonce": nonce, "provider_revision": PROVIDER_REVISION,
        "run": coordinates.run.id.value, "coordinate_artifact": encode(coordinates.artifact),
        "owner_native_tid": dispatch["owner_native_tid"], "owner_python_ident": dispatch["owner_python_ident"],
        "native_scope": scope, "physical_scope": physical_scope, "physical_profile": physical["profile"],
        "artifacts": {key: encode(inputs[schema][0]) for key, schema in schemas.items()}}
    owner.read_eto(*inputs[schemas["eto"]], pid)
    dispatch_lines = owner.read_lines("dispatch", *inputs[schemas["dispatch"]], pid)
    physical_lines = owner.read_lines("physical", *inputs[schemas["physical"]], pid, nonce)
    need(len(owner.parents) == native["inventory"]["eto_nodes"], "complete ETO count differs from archive hint")
    need(dispatch_lines == dispatch["file"]["lines"] and physical_lines == physical["file"]["lines"], "closed complete source row counts differ")
    owner.scan_archive(partitions)
    owner._closed_source = True
    owner.manifest_receipt = partitions.manifest_receipt
    return owner


def _write_json(path, doc, maximum=None):
    raw = canonical(doc)
    need(maximum is None or len(raw) <= maximum, "JSON report byte budget exceeded before publication")
    return _write(path, raw)


def _check_group_identity(source):
    """Known identities reject before any missing-physical/slot frontier.

    This checks declarations and already present cross-references only. It does
    not invent a missing node, physical marker, argument or completion.
    """
    from scar.trace.native_schema import parse_schema_ports
    pid, nonce = source["pid"], source["nonce"]
    absence = None
    by_sequence = defaultdict(dict)
    for row in source["dispatch"]:
        seq, kind = row["sequence"], row.get("kind")
        need(kind in ("DISPATCH_BEGIN", "DISPATCH_OUTPUT", "DISPATCH_END"), "unknown original dispatch row kind")
        group = by_sequence[seq]
        need(kind not in group, "duplicate original dispatch row role")
        group[kind] = row
        if kind == "DISPATCH_END":
            need(row.get("outcome") in ("RETURNED", "RAISED") and type(row.get("span_enter_returned")) is bool,
                 "dispatch END outcome/span declaration differs")
            continue
        phase = "span" if kind == "DISPATCH_BEGIN" else "output"
        need(row.get("marker") == f"scar-dispatch:{nonce}:{pid}:{seq}:{phase}",
             "dispatch marker nonce/process/sequence/phase differs")
        obs = row.get("observation", {})
        need(type(obs.get("process_id")) is int and obs["process_id"] == pid
             and type(obs.get("native_tid")) is int and obs["native_tid"] == source["owner_native_tid"]
             and type(obs.get("python_ident")) is int and obs["python_ident"] == source["owner_python_ident"],
             "dispatch observation process/thread owner differs")
    names = defaultdict(list)
    for node in source["nodes"]:
        names[node["name"]].append(node)
    physical = {r["marker"]: r for r in source["physical"] if r.get("kind") == "MARKER"}
    for seq, group in by_sequence.items():
        begin, output, end = (group.get(k) for k in ("DISPATCH_BEGIN", "DISPATCH_OUTPUT", "DISPATCH_END"))
        if end is not None:
            if end["span_enter_returned"]:
                need(begin is not None, "END claims an unobserved entered BEGIN")
            if end.get("output_marker") is not None:
                need(output is not None and end["output_marker"] == output["marker"]
                     and end["outcome"] == "RETURNED" and end["span_enter_returned"],
                     "END names another or unsuccessful original output marker")
            if end["outcome"] == "RAISED":
                need(output is None and end.get("output_marker") is None,
                     "raised dispatch has a contradictory normal output")
        known_nodes = {}
        for row in (begin, output):
            if row is None:
                continue
            matches = names.get(row["marker"], ())
            need(len(matches) <= 1, "duplicate original ETO dispatch marker")
            if matches:
                known_nodes[row["kind"]] = matches[0]
            marker = physical.get(row["marker"])
            if marker is None:
                continue
            for field, expected in (("dispatch_source_line", row["index"]), ("sequence", seq),
                                    ("dispatch_native_tid", source["owner_native_tid"]),
                                    ("dispatch_python_ident", source["owner_python_ident"])):
                if marker.get(field) is not None:
                    need(marker[field] == expected, "known physical marker source identity differs: " + field)
            if matches:
                attrs, event = attributes(matches[0]), marker.get("event") or {}
                for field, expected in (("record_function_thread_token", attrs.get("tid")),
                                        ("correlation_id", attrs.get("rf_id"))):
                    if event.get(field) is not None:
                        need(event[field] == expected, "known physical marker ETO identity differs: " + field)
        span = known_nodes.get("DISPATCH_BEGIN")
        result = known_nodes.get("DISPATCH_OUTPUT")
        if span is not None and result is not None:
            need(result["ctrl_deps"] == span["id"] and attributes(result).get("tid") == attributes(span).get("tid"),
                 "known output marker has another native parent/thread")
        if span is not None:
            candidates = []
            for child in source["nodes"]:
                raw = attributes(child).get("op_schema")
                if child["ctrl_deps"] == span["id"] and type(raw) is str and raw:
                    schema, _, _ = parse_schema_ports(raw)
                    key = schema.name.replace("::", ".") + "." + (schema.overload_name or "default")
                    if begin is not None and key == begin.get("operator"):
                        candidates.append(child)
                        need(child["name"] == schema.name and attributes(child).get("tid") == attributes(span).get("tid"),
                             "known matching native child label/thread contradicts span/schema")
            need(len(candidates) <= 1, "ambiguous matching direct native schema children")
        else:
            candidates = []
        normal = (begin is not None and output is not None and end is not None
                  and end["outcome"] == "RETURNED" and end["span_enter_returned"]
                  and not begin.get("slot_gaps") and not output.get("slot_gaps")
                  and str(begin.get("operator", "")).startswith("aten."))
        if normal:
            if span is None or result is None:
                absence = {"reason": "ORIGINAL_ETO_MARKER_UNAVAILABLE", "sequence": seq,
                           "missing_markers": [r["marker"] for r in (begin, output) if not names.get(r["marker"])]}
            elif not candidates:
                absence = {"reason": "DIRECT_SCHEMA_NATIVE_CHILD_UNAVAILABLE", "sequence": seq,
                           "operator": begin.get("operator")}
    return absence


def _unavailable_physical(source):
    """Absence has a frontier; contradictory qualified records still reject."""
    rows = source["dispatch"]
    if ([r.get("kind") for r in rows] != ["DISPATCH_BEGIN", "DISPATCH_OUTPUT", "DISPATCH_END"]
            or not str(rows[0].get("operator", "")).startswith("aten.")
            or rows[-1].get("outcome") != "RETURNED"):
        return None
    physical = {r["marker"]: r for r in source["physical"] if r.get("kind") == "MARKER"}
    for row in rows[:2]:
        marker = physical.get(row.get("marker"))
        if marker is None:
            return {"reason": "PHYSICAL_MARKER_UNAVAILABLE", "dispatch_line": row["index"]}
        if marker.get("gaps"):
            return {"reason": "PHYSICAL_MARKER_GAPS", "physical_line": marker["index"], "gaps": marker["gaps"]}
        for arg in marker.get("arguments", ()):
            meta = arg.get("metadata") or {}
            if meta.get("status") != "OBSERVED" or meta.get("gaps") or type(meta.get("provider_allocation_id")) is not int:
                return {"reason": "PHYSICAL_TENSOR_METADATA_UNAVAILABLE", "physical_line": marker["index"],
                        "argument_ordinal": arg.get("argument_ordinal"), "metadata_status": meta.get("status"),
                        "metadata_gaps": meta.get("gaps")}
    return None


def bind_native_capture_batches(coordinates, capture_directory, partitioned_native_manifest, out_dir, *,
                                expected_manifest_sha256, capture_model_path, expected_capture_model_sha256,
                                budget=NativeCaptureBatchBudget(), progress=None):
    """Verify once and account for every actually enumerated dispatch group.

    Coordinates must already be freshly bound by the ordinary public binder.
    This call does not execute the target or restore a serialized owner.
    """
    from scar.ir.program.codec import dumps as program_dumps
    from scar.ir.execution.codec import dumps as execution_dumps
    from scar.ir.execution.validation import validate
    need(type(budget) is NativeCaptureBatchBudget, "exact native batch budget required")
    budget.__post_init__()
    out = Path(out_dir).resolve()
    need(not out.exists(), "native batch output must be fresh")
    out.mkdir(parents=True)
    started, owner = time.monotonic(), None
    try:
        owner = _SourceIndex(out, budget, progress)
        owner = _acquire(coordinates, capture_directory, partitioned_native_manifest, capture_model_path, out, budget,
                         expected_manifest_sha256, expected_capture_model_sha256, progress, owner)
        sequences = tuple(sorted(owner.groups))
        observed = [owner.inventory(seq) for seq in sequences]
        observed_bytes = b"".join(canonical(row) + b"\n" for row in observed)
        need(len(observed_bytes) <= budget.max_inventory_bytes and len(observed_bytes) <= budget.max_output_bytes,
             "observed inventory byte budget exceeded before publication")
        _write(out / "observed-dispatches.jsonl", observed_bytes)
        enumerated_begins = sum(row["begin_count"] for row in observed)
        source_complete = (len(sequences) == enumerated_begins == owner.declared_attempts
                           and all(seq == i for i, seq in enumerate(sequences, 1))
                           and all(row["begin_count"] == 1 for row in observed))
        owner.emit({"stage": "dispatch_domain_enumerated", "declared_attempts": owner.declared_attempts,
                    "actual_groups": len(sequences), "actual_begin_rows": enumerated_begins,
                    "source_domain_complete": source_complete})
        for count, seq in enumerate(sequences, 1):
            if count % 256 == 0:
                owner.check()
                owner.emit({"stage": "dispatch_discovery", "visited_actual_groups": count - 1,
                            "static_signatures": len(owner.signatures)})
            source = owner.source_for((seq,))
            absent_native = _check_group_identity(source)
            if absent_native is not None:
                owner.classifications[seq] = {"state": "FRONTIER", **absent_native}
                continue
            unavailable = _unavailable_physical(source)
            if unavailable is not None:
                owner.classifications[seq] = {"state": "FRONTIER", **unavailable}
                continue
            interfaces, frontiers = replay_interfaces(source)
            if interfaces:
                interface = interfaces[0]
                # Missing original projected dependencies remain explicit; a
                # contradictory full record will reject in _project, not pass.
                try:
                    owner.selected(source, interfaces)
                except _MissingDependency as error:
                    owner.classifications[seq] = {"state": "FRONTIER", "reason": "ORIGINAL_REFERENCE_DEPENDENCY_UNAVAILABLE", "detail": str(error)}
                    continue
                leaves = sum(p["tensor"] for ports in interface["ports"].values() for p in ports)
                flat_leaves = sum(len(ports) for ports in interface["ports"].values())
                if leaves > budget.max_shard_tensor_leaves or flat_leaves > budget.max_shard_flat_leaves:
                    owner.classifications[seq] = {"state": "FRONTIER", "reason": "SINGLE_INVOCATION_FLAT_LEAF_BUDGET",
                                                  "tensor_leaves": leaves, "flat_leaves": flat_leaves}
                    continue
                sig = interface["signature_id"]
                owner.signatures.setdefault(sig, interface["signature"])
                owner.representatives.setdefault(sig, interface)
                owner.classifications[seq] = {"state": "READY", "signature_id": sig,
                                              "tensor_leaves": leaves, "flat_leaves": flat_leaves}
            else:
                need(len(frontiers) == 1, "actual group did not yield exactly one classification")
                owner.classifications[seq] = {"state": "FRONTIER", **frontiers[0]}
        definitions = {sig: owner.signatures[sig] for sig in sorted(owner.signatures)}
        interface_doc = {"schema": "scar.pinned-aten-protocol-interface", "schema_version": 1,
            "profile": PROFILE, "interfaces": definitions,
            "effect_contract": "UNKNOWN outside partial provider schema annotations", "content_version_claimed": False}
        interface_bytes = canonical(interface_doc)
        need(len(interface_bytes) <= budget.max_interface_bytes, "shared interface byte budget exceeded before publication")
        need(len(observed_bytes) + len(interface_bytes) <= budget.max_output_bytes, "shared interface exceeds remaining output budget")
        interface_artifact = _artifact(out / "native-interface.json", interface_bytes, interface_doc["schema"])
        _write(out / "native-interface.json", interface_bytes)
        program_source = {**owner.base, "max_sequences": owner.declared_attempts}
        representatives = [owner.representatives[sig] for sig in sorted(owner.representatives)]
        program, layouts = _build_program(representatives, program_source, interface_artifact)
        program_bytes = program_dumps(program).encode()
        need(len(program_bytes) <= budget.max_program_bytes, "shared static program byte budget exceeded")
        need(len(observed_bytes) + len(interface_bytes) + len(program_bytes) <= budget.max_output_bytes,
             "shared program exceeds remaining output budget")
        program_artifact = _artifact(out / "program.json", program_bytes, "scar.program-graph")
        _write(out / "program.json", program_bytes)
        shard_reports, first_shard, output_total = [], None, len(program_bytes) + len(interface_bytes) + len(observed_bytes)
        pending = []

        def emit_shard(selected_sequences):
            nonlocal first_shard, output_total
            owner.check()
            shard_started = time.monotonic()
            source = owner.source_for(tuple(selected_sequences), definitions=True)
            interfaces, frontiers = replay_interfaces(source)
            expected = {seq for seq in selected_sequences if owner.classifications[seq]["state"] == "READY"}
            interfaces = [i for i in interfaces if i["sequence"] in expected]
            need({i["sequence"] for i in interfaces} == expected, "source replay changed during shard construction")
            if not interfaces:
                return
            selected = owner.selected(source, interfaces)
            shard_dir = out / "shards" / f"{len(shard_reports):06d}"
            values, evidence, va, ea, geometry, payloads = _prepare_projection(source, interfaces, selected, shard_dir, budget)
            execution = _build_execution(program, layouts, interfaces, source, coordinates, program_artifact, va, ea)
            execution_bytes = execution_dumps(execution).encode()
            need(len(execution_bytes) <= budget.max_shard_execution_bytes and va.size_bytes <= budget.max_shard_values_bytes
                 and ea.size_bytes <= budget.max_shard_evidence_bytes, "materialized shard byte budget exceeded")
            # Only actual selected interfaces enter this lease; other sequence
            # groups keep their inventory/frontier without an invented activation.
            source["definition_signatures"] = definitions
            source["selected_sequences"] = sorted(expected)
            owned = _own_capture(source)
            native = _make_evidence(owned, program, execution, va, ea)
            catalogs = {"value_graphs": {va.sha256: values}, "evidence_graphs": {ea.sha256: evidence},
                        "artifact_bytes": {interface_artifact.sha256: interface_bytes}, "native_port_evidence": native}
            validation = validate(execution, program, **catalogs)
            validation_doc = {"valid": validation.valid, "issues": [encode(i) for i in validation.issues],
                              "gaps": [encode(g) for g in validation.gaps]}
            need(validation.valid, "actual shard validation failed: " + json.dumps(validation_doc["issues"][:10], sort_keys=True))
            artifact = _artifact(shard_dir / "execution.json", execution_bytes, "scar.execution-model")
            report = {"schema": "scar.native-capture-execution-shard", "schema_version": 1,
                "status": "REFERENCE_PORTS_VERIFIED", "sequences": sorted(expected),
                "program_snapshot": encode(execution.snapshot), "execution": encode(artifact),
                "values_projection": encode(va), "evidence_projection": encode(ea),
                "signature_ids": sorted({i["signature_id"] for i in interfaces}),
                "actual_activations": len(execution.activations), "tensor_denotations": len(execution.denotations),
                "physical_associations": len(geometry), "gap_counts": dict(Counter(g.code for g in validation.gaps)),
                "wall_seconds": time.monotonic() - shard_started}
            payloads.update({"execution.json": execution_bytes, "validation.json": canonical(validation_doc),
                             "report.json": canonical(report)})
            caps = {"source-values.json": budget.max_shard_values_bytes, "source-evidence.json": budget.max_shard_evidence_bytes,
                    "source-projection-receipts.json": budget.max_shard_receipt_bytes,
                    "execution.json": budget.max_shard_execution_bytes, "validation.json": budget.max_report_bytes,
                    "report.json": budget.max_report_bytes}
            for name, raw in payloads.items():
                need(len(raw) <= caps[name], "shard file byte budget exceeded before publication: " + name)
            shard_size = sum(map(len, payloads.values()))
            need(output_total + shard_size <= budget.max_output_bytes, "shard exceeds remaining published output budget")
            owner.check()
            need(report["wall_seconds"] <= budget.max_shard_seconds, "materialized shard wall budget exceeded")
            for name, raw in payloads.items():
                _write(shard_dir / name, raw)
            output_total += shard_size
            for interface in interfaces:
                seq = interface["sequence"]
                owner.classifications[seq] = {"state": "QUALIFIED_REFERENCE_NORMAL", "signature_id": interface["signature_id"],
                    "shard": str(shard_dir.relative_to(out)), "execution": encode(artifact),
                    "activation_id": "native-port:" + owner.base["run"] + ":" + str(seq)}
            shard_reports.append(report)
            if first_shard is None:
                first_shard = NativeProtocolWindowResult(shard_dir, program, execution, values, evidence, native, validation, report)
            owner.emit({"stage": "actual_shard_verified", "number": len(shard_reports) - 1,
                        "activations": len(execution.activations), "tensor_denotations": len(execution.denotations)})

        leaves, flat_leaves = 0, 0
        for seq in sequences:
            item = owner.classifications[seq]
            if item["state"] != "READY":
                continue
            if pending and (len(pending) >= budget.max_shard_attempts
                            or seq != pending[-1] + 1 or leaves + item["tensor_leaves"] > budget.max_shard_tensor_leaves
                            or flat_leaves + item["flat_leaves"] > budget.max_shard_flat_leaves):
                emit_shard(pending)
                pending, leaves, flat_leaves = [], 0, 0
            pending.append(seq)
            leaves += item["tensor_leaves"]
            flat_leaves += item["flat_leaves"]
        if pending:
            emit_shard(pending)
        inventory = [{**row, **owner.classifications[row["sequence"]]} for row in observed]
        need(all(row["state"] != "READY" for row in inventory), "unmaterialized actual dispatch remains")
        inventory_bytes = b"".join(canonical(row) + b"\n" for row in inventory)
        need(len(inventory_bytes) <= budget.max_inventory_bytes and output_total + len(inventory_bytes) <= budget.max_output_bytes,
             "final dispatch inventory budget exceeded before publication")
        inventory_artifact = _artifact(out / "dispatch-inventory.jsonl", inventory_bytes, "scar.native-dispatch-inventory")
        _write(out / "dispatch-inventory.jsonl", inventory_bytes)
        qualified = sum(row["state"] == "QUALIFIED_REFERENCE_NORMAL" for row in inventory)
        frontier = sum(row["state"] == "FRONTIER" for row in inventory)
        need(qualified + frontier == len(sequences), "actual dispatch accounting mismatch")
        report = {"schema": "scar.native-capture-batch", "schema_version": 1,
            "status": "SOURCE_DOMAIN_ACCOUNTED" if source_complete else "OPEN_SOURCE_DOMAIN_MISMATCH",
            "run": owner.base["run"], "coordinates": encode(coordinates.artifact),
            "source_manifest": owner.manifest_receipt, "raw_reads": owner.raw_receipts,
            "source_raw_acquisitions": 1, "coordinate_binds_inside_batch": 0,
            "declared_dispatch_attempts": owner.declared_attempts,
            "enumerated_dispatch_groups": len(sequences), "enumerated_begin_rows": enumerated_begins,
            "enumerated_begin_groups": sum(row["begin_count"] > 0 for row in observed),
            "actual_sequence_ids": list(sequences), "source_domain_complete": source_complete,
            "qualified_dispatches": qualified, "frontier_dispatches": frontier,
            "frontier_counts": dict(Counter(row["reason"] for row in inventory if row["state"] == "FRONTIER")),
            "unvisited_actual_groups": 0, "declared_minus_enumerated_begins": owner.declared_attempts - enumerated_begins,
            "unvisited_declared_sequences": 0 if source_complete else None,
            "dispatch_inventory": encode(inventory_artifact), "static_interfaces": len(definitions),
            "shared_program": encode(program_artifact), "shared_interface": encode(interface_artifact),
            "shards": shard_reports, "archive_reads": owner.archive_receipts,
            "native_raw_bytes_returned": owner.raw_returned, "private_spool_bytes_returned": owner.spool_returned,
            "private_index_bytes": owner.path.stat().st_size,
            "wall_seconds": time.monotonic() - started, "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "logical_contents_established": False, "complete_state_effects_established": False,
            "alias_completeness_established": False, "resource_readiness_established": False,
            "whole_model_established": False, "transformation_authorized": False,
            "target_executions": 0, "compile_calls": 0, "prepare_calls": 0}
        published = sum(p.stat().st_size for p in out.rglob("*") if p.is_file() and "private" not in p.relative_to(out).parts)
        report["published_bytes_before_report"] = published
        need(len(canonical(report)) <= budget.max_report_bytes and published + len(canonical(report)) <= budget.max_output_bytes,
             "final report/publication byte budget exceeded before publication")
        _write_json(out / "report.json", report)
        owner.check()
        return NativeCaptureBatchResult(out, program, report, first_shard)
    except BaseException as error:
        import traceback
        failure = {"status": "INCOMPLETE_NATIVE_CAPTURE_BATCH", "error_type": type(error).__name__,
            "message": str(error), "traceback": traceback.format_exc(), "wall_seconds": time.monotonic() - started,
            "whole_model_established": False, "target_executions": 0}
        if owner is not None:
            failure.update(raw_reads=owner.raw_receipts, declared_dispatch_attempts=owner.declared_attempts,
                           classified_actual_groups=len(owner.classifications), enumerated_dispatch_groups=len(owner.groups))
        _write_json(out / "failure.json", failure, budget.max_report_bytes)
        raise
    finally:
        if owner is not None:
            owner.db.close()


__all__ = ["NativeCaptureBatchBudget", "NativeCaptureBatchResult", "bind_native_capture_batches"]
