# Independent synchronous `finally` language witnesses

## Scope and result

This is an independent language experiment, **not an SCAR implementation or
acceptance result**. The probe imports only the Python standard library and
never imports SCAR. It neither lowers source nor compares behavior to a SCAR
interpreter.

Observed on CPython **3.14.7**, conda `lewm` environment:

- **19 cases PASS, 0 FAIL**, one actual probe run.
- `scar_imported=false` in the saved result.
- Worktree HEAD when started: `618cf83fff4e82ed0e873db0d2f4e9a14d6e4ab5`.
- Actual executable, complete Python version, UTC time and source SHA256 are in
  [results.json](results.json).
- CPython emitted five `SyntaxWarning` messages for `return`, `break` or
  `continue` inside `finally`. These constructs executed; no warning was hidden
  or treated as a failed assertion.

Run:

```bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 python artifacts/experiments/b1_call_operands/model_control_interfaces/language/probe.py
```

[probe.py](probe.py) saves actual ordered events, small state snapshots, object
and exception identities, and assertion failures before exiting. Subsequent
executions append a run instead of discarding earlier failures. Identity values
are process-local witnesses, not persistent semantic IDs. Recorded `repr`
strings and small containers are evidence only; no tensor values are stored.

## Cases and observations

| Case in JSON | What the actual execution established |
| --- | --- |
| `return_expression_before_finally_rebind` | `return_expression → finally_enter → finally_rebind → caller_return`; the returned object is the original binding, not the new binding. |
| `finally_mutates_returned_object` | The same returned list changes from `["before"]` to `["before", "finally"]` during cleanup; the return payload identity is preserved. |
| `normal_finally_preserves_return_with_poststate` | Pending Return keeps its payload identity; caller observes state version 1, not the pre-cleanup version 0. No active exception is observed. |
| `normal_finally_preserves_raise_with_poststate` | Pending Raise propagates the original exception identity; cleanup observes it through `sys.exception()`, updates state, and caller sees state version 1. |
| `finally_return_overrides_return` | Cleanup Return supplies the new payload rather than the earlier pending payload. |
| `finally_raise_overrides_return` | Cleanup Raise replaces the pending Return; the new exception has no implicit exception context in this case. |
| `finally_return_overrides_raise` | Cleanup Return suppresses the pending Raise and returns the new payload, although the original exception is active inside cleanup. |
| `finally_raise_overrides_raise_and_chains_context` | Cleanup Raise replaces pending Raise; the caught exception is the new object and `new.__context__ is original`, with no explicit cause. |
| `finally_break_overrides_return_targets_inner_loop` | Inner-loop Break replaces each pending Return. The outer loop still visits both iterations; only inner index 0 is visited. |
| `finally_continue_overrides_return_targets_inner_loop` | Inner-loop Continue replaces pending Return. Both inner iterations of both outer iterations execute, followed by the function's tail return. |
| `finally_continue_overrides_pending_break` | Cleanup Continue replaces the first pending Break; next iteration's normally completed cleanup preserves its pending Break. Visited indices are `[0, 1]`. |
| `finally_break_overrides_pending_continue` | Cleanup Break replaces pending Continue. Only index 0 executes. |
| `nested_finally_runs_inner_then_outer_preserving_payload` | `return_expression → inner_finally → outer_finally → caller_return`; payload identity is retained while cleanup state changes in that order. |
| `bare_raise_in_finally_reraises_pending_exception` | Bare `raise` propagates the same pending exception object, without creating a new implicit context. |
| `bare_raise_without_active_exception_overrides_pending_return` | Pending Return alone provides no exception to reraise. Bare `raise` instead raises `RuntimeError("No active exception to reraise")`, replacing that Return. |
| `bare_raise_uses_ambient_handler_context_despite_pending_return` | A pending Return may coexist with an active exception inherited from an enclosing `except`; bare `raise` reraises that ambient exception object. |
| `caught_exception_inside_finally_restores_pending_exception_context` | A cleanup-local handler temporarily sees its own exception, whose context is the original pending exception. Exiting that handler restores the original active exception, which subsequently propagates. |
| `finally_call_exception_overrides_return_with_partial_state` | A call inside cleanup writes state and then raises. That exception replaces the Return; its completed state write remains observable; code after the call is unreachable. |
| `finally_call_exception_overrides_raise_with_partial_state` | The cleanup call's exception replaces the pending exception and chains the original as context; the call's completed state write remains observable. |

## Consequences for the program model

The following are design implications of these observations, **not claims that
the current SCAR code already implements them**.

1. **Pending control and current state must be separate.** A pending Return
   retains an already evaluated payload reference. Normal cleanup retains that
   payload but forwards the state *after* cleanup. Forwarding an earlier state
   together with the saved control payload would lose writes. The two normal
   cleanup cases, mutable-return case and failing-call cases exercise this.

2. **Saving the payload does not freeze the referenced object's contents.**
   Rebinding a local variable does not change the saved return reference, but
   mutating its target can change what the caller receives. The reference
   identity and the target's state/version cannot be represented by one token.

3. **Cleanup replacement needs the precise control kind and destination.**
   Return and Raise carry their own payloads. Break/Continue name a particular
   loop destination; they cannot be represented as an undirected generic stop.
   The nested-loop cases distinguish inner-loop destinations from the outer
   loop and function return. These cases do not cover every possible locally
   contained jump inside a cleanup body.

4. **Exception context is a third, separate concern.** Pending Return can
   coexist with an active ambient exception. Consequently, deriving active
   exception context solely from a pending Raise tag is incorrect. A cleanup
   handler can temporarily change `sys.exception()` and then restore it;
   `exception.__context__` describes a causal link between exception objects,
   not the current state version or just the pending-control tag. Preserving
   only exception object identity does not by itself model traceback behavior.

5. **A failing cleanup call has an exceptional poststate.** Side effects that
   occurred before the call raised are retained. Both normal and exceptional
   cleanup exits need their actual outgoing states. A generic "call failed"
   marker must not roll back the call's completed write or resume the original
   pending control as though cleanup completed normally.

## Explicit boundaries

Not exercised here: `with`/context-manager protocols, `except*`/exception groups,
suspension, `async`, generators, cancellation, distributed control, source
lowering, runtime instrumentation, or optimization. Exact traceback contents,
explicit `raise ... from ...`, traceback mutation, exception cycles, finalizer
side effects and all forms of local jumps within cleanup are not fully audited.
The event traces are evidence for these concrete executions on this interpreter,
not an exhaustive proof of Python or a statement that M1 is complete.

Only the three ignored artifact files in this directory were written. No
product/test/documentation files, LeWM files, environments, or Git history were
changed for this task.
