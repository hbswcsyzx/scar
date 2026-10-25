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
    PROFILE_V2, SCALAR_INPUT_CAPABILITY, SCALAR_INPUT_CAPABILITIES, _make_evidence, _own_capture, _prepare_native_catalog, attributes, canonical, need, replay_batch_interfaces,
)
from scar.trace.native_protocol import (
    NativeProtocolWindowResult, _artifact, _build_execution, _build_program,
    _members, _metadata, _prepare_projection, _write,
)
from scar.trace.native_schema import PROVIDER_REVISION
from scar.store.bundle_partitions import BundlePartitions

PARENT_CLOSURE_CAPABILITY = 'SELECTED_NATIVE_PARENT_CLOSURE_V1'


@dataclass(frozen=True)
class NativeCaptureBatchBudget:
    max_source_raw_bytes: int = 600_000_000
    max_metadata_bytes: int = 4_000_000
    max_record_bytes: int = 4_000_000
    max_index_bytes: int = 4_000_000_000
    max_program_bytes: int = 64_000_000
    max_interface_bytes: int = 16_000_000
    max_inventory_chunk_bytes: int = 8_000_000
    max_inventory_chunk_rows: int = 1000
    max_inventory_manifest_bytes: int = 4_000_000
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
             and self.max_program_bytes <= 64_000_000 and self.max_inventory_chunk_bytes <= 8_000_000
             and self.max_inventory_chunk_rows <= 1000 and self.max_inventory_manifest_bytes <= 4_000_000,
             "batch source/program/attempt/inventory hard bounds exceeded")


@dataclass(frozen=True)
class NativeCaptureBatchResult:
    directory: Path
    program: object
    report: dict
    first_shard: object | None
    first_partial_shard: object | None = None


@dataclass(frozen=True)
class NativeStaticArtifacts:
    program: ProviderArtifact
    program_bytes: bytes
    interface: ProviderArtifact
    interface_bytes: bytes

    def __post_init__(self):
        for artifact, raw, schema in ((self.program, self.program_bytes, 'scar.program-graph'),
                                     (self.interface, self.interface_bytes, 'scar.pinned-torch-protocol-interface')):
            need(type(artifact) is ProviderArtifact and type(raw) is bytes and artifact.schema == schema
                 and len(raw) == artifact.size_bytes and sha256(raw).hexdigest() == artifact.sha256,
                 'static program/catalog need exact original bytes and artifact identities')


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
        self.parent_frontiers, self.missing_parent_edges = {}, {}
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
        # Preserve all fully hashed records for diagnosis even if a later known
        # cycle rejects acquisition. This private DB still cannot restore owners.
        self.db.commit()
        self.missing_parent_edges = {node: parent for node, parent in self.parents.items()
                                     if parent not in self.parents}
        done = set()
        for node_id in self.parents:
            chain, seen, current = [], set(), node_id
            cause = None
            while current not in done:
                if current not in self.parents:
                    cause = (chain[-1], current)
                    break
                need(current not in seen, "original ETO parent cycle")
                seen.add(current)
                chain.append(current)
                parent = self.parents[current]
                if parent == current:
                    need(current == 1, "unexpected original self-parent ETO root")
                    break
                current = parent
            else:
                cause = self.parent_frontiers.get(current)
            if cause is not None:
                for affected in chain:
                    self.parent_frontiers[affected] = cause
            done.update(chain)

    def parent_fact(self, node_id):
        node = self.get('node', node_id)
        attrs = attributes(node)
        cause = self.parent_frontiers.get(node_id)
        source = {'artifact': self.base['artifacts']['eto'],
                  'locator': '#/nodes/' + str(self.node_ordinals[node_id])}
        return {'node_id': node_id, 'original_ordinal': self.node_ordinals[node_id],
            'original_parent': self.parents[node_id], 'source': source,
            'parent_edge_source': {'artifact': source['artifact'], 'locator': source['locator'] + '/ctrl_deps'},
            'actor': {'process_id': self.base['pid'], 'record_function_thread_token': attrs.get('tid'),
                      'thread_namespace': 'ETO_RECORD_FUNCTION_THREAD_TOKEN', 'rf_id': attrs.get('rf_id'),
                      'scope': attrs.get('scope'), 'name': node['name']},
            'status': 'ORIGINAL_PARENT_CHAIN_UNAVAILABLE' if cause else 'ORIGINAL_ROOTED_PARENT_CLOSURE_VERIFIED',
            'direct_missing_parent_edge': node_id in self.missing_parent_edges,
            'missing_chain_origin_node': None if cause is None else cause[0],
            'missing_parent_id': None if cause is None else cause[1]}

    def parent_inventory(self):
        for node_id in self.parents:
            yield self.parent_fact(node_id)

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

    def source_for(self, sequences, definitions=False, *, require_complete_parents=True):
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
            while current in self.parents:
                selected_nodes.add(current)
                parent = self.parents[current]
                if parent == current:
                    break
                current = parent
        parent_frontiers = [self.parent_fact(n) for n in sorted(selected_nodes, key=self.node_ordinals.__getitem__)
                            if n in self.parent_frontiers]
        need(not require_complete_parents or not parent_frontiers,
             'selected native instance lacks its complete original parent closure')
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
            "node_ordinals": {str(n): self.node_ordinals[n] for n in selected_nodes},
            'parent_closure_capability': PARENT_CLOSURE_CAPABILITY,
            'required_parent_frontiers': parent_frontiers}
        objects, geometry_records = {}, {}
        for row in dispatch:
            for ref in row.get("observation", {}).get("tensor_references", []):
                if type(ref.get("ref")) is str:
                    original = self.get("archive:objects", ref["ref"], optional=True)
                    if original is not None:
                        objects[ref["ref"]] = original["record"]
        for row in physical:
            if row.get("kind") != "MARKER":
                continue
            for arg in row.get("arguments", []):
                ordinal = arg.get("argument_ordinal")
                if type(ordinal) is not int:
                    continue
                locator = "sha256:" + self.base["artifacts"]["physical"]["sha256"] + "#line/" + str(row["index"]) + "/arguments/" + str(ordinal)
                region = self.get("archive:regions", locator + ":" + str(ordinal), optional=True)
                allocation = None if region is None else self.get("archive:allocations", region["record"]["allocation"]["value"], optional=True)
                geometry_records[str(row["index"]) + ":" + str(ordinal)] = {"region": region, "allocation": allocation}
        source.update(object_records=objects, geometry_records=geometry_records)
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

    def selected_v2(self, source, interfaces):
        result = {("evidence", "instances"): [], ("values", "objects"): [],
                  ("values", "regions"): [], ("values", "allocations"): []}
        for node in source["nodes"]:
            row = self.get("archive:instances", node["id"], optional=True)
            if row is None:
                raise _MissingDependency("original native evidence instance unavailable")
            need(row["ordinal"] == self.node_ordinals[node["id"]], "original native instance ordinal contradicts source")
            result["evidence", "instances"].append(row)
        objects, regions, allocations = {}, {}, {}
        for interface in interfaces:
            for ports in interface["ports"].values():
                for port in ports:
                    original = port.get("object_record")
                    if original is not None:
                        row = self.get("archive:objects", port["held"]["weak_token"])
                        need(row["record"] == original, "original object record changed")
                        objects[row["record"]["id"]["value"]] = row
                    g = port.get("geometry", {})
                    if g.get("status") == "QUALIFIED":
                        witness = source["geometry_records"][str(g["physical_line"]) + ":" + str(g["argument_ordinal"])]
                        r, a = witness["region"], witness["allocation"]
                        regions[r["record"]["id"]["value"]] = r
                        allocations[a["record"]["id"]["value"]] = a
        for table, rows in (("objects", objects), ("regions", regions), ("allocations", allocations)):
            result["values", table] = sorted(rows.values(), key=lambda row: row["ordinal"])
        return result


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
        "reference_profile": PROFILE_V2,
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
    owner.base["source_manifest"] = partitions.manifest_receipt
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
                # Exact owned marker/ordered slots supply this bridge. Tree
                # correlation_id and ETO RecordFunction ID are distinct keys.
                if event.get("record_function_thread_token") is not None:
                    need(event["record_function_thread_token"] == attrs.get("tid"),
                         "known physical marker ETO thread differs")
        span = known_nodes.get("DISPATCH_BEGIN")
        result = known_nodes.get("DISPATCH_OUTPUT")
        if span is not None and result is not None:
            need(result["ctrl_deps"] == span["id"] and attributes(result).get("tid") == attributes(span).get("tid"),
                 "known output marker has another native parent/thread")
        if span is not None:
            candidates = []
            unsupported = None
            for child in source["nodes"]:
                raw = attributes(child).get("op_schema")
                if child["ctrl_deps"] == span["id"] and type(raw) is str and raw:
                    try:
                        schema, _, _ = parse_schema_ports(raw)
                    except RuntimeError as error:
                        if source.get("reference_profile") != PROFILE_V2:
                            raise
                        unsupported = {"reason": "SCHEMA_TYPE_RESOLUTION_UNAVAILABLE", "sequence": seq,
                                       "node": child["id"], "detail": str(error)[:512]}
                        continue
                    key = schema.name.replace("::", ".") + "." + (schema.overload_name or "default")
                    if begin is not None and key == begin.get("operator"):
                        candidates.append(child)
                        need(child["name"] == schema.name and attributes(child).get("tid") == attributes(span).get("tid"),
                             "known matching native child label/thread contradicts span/schema")
            need(len(candidates) <= 1, "ambiguous matching direct native schema children")
        else:
            candidates, unsupported = [], None
        normal = (begin is not None and output is not None and end is not None
                  and end["outcome"] == "RETURNED" and end["span_enter_returned"]
                  and not begin.get("slot_gaps") and not output.get("slot_gaps")
                  and (bool(begin.get("operator")) if source.get("reference_profile") == PROFILE_V2
                       else str(begin.get("operator", "")).startswith("aten.")))
        if normal:
            if unsupported is not None:
                absence = unsupported
            elif span is None or (result is None and source.get("reference_profile") != PROFILE_V2):
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


