"""Bounded immutable scope ledgers; indexed queries read one data chunk.

Publication requires the fixed source/call producer's owned scan. A failed or
interrupted build retains BUILDING plus closed chunks, never a PUBLISHED root.
The small sorted lookup index is derived and contains no graph facts.
"""
from __future__ import annotations

from bisect import bisect_left
from collections import Counter
from dataclasses import dataclass, fields
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import time

from scar.ir.modeling_scope import (
    AnalysisScope, Axis, Coverage, CoverageSubject, DenominatorInventory, Domain,
    Enumeration, LedgerEntry, RequirementStatus, digest, require, subject_key,
)
from scar.ir.modeling_scope_codec import to_dict, from_dict
from scar.ir.record_codec import loads as strict_loads

SCHEMA = "scar.partitioned-modeling-scope-ledger"
VERSION = 1


@dataclass(frozen=True)
class ScopeBudgets:
    max_chunk_bytes: int = 8_000_000
    max_chunk_rows: int = 1000
    max_record_bytes: int = 1_000_000
    max_manifest_bytes: int = 4_000_000
    max_entries: int = 200_000
    max_chunks: int = 10_000
    max_decoded_bytes: int = 4_000_000_000
    max_stored_bytes: int = 1_000_000_000
    max_seconds: int = 600

    def __post_init__(self):
        require(all(type(getattr(self, f.name)) is int and getattr(self, f.name) > 0 for f in fields(self)),
                "scope budgets require positive exact integers")
        require(self.max_chunk_bytes <= 8_000_000 and self.max_chunk_rows <= 1000
                and self.max_record_bytes <= self.max_chunk_bytes, "scope hard chunk/row bounds exceeded")


def _json(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                       separators=(",", ":")) + "\n").encode()


def _safe(root, uri):
    p = Path(uri)
    require(not p.is_absolute() and ".." not in p.parts and len(p.parts) == 2, "unsafe ledger chunk URI")
    actual = root / p
    require(not actual.is_symlink() and actual.resolve().is_relative_to(root.resolve()), "ledger chunk escapes root")
    return actual


