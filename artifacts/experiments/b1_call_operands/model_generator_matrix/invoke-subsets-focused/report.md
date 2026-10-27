# INVOKE subset connection tests

Status: **PASS_WITH_SCOPE**, first attempt only. This is a focused interface
receipt, not full P2 or complete generator-family acceptance.

## Exact command and result

The preserved `attempt001-command.sh` explicitly sources
`/home/zyf/miniconda3/etc/profile.d/conda.sh`, activates `lewm`, sets
`PYTHONDONTWRITEBYTECODE=1` and `PYTHONPATH=.`, then runs:

```sh
python artifacts/experiments/b1_call_operands/model_generator_matrix/run_focus.py \
  invoke-subsets-focused/attempt001 tests/unit/test_program_invoke_subsets.py
```

Actual result: **47 PASS / 0.87s**, exit **0**, wall **1.4750254405662417s**.
No preceding syntax/smoke/test attempt and no suppressed failure. Raw stdout,
stderr, exact subprocess command/environment, JUnit and result are under
`attempt001/`. All-source inventory SHA was stable before/after:
`63019101896ebfb9da1c18564b12f543bd5c048a43e2108efaf78f69820facb4`.
The 16 explicitly watched file hashes likewise matched before/after.

## What the new graph actually connects

`invoke_subset_program(kinds=(RAISE,), alternate_callee=False)` returns
`(ProgramGraph, details)`. RAISE-only and NORMAL-only callees contain only their
actual declared terminal kind after a real canonical RW state access. The
dual-edge callee contains a real BRANCH. Caller INVOKE inputs match the known
callee entry. The real RAISE landing is a caller handler, not an invented NORMAL
callee completion. Logical `(Reference, State)` signatures project into physical
`(State, Reference)` landing formals, which remain the original producers.

Tests cover exact edge/signature kind sets; nonempty/unique kinds and targets;
real callee exit mismatch; duplicate result projection and old-state rejection;
explicit missing-NORMAL ValueError; original result indices and getter bounds.

`final_gate_subset_program(kind)` retains reachable real core paths but carries
invalid specialized D1 metadata. Both N-only and R-only return **exactly**
`driver_gate_completions`. The R-only case has an explicit upstream branch to
the real Drive rather than an unreachable synthetic NORMAL continuation.

Partial INVOKE alone auto-selects v18, old schemas reject it, dual INVOKE keeps
automatic v2, old admission keeps v18. Existing immutable v2/v17 fixture bytes
are unchanged; no immutable evidence was regenerated.

## Scope, review and hashes

Source review and the old-unit audit are recorded in
`../design/invoke-completion-review.md`; its initial source snapshot and the
later focused receipt are preserved separately. Root's additional input-origin
query wrappers landed before this run: tested queries SHA is `b5a22aa7…`, stable
during the run. No product guard was edited by this test owner.

```
41aba0cbde2c4d761b18b991cbccecc1f292836a88a1d79792c0896899b60dc5 program_invoke_subset_graphs.py
9a5b5f4b645ee8e09655c4cd5666e54808d1b602dfdf2cce4c859ab157c7f841 test_program_invoke_subsets.py
11b533212e91c210b622c63e1259a0dbdbd2632e798bcc18174ff5d5ddfa6a13 attempt001/junit.xml
```

These fixtures establish declared structural relationships. They do not recover
source/runtime behavior, prove phase or object identity, assert native completion,
add zero-exit INVOKE support, or authorize transformations. No old tests were
edited, and no component/full/workload/GPU test was started. Files are frozen.
