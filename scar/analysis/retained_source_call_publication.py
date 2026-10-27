"""Small receipt-bound shards for a live RetainedSourceCallPortSession."""
from __future__ import annotations

from hashlib import sha256
import gzip
from io import BytesIO
import json
from pathlib import Path
import time
from dataclasses import dataclass

from scar.analysis.retained_source_call_ports import (
    RetainedSourceCallPortSession,
    _canonical,
    _need,
)
from scar.ir.program.python_call_targets import PythonSourcePortModel
from scar.ir.record_codec import loads as strict_loads


@dataclass(frozen=True, slots=True)
class RetainedSourceCallPortShardRef:
    shard_index: int
    path: str
    stored_sha256: str
    stored_bytes: int
    decoded_sha256: str
    decoded_bytes: int
    model_schema: str
    model_schema_version: int
    model_summary: dict
    candidate_scope: dict
    capture_denominators: dict
    namespace_refs: tuple[dict, ...]


@dataclass(frozen=True, slots=True)
class RetainedSourceCallPublicationIndex:
    manifest_path: str
    manifest_sha256: str
    manifest: dict
    shard_refs: tuple[RetainedSourceCallPortShardRef, ...]
    publication_closed: bool
    candidate_coverage_complete: bool


@dataclass(frozen=True, slots=True)
class RetainedSourceCallShard:
    shard_index: int
    path: str
    stored_sha256: str
    decoded_sha256: str
    manifest_sha256: str
    candidate_scope: dict
    namespace_refs: tuple[dict, ...]
    model: PythonSourcePortModel


def _shard_ref(root, raw):
    return RetainedSourceCallPortShardRef(raw["shard_index"],
        str((root / raw["path"]).absolute()), raw["stored_sha256"], raw["stored_bytes"],
        raw["decoded_sha256"], raw["decoded_bytes"], raw["model_schema"],
        raw["model_schema_version"], raw["model_summary"], raw["candidate_scope"],
        raw["capture_denominators"], tuple(raw.get("namespace_refs", ())))


def _gzip_deterministic(payload):
    out = BytesIO()
    with gzip.GzipFile(filename="", fileobj=out, mode="wb", mtime=0, compresslevel=6) as stream:
        stream.write(payload)
    return out.getvalue()


def _write_new(path, payload):
    path = Path(path).absolute()
    with path.open("xb") as stream:
        stream.write(payload)
    return path


