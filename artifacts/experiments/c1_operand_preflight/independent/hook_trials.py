"""Independent-process public-hook trials; tiny functions only, no SCAR imports."""
import collections
import dis
import json
import os
from pathlib import Path
import subprocess
import sys


def trial(mode):
    namespace = {}
    exec(compile("def target(value):\n    return value\ndef caller(fn, value):\n    return fn(value)\n",
                 str(Path(__file__).with_name("fixture.py")), "exec", dont_inherit=True), namespace)
    caller, target = namespace["caller"], namespace["target"]
    records, audits = [], []
    phase = "initial"
    def audit(event, args):
        if event in ("sys.setprofile", "sys.settrace") or event.startswith("sys.monitoring."):
            audits.append({"phase": phase, "event": event})
    sys.addaudithook(audit)
    def instruction(code, offset):
        records.append({"phase": phase, "kind": "INSTRUCTION", "offset": offset})
    def foreign_instruction(code, offset):
        records.append({"phase": phase, "kind": "FOREIGN_INSTRUCTION", "offset": offset})
    def call(code, offset, function, arg0):
        records.append({"phase": phase, "kind": "CALL", "offset": offset,
                        "callable_is_target": function is target,
                        "arg0_is_value": arg0 is value})
    def profile(frame, event, arg):
        if frame.f_code in (caller.__code__, target.__code__):
            records.append({"phase": phase, "kind": "PROFILE", "event": event,
                            "function": frame.f_code.co_name})
    def replacement(frame, event, arg):
        if frame.f_code in (caller.__code__, target.__code__):
            records.append({"phase": phase, "kind": "FOREIGN_PROFILE", "event": event,
                            "function": frame.f_code.co_name})
    tool = 5
    assert sys.monitoring.get_tool(tool) is None and sys.getprofile() is None
    sys.monitoring.use_tool_id(tool, "c1-independent-hook-trial")
    mask = sys.monitoring.events.INSTRUCTION | sys.monitoring.events.CALL
    value = object()
    if mode not in ("monitor_only", "monitor_then_profile"):
        sys.setprofile(profile)
    sys.monitoring.register_callback(tool, sys.monitoring.events.INSTRUCTION, instruction)
    sys.monitoring.register_callback(tool, sys.monitoring.events.CALL, call)
    sys.monitoring.set_local_events(tool, caller.__code__, mask)
    if mode == "monitor_then_profile":
        sys.setprofile(profile)
    states = []
    def run(label):
        nonlocal phase
        phase = label
        states.append({"phase": phase, "profile_is_expected": sys.getprofile() is profile,
                       "global_mask": sys.monitoring.get_events(tool),
                       "local_mask": sys.monitoring.get_local_events(tool, caller.__code__),
                       "tool_is_expected": sys.monitoring.get_tool(tool) == "c1-independent-hook-trial"})
        assert caller(target, value) is value
    try:
        run("baseline")
        phase = "hook_change"
        if mode == "reset_same_profile":
            sys.setprofile(profile)
            run("after_same_profile")
        elif mode == "replace_profile":
            sys.setprofile(replacement)
            run("after_replace_profile")
        elif mode == "remove_restore_profile":
            sys.setprofile(None)
            sys.setprofile(profile)
            run("after_restore_profile")
        elif mode == "replace_instruction":
            sys.monitoring.register_callback(tool, sys.monitoring.events.INSTRUCTION, foreign_instruction)
            run("after_replace_instruction")
            phase = "hook_restore"
            sys.monitoring.register_callback(tool, sys.monitoring.events.INSTRUCTION, instruction)
            run("after_restore_instruction")
        elif mode == "mask_off_restore":
            sys.monitoring.set_local_events(tool, caller.__code__, sys.monitoring.events.CALL)
            run("after_mask_off")
            phase = "hook_restore"
            sys.monitoring.set_local_events(tool, caller.__code__, mask)
            run("after_mask_restore")
    finally:
        phase = "cleanup"
        sys.setprofile(None)
        sys.monitoring.free_tool_id(tool)
    counts = {}
    for row in records:
        phase_counts = counts.setdefault(row["phase"], {})
        phase_counts[row["kind"]] = phase_counts.get(row["kind"], 0) + 1
    return {"mode": mode, "pid": os.getpid(), "python": sys.version,
            "fresh_compiled_code": True, "counts": counts, "states": states,
            "audits": audits, "records": records,
            "disassembly": [{"offset": i.offset, "opname": i.opname} for i in dis.get_instructions(caller)]}


if __name__ == "__main__":
    if len(sys.argv) > 1:
        print(json.dumps(trial(sys.argv[1]), sort_keys=True))
    else:
        modes = ("monitor_only", "monitor_then_profile", "profile_then_monitor", "reset_same_profile",
                 "replace_profile", "remove_restore_profile", "replace_instruction", "mask_off_restore")
        results = []
        for mode in modes:
            completed = subprocess.run([sys.executable, __file__, mode], text=True,
                                       capture_output=True, check=True)
            results.append(json.loads(completed.stdout))
        assert len({row["pid"] for row in results}) == len(modes)
        destination = Path(__file__).with_name("result.json")
        destination.write_text(json.dumps({"trials": results}, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"path": str(destination), "trials": len(results),
                          "counts": {row["mode"]: row["counts"] for row in results}}, indent=2))
