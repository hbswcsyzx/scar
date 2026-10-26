"""Bounded retained relations and disposable locator indexes.

Only the fixed producer publishes.  Failed builds retain BUILDING and closed
chunks.  A query locates one work chunk and selected source chunks, never raw.
"""
from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, fields
import gzip
import hashlib
import io
import os
from pathlib import Path
import time

from scar.ir.execution.fragment_relations import canonical, exact, need, stable_key, WorkRelations
from scar.ir.execution.fragment_relations_codec import to_dict, from_dict
from scar.ir.program.providers import ProviderArtifact
from scar.ir.record_codec import decode, encode, loads as strict_loads

SCHEMA = "scar.partitioned-execution-fragment-relations"
VERSION = 1


@dataclass(frozen=True, slots=True)
class RelationBudgets:
    max_input_bytes: int = 9_512_000_000
    max_core_input_bytes: int = 9_000_000_000
    max_code_source_bytes: int = 512_000_000
    max_output_bytes: int = 1_000_000_000
    max_record_bytes: int = 4_000_000
    max_input_chunk_bytes: int = 16_000_000
    max_chunk_bytes: int = 8_000_000
    max_chunk_rows: int = 1000
    max_metadata_bytes: int = 32_000_000
    max_records: int = 2_000_000
    max_seconds: int = 900

    def __post_init__(self):
        need(all(type(getattr(self, f.name)) is int and getattr(self, f.name) > 0 for f in fields(self)), "positive exact budgets required")
        need(self.max_chunk_bytes <= 8_000_000 and self.max_chunk_rows <= 1000
             and self.max_record_bytes <= self.max_chunk_bytes, "hard chunk bounds exceeded")


class Meter:
    def __init__(self, budget):
        exact(budget, RelationBudgets, "budget")
        self.budget, self.started = budget, time.monotonic()
        self.stored = self.decoded = self.output = self.code_source = 0

    def check(self):
        need(time.monotonic() - self.started <= self.budget.max_seconds, "wall budget exceeded")

    def charge(self, *, stored=0, decoded=0, output=0, code_source=False):
        self.check()
        need(self.stored + stored + self.decoded + decoded <= self.budget.max_input_bytes, "actual stored+decoded budget exceeded")
        candidate = self.code_source + (stored + decoded if code_source else 0)
        need(candidate <= self.budget.max_code_source_bytes
             and self.stored + stored + self.decoded + decoded - candidate <= self.budget.max_core_input_bytes, "core/code-source input partition exceeded")
        need(self.output + output <= self.budget.max_output_bytes, "stored output budget exceeded")
        self.stored += stored; self.decoded += decoded; self.output += output
        self.code_source = candidate

    def receipt(self):
        return {"stored_bytes": self.stored, "decoded_bytes": self.decoded,
                "actual_input_bytes": self.stored + self.decoded, "stored_output_bytes": self.output,
                "core_input_bytes": self.stored + self.decoded - self.code_source,
                "code_source_input_bytes": self.code_source,
                "elapsed_s": time.monotonic() - self.started,
                "scope": "returned stored plus decoded bytes, including repeats; source/runner guards separate"}


def read_payload(artifact, meter, *, decoded_bytes=None, decoded_sha256=None, compressed=False, maximum=None, code_source=False):
    exact(artifact, ProviderArtifact, "input artifact")
    path = Path(artifact.uri)
    need(path.is_absolute() and not path.is_symlink() and path.resolve() == path, "original logical path required; relocation is not inferred")
    limit = meter.budget.max_metadata_bytes if maximum is None else maximum
    expected = artifact.size_bytes if decoded_bytes is None else decoded_bytes
    need(type(expected) is int and 0 <= expected <= limit and artifact.size_bytes <= limit, "input/decoded bound exceeded before open")
    stat = path.stat()
    need(stat.st_size == artifact.size_bytes, "compressed/file stat differs before open")
    meter.charge(stored=artifact.size_bytes, code_source=code_source)
    with path.open("rb") as stream:
        stored = stream.read(artifact.size_bytes + 1)
    need(len(stored) == artifact.size_bytes and hashlib.sha256(stored).hexdigest() == artifact.sha256, "stored input receipt differs")
    meter.charge(decoded=expected, code_source=code_source)
    if compressed:
        with gzip.GzipFile(fileobj=io.BytesIO(stored), mode="rb") as stream:
            decoded = stream.read(expected + 1)
    else:
        decoded = stored
    need(len(decoded) == expected and hashlib.sha256(decoded).hexdigest() == (decoded_sha256 or artifact.sha256), "full decoded EOF receipt differs")
    after = path.stat()
    need((stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
         == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns), "input changed during read")
    return decoded