def publish_retained_source_call_port_shards(session, output_dir, *,
        max_selected_calls_per_shard=32, max_candidate_pairs_per_shard=64,
        max_shards=None):
    """Build a bounded candidate range into independent typed model shards.

    ``session`` owns the single strict raw read and stays live across calls.
    The publication stores only existing ``PythonSourcePortModel`` records;
    shared source/body descriptors remain qualified references inside them.
    """
    _need(type(session) is RetainedSourceCallPortSession,
          "a live retained raw-reader session is required")
    _need(type(max_selected_calls_per_shard) is int and max_selected_calls_per_shard > 0,
          "positive selected-call shard ceiling required")
    _need(type(max_candidate_pairs_per_shard) is int and max_candidate_pairs_per_shard > 0,
          "positive candidate shard ceiling required")
    _need(max_shards is None or type(max_shards) is int and max_shards > 0,
          "positive shard ceiling or None required")
    root = Path(output_dir).absolute()
    _need(not root.is_symlink(), "publication directory cannot be a symlink")
    root.mkdir(parents=True, exist_ok=True)
    _need(not any(root.iterdir()), "publication output directory must be empty")

    shards, windows = [], []
    started = time.monotonic()
    while session.cursor < session.max_candidate_pairs:
        if max_shards is not None and len(windows) >= max_shards:
            break
        batch = session.build_batch(
            max_selected_calls=max_selected_calls_per_shard,
            max_candidate_pairs=max_candidate_pairs_per_shard)
        scope = batch.report["candidate_scope"]
        if not scope["candidate_ordinals"]:
            break
        shard_ref = None
        if batch.model.bindings:
            model_payload = _canonical(batch.model.to_dict()) + b"\n"
            decoded_sha256 = sha256(model_payload).hexdigest()
            stored_payload = _gzip_deterministic(model_payload)
            stored_sha256 = sha256(stored_payload).hexdigest()
            name = f"shard-{len(shards):05d}.python-source-ports.json.gz"
            path = _write_new(root / name, stored_payload)
            namespace_refs = []
            seen_namespaces = set()
            for binding in batch.model.bindings:
                for namespace in (binding.caller_body, binding.callee_body):
                    key = _canonical(namespace.original_namespace())
                    if key not in seen_namespaces:
                        seen_namespaces.add(key)
                        namespace_refs.append(namespace.original_namespace())
            shard_ref = {
                "shard_index": len(shards), "path": name,
                "representation": "gzip-json-mtime0-v1",
                "stored_sha256": stored_sha256, "stored_bytes": len(stored_payload),
                "decoded_sha256": decoded_sha256, "decoded_bytes": len(model_payload),
                "model_schema": "scar.python-source-port-bindings", "model_schema_version": 2,
                "model_summary": batch.model.summary(),
                "capture_denominators": session.denominators,
                "candidate_scope": scope,
                "namespace_refs": namespace_refs,
            }
            shards.append(shard_ref)
        windows.append({
            "window_index": len(windows),
            "status": batch.report["status"],
            "candidate_scope": scope,
            "candidate_issues": batch.report["candidate_issues"],
            "model_summary": batch.report["model_summary"],
            "shard_index": None if shard_ref is None else shard_ref["shard_index"],
            "cache_state_after_window": batch.report["cache_state"],
        })

    session_summary = session.summary()
    if session.cursor >= session.total_direct_candidates:
        status = "ALL_DIRECT_CANDIDATES_SCANNED"
    elif session.cursor >= session.max_candidate_pairs:
        status = "BOUNDED_DIRECT_CANDIDATE_SCOPE_COMPLETE"
    else:
        status = "PARTIAL_SESSION_SCOPE"
    manifest = {
        "schema": "scar.retained-source-call-port-publication",
        "schema_version": 1,
        "status": status,
        "publication_closed": True,
        "created_by": "retained-source-call-session-v1",
        "storage": {"model_representation": "gzip-json-mtime0-v1",
            "shard_strategy": "one-existing-PythonSourcePortModel-per-batch",
            "raw_trace_copied": False, "source_bodies_copied": False},
        "shared_inputs": {
            "source_report": session_summary["source_report"],
            "bindings": session_summary["bindings"],
            "trace_root": session_summary["trace_root"],
            "trace_file_receipts": {
                "frame_files": [{"path": item.path, "family": item.family,
                    "process_id": item.process_id, "raw_sha256": item.raw_sha256,
                    "raw_bytes": item.raw_bytes, "lines": item.lines}
                    for item in session.operands.frame_scan.files],
                "operand_files": [{"path": item.path, "family": item.family,
                    "process_id": item.process_id, "raw_sha256": item.raw_sha256,
                    "raw_bytes": item.raw_bytes, "lines": item.lines}
                    for item in session.operands.files],
            },
            "producer_sources": session.producer_sources,
        },
        "capture_denominators": session.denominators,
        "candidate_funnel": session.candidate_funnel,
        "candidate_scope": session_summary["candidate_scope"],
        "cross_shard_scope": {
            "ordering": "original-call-attempt-index; shard candidate ranges are disjoint",
            "semantics": "no cross-shard invocation merge, value flow, or causal ordering is asserted",
            "namespace_refs_are_shared_descriptors": True,
        },
        "attempt_coverage_established": False,
        "candidate_coverage_complete": session_summary["full_candidate_coverage"],
        "selected_attempt_indices": session_summary["selected_attempt_indices"],
        "candidate_issues": session_summary["candidate_issues"],
        "windows": windows,
        "shards": shards,
        "totals": {
            "direct_candidate_pairs_total": session.total_direct_candidates,
            "direct_candidate_pairs_examined": session.cursor,
            "direct_candidate_pairs_remaining": max(0, session.total_direct_candidates - session.cursor),
            "selected_calls": len(session.selected_attempt_indices),
            "shards": len(shards), "windows": len(windows),
            "max_candidate_pairs": session.max_candidate_pairs,
            "max_selected_calls_per_shard": max_selected_calls_per_shard,
            "max_candidate_pairs_per_shard": max_candidate_pairs_per_shard,
        },
        "session": session_summary,
        "costs": {"raw_reader_seconds": session.raw_reader_seconds,
            "publication_seconds_after_raw_read": time.monotonic() - started,
            "input_cache_state": session.cache_state()},
        "claims": {
            "actual_formal_routing_established": False,
            "normal_return_selected": False,
            "runtime_callable_environment_established": False,
            "receiver_identity_established": False,
            "content_or_effect_equivalence_established": False,
            "whole_program_graph_established": False,
            "transformation_authorized": False,
        },
    }
    payload = _canonical(manifest) + b"\n"
    manifest_path = _write_new(root / "manifest.json", payload)
    manifest_sha256 = sha256(payload).hexdigest()
    index = RetainedSourceCallPublicationIndex(str(manifest_path), manifest_sha256, manifest,
        tuple(_shard_ref(root, item) for item in shards), True,
        session_summary["full_candidate_coverage"])
    return {"manifest_path": str(manifest_path), "manifest_sha256": manifest_sha256,
        "manifest_bytes": len(payload), "manifest": manifest, "index": index}


