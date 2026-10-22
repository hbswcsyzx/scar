"""Bind allocator observations to existing lifetime records after value freeze.

The output is a source-backed execution fragment, not a fabricated canonical
ProgramGraph or an assertion that the whole execution has been reconstructed.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

from scar.ir.execution.common import EvidencePoint, Unresolved
from scar.ir.execution.coordinates import ExecutionRun, ProcessInstance
from scar.ir.execution.ids import ProcessInstanceID, RunID, TargetLifetimeEventID
from scar.ir.execution.resources import AllocationTarget
from scar.ir.execution.snapshot import ExternalSnapshots, SnapshotError, external_artifact
from scar.ir.execution.validity import LifetimeEventKind, TargetLifetimeEvent
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.record_codec import encode


PROFILE_SCHEMA = "scar.native-memory-profile"
KINETO_SCHEMA = "pytorch.kineto.chrome-trace.v1"


def _receipt(result, kineto):
    """Locate the collector receipt mechanically; missing flags stay unknown."""
    path = Path(kineto.uri).parent / ("execution-evidence." + str(result.report["pid"]) + ".json")
    if not path.is_file():
        return None, None, None
    with path.open("rb") as stream:
        payload = stream.read(2_000_001)
    if len(payload) > 2_000_000:
        raise ValueError("native capture receipt exceeds its byte limit")
    document = json.loads(payload)
    if (document.get("schema") != "scar.execution-evidence-collection"
            or document.get("schema_version") != 1 or type(document.get("schema_version")) is not int
            or document.get("pid") != result.report["pid"]
            or document.get("provider", {}).get("torch_git_version") != result.report["provider_revision"]
            or document.get("configuration", {}).get("profile_memory") is not True):
        raise ValueError("native capture receipt differs from the supplied memory capture")
    for key, artifact in (("kineto", result.report["artifacts"]["kineto"]),
                          ("execution_trace", result.report["artifacts"]["eto"])):
        declared = document.get("artifacts", {}).get(key, {})
        actual_name = Path(artifact["path"]).name.removesuffix(".gz")
        if Path(declared.get("path", "")).name != actual_name or declared.get("size_bytes") != artifact["size_bytes"]:
            raise ValueError("native capture receipt does not name the supplied raw artifacts")
    experimental = document.get("configuration", {}).get("experimental_config", {})
    adjust = experimental.get("adjust_timestamps") if type(experimental) is dict else None
    if adjust is not None and type(adjust) is not bool:
        raise ValueError("captured timestamp adjustment must be an exact bool or absent")
    artifact = ProviderArtifact(str(path.resolve()), sha256(payload).hexdigest(), len(payload),
                                "scar.execution-evidence-collection")
    return artifact, payload, adjust


class _FragmentContext:
    """Same external binding checks as execution validation, without fake code."""
    def __init__(self, values, artifact, payloads, run, process):
        self.snapshots = ExternalSnapshots({artifact.sha256: values}, artifact_bytes=payloads)
        self.processes, self.runs = {process.id: process}, {run.id: run}
        self.issue_counts, self.gap_counts = Counter(), Counter()
        self.examples = []

    def issue(self, code, path, message):
        self.issue_counts[code] += 1
        if len(self.examples) < 8:
            self.examples.append({"code": code, "path": str(path), "message": message})

    def gap(self, code, path, message):
        self.gap_counts[code] += 1

    def external_values(self, artifact, path):
        from scar.ir.v2.values import ValueGraph
        try:
            graph = self.snapshots.graph(artifact, ValueGraph)
        except SnapshotError as error:
            self.issue(error.code, path, str(error))
            return None
        if graph is None:
            self.gap("external_graph_unavailable", path, "exact value snapshot unavailable")
        return graph


def export_native_memory(result, output):
    """Return JSON-safe existing IR records and validate every raw correspondence."""
    memory = result.memory
    if memory is None or memory.source_document is None:
        return None
    raw = result.report["artifacts"]["kineto"]
    kineto = ProviderArtifact(raw["path"], raw["sha256"], raw["size_bytes"], KINETO_SCHEMA)
    if result.raw_kineto_bytes is None:
        raise ValueError("native memory needs exact retained Kineto bytes for independent binding")
    capture, capture_payload, adjust = _receipt(result, kineto)
    profile = {"schema": PROFILE_SCHEMA, "schema_version": 1, "contract": {
        "kineto": encode(kineto), "scope": result.report["scope"], "pid": result.report["pid"],
        "provider_revision": result.report["provider_revision"], "adjust_timestamps": adjust,
        "capture_manifest": encode(capture)}}
    profile_payload = (json.dumps(profile, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    profile_path = Path(output) / "native-memory-profile.json"
    with profile_path.open("xb") as stream:
        stream.write(profile_payload)
    profile_artifact = ProviderArtifact(str(profile_path.resolve()), sha256(profile_payload).hexdigest(),
                                         len(profile_payload), PROFILE_SCHEMA)
    protocol = ProviderFactReference(profile_artifact, "#/contract")
    values_artifact = external_artifact(result.bundle.values, str((Path(output) / "native-memory-values.json.gz").resolve()))
    # These coordinates denote the supplied native capture window. They do not
    # silently merge it with a Python run or manufacture source occurrences.
    run_id = RunID(result.report["scope"] + ":run")
    process_id = ProcessInstanceID(result.report["scope"] + ":process:" + str(result.report["pid"]))
    capture_source = ProviderFactReference(kineto, "#/traceEvents")
    run = ExecutionRun(run_id, capture_source)
    process = ProcessInstance(process_id, run_id, result.report["pid"], capture_source)
    payloads = {kineto.sha256: result.raw_kineto_bytes, profile_artifact.sha256: profile_payload}
    if capture is not None:
        payloads[capture.sha256] = capture_payload
    ctx = _FragmentContext(result.bundle.values, values_artifact, payloads, run, process)
    from scar.ir.execution.native_memory_binding import resolve_native_memory_claim
    rows, statuses, flags, conditions = [], Counter(), Counter(), set()
    for item in memory.rows:
        target = AllocationTarget(values_artifact, item["allocation"])
        for field, kind in (("birth_index", LifetimeEventKind.LIVE), ("free_index", LifetimeEventKind.RETIRED)):
            index = item[field]
            if index is None:
                continue
            fact = ProviderFactReference(kineto, "#/traceEvents/" + str(index))
            point = EvidencePoint(run_id, process_id, fact)
            row = TargetLifetimeEvent(TargetLifetimeEventID(result.report["scope"] + ":memory-lifetime:" + str(index)),
                target, kind, point,
                Unresolved("Kineto receipt has no canonical source inventory projection", point),
                Unresolved("canonical allocation/free state effect is not connected", point), protocol, fact)
            resolved = resolve_native_memory_claim(ctx, row, str(row.id))
            if resolved is None:
                raise ValueError("generated allocator profile was not recognized")
            statuses[resolved["status"]] += 1
            for flag in ("matched", "birth_verified", "free_verified", "ordering_qualified"):
                flags[flag] += bool(resolved.get(flag))
            conditions.update(resolved.get("conditions", ()))
            rows.append(row)
    summary = {"rows": len(rows), "status_counts": dict(statuses), "flags": dict(flags),
        "issues": dict(ctx.issue_counts), "binding_gaps": dict(ctx.gap_counts), "examples": ctx.examples,
        "conditions": sorted(conditions), "canonical_stages_connected": False, "canonical_effects_connected": False,
        "physical_allocation_established": False, "execution_model_imported": False, "transformation_authorized": False}
    result.report["memory"]["lifetime_binding"] = summary
    if ctx.issue_counts or statuses.get("MISMATCH"):
        raise ValueError("native allocation lifetime correspondence contradicted original evidence: " + repr(summary))
    return {"schema": "scar.native-memory-execution-fragment", "schema_version": 1,
        "runs": encode((run,)), "processes": encode((process,)), "target_lifetime_events": encode(tuple(rows)),
        "values_artifact": encode(values_artifact), "kineto_artifact": encode(kineto),
        "profile_artifact": encode(profile_artifact), "capture_manifest_artifact": encode(capture),
        "validation": summary, "whole_model_established": False}


__all__ = ["export_native_memory", "PROFILE_SCHEMA", "KINETO_SCHEMA"]