def _atomic(root, name, payload, meter):
    meter.charge(output=len(payload))
    path = root / name
    with path.open("xb") as stream:
        stream.write(payload); stream.flush(); os.fsync(stream.fileno())
    return {"path": str(path), "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


class _Sink:
    def __init__(self, root, name, meter):
        self.root, self.name, self.meter = root, name, meter
        (root / name).mkdir()
        self.descriptors, self.pending, self.size = [], [], 0

    def add(self, value):
        self.meter.check(); data = canonical(value); b = self.meter.budget
        need(len(data) <= b.max_record_bytes, "relation/source row exceeds budget")
        if self.pending and (len(self.pending) >= b.max_chunk_rows or self.size + len(data) > b.max_chunk_bytes):
            self.close()
        position = (len(self.descriptors), len(self.pending))
        self.pending.append(data); self.size += len(data)
        return position

    def close(self):
        if not self.pending:
            return
        raw = b"".join(self.pending); stored = gzip.compress(raw, mtime=0)
        b = self.meter.budget
        need(len(raw) <= b.max_chunk_bytes and len(stored) <= b.max_chunk_bytes, "closed output chunk exceeds bound")
        uri = self.name + "/" + str(len(self.descriptors)).zfill(6) + ".jsonl.gz"
        _atomic(self.root, uri, stored, self.meter)
        self.descriptors.append({"uri": uri, "rows": len(self.pending), "stored_bytes": len(stored),
            "stored_sha256": hashlib.sha256(stored).hexdigest(), "decoded_bytes": len(raw),
            "decoded_sha256": hashlib.sha256(raw).hexdigest()})
        self.pending, self.size = [], 0


class _Writer:
    def __init__(self, root, meter, schema_version=VERSION):
        self.root, self.meter, self.schema_version = root, meter, schema_version
        self.data = _Sink(root, "work", meter)
        self.source = _Sink(root, "source", meter)
        self.work_lookup, self.source_lookup = {}, {}

    def source_row(self, locator, raw_row):
        key = stable_key(locator)
        need(key not in self.source_lookup, "duplicate retained source association")
        self.source_lookup[key] = self.source.add({"locator": encode(locator),
                                                  "record": raw_row})

    def work_row(self, row):
        exact(row, WorkRelations, "work relations")
        need(row.id not in self.work_lookup, "duplicate work denominator member")
        need(len(self.work_lookup) < self.meter.budget.max_records, "work member budget exceeded")
        self.work_lookup[row.id] = self.data.add(to_dict(row, schema_version=self.schema_version))

    def _index(self, family, values):
        sink = _Sink(self.root, family, self.meter)
        keys = sorted(values)
        for key in keys:
            chunk, line = values[key]
            sink.add({"id": key, "chunk": chunk, "line": line})
        sink.close(); offset = 0
        for row in sink.descriptors:
            row["first_id"], row["last_id"] = keys[offset], keys[offset + row["rows"] - 1]
            offset += row["rows"]
        return sink.descriptors


def publish_fragment_relations(producer, fresh_output, *, budgets=RelationBudgets()):
    from scar.analysis.fragment_relations import FragmentRelationProducer
    exact(producer, FragmentRelationProducer, "fixed relation producer")
    version = producer.schema_version
    root = Path(fresh_output).absolute(); root.mkdir(parents=False, exist_ok=False)
    meter = Meter(budgets)
    _atomic(root, "BUILDING.json", canonical({"schema": SCHEMA, "schema_version": version}), meter)
    writer = _Writer(root, meter, version)
    try:
        report = producer.produce(writer, meter)
        writer.data.close(); writer.source.close()
        need(len(writer.work_lookup) == report["declared_work_count"] == report["visited_work_count"], "incomplete work denominator cannot publish")
        work_index = writer._index("work-index", writer.work_lookup)
        source_index = writer._index("source-index", writer.source_lookup)
        producer.finish()
        manifest = {"schema": SCHEMA, "schema_version": version, "status": "PUBLISHED",
            "catalog": producer.catalog_document(), "producer": producer.producer_receipts(),
            "report": report, "work": writer.data.descriptors, "source": writer.source.descriptors,
            "work_index": work_index, "source_index": source_index, "io": meter.receipt(),
            "budgets": {f.name: getattr(budgets, f.name) for f in fields(budgets)},
            "scope": "PERSISTENT_QUALIFIED_RELATIONS_ONLY", "whole_program_complete": False}
        payload = canonical(manifest)
        need(len(payload) <= budgets.max_metadata_bytes, "relation manifest bound")
        receipt = _atomic(root, "manifest.json", payload, meter)
        return receipt
    except BaseException:
        # BUILDING and every completed chunk remain; no publication or retry.
        raise


class RelationPartitions:
    """Exact stored records, with per-record endpoint validation on query."""
    def __init__(self, manifest, *, expected_sha256, budgets=RelationBudgets(max_input_bytes=256_000_000, max_seconds=30)):
        path = Path(manifest).absolute(); data = path.read_bytes()
        need(len(data) <= budgets.max_metadata_bytes and hashlib.sha256(data).hexdigest() == expected_sha256, "published relation root receipt differs")
        m = strict_loads(data.decode())
        expected = {"schema", "schema_version", "status", "catalog", "producer", "report", "work", "source",
                    "work_index", "source_index", "io", "budgets", "scope", "whole_program_complete"}
        need(set(m) == expected and m["schema"] == SCHEMA and type(m["schema_version"]) is int
             and m["schema_version"] in (1, 2) and m["status"] == "PUBLISHED"
             and m["whole_program_complete"] is False, "unsupported relation publication")
        need(m["report"]["declared_work_count"] == m["report"]["visited_work_count"]
             == sum(row["rows"] for row in m["work"]), "published work denominator differs")
        self.root, self.manifest, self.budgets = path.parent, m, budgets
        for family in ("work", "source", "work_index", "source_index"):
            for number, d in enumerate(m[family]):
                folder = family.replace("_", "-")
                need(set(d) == {"uri", "rows", "stored_bytes", "stored_sha256", "decoded_bytes", "decoded_sha256"}
                     | ({"first_id", "last_id"} if family.endswith("index") else set()), "chunk fields")
                need(d["uri"] == folder + "/" + str(number).zfill(6) + ".jsonl.gz"
                     and type(d["rows"]) is int and 0 < d["rows"] <= 1000
                     and 0 < d["stored_bytes"] <= 8_000_000 and 0 < d["decoded_bytes"] <= 8_000_000, "chunk hard bounds/path")

    def _chunk(self, family, number, meter, cache):
        key = family, number
        if key not in cache:
            d = self.manifest[family][number]
            artifact = ProviderArtifact(str(self.root / d["uri"]), d["stored_sha256"], d["stored_bytes"], "scar.fragment-relation-chunk")
            raw = read_payload(artifact, meter, decoded_bytes=d["decoded_bytes"], decoded_sha256=d["decoded_sha256"],
                               compressed=True, maximum=8_000_000)
            rows = raw.splitlines(keepends=True)
            need(len(rows) == d["rows"] and all(row.endswith(b"\n") and len(row) <= self.budgets.max_record_bytes for row in rows), "chunk rows differ")
            cache[key] = rows
        return cache[key]

    def _lookup(self, family, key, meter, cache):
        desc = self.manifest[family + "_index"]
        number = bisect_left([d["last_id"] for d in desc], key)
        if number == len(desc) or key < desc[number]["first_id"]:
            return None
        rows = [strict_loads(row.decode()) for row in self._chunk(family + "_index", number, meter, cache)]
        need([r["id"] for r in rows] == sorted({r["id"] for r in rows}), "unordered/duplicate lookup index")
        found = [r for r in rows if r["id"] == key]
        if not found:
            return None
        p = found[0]
        raw = self._chunk(family, p["chunk"], meter, cache)[p["line"]]
        return strict_loads(raw.decode())

    def work(self, scope, reference, *, meter=None):
        from scar.analysis.fragment_relations import validate_retained_relation
        if meter is None:
            meter = Meter(self.budgets)
        exact(meter, Meter, "shared input budget")
        cache = {}
        identity = "work_relation:" + stable_key((scope, reference))
        document = self._lookup("work", identity, meter, cache)
        if document is None:
            return {"record": None, "costs": meter.receipt(), "whole_program_complete": False}
        need(document.get("schema_version") == self.manifest["schema_version"], "work/manifest transport version differs")
        row = from_dict(document)
        need(type(row) is WorkRelations and row.id == identity, "lookup changed the qualified work")
        validation = validate_retained_relation(row, self.manifest["catalog"], self.manifest["producer"],
                                                meter=meter, retention=self)
        return {"record": row, "validation": validation, "costs": meter.receipt(), "whole_program_complete": False}

    def source_record(self, locator, *, meter):
        """Only checksum-bound retained source chunks; never a caller resolver."""
        from scar.ir.execution.fragment_relations import FragmentLocator
        value = self._lookup("source", stable_key(locator), meter, {})
        need(value is not None and decode(FragmentLocator, value["locator"]) == locator, "source retention locator differs")
        return value["record"]