def _atomic(root, name, value):
    payload = _json(value)
    temporary = root / ("." + name + "." + secrets.token_hex(8))
    with temporary.open("xb") as stream:
        stream.write(payload); stream.flush(); os.fsync(stream.fileno())
    os.link(temporary, root / name)
    temporary.unlink()
    return {"path": str(root / name), "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}


class _Sink:
    def __init__(self, root, family, limits, totals, start):
        self.root, self.family, self.limits, self.totals, self.start = root, family, limits, totals, start
        (root / family).mkdir()
        self.descriptors, self.pending, self.size = [], [], 0

    def add(self, row):
        data = _json(row)
        require(len(data) <= self.limits.max_record_bytes, "ledger record budget exceeded")
        if self.pending and (self.size + len(data) > self.limits.max_chunk_bytes
                             or len(self.pending) >= self.limits.max_chunk_rows):
            self.close()
        position = (len(self.descriptors), len(self.pending))
        self.pending.append(data); self.size += len(data)
        require(time.monotonic() - self.start <= self.limits.max_seconds, "ledger wall budget exceeded")
        return position

    def close(self):
        if not self.pending:
            return
        require(self.totals["chunks"] < self.limits.max_chunks, "ledger chunk budget exceeded")
        raw = b"".join(self.pending)
        stored = gzip.compress(raw, mtime=0)
        require(len(raw) <= self.limits.max_chunk_bytes and len(self.pending) <= self.limits.max_chunk_rows,
                "closed chunk exceeds hard bounds")
        require(len(stored) <= self.limits.max_chunk_bytes, "stored chunk exceeds hard8MB bound")
        require(self.totals["decoded_bytes"] + len(raw) <= self.limits.max_decoded_bytes
                and self.totals["stored_bytes"] + len(stored) <= self.limits.max_stored_bytes,
                "ledger output byte budget exceeded")
        uri = self.family + "/" + str(len(self.descriptors)).zfill(6) + ".jsonl.gz"
        with (self.root / uri).open("xb") as stream:
            stream.write(stored); stream.flush(); os.fsync(stream.fileno())
        desc = {"uri": uri, "rows": len(self.pending), "stored_bytes": len(stored),
                "decoded_bytes": len(raw), "stored_sha256": hashlib.sha256(stored).hexdigest(),
                "decoded_sha256": hashlib.sha256(raw).hexdigest()}
        self.descriptors.append(desc)
        self.totals["chunks"] += 1
        self.totals["decoded_bytes"] += len(raw); self.totals["stored_bytes"] += len(stored)
        self.pending, self.size = [], 0


def publish_scope_ledger(scope, rows, fresh_output, *, resolver, budgets=None):
    """Publish only rows from the exact fixed InputResolver owned scan.

    No callback, user boolean or caller-authored assessment certifies members.
    Cross-record checks below are acceptance bookkeeping, not runtime proof.
    """
    from scar.analysis.modeling_scope import InputResolver
    require(type(resolver) is InputResolver and type(scope) is AnalysisScope,
            "publication requires fixed typed InputResolver and AnalysisScope")
    limits = budgets if budgets is not None else ScopeBudgets()
    require(type(limits) is ScopeBudgets, "invalid scope publication budgets")
    limits.__post_init__(); scope.__post_init__()
    resolver.begin_publication(scope)
    root = Path(fresh_output).absolute()
    root.mkdir(parents=False, exist_ok=False)
    _atomic(root, "BUILDING.json", {"schema": SCHEMA, "schema_version": VERSION, "scope_revision": scope.revision})
    start, totals = time.monotonic(), {"chunks": 0, "decoded_bytes": 0, "stored_bytes": 0}
    data = _Sink(root, "entries", limits, totals, start)
    index = _Sink(root, "index", limits, totals, start)
    lookup, denominators, members, membership = {}, {}, Counter(), {}
    mandatory, unresolved = 0, Counter()
    try:
        for row in rows:
            require(time.monotonic() - start <= limits.max_seconds, "ledger wall budget exceeded")
            require(type(row) in (LedgerEntry, DenominatorInventory), "unsupported ledger row")
            resolver.accept_publication_row(scope, row)
            if type(row) is DenominatorInventory:
                require(row.domain not in denominators, "duplicate independent denominator")
                denominators[row.domain] = row
                continue
            require(len(lookup) < limits.max_entries, "ledger member/entry budget exceeded")
            obligation = row.obligation
            require(obligation.subject.scope_id == scope.id and obligation.scope_revision == scope.revision,
                    "ledger entry belongs to another scope")
            require(obligation.id not in lookup, "duplicate obligation identity")
            if row.member is not None:
                key = row.member.denominator
                members[key] += 1
                membership.setdefault(key, hashlib.sha256()).update((digest(subject_key(row.member.subject)) + "\n").encode())
            mandatory += int(obligation.mandatory)
            for axis in row.assessment.axes:
                for result in axis.results:
                    if result.status is not RequirementStatus.SATISFIED:
                        unresolved[axis.axis.value] += 1
            lookup[obligation.id] = data.add(to_dict(row))
        resolver.finish_publication(scope)
        require(set(denominators) == set(Domain), "missing independent contract denominator")
        for row in denominators.values():
            require(members[row.id] == row.enumerated_count, "denominator member count mismatch")
            if row.membership_sha256 is not None:
                actual = membership.get(row.id, hashlib.sha256()).hexdigest()
                require(actual == row.membership_sha256, "denominator membership digest mismatch")
        data.close()
        sorted_ids = sorted(lookup)
        for ordinal, identity in enumerate(sorted_ids):
            chunk, line = lookup[identity]
            index.add({"id": identity, "chunk": chunk, "line": line})
        index.close()
        offset = 0
        for desc in index.descriptors:
            desc["first_id"] = sorted_ids[offset]
            desc["last_id"] = sorted_ids[offset + desc["rows"] - 1]
            offset += desc["rows"]
        # No semantic proof reuse is implemented by policy v1: semantic axes
        # are required OPEN even if source metadata contains PASS/validated.
        aggregate = "OPEN"
        manifest = {"schema": SCHEMA, "schema_version": VERSION, "status": "PUBLISHED",
            "scope": to_dict(scope), "denominators": [to_dict(denominators[d]) for d in Domain],
            "entries": data.descriptors, "index": index.descriptors, "totals": totals,
            "counts": {"obligations": len(lookup), "mandatory": mandatory,
                       "members": sum(members.values()), "unresolved_requirements": dict(unresolved)},
            "verification": {"aggregate": aggregate, "semantic_policy": "MEMBERSHIP_ONLY_V1",
                "evidence_review": "PRODUCER_BYTE_MEMBERSHIP; semantic/native/state/content/ready UNREVIEWED",
                "publication_is_program_completeness": False},
            "budgets": {f.name: getattr(limits, f.name) for f in fields(limits)},
            "producer": resolver.producer_receipts(), "input_review": resolver.review_receipt(),
            "wall_seconds": time.monotonic() - start}
        require(len(_json(manifest)) <= limits.max_manifest_bytes, "ledger manifest budget exceeded")
        require(time.monotonic() - start <= limits.max_seconds, "ledger wall budget exceeded before commit")
        receipt = _atomic(root, "manifest.json", manifest)
        return {"manifest": receipt, "aggregate": aggregate, "counts": manifest["counts"],
                "totals": totals, "scope_revision": scope.revision}
    except BaseException as error:
        # Only already-closed chunks survive. No manifest is published.
        try:
            _atomic(root, "FAILED.json", {"schema": SCHEMA, "scope_revision": scope.revision,
                "status": "PUBLISHED" if (root / "manifest.json").is_file() else "BUILDING",
                "reason": type(error).__name__ + ": " + str(error),
                "closed_totals": totals, "entries_seen": len(lookup), "input_review": resolver.review_receipt()})
        except Exception:
            pass
        raise


class ScopePartitions:
    """Checksum-bound read-only lookup; no source/raw replay or live session."""
    def __init__(self, manifest, *, expected_sha256, budgets=None):
        self.path = Path(manifest).absolute()
        self.root = self.path.parent
        self.limits = ScopeBudgets() if budgets is None else budgets
        require(type(self.limits) is ScopeBudgets, "invalid reader budgets")
        self.limits.__post_init__()
        require(self.path.is_file() and not self.path.is_symlink()
                and self.path.stat().st_size <= self.limits.max_manifest_bytes, "invalid manifest file/byte budget")
        raw = self.path.read_bytes()
        require(hashlib.sha256(raw).hexdigest() == expected_sha256, "ledger manifest receipt mismatch")
        self.manifest = strict_loads(raw.decode())
        m = self.manifest
        require(type(m) is dict and m.get("schema") == SCHEMA and type(m.get("schema_version")) is int
                and m["schema_version"] == VERSION and m.get("status") == "PUBLISHED", "unsupported/unpublished ledger")
        require(set(m) == {"schema", "schema_version", "status", "scope", "denominators", "entries", "index", "totals",
                           "counts", "verification", "budgets", "producer", "input_review", "wall_seconds"},
                "unexpected ledger manifest fields")
        self.scope = from_dict(m["scope"])
        require(type(self.scope) is AnalysisScope, "manifest scope type mismatch")
        denoms = [from_dict(d) for d in m["denominators"]]
        require(len(denoms) == len(Domain) and {d.domain for d in denoms} == set(Domain)
                and all(type(d) is DenominatorInventory and d.scope_revision == self.scope.revision for d in denoms),
                "ledger denominator scope/set mismatch")
        require(m["verification"].get("aggregate") == "OPEN"
                and m["verification"].get("semantic_policy") == "MEMBERSHIP_ONLY_V1",
                "initial ledger cannot assert semantic completion")
        for family in ("entries", "index"):
            require(type(m[family]) is list, "invalid chunk descriptor table")
            for number, d in enumerate(m[family]):
                expected = {"uri", "rows", "stored_bytes", "decoded_bytes", "stored_sha256", "decoded_sha256"}
                if family == "index":
                    expected |= {"first_id", "last_id"}
                require(type(d) is dict and set(d) == expected
                    and d["uri"] == family + "/" + str(number).zfill(6) + ".jsonl.gz", "bad chunk descriptor/path")
                require(type(d["rows"]) is int and 0 < d["rows"] <= self.limits.max_chunk_rows
                        and type(d["decoded_bytes"]) is int and 0 < d["decoded_bytes"] <= self.limits.max_chunk_bytes
                        and type(d["stored_bytes"]) is int and 0 < d["stored_bytes"] <= self.limits.max_chunk_bytes,
                        "chunk exceeds independent reader bound")
                for name in ("stored_sha256", "decoded_sha256"):
                    require(type(d[name]) is str and len(d[name]) == 64, "invalid chunk SHA")
        require(sum(d["rows"] for d in m["entries"]) == m["counts"]["obligations"]
                == sum(d["rows"] for d in m["index"]), "index/data count mismatch")
        actual_totals = {"chunks": len(m["entries"]) + len(m["index"]),
            "decoded_bytes": sum(d["decoded_bytes"] for d in (*m["entries"], *m["index"])),
            "stored_bytes": sum(d["stored_bytes"] for d in (*m["entries"], *m["index"]))}
        require(m["totals"] == actual_totals and actual_totals["chunks"] <= self.limits.max_chunks
                and actual_totals["decoded_bytes"] <= self.limits.max_decoded_bytes
                and actual_totals["stored_bytes"] <= self.limits.max_stored_bytes
                and type(m["counts"]["obligations"]) is int
                and 0 <= m["counts"]["obligations"] <= self.limits.max_entries,
                "ledger totals/count budget mismatch")
        for left, right in zip(m["index"], m["index"][1:]):
            require(left["last_id"] < right["first_id"], "index ranges overlap or are unordered")
        self._ends = [d["last_id"] for d in m["index"]]
        self.last_query = {}

    def _chunk(self, desc):
        path = _safe(self.root, desc["uri"])
        require(path.is_file() and path.stat().st_size == desc["stored_bytes"], "chunk stored-size mismatch")
        stored = path.read_bytes()
        require(hashlib.sha256(stored).hexdigest() == desc["stored_sha256"], "chunk stored SHA mismatch")
        with gzip.GzipFile(fileobj=io.BytesIO(stored)) as stream:
            raw = stream.read(self.limits.max_chunk_bytes + 1)
        require(len(raw) == desc["decoded_bytes"] and hashlib.sha256(raw).hexdigest() == desc["decoded_sha256"],
                "chunk decoded receipt mismatch")
        lines = raw.splitlines(keepends=True)
        require(len(lines) == desc["rows"] and all(x.endswith(b"\n") and len(x) <= self.limits.max_record_bytes for x in lines),
                "chunk line/record bound mismatch")
        return lines

    def query(self, identity, *, scope_revision):
        import re
        require(scope_revision == self.scope.revision, "query scope revision mismatch")
        require(type(identity) is str and re.fullmatch(r"obligation:[0-9a-f]{64}", identity) is not None,
                "query requires exact obligation ID")
        self.last_query = {"index_chunks_read": 0, "data_chunks_read": 0, "raw_replayed": False}
        index_number = bisect_left(self._ends, identity)
        if index_number == len(self._ends):
            self.last_query = {"index_chunks_read": 0, "data_chunks_read": 0, "raw_replayed": False}
            return None
        desc = self.manifest["index"][index_number]
        if identity < desc["first_id"]:
            return None
        rows = [strict_loads(x.decode()) for x in self._chunk(desc)]
        require(all(type(r) is dict and set(r) == {"id", "chunk", "line"} for r in rows)
                and [r["id"] for r in rows] == sorted({r["id"] for r in rows}), "invalid lookup index rows")
        row = next((r for r in rows if r["id"] == identity), None)
        self.last_query = {"index_chunks_read": 1, "data_chunks_read": 0, "raw_replayed": False,
                           "evidence_review": "REUSED_RETAINED_BYTE_MEMBERSHIP; semantic evidence UNREVIEWED"}
        if row is None:
            return None
        require(type(row["chunk"]) is int and 0 <= row["chunk"] < len(self.manifest["entries"])
                and type(row["line"]) is int and row["line"] >= 0, "index row coordinate invalid")
        lines = self._chunk(self.manifest["entries"][row["chunk"]])
        require(row["line"] < len(lines), "index line is outside data chunk")
        entry = from_dict(strict_loads(lines[row["line"]].decode()))
        require(type(entry) is LedgerEntry and entry.obligation.id == identity
                and entry.obligation.scope_revision == scope_revision
                and entry.obligation.subject.scope_id == self.scope.id, "lookup points to another original subject/scope")
        self.last_query["data_chunks_read"] = 1
        return entry


__all__ = ["ScopeBudgets", "ScopePartitions", "publish_scope_ledger", "SCHEMA", "VERSION"]
