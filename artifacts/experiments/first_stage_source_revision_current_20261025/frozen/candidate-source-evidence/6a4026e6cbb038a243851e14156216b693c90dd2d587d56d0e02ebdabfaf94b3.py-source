"""Bounded, post-close observations from PyTorch's existing physical model.

This exporter consumes the caller-owned result of the same closed profiler as
the explicit manifests. It neither starts a profiler nor imports torch. Marker
arguments are read as provider metadata, never as Tensor objects or contents.
The observations are not a canonical graph or a logical-value identity rule.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import sys


PROVIDER_REVISION = "cf30153c4c131c8164ee7798e5022d810682e2cb"
PROFILE = "scar.tensor-physical-event-tree-v1"
DISPATCH_PROFILE = "scar.dispatch-marker-collector-v1"
_NONCE = re.compile(r"[0-9a-f]{32}")


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _nonfinite(value):
    raise ValueError("nonfinite JSON scalar")


def _json(data):
    return json.loads(data, object_pairs_hook=_object, parse_constant=_nonfinite)


def _exact_path(path, expected):
    """Only open the caller's live file at the expected private output path."""
    actual = Path(path).absolute()
    if actual != expected or actual.is_symlink() or not actual.is_file():
        raise ValueError("explicit input does not match its live collector path")
    return actual


def _document(path, limit):
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("metadata input budget exceeded")
    value = _json(data)
    if type(value) is not dict:
        raise ValueError("metadata must be an object")
    return value, {"path": str(path), "raw_bytes": len(data),
                   "raw_sha256": hashlib.sha256(data).hexdigest()}


def _receipt_matches(declared, actual):
    return (type(declared) is dict and declared.get("path") == actual["path"]
            and type(declared.get("raw_bytes")) is int
            and declared["raw_bytes"] == actual["raw_bytes"]
            and declared.get("raw_sha256") == actual["raw_sha256"])


def _integer(value, *, minimum=None, optional=False):
    if optional and value is None:
        return None
    if type(value) is not int or (minimum is not None and value < minimum):
        raise ValueError("provider field is not a qualified integer")
    return value


