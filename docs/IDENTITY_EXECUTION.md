# Identity capture runtime probe (WIP)

Date: 2026-10-13. Runtime: CPython 3.14.7 in the `lewm` environment. This is a
reproducible runtime probe, not an implementation or acceptance report for the
identity evidence gate. The collector draft is paused while the graph node and
edge semantics are reviewed.

## Observed probe

The probe used `testcases/reference_identity/program.py`, whose `relate` body is
exactly `return left is right`. It ran the target once per condition, and all
monitoring tools and callbacks were removed after each run.

Command:

```bash
cd /home/zyf/AAA/scar
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
python - <<'PY'
import sys
from pathlib import Path
from importlib.util import module_from_spec, spec_from_file_location

source = Path('testcases/reference_identity/program.py').resolve()
spec = spec_from_file_location('identity_probe_fixture', source)
module = module_from_spec(spec)
spec.loader.exec_module(module)
function = module.relate
monitoring = sys.monitoring
mask = (monitoring.events.PY_START | monitoring.events.INSTRUCTION |
        monitoring.events.PY_RETURN)

for with_profile in (False, True):
    tool_id = next(index for index in range(6)
                   if monitoring.get_tool(index) is None)
    name = f'identity_probe_{with_profile}_{id(function)}'
    monitoring.use_tool_id(tool_id, name)
    seen = []
    def start(code, offset):
        seen.append(('PY_START', offset))
    def instruction(code, offset):
        seen.append(('INSTRUCTION', offset))
    def returned(code, offset, value):
        seen.append(('PY_RETURN', offset, type(value) is bool, value))
    for event, callback in ((monitoring.events.PY_START, start),
                            (monitoring.events.INSTRUCTION, instruction),
                            (monitoring.events.PY_RETURN, returned)):
        monitoring.register_callback(tool_id, event, callback)
    monitoring.set_local_events(tool_id, function.__code__, mask)
    if with_profile:
        sys.setprofile(lambda frame, event, arg: None)
    actual = function(object(), object())
    if with_profile:
        sys.setprofile(None)
    monitoring.set_local_events(tool_id, function.__code__, 0)
    for event in (monitoring.events.PY_START, monitoring.events.INSTRUCTION,
                  monitoring.events.PY_RETURN):
        monitoring.register_callback(tool_id, event, None)
    monitoring.free_tool_id(tool_id)
    print('with_profile=', with_profile, 'actual=', actual, 'events=', seen)

tool_id = next(index for index in range(6)
               if monitoring.get_tool(index) is None)
monitoring.use_tool_id(tool_id, f'identity_frame_probe_{id(function)}')
frames = []
def frame_start(code, offset):
    frame = sys._getframe(1)
    frames.append(('PY_START', offset, frame.f_code is code,
                   frame.f_code.co_name, dict(frame.f_locals)))
def frame_instruction(code, offset):
    frame = sys._getframe(1)
    frames.append(('INSTRUCTION', offset, frame.f_code is code,
                   frame.f_code.co_name, dict(frame.f_locals)))
def frame_return(code, offset, value):
    frame = sys._getframe(1)
    frames.append(('PY_RETURN', offset, frame.f_code is code,
                   frame.f_code.co_name, dict(frame.f_locals),
                   type(value) is bool, value))
for event, callback in ((monitoring.events.PY_START, frame_start),
                        (monitoring.events.INSTRUCTION, frame_instruction),
                        (monitoring.events.PY_RETURN, frame_return)):
    monitoring.register_callback(tool_id, event, callback)
monitoring.set_local_events(tool_id, function.__code__, mask)
actual = function('left-object', 'right-object')
monitoring.set_local_events(tool_id, function.__code__, 0)
for event in (monitoring.events.PY_START, monitoring.events.INSTRUCTION,
              monitoring.events.PY_RETURN):
    monitoring.register_callback(tool_id, event, None)
monitoring.free_tool_id(tool_id)
print('frame_probe_actual=', actual)
for row in frames:
    print('frame=', row)
PY
```

