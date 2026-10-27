"""Observed dependency source admission, separate from the program inventory.

The collector's original root is used for one strict raw scan. Current source
matching is delegated to the existing resolver under independent environment
namespaces. No application package is imported, no target code is executed and
no import closure, canonical program root or body transformation is invented.
"""
from __future__ import annotations

import base64
from collections import Counter, defaultdict
import csv
from dataclasses import dataclass
from email.parser import BytesParser
from email.policy import compat32
import hashlib
from io import BytesIO, StringIO, TextIOWrapper
import json
import os
from pathlib import Path
import sys
import sysconfig
import time
import tokenize

import scar
from scar.analysis.call_compilation import (
    UnsupportedCompilationFlags, compile_cache_key, future_flags_for,
)
from scar.analysis.call_demand import _SourceWorkspace
from scar.analysis.call_edges import _Sources
from scar.analysis.call_seeds import _EnteredCodeSink
from scar.analysis.call_trace_reader import scan_call_trace
from scar.analysis.program_context_store import PreparedContextStore
from scar.analysis.source_layers import _write_gzip_exclusive
from scar.ir.program.call_edges import CallEdgeBudget
from scar.ir.program.compilation import CallCompilationProfile
from scar.ir.program.expansion import ContextStoreBudget
from scar.ir.program.inventory import SourceContextDigest
from scar.ir.record_codec import encode


_PROFILE = CallCompilationProfile.RECORDED_FUTURE_FLAGS
_AUTHORITY = {
    "target_executed_by_resolver": False,
    "transitive_dependency_closure_established": False,
    "canonical_bodies_established": False,
    "actual_formal_routing_established": False,
    "function_environment_established": False,
    "effects_established": False,
    "state_versions_established": False,
    "observer_origin_established": False,
    "provider_version_at_capture_established": False,
    "whole_program_graph_established": False,
    "first_stage_complete": False,
    "transformation_authorized": False,
}


@dataclass(frozen=True, slots=True)
class DependencySourceBudget:
    """Global sidecar limits; source/raw limits additionally use CallEdgeBudget."""

    max_roots: int = 8
    max_metadata_entries: int = 4096
    max_metadata_files: int = 2048
    max_metadata_bytes: int = 32_000_000
    max_metadata_record_bytes: int = 4_000_000
    max_archive_record_bytes: int = 64_000_000
    max_archive_bytes: int = 512_000_000
    max_report_bytes: int = 32_000_000
    max_compile_variants: int = 768

    def __post_init__(self):
        for name in self.__dataclass_fields__:
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(name + " must be a positive exact integer")


class _Limit(ValueError):
    pass


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _bounded_canonical(value, limit):
    payload = bytearray()
    encoder = json.JSONEncoder(sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                               allow_nan=False)
    for chunk in encoder.iterencode(value):
        part = chunk.encode("utf-8")
        if len(part) > limit - len(payload):
            raise _Limit("canonical archive/report byte budget exceeded")
        payload.extend(part)
    return bytes(payload)


def _sha(payload):
    return hashlib.sha256(payload).hexdigest()


def _gap(code, detail):
    return {"code": code, "detail": detail}


def _read_file(path, limit):
    before = path.stat()
    if before.st_size > limit:
        raise _Limit("input file byte budget exceeded")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    after = path.stat()
    if len(raw) > limit:
        raise _Limit("input file byte budget exceeded")
    if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            or len(raw) != before.st_size):
        raise ValueError("input file changed while reading")
    return raw


def _decode_source(raw):
    encoding, _ = tokenize.detect_encoding(BytesIO(raw).readline)
    with TextIOWrapper(BytesIO(raw), encoding=encoding, newline=None) as stream:
        return stream.read()


