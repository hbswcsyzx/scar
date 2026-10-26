"""Read-only source attachments for the existing composition and binders.

No source is parsed, compiled, prepared or written here. Definitions and graph
views come exclusively from SHA-pinned original artifacts. Capture matching,
historical compiler witnesses and admission-time current guards stay separate.
"""
from __future__ import annotations

import base64
from collections import Counter, OrderedDict, defaultdict
from copy import deepcopy
import csv
from dataclasses import dataclass, replace
from email.parser import BytesParser
from email.policy import compat32
import gzip
import hashlib
from io import BytesIO, StringIO, TextIOWrapper
import json
import os
from pathlib import Path
import re
import sys
import tokenize

from scar.analysis.call_compilation import future_flags_for
from scar.analysis.call_trace_reader import CallTraceScan
from scar.analysis.source_layers import load_source_graph_artifact
from scar.ir.program.call_edges import CodeSourceLink, CapturedCode
from scar.ir.program.call_seeds import EnteredCodeGroup
from scar.ir.program.compilation import CallCompilationProfile
from scar.ir.program.inventory import SourceContextDigest
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.program.source_references import SourceArtifactLocator, SourceDefinitionReference
from scar.ir.record_codec import decode, encode, loads as strict_loads
from scar.ir.semantics_v2 import SourceSnapshot


_FALSE_AUTHORITY = (
    "target_executed_by_resolver", "transitive_dependency_closure_established",
    "canonical_bodies_established", "actual_formal_routing_established",
    "function_environment_established", "effects_established", "state_versions_established",
    "observer_origin_established", "provider_version_at_capture_established",
    "whole_program_graph_established", "first_stage_complete", "transformation_authorized",
)


@dataclass(frozen=True, slots=True)
class SourceAttachmentBudget:
    max_report_bytes: int = 64_000_000
    max_files: int = 256
    max_codes: int = 8192
    max_roots: int = 8
    max_artifact_bytes: int = 2_200_000_000
    max_record_bytes: int = 128_000_000
    cached_files: int = 2

    def __post_init__(self):
        for name in self.__dataclass_fields__:
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(name + " must be a positive exact integer")


