"""Read-only stdlib delivery audit. Never imports SCAR or opens source raw data.

Run from any cwd; JSON goes to stdout. The only counterexample reconstruction
is an in-memory copy of already saved declarations, not a runtime/native gate.
"""
import ast
from collections import Counter
import copy
from hashlib import sha256
import json
from pathlib import Path
import re

BASE = Path(__file__).resolve().parents[3]
FIRST = "artifacts/experiments/first_stage_native_protocol_bridge_20261023"
SECOND = "artifacts/experiments/first_stage_native_protocol_bridge_attempt02_20261023"
FINAL = "artifacts/experiments/first_stage_native_protocol_bridge_attempt03_20261023"
ORDER = "artifacts/analysis/native_port_order_review_20261023"


def payload(path):
    return (BASE / path).read_bytes()


def load(path):
    return json.loads(payload(path))


def canonical(data):
    return json.dumps(data, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode()


def info(path):
    raw = payload(path)
    return {"path": path, "bytes": len(raw), "sha256": sha256(raw).hexdigest()}


def receipt_mismatches(rows, prefix=""):
    result = []
    for row in rows:
        actual = info(prefix + row["path"])
        if actual["sha256"] != row["sha256"] or actual["bytes"] != row["bytes"]:
            result.append({"expected": row, "current": actual})
    return result


def candidate(directory):
    program = load(directory + "/result/program.json")
    execution = load(directory + "/result/execution.json")
    assert canonical(program) == payload(directory + "/result/program.json")
    assert canonical(execution) == payload(directory + "/result/execution.json")
    definitions = {v["id"]["value"]: v for v in program["values"]}
    boundary = next(b for b in program["native_boundaries"] if len(b["inputs"]) >= 2
                    and all("referent_identity" in definitions[s["port"]["value"]["value"]]
                            for s in b["inputs"][:2]))
    boundary["inputs"][0]["port"], boundary["inputs"][1]["port"] = (
        boundary["inputs"][1]["port"], boundary["inputs"][0]["port"])
    model = execution["model"]["fields"]
    changed = []
    for item in model["denotations"]:
        d = item["fields"]
        basis = d["basis"]
        b = basis["fields"]
        if (basis["$record"].endswith(".NativeInputRef")
                and b["boundary"]["value"] == boundary["id"]["value"]
                and b["position"] in (0, 1)):
            formal = boundary["inputs"][b["position"]]["port"]["value"]["value"]
            actual = next(v["fields"] for v in model["values"]
                          if v["fields"]["origin"]["value"] == b["entry"]["value"]
                          and v["fields"]["value"]["value"] == formal)
            d["value"] = copy.deepcopy(actual["id"])
            changed.append(d["id"]["value"])
    wire = canonical(program)
    artifact = model["snapshot"]["fields"]["artifact"]["fields"]
    artifact.update(uri="memory:internally-valid-native-order-counterexample",
                    sha256=sha256(wire).hexdigest(), size_bytes=len(wire),
                    schema="scar.program-graph")
    model["snapshot"]["fields"]["schema_version"] = program["schema_version"]
    return program, execution, {
        "program_sha256": artifact["sha256"], "program_bytes": len(wire),
        "execution_sha256": sha256(canonical(execution)).hexdigest(),
        "changed_boundary": boundary["id"]["value"],
        "changed_denotations": changed,
        "own_snapshot_matches_candidate": True,
    }


def ordinal_errors(program, execution):
    """Independently inspect JSON formal and actual denotation ordinals only.

    This deliberately does not recreate generic validation or source ownership.
    """
    regions = {r["id"]["value"]: r for r in program["regions"]}
    blocks = {b["id"]["value"]: b for r in program["regions"] for b in r["blocks"]}
    model = execution["model"]["fields"]
    visits = {v["fields"]["id"]["value"]: v["fields"] for v in model["visits"]}
    operations = {v["fields"]["id"]["value"]: v["fields"] for v in model["operations"]}
    actual = {(v["fields"]["origin"]["value"], v["fields"]["value"]["value"]):
              v["fields"]["id"]["value"] for v in model["values"]}
    errors = []
    for boundary in program["native_boundaries"]:
        entry = blocks[regions[boundary["region"]["value"]]["entry"]["value"]]
        for i, slot in enumerate(boundary["inputs"]):
            if slot["position"] != i or slot["port"]["value"] != entry["arguments"][i]:
                errors.append({"kind": "native_core_order", "boundary": boundary["id"]["value"], "position": i})
        for i, slot in enumerate(boundary["outputs"]):
            assert slot["position"] == i and slot["port"]["index"] == i
    for item in model["denotations"]:
        d = item["fields"]
        basis = d["basis"]
        b = basis["fields"]
        if basis["$record"].endswith(".NativeInputRef"):
            visit = b["entry"]["value"]
        else:
            assert basis["$record"].endswith(".NativeOutputRef")
            visit = operations[b["operation"]["value"]]["visit"]["value"]
        formal = blocks[visits[visit]["block"]["value"]]["arguments"][b["position"]]["value"]
        if d["value"]["value"] != actual[visit, formal]:
            errors.append({"kind": "actual_native_order", "denotation": d["id"]["value"], "position": b["position"]})
    return errors


def audit():
    staging = load(FINAL + "/staging-list.json")["paths"]
    final_receipts = load(FINAL + "/artifact-receipts.json")
    rows = final_receipts["files"]
    assert len(staging) == len(set(staging)) == 108
    assert len(rows) == 107 and sum(r["bytes"] for r in rows) == 7260135
    assert not receipt_mismatches(rows)
    assert set(staging) - {r["path"] for r in rows} == {FINAL + "/artifact-receipts.json"}
    assert not {r["path"] for r in rows} - set(staging)
    before = [info(p) for p in staging]
    assert sum(r["bytes"] for r in before) == 7284407
    inventories = []
    for directory in (FIRST, SECOND, FINAL, ORDER):
        actual = {str(p.relative_to(BASE)) for p in (BASE / directory).rglob("*") if p.is_file()}
        expected = {p for p in staging if p.startswith(directory + "/")}
        assert actual == expected
        inventories.append({"path": directory, "files": len(actual), "missing": [], "extra": []})
    production = load(FINAL + "/freeze.json")["production"]
    assert not receipt_mismatches(production)
    for directory in (FIRST, SECOND, FINAL):
        frozen = load(directory + "/freeze.json")
        assert not receipt_mismatches(frozen["production"], directory + "/producer/")
        if "script_sha256" in frozen:
            assert sha256(payload(directory + "/gate.py")).hexdigest() == frozen["script_sha256"]
    old_mismatches = []
    for path in (SECOND + "/artifact-receipts.json", ORDER + "/receipt.json"):
        mismatches = receipt_mismatches(load(path)["files"])
        old_mismatches.append({"receipt": path, "current_path_mismatches": mismatches})
    assert {m["expected"]["path"] for r in old_mismatches for m in r["current_path_mismatches"]} == {
        "scar/ir/execution/native_port_protocol.py", "docs/NATIVE_PROTOCOL_BRIDGE.md", "docs/NATIVE_PORT_ORDER_REVIEW.md"}
    attempts = []
    for directory, expected_exit in ((FIRST, 1), (SECOND, 0), (FINAL, 0)):
        timing = payload(directory + "/time.txt").decode()
        match = re.search(r"Elapsed \(wall clock\) time \(h:mm:ss or m:ss\): ([\d:.]+)", timing)
        parts = [float(p) for p in match[1].split(":")]
        seconds = sum(value * 60 ** i for i, value in enumerate(reversed(parts)))
        exit_status = int(re.search(r"Exit status: (\d+)", timing)[1])
        assert exit_status == expected_exit
        terminal_name = "failure.json" if directory == FIRST else "summary.json"
        terminal = load(directory + "/" + terminal_name)
        progress = [json.loads(line) for line in payload(directory + "/progress.jsonl").splitlines()]
        assert payload(directory + "/progress.jsonl") == payload(directory + "/stdout.txt")
        assert terminal["status"] == ("FAILED" if expected_exit else "PASS")
        io = load(directory + "/actual-io.json")
        sums = {kind: sum(r["bytes"] for r in io if r["kind"] == kind) for kind in ("decoded", "stored")}
        if not expected_exit:
            assert sums == terminal["actual_io_total"] == progress[-1]["actual_io"]
        attempts.append({"directory": directory, "status": terminal["status"], "exit_status": exit_status,
                         "whole_gate_wall_seconds": seconds, "in_process_wall_seconds": terminal["wall_seconds"],
                         "whole_gate_max_RSS_KiB": int(re.search(r"Maximum resident set size \(kbytes\): (\d+)", timing)[1]),
                         "error_type": terminal.get("error_type"), "message": terminal.get("message"), "actual_io": sums})
    saved_program = load(FINAL + "/result/program.json")
    saved_execution = load(FINAL + "/result/execution.json")
    assert ordinal_errors(saved_program, saved_execution) == []
    preflight = load(FINAL + "/order-preflight.json")
    for name, expected in preflight["input_files"].items():
        assert info(SECOND + "/result/" + name)["sha256"] == expected["sha256"]
        assert info(SECOND + "/result/" + name)["bytes"] == expected["bytes"]
    p2, e2, c2 = candidate(SECOND)
    p3, e3, c3 = candidate(FINAL)
    assert c2["program_sha256"] == preflight["counterexample_new_program_sha256"]
    assert c2["execution_sha256"] == preflight["counterexample_new_execution_sha256"]
    negative = load(FINAL + "/negative-checks.json")["freshly_sealed_wrong_order"]
    assert c3["program_sha256"] == negative["own_program_snapshot_sha256"]
    assert c3["execution_sha256"] == negative["own_execution_sha256"]
    assert negative["failure_kind"] == "NativePortOrderError" and negative["rejected"]
    assert negative["fresh_same_run_owned_constructor_used"] and negative["generic_execution_issue_count"] == 0
    errors = ordinal_errors(p3, e3)
    assert Counter(e["kind"] for e in errors) == {"native_core_order": 2, "actual_native_order": 4}
    assert "native_port_scope" not in negative["message"]
    gate = payload(FINAL + "/gate.py").decode()
    protocol = payload("scar/ir/execution/native_port_protocol.py").decode()
    ast.parse(gate)
    parsed = ast.parse(protocol)
    owner = next(n for n in parsed.body if isinstance(n, ast.ClassDef) and n.name == "NativePortEvidence")
    constructor = next(n for n in owner.body if isinstance(n, ast.FunctionDef) and n.name == "__init__")
    constructor_text = ast.get_source_segment(protocol, constructor)
    assert "_make_evidence(result.native_port_evidence._owned,wrong_program,wrong_order_model" in gate
    assert "except NativePortOrderError as error:" in gate
    assert "_require_native_port_order(program, model, json.loads(self._interfaces), owned.source()[\"run\"])" in constructor_text
    assert "require_scope(" not in constructor_text
    assert constructor_text.index("self._program_sha =") < constructor_text.index("_require_native_port_order(")
    old_protocol = payload(SECOND + "/producer/scar/ir/execution/native_port_protocol.py").decode()
    assert "_native_port_order_errors" not in old_protocol and "NativePortOrderError" not in old_protocol
    report = load(FINAL + "/result/report.json")
    validation = load(FINAL + "/result/validation.json")
    model = saved_execution["model"]["fields"]
    counts = {key: len(model[key]) for key in ("activations", "operations", "values", "uses", "denotations", "transfers")}
    assert counts == {"activations": 13, "operations": 26, "values": 73, "uses": 73, "denotations": 27, "transfers": 13}
    assert len(saved_program["native_boundaries"]) == len(load(FINAL + "/result/native-interface.json")["interfaces"]) == 4
    gaps = dict(Counter(g["code"] for g in validation["gaps"]))
    assert validation["valid"] and not validation["issues"] and len(validation["gaps"]) == 41
    assert gaps == {"host_thread_unresolved": 13, "native_reference_content_unproved": 27, "source_runtime_unverified": 1}
    assert report["qualified_interfaces"] == 13 and report["physical_geometry_associations"] == 27
    values = load(FINAL + "/result/source-values.json")
    evidence = load(FINAL + "/result/source-evidence.json")
    assert len(evidence["instances"]) == 67 and len(values["objects"]) == 11 and len(values["regions"]) == 27 and len(values["allocations"]) == 5
    assert all(len(values[key]) == 0 for key in ("logical_values", "versions", "provenance", "materializations"))
    assert all(info(p["path"]) == p for p in before), "staged bytes changed during audit"
    return {"status": "READ_ONLY_DELIVERY_AUDIT_PASS", "final_staging_manifest": info(FINAL + "/staging-list.json"),
            "final_artifact_receipt": info(FINAL + "/artifact-receipts.json"),
            "final_staged_files": 108, "final_staged_bytes": 7284407,
            "final_receipted_files_excluding_self": 107, "final_receipted_bytes_excluding_self": 7260135,
            "final_receipt_mismatches": [], "delivery_directory_inventory": inventories,
            "current_six_sources_match_final_freeze_and_producer": True, "production_sources": production,
            "all_three_historical_producer_freezes_match": True, "staged_bytes_unchanged_during_audit": True,
            "historical_receipt_current_path_differences": old_mismatches,
            "historical_difference_interpretation": "Historical receipts remain immutable. Two updated docs and attempt03's native_port_protocol.py supersede old mutable-path versions; all current versions are frozen by final receipts. Attempt02's exact source remains in its producer snapshot. Old doc bytes are not claimed recoverable from those old receipts.",
            "actual_attempts": attempts, "final_model_counts": counts, "static_interfaces": 4,
            "final_validation_issues": 0, "retained_gaps": gaps,
            "projection_counts": {"instances": 67, "objects": 11, "regions": 27, "physical_epochs": 5},
            "four_content_tables_empty": True,
            "independent_saved_JSON_positive_ordinal_errors": 0,
            "preflight_candidate_reconstructed": c2, "final_live_gate_candidate_reconstructed": c3,
            "independent_counterexample_ordinal_errors": errors,
            "retained_live_gate_rejection": negative,
            "rejection_chain": "gate.py calls _make_evidence with the genuine result.native_port_evidence._owned and candidate program/model; constructor seals those candidate bytes then independently replays source interfaces and calls the ABI checker, without require_scope. Retained NativePortOrderError agrees with independently reconstructed 2+4 ordinal errors.",
            "attempt02_independent_order_validation": False,
            "audit_limits": "Consistency and SHA/byte audit of saved evidence plus stdlib in-memory declaration reconstruction. Does not rerun generic validation, native ownership or the actual gate; no saved authority is restored. No raw source, optimization, backend, target execution or Git command.",
            "whole_program_model_established": False, "optimization_authorized": False,
            "raw_sources_read_by_this_audit": 0, "product_imports_by_this_audit": 0,
            "gate_runs_by_this_audit": 0, "git_commands_by_this_audit": 0}


if __name__ == "__main__":
    print(json.dumps(audit(), sort_keys=True, ensure_ascii=False, indent=2))
