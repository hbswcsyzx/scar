# C-profile hook classification without temporary containers

The outer recorder invokes `CallOperandObserver.profile` for C calls as well
as Python entries/exits, so its `_profile_setter` guard runs for ordinary C
functions. The old guard built a six-item list and generator before checking
current setter identities. The new guard reads the same live bindings with
direct identity comparisons; monitoring mutation checks remain enabled. No
application callable, binding state, Tensor value, or classification is cached.

`measure.py` compared the original production method from `d12d62bd` with the
changed production method, including all17 original setter/non-setter examples
and a temporary `sys.setprofile=len` binding replacement in the test process.
Classifications matched. Three alternating pairs of100,000 ordinary-C callback
checks measured median0.166573s before and0.109628s after. Raw per-pair times are
in `RESULT.json`. Warm-up consisted of the classification checks. This measures
only the helper, installs no hooks, and is not a LeWM speedup estimate.

A real public `trace --capture-profile process-ports --capture-transport snapshot`
run then executed the existing changing-defaults/two-receivers/threaded Python
program. It returned `[46950,645]`, stderr empty. Ordinary operand and Python
target readers accepted822 entries/exits,1,024 attempts and787 matching target
entries, with0 observation issues/target gaps. Its scoped result is retained at
`artifacts/experiments/raw_frontend_live_20261027/RESULT.json`; raw payloads stay
local. This verifies the current raw-target path with the guard change, not a
whole-program or whole-LeWM model.