def _sources(out, nonce, revision, metadata_path, observations_path, native_path,
             limits):
    pid = os.getpid()
    metadata_path = _exact_path(metadata_path, out / f"dispatch-meta.{pid}.{nonce}.json")
    observations_path = _exact_path(
        observations_path, out / f"dispatch-observations.{pid}.{nonce}.jsonl")
    native_path = _exact_path(native_path, out / f"execution-evidence.{pid}.json")
    meta, meta_receipt = _document(metadata_path, limits["max_metadata_bytes"])
    native, native_receipt = _document(native_path, limits["max_metadata_bytes"])
    if (meta.get("schema") != "scar.dispatch-observation-trace"
            or type(meta.get("schema_version")) is not int or meta["schema_version"] != 1
            or meta.get("profile") != DISPATCH_PROFILE
            or meta.get("provider_revision") != revision
            or type(meta.get("process_id")) is not int or meta["process_id"] != pid
            or meta.get("nonce") != nonce or meta.get("mode_popped") is not True):
        raise ValueError("dispatch metadata is not the closed owned production capture")
    if not _receipt_matches(meta.get("native_manifest"), native_receipt):
        raise ValueError("closed dispatch metadata does not bind the exact native manifest")
    if (native.get("schema") != "scar.execution-evidence-collection"
            or type(native.get("schema_version")) is not int or native["schema_version"] != 1
            or native.get("status") != "CLOSED"
            or type(native.get("pid")) is not int or native["pid"] != pid
            or native.get("provider", {}).get("torch_git_version") != revision
            or native.get("registration", {}).get("owned") is not True):
        raise ValueError("native manifest is not the closed owned provider capture")
    config = native.get("configuration", {})
    experimental = config.get("experimental_config")
    if (config.get("record_shapes") is not True or config.get("profile_memory") is not True
            or type(experimental) is not dict
            or experimental.get("adjust_timestamps") is not False
            or experimental.get("trace_only", False) is not False):
        raise ValueError("physical metadata requires shape/memory recording and an unadjusted event tree")
    dispatch = config.get("dispatch_observations", {})
    if (dispatch.get("profile") != DISPATCH_PROFILE or dispatch.get("started") is not True
            or dispatch.get("events") != str(observations_path)
            or dispatch.get("metadata") != str(metadata_path)):
        raise ValueError("native manifest does not declare these exact dispatch files")
    for label, name in (("execution_trace", f"execution-trace.{pid}.{nonce}.json"),
                        ("kineto", f"kineto.{pid}.{nonce}.json")):
        declared = native.get("artifacts", {}).get(label, {})
        if declared.get("path") != str(out / name) or declared.get("exists") is not True:
            raise ValueError("native artifact ownership nonce/path is not aligned")
    owner_ident = _integer(meta.get("owner_python_ident"), minimum=1)
    owner_tid = _integer(meta.get("owner_native_tid"), minimum=1)
    if (type(native.get("install_thread_id")) is not int
            or native["install_thread_id"] != owner_ident
            or type(dispatch.get("owner_python_ident")) is not int
            or dispatch["owner_python_ident"] != owner_ident):
        raise ValueError("dispatch owner Python ident is not the native collector owner")
    markers, attempts, digest = {}, {}, hashlib.sha256()
    raw_bytes = lines = 0
    with observations_path.open("rb") as stream:
        while True:
            line = stream.readline(limits["max_line_bytes"] + 1)
            if not line:
                break
            raw_bytes += len(line)
            lines += 1
            if (len(line) > limits["max_line_bytes"] or not line.endswith(b"\n")
                    or raw_bytes > limits["max_source_bytes"]
                    or lines > limits["max_source_rows"]):
                raise ValueError("dispatch inventory input budget or complete-line bound exceeded")
            digest.update(line)
            row = _json(line)
            if (type(row) is not dict or type(row.get("index")) is not int or row["index"] != lines
                    or type(row.get("process_id")) is not int or row["process_id"] != pid):
                raise ValueError("dispatch source line/index/process does not match")
            sequence = _integer(row.get("sequence"), minimum=1)
            if sequence not in attempts:
                if len(attempts) >= limits["max_markers"]:
                    raise ValueError("dispatch attempt inventory budget exceeded")
                attempts[sequence] = {"ended": False, "span": None, "output": None}
            attempt = attempts[sequence]
            kind = row.get("kind")
            if kind in ("DISPATCH_BEGIN", "DISPATCH_OUTPUT"):
                phase = "span" if kind == "DISPATCH_BEGIN" else "output"
                marker = f"scar-dispatch:{nonce}:{pid}:{sequence}:{phase}"
                observation = row.get("observation", {})
                references = observation.get("tensor_references")
                if (row.get("marker") != marker or marker in markers or attempt["ended"]
                        or type(observation.get("process_id")) is not int or observation["process_id"] != pid
                        or type(observation.get("python_ident")) is not int or observation["python_ident"] != owner_ident
                        or type(observation.get("native_tid")) is not int or observation["native_tid"] != owner_tid
                        or type(references) is not list
                        or len(references) > limits["max_slots"]
                        or (phase == "output" and attempt["span"] is None)):
                    raise ValueError("dispatch marker/ordered-source declaration does not match")
                if len(markers) >= limits["max_markers"]:
                    raise ValueError("dispatch marker inventory budget exceeded")
                declaration = {"marker": marker, "sequence": sequence, "phase": phase,
                    "source_line": lines, "tensor_slots": len(references),
                    "native_tid": owner_tid, "python_ident": owner_ident,
                    "entered": None, "occurrences": 0}
                markers[marker] = attempt[phase] = declaration
            elif kind == "DISPATCH_END":
                if (attempt["ended"] or row.get("outcome") not in ("RETURNED", "RAISED")
                        or type(row.get("span_enter_returned")) is not bool
                        or (row["span_enter_returned"] and attempt["span"] is None)):
                    raise ValueError("dispatch end declaration does not match")
                attempt["ended"] = True
                if attempt["span"] is not None:
                    attempt["span"]["entered"] = row["span_enter_returned"]
                expected_output = (None if attempt["output"] is None
                                   else attempt["output"]["marker"])
                output = row.get("output_marker")
                if output is not None and output != expected_output:
                    raise ValueError("dispatch end names an unobserved output marker")
                if output is not None and (not row["span_enter_returned"] or row["outcome"] != "RETURNED"):
                    raise ValueError("dispatch output marker has no successful enclosing dispatch")
                if attempt["output"] is not None:
                    attempt["output"]["entered"] = output == expected_output
            else:
                raise ValueError("unknown production dispatch row kind")
    observation_receipt = {"path": str(observations_path), "raw_bytes": raw_bytes,
                           "raw_sha256": digest.hexdigest(), "lines": lines}
    if (not _receipt_matches(meta.get("file"), observation_receipt)
            or type(meta["file"].get("lines")) is not int or meta["file"]["lines"] != lines
            or type(meta.get("events")) is not int or meta["events"] != lines
            or type(meta.get("bytes")) is not int or meta["bytes"] != raw_bytes):
        raise ValueError("dispatch file does not match its exact closed receipt")
    return meta, native, markers, {"dispatch_metadata": meta_receipt,
        "dispatch_observations": observation_receipt, "native_manifest": native_receipt}


