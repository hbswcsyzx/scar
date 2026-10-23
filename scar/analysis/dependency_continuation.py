"""Exact, artifact-qualified continuation of a dependency admission sidecar.

This is a source-recovery coordinator, not public source/compiler replay.
Unchanged historical witnesses are inherited explicitly. Only missing source
snapshots and source graphs are constructed; the program inventory is untouched.
"""
from __future__ import annotations

import base64
from collections import Counter, defaultdict
from copy import deepcopy
import csv
from dataclasses import dataclass
from email.parser import BytesParser
from email.policy import compat32
import gzip
import hashlib
from io import StringIO
import json
import os
from pathlib import Path
import re
import sys
import time

from scar.analysis.call_compilation import UnsupportedCompilationFlags, future_flags_for
from scar.analysis.call_demand import _SourceWorkspace
from scar.analysis.call_edges import _Sources
from scar.analysis.call_seeds import _EnteredCodeSink
from scar.analysis.call_trace_reader import scan_call_trace
from scar.analysis.dependency_sources import (
    DependencySourceBudget, _AUTHORITY, _Ledger, _Limit, _PROFILE,
    _bounded_canonical, _canonical, _decode_source, _gap, _pick_root,
    _read_file, _sha, _source_roots,
)
from scar.analysis.program_context_store import PreparedContextStore
from scar.analysis.source_layers import _write_gzip_exclusive
from scar.ir.program.call_edges import CallEdgeBudget, CodeSourceLink
from scar.ir.program.expansion import ContextStoreBudget
from scar.ir.program.inventory import SourceContextDigest
from scar.ir.record_codec import decode, encode


@dataclass(frozen=True, slots=True)
class DependencyContinuationBudget:
    """Independent input, delta archive and small-report ceilings.

    Parent artifact reads do not consume delta capacity. Source snapshots,
    graphs and checkpoints/reports cannot borrow one another's capacity.
    """

    max_parent_report_bytes: int = 64_000_000
    max_parent_artifacts: int = 4096
    max_parent_artifact_bytes: int = 1_600_000_000
    max_parent_artifact_record_bytes: int = 512_000_000
    max_roots: int = 8
    max_snapshot_bytes: int = 8_000_000
    max_snapshot_record_bytes: int = 8_000_000
    max_graph_bytes: int = 1_200_000_000
    max_graph_record_bytes: int = 512_000_000
    max_report_bytes: int = 64_000_000
    max_compile_variants: int = 768

    def __post_init__(self):
        for name in self.__dataclass_fields__:
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(name + " must be a positive exact integer")


def _require(condition, detail):
    if not condition:
        raise ValueError(detail)


def _json(payload):
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    def nonfinite(value):
        raise ValueError("nonfinite JSON value: " + value)
    return json.loads(payload, object_pairs_hook=pairs, parse_constant=nonfinite)


def _fingerprint(raw):
    text = _decode_source(raw)
    return text, "sha256:" + _sha(text.encode("utf-8"))


def _exact_canonical(document, retain_bytes):
    """Count/hash the entire canonical record even when storage is rejected.

    Retention is bounded by the independent record/remaining-total ceiling;
    after crossing it the encoder keeps counting without retaining payload.
    """
    encoder = json.JSONEncoder(sort_keys=True, ensure_ascii=False,
                               separators=(",", ":"), allow_nan=False)
    digest, size, payload = hashlib.sha256(), 0, bytearray()
    for chunk in encoder.iterencode(document):
        part = chunk.encode("utf-8")
        digest.update(part)
        size += len(part)
        if payload is not None:
            if size > retain_bytes:
                payload = None
            else:
                payload.extend(part)
    return size, digest.hexdigest(), None if payload is None else bytes(payload)


class _RawSink(_EnteredCodeSink):
    def __init__(self):
        super().__init__()
        self.exits = 0

    def exit(self, value):
        self.exits += 1

    def abort(self):
        super().abort()
        self.exits = 0


def _read_parent(parent_directory, expected_sha, program_root, budget):
    _require(type(expected_sha) is str and re.fullmatch(r"[0-9a-f]{64}", expected_sha),
             "expected parent report SHA256 is required")
    parent = Path(parent_directory).resolve(strict=True)
    _require(parent.is_dir(), "parent must be a retained directory")
    path = parent / "admissions.json"
    _require(path.is_file() and not path.is_symlink(), "parent report must be an ordinary file")
    raw = _read_file(path, budget.max_parent_report_bytes)
    _require(_sha(raw) == expected_sha, "parent report raw SHA256 mismatch")
    document = _json(raw)
    _require(type(document) is dict and document.get("schema") == "scar.dependency-source-admissions"
             and type(document.get("schema_version")) is int and document["schema_version"] == 1,
             "continuation requires a dependency admissions v1 parent")
    _require(_canonical(document) == raw, "parent report is not its exact canonical document")
    _require(document["program_root"] == str(program_root), "parent program root mismatch")
    _require(all(document.get(name) is False for name in _AUTHORITY),
             "parent cannot claim execution/body/transformation authority")
    _require(document["compilation_profile"] == _PROFILE.value,
             "parent compiler profile mismatch")
    roots = document["source_roots"]
    _require(type(roots) is list and len(roots) <= budget.max_roots,
             "parent source-root budget exceeded")
    identifiers = set()
    for root in roots:
        _require(root["id"] not in identifiers, "duplicate parent source root")
        identifiers.add(root["id"])
        fields = {name: value for name, value in root.items() if name != "id"}
        _require(root["id"] == "dependency-source-root:" + _sha(_canonical(fields)),
                 "parent namespace identity mismatch")
        namespace = Path(root["namespace_root"])
        _require(namespace.is_absolute() and namespace != Path(namespace.anchor),
                 "parent cannot grant a filesystem-wide namespace")
    current_roots, root_gaps = _source_roots(
        program_root, DependencySourceBudget(max_roots=budget.max_roots))
    _require(not root_gaps and current_roots == roots,
             "current interpreter/source namespaces differ from the parent")
    return parent, document, {"directory": str(parent), "path": "admissions.json",
                              "raw_sha256": expected_sha, "raw_bytes": len(raw)}


