"""Read actual environment identity evidence into existing source entry ports.

The caller supplies the original reader's operand/call/source models from the
same analysis invocation.  This adapter independently reads and hashes the
environment sidecars; it neither executes the target nor rebuilds source graphs.
Output records reference canonical EnvironmentInterface member ValueIDs.  They
are conditional identity associations, not another graph, state/content proof,
default-argument binding rule or optimization permission.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
from pathlib import Path
import re

from scar.analysis.runtime_sources import _json_object
from scar.ir.program.call_edges import CallLinkStatus, InvocationKey
from scar.ir.program.call_operands import CallableKind
from scar.ir.program.environments import EnvironmentRole
from scar.ir.record_codec import encode
from scar.trace.files import open_binary


_PATTERN = re.compile(r"function-(environments|environment-meta)\.([1-9][0-9]*)\.(jsonl|json)(?:\.gz)?$")
_COMMON = {"index", "kind", "process_id", "thread_id", "attempt_index", "invocation_id", "frame_index"}
_DISPATCH = _COMMON | {"code_key", "members", "observation_stage"}
_ENTRY = _COMMON | {"dispatch_index", "function_reference", "function_match", "globals_match",
                    "builtins_match", "readonly_association_checks_only"}
_GAP = _COMMON | {"reason"}
_MEMBER = {"role", "reference", "basis", "owner_reference", "cell_name", "cell_position"}
_ROLES = tuple(role.value for role in (
    EnvironmentRole.FUNCTION_OBJECT, EnvironmentRole.GLOBALS_NAMESPACE,
    EnvironmentRole.BUILTINS_NAMESPACE, EnvironmentRole.DEFAULTS, EnvironmentRole.KEYWORD_DEFAULTS))
_AUTHORITY = {
    "reference_contents_observed": False, "cell_contents_observed": False,
    "logical_versions_established": False, "callable_environment_established": False,
    "defaults_binding_established": False, "atomic_snapshot_established": False,
    "effects_established": False, "transformation_authorized": False,
}
_META_FIELDS = {
    "schema", "schema_version", "process_id", "python", "implementation", "limits", "events",
    "event_attempts", "dispatches", "entries", "gaps", "references", "bytes", "dropped_events",
    "errors", "io_failed", "stop_reason", "registry_peak", "anchor_peak", "anchors_per_object_limit",
    "pending_peak", "pending_dispatches", "discarded_dispatches", "scope", "identity_continuity",
    "owner_contract", "file", *_AUTHORITY,
}
_CONDITIONS = (
    "CAPTURE_PRODUCER_TRUSTED", "SIDECARS_BELONG_TO_THE_SAME_CAPTURE",
    "PYTHON_READONLY_FUNCTION_OWNER_NOT_MUTATED_BY_NATIVE_CODE",
    "MONITORING_AND_FRAME_INTERPOSITION_REMAIN_UNCLOSED",
)


def _need(condition, detail):
    if not condition:
        raise ValueError("callable environment: " + detail)


def _integer(value, name, minimum=0):
    _need(type(value) is int and value >= minimum, name + " must be an exact integer")
    return value


def _logical(path):
    return str(path.with_suffix("")) if path.suffix == ".gz" else str(path)


def _manifest_key(row):
    return row.process_id, row.family, Path(row.path).name, row.raw_sha256, row.raw_bytes, row.lines


def _anchor(path, line, raw, index=None):
    return {"path": _logical(path), "line_number": line,
            "line_sha256": hashlib.sha256(raw).hexdigest(), "index": index}


def _validate_metadata(meta, process, operand_meta):
    _need(set(meta) == _META_FIELDS and meta["schema"] == "scar.function-environment-trace"
          and type(meta["schema_version"]) is int and meta["schema_version"] == 1,
          "metadata fields/schema/version differ")
    _need(type(meta["process_id"]) is int and meta["process_id"] == process
          and meta["implementation"] == "cpython" and meta["python"] == operand_meta.python,
          "process/interpreter differs from original operand collector")
    _need(all(meta[name] is False for name in _AUTHORITY), "metadata overstates identity/effect authority")
    limits = meta["limits"]
    _need(type(limits) is dict and set(limits) == {"max_events", "max_bytes", "max_references"},
          "metadata limits differ")
    for name, value in limits.items():
        _integer(value, name, 1)
    for name in ("events", "event_attempts", "dispatches", "entries", "gaps", "references", "bytes",
                 "dropped_events", "registry_peak", "anchor_peak", "pending_peak", "pending_dispatches",
                 "discarded_dispatches"):
        _integer(meta[name], name)
    _need(meta["events"] == meta["dispatches"] + meta["entries"] + meta["gaps"]
          and meta["events"] <= meta["event_attempts"] <= limits["max_events"]
          and meta["event_attempts"] - meta["events"] <= meta["dropped_events"]
          and meta["bytes"] <= limits["max_bytes"], "collector counts exceed their declared limits")
    _need(meta["registry_peak"] <= meta["anchor_peak"] <= limits["max_references"]
          and type(meta["anchors_per_object_limit"]) is int and meta["anchors_per_object_limit"] == 4
          and meta["pending_dispatches"] <= meta["pending_peak"] <= meta["dispatches"]
          and 0 <= meta["dispatches"] - meta["entries"] - meta["discarded_dispatches"] - meta["pending_dispatches"]
              <= meta["dropped_events"],
          "registry/pending accounting differs")
    _need(type(meta["io_failed"]) is bool and type(meta["errors"]) is list and len(meta["errors"]) <= 16
          and all(type(item) is str and item for item in meta["errors"]), "invalid collector error metadata")
    _need(meta["stop_reason"] is None or type(meta["stop_reason"]) is str and bool(meta["stop_reason"]),
          "invalid collector stop reason")
    for name in ("scope", "identity_continuity", "owner_contract"):
        _need(type(meta[name]) is str and bool(meta[name]), "missing collection scope/owner contract")
    file = meta["file"]
    _need(type(file) is dict and set(file) == {"path", "raw_sha256", "raw_bytes", "lines"}
          and type(file["path"]) is str and Path(file["path"]).name == f"function-environments.{process}.jsonl"
          and type(file["raw_sha256"]) is str and re.fullmatch(r"[0-9a-f]{64}", file["raw_sha256"])
          and type(file["raw_bytes"]) is int and file["raw_bytes"] == meta["bytes"]
          and type(file["lines"]) is int and file["lines"] == meta["events"], "event manifest differs")


def _validate_dispatch(row, process):
    _need(set(row) == _DISPATCH and row["observation_stage"] == "DISPATCH_FIELD_OBSERVATIONS",
          "dispatch fields/stage differ")
    _need(type(row["code_key"]) is str and re.fullmatch(r"pycode-v2:[0-9a-f]{64}", row["code_key"]),
          "dispatch code key is invalid")
    members = row["members"]
    _need(type(members) is list and len(members) >= 5 and all(type(member) is dict for member in members),
          "dispatch must contain its complete environment prefix")
    _need(tuple(member.get("role") for member in members[:5]) == _ROLES
          and all(member.get("role") == EnvironmentRole.CAPTURED_CELL.value for member in members[5:]),
          "environment role order differs")
    function_ref = members[0].get("reference")
    _need(type(function_ref) is str and re.fullmatch(rf"weak:{process}:[1-9][0-9]*", function_ref),
          "function identity does not use the original weak-reference protocol")
    snapshots, names, references = {}, set(), 0
    for position, member in enumerate(members):
        _need(set(member) == _MEMBER, "environment member fields differ")
        reference = member["reference"]
        _need(type(reference) is str, "member reference must be text")
        references += 1 + (member["owner_reference"] is not None)
        if position == 0:
            _need(member["basis"] == "BASE_WEAK_REFERENCE" and member["owner_reference"] is None,
                  "function identity basis differs")
        elif position in (3, 4):
            match = re.fullmatch(rf"environment-snapshot:{process}:{row['index']}:([1-9][0-9]*)", reference)
            _need(match is not None and member["basis"] == "EVENT_LOCAL_SNAPSHOT"
                  and member["owner_reference"] is None, "mutable defaults cannot claim across-event identity")
            ordinal = int(match.group(1))
            if reference not in snapshots:
                _need(ordinal == len(snapshots) + 1, "event snapshot ordinals are not consecutive")
                snapshots[reference] = ordinal
        else:
            _need(re.fullmatch(rf"environment-anchor:{process}:[1-9][0-9]*", reference)
                  and member["basis"] == "LIVE_READONLY_FUNCTION_OWNER"
                  and member["owner_reference"] == function_ref, "readonly owner identity basis differs")
        if position < 5:
            _need(member["cell_name"] is None and member["cell_position"] is None,
                  "non-cell environment member contains a cell position")
        else:
            name = member["cell_name"]
            _need(type(name) is str and bool(name) and name not in names
                  and type(member["cell_position"]) is int and member["cell_position"] == position - 5,
                  "captured cell names/positions differ")
            names.add(name)
    return references


def import_callable_environments(trace, *, inventory, sources, call_model, operand_model,
                                max_raw_bytes=128_000_000, max_events=1_000_000,
                                max_line_bytes=2_000_000, max_references=2_000_000):
    """Read retained raw/gzip sidecars and bind only evidenced entry identities.

    Source/call/operand inputs must be the objects built together by the existing
    raw adapter.  File manifests and cross-event coordinates are checked here;
    supplied source matches are not re-executed or upgraded.  Paths in manifests
    are provenance labels: this reader opens only enumerated files in ``trace``
    or its immediate ``raw`` child, supporting relocated retained artifacts.
    """
    for name, value in (("max_raw_bytes", max_raw_bytes), ("max_events", max_events),
                        ("max_line_bytes", max_line_bytes), ("max_references", max_references)):
        _integer(value, name, 1)
    _need(sources.inventory is inventory and str(sources.root) == call_model.project_root == operand_model.project_root,
          "source/call/operand inputs do not belong to the same inventory/root")
    _need({_manifest_key(file) for file in call_model.files}
          == {_manifest_key(file) for file in operand_model.frame_scan.files},
          "call and operand readers did not bind identical original frame manifests")
    path = Path(trace).resolve()
    _need(path.is_dir(), "trace locator is not a retained directory")
    directories = [path]
    if (path / "raw").is_dir() and not (path / "raw").is_symlink():
        directories.append(path / "raw")
    families = {}
    for directory in directories:
        for candidate in directory.iterdir():
            match = _PATTERN.fullmatch(candidate.name)
            if match is None:
                continue
            family, process, suffix = match.groups()
            _need((family == "environment-meta") == (suffix == "json"), "sidecar suffix/family differs")
            _need(candidate.is_file() and not candidate.is_symlink(), "sidecar must be an ordinary retained file")
            key = int(process), family
            _need(key not in families, "duplicate plain/gzip or root/raw environment sidecar")
            families[key] = candidate
    processes = {process for process, _ in families}
    _need(len(processes) <= 128 and all((process, family) in families for process in processes
          for family in ("environments", "environment-meta")), "incomplete/excessive sidecar process families")
    metas = {meta.process_id: meta for meta in operand_model.metadata}
    attempts = {(event.process_id, event.index): event for event in operand_model.attempts}
    handshakes = defaultdict(list)
    for event in operand_model.handshakes:
        handshakes[event.process_id, event.attempt_index].append(event)
    edges = {edge.entry.invocation: edge for edge in call_model.edges}
    total_bytes = total_events = total_refs = 0
    files, metadata, raw_gaps = [], [], []
    dispatches, entries = {}, {}

    def lines(process, family):
        nonlocal total_bytes
        candidate = families[process, family]
        digest, file_bytes, line_count = hashlib.sha256(), 0, 0
        with open_binary(candidate) as stream:
            while True:
                allowance = min(max_line_bytes, max_raw_bytes - total_bytes)
                if family == "environment-meta":
                    allowance = min(allowance, 64_000 - file_bytes)
                raw = stream.readline(max(0, allowance) + 1)
                if not raw:
                    break
                _need(len(raw) <= allowance and raw.endswith(b"\n") and bool(raw.strip()),
                      "incomplete line or independent byte/line budget exceeded")
                line_count += 1
                total_bytes += len(raw); file_bytes += len(raw); digest.update(raw)
                yield candidate, line_count, raw
        files.append({"path": _logical(candidate), "family": family, "process_id": process,
                      "raw_sha256": digest.hexdigest(), "raw_bytes": file_bytes, "lines": line_count})

    for process in sorted(processes):
        _need(process in metas, "environment process has no original operand collector")
        meta_rows = list(lines(process, "environment-meta"))
        _need(len(meta_rows) == 1, "environment metadata must be exactly one JSON line")
        candidate, number, raw = meta_rows[0]
        meta = _json_object(raw, path=str(candidate), line_number=number)
        _validate_metadata(meta, process, metas[process])
        metadata.append(meta)
        count, refs, byte_count, previous, watermark = Counter(), 0, 0, 0, 0
        for candidate, number, raw in lines(process, "environments"):
            row = _json_object(raw, path=str(candidate), line_number=number)
            kind = row.get("kind")
            _need(kind in ("DISPATCH", "ENTRY", "GAP"), "unknown environment event")
            for name, minimum in (("index", 1), ("process_id", 1), ("thread_id", 0)):
                _integer(row.get(name), name, minimum)
            _need(row["process_id"] == process and previous < row["index"] <= meta["event_attempts"],
                  "event process/index differs")
            previous = row["index"]
            if kind != "GAP":
                _integer(row.get("attempt_index"), "attempt_index", 1)
                _integer(row.get("invocation_id"), "invocation_id", 1)
                _integer(row.get("frame_index"), "frame_index")
                _need(watermark <= row["frame_index"], "frame watermark moved backwards")
                watermark = row["frame_index"]
            anchor = _anchor(candidate, number, raw, row["index"])
            key = process, row.get("attempt_index")
            if kind == "DISPATCH":
                references = _validate_dispatch(row, process)
                _need(key not in dispatches, "duplicate environment dispatch attempt")
                attempt = attempts.get(key)
                _need(attempt is not None and attempt.dispatch.kind is CallableKind.EXACT_FUNCTION
                      and attempt.thread_id == row["thread_id"] and attempt.invocation_id == row["invocation_id"]
                      and attempt.frame_index == row["frame_index"] and attempt.dispatch.code == row["code_key"]
                      and attempt.dispatch.reference == row["members"][0]["reference"],
                      "dispatch disagrees with original exact-function operand attempt")
                dispatches[key] = row, anchor
            elif kind == "ENTRY":
                _need(set(row) == _ENTRY and row["readonly_association_checks_only"] is True
                      and all(type(row[name]) is bool for name in ("function_match", "globals_match", "builtins_match")),
                      "entry fields/checks differ")
                _integer(row["dispatch_index"], "dispatch_index", 1)
                dispatch = dispatches.get(key)
                _need(dispatch is not None and key not in entries and dispatch[0]["index"] == row["dispatch_index"]
                      and row["index"] > row["dispatch_index"] and row["thread_id"] == dispatch[0]["thread_id"]
                      and row["function_reference"] == dispatch[0]["members"][0]["reference"],
                      "entry has no unique matching dispatch")
                entries[key] = row, anchor
                references = 1
            else:
                _need(set(row) == _GAP and type(row["reason"]) is str and bool(row["reason"]),
                      "gap fields/reason differ")
                for name, minimum in (("attempt_index", 1), ("invocation_id", 1), ("frame_index", 0)):
                    if row[name] is not None:
                        _integer(row[name], name, minimum)
                raw_gaps.append({"reason": row["reason"], "anchor": anchor})
                references = 0
            _need(references <= meta["limits"]["max_references"], "event exceeds collector reference limit")
            count[kind] += 1; refs += references; byte_count += len(raw)
            total_events += 1; total_refs += references
            _need(total_events <= max_events and total_refs <= max_references,
                  "independent aggregate event/reference budget exceeded")
        manifest = files[-1]
        _need(count["DISPATCH"] == meta["dispatches"] and count["ENTRY"] == meta["entries"]
              and count["GAP"] == meta["gaps"] and sum(count.values()) == meta["events"]
              and refs == meta["references"] and byte_count == meta["bytes"]
              and manifest["raw_sha256"] == meta["file"]["raw_sha256"]
              and manifest["raw_bytes"] == meta["file"]["raw_bytes"] and manifest["lines"] == meta["file"]["lines"],
              "retained event hash/counts differ from metadata")

    bindings, unresolved = [], list(raw_gaps)
    from scar.analysis.environment_lowering import captured_cell_slot
    for key, (dispatch, dispatch_anchor) in dispatches.items():
        attempt = attempts[key]
        candidate = {"process_id": key[0], "attempt_index": key[1], "dispatch_anchor": dispatch_anchor,
                     "observed_members": dispatch["members"]}
        captured = entries.get(key)
        if captured is None:
            unresolved.append({**candidate, "reason": "NO_OBSERVED_ENTRY_HANDSHAKE"})
            continue
        entry, entry_anchor = captured
        candidate["entry_anchor"] = entry_anchor
        matches = handshakes[key]
        if len(matches) != 1:
            unresolved.append({**candidate, "reason": "MISSING_OR_AMBIGUOUS_OPERAND_ENTRY_HANDSHAKE"})
            continue
        handshake = matches[0]
        _need(handshake.thread_id == entry["thread_id"] and handshake.invocation_id == entry["invocation_id"]
              and handshake.entry_index == entry["frame_index"] and handshake.hook_epoch == attempt.hook_epoch,
              "environment entry disagrees with original operand handshake")
        invocation = InvocationKey(key[0], entry["thread_id"], entry["invocation_id"])
        candidate["invocation"] = encode(invocation)
        if not all(entry[name] for name in ("function_match", "globals_match", "builtins_match")):
            unresolved.append({**candidate, "reason": "ENTRY_READONLY_ASSOCIATION_MISMATCH"})
            continue
        edge = edges.get(invocation)
        if edge is None or edge.target.status is not CallLinkStatus.VERIFIED:
            unresolved.append({**candidate, "reason": "NO_VERIFIED_SOURCE_FUNCTION_FOR_ENTRY"})
            continue
        _need(edge.entry.code == dispatch["code_key"] and edge.entry.anchor.index == entry["frame_index"],
              "entry source/code differs from the dispatch evidence")
        definition = edge.target.definition
        body = sources.bodies.get(definition)
        if body is None or body.graph is None:
            unresolved.append({**candidate, "definition": encode(definition), "reason": "NO_GENERATED_SOURCE_BODY_INTERFACE"})
            continue
        environments = [environment for environment in body.graph.environments
                        if environment.region == body.graph.root and environment.code_definition == definition]
        if len(environments) != 1:
            unresolved.append({**candidate, "definition": encode(definition), "reason": "NO_UNIQUE_DECLARED_ENVIRONMENT_INTERFACE"})
            continue
        environment = environments[0]
        code = sources.objects.get(dispatch["code_key"])
        names = () if code is None else tuple(code.co_freevars)
        cells = environment.members[5:]
        if (code is None or len(environment.members) != len(dispatch["members"])
                or tuple(member.role.value for member in environment.members[:5]) != _ROLES
                or tuple(member["cell_name"] for member in dispatch["members"][5:]) != names
                or tuple(member.cell_slot for member in cells)
                    != tuple(captured_cell_slot(definition, name) for name in names)
                or tuple(member.cell_position for member in cells) != tuple(range(len(names)))):
            unresolved.append({**candidate, "definition": encode(definition), "reason": "COMPILER_SOURCE_ENVIRONMENT_LAYOUT_MISMATCH"})
            continue
        ports, missing = [], []
        for member, observed in zip(environment.members, dispatch["members"]):
            record = {"role": member.role.value, "reference_port": encode(member.reference),
                      "cell_slot": encode(member.cell_slot) if member.cell_slot is not None else None,
                      "cell_position": member.cell_position, "observed_reference": observed["reference"],
                      "identity_basis": observed["basis"]}
            if member.role in (EnvironmentRole.DEFAULTS, EnvironmentRole.KEYWORD_DEFAULTS):
                missing.append({**record, "reason": "DISPATCH_DEFAULTS_SNAPSHOT_IS_NOT_ENTRY_BINDING"})
            else:
                ports.append(record)
        bindings.append({"invocation": encode(invocation), "definition": encode(definition),
            "region": encode(environment.region), "environment": encode(environment.id),
            "dispatch_anchor": dispatch_anchor, "entry_anchor": entry_anchor,
            "operand_attempt_anchor": encode(attempt.anchor), "operand_handshake_anchor": encode(handshake.anchor),
            "frame_entry_anchor": encode(edge.entry.anchor), "ports": ports, "unresolved": missing,
            "conditions": list(_CONDITIONS), "status": "CONDITIONAL_REFERENCE_IDENTITY"})
    for key, attempt in attempts.items():
        if attempt.dispatch.kind is CallableKind.EXACT_FUNCTION and key not in dispatches:
            unresolved.append({"process_id": key[0], "attempt_index": key[1],
                               "operand_attempt_anchor": encode(attempt.anchor), "reason": "MISSING_ENVIRONMENT_DISPATCH"})
    for meta in metadata:
        if meta["dropped_events"] or meta["errors"] or meta["io_failed"] or meta["stop_reason"] is not None:
            unresolved.append({"process_id": meta["process_id"], "reason": "ENVIRONMENT_COLLECTION_INCOMPLETE",
                               "dropped_events": meta["dropped_events"], "errors": meta["errors"],
                               "stop_reason": meta["stop_reason"]})
    summary = {"processes": len(processes), "events": total_events, "references": total_refs,
               "dispatches": len(dispatches), "entries": len(entries),
               "operand_attempts": len(attempts), "identity_bound_entries": len(bindings),
               "identity_bound_ports": sum(len(record["ports"]) for record in bindings),
               "unresolved_entry_defaults": sum(len(record["unresolved"]) for record in bindings),
               "unresolved_records": len(unresolved),
               "unresolved_reasons": dict(sorted(Counter(record["reason"] for record in unresolved).items()))}
    return {"schema": "scar.callable-environment-bindings", "schema_version": 1,
            "scope": "existing source environment entry reference ports; conditional identity only",
            "valid": True, "files": files, "metadata": metadata,
            "inventory_sha256": call_model.inventory_sha256,
            "original_operand_files": encode(operand_model.files), "original_frame_files": encode(call_model.files),
            "bindings": bindings, "unresolved": unresolved, "summary": summary,
            "whole_program_graph_established": False, "state_versions_established": False, **_AUTHORITY}


__all__ = ["import_callable_environments"]
