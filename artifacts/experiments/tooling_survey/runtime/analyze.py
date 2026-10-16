"""Inspect the small saved traces; no target rerun and no inferred logical IDs."""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import subprocess

OUT = Path(__file__).resolve().parent
et = json.loads((OUT / "execution-trace.json").read_text())
chrome = json.loads((OUT / "chrome-trace.json").read_text())
et_rows, chrome_rows = [], []
for node in et["nodes"]:
    attrs = {attr["name"]: attr["value"] for attr in node["attrs"]}
    et_rows.append((attrs.get("rf_id"), node["name"]))
for node in chrome["traceEvents"]:
    if node.get("cat") == "cpu_op":
        chrome_rows.append((node.get("args", {}).get("Record function id"), node["name"]))
positive_et = [row for row in et_rows if type(row[0]) is int and row[0] > 0]
positive_chrome = [row for row in chrome_rows if type(row[0]) is int and row[0] > 0]
mutations = [node for node in et["nodes"] if node["name"] == "aten::add_"]
transpose = next(node for node in et["nodes"] if node["name"] == "aten::t")
source_files = ["scar/trace/inject.py", "scar/trace/cuda.py", "scar/trace/normalize_v2.py",
                "scar/trace/call_edges.py", "scar/trace/call_operands.py", "scar/trace/operand_bytecode.py",
                "scar/trace/values_v2.py", "scar/trace/session.py", "scar/trace/resources.py"]
flags = ["ENABLE_PYTORCH_EXECUTION_TRACE", "ENABLE_PYTORCH_EXECUTION_TRACE_EXTRAS",
         "ENABLE_PYTORCH_EXECUTION_TRACE_SAVE_INTEGRAL_TENSOR_RANGE",
         "ENABLE_PYTORCH_EXECUTION_TRACE_SAVE_INTEGRAL_TENSOR_DATA"]
summary = {
    "scope": "CPU probe only; runtime joins are not tensor logical identity or transform proof",
    "schema": et["schema"], "et_pid": et["pid"],
    "positive_et_rf_ids": len(positive_et), "positive_chrome_record_function_ids": len(positive_chrome),
    "matching_id_name_pairs": len(set(positive_et) & set(positive_chrome)),
    "duplicate_positive_et_ids": [key for key, n in Counter(row[0] for row in positive_et).items() if n > 1],
    "duplicate_positive_chrome_ids": [key for key, n in Counter(row[0] for row in positive_chrome).items() if n > 1],
    "nonpositive_or_missing_et_ids": [row for row in et_rows if not (type(row[0]) is int and row[0] > 0)],
    "inplace_self_tuples": [node["inputs"]["values"][0] for node in mutations],
    "inplace_same_tuple_before_and_after_mutation": mutations[0]["inputs"]["values"][0] == mutations[1]["inputs"]["values"][0],
    "view_input_tuple": transpose["inputs"]["values"][0],
    "view_output_tuple": transpose["outputs"]["values"][0],
    "view_input_output_strides": [transpose["inputs"]["strides"], transpose["outputs"]["strides"]],
    "ordinary_python_in_eto": any("ordinary_python_region" in node["name"] for node in et["nodes"]),
    "ordinary_python_in_kineto_stack_trace": any("ordinary_python_region" in str(node.get("name")) for node in chrome["traceEvents"]),
    "node_performance_timestamps_present": any("ts" in node or "dur" in node for node in et["nodes"]),
    "source_head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
    "source_files_sha256": {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in source_files},
    "execution_trace_flags_in_analyzer_process": {flag: os.environ.get(flag) for flag in flags},
}
(OUT / "analysis.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary, indent=2))
