#!/usr/bin/env python3
"""Reproduce the bounded normal-completion + original self-input lookup."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from scar.analysis.native_completion import query_native_normal_completion
from scar.analysis.native_input_storage_bridge import query_native_input_allocation
from scar.analysis.native_port_geometry import (
    connect_observed_input_region,
    query_native_port_geometries,
)
from scar.ir.execution.codec import loads as load_execution
from scar.ir.execution.ids import OperationOccurrenceID
from scar.ir.execution.model import ExecutionModel
from scar.ir.program.codec import loads as load_program
from scar.ir.program.model import ProgramGraph
from scar.ir.program.providers import ProviderArtifact
from scar.ir.record_codec import encode


_MAIN = Path("/home/zyf/AAA/scar-worktrees/structured-program-model")
_SOURCE = _MAIN / "artifacts/experiments/native_inputs_full_20261026/attempt05/native-input-connections"
_PROGRAM = _SOURCE / "program.json"
_EXECUTION = _SOURCE / "shards/000000/execution.json"
_NAVIGATION = _MAIN / "artifacts/experiments/native_inputs_full_20261026/attempt05/port-navigation/manifest.json"
_STORAGE_INDEX = Path("/home/zyf/AAA/scar-worktrees/source-entry-project/artifacts/experiments/tensor_gpu_reference_query_20261026/locator-index/manifest.json")
_PORT_QUALIFICATIONS = _SOURCE / "shards/000000/port-qualifications/manifest.json"
_INVOCATION = "native-port:capture:ca66b69a8cfc3c1b88e0c22e8ec00d58d735fd016d16edf85e8cf0ac51eb5fc3:9:invoke"
_PROGRAM_SHA = "d70685d1521bf28527fa32beb319fa0f9d66db257b6df3ce2559f013141d5bc6"
_EXECUTION_SHA = "d58eaa17e99f207f5a7780ab6e7904615e9376ab472dfcdb81ce7922a28f6dbc"
_NAVIGATION_SHA = "4436b171be0dec2782e7843bc097227d675efa5e33155a6e8a2bf2408b4b6f72"
_STORAGE_SHA = "d127c95a2ff1b1d848288c83ef3cb3785f55f0f2c68d0918f3ef7d280b1de7c2"
_PORT_QUALIFICATIONS_SHA = "c57875f849794a9b8cb3e2a4494b0f6aadf53d41de209f17b8f698be44b52e71"


def _artifact(path: Path, schema: str, expected_sha: str) -> ProviderArtifact:
    raw = path.read_bytes()
    actual_sha = hashlib.sha256(raw).hexdigest()
    if actual_sha != expected_sha:
        raise ValueError(f"artifact SHA differs for {path}: {actual_sha}")
    return ProviderArtifact(str(path), actual_sha, len(raw), schema)


def _occurrence(port):
    return {
        "reference": encode(port.reference),
        "use": encode(port.use),
        "value": encode(port.value),
        "denotation": encode(port.denotation) if port.denotation is not None else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path,
                        default=Path(__file__).with_name("ACTUAL_GEOMETRY.json"))
    args = parser.parse_args()

    program_artifact = _artifact(_PROGRAM, "scar.program-graph", _PROGRAM_SHA)
    execution_artifact = _artifact(_EXECUTION, "scar.execution-model", _EXECUTION_SHA)
    t0 = time.monotonic()
    program = load_program(_PROGRAM.read_text(encoding="utf-8"))
    execution = load_execution(_EXECUTION.read_text(encoding="utf-8"))
    load_seconds = time.monotonic() - t0
    if type(program) is not ProgramGraph or type(execution) is not ExecutionModel:
        raise TypeError("normal codecs did not return original typed graph records")

    start = time.monotonic()
    completion = query_native_normal_completion(
        program, execution, OperationOccurrenceID(_INVOCATION))
    completion_seconds = time.monotonic() - start
    if completion.same_object_reference_pairs != ((0, 0),):
        raise ValueError("the selected ETO output did not preserve exact self ObjectIdentity")

    navigation = _artifact(_NAVIGATION, "scar.native-input-port-navigation", _NAVIGATION_SHA)
    storage_index = _artifact(_STORAGE_INDEX, "scar.tensor-storage-locator-index", _STORAGE_SHA)
    qualification_manifest = _artifact(
        _PORT_QUALIFICATIONS, "scar.native-capture-table-chunks", _PORT_QUALIFICATIONS_SHA)
    start = time.monotonic()
    port_geometry = query_native_port_geometries(
        completion, execution, qualification_manifest,
        max_input_bytes=32_000_000, max_seconds=60)
    geometry_seconds = time.monotonic() - start
    input_zero_geometry = next(
        row for row in port_geometry.geometries
        if row.reference == completion.input_ports[0].reference)
    output_zero_geometry = next(
        row for row in port_geometry.geometries
        if row.reference == completion.output_ports[0].reference)
    if (input_zero_geometry.storage_offset != 0 or output_zero_geometry.storage_offset != 0
            or input_zero_geometry.tensor_id != output_zero_geometry.tensor_id
            or input_zero_geometry.storage_id != output_zero_geometry.storage_id
            or input_zero_geometry.numel != 1 or input_zero_geometry.itemsize != 4
            or input_zero_geometry.device != "cpu" or input_zero_geometry.shape != ()
            or input_zero_geometry.strides != ()
            or output_zero_geometry.numel != input_zero_geometry.numel
            or output_zero_geometry.itemsize != input_zero_geometry.itemsize
            or output_zero_geometry.device != input_zero_geometry.device
            or output_zero_geometry.shape != input_zero_geometry.shape
            or output_zero_geometry.strides != input_zero_geometry.strides):
        raise ValueError("unexpected geometry result")
    input_zero = completion.input_ports[0]
    if type(input_zero.reference).__name__ != "NativeInputRef":
        raise TypeError("the first source port is not the original native self input")
    start = time.monotonic()
    allocation = query_native_input_allocation(
        navigation,
        storage_index,
        native_input=input_zero.reference,
        execution=execution_artifact,
        derive_region=False,
        max_input_bytes=256_000_000,
        max_seconds=60,
    )
    allocation_seconds = time.monotonic() - start
    observed_region = connect_observed_input_region(
        input_zero_geometry, allocation, execution_artifact)

    output_denotation = completion.output_ports[0].denotation
    input_denotation = input_zero.denotation
    same_object_id = None
    if output_denotation is not None and input_denotation is not None:
        same_object_id = output_denotation.identity.object.object.value

    report = {
        "schema": "scar.native-normal-completion-actual",
        "schema_version": 2,
        "qualification": "ONE_RETAINED_NATIVE_INSTANCE_NORMAL_COMPLETION_AND_EXACT_ETO_GEOMETRY_TO_SELF_ALLOCATION_JOIN",
        "scope": "original capture ca66..., ETO node63 at #/nodes/50, canonical sequence9; no raw ETO scan or new capture",
        "input_artifacts": [
            {"uri": str(_PROGRAM), "schema": "scar.program-graph",
             "sha256": _PROGRAM_SHA, "size_bytes": program_artifact.size_bytes},
            {"uri": str(_EXECUTION), "schema": "scar.execution-model",
             "sha256": _EXECUTION_SHA, "size_bytes": execution_artifact.size_bytes},
            {"uri": str(_NAVIGATION), "schema": navigation.schema,
             "sha256": navigation.sha256, "size_bytes": navigation.size_bytes},
            {"uri": str(_STORAGE_INDEX), "schema": storage_index.schema,
             "sha256": storage_index.sha256, "size_bytes": storage_index.size_bytes},
            {"uri": str(_PORT_QUALIFICATIONS), "schema": qualification_manifest.schema,
             "sha256": qualification_manifest.sha256, "size_bytes": qualification_manifest.size_bytes},
        ],
        "timing_seconds": {
            "typed_program_and_execution_load": round(load_seconds, 6),
            "normal_completion_query": round(completion_seconds, 6),
            "receipt_bound_port_geometry_query": round(geometry_seconds, 6),
            "self_input_allocation_query": round(allocation_seconds, 6),
        },
        "completion": {
            "invocation": encode(completion.invocation),
            "normal_transfer": encode(completion.normal_transfer),
            "normal_return": encode(completion.normal_return),
            "boundary": encode(completion.boundary),
            "invocation_evidence": encode(completion.invocation_evidence),
            "completion_evidence": encode(completion.completion_evidence),
            "input_ports": [_occurrence(row) for row in completion.input_ports],
            "output_ports": [_occurrence(row) for row in completion.output_ports],
            "same_object_reference_pairs_output_input": [list(row) for row in completion.same_object_reference_pairs],
            "same_object_reference_id": same_object_id,
            "state_input": encode(completion.state_input) if completion.state_input else None,
            "state_output": encode(completion.state_output) if completion.state_output else None,
            "state_effect": encode(completion.state_effect) if completion.state_effect else None,
            "state_interface_status": completion.state_interface_status,
            "effects_complete": completion.effects_complete,
            "normal_basis": completion.normal_basis,
            "limits": [
                "selected NORMAL route and original output leaf are preserved from typed IR; no write/effect semantics are inferred",
                "same ObjectIdentity means same observed Tensor object reference, not same content version or storage epoch",
                "runtime implementation-code identity and exact dispatch branch are not established",
            ],
        },
        "self_input_allocation": {
            "input_reference": encode(input_zero.reference),
            "value_occurrence": encode(input_zero.value),
            "selector": allocation["selector"],
            "provider_epoch": allocation["provider_epoch"],
            "allocation_id": allocation["allocation"]["id"],
            "allocation_source": allocation["allocation_source"],
            "device": allocation["allocation"]["device"],
            "nbytes": allocation["allocation"]["nbytes"],
            "observed_region_connection": {
                "status": "DERIVED_FROM_EXACT_ETO_INPUT_GEOMETRY_AND_OBSERVED_PROVIDER_EPOCH",
                "region": encode(observed_region.region),
                "allocation": encode(observed_region.allocation),
                "allocation_source": encode(observed_region.allocation_source),
                "provider_epoch_source": encode(observed_region.provider_epoch_source),
                "geometry_source": encode(observed_region.geometry.source),
                "qualification_source": encode(observed_region.geometry.qualification_source),
                "offset_observed": observed_region.region.offset,
                "stored_as_new_IR_record": False,
                "contents_or_readiness_established": False,
            },
            "output_allocation_binding": "NOT_ESTABLISHED",
            "limits": [
                "allocation is observed for the original self input before the selected invocation",
                "input geometry and offset come from the exact original ETO boxed leaf and are joined to the same NativeInputRef allocation query",
                "ETO storage_id is a pointer token, not the profiler allocation epoch ID",
                "output ETO geometry is observed, but no output profiler allocation epoch is attached",
                "the input allocation is not attached to output solely from shared ObjectIdentity",
            ],
        },
        "port_geometry": {
            "manifest": encode(port_geometry.qualification_manifest),
            "program_snapshot": encode(port_geometry.program_snapshot),
            "eto_source": encode(port_geometry.eto_source),
            "measurements": port_geometry.measurements,
            "source_raw_eto_read": False,
            "without_tensor_geometry": [
                {"reference": encode(reference), "source": encode(source) if source else None}
                for reference, source in port_geometry.without_tensor_geometry
            ],
            "geometries": [
                {"reference": encode(row.reference), "source": encode(row.source),
                 "qualification_source": encode(row.qualification_source),
                 "direction": row.direction, "native_path": list(row.native_path),
                 "native_type": row.native_type,
                 "native_tensor_tuple": [row.tensor_id, row.storage_id, row.storage_offset,
                                         row.numel, row.itemsize, row.device],
                 "shape": list(row.shape), "strides": list(row.strides)}
                for row in port_geometry.geometries
            ],
            "storage_id_semantics": "ETO observer pointer token; not provider allocation epoch ID",
        },
    }
    args.output.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output),
                      "timing_seconds": report["timing_seconds"],
                      "input_ports": len(completion.input_ports),
                      "output_ports": len(completion.output_ports),
                      "same_object_reference_pairs_output_input": report["completion"]["same_object_reference_pairs_output_input"],
                      "input_allocation": report["self_input_allocation"]["allocation_id"],
                      "output_allocation_binding": "NOT_ESTABLISHED"}, sort_keys=True))


if __name__ == "__main__":
    main()