Output:

```text
with_profile= False actual= False events= [('PY_START', 0), ('INSTRUCTION', 2), ('INSTRUCTION', 4), ('INSTRUCTION', 6), ('PY_RETURN', 6, True, False)]
with_profile= True actual= False events= [('PY_START', 0), ('PY_RETURN', 6, True, False)]
frame_probe_actual= False
frame= ('PY_START', 0, True, 'relate', {'left': 'left-object', 'right': 'right-object'})
frame= ('INSTRUCTION', 2, True, 'relate', {'left': 'left-object', 'right': 'right-object'})
frame= ('INSTRUCTION', 4, True, 'relate', {'left': 'left-object', 'right': 'right-object'})
frame= ('INSTRUCTION', 6, True, 'relate', {'left': 'left-object', 'right': 'right-object'})
frame= ('PY_RETURN', 6, True, 'relate', {'left': 'left-object', 'right': 'right-object'}, True, False)
```

Two conclusions are directly supported on this runtime:

* `sys.setprofile` and `sys.monitoring.INSTRUCTION` do not provide a complete
  combined stream here. With the profile hook installed, `PY_START` and
  `PY_RETURN` remain, while all three instruction callbacks disappear. A
  capture that requires both hooks must reject the positive sample.
* In a direct, named monitoring callback, `sys._getframe(1)` returned the
  target frame for each of these events. `f_code is code` was true, the start
  frame locals held the actual bound arguments, and `PY_RETURN` provided the
  exact Python bool. Each callback can verify the target frame and fail closed
  if that check ever differs. Do not add a lambda/helper callback layer: it
  changes the callback stack and therefore the meaning of frame depth.

This observation supports a smaller capture path using monitoring alone:
read `f_locals` in the verified `PY_START` callback, map operand occurrences
through the witnessed instructions, and take the actual result from
`PY_RETURN`. It does not establish that this technique is portable across
Python versions or implementations; the current evidence is limited to this
CPython 3.14.7 process. Existing profile/trace hooks and overlapping
monitoring tools still need to be rejected or separately tested.

The same function's adaptive disassembly was:

```text
0 RESUME 0 0 ''
2 LOAD_FAST_BORROW_LOAD_FAST_BORROW 1 ('left', 'right') 'left, right'
4 IS_OP 0 0 'is'
6 RETURN_VALUE None None ''
```

The two source reads therefore share one observed load offset but remain two
ordered operand occurrences, with fused-load subindices 0 and 1. The
monitoring callback observes the `IS_OP` offset; it does not expose the VM
operand stack. Source/code mapping from the two entry references to the two
loads, and from the `IS_OP` result to `RETURN_VALUE`, must remain explicitly
`Inferred` under the exact code witness.

## Current draft boundary and checks

The source adapter prepared `relate`, `distinguish`, and `repeated_read` from
the fixture successfully. Both the semantic graph and source-semantics graph
validated. The source records retained two operand occurrences for
`repeated_read(left)`, both at fused load offset 2 with subindices 0 and 1.

Runtime collector smoke attempts are not a positive capture result:

* Passing bare `object()` instances was rejected because they are not
  weak-referenceable and strong leases were not explicitly enabled. The target
  returned its actual bool, but no execution slice was accepted.
* Passing weak-referenceable user objects reached the target, but the draft
  installed `sys.setprofile` together with instruction monitoring. The
  instruction stream was absent, so the draft accepted no call and exposed no
  raw events. The actual target bool was still returned to its caller.
* `bundle.validate()` was true for those empty bundles; this only validates an
  empty projection and is not evidence of a successful capture. `attest()` was
  false because there was no accepted call.

No `tests/unit/test_identity_execution_v2.py` exists yet. No pytest suite or
end-to-end evidence-gate test has been run by this agent. Syntax compilation
of the two draft Python files succeeded; that is not functional validation.
The collector draft is not ready for integration until its event types and
capture logic are reconciled with the monitoring-only probe and the graph
node/edge semantics review.
