#!/usr/bin/env python3
"""One normal same-Run OS fragment + snapshot worker-role consumer pass."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time

from scar.analysis.os_postprocessing_roles import bind_snapshot_postprocessor_roles
from scar.ir.execution.ids import ProcessInstanceID
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.record_codec import decode
from scar.trace.capture_coordinates import bind_capture_coordinates
from scar.trace.os_resources import import_os_resources


ROOT = Path(__file__).resolve().parent
CAPTURE = ROOT / "capture"
COORDINATES = CAPTURE / "capture-coordinates.json"
TRACE = CAPTURE / "trace"


def receipt_artifact(path: Path) -> ProviderArtifact:
    raw = path.read_bytes()
    return ProviderArtifact(str(path), hashlib.sha256(raw).hexdigest(), len(raw), "application/json")


def main() -> None:
    started = time.monotonic()
    coordinates = bind_capture_coordinates(CAPTURE, max_bytes=256_000_000, max_lines=100_000,
        profile_uri=str(COORDINATES), publish_os_profile=True)
    fragment = import_os_resources(CAPTURE / "os", scope="tiny-cpu-gpu-role-bridge:" + coordinates.artifact.sha256,
        coordinates=coordinates, max_bytes=64_000_000, max_lines=100_000, interface_work=True)
    pid = coordinates.target_process.pid
    names = (
        f"call-events.{pid}.jsonl.snapshot-receipt.json",
        f"call-codes.{pid}.jsonl.snapshot-receipt.json",
        f"call-operands.{pid}.jsonl.snapshot-receipt.json",
        f"python-call-targets.{pid}.jsonl.snapshot-receipt.json",
        f"function-environments.{pid}.jsonl.snapshot-receipt.json",
    )
    artifacts = tuple(receipt_artifact(TRACE / name) for name in names)
    model = bind_snapshot_postprocessor_roles(coordinates, fragment, artifacts)
    document = model.to_dict()
    checks = []
    for role in document["roles"]:
        source = decode(ProviderFactReference, role["exec"])
        process = decode(ProcessInstanceID, role["process"])
        query = model.query(source, process=process)
        checks.append({"process": role["declared_process_id"],
                       "exec_source": role["exec"],
                       "query_found_role": query is not None and query.get("role") == "SCAR_OFFLINE_POSTPROCESSING"})
    if len(document["roles"]) != 5 or len(checks) != 5 or not all(row["query_found_role"] for row in checks):
        raise ValueError("expected five positively bound snapshot materializer roles; see frontiers")
    result = {
        "status": "ROLE_BRIDGE_PASS",
        "capture_run_id": coordinates.run.id.value,
        "target_process_pid": pid,
        "input_snapshot_receipts": [
            {"uri": artifact.uri, "sha256": artifact.sha256, "size_bytes": artifact.size_bytes,
             "schema": artifact.schema} for artifact in artifacts],
        "normal_os_fragment_summary": fragment.summary,
        "role_navigation": document,
        "query_checks": checks,
        "elapsed_seconds": time.monotonic() - started,
        "all_os_syscall_observations_preserved": True,
        "whole_model_established": False,
        "LeWM_scope_claimed": False,
    }
    output = ROOT / "SNAPSHOT_ROLE_BRIDGE_RESULT.json"
    output.write_text(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False,
                                 allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "run": result["capture_run_id"],
                      "target_pid": pid, "positive_roles": len(document["roles"]),
                      "frontiers": len(document["frontiers"]),
                      "all_five_queries": all(row["query_found_role"] for row in checks),
                      "elapsed_seconds": result["elapsed_seconds"]}, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