def _verify_raw(parent, scanned, sink):
    _require(parent["trace_directory"] == scanned.directory, "parent trace directory mismatch")
    _require(parent["trace_files"] == encode(scanned.files),
             "complete raw file SHA/byte/line identity differs from parent")
    _require(parent["collection_metadata"] == list(scanned.metadata),
             "capture metadata differs from parent")
    _require(parent["raw_scan_issues"] == encode(scanned.issues),
             "raw scan issues differ from parent")
    _require(all(meta.get("python") == sys.version for meta in scanned.metadata),
             "recorded full Python string does not match this interpreter")
    captures = {(capture.process_id, capture.code.key): capture for capture in scanned.captures}
    groups = {(group.process_id, group.code): group for group in sink.groups()}
    admitted = {(row["process_id"], row["code"]): row for row in parent["admissions"]}
    _require(len(admitted) == len(parent["admissions"]) and set(admitted) == set(groups),
             "parent entered process/code group membership differs from raw capture")
    statuses, weighted, frontiers = Counter(), Counter(), Counter()
    for key, group in groups.items():
        row, capture = admitted[key], captures.get(key)
        _require(type(row["entered_invocations"]) is int and row["entered_invocations"] == group.count,
                 "parent entered invocation count differs from raw capture")
        _require(row["first_anchor"] == encode(group.first_anchor)
                 and row["last_anchor"] == encode(group.last_anchor), "parent group anchors mismatch")
        _require(row["captured_code"] == (encode(capture.code) if capture else None),
                 "parent complete captured-code descriptor mismatch")
        _require(row["descriptor_anchor"] == (encode(capture.anchor) if capture else None),
                 "parent descriptor anchor mismatch")
        link = row["code_source_link"]
        if link is not None:
            decoded = decode(CodeSourceLink, link)
            _require(decoded.code == group.code, "parent code/source witness belongs to another code")
            _require(row["status"] == "SOURCE_" + decoded.status.value,
                     "parent source status differs from its code/source witness")
        statuses[row["status"]] += 1
        weighted[row["status"]] += group.count
        for code in {gap["code"] for gap in row["frontiers"]}:
            frontiers[code] += group.count
    summary = parent["summary"]
    _require(summary["entered_code_groups"] == len(groups)
             and summary["entered_invocations"] == sum(group.count for group in groups.values())
             and summary["statuses"] == dict(statuses)
             and summary["weighted_statuses"] == dict(weighted)
             and summary["weighted_frontiers"] == dict(frontiers), "parent summary differs from raw groups")
    return captures, {"raw_files": len(scanned.files), "captured_descriptors": len(scanned.captures),
                      "entered_code_groups": len(groups),
                      "entered_invocations": sum(group.count for group in groups.values()),
                      "exited_invocations": sink.exits,
                      "all_raw_file_sha_counts_and_descriptors_match": True}


