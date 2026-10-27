#!/usr/bin/env python3
"""One bounded SCAR snapshot + owned OS/native smoke capture; no LeWM import."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parent
SOURCE = Path("/home/zyf/AAA/scar-worktrees/structured-program-model/artifacts/experiments/lewm_snapshot_ports_20261027/collector-source")
PYTHON = Path("/home/zyf/miniconda3/envs/lewm/bin/python")
CAPTURE = ROOT / "capture"
TRACE = CAPTURE / "trace"
COORDINATES = CAPTURE / "capture-coordinates.json"
OS_PARTITIONS = ROOT / "os-resource-fragment"
KNOWN_SOURCE_TREE_SHA256 = "17f64b651f02e40e500325277d261a7f6542b6cc375e1ae9c237f5fd3cb555c2"


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False,
                                allow_nan=False) + "\n", encoding="utf-8")


def sha(path: Path) -> dict:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            size += len(block)
            digest.update(block)
    return {"path": str(path), "bytes": size, "sha256": digest.hexdigest()}


def verify_frozen_source() -> dict:
    declaration = json.loads((SOURCE.parent / "COLLECTOR_SOURCE.json").read_text())
    if declaration["source_tree_sha256"] != KNOWN_SOURCE_TREE_SHA256:
        raise ValueError("frozen collector source tree receipt changed")
    for row in declaration["files"]:
        candidate = SOURCE / row["path"]
        receipt = sha(candidate)
        if receipt["bytes"] != row["bytes"] or receipt["sha256"] != row["sha256"]:
            raise ValueError("frozen collector source member changed: " + row["path"])
    return {"manifest": sha(SOURCE.parent / "COLLECTOR_SOURCE.json"),
            "source_tree_sha256": declaration["source_tree_sha256"],
            "file_count": declaration["file_count"], "total_bytes": declaration["total_bytes"]}


def command() -> list[str]:
    return [str(PYTHON), "-B", "-m", "scar.cli", "trace",
        "--calls-only", "--python-call-targets", "--execution-evidence", "--tensor-physical",
        "--capture-transport", "snapshot", "--snapshot-buffer-bytes", "8388608",
        "--out", str(TRACE), "--project-root", str(ROOT),
        "--max-call-events", "10000", "--max-call-bytes", "64000000",
        "--max-call-codes", "4096", "--max-call-references", "8192",
        "--max-operand-events", "10000", "--max-operand-bytes", "64000000",
        "--max-source-files", "256", "--max-source-file-bytes", "2000000",
        "--max-source-bytes", "64000000",
        "--os-capture-root", str(CAPTURE), "--os-profile", "program-interfaces",
        "--max-os-bytes", "64000000", "--max-os-lines", "100000",
        "--max-capture-bytes", "256000000", "--max-archive-bytes", "128000000",
        "--max-archive-files", "4096", "--os-timeout", "120", "--archive-workers", "4",
        "--", str(PYTHON), "-B", str(ROOT / "small_cuda_file_program.py")]


def capture() -> dict:
    if CAPTURE.exists() or OS_PARTITIONS.exists():
        raise FileExistsError("one-shot output path already exists; refusing to overwrite")
    source_receipt = verify_frozen_source()
    (ROOT / "data").mkdir(exist_ok=True)
    env = {key: value for key, value in os.environ.items() if not key.startswith("SCAR_")}
    env.update({
        "PYTHONPATH": str(SOURCE),
        "PYTHONDONTWRITEBYTECODE": "1",
        "SCAR_NATIVE_TENSOR_INPUTS": "1",
        "CUDA_VISIBLE_DEVICES": "0",
        "CUDA_CACHE_PATH": str(ROOT / "cuda-cache"),
        "TRITON_CACHE_DIR": str(ROOT / "triton-cache"),
        "TORCHINDUCTOR_CACHE_DIR": str(ROOT / "torchinductor-cache"),
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
    })
    argv = command()
    write_json(ROOT / "INPUTS.json", {
        "command": argv, "cwd": str(ROOT), "python": str(PYTHON),
        "collector_source": source_receipt,
        "environment": {key: env[key] for key in sorted(env)
                        if key.startswith(("SCAR_", "CUDA_", "TRITON_", "TORCHINDUCTOR_", "OMP_", "MKL_", "PYTHON"))},
        "program": "small_cuda_file_program.py; temporary local input, 2x2 CPU tensor, H2D, matmul, D2H, local output and exact scalar verification",
        "collector_witness": "omitted; ordinary coordinates do not require V1, while the binder's explicit collector-witness path accepts V2 only",
        "scope": "one tiny independent Python process, no LeWM import, no process-ports or full-program claim",
        "limits_are_ceilings_not_completeness": True,
    })
    started = time.monotonic()
    with (ROOT / "stdout.txt").open("xb") as out, (ROOT / "stderr.txt").open("xb") as err:
        proc = subprocess.Popen(argv, cwd=ROOT, env=env, stdout=out, stderr=err)
        write_json(ROOT / "RUNNING.json", {"pid": proc.pid, "capture_root": str(CAPTURE),
                                             "source_tree_sha256": source_receipt["source_tree_sha256"]})
        code = proc.wait()
    terminal = {"status": "EXITED", "exit_code": code, "elapsed_seconds": time.monotonic() - started,
                "wrapper_pid": proc.pid, "collector_source_tree_sha256": source_receipt["source_tree_sha256"],
                "whole_model_established": False}
    write_json(ROOT / "CAPTURE_TERMINAL.json", terminal)
    if code != 0:
        write_json(ROOT / "ACTUAL_TERMINAL.json", {**terminal, "postprocess": "NOT_RUN_AFTER_CAPTURE_FAILURE"})
        return terminal
    return terminal


def postprocess() -> dict:
    from scar.trace.capture_coordinates import bind_capture_coordinates
    from scar.trace.os_resources import OSInterfacePartitions, import_os_resources, publish_os_interfaces

    coordinate_model = bind_capture_coordinates(CAPTURE, max_bytes=256_000_000, max_lines=100_000,
        profile_uri=str(COORDINATES), publish_os_profile=True)
    coordinate_bytes = COORDINATES.read_bytes()
    if coordinate_bytes != coordinate_model.payload:
        raise ValueError("persisted coordinates differ from normal binder output")
    coord_receipt = sha(COORDINATES)
    members = coordinate_model.report["membership"]
    schemas = sorted({row["artifact"]["schema"] for row in members})
    if not coordinate_model.report.get("os_capture_provider"):
        raise ValueError("ordinary coordinate binder did not bind the owned OS launch")
    if not coordinate_model.report.get("native_tensor_input_membership"):
        raise ValueError("ordinary coordinate binder did not retain native tensor input membership")
    native_schemas = {"pytorch.execution-trace.v1", "pytorch.kineto.chrome-trace.v1"}
    if not native_schemas.issubset(set(schemas)):
        raise ValueError("coordinates lack retained ETO/Kineto membership")

    fragment = import_os_resources(CAPTURE / "os", scope="tiny-cpu-gpu-io:" + coord_receipt["sha256"],
        coordinates=coordinate_model, max_bytes=64_000_000, max_lines=100_000, interface_work=True)
    if fragment.run.id != coordinate_model.run.id:
        raise ValueError("normal OS fragment run differs from retained native/OS coordinates")
    published = publish_os_interfaces(fragment, OS_PARTITIONS)
    reader = OSInterfacePartitions(OS_PARTITIONS / "manifest.json")
    first_observation = next(reader.iter_records("observations"), None)
    first_submission = next(reader.iter_records("submissions"), None)

    receipts = []
    expected = [CAPTURE / "archive-index.json", COORDINATES]
    expected += sorted(CAPTURE.glob("os-capture-launch.*.json"))
    expected += sorted(TRACE.glob("execution-evidence.*.json"))
    expected += sorted(TRACE.glob("call-meta.*.json"))
    expected += sorted(TRACE.glob("python-call-target-meta.*.json"))
    expected += sorted(TRACE.glob("tensor-physical-meta.*.json"))
    expected += [OS_PARTITIONS / "manifest.json"]
    for path in expected:
        if path.is_file():
            receipts.append(sha(path))
    result = {
        "status": "POSTPROCESS_PASS",
        "coordinate_run_id": coordinate_model.run.id.value,
        "coordinate_target_process_pid": coordinate_model.target_process.pid,
        "coordinate_artifact_members": len(members),
        "coordinate_artifact_schemas": schemas,
        "same_run_os_fragment": fragment.run.id == coordinate_model.run.id,
        "os_resource_fragment_summary": fragment.summary,
        "os_interface_publication": published["manifest_receipt"],
        "normal_partition_reader": {
            "manifest_sha256": reader.manifest_receipt["physical_sha256"],
            "first_observation_available": first_observation is not None,
            "first_submission_available": first_submission is not None,
        },
        "receipts": receipts,
        "whole_model_established": False,
        "source_operation_or_tensor_value_correspondence_established": False,
    }
    write_json(ROOT / "POSTPROCESS_RESULT.json", result)
    write_json(ROOT / "ACTUAL_TERMINAL.json", {
        "status": "CAPTURE_AND_POSTPROCESS_PASS", "capture": json.loads((ROOT / "CAPTURE_TERMINAL.json").read_text()),
        "postprocess": result, "whole_model_established": False})
    return result


def main() -> int:
    capture_result = capture()
    if capture_result["exit_code"] != 0:
        return int(capture_result["exit_code"] or 1)
    try:
        postprocess()
    except Exception as error:
        write_json(ROOT / "POSTPROCESS_FAILURE.json", {
            "status": "POSTPROCESS_FAILED", "exception_type": type(error).__name__,
            "message": str(error), "capture_terminal": capture_result,
            "capture_preserved": True, "capture_was_not_repeated": True})
        write_json(ROOT / "ACTUAL_TERMINAL.json", {
            "status": "CAPTURE_PASS_POSTPROCESS_FAIL", "capture": capture_result,
            "postprocess_exception_type": type(error).__name__, "postprocess_error": str(error),
            "capture_preserved": True, "whole_model_established": False})
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