def read_retained_source_call_publication(path, *, expected_manifest_sha256=None,
                                          expected_sha256=None, max_bytes=32_000_000):
    _need(expected_manifest_sha256 is None or expected_sha256 is None
          or expected_manifest_sha256 == expected_sha256,
          "conflicting expected manifest SHA arguments")
    expected = expected_manifest_sha256 if expected_manifest_sha256 is not None else expected_sha256
    path = Path(path).absolute()
    _need(not path.is_symlink() and path.is_file(), "publication manifest must be a regular file")
    before = path.stat()
    _need(before.st_size <= max_bytes, "publication manifest exceeds its byte ceiling")
    raw = path.read_bytes()
    after = path.stat()
    _need((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
          == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
          and len(raw) == before.st_size
          and (expected is None or sha256(raw).hexdigest() == expected),
          "publication manifest receipt or stability differs")
    actual_sha256 = sha256(raw).hexdigest()
    manifest = strict_loads(raw.decode("utf-8"))
    _need(type(manifest) is dict and manifest.get("schema") == "scar.retained-source-call-port-publication"
          and type(manifest.get("schema_version")) is int and manifest["schema_version"] == 1,
          "unsupported retained source-call publication")
    _need(type(manifest.get("shards")) is list and type(manifest.get("windows")) is list,
          "publication shard/window tables must be arrays")
    _need(all(type(item) is dict for item in manifest["shards"] + manifest["windows"]),
          "publication shard/window records must be objects")
    _need(all(type(item.get("shard_index")) is int for item in manifest["shards"])
          and [item.get("shard_index") for item in manifest["shards"]] == list(range(len(manifest["shards"]))),
          "publication shard indices must be unique and ordered")
    _need(manifest.get("publication_closed") is True,
          "retained source-call publication manifest is not closed")
    root = path.parent
    refs = tuple(_shard_ref(root, item) for item in manifest["shards"])
    return RetainedSourceCallPublicationIndex(str(path), actual_sha256, manifest, refs, True,
        manifest.get("candidate_coverage_complete") is True)


def read_retained_source_call_shard(index, shard_index=None, *, expected_manifest_sha256=None,
                                    max_stored_bytes=64_000_000,
                                    max_decoded_bytes=128_000_000):
    if type(index) is RetainedSourceCallPublicationIndex:
        _need(shard_index is not None and expected_manifest_sha256 is None,
              "publication index and one shard ordinal required")
        pub_index = index
    else:
        _need(shard_index is not None and expected_manifest_sha256 is not None,
              "manifest path, expected SHA and one shard ordinal required")
        pub_index = read_retained_source_call_publication(index,
            expected_manifest_sha256=expected_manifest_sha256)
    manifest_path = Path(pub_index.manifest_path)
    manifest = pub_index.manifest
    _need(type(shard_index) is int and 0 <= shard_index < len(manifest["shards"]),
          "exact published shard index required")
    shard = manifest["shards"][shard_index]
    name = shard.get("path")
    _need(type(name) is str and Path(name).name == name and name.endswith(".json.gz"),
          "shard must use one local relative filename")
    shard_path = manifest_path.parent / name
    _need(not shard_path.is_symlink() and shard_path.is_file(), "shard file must be a regular file")
    before = shard_path.stat()
    _need(before.st_size <= max_stored_bytes and before.st_size == shard.get("stored_bytes"),
          "shard stored size differs or exceeds its ceiling")
    stored = shard_path.read_bytes()
    after = shard_path.stat()
    _need((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
          == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
          and sha256(stored).hexdigest() == shard.get("stored_sha256"),
          "shard stored receipt or stability differs")
    with gzip.GzipFile(fileobj=BytesIO(stored), mode="rb") as stream:
        decoded = stream.read(max_decoded_bytes + 1)
    _need(len(decoded) <= max_decoded_bytes and len(decoded) == shard.get("decoded_bytes")
          and sha256(decoded).hexdigest() == shard.get("decoded_sha256"),
          "shard decoded receipt or ceiling differs")
    model = PythonSourcePortModel.loads(decoded.decode("utf-8"))
    _need(model.summary() == shard.get("model_summary")
          and [binding.target.attempt_index for binding in model.bindings]
              == shard.get("candidate_scope", {}).get("selected_attempt_indices"),
          "decoded typed model differs from the selected shard record")
    return RetainedSourceCallShard(shard_index, str(shard_path), shard["stored_sha256"],
        shard["decoded_sha256"], pub_index.manifest_sha256, shard["candidate_scope"],
        tuple(shard.get("namespace_refs", ())), model)


def iter_retained_source_call_shards(path, *, expected_manifest_sha256):
    index = read_retained_source_call_publication(path,
        expected_manifest_sha256=expected_manifest_sha256)
    for shard in index.shard_refs:
        yield shard.shard_index, read_retained_source_call_shard(index, shard.shard_index)


__all__ = ["RetainedSourceCallPortShardRef", "RetainedSourceCallPublicationIndex",
    "RetainedSourceCallShard", "publish_retained_source_call_port_shards",
    "read_retained_source_call_publication", "read_retained_source_call_shard",
    "iter_retained_source_call_shards"]
