"""Static-only source freeze; deliberately does not import SCAR."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
paths = ["scar/trace/os_fd_table_contexts.py", "docs/OS_FD_TABLE_CONTEXTS.md",
    "scar/trace/os_resource_refinement.py", "scar/trace/os_resources.py",
    "scar/ir/execution/resources.py", "scar/ir/execution/ids.py",
    "scar/ir/execution/common.py", "scar/ir/program/resources.py",
    "scar/ir/program/providers.py", "scar/ir/record_codec.py",
    "scar/store/bundle_partitions.py"]
files = []
for name in paths:
    path = ROOT / name
    if path.suffix == ".py":
        ast.parse(path.read_text())
    files.append({"path": name, "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "ast": "PASS" if path.suffix == ".py" else "NOT_APPLICABLE"})
assert next(row for row in files if row["path"] == "scar/trace/os_resources.py")["sha256"] == "c52f45a62693e3e78875b3a23b7c56e0a4cdb48862436981f8d98941a4900c1b"
report = {"schema": "scar.fd-table-context-static-freeze", "schema_version": 1,
    "revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
    "status": "STATIC_ONLY_NOT_IMPORTED_NOT_EXECUTED", "files": files,
    "new_production_files": [paths[0]], "existing_production_files_modified_by_this_task": [],
    "artifact_schema": "scar.os-fd-table-context-refinement",
    "artifact_schema_version": 1, "target_runs": 0, "new_collector_runs": 0,
    "container_refinements_published": 0, "gate_executed": False,
    "full_execution_model_semantics": "OPEN", "first_stage_complete": False,
    "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
with (HERE / "static-freeze.json").open("x") as stream:
    json.dump(report, stream, indent=2, sort_keys=True)
    stream.write("\n")
print(json.dumps({"status": report["status"], "module": files[0], "revision": report["revision"]}, sort_keys=True))