class _Writer:
    def __init__(self, path, limits):
        self.path, self.limits = path, limits
        self.fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        self.digest = hashlib.sha256()
        self.bytes = self.lines = 0
        self.failure = None

    def emit(self, row):
        if self.lines >= self.limits["max_events"]:
            self.failure = "output_event_budget"
            return False
        data = (json.dumps(row, ensure_ascii=True, separators=(",", ":"),
                           allow_nan=False) + "\n").encode("ascii")
        if len(data) > self.limits["max_line_bytes"] or self.bytes + len(data) > self.limits["max_bytes"]:
            self.failure = "output_byte_or_line_budget"
            return False
        try:
            offset = 0
            while offset < len(data):
                size = os.write(self.fd, data[offset:])
                if size <= 0:
                    raise OSError("physical sidecar made no write progress")
                self.digest.update(data[offset:offset + size])
                self.bytes += size
                offset += size
        except OSError:
            self.failure = "output_io_failure"
            raise
        self.lines += 1
        return True

    def receipt(self):
        return {"path": str(self.path), "raw_bytes": self.bytes,
                "raw_sha256": self.digest.hexdigest(), "lines": self.lines}


def _provider_integer(owner, name, gaps, *, minimum=None, optional=False):
    try:
        return _integer(getattr(owner, name), minimum=minimum, optional=optional)
    except (AttributeError, TypeError, ValueError, RuntimeError):
        gaps.append(f"unavailable_or_invalid:{name}")
        return None


def _device(owner, torch, gaps):
    try:
        value = owner.device
        if type(value) is not torch.device:
            raise ValueError("invalid provider device")
        return {"type": value.type, "index": value.index, "text": str(value)}
    except (AttributeError, TypeError, ValueError, RuntimeError):
        gaps.append("unavailable_or_invalid:device")
        return None


def _header(event, parent_id, ordinal, gaps):
    event_id = _provider_integer(event, "id", gaps, minimum=1)
    parent = event.parent
    actual_parent = None if parent is None else _provider_integer(parent, "id", gaps, minimum=1)
    if actual_parent != parent_id:
        gaps.append("provider_parent_differs_from_traversal_parent")
    return {"traversal_ordinal": ordinal, "result_id": event_id,
        "parent_result_id": actual_parent,
        "start_time_ns": _provider_integer(event, "start_time_ns", gaps),
        "end_time_ns": _provider_integer(event, "end_time_ns", gaps),
        "record_function_thread_token": _provider_integer(event, "start_tid", gaps, minimum=1),
        "correlation_id": _provider_integer(event, "correlation_id", gaps, minimum=0)}


