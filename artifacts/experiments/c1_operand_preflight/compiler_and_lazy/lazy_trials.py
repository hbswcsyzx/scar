"""Fresh-process dynamic-import probes with the frozen real call recorder."""
import dis
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import CodeType

from scar.trace.call_edges import CallEdgeRecorder


def trial(mode):
    directory = Path(__file__).resolve().parent
    root = directory / (mode + "-source-" + str(os.getpid()))
    root.mkdir()
    helper_name = "lazy_helper_" + str(os.getpid())
    (root / (helper_name + ".py")).write_text("def identity(value):\n    return value\n")
    entry = root / "entry.py"
    entry.write_text("from " + helper_name + " import identity\n"
                     "def caller(fn, value):\n    return fn(value)\n"
                     "def run(value):\n    return caller(identity, value)\n"
                     "result = run(object())\n")
    spec = importlib.util.spec_from_file_location("lazy_entry", entry)
    module = importlib.util.module_from_spec(spec)
    output = directory / (mode + "-trace-" + str(os.getpid()))
    recorder = CallEdgeRecorder(output, root)
    events, codes, configured = [], {}, set()
    tool = 5
    mask = sys.monitoring.events.INSTRUCTION | sys.monitoring.events.CALL
    def belongs(code):
        return code.co_filename.startswith(str(root) + os.sep)
    def record(kind, code, offset=None, **extra):
        codes[id(code)] = code
        events.append({"index": len(events), "kind": kind, "code": id(code),
                       "qualname": code.co_qualname, "offset": offset, **extra})
    def configure(code, stage):
        if id(code) not in configured:
            configured.add(id(code))
            sys.monitoring.set_local_events(tool, code, mask)
            record("CONFIGURE", code, stage=stage)
    def profile(frame, event, argument):
        recorder.profile(frame, event, argument)
        if belongs(frame.f_code) and event in ("call", "return"):
            record("PROFILE_" + event.upper(), frame.f_code, frame.f_lasti)
            if event == "call" and mode == "profile_call_lazy":
                configure(frame.f_code, "profile_call")
    def start(code, offset):
        if belongs(code):
            record("PY_START", code, offset)
            if mode == "py_start_lazy":
                configure(code, "PY_START")
    def instruction(code, offset):
        if belongs(code):
            record("INSTRUCTION", code, offset)
    def call(code, offset, function, arg0):
        if belongs(code):
            record("CALL", code, offset)
    assert sys.getprofile() is None and sys.monitoring.get_tool(tool) is None
    old_path = list(sys.path)
    sys.path.insert(0, str(root))
    # The real recorder/profile is installed before monitoring configuration.
    sys.setprofile(profile)
    sys.monitoring.use_tool_id(tool, "c1-dynamic-lazy-trial")
    sys.monitoring.register_callback(tool, sys.monitoring.events.PY_START, start)
    sys.monitoring.register_callback(tool, sys.monitoring.events.INSTRUCTION, instruction)
    sys.monitoring.register_callback(tool, sys.monitoring.events.CALL, call)
    sys.monitoring.set_events(tool, sys.monitoring.events.PY_START)
    try:
        # Code objects are created by the import loader after hook setup; no
        # local events were preconfigured for their first actual entry.
        spec.loader.exec_module(module)
    finally:
        sys.setprofile(None)
        sys.monitoring.free_tool_id(tool)
        recorder.close()
        sys.path[:] = old_path
        sys.modules.pop(helper_name, None)
    comparisons = []
    for identity, code in codes.items():
        instructions = list(dis.get_instructions(code))
        expected = [i.offset for i in instructions if i.opname != "RESUME"]
        observed = [row["offset"] for row in events if row["code"] == identity and row["kind"] == "INSTRUCTION"]
        first_load = next((i.offset for i in instructions if i.opname.startswith("LOAD")), None)
        comparisons.append({"code": identity, "filename": code.co_filename, "qualname": code.co_qualname,
                            "all_instruction_offsets": [i.offset for i in instructions],
                            "expected_post_resume_offsets": expected,
                            "observed_instruction_offsets": observed,
                            "full_post_resume_sequence_equal": expected == observed,
                            "first_load_offset": first_load,
                            "first_load_delivered": first_load in observed,
                            "call_offsets": [row["offset"] for row in events if row["code"] == identity and row["kind"] == "CALL"],
                            "events": [row for row in events if row["code"] == identity],
                            "disassembly": [{"offset": i.offset, "opname": i.opname} for i in instructions]})
    metadata, = output.glob("call-meta.*.json")
    meta = json.loads(metadata.read_text())
    return {"mode": mode, "pid": os.getpid(), "python": sys.version,
            "dynamic_import_after_hook_setup": True, "recorder": "frozen scar.trace.call_edges.CallEdgeRecorder",
            "comparisons": comparisons,
            "counts": {kind: sum(row["kind"] == kind for row in events)
                       for kind in ("PY_START", "PROFILE_CALL", "PROFILE_RETURN", "CONFIGURE", "INSTRUCTION", "CALL")},
            "all_first_loads_delivered": all(row["first_load_delivered"] for row in comparisons),
            "all_post_resume_sequences_exact": all(row["full_post_resume_sequence_equal"] for row in comparisons),
            "recorder_metadata": meta, "events": events}


if __name__ == "__main__":
    if len(sys.argv) > 1:
        print(json.dumps(trial(sys.argv[1])))
    else:
        results = []
        for mode in ("py_start_lazy", "profile_call_lazy"):
            completed = subprocess.run([sys.executable, __file__, mode], check=True, text=True, capture_output=True)
            results.append(json.loads(completed.stdout))
        assert results[0]["pid"] != results[1]["pid"]
        result = {"trials": results}
        destination = Path(__file__).with_name("lazy_result.json")
        destination.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps({"out": str(destination), "trials": [
            {key: row[key] for key in ("mode", "pid", "counts", "all_first_loads_delivered", "all_post_resume_sequences_exact")}
            for row in results]}, indent=2))
