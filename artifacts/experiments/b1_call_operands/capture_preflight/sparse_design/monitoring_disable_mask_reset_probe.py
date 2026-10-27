import dis
import json
import sys

mon = sys.monitoring

def target(value):
    return value

def loop(sink):
    for value in range(3):
        sink(value)

code = loop.__code__
insns = list(dis.get_instructions(code))
calls = [i for i in insns if i.opname == "CALL"]
range_call, selected_call = calls
hits = {"instruction": {}, "call": {}}
def on_instruction(c, o):
    if c is code:
        hits["instruction"][o] = hits["instruction"].get(o, 0) + 1
        return mon.DISABLE
def on_call(c, o, fn, arg0):
    if c is code:
        hits["call"][o] = hits["call"].get(o, 0) + 1
        if o != selected_call.offset:
            return mon.DISABLE

tool = 5
mon.use_tool_id(tool, "sparse-disable-reset-probe")
mon.register_callback(tool, mon.events.INSTRUCTION, on_instruction)
mon.register_callback(tool, mon.events.CALL, on_call)
mask = mon.events.INSTRUCTION | mon.events.CALL
mon.set_local_events(tool, code, mask)
loop(target)
after_first = {kind: dict(counts) for kind, counts in hits.items()}
# Mimic B1's last-frame cleanup and next-entry reinstallation.
mon.set_local_events(tool, code, 0)
mask_at_zero = mon.get_local_events(tool, code)
mon.set_local_events(tool, code, mask)
loop(target)
after_mask_reinstall = {kind: dict(counts) for kind, counts in hits.items()}
mon.restart_events()
loop(target)
after_restart = {kind: dict(counts) for kind, counts in hits.items()}
mon.set_local_events(tool, code, 0)
mon.set_events(tool, 0)
mon.register_callback(tool, mon.events.INSTRUCTION, None)
mon.register_callback(tool, mon.events.CALL, None)
mon.free_tool_id(tool)
result = {
    "python": sys.version,
    "implementation": sys.implementation.name,
    "range_call_offset": range_call.offset,
    "selected_call_offset": selected_call.offset,
    "mask_at_zero": int(mask_at_zero),
    "after_first_invocation": after_first,
    "after_zero_then_mask_reinstall": after_mask_reinstall,
    "after_restart_events": after_restart,
}
assert after_first["call"].get(selected_call.offset) == 3, after_first
assert after_mask_reinstall["call"].get(selected_call.offset) == 6, after_mask_reinstall
assert after_first["instruction"] == after_mask_reinstall["instruction"], (after_first, after_mask_reinstall)
assert after_first["call"].get(range_call.offset) == after_mask_reinstall["call"].get(range_call.offset) == 1
assert after_restart["call"].get(selected_call.offset) == 9, after_restart
assert after_restart["call"].get(range_call.offset) == 2, after_restart
assert mask_at_zero == 0
print(json.dumps(result, sort_keys=True, indent=2))