def _verify_parent_artifacts(directory, parent, budget, emit):
    roots = {root["id"]: root for root in parent["source_roots"]}
    files = {row["path"]: row for row in parent["source_files"]}
    _require(len(files) == len(parent["source_files"]), "duplicate parent source file")
    wanted = defaultdict(list)
    for row in parent["admissions"]:
        link = row["code_source_link"]
        if link is not None and link["snapshot"] is not None:
            filename = link["snapshot"]["path"]
            _require(filename in files, "code/source snapshot has no parent source-file row")
            source = files[filename]
            _require(link["snapshot"]["fingerprint"] == source["fingerprint"],
                     "parent code/source witness snapshot fingerprint mismatch")
            if source["source_graph_artifact"] is not None:
                wanted[source["source_graph_artifact"]["path"]].append(link)
    headers, snapshots, providers = {}, {}, {}
    total = 0
    for family in ("sources", "graphs", "providers"):
        base = directory / family
        _require(base.is_dir() and not base.is_symlink(), "parent artifact directory unavailable")
        for path in sorted(base.iterdir()):
            _require(path.is_file() and not path.is_symlink()
                     and re.fullmatch(r"[0-9a-f]{64}\.json\.gz", path.name),
                     "unexpected or nonordinary parent artifact")
            _require(len(headers) < budget.max_parent_artifacts, "parent artifact count budget exceeded")
            remaining = min(budget.max_parent_artifact_record_bytes,
                            budget.max_parent_artifact_bytes - total)
            _require(remaining >= 1, "parent artifact read budget exhausted")
            emit("parent_artifact", "BEGIN", path=str(path.relative_to(directory)))
            with gzip.open(path, "rb") as stream:
                payload = stream.read(remaining + 1)
            _require(len(payload) <= remaining, "parent artifact record/total read budget exceeded")
            digest = _sha(payload)
            _require(path.name == digest + ".json.gz", "parent artifact canonical SHA mismatch")
            doc = _json(payload)
            _require(_canonical(doc) == payload, "parent artifact is not canonical JSON")
            _require(type(doc.get("schema_version")) is int and doc["schema_version"] == 1,
                     "unsupported parent artifact version")
            relative = str(path.relative_to(directory))
            header = {"schema": doc["schema"], "schema_version": 1, "path": relative,
                      "canonical_sha256": digest, "canonical_bytes": len(payload),
                      "compressed_bytes": path.stat().st_size}
            total += len(payload)
            if family in ("sources", "providers"):
                raw = base64.b64decode(doc["raw_base64"], validate=True)
                _require(len(raw) == doc["raw_bytes"] and _sha(raw) == doc["raw_sha256"],
                         "parent retained raw bytes SHA/size mismatch")
                if family == "sources":
                    _require(doc["schema"] == "scar.dependency-source-snapshot",
                             "parent source artifact schema mismatch")
                    text, fingerprint = _fingerprint(raw)
                    _require(text == doc["decoded_text"] and fingerprint == doc["fingerprint"],
                             "parent decoded source snapshot mismatch")
                    _require(doc["code_source_match_established"] is False,
                             "source bytes cannot establish code correspondence alone")
                    snapshots[relative] = {key: doc[key] for key in (
                        "source_root", "namespace_root", "original_uri", "raw_sha256",
                        "raw_bytes", "fingerprint")}
                else:
                    _require(doc["schema"] == "scar.dependency-provider-artifact",
                             "parent provider artifact schema mismatch")
                    providers[doc["original_uri"]] = (raw, header)
            elif family == "graphs":
                _require(doc["schema"] == "scar.dependency-source-graphs"
                         and doc["independent_source_replay_established"] is False
                         and all(doc.get(name) is False for name in _AUTHORITY),
                         "parent graph schema/authority mismatch")
                root = roots[doc["source_root"]]
                _require(doc["namespace_root"] == doc["context"]["namespace_root"]
                         == root["namespace_root"], "parent graph namespace mismatch")
                for key, graph in (("semantic_sha256", "semantic"),
                                   ("semantics_sha256", "semantics"), ("control_sha256", "control")):
                    _require(_sha(_canonical(doc[graph])) == doc["context"][key],
                             "parent original source context digest mismatch")
                definitions = {row["id"]["wire"]: row for row in doc["semantic"]["definitions"]}
                atoms = {row["id"]["wire"]: row["reference"]
                         for row in doc["semantic"]["source_atoms"]}
                for link in wanted.get(relative, ()):
                    _require(link["snapshot"] == doc["snapshot"], "code/source graph snapshot mismatch")
                    if link["definition"] is not None:
                        definition = definitions[link["definition"]["wire"]]
                        reference = link["source"]
                        _require(reference is not None
                                 and reference["atom_id"]["wire"] in {
                                     atom["wire"] for atom in definition["source_atoms"]}
                                 and atoms[reference["atom_id"]["wire"]] == reference,
                                 "parent DefinitionID/SourceReference membership mismatch")
                header = {**header, "source_root": doc["source_root"], "snapshot": doc["snapshot"],
                          "context": doc["context"],
                          "source_snapshot_artifact": doc["source_snapshot_artifact"]}
            headers[relative] = header
            emit("parent_artifact", "END", path=relative, canonical_bytes=len(payload))
            del doc, payload

    def reference(value):
        _require(type(value) is dict, "parent artifact reference must be an object")
        header = headers[value["path"]]
        _require(set(value) == {"schema", "schema_version", "path", "canonical_sha256",
                               "canonical_bytes", "compressed_bytes"}
                 and all(value[key] == header[key] for key in value),
                 "parent artifact reference/header mismatch")
        return header

    for filename, row in files.items():
        path, root = Path(filename), roots[row["source_root"]]
        _require(type(row["raw_bytes"]) is int and row["raw_bytes"] >= 0
                 and type(row["raw_sha256"]) is str and re.fullmatch(r"[0-9a-f]{64}", row["raw_sha256"])
                 and type(row["fingerprint"]) is str and re.fullmatch(r"sha256:[0-9a-f]{64}", row["fingerprint"]),
                 "parent source-file fingerprint/size fields are malformed")
        _require(path.is_absolute() and path.suffix == ".py"
                 and path.is_relative_to(root["namespace_root"])
                 and _pick_root(path, parent["source_roots"])["id"] == root["id"],
                 "parent source file is outside its qualified namespace")
        if row["snapshot_artifact"] is not None:
            reference(row["snapshot_artifact"])
            snapshot = snapshots[row["snapshot_artifact"]["path"]]
            _require(snapshot["original_uri"] == filename
                     and snapshot["source_root"] == row["source_root"]
                     and snapshot["namespace_root"] == root["namespace_root"]
                     and all(snapshot[name] == row[name] for name in ("raw_sha256", "raw_bytes", "fingerprint")),
                     "parent source snapshot/file witness mismatch")
        if row["source_graph_artifact"] is not None:
            graph = reference(row["source_graph_artifact"])
            reference(graph["source_snapshot_artifact"])
            _require(graph["source_root"] == row["source_root"]
                     and graph["snapshot"]["path"] == filename
                     and graph["snapshot"]["fingerprint"] == row["fingerprint"]
                     and graph["source_snapshot_artifact"] == row["snapshot_artifact"]
                     and graph["context"] == row["context"], "parent graph/file witness mismatch")
        for provider in row["providers"]:
            if provider["kind"] == "INSTALLED_DISTRIBUTION":
                reference(provider["metadata_artifact"]); reference(provider["record_artifact"])
    _require(parent["summary"]["source_files_with_snapshots"] == sum(
        row["snapshot_artifact"] is not None for row in files.values())
        and parent["summary"]["source_files_with_graphs"] == sum(
            row["source_graph_artifact"] is not None for row in files.values()),
        "parent source artifact summary mismatch")
    return files, providers, {"artifact_files_checked": len(headers),
                              "artifact_canonical_bytes_checked": total,
                              "all_artifact_hashes_and_references_match": True}