class _Ledger:
    def __init__(self, call_budget, budget):
        self.call, self.budget = call_budget, budget
        self.counts = Counter()
        self.compile_reservations = set()

    def source(self, size):
        if self.counts["source_files"] >= self.call.max_source_files:
            raise _Limit("global source file budget exceeded")
        if size > self.call.max_source_bytes - self.counts["source_bytes"]:
            raise _Limit("global source byte budget exceeded")
        # Failed source construction still consumes its admitted input work.
        self.counts["source_files"] += 1
        self.counts["source_bytes"] += size

    def metadata(self, size):
        if self.counts["metadata_files"] >= self.budget.max_metadata_files:
            raise _Limit("global metadata file budget exceeded")
        if size > self.budget.max_metadata_bytes - self.counts["metadata_bytes"]:
            raise _Limit("global metadata byte budget exceeded")
        self.counts["metadata_files"] += 1
        self.counts["metadata_bytes"] += size

    def archive(self, size):
        if size > self.budget.max_archive_bytes - self.counts["archive_canonical_bytes"]:
            raise _Limit("global archive byte budget exceeded")
        self.counts["archive_canonical_bytes"] += size

    def reserve_compilation(self, namespace, path, fingerprint, flags, compiled):
        keys = tuple(compile_cache_key(path, fingerprint, _PROFILE, flags, optimize,
                                      compile_filename=str(path)) for optimize in (0, 1, 2))
        new = [(namespace, key) for key in keys
               if key not in compiled and (namespace, key) not in self.compile_reservations]
        if len(new) > self.budget.max_compile_variants - len(self.compile_reservations):
            raise _Limit("global compilation variant reservation budget exceeded")
        # Reservations are not refunded if compile or source construction fails.
        self.compile_reservations.update(new)
        self.counts["compile_variants_reserved"] = len(self.compile_reservations)


class _Archives:
    def __init__(self, destination, ledger):
        self.out, self.ledger = destination, ledger
        self.files = {}
        self._artifacts = {}

    def write(self, directory, schema, document):
        payload = _bounded_canonical(document, self.ledger.budget.max_archive_record_bytes)
        digest = _sha(payload)
        relative = f"{directory}/{digest}.json.gz"
        if relative in self._artifacts:
            return self._artifacts[relative]
        self.ledger.archive(len(payload))
        path = self.out / relative
        compressed = _write_gzip_exclusive(path, payload)
        artifact = {"schema": schema, "schema_version": 1, "path": relative,
                    "canonical_sha256": digest, "canonical_bytes": len(payload),
                    "compressed_bytes": compressed}
        self._artifacts[relative] = artifact
        self.ledger.counts["archive_compressed_bytes"] += compressed
        return artifact

    def metadata(self, path):
        size = path.stat().st_size
        self.ledger.metadata(size)
        raw = _read_file(path, min(self.ledger.budget.max_metadata_record_bytes,
                                   self.ledger.budget.max_metadata_bytes))
        artifact = self.write("providers", "scar.dependency-provider-artifact", {
            "schema": "scar.dependency-provider-artifact", "schema_version": 1,
            "original_uri": str(path), "raw_sha256": _sha(raw), "raw_bytes": len(raw),
            "raw_base64": base64.b64encode(raw).decode("ascii"),
        })
        return raw, artifact

    def source(self, path, root):
        size = path.stat().st_size
        self.ledger.source(size)
        raw = _read_file(path, min(4_000_000, self.ledger.call.max_source_bytes))
        text = _decode_source(raw)
        fingerprint = "sha256:" + _sha(text.encode("utf-8"))
        row = {"source_root": root["id"], "path": str(path),
               "raw_sha256": _sha(raw), "raw_bytes": len(raw),
               "fingerprint": fingerprint, "snapshot_artifact": None,
               "source_graph_artifact": None, "context": None,
               "providers": [], "frontiers": []}
        self.files[str(path)] = row
        row["snapshot_artifact"] = self.write("sources", "scar.dependency-source-snapshot", {
            "schema": "scar.dependency-source-snapshot", "schema_version": 1,
            "source_root": root["id"], "namespace_root": root["namespace_root"],
            "original_uri": str(path), "raw_sha256": row["raw_sha256"], "raw_bytes": len(raw),
            "raw_base64": base64.b64encode(raw).decode("ascii"),
            "decoded_text": text, "fingerprint": fingerprint,
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
            "code_source_match_established": False,
        })
        return row

    def prepared(self, context, root):
        row = self.files[str(context.path)]
        if row["source_graph_artifact"] is not None:
            return
        if "sha256:" + _sha(context.text.encode("utf-8")) != row["fingerprint"]:
            raise ValueError("prepared source changed since retained dependency snapshot")
        if context.semantics.sources[str(context.path)].fingerprint != row["fingerprint"]:
            raise ValueError("prepared dependency source snapshot differs")
        # These are the original already-prepared source graphs, exported at
        # first preparation. No second prepare or fake inventory is needed.
        semantic = context.semantic.to_dict()
        semantics = context.semantics.to_dict()
        control = context.control.to_dict()
        digest = SourceContextDigest(str(context.root), _sha(_canonical(semantic)),
                                    _sha(_canonical(semantics)), _sha(_canonical(control)))
        row["context"] = encode(digest)
        try:
            row["source_graph_artifact"] = self.write("graphs", "scar.dependency-source-graphs", {
                "schema": "scar.dependency-source-graphs", "schema_version": 1,
                "source_root": root["id"], "namespace_root": str(context.root),
                "snapshot": encode(context.semantics.sources[str(context.path)]),
                "source_snapshot_artifact": row["snapshot_artifact"],
                "context": encode(digest), "semantic": semantic,
                "semantics": semantics, "control": control,
                "source_layer_producer": "EXPORTED_DURING_FIRST_SOURCE_PREPARATION",
                "independent_source_replay_established": False,
                **_AUTHORITY,
            })
        except _Limit as error:
            row["frontiers"].append(_gap("SOURCE_GRAPH_ARCHIVE_BUDGET", str(error)))
            # The earlier independent source snapshot remains retained.


