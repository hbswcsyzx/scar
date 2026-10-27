"""Bounded positive source lookup over original OS provider records.

Routing is a heuristic, not proof of source order, uniqueness or absence.
No actor/TID/ordinal is a caller input.  No canonical graph is created here.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import secrets

from scar.ir.execution.resources import ProviderHandle
from scar.ir.program.providers import ProviderArtifact
from scar.ir.record_codec import decode, encode, loads as strict_loads
from scar.store.bundle_partitions import BundleBudgets, _line
from scar.trace.os_resource_refinement import OSResourceBase, OSResourceRefinement
from scar.trace.os_resources import _clone_flags


SCHEMA = "scar.os-source-lookup"
VERSION = 1
_RAW = "strace.syscalls.text.v1"


@dataclass(frozen=True)
class OSSourceLookupBudgets:
    max_queries: int = 8
    max_lookup_decoded_bytes: int = 64_000_000
    max_metadata_bytes: int = 2_000_000
    max_document_bytes: int = 4_000_000
    max_ports: int = 128
    max_artifacts: int = 512

    def __post_init__(self):
        _need(all(type(value) is int and value > 0 for value in vars(self).values()), "budgets must be positive integers")


def _need(value, message):
    if not value:
        raise ValueError("OS source lookup: " + message)


def _document(path, maximum):
    path = Path(path).absolute()
    _need(path.is_file() and not path.is_symlink(), "explicit input file absent or symlinked")
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    _need(len(raw) <= maximum, "input metadata budget exceeded")
    value = strict_loads(raw.decode("utf-8"))
    declared = value.get("schema") if type(value) is dict else None
    schema = declared if type(declared) is str and declared else "application/json"
    return value, {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "schema": schema}


def _source(entry, line):
    return {"artifact": {"uri": entry["logical_path"], "sha256": entry["raw_sha256"],
        "size_bytes": entry["raw_bytes"], "schema": _RAW}, "locator": "#/lines/" + str(line)}


def _number(source):
    match = re.fullmatch(r"#/lines/([1-9][0-9]*)", source["locator"])
    _need(match is not None, "source is not an exact original physical line")
    return int(match[1])


def _same_receipt(receipt, expected):
    return all(receipt[key] == expected[key] for key in ("path", "sha256", "bytes"))


def _native_tid(entry):
    match = re.fullmatch(r"syscalls\.([1-9][0-9]*)", PurePosixPath(entry["logical_path"]).name)
    _need(match is not None, "unsupported per-native-TID provider selector")
    return int(match[1])


def find_os_birth_witnesses(base, r2_manifest, *, archive, coordinates, context_events, budgets=None, progress=None):
    """Discover all selected actor birth demands; qualify only exact positive hits.

    ``context_events`` supplies original successful exec facts for need routing;
    it cannot authorize a match.  Every match resolves an exact original row.
    """
    limits = budgets or OSSourceLookupBudgets()
    _need(type(base) is OSResourceBase and type(limits) is OSSourceLookupBudgets, "explicit original base/budgets required")
    inputs = {}
    base_wire, base_receipt = _document(base.reader.manifest_receipt["path"], limits.max_metadata_bytes)
    _need(base_wire == base.manifest and base_receipt["sha256"] == base.artifact.sha256
          and base_receipt["bytes"] == base.artifact.size_bytes, "original base manifest changed")
    archive_doc, inputs["archive"] = _document(archive, limits.max_metadata_bytes)
    coords, inputs["coordinates"] = _document(coordinates, limits.max_metadata_bytes)
    exec_events, inputs["context_events"] = _document(context_events, limits.max_metadata_bytes)
    r2_wire, inputs["r2_manifest"] = _document(r2_manifest, limits.max_document_bytes)
    r2 = OSResourceRefinement.read(base, r2_manifest, max_bytes=limits.max_document_bytes)
    _need(r2_wire == r2.document and len(r2.handles) <= limits.max_ports, "R2 changed or selected port budget exceeded")
    _need(coords.get("schema") == "scar.capture-coordinates" and coords.get("schema_version") == 1
          and coords.get("profile") == "RETAINED_COLLECTOR_PROCESS_MEMBERSHIP_V1", "unsupported coordinate profile")
    _need(coords["run"] == encode(base.run) and coords["seed"]["archive_sha256"] == inputs["archive"]["sha256"],
          "archive/coordinates/base belong to different captures")
    binding = base.manifest["protocol_document"]["contract"]["coordinate_binding"]
    _need((binding["uri"], binding["sha256"], binding["size_bytes"]) ==
          (inputs["coordinates"]["path"], inputs["coordinates"]["sha256"], inputs["coordinates"]["bytes"]),
          "original base binds another coordinate artifact")
    _need(type(exec_events) is list, "context events must be explicit provider event records")
    entries, actual = {}, {}
    original = PurePosixPath(coords["original_root"])
    for entry in archive_doc["files"]:
        logical, local = PurePosixPath(entry["logical_path"]), PurePosixPath(entry["actual_path"])
        _need(logical.is_absolute() and local.is_absolute() and ".." not in logical.parts and ".." not in local.parts
              and logical.is_relative_to(original) and local.is_relative_to(original), "archive member escapes original namespace")
        _need(entry["logical_path"] not in entries and entry["actual_path"] not in actual, "ambiguous exact retention mapping")
        entries[entry["logical_path"]] = entry; actual[entry["actual_path"]] = entry
    artifacts, logical_index, actual_index = [], {}, {}
    for envelope in base.reader.iter_records("artifacts"):
        _need(len(artifacts) < limits.max_artifacts, "source artifact budget exceeded")
        artifact = decode(ProviderArtifact, envelope["record"])
        _need(artifact.uri in actual, "R1 artifact lacks its exact retained actual URI")
        entry = actual[artifact.uri]
        _need((artifact.sha256, artifact.size_bytes, artifact.schema) ==
              (entry["raw_sha256"], entry["raw_bytes"], _RAW)
              and entry["logical_path"] not in logical_index and artifact.uri not in actual_index,
              "R1/raw source namespace differs or is ambiguous")
        index = len(artifacts)
        artifacts.append(artifact); logical_index[entry["logical_path"]] = index; actual_index[artifact.uri] = index
    _need(len(artifacts) == base.manifest["tables"]["artifacts"]["records"] == coords["counts"]["os_artifacts"],
          "source artifact denominator incomplete")
    threads = {row["tid"]: row for row in coords["threads"]}
    _need(len(threads) == len(coords["threads"]), "native thread selectors ambiguous")
    members = {}
    for row in coords["membership"]:
        if row["artifact"]["schema"] == _RAW:
            _need(row["artifact"]["uri"] not in members, "native artifact membership ambiguous")
            members[row["artifact"]["uri"]] = row
    groups, anchors = {}, {}
    for identity, (handle_ordinal, handle) in r2.handles.items():
        _need(type(handle.handle) is ProviderHandle and handle.source.artifact.uri in actual_index,
              "selected handle source is outside the exact original provider namespace")
        index = actual_index[handle.source.artifact.uri]
        entry = actual[handle.source.artifact.uri]
        line = _number(encode(handle.source))
        native_tid = _native_tid(entry)  # Declared native selector, never a TGID inference.
        thread = threads.get(native_tid)
        if thread is not None:
            member = members.get(entry["logical_path"])
            _need(member is not None and member["artifact"] == _source(entry, line)["artifact"]
                  and member["local_path"] == entry["actual_path"] and member["thread"] == thread["id"]
                  and member["process"] == thread["process"] and handle.start.process is not None
                  and handle.start.process.wire == member["process"]["wire"], "selected native membership differs")
        group = groups.setdefault(entry["logical_path"], {"artifact": _source(entry, line)["artifact"],
            "native_tid": native_tid, "handles": [], "first_selected_line": line, "last_selected_line": line})
        group["handles"].append(encode(identity))
        group["first_selected_line"] = min(group["first_selected_line"], line)
        group["last_selected_line"] = max(group["last_selected_line"], line)
        anchors.setdefault(index, set()).add((line, handle.handle.selector.ordinal))
    needs, frontiers = [], []
    for logical, group in sorted(groups.items()):
        thread = threads.get(group["native_tid"])
        if thread is None:
            frontiers.append({"group": logical, "reason": "NO_OWN_BIRTH_COORDINATE", "absence_claimed": False})
            continue
        source = thread["source"]
        _need(source["artifact"]["uri"] in logical_index, "birth source lacks an exact original R1 artifact mapping")
        index = logical_index[source["artifact"]["uri"]]
        entry = entries[source["artifact"]["uri"]]
        _need(source["artifact"] == _source(entry, 1)["artifact"], "birth source raw receipt differs")
        prior_execs = []
        for event in exec_events:
            if event["syscall"] in ("execve", "execveat") and event["result"] == 0:
                fact = event["source"]
                _need(fact["artifact"]["uri"] in logical_index and fact["artifact"] ==
                      _source(entries[fact["artifact"]["uri"]], 1)["artifact"], "exec routing hint source is outside original capture")
                if fact["artifact"]["uri"] == logical and _number(fact) < group["first_selected_line"]:
                    prior_execs.append(fact)
        target_exec = coords["seed"]["target_exec"]
        if target_exec["artifact"]["uri"] == logical and _number(target_exec) < group["first_selected_line"]:
            prior_execs.append(target_exec)
        needs.append({"group": logical, "child_thread": thread, "birth_source": source,
            "source_artifact_index": index, "source_line": _number(source),
            "consumer_need": "POST_EXEC_ANCHOR_ALREADY_AVAILABLE" if prior_execs else "PRE_EXEC_BIRTH_REQUIRED"})
    queries, matches, memo = [], [], {}
    charged = 0

    def query(ordinal, need, route):
        nonlocal charged
        if ordinal in memo:
            return memo[ordinal]
        if not 0 <= ordinal < base.manifest["tables"]["observations"]["records"] or len(queries) >= limits.max_queries:
            return None
        selector = base.selector("observations", ordinal)
        chunk_index = int(selector.chunk.locator.rsplit("/", 1)[1])
        amount = base.manifest["tables"]["observations"]["chunks"][chunk_index]["decoded_bytes"]
        _need(type(amount) is int and amount >= 0, "chunk byte charge invalid")
        if charged + amount > limits.max_lookup_decoded_bytes:
            return None
        charged += amount  # Conservative per-call charge; no assumptions about cache residency.
        resolved = base.resolve(selector)
        memo[ordinal] = resolved
        queries.append({"need_source": need["birth_source"], "route": route, "selector": encode(selector),
            "actual_source": resolved["record"].get("source"), "row_sha256": resolved["row_sha256"],
            "locator": resolved["locator"], "declared_decoded_bytes_charged": amount})
        if progress is not None:
            progress({"phase": "OS_SOURCE_QUERY", "queries": len(queries), "charged_decoded_bytes": charged})
        return resolved

    for need in sorted(needs, key=lambda row: (row["consumer_need"] != "PRE_EXEC_BIRTH_REQUIRED", row["group"])):
        candidates = sorted(anchors.get(need["source_artifact_index"], ()), key=lambda pair: abs(pair[0]-need["source_line"]))
        planned = [(ordinal + need["source_line"] - line, {"kind": "SPARSE_ANCHOR_LINE_DELTA",
            "anchor_line": line, "anchor_ordinal": ordinal}) for line, ordinal in candidates]
        low, high = 0, base.manifest["tables"]["observations"]["records"] - 1
        found, attempted = False, set()
        while len(queries) < limits.max_queries:
            if planned:
                ordinal, route = planned.pop(0)
            elif low <= high:
                ordinal, route = (low + high)//2, {"kind": "SOURCE_ORDER_BINARY_HINT_ONLY"}
            else:
                break
            if ordinal in attempted:
                if not planned:
                    break
                continue
            attempted.add(ordinal)
            resolved = query(ordinal, need, route)
            if resolved is None:
                break
            row = resolved["record"]
            expected = {"artifact": need["source_artifact_index"], "line": need["source_line"]}
            actual_source = row.get("source")
            if actual_source == expected:
                flags = _clone_flags({"name": row["syscall"], "args": [str(value) for value in row.get("arguments", ())]})
                parent_uri = need["birth_source"]["artifact"]["uri"]
                parent_tid = _native_tid(entries[parent_uri])
                parent_member = members.get(parent_uri)
                parent_process = parent_member["process"]["wire"] if parent_member is not None else None
                creator_context = (parent_uri == coords["seed"]["target_birth"]["artifact"]["uri"]
                    and any(frontier.get("code") == "os_actor_not_connected_to_target_ancestry"
                            and frontier.get("tid") == parent_tid for frontier in coords["open"]))
                qualified = (row.get("syscall") in ("clone", "clone3", "fork", "vfork")
                    and row.get("result") == need["child_thread"]["tid"]
                    and row.get("tid") == parent_tid and row.get("process") == parent_process
                    and (parent_member is not None or creator_context)
                    and row.get("argument_rendering_complete") is True and flags is not None)
                if qualified:
                    matches.append({"need": need, "selector": encode(base.selector("observations", ordinal)),
                        "record": row, "ordinal": ordinal, "row_sha256": resolved["row_sha256"],
                        "locator": resolved["locator"], "verification": resolved["verification"], "clone_flags": flags,
                        "global_observation_source_uniqueness": "NOT_CLAIMED"})
                    found = True
                else:
                    frontiers.append({"group": need["group"], "reason": "SOURCE_MATCH_BIRTH_CONTRACT_UNQUALIFIED", "absence_claimed": False})
                break
            if type(actual_source) is not dict or any(type(actual_source.get(key)) is not int for key in ("artifact", "line")):
                break
            # A bad hint may skip a valid answer; misses never establish absence.
            if (actual_source["artifact"], actual_source["line"]) < (expected["artifact"], expected["line"]):
                low = max(low, ordinal + 1)
            else:
                high = min(high, ordinal - 1)
        if not found:
            frontiers.append({"group": need["group"], "reason": "LOOKUP_BUDGET_OR_HEURISTIC_FRONTIER", "absence_claimed": False})
    report = {"schema": SCHEMA, "schema_version": VERSION, "producer": "AUTOMATIC_SOURCE_LOOKUP",
        "run": encode(base.run), "base": encode(base.artifact), "inputs": inputs,
        "groups": list(groups.values()), "needs": needs, "matches": matches, "queries": queries, "frontiers": frontiers,
        "counts": {"selected_ports": len(r2.handles), "groups": len(groups), "birth_needs": len(needs),
            "preexec_birth_needs": sum(row["consumer_need"] == "PRE_EXEC_BIRTH_REQUIRED" for row in needs),
            "positive_matches": len(matches), "queries": len(queries), "lookup_decoded_bytes_charged": charged},
        "source_order_proved": False, "source_uniqueness_proved": False, "absence_claimed": False,
        "full_execution_model_semantics": "OPEN", "first_stage_complete": False}
    for name, path in (("archive", archive), ("coordinates", coordinates), ("context_events", context_events), ("r2_manifest", r2_manifest)):
        _, current = _document(path, limits.max_document_bytes if name == "r2_manifest" else limits.max_metadata_bytes)
        _need(current == inputs[name], "source lookup input bytes changed during discovery")
    _, current_base = _document(base.reader.manifest_receipt["path"], limits.max_metadata_bytes)
    _need(current_base == base_receipt, "original base changed during discovery")
    return report


def _publish(path, value, limits):
    encoding = BundleBudgets(max_record_bytes=limits.max_document_bytes,
        max_chunk_decoded_bytes=max(16_000_000, limits.max_document_bytes), max_manifest_bytes=limits.max_document_bytes)
    payload = _line(value, encoding)
    temporary = path.parent / ("." + path.name + "." + secrets.token_hex(16) + ".tmp")
    with temporary.open("xb") as stream:
        stream.write(payload); stream.flush(); os.fsync(stream.fileno())
    os.link(temporary, path); temporary.unlink()
    return {"path": str(path), "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}


def prepare_fd_context_evidence(base, r2_manifest, *, archive, coordinates, r1_summary,
                                projection_summary, projection_files, context_events, fresh_out,
                                budgets=None, progress=None):
    """Discover and publish the old consumer's witness, or explicit capability frontier.

    Zero/multiple required pre-exec births are not filled with unrelated rows.
    The existing FD consumer independently checks this fresh evidence again.
    """
    limits = budgets or OSSourceLookupBudgets()
    _need(type(limits) is OSSourceLookupBudgets, "explicit lookup budgets required")
    out = Path(fresh_out).absolute()
    _need(not out.exists(), "output must be fresh")
    lookup = find_os_birth_witnesses(base, r2_manifest, archive=archive, coordinates=coordinates,
        context_events=context_events, budgets=limits, progress=progress)
    coords, coords_receipt = _document(coordinates, limits.max_metadata_bytes)
    summary, summary_receipt = _document(r1_summary, limits.max_metadata_bytes)
    projection, projection_receipt = _document(projection_summary, limits.max_metadata_bytes)
    files, files_receipt = _document(projection_files, limits.max_metadata_bytes)
    _need(summary == base.manifest["summary"] and projection.get("schema") == "scar.fd-table-complement-projection"
          and projection.get("schema_version") == 1 and projection["run"] == encode(base.run), "projection/summary scope differs")
    _need(_same_receipt(coords_receipt, lookup["inputs"]["coordinates"]), "coordinates changed after discovery")
    for name, receipt in (("archive", lookup["inputs"]["archive"]), ("coordinates", coords_receipt), ("summary", summary_receipt)):
        _need(_same_receipt(receipt, projection["inputs"][name]), "projection original input receipts differ")
    _need(projection["inputs"]["manifest"]["sha256"] == base.artifact.sha256,
          "projection uses another original R1")
    file_entries = [row["entry"] for row in files]
    _need(len(file_entries) == projection["scope"]["verified_non_main_files"]
          and len({row["logical_path"] for row in file_entries}) == len(file_entries), "projection file receipt scope differs")
    required = [row for row in lookup["needs"] if row["consumer_need"] == "PRE_EXEC_BIRTH_REQUIRED"]
    preparation_frontiers = []
    chosen = None
    if len(required) != 1:
        preparation_frontiers.append({"reason": "CONSUMER_V1_REQUIRES_ONE_PREEXEC_WITNESS", "actual_required": len(required)})
    else:
        candidates = [row for row in lookup["matches"] if row["need"] == required[0]]
        if len(candidates) != 1:
            preparation_frontiers.append({"reason": "REQUIRED_PREEXEC_BIRTH_NOT_POSITIVELY_RESOLVED"})
        else:
            chosen = candidates[0]
            if "CLONE_FILES" in chosen["clone_flags"] or "CLONE_THREAD" in chosen["clone_flags"]:
                preparation_frontiers.append({"reason": "CONSUMER_V1_SHARED_PREEXEC_CONTEXT_UNSUPPORTED"})
                chosen = None
    out.mkdir(mode=0o700, parents=False, exist_ok=False)
    lookup_receipt = _publish(out / "lookup.json", lookup, limits)
    evidence_receipt = None
    if chosen is not None and not preparation_frontiers:
        # Do not grant authority to a prior report boolean: resolve its original slot again.
        selector = base.selector("observations", chosen["ordinal"])
        actual = base.resolve(selector)
        _need(all(actual[key] == chosen[key] for key in ("record", "ordinal", "row_sha256", "locator")),
              "chosen source record changed before publication")
        evidence = {"schema": "scar.fd-table-context-read-review", "schema_version": 1,
            "producer": {"kind": "AUTOMATIC_SOURCE_LOOKUP", "lookup_schema": SCHEMA,
                         "lookup_schema_version": VERSION, "lookup_receipt": lookup_receipt},
            "run": coords["run"]["id"], "inputs": {"archive": lookup["inputs"]["archive"],
                "coordinates": coords_receipt, "summary": summary_receipt,
                "r1_manifest": {"path": base.artifact.uri, "sha256": base.artifact.sha256, "bytes": base.artifact.size_bytes},
                "r2_manifest": lookup["inputs"]["r2_manifest"]},
            "target_exec_coordinate": coords["seed"]["target_exec"], "target_birth_coordinate": coords["seed"]["target_birth"],
            "child_birth_r1": {key: actual[key] for key in ("record", "ordinal", "row_sha256", "locator", "verification")},
            "child_birth_coordinate": chosen["need"]["child_thread"],
            "upstream_birth_source_discovery": "AUTOMATIC_POSITIVE_EXACT_LOOKUP",
            "source_uniqueness_proved": False, "full_execution_model_semantics": "OPEN", "first_stage_complete": False}
        evidence_receipt = _publish(out / "context-evidence.json", evidence, limits)
    report = {"schema": "scar.fd-context-evidence-preparation", "schema_version": 1,
        "status": "PUBLISHED_WITNESS" if evidence_receipt is not None else "CONSUMER_FRONTIER",
        "producer": "AUTOMATIC_SOURCE_LOOKUP", "lookup_receipt": lookup_receipt, "context_evidence": evidence_receipt,
        "projection_receipts": {"summary": projection_receipt, "files": files_receipt},
        "counts": lookup["counts"], "frontiers": lookup["frontiers"] + preparation_frontiers,
        "all_needs_reported": True, "full_execution_model_semantics": "OPEN", "first_stage_complete": False}
    report_receipt = _publish(out / "preparation-report.json", report, limits)
    return {**report, "report_receipt": report_receipt}


__all__ = ["OSSourceLookupBudgets", "find_os_birth_witnesses", "prepare_fd_context_evidence"]