def _guard(row, call_budget, remaining_bytes=None):
    result = {"path": row["path"], "source_root": row["source_root"],
              "expected_raw_sha256": row["raw_sha256"], "expected_raw_bytes": row["raw_bytes"],
              "expected_fingerprint": row["fingerprint"], "matches": False}
    try:
        path = Path(row["path"])
        _require(path == path.resolve(strict=True) and path.is_file(), "source is missing or noncanonical")
        limit = min(4_000_000, call_budget.max_source_bytes)
        if remaining_bytes is not None:
            limit = min(limit, remaining_bytes)
        raw = _read_file(path, limit)
        text, fingerprint = _fingerprint(raw)
        result.update(current_raw_sha256=_sha(raw), current_raw_bytes=len(raw),
                      current_fingerprint=fingerprint)
        result["matches"] = (result["current_raw_sha256"] == row["raw_sha256"]
                             and len(raw) == row["raw_bytes"] and fingerprint == row["fingerprint"])
        result["status"] = "MATCH" if result["matches"] else "CURRENT_SOURCE_DRIFT"
        return result, raw, text
    except (OSError, ValueError, TypeError, UnicodeError, SyntaxError) as error:
        result.update(status=("CURRENT_SOURCE_GUARD_BUDGET" if isinstance(error, _Limit)
                              else "CURRENT_SOURCE_UNAVAILABLE"),
                      detail=type(error).__name__ + ": " + str(error))
        return result, None, None


def _locator(artifact, source_root, origin, parent_ref=None):
    if artifact is None:
        return None
    result = {"origin": origin, "source_root": source_root, "artifact": artifact}
    if origin == "PARENT":
        result["parent_report_raw_sha256"] = parent_ref["raw_sha256"]
        result["parent_directory"] = parent_ref["directory"]
    return result


def _providers_from_retained_metadata(providers, roots, wanted, parent_ref):
    """Use only already archived METADATA/RECORD; no environment enumeration."""
    owners = defaultdict(list)
    for uri, (raw, metadata) in sorted(providers.items()):
        path = Path(uri)
        if path.name != "METADATA" or not path.parent.name.endswith(".dist-info"):
            continue
        paired = providers.get(str(path.parent / "RECORD"))
        root = _pick_root(path, roots)
        if paired is None or root is None or not {"purelib", "platlib"}.intersection(root["roles"]):
            continue
        message = BytesParser(policy=compat32).parsebytes(raw, headersonly=True)
        name, version = message.get("Name"), message.get("Version")
        if (len(message.get_all("Name", [])) != 1 or len(message.get_all("Version", [])) != 1
                or type(name) is not str or not name or type(version) is not str or not version):
            continue
        records, record = paired
        provider = {"kind": "INSTALLED_DISTRIBUTION", "name": name, "version": version,
                    "metadata_artifact": _locator(metadata, root["id"], "PARENT", parent_ref),
                    "record_artifact": _locator(record, root["id"], "PARENT", parent_ref),
                    "record_is_ownership_evidence_not_source_or_code_proof": True,
                    "metadata_origin": "REUSED_PARENT_METADATA_BYTES_NOT_CURRENT_RESCAN"}
        matched = set()
        for row in csv.reader(StringIO(records.decode("utf-8", errors="strict"))):
            if not row or not row[0] or Path(row[0]).is_absolute():
                continue
            candidate = Path(os.path.normpath(str(Path(root["namespace_root"]) / row[0])))
            if candidate.is_relative_to(root["namespace_root"]) and str(candidate) in wanted:
                matched.add(str(candidate))
        for filename in matched:
            owners[filename].append(provider)
    return owners


