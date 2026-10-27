from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import replace
from pathlib import Path

from scar.ir.program.drivers import BodyResume, NormalResultPort
from scar.ir.program.ids import LocationID, OperationID, UseID
from scar.ir.program.model import Behavior
from scar.ir.program.validation import validate
from tests.fixtures.program_driver_graphs import driver_program, raw_only_program
from tests.fixtures.program_resumption_graphs import resumption_cleanup_invoke_program, resumption_loop_program

ROOT = Path(__file__).resolve().parents[5]
FILES = (
    "scar/ir/program/driver_validation.py",
    "scar/ir/program/driver_flow.py",
    "scar/ir/program/control_validation.py",
    "scar/ir/program/validation.py",
)

def issues(graph):
    return [(row.code, row.path) for row in validate(graph)]

def change_op(graph, identity, fn):
    return replace(graph, operations=tuple(fn(op) if op.id == OperationID(identity) else op
                                           for op in graph.operations))

def no_crash(name, graph, expect=()):
    try:
        got = issues(graph)
    except BaseException as exc:
        return {"name": name, "crash": type(exc).__name__ + ": " + str(exc)}
    codes = {code for code, _ in got}
    return {"name": name, "issues": got, "expected_codes_present": sorted(set(expect) & codes),
            "returned_issues": bool(got)}


def main():
    source_hashes = {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in FILES}
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
                          capture_output=True, text=True).stdout.strip()
    result = {"head": head, "python": __import__("sys").version,
              "source_sha256": source_hashes, "cases": []}

    # Valid control samples: basic driver, Create+Drive, and nested C1/C2B bodies.
    for name, graph in (
        ("base_start", driver_program()),
        ("create_start", driver_program(create=True)),
        ("c1_invoke_body", driver_program(target="value", body_graph=resumption_cleanup_invoke_program())),
        ("loop_body", driver_program(target="value", body_graph=resumption_loop_program())),
    ):
        result["cases"].append({"name": name, "issues": issues(graph)})

    # Effect labels that conflict with a pure raw request constructor must not pass.
    for behavior_set in (
        (Behavior.WRITE,), (Behavior.READ,), (Behavior.MEMORY,), (Behavior.TRANSFER,),
        (Behavior.ORDER,), (Behavior.CONTROL,), (),
    ):
        graph = raw_only_program()
        graph = change_op(graph, "raw.pack", lambda op, bs=behavior_set: replace(op, behaviors=bs))
        result["cases"].append(no_crash("raw_behaviors:" + ",".join(x.value for x in behavior_set), graph,
                                        expect=("driver_raw_pack",)))

    # Source/result/state/metadata tampering: validation should fail closed, never throw.
    graph = driver_program()
    bad_drive = replace(graph.body_drives[0], state_inputs=(
        replace(graph.body_drives[0].state_inputs[0], source=UseID("missing.state.use")),
        *graph.body_drives[0].state_inputs[1:],
    ))
    malformed = replace(graph, body_drives=(bad_drive,))
    result["cases"].append(no_crash("missing_body_state_use", malformed,
                                    expect=("driver_state_inputs",)))

    graph = driver_program()
    bad_drive = replace(graph.body_drives[0], target=BodyResume(OperationID("resume.suspend"), 999))
    malformed = replace(graph, body_drives=(bad_drive,))
    result["cases"].append(no_crash("resume_case_out_of_range", malformed,
                                    expect=("driver_target",)))

    graph = driver_program(create=True)
    bad_create = replace(graph.resumable_creates[0], handle_result=NormalResultPort(999))
    malformed = replace(graph, resumable_creates=(bad_create,))
    result["cases"].append(no_crash("create_result_out_of_range", malformed,
                                    expect=("driver_result",)))

    # Bypass record constructors with post-init mutation, as hostile in-memory graphs can.
    graph = driver_program()
    bad_drive = replace(graph.body_drives[0])
    object.__setattr__(bad_drive, "target", object())
    object.__setattr__(graph, "body_drives", (bad_drive,))
    result["cases"].append(no_crash("forged_target_class", graph, expect=("schema",)))

    graph = driver_program(create=True)
    bad_row = replace(graph.resumable_creates[0])
    object.__setattr__(bad_row.handle_result, "index", True)
    object.__setattr__(graph, "resumable_creates", (bad_row,))
    result["cases"].append(no_crash("bool_result_port", graph, expect=("schema",)))

    print(json.dumps(result, sort_keys=True, indent=2))

if __name__ == "__main__":
    main()