def _tensor(metadata, torch, limits):
    gaps = []
    if type(metadata) is not torch._C._profiler._TensorMetadata:
        return {"status": "OPEN", "gaps": ["marker_argument_is_not_direct_tensor_metadata"]}
    result = {"status": "OBSERVED",
        "impl_ptr": _provider_integer(metadata, "impl_ptr", gaps, minimum=0, optional=True),
        "storage_data_ptr": _provider_integer(metadata, "storage_data_ptr", gaps, minimum=0, optional=True),
        # TensorID starts at zero in this provider. Preserve an observed zero;
        # never synthesize it for missing fields or promote it to LogicalValueID.
        "provider_tensor_id": _provider_integer(metadata, "id", gaps, minimum=0, optional=True),
        "provider_allocation_id": _provider_integer(metadata, "allocation_id", gaps, minimum=1, optional=True),
        "device": _device(metadata, torch, gaps), "dtype": None, "layout": None,
        "sizes": None, "strides": None, "storage_offset": None}
    for name, kind in (("dtype", torch.dtype), ("layout", torch.layout)):
        try:
            value = getattr(metadata, name)
            if type(value) is not kind:
                raise ValueError("invalid provider representation")
            result[name] = str(value)
        except (AttributeError, TypeError, ValueError, RuntimeError):
            gaps.append(f"unavailable_or_invalid:{name}")
    for name in ("sizes", "strides"):
        try:
            value = getattr(metadata, name)
            if (type(value) is not list or len(value) > limits["max_rank"]
                    or any(type(item) is not int for item in value)
                    or (name == "sizes" and any(item < 0 for item in value))):
                raise ValueError("unsupported or over-budget provider geometry")
            result[name] = value
        except (AttributeError, TypeError, ValueError, RuntimeError):
            gaps.append(f"unavailable_or_invalid:{name}")
    if (result["sizes"] is not None and result["strides"] is not None
            and len(result["sizes"]) != len(result["strides"])):
        gaps.append("provider_geometry_rank_mismatch")
    result["physical_epoch_reference_observed"] = (
        result["provider_allocation_id"] is not None and result["device"] is not None
        and result["storage_data_ptr"] not in (None, 0))
    result["storage_offset_gap"] = "not_exposed_by_installed_tensor_metadata_binding"
    result["gaps"] = gaps
    if gaps:
        result["status"] = "OPEN"
    return result


def _allocation(extra, event, parent_id, ordinal, torch):
    gaps = []
    result = {"kind": "ALLOCATION", "event": _header(event, parent_id, ordinal, gaps),
        "ptr": _provider_integer(extra, "ptr", gaps, minimum=0),
        "provider_tensor_id": _provider_integer(extra, "id", gaps, minimum=0, optional=True),
        "provider_allocation_id": _provider_integer(extra, "allocation_id", gaps, minimum=1, optional=True),
        "alloc_size": _provider_integer(extra, "alloc_size", gaps),
        "total_allocated": _provider_integer(extra, "total_allocated", gaps, minimum=0),
        "total_reserved": _provider_integer(extra, "total_reserved", gaps, minimum=0),
        "device": _device(extra, torch, gaps), "gaps": gaps}
    size = result["alloc_size"]
    result["receipt_kind"] = (None if size is None else
        "ALLOCATE" if size > 0 else "FREE" if size < 0 else "ZERO_SIZE")
    result["physical_epoch_reference_observed"] = (
        result["provider_allocation_id"] is not None and result["device"] is not None
        and result["ptr"] not in (None, 0))
    result["legacy_kineto_allocation_correspondence_established"] = False
    return result