class _DeltaArchives:
    def __init__(self, out, budget, call_budget, parent_ref, files, roots, guards, emit):
        self.out, self.budget, self.call = out, budget, call_budget
        self.parent_ref, self.files, self.roots = parent_ref, files, roots
        self.guards, self.emit = guards, emit
        self.counts = Counter()

    def write(self, directory, document, row):
        family = "snapshot" if directory == "sources" else "graph"
        record_cap = getattr(self.budget, "max_" + family + "_record_bytes")
        total_cap = getattr(self.budget, "max_" + family + "_bytes")
        used = self.counts[family + "_canonical_bytes_written"]
        size, digest, payload = _exact_canonical(document, min(record_cap, total_cap - used))
        attempt = {"family": family, "canonical_bytes": size, "canonical_sha256": digest,
                   "record_cap": record_cap, "remaining_total_before": total_cap - used}
        row["archive_attempts"].append(attempt)
        self.counts[family + "_canonical_bytes_attempted"] += size
        if payload is None:
            attempt["status"] = "RECORD_BUDGET" if size > record_cap else "TOTAL_BUDGET"
            self.emit(family + "_archive", "BUDGET_REJECTED", path=row["path"],
                      canonical_bytes=size, canonical_sha256=digest, record_cap=record_cap,
                      remaining_total=total_cap - used)
            raise _Limit(f"{family} archive {attempt['status']}: actual={size}, "
                         f"record_cap={record_cap}, remaining_total={total_cap - used}")
        path = f"{directory}/{digest}.json.gz"
        compressed = _write_gzip_exclusive(self.out / path, payload)
        artifact = {"schema": document["schema"], "schema_version": document["schema_version"],
                    "path": path, "canonical_sha256": digest, "canonical_bytes": size,
                    "compressed_bytes": compressed}
        self.counts[family + "_canonical_bytes_written"] += size
        self.counts[family + "_compressed_bytes_written"] += compressed
        self.counts[family + "_artifacts_written"] += 1
        attempt["status"] = "STORED"
        self.emit(family + "_archive", "END", path=row["path"], canonical_bytes=size,
                  canonical_sha256=digest, compressed_bytes=compressed)
        return _locator(artifact, row["source_root"], "CONTINUATION")

    def source(self, row, raw, text):
        root = self.roots[row["source_root"]]
        row["snapshot_artifact"] = self.write("sources", {
            "schema": "scar.dependency-source-snapshot", "schema_version": 1,
            "source_root": root["id"], "namespace_root": root["namespace_root"],
            "original_uri": row["path"], "raw_sha256": row["raw_sha256"], "raw_bytes": len(raw),
            "raw_base64": base64.b64encode(raw).decode("ascii"), "decoded_text": text,
            "fingerprint": row["fingerprint"],
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
            "code_source_match_established": False,
        }, row)

    def prepared(self, context):
        row = self.files[str(context.path)]
        if row["source_graph_artifact"] is not None:
            return
        _require(row["snapshot_artifact"] is not None, "cannot archive graphs without retained source bytes")
        guard, _, _ = _guard(row, self.call)
        self.guards[row["path"]] = guard
        _require(guard["matches"], "source drifted before missing graph export")
        snapshot = encode(context.semantics.sources[str(context.path)])
        _require(snapshot["path"] == row["path"] and snapshot["fingerprint"] == row["fingerprint"]
                 and "sha256:" + _sha(context.text.encode()) == row["fingerprint"],
                 "new source layers differ from retained historical snapshot")
        semantic, semantics, control = (context.semantic.to_dict(), context.semantics.to_dict(),
                                        context.control.to_dict())
        digest = encode(SourceContextDigest(str(context.root), _sha(_canonical(semantic)),
            _sha(_canonical(semantics)), _sha(_canonical(control))))
        if row["parent_context"] is not None:
            _require(digest == row["parent_context"],
                     "reconstructed missing graphs differ from original source context digests")
        row["context"] = digest
        row["source_graph_artifact"] = self.write("graphs", {
            "schema": "scar.dependency-continuation-source-graphs", "schema_version": 1,
            "source_root": row["source_root"], "namespace_root": str(context.root),
            "snapshot": snapshot, "source_snapshot_locator": row["snapshot_artifact"],
            "context": digest, "semantic": semantic, "semantics": semantics, "control": control,
            "source_layer_producer": "CONSTRUCTED_ONLY_FOR_MISSING_PARENT_GRAPH",
            "parent_context_digest_matched": row["parent_context"] is not None,
            "independent_source_replay_established": False, **_AUTHORITY,
        }, row)


class _ContinuationWorkspace(_SourceWorkspace):
    def __init__(self, root, context_budget, shared_store, archives, emit):
        super().__init__(root["namespace_root"], context_budget, entry=None)
        self.store.close()
        self.store = shared_store
        self.archives, self.emit = archives, emit
        self.exported = set()

    def prepare(self, path):
        self.emit("prepare", "BEGIN", path=str(path))
        context = super().prepare(path)
        self.emit("prepare", "END", path=str(path))
        key = str(path)
        if key not in self.exported:
            self.exported.add(key)
            try:
                self.archives.prepared(context)
            except _Limit as error:
                # Missing graph storage must not suppress a valid new compiler
                # witness. The source snapshot has its own reserved capacity.
                self.archives.files[key]["frontiers"].append(
                    _gap("SOURCE_GRAPH_ARCHIVE_BUDGET", str(error)))
        return context