def _write_inventory(directory, rows, budget, publish, *, role, metadata=None, coordinate_key='sequence'):
    """Bounded transport chunks; original sequence and source locators survive."""
    chunks, buffer, count, total, first, last = [], bytearray(), 0, 0, None, None
    begins, begin_groups = 0, 0

    def flush():
        nonlocal buffer, count
        if not count:
            return
        path = directory / f"{len(chunks):06d}.jsonl"
        raw = bytes(buffer)
        publish(path, raw, budget.max_inventory_chunk_bytes)
        chunks.append({"artifact": encode(_artifact(path, raw, "scar.native-capture-row-chunk")),
            "rows": count, 'first_' + coordinate_key: first, 'last_' + coordinate_key: last,
            "first_row_ordinal": total - count, "last_row_ordinal": total - 1})
        buffer, count = bytearray(), 0

    for row in rows:
        raw = canonical(row) + b"\n"
        need(len(raw) <= min(budget.max_record_bytes, budget.max_inventory_chunk_bytes), "inventory row exceeds bounded transport cap")
        if count and (count >= budget.max_inventory_chunk_rows or len(buffer) + len(raw) > budget.max_inventory_chunk_bytes):
            flush()
        if not count:
            first = row[coordinate_key]
        buffer.extend(raw)
        count += 1
        total += 1
        last = row[coordinate_key]
        begins += row.get("begin_count", 0)
        begin_groups += int(row.get("begin_count", 0) > 0)
    flush()
    document = {**(metadata or {}), "schema": "scar.native-capture-table-chunks", "schema_version": 1,
        "profile": PROFILE_V2, "role": role, "row_schema_version": 2,
        "rows": total, "begin_rows": begins, "begin_groups": begin_groups,
        "max_chunk_bytes": budget.max_inventory_chunk_bytes, "max_chunk_rows": budget.max_inventory_chunk_rows,
        "chunks": chunks, "storage_ordinals_are_not_source_coordinates": True}
    if coordinate_key != 'sequence':
        document['source_coordinate_field'] = coordinate_key
    raw = canonical(document)
    path = directory / "manifest.json"
    publish(path, raw, budget.max_inventory_manifest_bytes)
    return _artifact(path, raw, document["schema"]), document