class _ArchivingWorkspace(_SourceWorkspace):
    def __init__(self, root, context_budget, shared_store, archives, emit):
        super().__init__(root["namespace_root"], context_budget, entry=None)
        # All namespaces share one existing bounded scratch store. Release only
        # this newly created empty temporary store before replacing it.
        self.store.close()
        self.store = shared_store
        self._archive_root, self._archives = root, archives
        self._emit = emit
        self._export_attempted = set()

    def prepare(self, path):
        self._emit("prepare", "BEGIN", path=str(path))
        context = super().prepare(path)
        self._emit("prepare", "END", path=str(path))
        key = str(path)
        if key not in self._export_attempted:
            self._export_attempted.add(key)
            self._archives.prepared(context, self._archive_root)
            self._emit("source_graph_archive", "END", path=key,
                       stored=self._archives.files[key]["source_graph_artifact"] is not None)
        return context


def _source_roots(program_root, budget):
    groups = {}
    for role in ("purelib", "platlib", "stdlib"):
        value = sysconfig.get_path(role)
        if not value:
            continue
        path = Path(value).resolve()
        if path.is_dir() and path != Path(path.anchor):
            groups.setdefault(str(path), {"roles": [], "kind": "PYTHON_ENVIRONMENT"})["roles"].append(role)
    tool = Path(__file__).resolve().parents[2]
    if tool.is_dir() and tool != Path(tool.anchor):
        group = groups.setdefault(str(tool), {"roles": [], "kind": "TOOL_SOURCE"})
        group["roles"].append("tool")
    roots, gaps = [], []
    for path, fields in sorted(groups.items()):
        if path == str(program_root):
            continue
        if len(roots) >= budget.max_roots:
            gaps.append(_gap("SOURCE_ROOT_BUDGET", path))
            continue
        root = {"namespace_root": path, "kind": fields["kind"],
                "roles": sorted(fields["roles"]), "origin": "CURRENT_INTERPRETER_SYSCONFIG_OR_TOOL_MODULE",
                "python_version": sys.version, "implementation": sys.implementation.name,
                "cache_tag": sys.implementation.cache_tag}
        root["id"] = "dependency-source-root:" + _sha(_canonical(root))
        roots.append(root)
    return roots, gaps


