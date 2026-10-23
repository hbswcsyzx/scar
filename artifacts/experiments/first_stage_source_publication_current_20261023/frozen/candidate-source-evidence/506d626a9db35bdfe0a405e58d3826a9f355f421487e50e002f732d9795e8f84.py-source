"""A bounded, immutable container refinement of an existing R2 selection view.

This module recovers descriptor-context identity, never descriptor contents or
physical fdtable allocation.  It does not construct a complete ExecutionModel.
All metadata inputs are explicit; provider URIs are not arbitrary file openers.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
import gzip
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import secrets

from scar.ir.execution.common import EvidencePoint, Unresolved
from scar.ir.execution.ids import ResourceInstanceID
from scar.ir.execution.resources import (
    HandleBinding, ImportedAt, InstanceTarget, ProviderHandle, ResourceInstance, RunRealm,
)
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.program.resources import ResourceKind, ResourceRole
from scar.ir.record_codec import decode, encode, loads as strict_loads
from scar.store.bundle_partitions import BundleBudgets, _line
from scar.trace import os_resources as parser
from scar.trace.os_resource_refinement import OSResourceBase, OSResourceRefinement


SCHEMA = "scar.os-fd-table-context-refinement"
VERSION = 1
_RAW_SCHEMA = "strace.syscalls.text.v1"
_RELEVANT = frozenset(("execve", "execveat", "clone", "clone3", "fork", "vfork", "unshare", "close_range"))


@dataclass(frozen=True)
class FDTableContextInputs:
    capture_root: str | Path
    archive: str | Path
    coordinates: str | Path
    r1_summary: str | Path
    r1_audit: str | Path
    projection_summary: str | Path
    projection_files: str | Path
    projection_events: str | Path
    context_evidence: str | Path


@dataclass(frozen=True)
class FDTableContextBudgets:
    max_raw_bytes: int = 12_000_000
    max_raw_lines: int = 200_000
    max_line_bytes: int = 16_384
    max_files: int = 512
    max_ports: int = 128
    max_contexts: int = 8
    max_base_resource_ids: int = 20_000
    max_metadata_bytes: int = 2_000_000
    max_document_bytes: int = 4_000_000

    def __post_init__(self):
        _need(all(type(value) is int and value > 0 for value in vars(self).values()), "invalid positive budgets")


def _need(value, message):
    if not value:
        raise ValueError("OS FD table context: " + message)


def _canonical(value):
    # Reuse the bounded JSON encoder; no whole base/model is encoded here.
    limits = BundleBudgets(max_record_bytes=4_000_000, max_chunk_decoded_bytes=16_000_000)
    return _line(value, limits)


def _sha(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _document(path, maximum, schema=None):
    path = Path(path).absolute()
    _need(path.is_file() and not path.is_symlink(), "explicit metadata file absent or symlinked")
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    _need(len(raw) <= maximum, "metadata/document budget exceeded")
    value = strict_loads(raw.decode("utf-8"))
    declared = value.get("schema") if type(value) is dict else None
    actual_schema = declared if type(declared) is str and declared else "application/json"
    _need(schema is None or schema == actual_schema, "explicit artifact schema differs")
    return value, ProviderArtifact(str(path), hashlib.sha256(raw).hexdigest(), len(raw), actual_schema)


def _fact_key(source):
    return source["artifact"]["uri"], source["locator"]


def _raw_fact(entry, line):
    return {"artifact": {"uri": entry["logical_path"], "sha256": entry["raw_sha256"],
        "size_bytes": entry["raw_bytes"], "schema": _RAW_SCHEMA}, "locator": "#/lines/" + str(line)}


def _line_number(source):
    match = re.fullmatch(r"#/lines/([1-9][0-9]*)", source["locator"])
    _need(match is not None, "source is not an exact physical line")
    return int(match[1])


def _prepare(base, r2_manifest, inputs, limits, progress):
    _need(type(base) is OSResourceBase and type(inputs) is FDTableContextInputs
          and type(limits) is FDTableContextBudgets, "explicit base/inputs/budgets required")
    root = Path(inputs.capture_root).resolve()
    _need(not Path(inputs.capture_root).is_symlink() and root.is_dir(), "capture root absent or symlinked")
    names = ("archive", "coordinates", "r1_summary", "r1_audit", "projection_summary", "projection_files",
             "projection_events", "context_evidence")
    docs, receipts = {}, {}
    for name in names:
        docs[name], receipts[name] = _document(getattr(inputs, name), limits.max_metadata_bytes)
    base_wire, base_receipt = _document(base.reader.manifest_receipt["path"], limits.max_metadata_bytes, base.artifact.schema)
    _need(base_wire == base.manifest and base_receipt == base.artifact, "explicit base receipt/document changed")
    r2_wire, r2_receipt = _document(r2_manifest, limits.max_document_bytes, "scar.os-resource-refinement")
    r2 = OSResourceRefinement.read(base, r2_manifest, max_bytes=limits.max_document_bytes)
    _need(r2.document == r2_wire, "R2 bytes changed between receipt and public validation")
    receipts["r2"] = r2_receipt
    archive, coords, summary, audit, projection = (docs[name] for name in
        ("archive", "coordinates", "r1_summary", "r1_audit", "projection_summary"))
    context = docs["context_evidence"]
    _need(type(archive) is dict and type(archive.get("files")) is list, "unsupported archive")
    _need(coords.get("schema") == "scar.capture-coordinates" and coords.get("schema_version") == 1
          and coords.get("profile") == "RETAINED_COLLECTOR_PROCESS_MEMBERSHIP_V1", "unsupported coordinate profile")
    _need(projection.get("schema") == "scar.fd-table-complement-projection" and projection.get("schema_version") == 1
          and context.get("schema") == "scar.fd-table-context-read-review" and context.get("schema_version") == 1,
          "unsupported retained proof envelope")
    _need(receipts["archive"].sha256 == coords["seed"]["archive_sha256"] == coords["retention"]["archive_sha256"],
          "archive is not bound to original coordinates")
    bound_coords = base.manifest["protocol_document"]["contract"]["coordinate_binding"]
    _need((bound_coords["uri"], bound_coords["sha256"], bound_coords["size_bytes"])
          == (receipts["coordinates"].uri, receipts["coordinates"].sha256, receipts["coordinates"].size_bytes),
          "base protocol binds different original coordinates")
    _need(summary == base.manifest["summary"] and audit.get("status") == "PASS"
          and audit.get("all_work_wire_local_evidence_links") == "PASS"
          and audit["manifest_receipt"] == base.reader.manifest_receipt
          and audit["interface_names"] == summary["interface_counts"], "prior full-scope count authority differs")
    full_classes = summary["classification_counts"]
    _need(set(full_classes) <= {"COMPLETED", "SIGNAL"}
          and full_classes.get("COMPLETED") == summary["syscall_observations"]
          and sum(full_classes.values()) == summary["physical_lines"] == coords["counts"]["os_lines"],
          "full-scope source has an unqualified line/context frontier")
    _need(coords["run"] == encode(base.run) and projection["run"] == coords["run"]
          and context["run"] == coords["run"]["id"], "proofs belong to different Runs")
    _need(projection["inputs"]["manifest"]["sha256"] == base.artifact.sha256
          and context["inputs"]["r1_manifest"]["sha256"] == base.artifact.sha256
          and context["inputs"]["r2_manifest"]["sha256"] == r2_receipt.sha256,
          "proofs bind another selected base/R2")
    for proof, aliases in ((projection["inputs"], {"archive": "archive", "coordinates": "coordinates",
            "summary": "r1_summary", "audit": "r1_audit"}),
            (context["inputs"], {"archive": "archive", "coordinates": "coordinates", "summary": "r1_summary"})):
        for key, name in aliases.items():
            _need(proof[key]["path"] == receipts[name].uri and proof[key]["sha256"] == receipts[name].sha256
                  and proof[key]["bytes"] == receipts[name].size_bytes, "exact proof input receipt differs")
    original = PurePosixPath(coords["original_root"])
    entries, by_actual = {}, {}
    for row in archive["files"]:
        logical, actual = PurePosixPath(row["logical_path"]), PurePosixPath(row["actual_path"])
        _need(logical.is_absolute() and actual.is_absolute() and ".." not in logical.parts and ".." not in actual.parts
              and logical.is_relative_to(original) and actual.is_relative_to(original), "archive path escapes original namespace")
        if logical.parent != original / "os":
            continue
        _need(re.fullmatch(r"syscalls\.[1-9][0-9]*", logical.name) is not None
              and row["logical_path"] not in entries and row["actual_path"] not in by_actual,
              "unsupported/duplicate OS artifact namespace")
        _need(all(re.fullmatch(r"[0-9a-f]{64}", row.get(key, "")) for key in ("raw_sha256", "gzip_sha256"))
              and all(type(row.get(key)) is int and row[key] >= 0 for key in ("raw_bytes", "compressed_bytes")),
              "invalid exact archive receipt")
        entries[row["logical_path"]] = row; by_actual[row["actual_path"]] = row
    _need(1 < len(entries) <= limits.max_files and len(entries) == coords["counts"]["os_artifacts"]
          == base.manifest["tables"]["artifacts"]["records"], "OS artifact denominator differs")
    local_paths = {str(root / str(PurePosixPath(row["actual_path"]).relative_to(original))) for row in entries.values()}
    _need({str(path) for path in (root / "os").iterdir() if path.is_file()} == local_paths,
          "retained local OS scope is not the exact archive set")
    artifacts = []
    for envelope in base.reader.iter_records("artifacts"):
        artifact = decode(ProviderArtifact, envelope["record"])
        _need(artifact.uri in by_actual, "R1 artifact lacks exact original archive actual URI")
        entry = by_actual[artifact.uri]
        _need((artifact.sha256, artifact.size_bytes, artifact.schema) ==
              (entry["raw_sha256"], entry["raw_bytes"], _RAW_SCHEMA), "R1/archive raw identity differs")
        artifacts.append(artifact)
    _need(len(artifacts) == len(entries) and len({row.uri for row in artifacts}) == len(artifacts), "R1 artifact scope incomplete")
    target = coords["seed"]["target_exec"]["artifact"]
    _need(target["uri"] in entries and target == _raw_fact(entries[target["uri"]], 1)["artifact"], "target has no exact raw archive membership")
    main_entry = entries[target["uri"]]
    selected_entries = sorted([row for uri, row in entries.items() if uri != target["uri"]], key=lambda row: row["logical_path"])
    _need(sum(row["raw_bytes"] for row in selected_entries) <= limits.max_raw_bytes, "non-main raw byte budget exceeded")
    threads = {row["tid"]: row for row in coords["threads"]}
    processes = {row["id"]["wire"]: row for row in coords["processes"]}
    _need(len(threads) == len(coords["threads"]) and len(processes) == len(coords["processes"]), "coordinate identities ambiguous")
    members = {}
    for row in coords["membership"]:
        if row["artifact"]["schema"] == _RAW_SCHEMA:
            _need(row["artifact"]["uri"] not in members, "duplicate native artifact membership")
            members[row["artifact"]["uri"]] = row
    open_tids = {row["tid"] for row in coords["open"] if row["code"] == "os_actor_not_connected_to_target_ancestry"}
    creator_uri = coords["seed"]["target_birth"]["artifact"]["uri"]
    full, counts, classes, events, file_rows, total_bytes, total_lines = Counter(summary["interface_counts"]), Counter(), Counter(), [], [], 0, 0
    for number, entry in enumerate(selected_entries, 1):
        local = root / str(PurePosixPath(entry["actual_path"]).relative_to(original))
        _need(not local.is_symlink() and local.resolve().is_relative_to(root) and local.is_file(), "raw member unsafe or absent")
        tid = int(PurePosixPath(entry["logical_path"]).name.rsplit(".", 1)[1])
        member = members.get(entry["logical_path"])
        if member is not None:
            _need(member["artifact"] == _raw_fact(entry, 1)["artifact"] and member["local_path"] == str(local)
                  and tid in threads and member["thread"] == threads[tid]["id"]
                  and member["process"] == threads[tid]["process"], "native actor/member receipt differs")
        else:
            _need(tid in open_tids and entry["logical_path"] == creator_uri,
                  "missing native membership is not the exact witnessed creator context")
        stored, stored_bytes = hashlib.sha256(), 0
        with local.open("rb") as stream:
            while part := stream.read(65536):
                stored.update(part); stored_bytes += len(part)
        _need((stored.hexdigest(), stored_bytes) == (entry["gzip_sha256"], entry["compressed_bytes"]), "compressed receipt differs")
        digest, size, lines, calls = hashlib.sha256(), 0, 0, Counter()
        with gzip.open(local, "rb") as stream:
            while raw := stream.readline(limits.max_line_bytes + 1):
                _need(len(raw) <= limits.max_line_bytes and raw.endswith(b"\n"), "line bound/termination failed")
                size += len(raw); digest.update(raw); lines += 1; total_lines += 1; total_bytes += len(raw)
                _need(total_bytes <= limits.max_raw_bytes and total_lines <= limits.max_raw_lines, "raw projection budget exceeded")
                text = raw.decode("utf-8").rstrip("\r\n")
                timed = parser._TIME.match(text)
                _need(timed is not None, "unknown source line rendering")
                body = timed[1]
                if body.startswith("--- "):
                    classes["SIGNAL"] += 1; continue
                _need(not body.startswith("+++ ") and parser._UNFINISHED.match(body) is None
                      and parser._RESUMED.match(body) is None, "exit/migration or unfinished/resumed frontier")
                call = parser._CALL.match(body)
                _need(call is not None, "unrecognized complete call")
                name, arguments, returned, tail = call.groups()
                counts[name] += 1; calls[name] += 1; classes["COMPLETED"] += 1
                if name not in _RELEVANT:
                    continue
                args, result = parser._arguments(arguments), parser._number(returned)
                _need(result is not None and "..." not in arguments, "incomplete context-effect rendering")
                flags = parser._clone_flags({"name": name, "args": args}) if name in parser._CLONE else None
                _need(name not in parser._CLONE or result <= 0 or flags is not None, "birth flags incomplete")
                event = {"source": _raw_fact(entry, lines), "tid": tid, "syscall": name, "result": result,
                    "result_rendering": returned, "arguments": args, "arguments_split": True,
                    "argument_rendering_complete": True, "clone_flags": flags, "rendering": text,
                    "coordinate_process": threads[tid]["process"] if tid in threads else None,
                    "actor_birth": threads[tid]["source"] if tid in threads else None}
                if name in ("execve", "execveat") and result == 0:
                    if tid in threads:
                        process = processes[threads[tid]["process"]["wire"]]
                        event.update(coordinate_process_pid=process["pid"],
                            exec_affects_target_group=process["id"] == coords["target_process"],
                            leader_according_to_existing_birth_profile=process["pid"] == tid)
                        _need(not event["exec_affects_target_group"] and event["leader_according_to_existing_birth_profile"],
                              "target-group exec or potential leader/TID migration")
                    else:
                        _need(lines == 1 and entry["logical_path"] == creator_uri, "unqualified unbound-actor exec")
                        event["exec_affects_target_group"] = "CONTEXT_ACTOR_AT_RECORDED_TARGET_BIRTH"
                events.append(event)
        _need((digest.hexdigest(), size) == (entry["raw_sha256"], entry["raw_bytes"]), "decoded receipt differs")
        file_rows.append({"entry": entry, "lines": lines, "calls": dict(calls), "raw_and_stored_sha_verified": True,
                          "coordinate_membership": member})
        if progress is not None and (number % 32 == 0 or number == len(selected_entries)):
            progress({"phase": "PROOF_RAW", "files": number, "lines": total_lines, "decoded_bytes": total_bytes})
    _need(file_rows == docs["projection_files"] and events == docs["projection_events"], "original proof records differ from independent replay")
    _need(dict(counts) == projection["non_main_interface_counts"] and dict(classes) == projection["scope"]["classifications"]
          and total_bytes == projection["scope"]["decoded_bytes"] and total_lines == projection["scope"]["lines"]
          and len(file_rows) == projection["scope"]["verified_non_main_files"], "original proof denominator differs")
    _need(set(counts) <= set(full) and all(counts[name] <= full[name] for name in counts)
          and sum(full.values()) == base.manifest["tables"]["observations"]["records"], "complement has no exact full-scope count authority")
    remaining = {name: full[name] - counts[name] for name in full}
    success = sum(row["syscall"] in ("execve", "execveat") and row["result"] == 0 for row in events)
    failure = sum(row["syscall"] in ("execve", "execveat") and row["result"] == -1 for row in events)
    _need(remaining.get("execve") == 1 and summary["nonreturn_protocol_counts"]["EXEC_IMAGE_REPLACED"] - success == 1
          and audit["failed_exec_receipts"] - failure == 0
          and all(full[name] == 0 for name in ("execveat", "unshare", "close_range")), "target context continuity not established")
    _need(context["target_exec_coordinate"] == coords["seed"]["target_exec"]
          and context["target_birth_coordinate"] == coords["seed"]["target_birth"], "small proof target anchors differ")
    target_births = [row for row in events if row["source"] == coords["seed"]["target_birth"]]
    _need(len(target_births) == 1 and target_births[0]["syscall"] in parser._CLONE
          and target_births[0]["result"] == base.manifest["protocol_document"]["contract"]["root_tid"]
          and target_births[0]["clone_flags"] is not None
          and "CLONE_FILES" not in target_births[0]["clone_flags"], "creator/target private birth is not qualified")
    birth = context["child_birth_r1"]
    resolved = base.resolve(base.selector("observations", birth["ordinal"]))
    _need(all(resolved[key] == birth[key] for key in ("record", "row_sha256", "ordinal", "locator")), "selected child birth original row differs")
    birth_row = resolved["record"]
    _need(birth_row["interface_record"] is True and birth_row["argument_rendering_complete"] is True
          and birth_row["syscall"] in parser._CLONE and type(birth_row["result"]) is int and birth_row["result"] > 0,
          "selected child birth result/flags unavailable")
    child_thread = threads.get(birth_row["result"])
    _need(child_thread is not None and child_thread == context["child_birth_coordinate"], "selected child coordinate differs")
    birth_artifact = artifacts[birth_row["source"]["artifact"]]
    birth_entry = by_actual[birth_artifact.uri]
    birth_source = _raw_fact(birth_entry, birth_row["source"]["line"])
    _need(birth_source == child_thread["source"], "birth source/namespace differs from retained coordinate")
    birth_flags = parser._clone_flags({"name": birth_row["syscall"], "args": [str(value) for value in birth_row["arguments"]]})
    _need(birth_flags is not None and "CLONE_FILES" not in birth_flags and "CLONE_THREAD" not in birth_flags,
          "selected pre-exec child does not have an independent table birth")
    groups = {}
    _need(len(r2.handles) <= limits.max_ports, "selected port budget exceeded")
    for identity, (ordinal, handle) in r2.handles.items():
        _need(type(handle.handle) is ProviderHandle and type(handle.handle.container) is Unresolved
              and type(handle.start) is EvidencePoint and handle.start.run == base.run.id,
              "R2 selected handle cannot be container-refined")
        selected = base.resolve(handle.handle.selector)
        row = selected["record"]
        artifact = artifacts[row["source"]["artifact"]]
        entry = by_actual[artifact.uri]
        line = row["source"]["line"]
        _need(handle.source == ProviderFactReference(artifact, "#/lines/" + str(line))
              and handle.start.source == handle.source
              and row["tid"] == int(PurePosixPath(entry["logical_path"]).name.rsplit(".", 1)[1]),
              "selected port source/actor differs")
        groups.setdefault(entry["logical_path"], []).append((line, ordinal, handle))
    _need(0 < len(groups) <= limits.max_contexts, "observed context budget exceeded")
    additions, changes, proofs = [], [], []
    old_changes = {decode(HandleBinding, row["replacement"]).id: row for row in r2.document["handle_refinements"]}
    for uri, ports in sorted(groups.items()):
        ports.sort(key=lambda row: (row[0], row[1]))
        first, last = ports[0][0], ports[-1][0]
        local_events = [row for row in events if row["source"]["artifact"]["uri"] == uri]
        switches = [row for row in local_events if first <= _line_number(row["source"]) <= last
                    and row["syscall"] in ("execve", "execveat", "unshare", "close_range") and row["result"] == 0]
        _need(not switches, "selected ports cross an unproven context transition")
        if uri == target["uri"]:
            _need(_line_number(coords["seed"]["target_exec"]) < first, "target port predates the sole witnessed exec")
            basis, witness = "TARGET_EXACT_COMPLEMENT", coords["seed"]["target_exec"]
        else:
            prior_execs = [row for row in local_events if row["syscall"] in ("execve", "execveat")
                           and row["result"] == 0 and _line_number(row["source"]) < first]
            if prior_execs:
                basis, witness = "POST_EXEC_OBSERVED_CONTEXT", prior_execs[-1]["source"]
            else:
                tid = int(PurePosixPath(uri).name.rsplit(".", 1)[1])
                _need(tid == child_thread["tid"], "pre-exec selected actor lacks a qualified nonshared birth witness")
                basis, witness = "PRIVATE_BIRTH_OBSERVED_CONTEXT", birth_source
        first_handle = ports[0][2]
        context_id = ResourceInstanceID("scar.os-fd-context:" + _sha({"run": encode(base.run.id),
            "first_observation": encode(first_handle.start), "basis": basis, "witness": witness}))
        resource = ResourceInstance(context_id, ResourceKind.OTHER, ResourceRole.HANDLE_TABLE,
            RunRealm(base.run.id), ImportedAt(first_handle.start), first_handle.source)
        _need(decode(ResourceInstance, encode(resource)) == resource, "typed observed resource codec changed its record")
        additions.append(resource)
        proofs.append({"resource": encode(context_id), "basis": basis, "witness": witness,
            "interval": {"artifact": _raw_fact(entries[uri], 1)["artifact"], "first_selected_line": first, "last_selected_line": last},
            "handles": [encode(row[2].id) for row in ports]})
        for line, ordinal, handle in ports:
            replacement = replace(handle, handle=replace(handle.handle, container=InstanceTarget(context_id)))
            _need(decode(HandleBinding, encode(replacement)) == replacement, "typed container codec changed its record")
            before, after = encode(handle), encode(replacement)
            _need({key: value for key, value in before.items() if key != "handle"} ==
                  {key: value for key, value in after.items() if key != "handle"}
                  and {key: value for key, value in before["handle"].items() if key != "container"} ==
                  {key: value for key, value in after["handle"].items() if key != "container"}, "noncontainer field changed")
            changes.append({"r1_preimage": old_changes[handle.id]["preimage"], "r2_record_sha256": _sha(before),
                            "replacement": after})
    added_ids = {row.id for row in additions}
    _need(len(added_ids) == len(additions), "observed context identities conflict")
    scanned_resources = 0
    for envelope in base.reader.iter_records("resources"):
        scanned_resources += 1
        _need(scanned_resources <= limits.max_base_resource_ids, "base resource ID check budget exceeded")
        _need(decode(ResourceInstanceID, envelope["record"]["id"]) not in added_ids, "context ID collides with an original resource")
    _need(scanned_resources == base.manifest["tables"]["resources"]["records"], "original resource ID scope incomplete")
    for name in names:
        _, current = _document(getattr(inputs, name), limits.max_metadata_bytes, receipts[name].schema)
        _need(current == receipts[name], "proof metadata changed during validation")
    _, current_r2 = _document(r2_manifest, limits.max_document_bytes, "scar.os-resource-refinement")
    _need(current_r2 == r2_receipt, "R2 artifact changed during proof validation")
    _, current_base = _document(base.reader.manifest_receipt["path"], limits.max_metadata_bytes, base.artifact.schema)
    _need(current_base == base_receipt, "base manifest changed during proof validation")
    return base, r2, receipts, additions, changes, proofs, {"exact_os_artifacts": len(entries),
        "verified_complement_artifacts": len(selected_entries), "complement_lines": total_lines,
        "complement_decoded_bytes": total_bytes, "complement_calls": sum(counts.values()),
        "base_resources_total": scanned_resources, "r2_base_resources_selected": len(r2.resources),
        "r2_handles_selected": len(r2.handles), "new_contexts_selected": len(additions),
        "handle_containers_refined": len(changes)}, r2_receipt


def _expected(prepared):
    base, r2, receipts, resources, changes, proofs, counts, r2_receipt = prepared
    return {"schema": SCHEMA, "schema_version": VERSION, "status": "PUBLISHED",
        "base": encode(base.artifact), "r2": encode(r2_receipt), "run": encode(base.run),
        "inputs": {name: encode(receipt) for name, receipt in receipts.items()},
        "context_resources": encode(tuple(resources)), "handle_refinements": changes, "context_proofs": proofs,
        "counts": counts, "scope": "selected R2 handles; existing base resources registry remains partial",
        "validation": {"r2_public_preimage_endpoint_validation": True, "typed_selected_record_codec_validation": True,
            "selected_context_fk_and_realm_validation": True, "base_resource_id_collision_scan": True,
            "full_execution_model_semantics": "OPEN: no complete ProgramSnapshot supplied"},
        "execution_capability_version": 9, "program_snapshot_created": False, "complete_execution_model": False,
        "whole_model_established": False, "first_stage_complete": False, "transformation_authorized": False}


class OSFDTableContexts:
    """One immutable selection over R2; registries are explicitly selected/partial."""
    def __init__(self):
        raise TypeError("use OSFDTableContexts.read with explicit bound inputs")

    @classmethod
    def _qualified(cls, prepared, document):
        _need(document == _expected(prepared), "published context refinement differs from independently qualified proof/selection")
        self = object.__new__(cls)
        self.base, self.r2 = prepared[:2]
        self.document = document
        self.context_resources = {decode(ResourceInstance, wire).id: decode(ResourceInstance, wire)
                                  for wire in document["context_resources"]}
        self.handles = {}
        for entry in document["handle_refinements"]:
            row = decode(HandleBinding, entry["replacement"])
            original = self.r2.handles[row.id][1]
            _need(type(row.handle.container) is InstanceTarget and row.handle.container.instance in self.context_resources,
                  "container has no exact selected context resource")
            target = self.context_resources[row.handle.container.instance]
            _need(target.realm == row.handle.namespace.realm == RunRealm(self.base.run.id)
                  and type(target.origin) is ImportedAt and target.origin.point.run == row.start.run
                  and target.kind is ResourceKind.OTHER and target.role is ResourceRole.HANDLE_TABLE,
                  "container role/origin/realm FK invalid")
            _need(_sha(encode(original)) == entry["r2_record_sha256"], "selected R2 preimage changed")
            self.handles[row.id] = row
        return self

    @classmethod
    def read(cls, base, r2_manifest, inputs, path, *, budgets=None, progress=None):
        limits = budgets or FDTableContextBudgets()
        document, _ = _document(path, limits.max_document_bytes, SCHEMA)
        return cls._qualified(_prepare(base, r2_manifest, inputs, limits, progress), document)

    def record(self, table, ordinal):
        """R2 public selection, with only an admitted handle.container replaced."""
        selected = self.r2.record(table, ordinal)
        if table != "handles":
            return selected
        row = decode(HandleBinding, selected["record"])
        replacement = self.handles.get(row.id)
        if replacement is None:
            return selected
        _need(self.r2.handles[row.id][0] == ordinal, "selected handle ordinal changed")
        return {**selected, "record": encode(replacement), "selection": "FD_TABLE_CONTAINER_REFINED",
                "r2_selection": selected["selection"]}

    def selected_resource(self, identity):
        """Missing here means unselected, never absence from the original model."""
        _need(type(identity) is ResourceInstanceID, "resource query requires the original typed ID")
        row = self.context_resources.get(identity)
        coverage = "SELECTED_CONTEXT" if row is not None else "R2_SELECTED_BASE"
        if row is None:
            row = self.r2.resources.get(identity)
        if row is None:
            coverage = "NOT_IN_SELECTED_REGISTRY"
        return {"coverage": coverage, "record": encode(row) if row is not None else None,
                "base_total": self.document["counts"]["base_resources_total"],
                "base_selected": self.document["counts"]["r2_base_resources_selected"],
                "contexts_selected": len(self.context_resources), "complete_registry": False}


def build_os_fd_table_contexts(base, r2_manifest, inputs, fresh_out, *, budgets=None, progress=None):
    limits = budgets or FDTableContextBudgets()
    prepared = _prepare(base, r2_manifest, inputs, limits, progress)
    document = _expected(prepared)
    OSFDTableContexts._qualified(prepared, document)  # Selected typed/FK checks, never a fake full model.
    encoding = BundleBudgets(max_record_bytes=limits.max_document_bytes,
        max_chunk_decoded_bytes=max(16_000_000, limits.max_document_bytes), max_manifest_bytes=limits.max_document_bytes)
    payload = _line(document, encoding)
    out = Path(fresh_out).absolute()
    out.mkdir(mode=0o700, parents=False, exist_ok=False)
    temporary = out / (".contexts." + secrets.token_hex(16) + ".tmp")
    with temporary.open("xb") as stream:
        stream.write(payload); stream.flush(); os.fsync(stream.fileno())
    os.link(temporary, out / "manifest.json"); temporary.unlink()
    return {"document": document, "manifest_receipt": {"path": str(out / "manifest.json"),
        "physical_sha256": hashlib.sha256(payload).hexdigest(), "physical_bytes": len(payload)}}


__all__ = ["FDTableContextInputs", "FDTableContextBudgets", "OSFDTableContexts", "build_os_fd_table_contexts"]