def bind_native_capture_batches(coordinates, capture_directory, partitioned_native_manifest, out_dir, *,
                                expected_manifest_sha256, capture_model_path, expected_capture_model_sha256,
                                budget=NativeCaptureBatchBudget(), progress=None, on_verified_shard=None,
                                scalar_input_profile=None, static_artifacts=None):
    """Verify once and account for every actually enumerated dispatch group.

    Coordinates must already be freshly bound by the ordinary public binder.
    This call does not execute the target or restore a serialized owner.
    """
    from scar.ir.execution.codec import dumps as execution_dumps
    from scar.ir.execution.validation import prepare_program_snapshot, validate
    need(type(budget) is NativeCaptureBatchBudget, "exact native batch budget required")
    need(on_verified_shard is None or callable(on_verified_shard), "verified shard consumer must be callable")
    need(scalar_input_profile in (None, *SCALAR_INPUT_CAPABILITIES), 'unsupported requested scalar capability')
    need(static_artifacts is None or type(static_artifacts) is NativeStaticArtifacts, 'exact static artifact input required')
    budget.__post_init__()
    out = Path(out_dir).resolve()
    need(not out.exists(), "native batch output must be fresh")
    out.mkdir(parents=True)
    started, owner = time.monotonic(), None
    published_total = 0

    def publish(path, raw, maximum):
        nonlocal published_total
        need(len(raw) <= maximum, "artifact exceeds per-file cap before publication: " + path.name)
        need(published_total + len(raw) <= budget.max_output_bytes, "artifact exceeds remaining output cap before publication")
        _write(path, raw)
        published_total += len(raw)

    try:
        owner = _SourceIndex(out, budget, progress)
        owner = _acquire(coordinates, capture_directory, partitioned_native_manifest, capture_model_path, out, budget,
                         expected_manifest_sha256, expected_capture_model_sha256, progress, owner)
        if scalar_input_profile is not None:
            owner.base['scalar_input_profile'] = scalar_input_profile
        parent_inventory_artifact, parent_inventory = _write_inventory(out / 'native-parent-inventory',
            owner.parent_inventory(), budget, publish, role='native-parent-closure', coordinate_key='original_ordinal',
            metadata={'capability': PARENT_CLOSURE_CAPABILITY,
                'whole_tree_parent_closure_established': not bool(owner.parent_frontiers),
                'missing_parent_edges': len(owner.missing_parent_edges), 'affected_nodes': len(owner.parent_frontiers),
                'run': owner.base['run'], 'process_id': owner.base['pid'], 'source_artifact': owner.base['artifacts']['eto']})
        sequences = tuple(sorted(owner.groups))
        observed_artifact, observed = _write_inventory(out / "observed-dispatches", (owner.inventory(seq) for seq in sequences),
            budget, publish, role="observed-dispatches", metadata={"declared_attempts": owner.declared_attempts})
        enumerated_begins = observed["begin_rows"]
        source_complete = (len(sequences) == enumerated_begins == owner.declared_attempts
                           and all(seq == i for i, seq in enumerate(sequences, 1))
                           and observed["begin_groups"] == len(sequences))
        owner.emit({"stage": "dispatch_domain_enumerated", "declared_attempts": owner.declared_attempts,
                    "actual_groups": len(sequences), "actual_begin_rows": enumerated_begins,
                    "source_domain_complete": source_complete})
        for count, seq in enumerate(sequences, 1):
            if count % 256 == 0:
                owner.check()
                owner.emit({"stage": "dispatch_discovery", "visited_actual_groups": count - 1,
                            "static_signatures": len(owner.signatures)})
            source = owner.source_for((seq,), require_complete_parents=False)
            absent_native = _check_group_identity(source)
            # Identity contradictions are checked before this availability
            # frontier. Only closed original ancestry can reach a source lease.
            if source['required_parent_frontiers']:
                owner.classifications[seq] = {'state': 'FRONTIER',
                    'reason': 'ORIGINAL_NATIVE_PARENT_CLOSURE_UNAVAILABLE',
                    'parent_frontiers': source['required_parent_frontiers'], 'other_absence': absent_native}
                continue
            if absent_native is not None:
                owner.classifications[seq] = {"state": "FRONTIER", **absent_native}
                continue
            interfaces, frontiers = replay_batch_interfaces(source)
            if interfaces:
                interface = interfaces[0]
                # Missing original projected dependencies remain explicit; a
                # contradictory full record will reject in _project, not pass.
                try:
                    owner.selected_v2(source, interfaces)
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
        interface_doc = {"schema": "scar.pinned-torch-protocol-interface", "schema_version": 1,
            "profile": PROFILE_V2, "interfaces": definitions,
            "effect_contract": "UNKNOWN outside partial provider schema annotations", "content_version_claimed": False}
        interface_bytes = canonical(interface_doc)
        need(len(interface_bytes) <= budget.max_interface_bytes, "shared interface byte budget exceeded before publication")
        interface_artifact = _artifact(out / "native-interface.json", interface_bytes, interface_doc["schema"])
        if static_artifacts is not None:
            need(interface_bytes == static_artifacts.interface_bytes, 'independent original scalar/catalog ABI differs')
            interface_artifact = static_artifacts.interface
        publish(out / "native-interface.json", interface_bytes, budget.max_interface_bytes)
        program_source = {**owner.base, "max_sequences": owner.declared_attempts}
        representatives = [owner.representatives[sig] for sig in sorted(owner.representatives)]
        program, layouts = _build_program(representatives, program_source, interface_artifact)
        prepared_snapshot = prepare_program_snapshot(program)
        program_bytes = prepared_snapshot.canonical_bytes(program)
        need(len(program_bytes) <= budget.max_program_bytes, "shared static program byte budget exceeded")
        program_artifact = _artifact(out / "program.json", program_bytes, "scar.program-graph")
        if static_artifacts is not None:
            need(program_bytes == static_artifacts.program_bytes, 'independent rebuilt ProgramSnapshot differs')
            program_artifact = static_artifacts.program
        publish(out / "program.json", program_bytes, budget.max_program_bytes)
        shard_reports, first_shard, first_partial_shard = [], None, None
        prepared_catalog = None
        pending = []

        def emit_shard(selected_sequences):
            nonlocal first_shard, first_partial_shard, prepared_catalog
            owner.check()
            shard_started = time.monotonic()
            source = owner.source_for(tuple(selected_sequences), definitions=True)
            interfaces, frontiers = replay_batch_interfaces(source)
            expected = {seq for seq in selected_sequences if owner.classifications[seq]["state"] == "READY"}
            interfaces = [i for i in interfaces if i["sequence"] in expected]
            need({i["sequence"] for i in interfaces} == expected, "source replay changed during shard construction")
            if not interfaces:
                return
            selected = owner.selected_v2(source, interfaces)
            shard_dir = out / "shards" / f"{len(shard_reports):06d}"
            values, evidence, va, ea, geometry, payloads = _prepare_projection(source, interfaces, selected, shard_dir, budget)
            execution = _build_execution(program, layouts, interfaces, source, coordinates, program_artifact, va, ea,
                                         prepared_snapshot=prepared_snapshot)
            execution_bytes = execution_dumps(execution).encode()
            need(len(execution_bytes) <= budget.max_shard_execution_bytes and va.size_bytes <= budget.max_shard_values_bytes
                 and ea.size_bytes <= budget.max_shard_evidence_bytes, "materialized shard byte budget exceeded")
            # Only actual selected interfaces enter this lease; other sequence
            # groups keep their inventory/frontier without an invented activation.
            source["definition_signatures"] = definitions
            source["selected_sequences"] = sorted(expected)
            owned = _own_capture(source)
            if prepared_catalog is None:
                prepared_catalog = _prepare_native_catalog(owned, program, prepared_snapshot)
            native = _make_evidence(owned, program, execution, va, ea, _prepared=prepared_catalog,
                _scalar_projection=payloads['source-values.json'] if scalar_input_profile is not None else None)
            catalogs = {"value_graphs": {va.sha256: values}, "evidence_graphs": {ea.sha256: evidence},
                        "artifact_bytes": {interface_artifact.sha256: interface_bytes}, "native_port_evidence": native}
            validation = validate(execution, program, prepared_snapshot=prepared_snapshot, **catalogs)
            validation_doc = {"valid": validation.valid, "issues": [encode(i) for i in validation.issues],
                              "gaps": [encode(g) for g in validation.gaps]}
            need(validation.valid, "actual shard validation failed: " + json.dumps(validation_doc["issues"][:10], sort_keys=True))
            artifact = _artifact(shard_dir / "execution.json", execution_bytes, "scar.execution-model")
            tensor_ports = [p for i in interfaces for ports in i["ports"].values() for p in ports if p["tensor"]]
            b_count = sum(p.get("object_record") is not None for p in tensor_ports)
            c_count = sum(p["geometry"]["status"] == "QUALIFIED" for p in tensor_ports)
            denotations = {d.id.value: d for d in execution.denotations}
            port_rows = []
            for interface in interfaces:
                for direction, ports in interface["ports"].items():
                    for position, port in enumerate(ports):
                        if not port["tensor"]:
                            continue
                        denotation = denotations["native-port:" + source["run"] + ":" + str(interface["sequence"]) + ":" + direction + ":denotation:" + str(position)]
                        port_rows.append({"sequence": interface["sequence"], "direction": direction, "position": position,
                            "native_path": port["path"], "native_type": port["type"], "source": encode(denotation.source),
                            "native_tensor_tuple": port["value"], "native_shape": port["shape"], "native_strides": port["strides"],
                            "denotation": encode(denotation), "A": "QUALIFIED_NATIVE_PORT",
                            "B": "QUALIFIED_HELD_OBJECT" if port.get("object_record") is not None else "UNRESOLVED",
                            "C": port["geometry"], "D": "CONTENT_STATE_READY_UNPROVED"})
            qualification_artifact, _ = _write_inventory(shard_dir / "port-qualifications", iter(port_rows), budget, publish,
                role="native-port-qualifications", metadata={"program_snapshot": encode(execution.snapshot)})
            scalar_rows = []
            if scalar_input_profile is not None:
                for interface in interfaces:
                    for position, port in enumerate(interface['ports']['inputs']):
                        if port['tensor']:
                            continue
                        scalar = port['scalar_input']
                        denotation = denotations['native-port:' + source['run'] + ':' + str(interface['sequence']) + ':inputs:denotation:' + str(position)]
                        scalar_rows.append({'sequence': interface['sequence'], 'position': position,
                            'native_path': port['path'], 'provider_type': port['type'],
                            'formal_kind': scalar.get('formal_kind'), 'formal_real_kind': scalar.get('formal_real_kind'),
                            'frontier': scalar['frontier'], 'denotation': encode(denotation), 'input_root_not_consumer_output': True})
                scalar_artifact, _ = _write_inventory(shard_dir / 'scalar-input-qualifications', iter(scalar_rows), budget, publish,
                    role='native-scalar-input-qualifications', metadata={'scalar_input_profile': scalar_input_profile,
                        'program_snapshot': encode(execution.snapshot)})
            report = {"schema": "scar.native-capture-execution-shard", "schema_version": 2, "profile": PROFILE_V2,
                "status": "NATIVE_PORTS_MODELED_WITH_EXPLICIT_QUALIFICATION", "sequences": sorted(expected),
                "program_snapshot": encode(execution.snapshot), "execution": encode(artifact),
                "values_projection": encode(va), "evidence_projection": encode(ea),
                "signature_ids": sorted({i["signature_id"] for i in interfaces}),
                "actual_activations": len(execution.activations), "tensor_denotations": len(tensor_ports),
                "native_tensor_ports": len(tensor_ports), "held_object_ports": b_count,
                "unresolved_object_ports": len(tensor_ports) - b_count, "geometry_qualified_ports": c_count,
                "geometry_gap_ports": len(tensor_ports) - c_count,
                "port_qualifications": encode(qualification_artifact),
                "physical_associations": len(geometry), "gap_counts": dict(Counter(g.code for g in validation.gaps)),
                "wall_seconds": time.monotonic() - shard_started}
            if scalar_input_profile is not None:
                report.update(scalar_input_profile=scalar_input_profile, scalar_input_ports=len(scalar_rows),
                    scalar_observed_roots=sum(r['frontier'] is None for r in scalar_rows),
                    scalar_frontiers=dict(Counter(r['frontier'] for r in scalar_rows if r['frontier'] is not None)),
                    scalar_input_qualifications=encode(scalar_artifact))
            payloads.update({"execution.json": execution_bytes, "validation.json": canonical(validation_doc),
                             "report.json": canonical(report)})
            caps = {"source-values.json": budget.max_shard_values_bytes, "source-evidence.json": budget.max_shard_evidence_bytes,
                    "source-projection-receipts.json": budget.max_shard_receipt_bytes,
                    "execution.json": budget.max_shard_execution_bytes, "validation.json": budget.max_report_bytes,
                    "report.json": budget.max_report_bytes}
            for name, raw in payloads.items():
                need(len(raw) <= caps[name], "shard file byte budget exceeded before publication: " + name)
            shard_size = sum(map(len, payloads.values()))
            need(published_total + shard_size <= budget.max_output_bytes, "shard exceeds remaining published output budget")
            owner.check()
            need(report["wall_seconds"] <= budget.max_shard_seconds, "materialized shard wall budget exceeded")
            for name, raw in payloads.items():
                publish(shard_dir / name, raw, caps[name])
            for interface in interfaces:
                seq = interface["sequence"]
                ports = [p for ps in interface["ports"].values() for p in ps if p["tensor"]]
                held = sum(p.get("object_record") is not None for p in ports)
                geometry_count = sum(p["geometry"]["status"] == "QUALIFIED" for p in ports)
                owner.classifications[seq] = {"state": "MODELED_COMPLETE_REFERENCE" if held == len(ports) else "MODELED_PARTIAL_REFERENCE",
                    "native_tensor_ports": len(ports), "held_object_ports": held, "unresolved_object_ports": len(ports) - held,
                    "geometry_qualified_ports": geometry_count, "geometry_gap_ports": len(ports) - geometry_count,
                    "port_qualifications": encode(qualification_artifact), "signature_id": interface["signature_id"],
                    "shard": str(shard_dir.relative_to(out)), "execution": encode(artifact),
                    "activation_id": "native-port:" + owner.base["run"] + ":" + str(seq)}
            shard_reports.append(report)
            verified = NativeProtocolWindowResult(shard_dir, program, execution, values, evidence, native, validation, report)
            if on_verified_shard is not None:
                on_verified_shard(verified)
            if first_shard is None:
                first_shard = verified
            if first_partial_shard is None and b_count < len(tensor_ports):
                first_partial_shard = verified
            owner.emit({"stage": "actual_shard_verified", "number": len(shard_reports) - 1,
                        "activations": len(execution.activations), "tensor_denotations": len(tensor_ports)})

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
        need(all(owner.classifications[s]["state"] != "READY" for s in sequences), "unmaterialized actual dispatch remains")
        inventory_artifact, _ = _write_inventory(out / "dispatch-inventory",
            ({**owner.inventory(seq), **owner.classifications[seq]} for seq in sequences), budget, publish,
            role="dispatch-accounting", metadata={"declared_attempts": owner.declared_attempts, "program_snapshot": encode(program_artifact)})
        complete = sum(owner.classifications[s]["state"] == "MODELED_COMPLETE_REFERENCE" for s in sequences)
        partial = sum(owner.classifications[s]["state"] == "MODELED_PARTIAL_REFERENCE" for s in sequences)
        frontier = sum(owner.classifications[s]["state"] == "FRONTIER" for s in sequences)
        need(complete + partial + frontier == len(sequences), "actual dispatch accounting mismatch")
        report = {"schema": "scar.native-capture-batch", "schema_version": 2, "profile": PROFILE_V2,
            "capabilities": {"native_tensor_ports": True, "held_reference_subset": True, "geometry_independent": True,
                             "unresolved_native_identity": True, "logical_contents": False, "resource_ready": False,
                             'selected_native_parent_closure': PARENT_CLOSURE_CAPABILITY},
            "status": "SOURCE_DOMAIN_ACCOUNTED_WITH_PORT_GAPS" if source_complete else "OPEN_SOURCE_DOMAIN_MISMATCH",
            "run": owner.base["run"], "coordinates": encode(coordinates.artifact),
            "source_manifest": owner.manifest_receipt, "raw_reads": owner.raw_receipts,
            "source_raw_acquisitions": 1, "coordinate_binds_inside_batch": 0,
            "declared_dispatch_attempts": owner.declared_attempts,
            "enumerated_dispatch_groups": len(sequences), "enumerated_begin_rows": enumerated_begins,
            "enumerated_begin_groups": observed["begin_groups"],
            "actual_sequence_ids": list(sequences), "source_domain_complete": source_complete,
            'source_domain_definition': 'complete observed dispatch inventory, not complete ETO tree/whole program',
            'whole_tree_parent_closure_established': not bool(owner.parent_frontiers),
            'qualified_leases_have_complete_required_parent_closure': True,
            'native_parent_inventory': encode(parent_inventory_artifact), 'native_parent_nodes': parent_inventory['rows'],
            'missing_parent_edge_count': len(owner.missing_parent_edges),
            'parent_frontier_node_count': len(owner.parent_frontiers),
            "structurally_modeled_dispatches": complete + partial,
            "modeled_complete_reference_dispatches": complete, "modeled_partial_reference_dispatches": partial,
            "unmodeled_frontier_dispatches": frontier,
            "frontier_counts": dict(Counter(owner.classifications[s]["reason"] for s in sequences if owner.classifications[s]["state"] == "FRONTIER")),
            "native_tensor_ports": sum(r["native_tensor_ports"] for r in shard_reports),
            "held_object_ports": sum(r["held_object_ports"] for r in shard_reports),
            "unresolved_object_ports": sum(r["unresolved_object_ports"] for r in shard_reports),
            "geometry_qualified_ports": sum(r["geometry_qualified_ports"] for r in shard_reports),
            "geometry_gap_ports": sum(r["geometry_gap_ports"] for r in shard_reports),
            "unvisited_actual_groups": 0, "declared_minus_enumerated_begins": owner.declared_attempts - enumerated_begins,
            "unvisited_declared_sequences": 0 if source_complete else None,
            "dispatch_inventory": encode(inventory_artifact), "observed_dispatch_inventory": encode(observed_artifact), "static_interfaces": len(definitions),
            "shared_program": encode(program_artifact), "shared_interface": encode(interface_artifact),
            "shards": shard_reports, "archive_reads": owner.archive_receipts,
            "native_raw_bytes_returned": owner.raw_returned, "private_spool_bytes_returned": owner.spool_returned,
            "private_index_bytes": owner.path.stat().st_size,
            "wall_seconds": time.monotonic() - started, "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "logical_contents_established": False, "complete_state_effects_established": False,
            "implementation_code_identity_established": False,
            "observed_execution_instrumented": True,
            "target_observer_work_attribution_established": False,
            "clean_benchmark_established": False,
            "observation_scope": "Observed instrumented execution including provider/mode/observer activity; target versus observer work remains unattributed",
            "alias_completeness_established": False, "resource_readiness_established": False,
            "whole_model_established": False, "transformation_authorized": False,
            "target_executions": 0, "compile_calls": 0, "prepare_calls": 0}
        published = sum(p.stat().st_size for p in out.rglob("*") if p.is_file() and "private" not in p.relative_to(out).parts)
        if scalar_input_profile is not None:
            report.update(scalar_input_profile=scalar_input_profile,
                scalar_input_ports=sum(r['scalar_input_ports'] for r in shard_reports),
                scalar_observed_roots=sum(r['scalar_observed_roots'] for r in shard_reports),
                scalar_frontiers=dict(sum((Counter(r['scalar_frontiers']) for r in shard_reports), Counter())),
                scalar_input_contents_observed_locally=any(r['scalar_observed_roots'] for r in shard_reports), scalar_upstream_producers_established=False,
                static_artifacts_reused=static_artifacts is not None)
        report["published_bytes_before_report"] = published
        need(len(canonical(report)) <= budget.max_report_bytes and published + len(canonical(report)) <= budget.max_output_bytes,
             "final report/publication byte budget exceeded before publication")
        publish(out / "report.json", canonical(report), budget.max_report_bytes)
        owner.check()
        return NativeCaptureBatchResult(out, program, report, first_shard, first_partial_shard)
    except BaseException as error:
        import traceback
        failure = {"status": "INCOMPLETE_NATIVE_CAPTURE_BATCH", "error_type": type(error).__name__,
            "message": str(error), "traceback": traceback.format_exc(), "wall_seconds": time.monotonic() - started,
            "whole_model_established": False, "target_executions": 0}
        if owner is not None:
            failure.update(raw_reads=owner.raw_receipts, declared_dispatch_attempts=owner.declared_attempts,
                           archive_reads=owner.archive_receipts,
                           classified_actual_groups=len(owner.classifications), enumerated_dispatch_groups=len(owner.groups))
        _write_json(out / "failure.json", failure, budget.max_report_bytes)
        raise
    finally:
        if owner is not None:
            owner.db.close()