def _need(value, detail):
    if not value:
        raise ValueError("source attachments: " + detail)


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _plain(path, expected_sha, schema, limit):
    path = Path(path)
    _need(path.is_absolute() and str(path.resolve(strict=True)) == str(path)
          and path.is_file() and not path.is_symlink(), "manifest must be an ordinary canonical path")
    before = path.stat()
    _need(before.st_size <= limit, "manifest byte budget exceeded")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    after = path.stat()
    _need((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
          == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
          and len(raw) == before.st_size and len(raw) <= limit
          and _sha(raw) == expected_sha, "manifest bytes changed or differ from pinned SHA")
    doc = strict_loads(raw.decode("utf-8", errors="strict"))
    _need(type(doc) is dict and doc.get("schema") == schema
          and type(doc.get("schema_version")) is int and doc["schema_version"] == 1
          and _canonical(doc) == raw, "manifest canonical schema/version mismatch")
    artifact = ProviderArtifact(str(path), expected_sha, len(raw), schema)
    return doc, SourceArtifactLocator(artifact, expected_sha, len(raw), "canonical-json")


def _pointer(document, pointer):
    _need(type(pointer) is str and (pointer == "#" or pointer.startswith("#/")), "invalid JSON pointer")
    value = document
    for encoded in pointer[2:].split("/") if pointer != "#" else ():
        _need(re.search(r"~(?![01])", encoded) is None, "invalid JSON pointer escape")
        part = encoded.replace("~1", "/").replace("~0", "~")
        if type(value) is list:
            _need(re.fullmatch(r"0|[1-9][0-9]*", part) is not None, "invalid JSON array index")
            value = value[int(part)]
        else:
            _need(type(value) is dict and part in value, "JSON pointer is absent from original artifact")
            value = value[part]
    return value


class ArchivedSourceUnavailable(LookupError):
    """An explicitly missing original snapshot, distinct from contradictory bytes."""


class SourceAttachments:
    """Bounded reader/resolver over one existing dependency continuation.

    Construction validates small manifests, source snapshots and provider
    evidence. Source graphs are decoded lazily, once for each file's code
    definitions. Public graph queries receive defensive copies of owned views.
    """

    def __init__(self, report_path, *, expected_report_sha256, project_root,
                 budget=SourceAttachmentBudget()):
        _need(type(budget) is SourceAttachmentBudget, "exact independent attachment budget required")
        budget.__post_init__()
        self.budget = budget
        self._report, self._report_locator = _plain(report_path, expected_report_sha256,
            "scar.dependency-source-continuation", budget.max_report_bytes)
        report = self._report
        _need(all(report.get(name) is False for name in _FALSE_AUTHORITY), "attachment overstates authority")
        _need(report.get("continuation_attempt_complete") is True, "continuation has no final completion receipt")
        _need(report["program_root"] == str(project_root), "original program root differs from composition")
        _need(report["compilation_profile"] == CallCompilationProfile.RECORDED_FUTURE_FLAGS.value,
              "unsupported historical compiler/source witness profile")
        self._directory = Path(self._report_locator.artifact.uri).parent
        parent_ref = report["parent"]
        _need(parent_ref["path"] == "admissions.json", "unsupported parent manifest locator")
        parent_dir = Path(parent_ref["directory"])
        self._parent, self._parent_locator = _plain(parent_dir / parent_ref["path"],
            parent_ref["raw_sha256"], "scar.dependency-source-admissions", budget.max_report_bytes)
        _need(self._parent_locator.artifact.size_bytes == parent_ref["raw_bytes"], "parent byte receipt mismatch")
        parent = self._parent
        _need(all(parent.get(name) is False for name in _FALSE_AUTHORITY)
              and parent["program_root"] == report["program_root"]
              and parent["compilation_profile"] == report["compilation_profile"]
              and parent["trace_files"] == report["trace_files"]
              and parent["collection_metadata"] == report["collection_metadata"]
              and parent["raw_scan_issues"] == report["raw_scan_issues"]
              and parent["source_roots"] == report["source_roots"], "parent/continuation scope differs")
        self._roots, self._root_indexes = {}, {}
        _need(len(report["source_roots"]) <= budget.max_roots, "source-root budget exceeded")
        for index, root in enumerate(report["source_roots"]):
            fields = {key: value for key, value in root.items() if key != "id"}
            _need(root["id"] == "dependency-source-root:" + _sha(_canonical(fields)), "root identity mismatch")
            path = Path(root["namespace_root"])
            _need(path.is_absolute() and os.path.normpath(str(path)) == str(path)
                  and path != Path(path.anchor) and root["id"] not in self._roots, "invalid/duplicate source namespace")
            self._roots[root["id"]], self._root_indexes[root["id"]] = root, index
        self._files = {row["path"]: row for row in report["source_files"]}
        self._file_indexes = {row["path"]: index for index, row in enumerate(report["source_files"])}
        old_files = {row["path"]: row for row in parent["source_files"]}
        _need(len(self._files) == len(report["source_files"]) <= budget.max_files
              and len(old_files) == len(parent["source_files"]) and set(old_files) == set(self._files),
              "source-file denominator differs or exceeds budget")
        self._guards = {row["path"]: row for row in report["source_guards"]}
        self._guard_indexes = {row["path"]: index for index, row in enumerate(report["source_guards"])}
        _need(len(self._guards) == len(report["source_guards"]) and set(self._guards) == set(self._files),
              "guard/source-file denominator mismatch")
        self._rows = {(row["process_id"], row["code"]): row for row in report["admissions"]}
        self._static_rows = defaultdict(list)
        for key, row in self._rows.items():
            self._static_rows[key[1]].append((key, row))
        self._row_indexes = {(row["process_id"], row["code"]): index
                             for index, row in enumerate(report["admissions"])}
        old_rows = {(row["process_id"], row["code"]): row for row in parent["admissions"]}
        _need(len(self._rows) == len(report["admissions"]) <= budget.max_codes
              and len(old_rows) == len(parent["admissions"]) and set(self._rows) == set(old_rows),
              "entered process/code denominator differs or exceeds budget")
        self._snapshots, self._links, self._requests = {}, {}, defaultdict(list)
        statuses, weights = Counter(), Counter()
        for key, row in self._rows.items():
            old = old_rows[key]
            for field in ("process_id", "code", "captured_code", "descriptor_anchor", "first_anchor",
                          "last_anchor", "entered_invocations"):
                _need(row[field] == old[field], "parent original captured descriptor/group differs")
            _need(type(row["entered_invocations"]) is int and row["entered_invocations"] >= 1,
                  "invalid entered invocation count")
            if old["code_source_link"] is not None:
                _need(row["code_source_link"] == old["code_source_link"]
                      and row["source_compiler_witness_reused"] is True
                      and row["source_compiler_matching_performed"] is False,
                      "historical compiler witness was changed or relabeled")
            elif row["code_source_link"] is not None:
                _need(row["source_compiler_witness_reused"] is False
                      and row["source_compiler_matching_performed"] is True,
                      "new source witness has no original matcher provenance")
            captured = decode(CapturedCode, row["captured_code"]) if row["captured_code"] is not None else None
            _need(captured is None or captured.key == row["code"], "captured complete code key mismatch")
            link = decode(CodeSourceLink, row["code_source_link"]) if row["code_source_link"] is not None else None
            if link is not None:
                _need(link.code == row["code"] and row["status"] == "SOURCE_" + link.status.value,
                      "code/source status or complete code identity mismatch")
                self._links[key] = link
                if link.status.value == "VERIFIED":
                    _need(captured is not None and link.snapshot is not None
                          and captured.filename == link.snapshot.path and row["source_file"] == captured.filename,
                          "verified code has no exact source snapshot/captured filename")
                    file = self._files[captured.filename]
                    _need(row["source_root"] == file["source_root"]
                          and link.snapshot.fingerprint == file["fingerprint"], "source witness changed namespace/version")
                    prior = self._snapshots.get(captured.filename)
                    _need(prior is None or prior == link.snapshot, "one file has conflicting source snapshot witnesses")
                    self._snapshots[captured.filename] = link.snapshot
                    self._requests[captured.filename].append(key)
            statuses[row["status"]] += 1; weights[row["status"]] += row["entered_invocations"]
        summary = report["summary"]
        _need(summary["entered_code_groups"] == len(self._rows)
              and summary["entered_invocations"] == sum(weights.values())
              and summary["statuses"] == dict(statuses) and summary["weighted_statuses"] == dict(weights),
              "attachment summary differs from retained groups")
        self._charged, self._unique_bytes = set(), 0
        self._auxiliary = {}
        self._views = OrderedDict()
        self._resolved = {}
        # Small original definition records only. The full graph LRU remains
        # bounded; exact qualified references cannot acquire new proof by ID.
        self._definitions = {}
        self._file_graph_locators = {}
        self._verified_capture = None
        self._measurements = Counter()
        for filename, row in self._files.items():
            old = old_files[filename]
            _need(all(row[field] == old[field] for field in ("path", "source_root", "raw_sha256", "raw_bytes", "fingerprint")),
                  "historical source bytes/namespace changed")
            root = self._roots[row["source_root"]]
            matching = [item for item in self._roots.values()
                        if Path(filename).is_relative_to(item["namespace_root"])]
            selected = max(matching, key=lambda item: len(Path(item["namespace_root"]).parts), default=None)
            _need(Path(filename).is_absolute() and os.path.normpath(filename) == filename
                  and not Path(filename).is_relative_to(project_root)
                  and selected is not None and selected["id"] == root["id"],
                  "source path is outside the declared namespace")
            if old["context"] is not None:
                _need(row["context"] == old["context"], "reconstructed graph did not retain original context")
            if row["context"] is not None:
                _need(decode(SourceContextDigest, row["context"]).namespace_root == root["namespace_root"],
                      "source context uses a different original namespace")
            for field in ("snapshot_artifact", "source_graph_artifact"):
                if old[field] is not None:
                    value = row[field]
                    _need(value is not None and value["origin"] == "PARENT" and value["artifact"] == old[field],
                          "an inherited original artifact was replaced")
            guard = self._guards[filename]
            _need(guard["source_root"] == row["source_root"]
                  and guard["expected_raw_sha256"] == row["raw_sha256"]
                  and guard["expected_raw_bytes"] == row["raw_bytes"]
                  and guard["expected_fingerprint"] == row["fingerprint"]
                  and type(guard["matches"]) is bool, "admission-time guard has a different expected source")
            if guard["matches"]:
                _need(guard["current_raw_sha256"] == row["raw_sha256"]
                      and guard["current_raw_bytes"] == row["raw_bytes"]
                      and guard["current_fingerprint"] == row["fingerprint"], "guard success contradicts its observed bytes")
            snapshot_ref = row["snapshot_artifact"]
            if snapshot_ref is not None:
                doc, _ = self._aux(snapshot_ref, row["source_root"], "sources")
                raw = base64.b64decode(doc["raw_base64"], validate=True)
                encoding, _ = tokenize.detect_encoding(BytesIO(raw).readline)
                with TextIOWrapper(BytesIO(raw), encoding=encoding, newline=None) as stream:
                    text = stream.read()
                _need(doc["original_uri"] == filename and doc["source_root"] == row["source_root"]
                      and doc["namespace_root"] == root["namespace_root"]
                      and _sha(raw) == row["raw_sha256"] == doc["raw_sha256"]
                      and len(raw) == row["raw_bytes"] == doc["raw_bytes"]
                      and text == doc["decoded_text"]
                      and "sha256:" + _sha(text.encode()) == row["fingerprint"] == doc["fingerprint"]
                      and doc["code_source_match_established"] is False,
                      "retained source snapshot differs from its original bytes/version")
                if filename in self._snapshots:
                    _need(self._snapshots[filename].python_version == doc["python_version"],
                          "snapshot Python version differs from the original compiler witness")
            graph_ref = row["source_graph_artifact"]
            if graph_ref is not None:
                self._artifact_path(graph_ref, row["source_root"], "graphs")
        self._validate_providers()

    @classmethod
    def from_admissions(cls, report_path, *, expected_report_sha256, project_root,
                        budget=SourceAttachmentBudget()):
        """Read the original admission directly, without inventing continuation.

        No raw scan/current guard is restored. Definition membership is checked
        lazily against the original graph before a qualified reference is issued.
        """
        _need(cls is SourceAttachments and type(budget) is SourceAttachmentBudget,
              "exact admission reader and independent budget required")
        budget.__post_init__()
        self = object.__new__(cls)
        self.budget, self._admission_mode = budget, True
        self._report, self._report_locator = _plain(report_path, expected_report_sha256,
            "scar.dependency-source-admissions", budget.max_report_bytes)
        report = self._report
        _need(all(report.get(name) is False for name in _FALSE_AUTHORITY), "admission overstates authority")
        _need(report["program_root"] == str(project_root)
              and report["compilation_profile"] == CallCompilationProfile.RECORDED_FUTURE_FLAGS.value,
              "original admission project/compiler scope differs")
        self._directory = Path(self._report_locator.artifact.uri).parent
        self._parent = self._parent_locator = None
        self._guards, self._guard_indexes = {}, {}
        self._roots, self._root_indexes = {}, {}
        _need(len(report["source_roots"]) <= budget.max_roots, "admission root budget exceeded")
        for index, root in enumerate(report["source_roots"]):
            fields = {key: value for key, value in root.items() if key != "id"}
            path = Path(root["namespace_root"])
            _need(root["id"] == "dependency-source-root:" + _sha(_canonical(fields))
                  and path.is_absolute() and str(path) == os.path.normpath(str(path))
                  and path != Path(path.anchor) and root["id"] not in self._roots,
                  "invalid original admission namespace")
            self._roots[root["id"]], self._root_indexes[root["id"]] = root, index
        self._files = {row["path"]: row for row in report["source_files"]}
        self._file_indexes = {row["path"]: index for index, row in enumerate(report["source_files"])}
        _need(len(self._files) == len(report["source_files"]) <= budget.max_files,
              "duplicate admission source or file budget exceeded")
        self._rows = {(row["process_id"], row["code"]): row for row in report["admissions"]}
        _need(len(self._rows) == len(report["admissions"]) <= budget.max_codes,
              "duplicate admission group or code budget exceeded")
        self._row_indexes = {key: index for index, key in enumerate(self._rows)}
        self._static_rows, self._requests = defaultdict(list), defaultdict(list)
        self._snapshots, self._links = {}, {}
        statuses, weights = Counter(), Counter()
        for key, row in self._rows.items():
            _need(type(key[0]) is int and key[0] > 0
                  and type(row["entered_invocations"]) is int and row["entered_invocations"] > 0,
                  "invalid original admission group")
            captured = decode(CapturedCode, row["captured_code"]) if row["captured_code"] is not None else None
            _need(captured is None or captured.key == key[1], "captured descriptor/key differs")
            self._static_rows[key[1]].append((key, row))
            link = decode(CodeSourceLink, row["code_source_link"]) if row["code_source_link"] is not None else None
            if link is not None:
                _need(link.code == key[1] and row["status"] == "SOURCE_" + link.status.value,
                      "admission source status/key differs")
                self._links[key] = link
                if link.status.value == "VERIFIED":
                    _need(captured is not None and link.snapshot is not None
                          and captured.filename == link.snapshot.path == row["source_file"]
                          and captured.filename in self._files, "verified admission has no exact source")
                    file = self._files[captured.filename]
                    _need(row["source_root"] == file["source_root"]
                          and link.snapshot.fingerprint == file["fingerprint"], "admission source namespace/version differs")
                    prior = self._snapshots.get(captured.filename)
                    _need(prior is None or prior == link.snapshot, "conflicting original source snapshot")
                    self._snapshots[captured.filename] = link.snapshot
                    self._requests[captured.filename].append(key)
            statuses[row["status"]] += 1
            weights[row["status"]] += row["entered_invocations"]
        summary = report["summary"]
        _need(summary["entered_code_groups"] == len(self._rows)
              and summary["entered_invocations"] == sum(weights.values())
              and summary["statuses"] == dict(statuses) and summary["weighted_statuses"] == dict(weights),
              "admission denominator/status accounting differs")
        self._charged, self._unique_bytes, self._auxiliary = set(), 0, {}
        self._views, self._resolved, self._definitions = OrderedDict(), {}, {}
        self._file_graph_locators, self._verified_capture = {}, None
        self._measurements = Counter()
        for filename, row in self._files.items():
            root = self._roots[row["source_root"]]
            matching = [item for item in self._roots.values() if Path(filename).is_relative_to(item["namespace_root"])]
            selected = max(matching, key=lambda item: len(Path(item["namespace_root"]).parts), default=None)
            _need(Path(filename).is_absolute() and os.path.normpath(filename) == filename
                  and not Path(filename).is_relative_to(project_root)
                  and selected is not None and selected["id"] == root["id"], "admission file namespace differs")
            if row["context"] is not None:
                _need(decode(SourceContextDigest, row["context"]).namespace_root == root["namespace_root"],
                      "admission context namespace differs")
            if row["snapshot_artifact"] is not None:
                doc, _locator = self._aux(row["snapshot_artifact"], row["source_root"], "sources")
                raw = base64.b64decode(doc["raw_base64"], validate=True)
                encoding, _ = tokenize.detect_encoding(BytesIO(raw).readline)
                with TextIOWrapper(BytesIO(raw), encoding=encoding, newline=None) as stream:
                    text = stream.read()
                _need(doc["original_uri"] == filename and doc["source_root"] == row["source_root"]
                      and doc["namespace_root"] == root["namespace_root"]
                      and _sha(raw) == row["raw_sha256"] == doc["raw_sha256"]
                      and len(raw) == row["raw_bytes"] == doc["raw_bytes"]
                      and text == doc["decoded_text"]
                      and "sha256:" + _sha(text.encode()) == row["fingerprint"] == doc["fingerprint"]
                      and doc["code_source_match_established"] is False, "original source snapshot differs")
                if filename in self._snapshots:
                    _need(self._snapshots[filename].python_version == doc["python_version"],
                          "admission snapshot Python version differs")
            if row["source_graph_artifact"] is not None:
                self._artifact_path(row["source_graph_artifact"], row["source_root"], "graphs")
        self._validate_providers()
        return self

    def catalog_rows(self):
        """Original complete groups; does not resolve graphs or claim a Run."""
        return tuple(deepcopy(row) for row in self._rows.values())

    def archived_source(self, snapshot):
        """Read a verified link's original snapshot without graph or live-source access.

        This proves original text/locator identity only. It does not resolve a
        semantic definition, refresh a guard, or create a current capture fact.
        """
        _need(type(snapshot) is SourceSnapshot, "exact original source snapshot required")
        self.require_unchanged()
        filename = snapshot.path
        _need(self._snapshots.get(filename) == snapshot and filename in self._files,
              "snapshot is not the original verified compiler/source input")
        row = self._files[filename]
        if row["snapshot_artifact"] is None:
            raise ArchivedSourceUnavailable("ARCHIVED_SOURCE_SNAPSHOT_UNAVAILABLE")
        root = self._roots[row["source_root"]]
        doc, locator = self._aux(row["snapshot_artifact"], row["source_root"], "sources")
        raw = base64.b64decode(doc["raw_base64"], validate=True)
        encoding, _ = tokenize.detect_encoding(BytesIO(raw).readline)
        with TextIOWrapper(BytesIO(raw), encoding=encoding, newline=None) as stream:
            text = stream.read()
        _need(doc["original_uri"] == filename and doc["source_root"] == row["source_root"]
              and doc["namespace_root"] == root["namespace_root"]
              and len(raw) == row["raw_bytes"] == doc["raw_bytes"]
              and _sha(raw) == row["raw_sha256"] == doc["raw_sha256"]
              and text == doc["decoded_text"]
              and snapshot.fingerprint == row["fingerprint"] == doc["fingerprint"]
                  == "sha256:" + _sha(text.encode("utf-8"))
              and snapshot.python_version == doc["python_version"]
              and doc["code_source_match_established"] is False,
              "original archived source bytes/namespace/snapshot contradict its witness")
        self.require_unchanged()
        return {"snapshot": snapshot, "text": text, "locator": locator,
                "declaration": self._declaration(filename, "snapshot_artifact"),
                "encoding": encoding, "raw_sha256": _sha(raw), "raw_bytes": len(raw),
                "source_root": row["source_root"], "namespace_root": root["namespace_root"],
                "owner": self.receipts()}

    def require_unchanged(self):
        schema = "scar.dependency-source-admissions" if getattr(self, "_admission_mode", False) else "scar.dependency-source-continuation"
        document, locator = _plain(self._report_locator.artifact.uri, self._report_locator.artifact.sha256,
                                  schema, self.budget.max_report_bytes)
        _need(locator == self._report_locator and _canonical(document) == _canonical(self._report),
              "bound original source manifest changed")

    def receipts(self):
        """Explicit attachments input; never changes CompositionIndex.document."""
        if getattr(self, "_admission_mode", False):
            return {"report": encode(self._report_locator), "parent": None,
                    "format": "scar.source-admissions-input.v1",
                    "source_root_count": len(self._roots), "source_file_count": len(self._files)}
        return {"report": encode(self._report_locator), "parent": encode(self._parent_locator),
                "format": "scar.source-attachments-input.v1",
                "source_root_count": len(self._roots), "source_file_count": len(self._files)}

    def _manifest_locator(self, pointer):
        _pointer(self._report, pointer)
        return replace(self._report_locator, pointer=pointer)

    def _declaration(self, filename, field):
        return ProviderFactReference(self._report_locator.artifact,
            f"#/source_files/{self._file_indexes[filename]}/{field}")

    def _artifact_path(self, locator, source_root, family):
        _need(type(locator) is dict, "artifact locator must be an object")
        if getattr(self, "_admission_mode", False):
            _need(source_root in self._roots, "admission artifact namespace is unknown")
            base, artifact = self._directory, locator
        elif locator["origin"] == "PARENT":
            _need(locator["source_root"] == source_root, "artifact namespace mismatch")
            base = Path(self._parent_locator.artifact.uri).parent
            _need(locator["parent_directory"] == str(base)
                  and locator["parent_report_raw_sha256"] == self._parent_locator.artifact.sha256,
                  "artifact does not name the pinned original parent")
            artifact = locator["artifact"]
        else:
            _need(locator["source_root"] == source_root and locator["origin"] == "CONTINUATION",
                  "unsupported source artifact origin/namespace")
            base = self._directory
            artifact = locator["artifact"]
        _need(set(artifact) == {"schema", "schema_version", "path", "canonical_sha256", "canonical_bytes", "compressed_bytes"}
              and type(artifact["schema_version"]) is int and artifact["schema_version"] == 1
              and type(artifact["canonical_sha256"]) is str
              and re.fullmatch(r"[0-9a-f]{64}", artifact["canonical_sha256"])
              and artifact["path"] == family + "/" + artifact["canonical_sha256"] + ".json.gz",
              "artifact is not its original supported canonical locator")
        for key in ("canonical_bytes", "compressed_bytes"):
            _need(type(artifact[key]) is int and 0 < artifact[key] <= self.budget.max_record_bytes,
                  "artifact record byte budget exceeded")
        path = base / artifact["path"]
        _need(path.is_file() and not path.is_symlink() and path.resolve() == path,
              "artifact is not an ordinary file beneath its manifest directory")
        return path, artifact

    def _charge(self, path, artifact):
        key = str(path), artifact["canonical_sha256"]
        if key not in self._charged:
            _need(artifact["canonical_bytes"] <= self.budget.max_artifact_bytes - self._unique_bytes,
                  "unique attachment artifact byte budget exceeded")
            self._charged.add(key)
            self._unique_bytes += artifact["canonical_bytes"]

    def _aux(self, locator, source_root, family):
        path, artifact = self._artifact_path(locator, source_root, family)
        key = str(path), artifact["canonical_sha256"]
        if key in self._auxiliary:
            return self._auxiliary[key]
        self._charge(path, artifact)
        before = path.stat()
        _need(before.st_size == artifact["compressed_bytes"], "auxiliary compressed-byte receipt mismatch")
        with path.open("rb") as stream:
            raw = stream.read(self.budget.max_record_bytes + 1)
        _need(len(raw) <= self.budget.max_record_bytes, "auxiliary physical byte budget exceeded")
        with gzip.GzipFile(fileobj=BytesIO(raw), mode="rb") as stream:
            payload = stream.read(self.budget.max_record_bytes + 1)
        _need(len(payload) <= self.budget.max_record_bytes, "auxiliary decoded byte budget exceeded")
        after = path.stat()
        _need((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
              == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
              and len(raw) == artifact["compressed_bytes"]
              and len(payload) == artifact["canonical_bytes"] and _sha(payload) == artifact["canonical_sha256"],
              "auxiliary source artifact bytes differ from its declaration")
        doc = strict_loads(payload.decode("utf-8"))
        _need(_canonical(doc) == payload and doc.get("schema") == artifact["schema"]
              and type(doc.get("schema_version")) is int and doc["schema_version"] == 1,
              "auxiliary artifact canonical schema mismatch")
        expected = "scar.dependency-source-snapshot" if family == "sources" else "scar.dependency-provider-artifact"
        _need(doc["schema"] == expected, "auxiliary artifact has an unsupported role/schema")
        physical = ProviderArtifact(str(path), _sha(raw), len(raw), doc["schema"])
        result = doc, SourceArtifactLocator(physical, artifact["canonical_sha256"], len(payload), "gzip-canonical-json")
        self._auxiliary[key] = result
        self._measurements["auxiliary_artifacts_read"] += 1
        self._measurements["physical_artifact_bytes_read"] += len(raw)
        return result

    def _validate_providers(self):
        pairs = {}
        for filename, row in self._files.items():
            root = self._roots[row["source_root"]]
            for provider in row["providers"]:
                if provider["kind"] != "INSTALLED_DISTRIBUTION":
                    continue  # Original stdlib/tool evidence stays in the manifest record.
                metadata, _ = self._aux(provider["metadata_artifact"], row["source_root"], "providers")
                record, _ = self._aux(provider["record_artifact"], row["source_root"], "providers")
                metadata_path, record_path = Path(metadata["original_uri"]), Path(record["original_uri"])
                _need(metadata_path.is_absolute() and metadata_path.is_relative_to(root["namespace_root"])
                      and metadata_path.name == "METADATA" and metadata_path.parent.name.endswith(".dist-info")
                      and record_path == metadata_path.parent / "RECORD"
                      and provider["record_is_ownership_evidence_not_source_or_code_proof"] is True,
                      "provider metadata/RECORD origin differs from its namespace")
                key = metadata["raw_sha256"], record["raw_sha256"], row["source_root"]
                if key not in pairs:
                    decoded = []
                    for doc in (metadata, record):
                        raw = base64.b64decode(doc["raw_base64"], validate=True)
                        _need(_sha(raw) == doc["raw_sha256"] and len(raw) == doc["raw_bytes"],
                              "provider raw bytes differ from retained metadata")
                        decoded.append(raw)
                    message = BytesParser(policy=compat32).parsebytes(decoded[0], headersonly=True)
                    _need(len(message.get_all("Name", [])) == len(message.get_all("Version", [])) == 1,
                          "provider metadata has ambiguous distribution identity")
                    base = Path(root["namespace_root"])
                    owned = set()
                    for item in csv.reader(StringIO(decoded[1].decode("utf-8"))):
                        if item and item[0] and not Path(item[0]).is_absolute():
                            candidate = Path(os.path.normpath(str(base / item[0])))
                            if candidate.is_relative_to(base) and str(candidate) in self._files:
                                owned.add(str(candidate))
                    pairs[key] = message.get("Name"), message.get("Version"), owned
                name, version, owned = pairs[key]
                _need(name == provider["name"] and version == provider["version"] and filename in owned,
                      "provider/version/RECORD ownership differs from retained facts")

    def verify_capture(self, scanned, groups):
        """Match a complete existing raw scan; no compiler or second raw scan."""
        self._verified_capture = None
        _need(type(scanned) is CallTraceScan, "capture verifier requires the strict reader's scan")
        _need(encode(scanned.files) == self._report["trace_files"]
              and list(scanned.metadata) == self._report["collection_metadata"]
              and encode(scanned.issues) == self._report["raw_scan_issues"],
              "capture raw SHA/counts/metadata differ from the historical source witness")
        captures = {(item.process_id, item.code.key): item for item in scanned.captures}
        values = tuple(groups)
        _need(all(type(group) is EnteredCodeGroup for group in values), "typed entered-code groups required")
        grouped = {(group.process_id, group.code): group for group in values}
        _need(len(grouped) == len(values) and set(grouped) == set(self._rows), "entered-code denominator differs")
        for key, group in grouped.items():
            row, captured = self._rows[key], captures.get(key)
            _need(group.count == row["entered_invocations"] and encode(group.first_anchor) == row["first_anchor"]
                  and encode(group.last_anchor) == row["last_anchor"]
                  and (encode(captured.code) if captured else None) == row["captured_code"]
                  and (encode(captured.anchor) if captured else None) == row["descriptor_anchor"],
                  "complete code descriptor/raw anchors/count differ from the attachment")
        self._verified_capture = {"trace_directory": scanned.directory,
            "trace_files_sha256": _sha(_canonical(encode(scanned.files))),
            "captured_codes": len(scanned.captures), "entered_code_groups": len(grouped),
            "entered_invocations": sum(group.count for group in values)}
        return deepcopy(self._verified_capture)

    def code_witness(self, process_id, code):
        """Original full evidence, explicitly historical; not a runtime producer."""
        key = process_id, code
        row = self._rows.get(key)
        if row is None:
            return None
        index = self._row_indexes[key]
        filename = row["source_file"]
        return {"record": deepcopy(row), "witness_scope": "HISTORICAL_CAPTURE_SOURCE_EVIDENCE",
                "record_locator": self._manifest_locator(f"#/admissions/{index}"),
                "descriptor_locator": self._manifest_locator(f"#/admissions/{index}/captured_code"),
                "code_source_locator": self._manifest_locator(f"#/admissions/{index}/code_source_link"),
                "capture_verified": self._verified_capture is not None,
                "guard_scope": "RECORDED_AT_ATTACHMENT_ADMISSION_NOT_REFRESHED",
                "guard": deepcopy(self._guards.get(filename)),
                "guard_locator": self._manifest_locator(f"#/source_guards/{self._guard_indexes[filename]}")
                                 if filename in self._guard_indexes else None}

    def current_scope_receipt(self, scanned, groups):
        """Receipt of a new strict scan, never equality with historical groups."""
        _need(type(scanned) is CallTraceScan, "strict current scan required")
        values = tuple(groups)
        _need(all(type(group) is EnteredCodeGroup for group in values)
              and len({(group.process_id, group.code) for group in values}) == len(values),
              "current entered-code groups are invalid or duplicate")
        return {"scope": "CURRENT_INDEPENDENT_SCAN_FOR_STATIC_REUSE",
            "trace_directory": scanned.directory,
            "trace_files_sha256": _sha(_canonical(encode(scanned.files))),
            "captured_codes": len(scanned.captures), "entered_code_groups": len(values),
            "entered_invocations": sum(group.count for group in values)}

    def static_code_witness(self, captured, *, compilation_profile, captured_python_build):
        """Select only complete code/source evidence, without old dynamic facts.

        The historical record locator is provenance. Its PID/counts/anchors
        are deliberately absent from the returned static view. No source read,
        compile or new capture binding occurs in this selector.
        """
        _need(type(captured) is CapturedCode, "complete typed captured code required")
        matched = [(key, row) for key, row in self._static_rows.get(captured.key, ())
                   if row["captured_code"] == encode(captured)]
        if not matched:
            return None
        key, row = matched[0]
        _need(all(item["code_source_link"] == row["code_source_link"] and item["status"] == row["status"]
                  for _, item in matched[1:]), "ambiguous historical static code/source proof")
        historical_builds = sorted({meta["python"] for meta in self._report["collection_metadata"]})
        frontiers = []
        if compilation_profile != self._report["compilation_profile"]:
            frontiers.append("STATIC_WITNESS_COMPILATION_PROFILE_MISMATCH")
        if (type(captured_python_build) is not str or historical_builds != [captured_python_build]
                or captured_python_build != sys.version):
            frontiers.append("STATIC_WITNESS_PYTHON_BUILD_MISMATCH")
        future_flags = None
        try:
            future_flags = future_flags_for(captured.flags, CallCompilationProfile.RECORDED_FUTURE_FLAGS)
        except (ValueError, TypeError):
            frontiers.append("STATIC_WITNESS_UNSUPPORTED_COMPILATION_FLAGS")
        index = self._row_indexes[key]
        result = {"captured_code": deepcopy(row["captured_code"]), "status": row["status"],
            "code_source_link": deepcopy(row["code_source_link"]),
            "record_locator": encode(self._manifest_locator(f"#/admissions/{index}")),
            "descriptor_locator": encode(self._manifest_locator(f"#/admissions/{index}/captured_code")),
            "code_source_locator": encode(self._manifest_locator(f"#/admissions/{index}/code_source_link")),
            "witness_scope": "HISTORICAL_CODE_SOURCE_ONLY",
            "context_guard": {"compilation_profile": compilation_profile,
                "historical_compilation_profile": self._report["compilation_profile"],
                "captured_python_build": captured_python_build, "historical_python_builds": historical_builds,
                "reader_python_build": sys.version, "future_flags": future_flags,
                "status": "MATCH" if not frontiers else "UNRESOLVED", "frontiers": frontiers},
            "historical_frontiers": deepcopy(row["frontiers"])}
        return result

    def static_definition_reference(self, witness):
        """Resolve the selected original record; no new PID masquerades as old."""
        _need(type(witness) is dict, "static source witness required")
        captured = decode(CapturedCode, witness["captured_code"])
        for key, row in self._static_rows.get(captured.key, ()):
            if row["captured_code"] == witness["captured_code"]:
                locator = encode(self._manifest_locator(f"#/admissions/{self._row_indexes[key]}"))
                if locator == witness["record_locator"] and row["code_source_link"] == witness["code_source_link"]:
                    return self.definition_reference(*key)
        raise ValueError("static witness is not one bound original full descriptor/source record")

    def _view(self, filename):
        if filename not in self._views:
            row = self._files[filename]
            _need(row["source_graph_artifact"] is not None and filename in self._snapshots,
                  "source graph or verified snapshot remains unavailable")
            path, artifact = self._artifact_path(row["source_graph_artifact"], row["source_root"], "graphs")
            self._charge(path, artifact)
            view, locator = load_source_graph_artifact(path, schema=artifact["schema"],
                canonical_sha256=artifact["canonical_sha256"], canonical_bytes=artifact["canonical_bytes"],
                compressed_bytes=artifact["compressed_bytes"], source_root=row["source_root"],
                snapshot=self._snapshots[filename], context=decode(SourceContextDigest, row["context"]),
                snapshot_locator=row["snapshot_artifact"],
                declaration=self._declaration(filename, "source_graph_artifact"),
                max_record_bytes=self.budget.max_record_bytes)
            self._views[filename] = view
            self._file_graph_locators[filename] = locator
            self._measurements["graph_artifacts_read"] += 1
            self._measurements["physical_artifact_bytes_read"] += artifact["compressed_bytes"]
            while len(self._views) > self.budget.cached_files:
                self._views.popitem(last=False)
        self._views.move_to_end(filename)
        return self._views[filename]

    def definition_reference(self, process_id, code):
        """Resolve all requested definitions in the same file on its first read."""
        key = process_id, code
        if key in self._resolved:
            return self._resolved[key]
        link = self._links.get(key)
        if link is None or link.status.value != "VERIFIED" or link.definition is None or link.source is None:
            self._resolved[key] = None
            return None
        filename = link.snapshot.path
        view = self._view(filename)
        definition_indexes = {definition.id: index for index, definition in enumerate(view.semantic.definitions.values())}
        row = self._files[filename]
        root = self._manifest_locator(f"#/source_roots/{self._root_indexes[row['source_root']]}")
        providers = tuple(self._manifest_locator(f"#/source_files/{self._file_indexes[filename]}/providers/{index}")
                          for index in range(len(row["providers"])))
        for requested in self._requests[filename]:
            witness = self._links[requested]
            if witness.definition is None or witness.source is None:
                self._resolved[requested] = None
                continue
            _need(witness.snapshot == view.snapshot and witness.definition in view.semantic.definitions,
                  "original code witness definition is absent from its source graph")
            definition = view.semantic.definitions[witness.definition]
            atom = view.semantic.source_atoms.get(witness.source.atom_id)
            _need(witness.source.atom_id in definition.source_atoms and atom is not None
                  and atom.reference == witness.source, "original definition/source atom correspondence differs")
            graph = replace(self._file_graph_locators[filename],
                            pointer=f"#/semantic/definitions/{definition_indexes[witness.definition]}")
            reference = SourceDefinitionReference(root, providers, graph, view.snapshot,
                view.context, witness.definition, witness.source)
            self._resolved[requested] = reference
            self._definitions[_canonical(encode(reference))] = deepcopy(definition)
        return self._resolved.get(key)

    def resolve_all_definitions(self):
        for filename in sorted(self._requests):
            for key in self._requests[filename]:
                self.definition_reference(*key)
        return {key: value for key, value in self._resolved.items() if value is not None}

    def _verify_reference(self, reference):
        _need(type(reference) is SourceDefinitionReference, "exact formal source definition reference required")
        reference.__post_init__()
        filename = reference.snapshot.path
        _need(filename in self._files, "definition source is not an admitted attachment")
        view = self._view(filename)
        row = self._files[filename]
        root = self._manifest_locator(f"#/source_roots/{self._root_indexes[row['source_root']]}")
        providers = tuple(self._manifest_locator(f"#/source_files/{self._file_indexes[filename]}/providers/{index}")
                          for index in range(len(row["providers"])))
        definition = view.semantic.definitions.get(reference.definition)
        atom = view.semantic.source_atoms.get(reference.source.atom_id)
        indexes = {item.id: index for index, item in enumerate(view.semantic.definitions.values())}
        _need(definition is not None and atom is not None and atom.reference == reference.source
              and reference.source.atom_id in definition.source_atoms
              and reference.snapshot == view.snapshot and reference.context == view.context
              and reference.root == root and reference.providers == providers
              and reference.graph == replace(self._file_graph_locators[filename],
                    pointer=f"#/semantic/definitions/{indexes[reference.definition]}"),
              "definition/root/provider/artifact locator differs from the bound original graph")
        return view

    @property
    def project_root(self):
        return self._report["program_root"]

    def capture_declaration(self):
        """Historical raw identity; not an independently performed replay."""
        return {key: deepcopy(self._report[key]) for key in
                ("trace_files", "collection_metadata", "raw_scan_issues")}

    def resolve_definition(self, reference):
        _need(type(reference) is SourceDefinitionReference, "exact formal source definition reference required")
        reference.__post_init__()
        key = _canonical(encode(reference))
        if key in self._definitions:
            return deepcopy(self._definitions[key])
        view = self._verify_reference(reference)
        definition = view.semantic.definitions[reference.definition]
        self._definitions[key] = deepcopy(definition)
        return deepcopy(definition)

    def owns_reference(self, reference):
        """Select an owner by its pinned root artifact, never by path alone."""
        return (type(reference) is SourceDefinitionReference
                and reference.root.artifact == self._report_locator.artifact
                and reference.root.decoded_sha256 == self._report_locator.decoded_sha256
                and reference.root.pointer.startswith("#/source_roots/"))

    def source_view(self, reference):
        return deepcopy(self._verify_reference(reference))

    def measurements(self):
        return {**dict(self._measurements), "unique_artifact_canonical_bytes": self._unique_bytes,
                "resolved_code_definitions": sum(value is not None for value in self._resolved.values()),
                "cached_original_definition_records": len(self._definitions),
                "cached_source_files": len(self._views), "source_reprepared": False, "source_recompiled": False}


__all__ = ["SourceAttachmentBudget", "SourceAttachments", "ArchivedSourceUnavailable"]
