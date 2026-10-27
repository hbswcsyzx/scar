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
_INVOCATION = "native-port:capture:ca66b69a8cfc3c1b88e0c22e8ec00d58d735fd016d16edf85e8cf0ac51eb5fc3:9:invoke"
_PROGRAM_SHA = "d70685d1521bf28527fa32beb319fa0f9d66db257b6df3ce2559f013141d5bc6"
_EXECUTION_SHA = "d58eaa17e99f207f5a7780ab6e7904615e9376ab472dfcdb81ce7922a28f6dbc"
_NAVIGATION_SHA = "4436b171be0dec2782e7843bc097227d675efa5e33155a6e8a2bf2408b4b6f72"
_STORAGE_SHA = "d127c95a2ff1b1d848288c83ef3cb3785f55f0f2c68d0918f3ef7d280b1de7c2"


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
                        default=Path(__file__).with_name("ACTUAL.json"))
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
    input_zero = completion.input_ports[0]
    if type(input_zero.reference).__name__ != "NativeInputRef":
        raise TypeError("the first source port is not the original native self input")
    start = time.monotonic()
    allocation = query_native_input_allocation(
        navigation,
        storage_index,
        native_input=input_zero.reference,
        execution=execution_artifact,
        derive_region=True,
        max_input_bytes=256_000_000,
        max_seconds=60,
    )
    allocation_seconds = time.monotonic() - start

    output_denotation = completion.output_ports[0].denotation
    input_denotation = input_zero.denotation
    same_object_id = None
    if output_denotation is not None and input_denotation is not None:
        same_object_id = output_denotation.identity.object.object.value

    report = {
        "schema": "scar.native-normal-completion-actual",
        "schema_version": 1,
        "qualification": "ONE_RETAINED_NATIVE_INSTANCE_NORMAL_COMPLETION_AND_SELF_INPUT_ALLOCATION_QUERY",
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
        ],
        "timing_seconds": {
            "typed_program_and_execution_load": round(load_seconds, 6),
            "normal_completion_query": round(completion_seconds, 6),
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
            "device": allocation["allocation"]["device"],
            "nbytes": allocation["allocation"]["nbytes"],
            "geometry": allocation["geometry"],
            "derived_region_result": allocation.get("geometry"),
            "output_allocation_binding": "NOT_ESTABLISHED",
            "limits": [
                "allocation is observed for the original self input before the selected invocation",
                "the ETO output carries no same-point physical geometry or allocation epoch",
                "this input allocation is not attached to output solely from shared ObjectIdentity",
            ],
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