__all__ = ["NativeCaptureBatchBudget", "NativeCaptureBatchResult", "bind_native_capture_batches"]


@dataclass(frozen=True)
class NativeCaptureModelBatchResult:
    native: NativeCaptureBatchResult
    metadata: object
    report: dict


def bind_native_capture_model_batches(capture_model_path, out_dir, *, expected_sha256,
                                     input_budget=None, budget=None, progress=None, on_verified_shard=None,
                                     scalar_input_profile=None, static_program=None, static_interface=None):
    """Reuse G1 graphs with a genuine fresh ordinary coordinate acquisition.

    This entry never imports a capture/model, reconstructs an owner from JSON,
    or executes a target. G1 locates exact retained products; the normal binder
    and V2 producer perform their ordinary checks. Metadata has a separate cap.
    """
    from scar.trace.capture_coordinates import bind_capture_coordinates
    from scar.trace.native_tensor_inputs import NativeInputPayloadBudget, prepare_native_input_metadata
    from scar.ir.record_codec import decode
    from scar.ir.execution.coordinates import ExecutionRun
    need(input_budget is None or type(input_budget) is NativeInputPayloadBudget, 'exact input payload budget required')
    inputs = input_budget or NativeInputPayloadBudget()
    need(budget is None or type(budget) is NativeCaptureBatchBudget, 'exact native batch budget required')
    limits = budget or NativeCaptureBatchBudget(max_source_raw_bytes=20_000_000, max_index_bytes=128_000_000,
        max_output_bytes=64_000_000, max_wall_seconds=120)
    need(limits.max_wall_seconds <= 120 and limits.max_index_bytes <= 128_000_000
         and limits.max_output_bytes <= 64_000_000, 'small capture model entry budget exceeds hard cap')
    need(on_verified_shard is None or callable(on_verified_shard), 'verified shard consumer must be callable')
    need(scalar_input_profile in (None, *SCALAR_INPUT_CAPABILITIES), 'unsupported scalar capability')
    need((static_program is None) == (static_interface is None), 'program/catalog must be supplied together')
    out = Path(out_dir).resolve()
    need(not out.exists(), 'capture model binding output must be fresh')
    out.mkdir(parents=True)
    started = time.monotonic()

    def control(path, expected=None, *, program_IR=False):
        path = Path(path)
        need(path.is_absolute() and path.is_file() and not path.is_symlink(), 'control metadata is not an exact regular path')
        size = path.stat().st_size
        charged = inputs.charge(('program IR: ' if program_IR else 'control: ') + path.name,
                                size, size, control=not program_IR)
        with path.open('rb') as stream:
            raw = stream.read(size + 1)
        need(len(raw) == size and (expected is None or sha256(raw).hexdigest() == expected), 'control metadata changed')
        inputs.complete(charged)
        return _json(raw), raw

    try:
        model, model_raw = control(capture_model_path, expected_sha256)
        static = None
        if static_program is not None:
            need(type(static_program) is type(static_interface) is ProviderArtifact, 'typed exact static artifacts required')
            _, program_raw = control(static_program.uri, static_program.sha256, program_IR=True)
            _, interface_raw = control(static_interface.uri, static_interface.sha256)
            static = NativeStaticArtifacts(static_program, program_raw, static_interface, interface_raw)
        need(model.get('schema') == 'scar.capture-model' and model.get('schema_version') == 1
             and model.get('coordinate_identity_consistent') is True, 'unsupported G1 capture model')
        root = Path(model['capture']).resolve()
        need(root.is_dir(), 'G1 original capture unavailable')
        expected_coordinate = model['coordinate_binding']
        retained, retained_raw = control(expected_coordinate['uri'], expected_coordinate['sha256'])
        need(len(retained_raw) == expected_coordinate['size_bytes'] and retained['local_root'] == str(root),
             'G1 coordinate root/size differs')
        archive, archive_raw = control(root / 'archive-index.json', retained['seed']['archive_sha256'])
        need(archive.get('schema') == 'scar.lossless-capture-archive' and archive.get('schema_version') == 1
             and archive.get('verified_roundtrip') is True, 'unsupported exact lossless capture')
        storage = model['native_bundle_storage']
        need(storage.get('kind') == 'partitioned', 'G1 partitioned native graphs required')
        manifest_path = Path(storage['manifest'])
        declarations = [r for r in model['outputs'] if r['path'] == str(manifest_path)]
        need(len(declarations) == 1, 'G1 native manifest lacks one exact output receipt')
        declaration = declarations[0]
        partition, partition_raw = control(manifest_path, declaration['stored_sha256'])
        need(len(partition_raw) == declaration['stored_bytes'], 'G1 native manifest size differs')
        members = {r['artifact']['uri']: r for r in retained['membership']}
        need(len(members) == len(retained['membership']), 'duplicate G1 membership URI')
        archived = {r['logical_path']: r for r in archive['files']}
        need(len(archived) == len(archive['files']), 'duplicate capture archive URI')
        def one(schema):
            rows = [r['artifact'] for r in retained['membership'] if r['artifact']['schema'] == schema]
            need(len(rows) == 1, 'one G1 member required: ' + schema)
            return rows[0]
        native_member = one('scar.execution-evidence-collection')
        native_meta, native_meta_raw = control(members[native_member['uri']]['local_path'], native_member['sha256'])
        run_path = root / 'trace' / 'run.json'
        run_size = run_path.stat().st_size
        # Pre-charge complete public-binder passes before it opens the payloads.
        # Success is reconciled with fresh membership/byte counts, not a flag.
        plain_sizes = sum(r['artifact']['size_bytes'] for r in retained['membership'] if r['artifact']['uri'] not in archived) + run_size
        archive_stored = sum(r['compressed_bytes'] for r in archive['files'])
        verified_raw = sum(r['raw_bytes'] for r in archive['files']) + plain_sizes
        need(verified_raw == retained['counts']['verified_raw_bytes'], 'declared binder inventory/raw count differs')
        inputs.charge('ordinary binder verified complete members', 2*archive_stored + plain_sizes, verified_raw,
                      basis='precharged complete SHA passes; fresh public binder reconciles exact receipts')
        os_members = [r['artifact'] for r in retained['membership'] if r['artifact']['schema'] == 'strace.syscalls.text.v1']
        inputs.charge('ordinary binder OS fact parse', sum(archived[r['uri']]['compressed_bytes'] for r in os_members),
                      sum(r['size_bytes'] for r in os_members), basis='unchanged public binder complete OS parse passes')
        cap = retained['native_tensor_input_membership']
        chunk_raw = sum(r['size_bytes'] for r in cap['chunks'])
        chunk_stored = sum(archived[r['uri']]['compressed_bytes'] for r in cap['chunks'])
        inputs.charge('ordinary binder strict companion parse', chunk_stored, chunk_raw,
                      basis='unchanged strict-reader complete parse passes after member SHA verification')
        physical_member = one('scar.tensor-physical-trace')
        dispatch_member = one('scar.dispatch-observation-trace')
        companion_doc_sizes = sum(r['size_bytes'] for r in (native_member, physical_member, dispatch_member, cap['manifest']))
        inputs.charge('ordinary binder strict companion metadata parse', companion_doc_sizes, companion_doc_sizes,
                      basis='cached verified metadata document parse')
        doc_names = ('call-meta.', 'call-operand-meta.', 'function-environment-meta.', 'dispatch-meta.', 'tensor-physical-meta.')
        doc_sizes = sum(r['artifact']['size_bytes'] for r in retained['membership']
                        if Path(r['logical_path']).name.startswith(doc_names)) + cap['manifest']['size_bytes'] + run_size
        inputs.charge('ordinary binder other metadata parse', doc_sizes, doc_sizes, basis='complete document passes')
        initial_sizes = native_member['size_bytes'] + len(archive_raw)
        inputs.charge('ordinary binder initial native/archive', initial_sizes, initial_sizes, basis='complete initial document reads')
        launch = retained['os_capture_provider']['launch']
        coverage = retained['os_capture_provider']['profile']
        os_control = sum(r['size_bytes'] for r in (launch, coverage, native_meta['configuration']['os_capture_intent']['intent']))
        inputs.charge('ordinary binder OS intent/launch/coverage', 2*os_control, 2*os_control,
                      basis='unchanged _document: receipt read plus document read')
        coordinates = bind_capture_coordinates(root, max_bytes=verified_raw, profile_uri=str(out / 'capture-coordinates.json'))
        need(coordinates.run == decode(ExecutionRun, model['run'])
             and coordinates.payload == retained_raw
             and coordinates.report['counts']['verified_raw_bytes'] == verified_raw,
             'fresh ordinary coordinates differ from exact G1 Run/membership')
        inputs.complete_prefix('ordinary binder ')
        _write(out / 'capture-coordinates.json', coordinates.payload)
        metadata = prepare_native_input_metadata(coordinates, budget=inputs)
        # Source acquisition is still the original V2 owner. No G1 success bit
        # substitutes for its full source SHA / original record / namespace checks.
        source_artifacts = [one(s) for s in ('pytorch.execution-trace.v1', 'scar.dispatch-observation.events.v1', 'scar.tensor-physical-observation.v1')]
        source_raw = sum(r['size_bytes'] for r in source_artifacts)
        source_stored = sum(archived[r['uri']]['compressed_bytes'] for r in source_artifacts)
        inputs.charge('native V2 complete sources', source_stored, source_raw, basis='precharged original V2 complete source reads')
        tables = [('evidence', 'instances'), ('values', 'objects'), ('values', 'regions'), ('values', 'allocations')]
        table_stored = table_raw = 0
        for graph, table in tables:
            for chunk in partition['graphs'][graph]['tables'][table]['chunks']:
                table_stored += chunk['physical_bytes']; table_raw += chunk['decoded_bytes']
        inputs.charge('native V2 original four tables', table_stored, table_raw, basis='precharged complete BundlePartitions chunk reads')
        acquisition_meta = len(model_raw) + len(partition_raw) + sum(r['size_bytes'] for r in (native_member, dispatch_member, physical_member))
        inputs.charge('native V2 acquisition metadata', acquisition_meta, acquisition_meta, basis='complete acquisition metadata reads')
        consumed_shards = 0
        def consume(shard):
            nonlocal consumed_shards
            metadata.bind_shard(shard)
            consumed_shards += 1
            if on_verified_shard is not None:
                on_verified_shard(shard, metadata)
            need(time.monotonic() - started <= limits.max_wall_seconds, 'capture-model whole wall budget')
        native = bind_native_capture_batches(coordinates, root, manifest_path, out / 'native',
            expected_manifest_sha256=declaration['stored_sha256'], capture_model_path=capture_model_path,
            expected_capture_model_sha256=expected_sha256, budget=limits, progress=progress, on_verified_shard=consume,
            scalar_input_profile=scalar_input_profile, static_artifacts=static)
        need(sum(r['raw_bytes_read'] for r in native.report['raw_reads']) == source_raw
             and sum(r['stored_bytes_read'] for r in native.report['raw_reads']) == source_stored,
             'actual native complete-source read accounting differs')
        need(sum(r['decoded_bytes'] for r in native.report['archive_reads']) == table_raw
             and sum(r['stored_bytes'] for r in native.report['archive_reads']) == table_stored,
             'actual original-table read accounting differs')
        inputs.complete_prefix('native V2 ')
        need(consumed_shards == len(native.report['shards']), 'not every verified shard consumed')
        association = metadata.report()
        association_payload = canonical(association)
        need(len(association_payload) <= limits.max_report_bytes, 'association report byte cap')
        report = {'schema': 'scar.native-capture-model-input-binding', 'schema_version': 1,
            'profile': association['profile'], 'G1_capture_model': {'uri': str(capture_model_path), 'sha256': expected_sha256, 'size_bytes': len(model_raw)},
            'run': coordinates.run.id.value, 'fresh_public_coordinate_binds': 1, 'verified_shards_consumed': consumed_shards,
            'declared_dispatch_attempts': native.report['declared_dispatch_attempts'],
            'enumerated_dispatch_groups': native.report['enumerated_dispatch_groups'],
            'modeled_dispatches': native.report['structurally_modeled_dispatches'],
            'G1_dispatch_outcomes': model['native']['dispatch_bridge']['outcomes'],
            'dispatch_frontiers': native.report['frontier_counts'], 'metadata_counts': association['counts'],
            'native_parent_closure': {key: native.report[key] for key in (
                'source_domain_definition', 'whole_tree_parent_closure_established',
                'qualified_leases_have_complete_required_parent_closure', 'native_parent_inventory',
                'native_parent_nodes', 'missing_parent_edge_count', 'parent_frontier_node_count')},
            'input_budget': inputs.report(), 'own_source_hash_checks': native.report['raw_reads'],
            'output_limit_bytes': limits.max_output_bytes, 'private_index_limit_bytes': limits.max_index_bytes,
            'wall_limit_seconds': limits.max_wall_seconds, 'rss_limit_KiB': limits.max_rss_kib,
            'metadata_associations': str(out / 'input-associations.json'), 'target_executions': 0,
            'capture_imports': 0, 'OS_interface_imports': 0, 'whole_model_established': False,
            'source_call_binding_established': False, 'logical_content_established': False,
            'state_effects_established': False, 'resource_ready_established': False,
            'whole_elapsed_seconds': time.monotonic() - started}
        report_payload = canonical(report)
        if scalar_input_profile is not None:
            report.update(scalar_input_profile=scalar_input_profile,
                scalar_input_ports=native.report['scalar_input_ports'], scalar_observed_roots=native.report['scalar_observed_roots'],
                scalar_frontiers=native.report['scalar_frontiers'], scalar_upstream_producers_established=False)
            report_payload = canonical(report)
        published = sum(p.stat().st_size for p in out.rglob('*') if p.is_file() and 'private' not in p.relative_to(out).parts)
        need(published + len(association_payload) + len(report_payload) <= limits.max_output_bytes, 'whole binding published output byte cap')
        need(time.monotonic() - started <= limits.max_wall_seconds, 'capture-model whole wall budget')
        _write(out / 'input-associations.json', association_payload)
        _write(out / 'report.json', report_payload)
        return NativeCaptureModelBatchResult(native, metadata, report)
    except BaseException as error:
        import traceback
        # Diagnostic receipts from this call's own fresh failure output cannot
        # restore a lease. Distinguish verified reads from pending reservations.
        native_failure = out / 'native' / 'failure.json'
        verified_native_reads = []
        if native_failure.is_file() and native_failure.stat().st_size <= 1_000_000:
            observed_failure = _json(native_failure.read_bytes())
            verified_native_reads = observed_failure.get('raw_reads', [])
            if verified_native_reads:
                inputs.complete_prefix('native V2 acquisition metadata')
        _write_json(out / 'failure.json', {'status': 'INCOMPLETE_NATIVE_INPUT_MODEL_BINDING', 'error_type': type(error).__name__,
            'message': str(error), 'traceback': traceback.format_exc(), 'input_budget': inputs.report(),
            'native_verified_source_reads': verified_native_reads,
            'partial_or_unverified_stream_bytes_not_measured': True,
            'whole_elapsed_seconds': time.monotonic() - started, 'target_executions': 0}, limits.max_report_bytes)
        raise


__all__ += ['NativeCaptureModelBatchResult', 'bind_native_capture_model_batches', 'NativeStaticArtifacts']
