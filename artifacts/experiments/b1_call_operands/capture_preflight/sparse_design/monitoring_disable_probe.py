import dis
import json
import sys

mon = sys.monitoring
if sys.version_info < (3, 12):
    raise RuntimeError(f"sys.monitoring unavailable: {sys.version}")

def target(value):
    return value

def loop(sink):
    for value in range(3):
        sink(value)

code = loop.__code__
insns = list(dis.get_instructions(code))
calls = [i for i in insns if i.opname == "CALL"]
if len(calls) != 2:
    raise AssertionError([(i.offset, i.opname, i.arg, i.argval) for i in insns])
range_call, selected_call = calls
hits = {"instruction": {}, "call": {}}

def on_instruction(c, o):
    if c is code:
        counts = hits["instruction"]
        counts[o] = counts.get(o, 0) + 1
        return mon.DISABLE

def on_call(c, o, fn, arg0):
    if c is code:
        counts = hits["call"]
        counts[o] = counts.get(o, 0) + 1
        if o != selected_call.offset:
            return mon.DISABLE

tool = 5
mon.use_tool_id(tool, "sparse-disable-probe")
mon.register_callback(tool, mon.events.INSTRUCTION, on_instruction)
mon.register_callback(tool, mon.events.CALL, on_call)
mask = mon.events.INSTRUCTION | mon.events.CALL
mon.set_local_events(tool, code, mask)
loop(target)
mon.set_local_events(tool, code, mask)
loop(target)
after_two = {kind: dict(counts) for kind, counts in hits.items()}
mask_after_two = mon.get_local_events(tool, code)
mon.restart_events()
loop(target)
after_restart = {kind: dict(counts) for kind, counts in hits.items()}
mask_after_restart = mon.get_local_events(tool, code)
mon.set_local_events(tool, code, 0)
mon.set_events(tool, 0)
mon.register_callback(tool, mon.events.INSTRUCTION, None)
mon.register_callback(tool, mon.events.CALL, None)
mon.free_tool_id(tool)
result = {
    "python": sys.version,
    "implementation": sys.implementation.name,
    "code": [{"offset": i.offset, "opname": i.opname,
              "arg": i.arg, "argval": repr(i.argval)} for i in insns],
    "range_call_offset": range_call.offset,
    "selected_call_offset": selected_call.offset,
    "mask": int(mask),
    "mask_after_two": int(mask_after_two),
    "mask_after_restart": int(mask_after_restart),
    "after_two_invocations": after_two,
    "after_restart_and_third_invocation": after_restart,
}
assert after_two["call"].get(selected_call.offset) == 6, after_two
assert after_two["call"].get(range_call.offset) == 1, after_two
assert after_two["instruction"].get(selected_call.offset) == 1, after_two
assert after_two["instruction"].get(range_call.offset) == 1, after_two
assert after_restart["call"].get(selected_call.offset) == 9, after_restart
assert after_restart["call"].get(range_call.offset) == 2, after_restart
assert after_restart["instruction"].get(selected_call.offset) == 2, after_restart
assert mask_after_two == mask_after_restart == mask
print(json.dumps(result, sort_keys=True, indent=2))