def continue_dependency_sources(trace_directory, project_root, parent_directory, fresh_out, *,
                                expected_parent_report_sha256,
                                call_budget=CallEdgeBudget(),
                                budget=DependencyContinuationBudget(),
                                context_budget=ContextStoreBudget(), progress=None):
    """Inherit audited historical fragments, construct only missing evidence.

    The parent is immutable and explicitly SHA-pinned. Output is a new sidecar
    plus per-file checkpoints; it is not inventory v8 or public replay proof.
    No target/package code is imported or executed by this coordinator.
    """
    _require(type(call_budget) is CallEdgeBudget and type(budget) is DependencyContinuationBudget
             and type(context_budget) is ContextStoreBudget, "exact typed independent budgets required")
    call_budget.__post_init__(); budget.__post_init__(); context_budget.__post_init__()
    _require(progress is None or callable(progress), "progress must be callable or None")
    program_root = Path(project_root).resolve(strict=True)
    _require(program_root.is_dir(), "program root must exist")
    out = Path(fresh_out).absolute()
    _require(not out.exists() and not out.is_symlink(), "continuation output must be fresh")
    started, emitted, errors = time.monotonic(), 0, []

    def emit(stage, status, **fields):
        nonlocal emitted
        if progress is None or emitted >= 2 * budget.max_parent_artifacts + 12 * call_budget.max_source_files + 64:
            return
        emitted += 1
        try:
            progress({"stage": stage, "status": status, "elapsed_s": time.monotonic() - started, **fields})
        except Exception as error:
            if len(errors) < 8:
                errors.append(type(error).__name__)

    emit("parent_report", "BEGIN")
    parent_dir, parent, parent_ref = _read_parent(
        parent_directory, expected_parent_report_sha256, program_root, budget)
    _require(not out.resolve().is_relative_to(parent_dir),
             "continuation output cannot be inside immutable parent directory")
    emit("parent_report", "END", raw_sha256=parent_ref["raw_sha256"])
    sink = _RawSink()
    emit("raw_scan", "BEGIN")
    scanned = scan_call_trace(trace_directory, program_root, call_budget, sink=sink)
    _require(not out.resolve().is_relative_to(scanned.directory),
             "continuation output cannot be inside immutable raw capture directory")
    captures, raw_audit = _verify_raw(parent, scanned, sink)
    emit("raw_scan", "END", **raw_audit)
    emit("parent_artifacts", "BEGIN")
    parent_files, provider_bytes, archive_audit = _verify_parent_artifacts(parent_dir, parent, budget, emit)
    emit("parent_artifacts", "END", **archive_audit)
    _require(len(parent_files) <= call_budget.max_source_files
             and sum(row["raw_bytes"] for row in parent_files.values()) <= call_budget.max_source_bytes,
             "parent demanded source cohort exceeds independent source budget")
    roots = {root["id"]: root for root in parent["source_roots"]}
    files, guards, inputs, guarded_source_bytes = {}, {}, {}, 0
    for filename, old in sorted(parent_files.items()):
        row = deepcopy(old)
        row["parent_context"] = row["context"]
        row["parent_frontiers"], row["frontiers"] = row["frontiers"], []
        row["archive_attempts"] = []
        row["cohort"] = ("REUSE_PARENT_GRAPHS" if row["source_graph_artifact"] is not None
                         else "MISSING_GRAPHS_ONLY" if row["snapshot_artifact"] is not None
                         else "MISSING_SNAPSHOT_AND_GRAPHS")
        for field in ("snapshot_artifact", "source_graph_artifact"):
            row[field] = _locator(row[field], row["source_root"], "PARENT", parent_ref)
        for provider in row["providers"]:
            if provider["kind"] == "INSTALLED_DISTRIBUTION":
                for field in ("metadata_artifact", "record_artifact"):
                    provider[field] = _locator(provider[field], row["source_root"], "PARENT", parent_ref)
        guard, raw, text = _guard(row, call_budget, call_budget.max_source_bytes - guarded_source_bytes)
        guarded_source_bytes += guard.get("current_raw_bytes", 0)
        guards[filename], files[filename] = guard, row
        if row["cohort"] != "REUSE_PARENT_GRAPHS" and guard["matches"]:
            inputs[filename] = raw, text
        emit("source_guard", "END", path=filename, matches=guard["matches"], cohort=row["cohort"])
    missing_sources = {filename for filename, row in files.items()
                       if row["cohort"] == "MISSING_SNAPSHOT_AND_GRAPHS"}
    provider_reuse_frontiers = []
    try:
        owners = _providers_from_retained_metadata(
            provider_bytes, parent["source_roots"], missing_sources, parent_ref)
    except (UnicodeError, ValueError, csv.Error) as error:
        owners = {}
        provider_reuse_frontiers.append(_gap("RETAINED_PROVIDER_PARSE_UNAVAILABLE",
                                              type(error).__name__ + ": " + str(error)))
    del provider_bytes
    rows, requests = deepcopy(parent["admissions"]), defaultdict(list)
    replaced_frontiers = {"SOURCE_ADMISSION_UNAVAILABLE", "SOURCE_GRAPH_ARCHIVE_BUDGET",
                          "SOURCE_GRAPHS_UNAVAILABLE"}
    for row in rows:
        row["parent_status"] = row["status"]
        row["parent_frontiers"] = deepcopy(row["frontiers"])
        row["source_compiler_witness_reused"] = row["code_source_link"] is not None
        row["source_compiler_matching_performed"] = False
        row["witness_origin"] = ("PARENT_SOURCE_COMPILER_WITNESS_NOT_RECOMPILED"
                                  if row["code_source_link"] is not None else None)
        capture = captures.get((row["process_id"], row["code"]))
        filename = capture.code.filename if capture else None
        row["current_source_guard_matches"] = guards[filename]["matches"] if filename in guards else None
        if filename not in files:
            continue
        file_row = files[filename]
        _require(row["source_root"] == file_row["source_root"],
                 "parent admission/source-file namespace mismatch")
        row["source_file"] = filename
        requests[filename].append(row)
        if file_row["cohort"] != "REUSE_PARENT_GRAPHS":
            row["frontiers"] = [gap for gap in row["frontiers"] if gap["code"] not in replaced_frontiers]
    out.mkdir(parents=True, exist_ok=False)
    (out / "sources").mkdir(); (out / "graphs").mkdir()
    archives = _DeltaArchives(out, budget, call_budget, parent_ref, files, roots, guards, emit)
    # The existing ledger is reused only for bounded compile reservations; its
    # old shared archive budget is deliberately not used in this continuation.
    compile_ledger = _Ledger(call_budget, DependencySourceBudget(max_compile_variants=budget.max_compile_variants))
    measurements, completed_files = {"initial_current_source_bytes_guarded": guarded_source_bytes}, []

    def document(stage, complete):
        statuses, weighted, frontiers = Counter(), Counter(), Counter()
        for row in rows:
            statuses[row["status"]] += 1
            weighted[row["status"]] += row["entered_invocations"]
            for code in {gap["code"] for gap in row["frontiers"]}:
                frontiers[code] += row["entered_invocations"]
        return {
            "schema": "scar.dependency-source-continuation", "schema_version": 1,
            "stage": stage, "continuation_attempt_complete": complete,
            "scope": "historical dependency source fragments; original program inventory untouched",
            "parent": parent_ref, "program_root": str(program_root), "trace_directory": scanned.directory,
            "trace_files": encode(scanned.files), "collection_metadata": list(scanned.metadata),
            "raw_scan_issues": encode(scanned.issues), "source_roots": parent["source_roots"],
            "compilation_profile": _PROFILE.value, "call_budget": encode(call_budget),
            "budget": encode(budget), "context_budget": encode(context_budget),
            "environment": {"python": sys.version, "executable": sys.executable,
                            "captured_executable_binary_identity_established": False},
            "raw_audit": raw_audit, "parent_artifact_audit": archive_audit,
            "source_guards": list(guards.values()), "source_files": list(files.values()),
            "admissions": rows, "completed_files": list(completed_files),
            "parent_file_errors": parent["file_errors"],
            "provider_frontiers": [*parent["provider_frontiers"], *provider_reuse_frontiers],
            "root_frontiers": parent["root_frontiers"],
            "summary": {"entered_code_groups": len(rows),
                        "entered_invocations": sum(row["entered_invocations"] for row in rows),
                        "statuses": dict(statuses), "weighted_statuses": dict(weighted),
                        "weighted_frontiers": dict(frontiers),
                        "source_files_with_snapshots": sum(row["snapshot_artifact"] is not None for row in files.values()),
                        "source_files_with_graphs": sum(row["source_graph_artifact"] is not None for row in files.values()),
                        "current_source_guard_matches": sum(row["matches"] for row in guards.values()),
                        "historical_compiler_witnesses_reused": sum(row["source_compiler_witness_reused"] for row in rows),
                        "new_compiler_matching_groups": sum(row["source_compiler_matching_performed"] for row in rows)},
            "measurements": {**measurements, **dict(archives.counts), **dict(compile_ledger.counts),
                             "progress_events_emitted": emitted, "progress_callback_errors": list(errors)},
            "conditions": ["parent compiler/source witnesses are inherited, not independently recompiled",
                           "current-source drift does not erase historical snapshot evidence",
                           "new graph construction is not body/effect or independent public replay proof",
                           "provider metadata is inherited ownership evidence, not package-at-capture proof",
                           "the new sidecar does not inline or authorize program inventory transformations"],
            **_AUTHORITY,
        }

    def checkpoint(stage):
        payload = _bounded_canonical(document(stage, False), budget.max_report_bytes)
        temporary = out / ".checkpoint.json.tmp"
        with temporary.open("xb") as stream:
            stream.write(payload)
        os.replace(temporary, out / "checkpoint.json")
        emit("checkpoint", "END", stage_name=stage, report_bytes=len(payload),
             completed_files=len(completed_files))

    # Every current guard and planned cohort is saved before the first new
    # snapshot/preparation. Graph storage never consumes this report capacity.
    checkpoint("GUARDS_RECORDED_NO_NEW_SOURCE_WORK")
    for filename in sorted(missing_sources):
        row = files[filename]
        if guards[filename]["matches"]:
            raw, text = inputs[filename]
            try:
                archives.source(row, raw, text)
                if {"purelib", "platlib"}.intersection(roots[row["source_root"]]["roles"]):
                    row["providers"] = owners.get(filename, [])
                    if len(row["providers"]) != 1:
                        code = "DISTRIBUTION_OWNERSHIP_AMBIGUOUS" if row["providers"] else "DISTRIBUTION_OWNERSHIP_UNRESOLVED"
                        row["frontiers"].append(_gap(code,
                            "parent retained metadata does not establish one unique provider"))
                else:
                    # The parent's version/root evidence is retained as such;
                    # do not invent a package-at-capture version from current FS.
                    templates = [old["providers"] for old in parent_files.values()
                                 if old["source_root"] == row["source_root"] and old["providers"]]
                    row["providers"] = deepcopy(templates[0]) if templates else []
                    if not row["providers"]:
                        row["frontiers"].append(_gap("RETAINED_PROVIDER_UNAVAILABLE",
                            "parent contains no provider witness for this namespace"))
            except _Limit as error:
                row["frontiers"].append(_gap("SOURCE_SNAPSHOT_ARCHIVE_BUDGET", str(error)))
        checkpoint("SOURCE_SNAPSHOT_ATTEMPTED:" + filename)
    workers = {}
    with PreparedContextStore(context_budget) as shared_store:
        for filename, file_row in files.items():
            if file_row["cohort"] == "REUSE_PARENT_GRAPHS":
                continue
            emit("source_file", "BEGIN", path=filename, cohort=file_row["cohort"])
            try:
                guard, _, _ = _guard(file_row, call_budget)
                guards[filename] = guard
                _require(guard["matches"], "current source differs from the parent historical source bytes")
                _require(file_row["snapshot_artifact"] is not None, "missing source snapshot was not stored")
                root = roots[file_row["source_root"]]
                if root["id"] not in workers:
                    workspace = _ContinuationWorkspace(root, context_budget, shared_store, archives, emit)
                    resolver = _Sources(Path(root["namespace_root"]), call_budget, inventory=None,
                        _source_workspace=workspace, compilation_profile=_PROFILE)
                    workers[root["id"]] = workspace, resolver
                workspace, resolver = workers[root["id"]]
                if file_row["cohort"] == "MISSING_GRAPHS_ONLY":
                    # Rebuild only seven missing artifacts in this capture.
                    # Original compiler witnesses are untouched and inherited.
                    workspace.prepare(Path(filename))
                else:
                    for row in requests[filename]:
                        if row["code_source_link"] is not None:
                            continue
                        captured = captures[row["process_id"], row["code"]].code
                        try:
                            future_flags_for(captured.flags, _PROFILE)
                        except UnsupportedCompilationFlags:
                            pass  # Existing resolver publishes its exact flags boundary.
                        else:
                            compile_ledger.reserve_compilation(root["id"], Path(filename),
                                file_row["fingerprint"], captured.flags, resolver.compiled)
                        row["source_compiler_matching_performed"] = True
                        link = resolver.code(captured)
                        if link.snapshot is not None:
                            if (link.snapshot.fingerprint != file_row["fingerprint"]
                                    or link.snapshot.path != filename):
                                row["rejected_code_source_link"] = encode(link)
                                row["status"] = "UNRESOLVED"
                                row["frontiers"].append(_gap("RETAINED_SOURCE_MISMATCH",
                                    "new compiler witness differs from retained source snapshot"))
                                continue
                        row["code_source_link"], row["status"] = encode(link), "SOURCE_" + link.status.value
                        row["witness_origin"] = "EXISTING_MATCHER_ON_MISSING_PARENT_SOURCE"
                        if link.status.value != "VERIFIED":
                            row["frontiers"].append(_gap("CODE_SOURCE_" + link.status.value,
                                                        "see original matcher CodeSourceLink issues"))
                        if link.definition is None:
                            row["frontiers"].append(_gap("DEFINITION_NOT_LINKED",
                                                        "code matching does not invent a definition/body"))
            except (OSError, ValueError, TypeError, KeyError, SyntaxError, RecursionError) as error:
                file_row["frontiers"].append(_gap("SOURCE_CONTINUATION_UNAVAILABLE",
                                                       type(error).__name__ + ": " + str(error)))
            completed_files.append(filename)
            measurements.update(source_prepare_attempts=sum(sum(workspace.preparations.values())
                                                             for workspace, _ in workers.values()),
                actual_compile_cache_entries=sum(len(resolver.compiled) for _, resolver in workers.values()),
                scratch_compressed_bytes_written=shared_store.compressed_bytes_written,
                scratch_uncompressed_bytes_written=shared_store.uncompressed_bytes_written)
            checkpoint("SOURCE_FILE_ATTEMPTED:" + filename)
            emit("source_file", "END", path=filename,
                 graph_stored=file_row["source_graph_artifact"] is not None)
    for filename, file_row in files.items():
        if not guards[filename]["matches"]:
            file_row["frontiers"].append(_gap(guards[filename]["status"],
                "historical snapshot evidence is retained; it is not current-source equality proof"))
        if file_row["snapshot_artifact"] is None:
            file_row["frontiers"].append(_gap("SOURCE_SNAPSHOT_UNAVAILABLE", "no snapshot artifact was retained"))
        if file_row["source_graph_artifact"] is None:
            file_row["frontiers"].append(_gap("SOURCE_GRAPHS_UNAVAILABLE", "missing graph artifact remains a frontier"))
        for row in requests[filename]:
            row["current_source_guard_matches"] = guards[filename]["matches"]
            row["frontiers"].extend(file_row["frontiers"])
    checkpoint("ALL_FILES_ATTEMPTED")
    report = document("ALL_FILES_ATTEMPTED", True)
    payload = _bounded_canonical(report, budget.max_report_bytes)
    with (out / "continuation.json").open("xb") as stream:
        stream.write(payload)
    emit("report", "END", raw_sha256=_sha(payload), report_bytes=len(payload),
         statuses=report["summary"]["statuses"])
    return report


__all__ = ["DependencyContinuationBudget", "continue_dependency_sources"]
