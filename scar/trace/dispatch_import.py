"""Decode production dispatch slots into the existing native evidence bundle.

Markers identify exact provider observations. Their actual ctrl_deps path is
retained; a dispatch callback is never promoted to a direct Python/ATen call.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re

from scar.ir.v2 import EvidenceClaim, EvidenceKind, ObjectID, ObjectInstance
from scar.ir.v2.evidence import EvidenceEdge, EvidenceEndpoint, EvidenceNodeKind as N, EvidenceRelation
from scar.ir.program.providers import ProviderArtifact
from scar.ir.record_codec import decode, encode
from scar.trace.dispatch_evidence import PRODUCTION_PROFILE, PROVIDER_REVISION
from scar.trace.files import open_binary, resolve as resolve_retained_path
from scar.trace.native_import import _canonical_hash, _constant, _float, _pairs

_MARKER = re.compile(r"scar-dispatch:([0-9a-f]{32}):([1-9][0-9]*):([1-9][0-9]*):(span|output)")
_WEAK = re.compile(r"weak:([1-9][0-9]*):([1-9][0-9]*)")


def _retained_artifact(coordinates, actual_path, raw_sha256, raw_bytes, schema):
    """Resolve an explicitly read local file to its original declared artifact.

    A content hash alone cannot select between distinct retained files. New
    coordinate reports publish local_path separately from the logical URI;
    historical reports require an exact URI/path match instead. No URI opens
    a file, no basename/selector inference participates in this lookup.
    """
    if coordinates is None:
        return ProviderArtifact(str(Path(actual_path).absolute()), raw_sha256, raw_bytes, schema)
    local_path = str(Path(actual_path).resolve())
    matches = []
    for member in coordinates.report["membership"]:
        declared = decode(ProviderArtifact, member["artifact"])
        selected_path = member.get("local_path", declared.uri)
        if (selected_path == local_path and declared.sha256 == raw_sha256
                and declared.size_bytes == raw_bytes):
            matches.append(declared)
    if len(matches) != 1:
        raise ValueError("dispatch input has no unique exact retained path/raw-byte membership")
    return matches[0]


def import_dispatch_bridge(result, observations_path, metadata_path, call_events_path,
                           call_codes_path, call_meta_path, *, native_manifest_path,
                           coordinates=None, max_bytes=512000000, max_events=400000):
    """Append exact Object→ProviderReference associations; return result.

    Every opened path is an explicit caller argument. Metadata paths select no
    external files. Missing context/weak identity/slot qualification remains a
    gap; contradictory marker identities or byte receipts are rejected.
    """
    if any(type(value) is not int or value < 1 for value in (max_bytes, max_events)):
        raise ValueError("dispatch import budgets must be positive exact integers")
    if result.report["provider_revision"] != PROVIDER_REVISION:
        raise ValueError("unsupported dispatch provider revision")
    if "dispatch_bridge" in result.report:
        raise ValueError("this native bundle already has a dispatch bridge")
    documents, artifacts, lines, input_paths, remaining = {}, {}, {}, {}, max_bytes
    for key, path, schema in (
        ("observations", observations_path, "scar.dispatch-observation.events.v1"),
        ("metadata", metadata_path, "scar.dispatch-observation-trace"),
        ("calls", call_events_path, "scar.call-edge-events.v1"),
        ("codes", call_codes_path, "scar.call-edge-codes.v1"),
        ("call_meta", call_meta_path, "scar.call-edge-trace"),
        ("native_meta", native_manifest_path, "scar.execution-evidence-collection")):
        actual_path = resolve_retained_path(path).resolve()
        input_paths[key] = str(actual_path)
        with open_binary(actual_path) as stream:
            payload = stream.read(remaining + 1)
        if len(payload) > remaining:
            raise ValueError("dispatch import exceeds combined raw byte budget")
        remaining -= len(payload)
        artifact = _retained_artifact(coordinates, actual_path if coordinates is not None else path,
                                      sha256(payload).hexdigest(), len(payload), schema)
        artifacts[key] = artifact
        def decode(raw):
            return json.loads(raw, object_pairs_hook=_pairs, parse_float=_float, parse_constant=_constant)
        if key in ("observations", "calls", "codes"):
            numbered = [(number, raw) for number, raw in enumerate(payload.splitlines(), 1) if raw.strip()]
            if key == "observations" and len(numbered) > max_events:
                raise ValueError("dispatch observation event budget exceeded")
            documents[key] = [decode(raw) for _, raw in numbered]
            lines[key] = [number for number, _ in numbered]
        else:
            documents[key] = decode(payload)
    meta, native, call_meta = documents["metadata"], documents["native_meta"], documents["call_meta"]
    pid, nonce = meta.get("process_id"), meta.get("nonce")
    if (meta.get("schema") != "scar.dispatch-observation-trace" or meta.get("schema_version") != 1
            or meta.get("profile") != PRODUCTION_PROFILE or meta.get("provider_revision") != PROVIDER_REVISION
            or type(pid) is not int or pid != result.report["pid"]
            or type(nonce) is not str or re.fullmatch(r"[0-9a-f]{32}", nonce) is None):
        raise ValueError("dispatch producer profile/process/nonce mismatch")
    declaration, native_declaration = meta.get("file", {}), meta.get("native_manifest", {})
    for declaration_item, key in ((declaration, "observations"), (native_declaration, "native_meta")):
        if (declaration_item.get("raw_sha256"), declaration_item.get("raw_bytes")) != (
                artifacts[key].sha256, artifacts[key].size_bytes):
            raise ValueError("dispatch producer exact raw receipt mismatch: " + key)
    if (declaration.get("lines") != len(documents["observations"])
            or meta.get("events") != len(documents["observations"])
            or meta.get("bytes") != artifacts["observations"].size_bytes):
        raise ValueError("dispatch producer event/byte count mismatch")
    dispatch_config = native.get("configuration", {}).get("dispatch_observations", {})
    if (native.get("schema") != "scar.execution-evidence-collection" or native.get("schema_version") != 1
            or native.get("pid") != pid or native.get("status") != "CLOSED" or native.get("failures") != []
            or native.get("provider", {}).get("torch_git_version") != PROVIDER_REVISION
            or dispatch_config.get("profile") != PRODUCTION_PROFILE or dispatch_config.get("started") is not True
            or dispatch_config.get("events") != declaration.get("path")
            or Path(dispatch_config.get("metadata", "")).name != Path(metadata_path).name.removesuffix(".gz")):
        raise ValueError("native receipt does not bind this production dispatch collector")
    for family, native_key in (("execution_trace", "eto"), ("kineto", "kineto")):
        item = native.get("artifacts", {}).get(family, {})
        actual = result.report["artifacts"].get(native_key)
        expected_name = ("execution-trace" if family == "execution_trace" else "kineto") + f".{pid}.{nonce}.json"
        if (actual is None or Path(item.get("path", "")).name != expected_name
                or Path(actual["path"]).name.removesuffix(".gz") != expected_name
                or item.get("size_bytes") != actual["size_bytes"]):
            raise ValueError("native artifact differs from the dispatch nonce capture")
    if (call_meta.get("schema") != "scar.call-edge-trace" or call_meta.get("schema_version") != 1
            or call_meta.get("process_id") != pid or call_meta.get("events") != len(documents["calls"])
            or call_meta.get("codes") != len(documents["codes"])):
        raise ValueError("call collector schema/process/count mismatch")
    codes, entries, exits, indices = {}, {}, {}, set()
    for row in documents["codes"]:
        if type(row) is not dict or row.get("key") in codes:
            raise ValueError("invalid/duplicate call code")
        codes[row["key"]] = row
    for number, row in zip(lines["calls"], documents["calls"], strict=True):
        if (type(row) is not dict or row.get("process_id") != pid
                or type(row.get("index")) is not int or row["index"] in indices):
            raise ValueError("invalid/duplicate call event")
        indices.add(row["index"])
        if row.get("kind") == "call_enter":
            if row.get("invocation_id") in entries or row.get("code") not in codes:
                raise ValueError("duplicate/unbound retained entry")
            entries[row["invocation_id"]] = (number, row)
        elif row.get("kind") == "call_exit":
            exits[row["invocation_id"]] = row["index"]
    membership_verified = coordinates is not None
    if coordinates is not None:
        for artifact in artifacts.values():
            if coordinates.process_for(artifact, pid) != coordinates.target_process:
                raise ValueError("dispatch/call artifact lacks verified capture membership")
        native_artifact = result.report["artifacts"]["eto"]
        provider = _retained_artifact(coordinates, resolve_retained_path(native_artifact["path"]).resolve(),
            native_artifact["sha256"], native_artifact["size_bytes"], "pytorch.execution-trace.v1")
        if coordinates.process_for(provider, pid) != coordinates.target_process:
            raise ValueError("native graph belongs to a different capture")
    evidence, values = result.bundle.evidence, result.bundle.values
    native_nodes = {instance.metadata["node_id"]: instance for instance in evidence.instances.values()
                    if instance.metadata.get("provider") == "ETO"}
    marker_nodes = {}
    for instance in native_nodes.values():
        name = result.bundle.semantic.definitions[instance.definition].label
        if name.startswith(f"scar-dispatch:{nonce}:"):
            if name in marker_nodes:
                raise ValueError("duplicate production marker node")
            marker_nodes[name] = instance
    scope = "dispatch-reference:" + _canonical_hash({"native_scope": result.report["scope"],
        "profile": PRODUCTION_PROFILE, "artifacts": {key: artifact.sha256 for key, artifact in artifacts.items()}})
    grouped, gaps, paths, observations, consumed = {}, Counter(), [], [], set()
    pending_objects, pending_edges = {}, []
    def pointer(key, suffix):
        return "sha256:" + artifacts[key].sha256 + suffix
    for number, row in zip(lines["observations"], documents["observations"], strict=True):
        if type(row) is not dict or row.get("process_id") != pid or type(row.get("sequence")) is not int:
            raise ValueError("invalid dispatch event process/sequence")
        sequence, kind = row["sequence"], row.get("kind")
        group = grouped.setdefault(sequence, {})
        if kind not in ("DISPATCH_BEGIN", "DISPATCH_OUTPUT", "DISPATCH_END") or kind in group:
            raise ValueError("invalid/duplicate dispatch event kind")
        group[kind] = row
        if kind == "DISPATCH_END":
            continue
        match = _MARKER.fullmatch(row.get("marker", ""))
        phase = "span" if kind == "DISPATCH_BEGIN" else "output"
        if match is None or match.groups() != (nonce, str(pid), str(sequence), phase):
            raise ValueError("dispatch marker identity mismatch")
        marker = marker_nodes.get(row["marker"])
        if marker is None:
            gaps["marker_enter_not_retained"] += 1; continue
        consumed.add(row["marker"])
        observation = row.get("observation", {})
        if observation.get("process_id") != pid or type(observation.get("native_tid")) is not int:
            raise ValueError("dispatch thread observation missing")
        native_tid_verified = marker.metadata.get("kineto_reference") is not None
        if native_tid_verified:
            if (marker.metadata.get("raw_pid") != pid
                    or marker.metadata.get("raw_tid") != observation["native_tid"]):
                raise ValueError("actual RF-correlated Kineto host thread differs from dispatch observation")
        else:
            gaps["marker_host_native_tid_unverified"] += 1
        context = observation.get("context")
        if context is None:
            gaps["retained_ancestor_missing"] += 1
        else:
            found = entries.get(context.get("invocation"))
            if found is None:
                raise ValueError("dispatch retained ancestor is absent")
            entry_number, entry = found
            if (context.get("kind") != "retained ancestor context, not a proven direct caller"
                    or context.get("code") != entry["code"]
                    or context.get("source_file") != codes[entry["code"]]["filename"]
                    or observation.get("python_ident") != entry["thread_id"]
                    or type(context.get("bytecode_offset")) is not int or context["bytecode_offset"] < 0
                    or type(observation.get("call_event_index")) is not int
                    or not entry["index"] <= observation["call_event_index"] < exits.get(entry["invocation_id"], float("inf"))):
                raise ValueError("dispatch retained ancestor/context is contradictory")
        slots = [slot for slot in marker.metadata.get("tensor_slots", ()) if slot["role"] == "inputs"]
        leaves = observation.get("tensor_references")
        if (type(leaves) is not list or len(leaves) != len(slots)
                or [slot["ordered_path"] for slot in slots] != [[i] for i in range(len(slots))]):
            raise ValueError("dispatch marker does not contain the exact flattened Tensor slots")
        ancestry, current, seen = [], marker, set()
        while current is not None and current.id not in seen:
            seen.add(current.id)
            ancestry.append({"instance": current.id.wire, "node_id": current.metadata["node_id"],
                "rf_id": current.metadata["rf_id"], "ctrl_deps": current.metadata["ctrl_deps"],
                "raw_reference": current.metadata["raw_reference"]})
            parent = current.metadata["ctrl_deps"]
            current = native_nodes.get(parent) if parent != current.metadata["node_id"] else None
        observations.append({"sequence": sequence, "phase": phase, "marker_instance": marker.id.wire,
            "retained_ancestor": context, "python_ident": observation["python_ident"],
            "native_tid": observation["native_tid"], "native_tid_verified": native_tid_verified,
            "actual_provider_ancestry": ancestry})
        seen_paths = set()
        for ordinal, (leaf, slot) in enumerate(zip(leaves, slots, strict=True)):
            weak = _WEAK.fullmatch(leaf.get("ref", ""))
            path = leaf.get("path")
            if type(path) is not list or any(type(part) not in (int, str) for part in path):
                raise ValueError("invalid exact Tensor payload path")
            if tuple(path) in seen_paths:
                raise ValueError("duplicate Tensor payload path")
            seen_paths.add(tuple(path))
            if weak is None or int(weak[1]) != pid or leaf.get("identity_qualified") is not True:
                gaps["weak_reference_unqualified"] += 1; continue
            identifier = ObjectID(scope + ":" + leaf["ref"])
            claim = EvidenceClaim(EvidenceKind.INFERRED, (
                pointer("observations", f"#line/{number}"), pointer("metadata", "#"),
                pointer("native_meta", "#"), slot["raw_reference"]), scope=scope,
                assumptions=("fixed production collector passed the same held Tensor to this exact marker argument",
                    "association is local to this observation; no persistent content/storage identity",
                    "retained ancestor is not a direct caller",
                    "capture membership verified" if membership_verified else "caller supplied these artifacts as one capture"))
            if identifier not in values.objects and identifier not in pending_objects:
                pending_objects[identifier] = ObjectInstance(identifier, scope, (claim,), metadata={
                    "weak_token": leaf["ref"], "process_id": pid, "lifetime": "UNKNOWN",
                    "identity_basis": "existing call recorder weak-reference epoch"})
            edge_id = scope + f":slot:{number}:{ordinal}"
            pending_edges.append(EvidenceEdge(edge_id, EvidenceRelation.OBJECT_REFERENCE_ASSOCIATION,
                EvidenceEndpoint(N.OBJECT, identifier), EvidenceEndpoint(N.PROVIDER_REFERENCE, slot["provider_reference"]), claim))
            paths.append({"edge_id": edge_id, "sequence": sequence, "phase": phase,
                "original_payload_path": path, "provider_argument_ordinal": ordinal,
                "provider_role": "inputs", "marker_instance": marker.id.wire})
        if row.get("slot_gaps"):
            gaps["unqualified_payload_slots"] += len(row["slot_gaps"])
    for sequence, group in grouped.items():
        end = group.get("DISPATCH_END")
        if "DISPATCH_BEGIN" not in group or end is None:
            gaps["incomplete_dispatch_phase_inventory"] += 1; continue
        if end.get("outcome") == "RAISED":
            if "DISPATCH_OUTPUT" in group or end.get("output_marker") is not None:
                raise ValueError("raised dispatch falsely declares an output observation")
        elif end.get("outcome") == "RETURNED":
            if "DISPATCH_OUTPUT" not in group:
                gaps["returned_dispatch_output_unobserved"] += 1
            else:
                span_node = marker_nodes.get(group["DISPATCH_BEGIN"]["marker"])
                output_node = marker_nodes.get(group["DISPATCH_OUTPUT"]["marker"])
                if span_node is not None and output_node is not None and (
                        output_node.metadata["ctrl_deps"] != span_node.metadata["node_id"]
                        or output_node.metadata["raw_tid"] != span_node.metadata["raw_tid"]):
                    raise ValueError("output observation is not a real child of its dispatch span")
        else:
            raise ValueError("unknown dispatch outcome")
    if set(marker_nodes) - consumed:
        gaps["provider_markers_without_retained_sidecar"] += len(set(marker_nodes) - consumed)
    if meta.get("dropped_events") or meta.get("errors") or meta.get("gaps") or meta.get("io_failed"):
        gaps["collector_declared_partial"] += 1
    for item in pending_objects.values():
        values.add_object(item)
        evidence.register_external(EvidenceEndpoint(N.OBJECT, item.id))
    for edge in pending_edges:
        evidence.add_edge(edge)
    result.bundle.assert_valid()
    result.report["dispatch_bridge"] = {"schema": "scar.dispatch-observation-import", "schema_version": 1,
        "profile": PRODUCTION_PROFILE, "scope": scope, "production_collector": True,
        "capture_membership_verified": membership_verified,
        "artifacts": {key: encode(artifact) for key, artifact in artifacts.items()},
        "retained_input_paths": input_paths,
        "dispatches": len(grouped), "marker_nodes": len(marker_nodes), "slot_associations": len(paths),
        "outcomes": dict(Counter(group.get("DISPATCH_END", {}).get("outcome", "OPEN") for group in grouped.values())),
        "observations": observations, "paths": paths, "gaps": dict(gaps),
        "direct_python_operator_correspondence_established": False,
        "logical_versions_established": False, "world_effects_established": False,
        "resource_readiness_established": False, "whole_model_established": False,
        "transformation_authorized": False}
    return result


__all__ = ["import_dispatch_bridge"]