def _pick_root(path, roots):
    matching = [root for root in roots if path.is_relative_to(root["namespace_root"])]
    return max(matching, key=lambda root: len(Path(root["namespace_root"]).parts), default=None)


def _distribution_owners(roots, wanted, archives):
    """Read bounded installed metadata only; do not import candidate packages."""
    owners, gaps = defaultdict(list), []
    for root in roots:
        if not {"purelib", "platlib"}.intersection(root["roles"]):
            continue
        base = Path(root["namespace_root"])
        paths = {path for path in wanted if _pick_root(Path(path), roots) is root}
        if not paths:
            continue
        candidates = []
        try:
            with os.scandir(base) as entries:
                for entry in entries:
                    archives.ledger.counts["metadata_directory_entries"] += 1
                    if archives.ledger.counts["metadata_directory_entries"] > archives.ledger.budget.max_metadata_entries:
                        raise _Limit("global metadata directory entry budget exceeded")
                    if entry.name.endswith(".dist-info") and entry.is_dir(follow_symlinks=False):
                        candidates.append(Path(entry.path))
        except (OSError, _Limit) as error:
            gaps.append(_gap("DISTRIBUTION_METADATA_ENUMERATION", str(error)))
        for directory in sorted(candidates):
            try:
                metadata_path, record_path = directory / "METADATA", directory / "RECORD"
                if (metadata_path.is_symlink() or record_path.is_symlink()
                        or not metadata_path.is_file() or not record_path.is_file()):
                    continue
                raw, metadata_artifact = archives.metadata(metadata_path)
                records, record_artifact = archives.metadata(record_path)
                message = BytesParser(policy=compat32).parsebytes(raw, headersonly=True)
                name, version = message.get("Name"), message.get("Version")
                if (len(message.get_all("Name", [])) != 1 or len(message.get_all("Version", [])) != 1
                        or type(name) is not str or not name or type(version) is not str or not version):
                    gaps.append(_gap("DISTRIBUTION_METADATA_IDENTITY", str(directory)))
                    continue
                provider = {"kind": "INSTALLED_DISTRIBUTION", "name": name, "version": version,
                            "metadata_artifact": metadata_artifact, "record_artifact": record_artifact,
                            "record_is_ownership_evidence_not_source_or_code_proof": True}
                matched = set()
                for row in csv.reader(StringIO(records.decode("utf-8", errors="strict"))):
                    if not row or not row[0]:
                        continue
                    relative = Path(row[0])
                    if relative.is_absolute():
                        continue
                    candidate = base / relative
                    # RECORD may name scripts outside site-packages; those are
                    # not roots granted by this protocol and are not followed.
                    normalized = Path(os.path.normpath(str(candidate)))
                    if normalized.is_relative_to(base) and str(normalized) in paths:
                        matched.add(str(normalized))
                for path in matched:
                    owners[path].append(provider)
            except (OSError, ValueError, UnicodeError, csv.Error) as error:
                gaps.append(_gap("DISTRIBUTION_METADATA_UNAVAILABLE", type(error).__name__ + ": " + str(error)))
                if isinstance(error, _Limit):
                    break
    return owners, gaps


