"""Conservative, offline projection of v1 JSONL into IR v2 evidence.

This is a format adapter, not a semantic identity solver. Every value capture
gets a provisional snapshot identity; legacy storage/version strings are hints.
The raw file remains authoritative, addressed by line number and SHA256.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

import scar.ir.v2 as ir


@dataclass
class NormalizationResult:
    bundle: ir.IRBundle
    coverage: dict[str, Any]


_COMPLETED = {"module_call", "transfer", "torch_dispatch"}
_GPU = {"cuda_kernel", "cuda_memcpy"}
_CONTROL = {"python_line", "loop_iteration", "python_exception"}
_ALLOCATION = {"allocation", "memory_allocation", "cuda_allocation"}
_FREE = {"free", "memory_free", "cuda_free"}
_KNOWN = {"python_call", "python_return", "python_c_call", "cuda_barrier"} | _COMPLETED | _GPU | _CONTROL | _ALLOCATION | _FREE
_VALUE_FIELDS = {
    "type", "shape", "dtype", "device", "offset", "strides", "representation",
    "input_path", "state_role", "object_id", "storage_id", "logical_version",
    "content_fingerprint",
}


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode()).hexdigest()


def _integer(value: Any) -> bool:
    return type(value) is int


def _scalar_id(value: Any) -> bool:
    return type(value) in (str, int) and value != ""


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _no_constant(value):
    raise ValueError(f"non-finite JSON number: {value}")


def _finite_float(value):
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"non-finite JSON number: {value}")
    return parsed


class _Normalizer:
    def __init__(self, source: str, namespace: str):
        self.source, self.namespace = source, namespace
        self.semantic = ir.SemanticGraph()
        self.evidence = ir.EvidenceGraph()
        self.values = ir.ValueGraph()
        self.entries: list[dict[str, Any]] = []
        self.calls = defaultdict(list)
        self.returns = []
        self.parents = []
        self.controls = []
        self.streams = defaultdict(list)
        self.counts = Counter()
        self.raw_hash = hashlib.sha256()

    def claim(self, entry, *, inferred=False, assumptions=()):
        return ir.EvidenceClaim(
            ir.EvidenceKind.INFERRED if inferred else ir.EvidenceKind.OBSERVED,
            (entry["raw_reference"],), scope=self.namespace,
            assumptions=tuple(assumptions))

    def edge(self, relation, source_kind, source, target_kind, target, entry, **claim):
        edge_id = f"{self.namespace}:edge:{len(self.evidence.edges)}"
        self.evidence.edges[edge_id] = ir.EvidenceEdge(
            edge_id, relation, ir.EvidenceEndpoint(source_kind, source),
            ir.EvidenceEndpoint(target_kind, target), self.claim(entry, **claim))
        return edge_id

    def issue(self, entry, message, status="ambiguous"):
        entry["issues"].append(message)
        priority = {"normalized": 0, "ambiguous": 1, "opaque": 2, "unmatched": 3, "invalid": 4}
        if priority[status] > priority[entry["status"]]:
            entry["status"] = status

    def raw(self, record: Any, line: int, raw: bytes, error: str | None = None):
        self.raw_hash.update(raw)
        entry = {"line": line, "raw_reference": f"{self.source}#L{line}",
                 "sha256": hashlib.sha256(raw).hexdigest(), "kind": None,
                 "status": "normalized", "normalized": [], "issues": []}
        self.entries.append(entry)
        if error is not None:
            self.issue(entry, error, "invalid")
            return
        if not isinstance(record, dict) or not isinstance(record.get("kind"), str):
            self.issue(entry, "record must be an object with a kind string", "invalid")
            return
        entry["kind"] = record["kind"]
        entry["legacy_index"] = record.get("index")
        self.counts[record["kind"]] += 1
        if not isinstance(record.get("metadata", {}), dict) or not isinstance(record.get("resource", {}), dict):
            self.issue(entry, "metadata and resource must be objects", "invalid")
            return
        if (not isinstance(record.get("effect", {}), dict)
                or any(not isinstance(record.get(role, []), list) for role in ("inputs", "outputs"))):
            self.issue(entry, "effect must be an object; inputs/outputs must be arrays", "invalid")
            return
        metadata, resource = record.get("metadata", {}), record.get("resource", {})
        # Profile rows summarize many invocations; their emission time is not
        # an execution timestamp and memory deltas are not allocation events.
        if record["kind"] == "torch_op" and metadata.get("aggregate") is True:
            self.aggregate(record, entry)
            return
        if record["kind"] == "python_return":
            self.returns.append((record, entry))
            return
        if record["kind"] in _CONTROL:
            control_id = f"{self.namespace}:control:{line}"
            self.evidence.control_events.add(control_id)
            entry["normalized"].append({"kind": "control_event", "id": control_id})
            self.controls.append((record, entry, control_id))
            # The control ID owns no payload in schema v2; coverage carries its
            # exact raw location and small semantic fields.
            entry["control"] = {key: metadata[key] for key in (
                "line", "byte_offset", "loop_target_offset", "iteration",
                "loop_iteration", "function") if key in metadata}
            return
        self.instance(record, entry)

    def key(self, record, invocation=None):
        metadata = record.get("metadata", {})
        invocation = record.get("invocation_id") if invocation is None else invocation
        process, thread = metadata.get("process_id"), metadata.get("thread_id")
        if not all(_scalar_id(value) for value in (process, thread, invocation)):
            return None
        # Preserve int/string distinction and process/thread ownership.
        return _hash((self.namespace, process, thread, invocation))

    def measurement(self, metric, value, unit, entry, scope, samples=1, instance=None):
        if type(value) not in (int, float) or not math.isfinite(value):
            self.issue(entry, f"invalid numeric measurement {metric}")
            return
        identifier = ir.MeasurementID(f"{self.namespace}:record:{entry['line']}:{metric}")
        self.evidence.measurements[identifier] = ir.MeasurementRecord(
            identifier, metric, value, unit, scope, samples=max(1, samples),
            instrumented=True, evidence=(self.claim(entry),))
        entry["normalized"].append({"kind": "measurement", "id": identifier.wire})
        if instance is not None:
            self.edge(ir.EvidenceRelation.MEASURED_BY, ir.EvidenceNodeKind.OPERATION_INSTANCE,
                      instance, ir.EvidenceNodeKind.MEASUREMENT, identifier, entry)

    def aggregate(self, record, entry):
        resource = record.get("resource", {})
        count = resource.get("count", 1)
        samples = count if _integer(count) and count >= 1 else 1
        scope = f"aggregate:{record.get('code_id') or 'unknown'}:{self.namespace}:line:{entry['line']}"
        self.measurement("self_cpu_time_total", record.get("duration_ns"), "ns", entry, scope, samples)
        for key, unit in (("count", "count"), ("cuda_time_total_us", "us"),
                          ("cpu_memory_usage", "bytes"), ("self_cpu_memory_usage", "bytes"),
                          ("device_memory_usage", "bytes"), ("self_device_memory_usage", "bytes")):
            if key in resource:
                self.measurement(key, resource[key], unit, entry, scope, samples)
        entry["aggregate"] = True

    def instance(self, record, entry):
        kind = record["kind"]
        metadata, resource = record.get("metadata", {}), record.get("resource", {})
        identifier = ir.OperationInstanceID(f"{self.namespace}:record:{entry['line']}")
        code = record.get("code_id")
        label = metadata.get("operation") or metadata.get("c_qualname") or metadata.get("qualname") or metadata.get("function") or resource.get("operation") or code or kind
        op_kind = {"python_call": ir.OperationKind.FUNCTION, "module_call": ir.OperationKind.MODULE,
                   "torch_dispatch": ir.OperationKind.OPERATOR, "cuda_kernel": ir.OperationKind.KERNEL,
                   "cuda_memcpy": ir.OperationKind.TRANSFER}.get(kind, ir.OperationKind.OPAQUE)
        if kind in _ALLOCATION:
            op_kind = ir.OperationKind.ALLOCATION
        # A host wrapper is a representation request, not proof of DMA.
        if kind == "transfer":
            op_kind = ir.OperationKind.OPERATOR
        definition = ir.OperationDefinitionID("runtime:" + _hash((self.namespace, kind, code, label)))
        if definition not in self.semantic.definitions:
            self.semantic.definitions[definition] = ir.OperationDefinition(
                definition, op_kind, str(label), code_id=code if isinstance(code, str) else None,
                metadata={"origin": "v1_runtime_stub", "source_semantics": "unresolved",
                          "raw_kind": kind, "source_file_hint": metadata.get("file"),
                          "source_line_hint": metadata.get("line")})
        process = metadata.get("process_id")
        thread = metadata.get("host_tid") if kind == "cuda_barrier" else metadata.get("thread_id")
        if kind in _GPU:
            thread = f"gpu-stream:{resource.get('stream', 'unknown')}"
        if not _scalar_id(process):
            process = f"unknown-process:{entry['line']}"
            self.issue(entry, "process identity missing; cross-record identity disabled")
        if not _scalar_id(thread):
            thread = f"unknown-thread:{entry['line']}"
            self.issue(entry, "thread identity missing; host pairing disabled")
        timestamp, duration = record.get("ts_ns"), record.get("duration_ns")
        if timestamp is not None and (not _integer(timestamp) or timestamp < 0):
            self.issue(entry, "invalid timestamp")
            timestamp = None
        if duration is not None and (not _integer(duration) or duration < 0):
            self.issue(entry, "invalid duration")
            duration = None
        start, end, timing = timestamp, None, "point_observation"
        if kind in _COMPLETED:
            end = timestamp
            start = end - duration if end is not None and duration is not None and end >= duration else None
            timing = "end_emission; span start inferred from measured duration"
        elif kind in _GPU or kind == "cuda_barrier":
            end = timestamp + duration if timestamp is not None and duration is not None else None
            timing = "kineto_start_and_duration"
        known_metadata = {key: metadata[key] for key in (
            "clock_domain", "parent_invocation_id", "call_depth", "correlation", "external_id",
            "profiler_pid", "profiler_tid", "host_tid", "host_runtime", "physical",
            "logical_tensor_mapping", "mapping_confidence", "matched_transfer_event_index",
            "loop_instance", "loop_iteration", "loop_target_offset", "outcome",
            "same_object", "device_transition", "input_capture", "contract_read_capture",
            "pure_contract", "contract_state_stable") if key in metadata}
        known_metadata.update({"raw_reference": entry["raw_reference"], "raw_sha256": entry["sha256"],
                               "raw_kind": kind, "legacy_invocation_id": record.get("invocation_id"),
                               "timestamp_semantics": timing, "collector": "scar.v1",
                               "effects_complete": False, "legacy_effect": record.get("effect", {}),
                               "labels": record.get("labels", []), "resource_snapshot": resource,
                               "completion": "missing_return" if kind == "python_call" else "observed_span" if end is not None else "point_only"})
        if kind == "transfer":
            known_metadata["physical_copy"] = False if metadata.get("physical") is False else "UNKNOWN"
        elif kind == "cuda_memcpy":
            known_metadata["physical_copy"] = (
                True if metadata.get("physical") is True and metadata.get("clock_domain") == "kineto" else "UNKNOWN")
            if known_metadata["physical_copy"] != True:
                self.issue(entry, "memcpy lacks runtime physical/clock evidence")
            known_metadata["logical_mapping"] = "unresolved; legacy signature match is not proof"
        if kind not in _KNOWN:
            self.issue(entry, f"unsupported event kind {kind}; retained as opaque", "opaque")
        operation = ir.OperationInstance(identifier, definition, process, thread,
                                         start_ns=start, end_ns=end, metadata=known_metadata)
        self.evidence.instances[identifier] = operation
        entry["normalized"].append({"kind": "operation_instance", "id": identifier.wire})
        if duration is not None:
            self.measurement("duration", duration, "ns", entry, identifier.wire, instance=identifier)
        if kind == "python_call":
            key = self.key(record)
            if key is not None:
                self.calls[key].append((operation, entry, record))
            else:
                self.issue(entry, "call cannot be paired without process/thread/invocation", "unmatched")
        parent = metadata.get("parent_invocation_id")
        if parent is not None and kind not in _GPU and kind != "cuda_barrier":
            self.parents.append((operation, record, entry, parent))
        for role in ("inputs", "outputs"):
            snapshots = record.get(role, [])
            if not isinstance(snapshots, list):
                self.issue(entry, f"{role} is not an array")
                continue
            for index, snapshot in enumerate(snapshots):
                self.snapshot(snapshot, role, index, operation, entry)
        self.resources(operation, record, entry)
        if kind in _ALLOCATION | _FREE:
            self.memory_event(operation, record, entry)
        if kind in _GPU:
            selectors = (metadata.get("process_id"), metadata.get("clock_domain"),
                         resource.get("device"), resource.get("context"), resource.get("stream"))
            if all(_scalar_id(item) for item in selectors) and start is not None and end is not None:
                self.streams[_hash(selectors)].append((operation, entry))
            else:
                self.issue(entry, "incomplete stream/clock/context identity; no same-stream ordering")
        return operation

    def resources(self, operation, record, entry):
        metadata, resource = record.get("metadata", {}), record.get("resource", {})
        selectors = [(ir.ResourceKind.PROCESS, {"process": operation.process_id})]
        if record["kind"] not in _GPU:
            selectors.append((ir.ResourceKind.THREAD, {"process": operation.process_id, "thread": operation.thread_id}))
        if resource.get("device") not in (None, "unknown", ""):
            selectors.append((ir.ResourceKind.DEVICE, {"process": operation.process_id, "device": resource["device"]}))
        if record["kind"] in _GPU and resource.get("stream") is not None:
            selectors.append((ir.ResourceKind.STREAM, {
                "process": operation.process_id, "device": resource.get("device"),
                "context": resource.get("context"), "stream": resource["stream"],
                "clock_domain": metadata.get("clock_domain")}))
        for kind, selector in selectors:
            rid = ir.ResourceID(f"{self.namespace}:{kind.value}:{_hash(selector)}")
            if rid not in self.semantic.resources:
                self.semantic.resources[rid] = ir.ResourceRequirement(
                    rid, kind, json.dumps(selector, sort_keys=True), evidence=(self.claim(entry),))
            self.evidence.external_references.add((ir.EvidenceNodeKind.RESOURCE, rid.wire))
            self.edge(ir.EvidenceRelation.USES_RESOURCE, ir.EvidenceNodeKind.OPERATION_INSTANCE,
                      operation.id, ir.EvidenceNodeKind.RESOURCE, rid, entry)

    def snapshot(self, snapshot, role, index, operation, entry):
        if not isinstance(snapshot, dict):
            self.issue(entry, f"{role}[{index}] is not a value snapshot")
            return
        token = f"{self.namespace}:record:{entry['line']}:{role}:{index}"
        logical = ir.LogicalValueID(f"snapshot:{token}")
        version = ir.ValueVersionID(logical, 0)
        hints = {key: value for key, value in snapshot.items() if key in _VALUE_FIELDS}
        semantic_type = str(snapshot.get("type") or "unknown")
        self.values.logical_values[logical] = ir.LogicalValue(
            logical, semantic_type, "Provisional capture; cross-snapshot equivalence unresolved",
            metadata={"identity_basis": "capture_occurrence", "equivalence": "UNKNOWN"})
        self.values.versions[version] = ir.ValueVersion(version, metadata={"legacy_hints": hints})
        object_token = snapshot.get("object_id")
        if isinstance(object_token, str) and object_token:
            # The old identity contains an address, not a lifetime generation.
            object_id = ir.ObjectID(f"snapshot:{token}")
            self.values.bindings.append(ir.ObjectBinding(
                object_id, version, ir.BindingRelation.UNKNOWN, scope=entry["raw_reference"],
                metadata={"legacy_object_id": object_token, "lifetime_identity": "unresolved"}))
        device = str(snapshot.get("device") or "unknown")
        region_id = None
        shape, strides, offset = snapshot.get("shape"), snapshot.get("strides"), snapshot.get("offset")
        geometry_valid = (isinstance(shape, list) and isinstance(strides, list)
                          and len(shape) == len(strides) and all(_integer(x) and x >= 0 for x in shape)
                          and all(_integer(x) for x in strides) and _integer(offset) and offset >= 0
                          and offset + sum(min(0, (size - 1) * stride) for size, stride in zip(shape, strides)) >= 0)
        if snapshot.get("storage_id") and geometry_valid:
            allocation = ir.StorageAllocationID(f"snapshot:{token}")
            self.values.allocations[allocation] = ir.StorageAllocation(
                allocation, device, nbytes=None, allocator_token=str(snapshot["storage_id"]),
                lifetime_scope=entry["raw_reference"], metadata={"allocation_event": False,
                    "identity_basis": "snapshot_only", "legacy_logical_version": snapshot.get("logical_version")})
            region_id = ir.StorageRegionID(f"snapshot:{token}")
            self.values.regions[region_id] = ir.StorageRegion(
                region_id, allocation, offset, tuple(shape), tuple(strides),
                str(snapshot.get("dtype") or "unknown"), device)
            self.evidence.external_references.add((ir.EvidenceNodeKind.STORAGE_REGION, region_id.wire))
            self.edge(ir.EvidenceRelation.USES_STORAGE, ir.EvidenceNodeKind.OPERATION_INSTANCE,
                      operation.id, ir.EvidenceNodeKind.STORAGE_REGION, region_id, entry)
        elif snapshot.get("storage_id"):
            self.issue(entry, f"{role}[{index}] has incomplete/invalid storage geometry")
        materialization = ir.MaterializationID(f"snapshot:{token}")
        self.values.materializations[materialization] = ir.Materialization(
            materialization, version, str(snapshot.get("representation") or "captured_object"),
            device, region=region_id, validity_scope=entry["raw_reference"],
            metadata={"identity_basis": "snapshot_only", "readiness": "UNKNOWN"})
        observation_id = f"observation:{token}"
        self.evidence.observations[observation_id] = ir.ValueObservation(
            observation_id, version, operation.id, materialization,
            "input" if role == "inputs" else "output", metadata={"legacy_hints": hints,
                "raw_reference": entry["raw_reference"], "logical_equivalence": "UNKNOWN"})
        self.edge(ir.EvidenceRelation.OBSERVED_READ if role == "inputs" else ir.EvidenceRelation.PRODUCES,
                  ir.EvidenceNodeKind.OPERATION_INSTANCE, operation.id,
                  ir.EvidenceNodeKind.VALUE_OBSERVATION, observation_id, entry,
                  inferred=role == "inputs", assumptions=("captured argument; actual read not proven",) if role == "inputs" else ())
        effect = operation.metadata.get("legacy_effect", {})
        if isinstance(effect, dict):
            tokens = {str(snapshot.get("logical_version")), str(snapshot.get("object_id"))}
            writes = effect.get("writes", [])
            if isinstance(writes, list) and all(isinstance(item, str) for item in writes) and tokens.intersection(writes):
                self.edge(ir.EvidenceRelation.OBSERVED_WRITE, ir.EvidenceNodeKind.OPERATION_INSTANCE,
                          operation.id, ir.EvidenceNodeKind.VALUE_OBSERVATION, observation_id, entry)

    def memory_event(self, operation, record, entry):
        resource = record.get("resource", {})
        # Explicit allocation event only. A pointer without allocator lifetime
        # correlation cannot link a later free to this allocation safely.
        allocation = ir.StorageAllocationID(f"event:{self.namespace}:{entry['line']}")
        nbytes = resource.get("bytes", resource.get("nbytes"))
        if nbytes is not None and (not _integer(nbytes) or nbytes < 0):
            self.issue(entry, "invalid allocation size")
            nbytes = None
        self.values.allocations[allocation] = ir.StorageAllocation(
            allocation, str(resource.get("device") or "unknown"), nbytes=nbytes,
            allocator_token=str(resource.get("allocation_id") or resource.get("storage_id") or "unknown"),
            lifetime_scope=entry["raw_reference"], metadata={"allocation_event": record["kind"] in _ALLOCATION,
                "free_observation": record["kind"] in _FREE, "lifetime_pairing": "unresolved"})
        self.evidence.external_references.add((ir.EvidenceNodeKind.ALLOCATION, allocation.wire))
        self.edge(ir.EvidenceRelation.USES_STORAGE, ir.EvidenceNodeKind.OPERATION_INSTANCE,
                  operation.id, ir.EvidenceNodeKind.ALLOCATION, allocation, entry)

    def finish(self):
        paired = set()
        for key, calls in self.calls.items():
            if len(calls) > 1:
                for _, entry, _ in calls:
                    self.issue(entry, "duplicate invocation in process/thread scope; pairing disabled")
        for record, entry in self.returns:
            candidates = self.calls.get(self.key(record, record.get("metadata", {}).get("paired_invocation_id")), [])
            match = candidates[0] if len(candidates) == 1 else None
            if match is not None:
                operation, call_entry, call = match
                metadata = record.get("metadata", {})
                end = record.get("ts_ns")
                valid = (operation.id not in paired and record.get("code_id") == call.get("code_id")
                         and isinstance(metadata.get("clock_domain"), str)
                         and metadata.get("clock_domain") == call.get("metadata", {}).get("clock_domain")
                         and _integer(end) and operation.start_ns is not None and end >= operation.start_ns)
            else:
                valid = False
            if not valid:
                self.issue(entry, "return has no unique compatible call", "unmatched")
                orphan = dict(record, kind="unmatched_python_return")
                self.instance(orphan, entry)
                continue
            paired.add(operation.id)
            operation.end_ns = end
            operation.metadata.update({"completion": "paired_return", "return_reference": entry["raw_reference"],
                                       "outcome": metadata.get("outcome", "unknown")})
            entry["normalized"].append({"kind": "operation_instance", "id": operation.id.wire})
            for index, snapshot in enumerate(record.get("outputs", [])):
                self.snapshot(snapshot, "outputs", index, operation, entry)
        for calls in self.calls.values():
            for operation, entry, _ in calls:
                if operation.id not in paired:
                    self.issue(entry, "call has no compatible return; completion remains unknown", "unmatched")
        for operation, record, entry, parent in self.parents:
            candidates = self.calls.get(self.key(record, parent), [])
            if len(candidates) == 1 and candidates[0][0].id != operation.id:
                parent_op, parent_entry, parent_record = candidates[0]
                # Earlier call boundary prevents corrupt cyclic parent claims.
                if parent_entry["line"] < entry["line"]:
                    operation.parent = parent_op.id
                    self.edge(ir.EvidenceRelation.CONTROLS_INSTANCE, ir.EvidenceNodeKind.OPERATION_INSTANCE,
                              parent_op.id, ir.EvidenceNodeKind.OPERATION_INSTANCE, operation.id, entry)
                    continue
            self.issue(entry, "parent invocation is missing/ambiguous; no parent edge")
        for record, entry, control in self.controls:
            candidates = self.calls.get(self.key(record), [])
            if len(candidates) == 1:
                operation = candidates[0][0]
                entry["control"]["owning_operation"] = operation.id.wire
                operation.metadata.setdefault("control_observations", []).append(control)
                self.edge(ir.EvidenceRelation.OBSERVED_CONTROL, ir.EvidenceNodeKind.OPERATION_INSTANCE,
                          operation.id, ir.EvidenceNodeKind.CONTROL_EVENT, control, entry)
            else:
                self.issue(entry, "control observation has no unique owning call", "unmatched")
        for spans in self.streams.values():
            spans.sort(key=lambda pair: (pair[0].start_ns, pair[0].end_ns, pair[0].id.wire))
            for (previous, _), (current, entry) in zip(spans, spans[1:]):
                if previous.end_ns <= current.start_ns and previous.start_ns < current.start_ns:
                    self.edge(ir.EvidenceRelation.HAPPENS_BEFORE, ir.EvidenceNodeKind.OPERATION_INSTANCE,
                              previous.id, ir.EvidenceNodeKind.OPERATION_INSTANCE, current.id, entry,
                              inferred=True,
                              assumptions=("same process, clock, device, context and CUDA stream",))
                else:
                    self.issue(entry, "same-stream timestamps overlap/tie; order not asserted")
        bundle = ir.IRBundle(self.semantic, self.evidence, self.values)
        validation = bundle.assert_valid()
        counts = Counter(entry["status"] for entry in self.entries)
        report = {"schema": "scar.trace.v2.coverage", "schema_version": 1,
                  "source": self.source, "namespace": self.namespace,
                  "source_sha256": self.raw_hash.hexdigest(), "raw_records": len(self.entries),
                  "accounted_records": sum(counts.values()), "status_counts": {
                      key: counts[key] for key in ("normalized", "ambiguous", "opaque", "unmatched", "invalid")},
                  "kind_counts": dict(sorted(self.counts.items())),
                  "records": self.entries, "graph_counts": {name: value["counts"] for name, value in validation["graphs"].items()},
                  "scope": {"collector": "v1 trace", "semantics": "runtime stubs; G5 correspondence pending",
                            "values": "snapshot-scoped provisional identity; no cross-snapshot equivalence",
                            "effects": "legacy evidence retained; completeness not promoted",
                            "timing": "clock domains retained; no host/GPU clock alignment",
                            "optimization": "none"}, "valid": validation["valid"]}
        return NormalizationResult(bundle, report)


def normalize_records(records: Iterable[dict[str, Any]], *, source: str = "memory",
                      namespace: str = "memory") -> NormalizationResult:
    """Normalize generic record fixtures without running or importing a workload."""
    normalizer = _Normalizer(source, namespace)
    for line, record in enumerate(records, 1):
        raw = (json.dumps(record, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode()
        normalizer.raw(record, line, raw)
    return normalizer.finish()


def normalize_trace(path: str | Path, *, namespace: str | None = None) -> NormalizationResult:
    """Read each physical JSONL line once per pass, retaining malformed lines."""
    path = Path(path).resolve()
    if path.is_dir():
        path = path / "events.jsonl"
    if namespace is None:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        namespace = "trace:" + digest.hexdigest()
    normalizer = _Normalizer(str(path), namespace)
    with path.open("rb") as stream:
        for line, raw in enumerate(stream, 1):
            try:
                record = json.loads(raw, object_pairs_hook=_unique_object,
                                    parse_constant=_no_constant, parse_float=_finite_float)
            except (ValueError, UnicodeError) as error:
                normalizer.raw(None, line, raw, f"invalid JSON: {error}")
            else:
                normalizer.raw(record, line, raw)
    return normalizer.finish()


__all__ = ["NormalizationResult", "normalize_records", "normalize_trace"]
