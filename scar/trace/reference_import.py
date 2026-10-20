"""Replay a supplied exact-argument marker capture, without executing Torch.

This first profile describes the archived CPU research collector, NOT a
production collector. The cross-file correspondence is conditional on the
declared collector/capture contract. It creates no logical contents, storage
lifetimes, direct Python-to-ATen call, effect or completion-order claims.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re

from scar.ir.v2 import EvidenceClaim, EvidenceKind, ObjectID, ObjectInstance
from scar.ir.v2.evidence import EvidenceEdge, EvidenceEndpoint, EvidenceNodeKind as N, EvidenceRelation
from scar.trace.files import open_binary
from scar.trace.native_import import _canonical_hash, _constant, _float, _load_importer, _pairs


RESEARCH_PROFILE = "scar.marker-research-probe-v1"
_NAME = re.compile(r"scar-observation:([0-9a-f]{32}):([1-9][0-9]*):([1-9][0-9]*):(input|output)")
_WEAK = re.compile(r"weak:([1-9][0-9]*):([1-9][0-9]*)")


def _json(payload):
    try:
        return json.loads(payload, object_pairs_hook=_pairs,
                          parse_float=_float, parse_constant=_constant)
    except (UnicodeError, RecursionError, OverflowError) as error:
        raise ValueError("invalid reference observation JSON") from error


def _positive(value):
    return type(value) is int and value > 0


def import_reference_bridge(eto_path, markers_path, call_events_path, call_codes_path, call_meta_path,
                            *, reference_profile: str, provider_revision: str,
                            kineto_path=None, max_bytes=512_000_000, max_markers=100_000):
    """Import marker argument references under an explicit supplied profile.

    The original payload path and flattened provider argument ordinal are
    different coordinates. Even an output-phase marker encodes its Tensor
    arguments in marker.inputs, not marker.outputs. Missing or ambiguous joins
    are rejected, rather than resolved by timing, names of operators or shapes.
    """
    if reference_profile != RESEARCH_PROFILE:
        raise ValueError("unsupported reference collector profile")
    if not _positive(max_bytes) or not _positive(max_markers):
        raise ValueError("reference budgets must be positive exact integers")
    remaining, artifacts, raw, line_numbers = max_bytes, {}, {}, {}
    for key, path in (("markers", markers_path), ("calls", call_events_path),
                      ("codes", call_codes_path), ("meta", call_meta_path)):
        with open_binary(path) as stream:
            payload = stream.read(remaining + 1)
        if len(payload) > remaining:
            raise ValueError("reference evidence exceeds combined decompressed max_bytes")
        remaining -= len(payload)
        artifacts[key] = {"path": str(Path(path).absolute()), "sha256": sha256(payload).hexdigest(),
                          "size_bytes": len(payload), "hash_basis": "decompressed retained raw bytes"}
        if key in ("calls", "codes"):
            numbered = [(number, line) for number, line in enumerate(payload.splitlines(), 1) if line.strip()]
            raw[key] = [_json(line) for _, line in numbered]
            line_numbers[key] = [number for number, _ in numbered]
        else:
            raw[key] = _json(payload)
    markers, calls, codes, meta = (raw[key] for key in ("markers", "calls", "codes", "meta"))
    if type(markers) is not list or not markers or len(markers) > max_markers:
        raise ValueError("marker array is empty, invalid or exceeds max_markers")
    if (type(meta) is not dict or meta.get("schema") != "scar.call-edge-trace"
            or type(meta.get("schema_version")) is not int or meta["schema_version"] != 1
            or not _positive(meta.get("process_id"))):
        raise ValueError("unsupported call metadata")
    # This profile was closed successfully. Partial/lossy collectors require a
    # separate interface with explicit missing-reference inventory.
    for key in ("dropped_events", "dropped_codes", "open_invocations", "active_frames"):
        if type(meta.get(key)) is not int or meta[key] != 0:
            raise ValueError("research profile requires closed, lossless call metadata: " + key)
    if meta.get("io_failed") is not False or meta.get("errors") != []:
        raise ValueError("call collector failed")
    importer = _load_importer(eto_path, kineto_path, max_bytes=remaining,
                              provider_revision=provider_revision)
    if importer.pid != meta["process_id"]:
        raise ValueError("call and ETO processes differ")
    result = importer.finish()
    code_index, entries, event_indices = {}, {}, set()
    for number, code in enumerate(codes):
        if (type(code) is not dict or type(code.get("key")) is not str
                or not code["key"] or code["key"] in code_index
                or type(code.get("filename")) is not str or not code["filename"]):
            raise ValueError("invalid or duplicate call code")
        code_index[code["key"]] = (line_numbers["codes"][number], code)
    for number, event in enumerate(calls):
        if (type(event) is not dict or type(event.get("process_id")) is not int
                or event["process_id"] != importer.pid or not _positive(event.get("index"))
                or event["index"] in event_indices):
            raise ValueError("invalid, duplicate or cross-process call event")
        event_indices.add(event["index"])
        if event.get("kind") == "call_enter":
            invocation = event.get("invocation_id")
            if (not _positive(invocation) or invocation in entries or type(event.get("code")) is not str
                    or event.get("code") not in code_index):
                raise ValueError("invalid, duplicate or unbound call entry")
            entries[invocation] = (line_numbers["calls"][number], event)
    if (type(meta.get("events")) is not int or type(meta.get("codes")) is not int
            or meta["events"] != len(calls) or meta["codes"] != len(codes)):
        raise ValueError("call metadata count mismatch")
    nodes_by_name = {}
    for number, node in enumerate(importer.eto["nodes"]):
        nodes_by_name.setdefault(node["name"], []).append((number, node))
    scope = "python-reference:" + _canonical_hash({
        "native_scope": result.report["scope"], "profile": reference_profile,
        "artifacts": {key: item["sha256"] for key, item in artifacts.items()}})

    def pointer(key, path):
        return "sha256:" + artifacts[key]["sha256"] + path

    pairs, nonces, paths = {}, set(), []
    object_provider_tokens = {}
    for number, row in enumerate(markers):
        if type(row) is not dict or set(row) != {"name", "sequence", "phase", "context", "tensor_references"}:
            raise ValueError("invalid research marker fields")
        parsed = _NAME.fullmatch(row["name"]) if type(row["name"]) is str else None
        if parsed is None:
            raise ValueError("invalid marker identity")
        nonce, pid, sequence, phase = parsed.groups()
        sequence, pid = int(sequence), int(pid)
        if (pid != importer.pid or not _positive(row["sequence"])
                or sequence != row["sequence"] or phase != row["phase"]):
            raise ValueError("marker process/sequence/phase mismatch")
        nonces.add(nonce)
        if len(nonces) != 1 or (sequence, phase) in pairs:
            raise ValueError("mixed capture nonces or duplicate marker phase")
        candidates = nodes_by_name.get(row["name"], ())
        if len(candidates) != 1:
            raise ValueError("marker node is absent or nonunique")
        node_number, node = candidates[0]
        instance = importer.nodes[node["id"]]
        pairs[sequence, phase] = instance.id
        context = row["context"]
        if (type(context) is not dict or not _positive(context.get("invocation"))
                or context["invocation"] not in entries
                or context.get("kind") != "retained ancestor context, not a proven direct caller"
                or type(context.get("bytecode_offset")) is not int or context["bytecode_offset"] < 0):
            raise ValueError("marker lacks a retained ancestor context")
        entry_number, entry = entries[context["invocation"]]
        code_number, code = code_index[entry["code"]]
        if context.get("code") != entry["code"] or context.get("source_file") != code["filename"]:
            raise ValueError("marker context code mismatch")
        inputs = node.get("inputs")
        if (type(inputs) is not dict or type(inputs.get("values")) is not list
                or type(inputs.get("types")) is not list):
            raise ValueError("marker lacks exact provider input arrays")
        leaves, values, types = row["tensor_references"], inputs["values"], inputs["types"]
        slots = [slot for slot in instance.metadata.get("tensor_slots", ()) if slot["role"] == "inputs"]
        if (type(leaves) is not list or len(leaves) != len(values) or len(types) != len(values)
                or len(slots) != len(values) or [slot["ordered_path"] for slot in slots] != [[i] for i in range(len(values))]):
            raise ValueError("marker arguments are not an exact flattened Tensor slot list")
        seen_paths = set()
        for ordinal, (leaf, slot) in enumerate(zip(leaves, slots, strict=True)):
            if type(leaf) is not dict or set(leaf) != {"path", "ref"} or type(leaf["path"]) is not list:
                raise ValueError("invalid marker Tensor reference")
            if any(type(part) not in (int, str) or (type(part) is int and part < 0) for part in leaf["path"]):
                raise ValueError("invalid original payload path")
            original_path = tuple(leaf["path"])
            if original_path in seen_paths:
                raise ValueError("duplicate original payload path")
            seen_paths.add(original_path)
            weak = _WEAK.fullmatch(leaf["ref"]) if type(leaf["ref"]) is str else None
            if weak is None or int(weak[1]) != importer.pid:
                raise ValueError("reference is not a same-process verified weak token")
            identifier = ObjectID(scope + ":" + leaf["ref"])
            evidence = EvidenceClaim(EvidenceKind.INFERRED, (
                pointer("markers", f"#/{number}/tensor_references/{ordinal}"), slot["raw_reference"],
                pointer("calls", f"#line/{entry_number}"), pointer("codes", f"#line/{code_number}"),
                pointer("meta", "#")), scope=scope, assumptions=(
                    "supplied files belong to the same declared research collector capture",
                    "collector holds this exact Tensor while obtaining its weak reference and passing marker arguments",
                    "retained ancestor context is not a direct Python-to-ATen call correspondence",
                    "association is local to this marker slot, not persistent content/storage equivalence"))
            if identifier not in result.bundle.values.objects:
                result.bundle.values.add_object(ObjectInstance(identifier, scope, (evidence,), metadata={
                    "weak_token": leaf["ref"], "process_id": pid, "lifetime": "UNKNOWN",
                    "identity_basis": "supplied recorder weak-reference epoch, scoped by input artifact hashes"}))
                result.bundle.evidence.register_external(EvidenceEndpoint(N.OBJECT, identifier))
            edge_id = scope + f":marker:{number}:slot:{ordinal}"
            result.bundle.evidence.add_edge(EvidenceEdge(edge_id,
                EvidenceRelation.OBJECT_REFERENCE_ASSOCIATION,
                EvidenceEndpoint(N.OBJECT, identifier), EvidenceEndpoint(N.PROVIDER_REFERENCE, slot["provider_reference"]),
                evidence))
            object_provider_tokens.setdefault(identifier.wire, set()).add(slot["provider_reference"])
            paths.append({"edge_id": edge_id, "marker_instance": instance.id.wire,
                          "marker_phase": phase, "original_payload_path": list(original_path),
                          "provider_argument_ordinal": ordinal, "provider_role": "inputs",
                          "retained_ancestor": {"invocation": context["invocation"], "code": context["code"]},
                          "marker_raw_reference": importer.pointer("eto", f"#/nodes/{node_number}")})
    sequences = {key[0] for key in pairs}
    if set(pairs) != {(sequence, phase) for sequence in sequences for phase in ("input", "output")}:
        raise ValueError("research profile requires both marker phases for each dispatch")
    nonce, = nonces
    actual_names = {name for name in nodes_by_name if name.startswith(f"scar-observation:{nonce}:")}
    if actual_names != {row["name"] for row in markers}:
        raise ValueError("unaccounted marker nodes in this capture nonce")
    result.bundle.assert_valid()
    result.report["reference_bridge"] = {
        "schema": "scar.reference-marker-import", "schema_version": 1, "profile": reference_profile,
        "scope": scope, "artifacts": artifacts, "markers": len(markers), "dispatch_pairs": len(sequences),
        "objects": len(result.bundle.values.objects), "slot_associations": len(paths), "paths": paths,
        "objects_with_multiple_provider_tokens": sum(len(tokens) > 1 for tokens in object_provider_tokens.values()),
        "status": "Inferred under supplied research capture contract",
        "production_collector": False, "direct_python_operator_correspondence_established": False,
        "logical_versions_established": False, "whole_model_established": False,
    }
    result.report["budget"] = {"max_bytes": max_bytes, "max_markers": max_markers,
        "decompressed_bytes": result.report["budget"]["decompressed_bytes"] + sum(item["size_bytes"] for item in artifacts.values())}
    result.report["inventory"]["reference_bridge_edges"] = len(paths)
    return result


__all__ = ["RESEARCH_PROFILE", "import_reference_bridge"]