def admit_dependency_sources(trace_directory, project_root, out_directory, *,
                             call_budget=CallEdgeBudget(), budget=DependencySourceBudget(),
                             context_budget=ContextStoreBudget(), progress=None):
    """Publish a standalone dependency admission sidecar from one strict scan.

    Every entered (process, code) remains in the denominator. Program-local
    codes are left to the existing inventory. External matches retain the old
    CodeSourceLink and the first prepared source graphs, qualified by root and
    artifact. Outputs are fragments, never an inline inventory or execution IR.
    """
    if (type(call_budget) is not CallEdgeBudget or type(budget) is not DependencySourceBudget
            or type(context_budget) is not ContextStoreBudget):
        raise TypeError("dependency admission requires exact typed budgets")
    call_budget.__post_init__(); budget.__post_init__(); context_budget.__post_init__()
    if progress is not None and not callable(progress):
        raise TypeError("progress must be a caller-owned callable or None")
    started, emitted, progress_errors = time.monotonic(), 0, []

    def emit(stage, status, **fields):
        nonlocal emitted
        if progress is None or emitted >= 6 * call_budget.max_source_files + 32:
            return
        emitted += 1
        try:
            progress({"stage": stage, "status": status,
                      "elapsed_s": time.monotonic() - started, **fields})
        except Exception as error:
            if len(progress_errors) < 8:
                progress_errors.append(type(error).__name__)
    program_root = Path(project_root).resolve()
    if not program_root.is_dir():
        raise ValueError("program root must be an existing directory")
    destination = Path(out_directory).absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError("dependency admission output must be fresh")
    sink = _EnteredCodeSink()
    emit("raw_scan", "BEGIN")
    scanned = scan_call_trace(trace_directory, program_root, call_budget, sink=sink)
    groups = sink.groups()
    emit("raw_scan", "END", entered_code_groups=len(groups),
         entered_invocations=sum(group.count for group in groups))
    captures = {(capture.process_id, capture.code.key): capture for capture in scanned.captures}
    python_matches = {meta["process_id"]: meta.get("python") == sys.version for meta in scanned.metadata}
    roots, root_gaps = _source_roots(program_root, budget)
    ledger = _Ledger(call_budget, budget)
    destination.mkdir(parents=True, exist_ok=False)
    for directory in ("sources", "graphs", "providers"):
        (destination / directory).mkdir()
    archives = _Archives(destination, ledger)
    pending, rows, file_errors = defaultdict(list), [], {}
    for group in groups:
        capture = captures.get((group.process_id, group.code))
        row = {"process_id": group.process_id, "code": group.code,
               "entered_invocations": group.count, "first_anchor": encode(group.first_anchor),
               "last_anchor": encode(group.last_anchor),
               "captured_code": encode(capture.code) if capture is not None else None,
               "descriptor_anchor": encode(capture.anchor) if capture is not None else None,
               "status": "UNRESOLVED", "source_root": None, "source_file": None,
               "code_source_link": None, "frontiers": []}
        rows.append(row)
        if capture is None:
            row["frontiers"].append(_gap("CAPTURE_DESCRIPTOR_MISSING", "entered code has no retained descriptor"))
            continue
        if not python_matches.get(group.process_id, False):
            row["frontiers"].append(_gap("RECORDED_PYTHON_MISMATCH", "recorded Python string does not exactly match this interpreter"))
            continue
        path = Path(capture.code.filename)
        if not path.is_absolute():
            row["frontiers"].append(_gap("NONFILE_CODE_FILENAME", "frozen/generated/relative code needs a separate provider"))
            continue
        if path.is_relative_to(program_root):
            row["status"] = "PROGRAM_SCOPE_RETAINED"
            continue
        root = _pick_root(path, roots)
        if root is None:
            row["frontiers"].append(_gap("NO_ENVIRONMENT_SOURCE_ROOT", "code filename is outside automatically established namespaces"))
            continue
        row["source_root"] = root["id"]
        try:
            if path.suffix != ".py" or path != path.resolve(strict=True) or not path.is_file():
                raise ValueError("dependency source must be an existing canonical .py file")
        except (OSError, ValueError) as error:
            row["frontiers"].append(_gap("SOURCE_FILE_UNAVAILABLE", str(error)))
            continue
        pending[str(path)].append((row, capture.code, root))
    # The manifest's precise demanded files, not a recursive environment scan.
    emit("provider_metadata", "BEGIN", demanded_files=len(pending))
    owners, provider_gaps = _distribution_owners(roots, set(pending), archives)
    emit("provider_metadata", "END", owned_files=len(owners), frontiers=len(provider_gaps))
    workers = {}
    with PreparedContextStore(context_budget) as shared_store:
        for filename, requests in sorted(pending.items()):
            path, root = Path(filename), requests[0][2]
            emit("source_file", "BEGIN", path=filename, entered_code_groups=len(requests))
            try:
                file_row = archives.source(path, root)
                if {"purelib", "platlib"}.intersection(root["roles"]):
                    file_row["providers"] = owners.get(filename, [])
                    if len(file_row["providers"]) != 1:
                        code = "DISTRIBUTION_OWNERSHIP_AMBIGUOUS" if file_row["providers"] else "DISTRIBUTION_OWNERSHIP_UNRESOLVED"
                        file_row["frontiers"].append(_gap(code, "retain source facts without inventing a unique distribution/version"))
                elif "tool" in root["roles"]:
                    file_row["providers"] = [{"kind": "CURRENT_TOOL_SOURCE", "version": getattr(scar, "__version__", None),
                                              "module_path": str(Path(__file__).resolve()),
                                              "observer_origin_of_each_invocation_established": False}]
                else:
                    file_row["providers"] = [{"kind": "CURRENT_PYTHON_STDLIB", "version": sys.version,
                                              "implementation": sys.implementation.name,
                                              "sysconfig_role": "stdlib", "namespace_root": root["namespace_root"]}]
                if root["id"] not in workers:
                    workspace = _ArchivingWorkspace(root, context_budget, shared_store, archives, emit)
                    worker = _Sources(Path(root["namespace_root"]), call_budget, inventory=None,
                                      _source_workspace=workspace, compilation_profile=_PROFILE)
                    workers[root["id"]] = workspace, worker
                _, resolver = workers[root["id"]]
                for row, captured, _ in requests:
                    row["source_file"] = filename
                    try:
                        try:
                            future_flags_for(captured.flags, _PROFILE)
                        except UnsupportedCompilationFlags:
                            pass  # The original resolver publishes the exact unsupported-flags issue.
                        else:
                            ledger.reserve_compilation(root["id"], path, file_row["fingerprint"],
                                                       captured.flags, resolver.compiled)
                        link = resolver.code(captured)
                        row["code_source_link"] = encode(link)
                        row["status"] = "SOURCE_" + link.status.value
                        if link.snapshot is not None and link.snapshot.fingerprint != file_row["fingerprint"]:
                            row["status"] = "UNRESOLVED"
                            row["frontiers"].append(_gap("RETAINED_SOURCE_MISMATCH", "code/source witness differs from retained source artifact"))
                        if link.status.value != "VERIFIED":
                            row["frontiers"].append(_gap("CODE_SOURCE_" + link.status.value, "see original CodeSourceLink issues"))
                        if link.definition is None:
                            row["frontiers"].append(_gap("DEFINITION_NOT_LINKED", "successful code correspondence does not invent a definition/body interface"))
                    except _Limit as error:
                        row["frontiers"].append(_gap("COMPILATION_BUDGET", str(error)))
                    except (OSError, ValueError, TypeError, KeyError, SyntaxError, RecursionError) as error:
                        row["frontiers"].append(_gap("SOURCE_MATCH_UNAVAILABLE", type(error).__name__ + ": " + str(error)))
            except (OSError, ValueError, TypeError, KeyError, SyntaxError, RecursionError) as error:
                file_errors[filename] = _gap("SOURCE_ADMISSION_UNAVAILABLE", type(error).__name__ + ": " + str(error))
                for row, _, _ in requests:
                    row["frontiers"].append(file_errors[filename])
            emit("source_file", "END", path=filename,
                 statuses=dict(Counter(row["status"] for row, _, _ in requests)))
        measurements = {
            **dict(ledger.counts), "actual_compile_cache_entries": sum(len(worker.compiled) for _, worker in workers.values()),
            "scratch_compressed_bytes_written": shared_store.compressed_bytes_written,
            "scratch_uncompressed_bytes_written": shared_store.uncompressed_bytes_written,
            "source_prepare_attempts": sum(sum(workspace.preparations.values()) for workspace, _ in workers.values()),
            "progress_events_emitted": emitted, "progress_callback_errors": progress_errors,
        }
    for row in rows:
        source = archives.files.get(row["source_file"])
        if source is not None:
            row["frontiers"].extend(source["frontiers"])
            if source["source_graph_artifact"] is None:
                row["frontiers"].append(_gap("SOURCE_GRAPHS_UNAVAILABLE", "retained source snapshot is separate from prepared source graphs"))
    statuses, weighted, frontiers = Counter(), Counter(), Counter()
    for row in rows:
        statuses[row["status"]] += 1
        weighted[row["status"]] += row["entered_invocations"]
        for code in {gap["code"] for gap in row["frontiers"]}:
            frontiers[code] += row["entered_invocations"]
    report = {
        "schema": "scar.dependency-source-admissions", "schema_version": 1,
        "scope": "entered code dependency source fragments; original program root and inventory unchanged",
        "program_root": str(program_root), "trace_directory": scanned.directory,
        "trace_files": encode(scanned.files), "collection_metadata": list(scanned.metadata),
        "raw_scan_issues": encode(scanned.issues), "call_budget": encode(call_budget),
        "budget": encode(budget), "context_budget": encode(context_budget),
        "compilation_profile": _PROFILE.value,
        "environment": {"python": sys.version, "executable": sys.executable,
                        "prefix": sys.prefix, "base_prefix": sys.base_prefix,
                        "implementation": sys.implementation.name, "cache_tag": sys.implementation.cache_tag,
                        "recorded_python_exact_string_matches": [
                            {"process_id": pid, "matches": matched}
                            for pid, matched in sorted(python_matches.items())],
                        "captured_executable_binary_identity_established": False},
        "source_roots": roots, "root_frontiers": root_gaps,
        "provider_frontiers": provider_gaps, "source_files": list(archives.files.values()),
        "file_errors": file_errors, "admissions": rows,
        "summary": {"entered_code_groups": len(rows), "entered_invocations": sum(group.count for group in groups),
                    "statuses": dict(statuses), "weighted_statuses": dict(weighted),
                    "weighted_frontiers": dict(frontiers),
                    "source_files_with_snapshots": sum(row["snapshot_artifact"] is not None for row in archives.files.values()),
                    "source_files_with_graphs": sum(row["source_graph_artifact"] is not None for row in archives.files.values())},
        "measurements": measurements,
        "conditions": ["current interpreter string matches are not captured executable binary identities",
                       "current installed provider versions are not independently captured package version facts",
                       "distribution metadata is ownership evidence, not source integrity or effect proof",
                       "root-qualified source artifacts are fragments, not inline inventory v8 or a ProgramSnapshot",
                       "source preparation/export is not independent public source replay",
                       "program-local codes remain delegated to the original inventory pipeline"],
        **_AUTHORITY,
    }
    payload = _bounded_canonical(report, budget.max_report_bytes)
    with (destination / "admissions.json").open("xb") as stream:
        stream.write(payload)
    emit("report", "END", entered_code_groups=len(rows), statuses=dict(statuses))
    return report


__all__ = ["DependencySourceBudget", "admit_dependency_sources"]