def export_tensor_physical(profiler_result, out, *, nonce,
        provider_revision=PROVIDER_REVISION, dispatch_metadata_path,
        dispatch_observations_path, native_manifest_path,
        max_events=1000000, max_bytes=512000000, max_nodes=2000000,
        max_depth=1024, max_markers=250000, max_slots=4096, max_rank=64,
        max_line_bytes=2000000, max_metadata_bytes=2000000,
        max_source_bytes=2000000000, max_source_rows=2000000):
    """Export metadata/allocator receipts after the complete collector close.

    ``profiler_result`` is the still-live, caller-owned ``kineto_results`` of
    the profiler named by the closed native manifest. Call on its owner process
    after dispatch metadata has bound the final native manifest hash. Files are
    created exclusively; an existing output is an error. Invalid source inputs
    fail before creation. A traversal/output frontier produces an OPEN receipt.

    This function does not import torch, start collection, inspect Tensor
    contents, build logical versions, or bind old Kineto allocation receipts.
    A consumer must require the final metadata's complete marker qualification
    before accepting any provisional ordered marker-slot correspondence.
    """
    limits = dict(max_events=max_events, max_bytes=max_bytes, max_nodes=max_nodes,
        max_depth=max_depth, max_markers=max_markers, max_slots=max_slots, max_rank=max_rank,
        max_line_bytes=max_line_bytes, max_metadata_bytes=max_metadata_bytes,
        max_source_bytes=max_source_bytes, max_source_rows=max_source_rows)
    if any(type(value) is not int or value < 1 for value in limits.values()):
        raise ValueError("physical export budgets must be positive exact integers")
    if (provider_revision != PROVIDER_REVISION or type(nonce) is not str
            or _NONCE.fullmatch(nonce) is None):
        raise ValueError("unsupported physical metadata provider or capture nonce")
    torch = sys.modules.get("torch")
    if (torch is None or getattr(getattr(torch, "version", None), "git_version", None) != provider_revision
            or type(profiler_result) is not torch._C._autograd._ProfilerResult):
        raise ValueError("a loaded matching provider and its exact closed ProfilerResult are required")
    out = Path(out).resolve(strict=True)
    if not out.is_dir():
        raise ValueError("physical output directory does not exist")
    meta, native, markers, inputs = _sources(out, nonce, provider_revision,
        dispatch_metadata_path, dispatch_observations_path, native_manifest_path, limits)
    pid = os.getpid()
    event_path = out / f"tensor-physical.{pid}.{nonce}.jsonl"
    metadata_path = out / f"tensor-physical-meta.{pid}.{nonce}.json"
    if metadata_path.exists() or metadata_path.is_symlink():
        raise ValueError("physical metadata output must be fresh")
    # Reserve metadata before any observations. O_EXCL is the publication
    # ownership receipt, and a failed export never overwrites an earlier one.
    metadata_fd = os.open(metadata_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    writer = None
    counts, gaps, errors = Counter(), Counter(), []
    seen, stack = set(), []
    frontier = None
    completed = False
    try:
        writer = _Writer(event_path, limits)
        roots = profiler_result.experimental_event_tree()
        if type(roots) is not list:
            raise ValueError("provider did not return its documented event-tree roots")
        # Keep iterators and active ancestry only. Never flatten/list the tree.
        # The provider binding itself returns roots/children lists; its own
        # memory and the previously captured provider buffers are not bounded.
        stack = [(iter(roots), None, 0)]
        while stack:
            iterator, parent_id, depth = stack[-1]
            try:
                event = next(iterator)
            except StopIteration:
                stack.pop()
                continue
            if counts["visited_nodes"] >= max_nodes or depth > max_depth:
                frontier = {"reason": "node_or_depth_budget", "depth": depth,
                            "pending_iterator_levels": len(stack), "unvisited_nodes": None}
                break
            counts["visited_nodes"] += 1
            if type(event) is not torch._C._profiler._ProfilerEvent:
                raise ValueError("event tree contains a nonprovider event")
            result_id = _integer(event.id, minimum=1)
            if result_id in seen:
                gaps["repeated_or_cyclic_result_node"] += 1
                continue
            seen.add(result_id)
            tag, extra = event.typed
            row = None
            if tag == torch._C._profiler._EventType.Allocation:
                counts["allocation_nodes"] += 1
                row = _allocation(extra, event, parent_id, counts["visited_nodes"], torch)
                counts[f"allocation_{row['receipt_kind'] or 'UNQUALIFIED'}"] += 1
                if row["gaps"]:
                    counts["allocation_receipts_with_gaps"] += 1
                if row["physical_epoch_reference_observed"]:
                    counts["allocation_receipts_with_epoch_reference"] += 1
            elif tag == torch._C._profiler._EventType.TorchOp:
                name = extra.name
                if type(name) is not str:
                    raise ValueError("provider TorchOp name is not a string")
                if name.startswith(f"scar-dispatch:{nonce}:"):
                    declaration = markers.get(name)
                    if declaration is None:
                        gaps["owned_nonce_marker_not_declared_by_dispatch_source"] += 1
                    else:
                        declaration["occurrences"] += 1
                        counts["marker_nodes"] += 1
                        local_gaps = []
                        header = _header(event, parent_id, counts["visited_nodes"], local_gaps)
                        values = extra.inputs
                        if type(values) is not list or len(values) > max_slots:
                            local_gaps.append("unsupported_or_over_budget_marker_arguments")
                            values = None
                        elif len(values) != declaration["tensor_slots"]:
                            local_gaps.append("marker_argument_count_differs_from_dispatch_source")
                        slots = []
                        if values is not None:
                            for ordinal, value in enumerate(values):
                                tensor = _tensor(value, torch, limits)
                                slots.append({"argument_ordinal": ordinal,
                                    "dispatch_reference_ordinal": ordinal, "metadata": tensor})
                                counts["marker_argument_slots"] += 1
                                if tensor["status"] == "OPEN":
                                    counts["marker_argument_slots_with_gaps"] += 1
                                if tensor.get("physical_epoch_reference_observed"):
                                    counts["marker_slots_with_epoch_reference"] += 1
                        if declaration["entered"] is not True:
                            local_gaps.append("dispatch_end_did_not_confirm_marker_enter")
                        if declaration["occurrences"] != 1:
                            local_gaps.append("duplicate_owned_marker_name")
                        row = {"kind": "MARKER", "marker": name, "event": header,
                            "sequence": declaration["sequence"], "phase": declaration["phase"],
                            "dispatch_source_line": declaration["source_line"],
                            "dispatch_native_tid": declaration["native_tid"],
                            "dispatch_python_ident": declaration["python_ident"],
                            "expected_argument_count": declaration["tensor_slots"],
                            "arguments": slots, "gaps": local_gaps,
                            "binding_status": "PROVISIONAL_REQUIRES_FINAL_METADATA"}
                        if local_gaps:
                            counts["marker_nodes_with_gaps"] += 1
                        for gap in local_gaps:
                            gaps[gap] += 1
            if row is not None:
                row.update(schema="scar.tensor-physical-observation", schema_version=1,
                           process_id=pid, nonce=nonce, index=writer.lines + 1)
                if not writer.emit(row):
                    frontier = {"reason": writer.failure, "result_id": result_id,
                        "depth": depth, "pending_iterator_levels": len(stack),
                        "dropped_events_at_least": 1, "unvisited_nodes": None}
                    break
            children = event.children
            if type(children) is not list:
                raise ValueError("provider did not return documented event-tree children")
            if children:
                stack.append((iter(children), result_id, depth + 1))
        else:
            completed = True
    except Exception as error:
        errors.append({"stage": "export", "type": type(error).__name__,
                       "message": str(error)[:512]})
        frontier = {"reason": "export_exception", "pending_iterator_levels": len(stack),
                    "unvisited_nodes": None}
    finally:
        stack.clear()
        seen.clear()
        if writer is not None:
            os.close(writer.fd)
    required = sum(item["entered"] is True for item in markers.values())
    missing, duplicates = [], []
    missing_count = duplicate_count = 0
    for item in markers.values():
        if item["entered"] is True and item["occurrences"] == 0:
            missing_count += 1
            if len(missing) < 32:
                missing.append(item["marker"])
        if item["occurrences"] > 1:
            duplicate_count += 1
            if len(duplicates) < 32:
                duplicates.append(item["marker"])
    marker_complete = (completed and not errors and not gaps and not missing_count
        and not duplicate_count and required > 0 and counts["marker_argument_slots_with_gaps"] == 0)
    allocation_complete = (completed and not errors and not gaps["repeated_or_cyclic_result_node"]
                           and counts["allocation_receipts_with_gaps"] == 0)
    report = {"schema": "scar.tensor-physical-trace", "schema_version": 1,
        "profile": PROFILE, "provider_revision": provider_revision,
        "process_id": pid, "nonce": nonce, "limits": limits, "inputs": inputs,
        "file": None if writer is None else writer.receipt(),
        "status": "OBSERVED" if marker_complete and allocation_complete else "OPEN",
        "counts": dict(counts), "gaps": dict(gaps), "errors": errors,
        "traversal_completed": completed, "frontier": frontier,
        "source_marker_count": len(markers), "confirmed_marker_count": required,
        "missing_confirmed_markers": {"count": missing_count, "sample": missing},
        "duplicate_marker_names": {"count": duplicate_count, "sample": duplicates},
        "marker_ordered_slot_correspondence_established": marker_complete,
        "allocation_receipt_traversal_complete": allocation_complete,
        "source_collection_gaps": {"dispatch_dropped_events": meta.get("dropped_events"),
            "dispatch_errors": meta.get("errors"), "dispatch_gaps": meta.get("gaps"),
            "native_failures": native.get("failures")},
        "result_ownership": "caller-held result of the same closed profiler; unique nonce markers checked",
        "configuration": {key: native["configuration"].get(key) for key in
            ("record_shapes", "profile_memory", "with_stack", "experimental_config")},
        "namespaces": {
            "result_id": "provider Result object address, capture-local; not RF id or Ev Idx",
            "traversal_ordinal": "exporter DFS order; not provider original result-vector Ev Idx",
            "record_function_thread_token": "provider RecordFunction thread token; not Linux TID",
            "dispatch_native_tid": "actual Python threading.get_native_id observation in source row",
            "provider_tensor_id": "provider transitive TensorImpl/storage group; not logical identity",
            "provider_allocation_id": "provider physical epoch, scoped to result/capture/process/device"},
        "proof_boundary": [
            "marker rows require final complete metadata and exact ordered-slot importer checks",
            "ETO/Kineto marker alignment must be checked by their existing exact marker/RF importer",
            "TensorMetadata has no storage offset or authoritative allocation extent",
            "allocation receipts do not establish GPU completion or physical cudaMalloc/cudaFree",
            "preexisting storage may have a provider epoch without an allocation birth receipt",
            "individual legacy Kineto memory receipts have no exposed exact event-tree source locator",
            "external writes, NumPy aliases and logical content equality remain unproved",
            "instrumentation can change references, allocation and timing; not a clean benchmark"],
        "eto_marker_correspondence_established": False,
        "legacy_kineto_allocation_correspondence_established": False,
        "logical_versions_established": False, "materializations_established": False,
        "state_effects_established": False, "resource_readiness_established": False,
        "whole_model_established": False, "transformation_authorized": False}
    try:
        payload = (json.dumps(report, ensure_ascii=True, sort_keys=True,
                             separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")
        if len(payload) > max_metadata_bytes:
            raise ValueError("physical metadata output exceeds its explicit bound")
        offset = 0
        while offset < len(payload):
            size = os.write(metadata_fd, payload[offset:])
            if size <= 0:
                raise OSError("physical metadata made no write progress")
            offset += size
    finally:
        os.close(metadata_fd)
    return report


__all__ = ["export_tensor_physical", "PROFILE", "PROVIDER_REVISION"]
