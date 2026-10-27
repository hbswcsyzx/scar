# Recording and postprocessing budgets

Implemented on independent `capture-phase-budget`, base `d12d62bd`. Six production files change: new `trace/capture_phases.py`, the owned OS launcher, CLI, call recorder, native manager and sitecustomize. Main, frozen collectors, LeWM and native/declarative data readers are untouched. No LeWM/Torch capture ran.

`--os-postprocess-timeout N` explicitly enables a separate finite shutdown/conversion allowance. `--os-timeout R` remains the recording ceiling; the first qualified `ATEXIT_STOPPING` starts one N-second deadline. `CONVERTING` never renews it. Total provider time is at most R+N, plus the existing bounded5s termination grace; any external wrapper must cover that total. Without the new option, the old total wall limit and launch/archive format remain unchanged. Byte/file bounds continue in both phases.

The registered `ExecutionEvidence.close_at_exit` emits before native stop/export. Public/manual `close()` is unchanged. The optional emitter requires the original owner process/main thread and a C-initiated atexit frame with no Python caller. The recorder's dedicated atexit wrapper supplies the same boundary when native evidence was not installed. `finish` sets `_closing`, so all observation callbacks reject new observations, and emits `CONVERTING` before stop/materialization. Remaining shutdown gaps/mask cleanup are collector work.

Events are atomically published immutable plain JSON, not a graph/schema authority. They retain pid, process start ticks/parent, thread coordinates, monotonic clock, exact capture nonce/intent SHA, callback source/code identity and predecessor receipt. The outer launcher checks pinned producer source/code, its own live unreaped strace child ancestry and the original owner incarnation. Late, conflicting, changed or missing accepted events fall back to the original recording deadline. These are cooperative owned-collector observations, not hostile-process authentication. They do not prove all daemon/external actors ended, capture completeness or GPU ready.

Two actual owned CPU cases used R=3s/N=8s:

- **Converting:** main returned to atexit about0.569s after provider start. Two snapshot conversions were deliberately delayed2s each. Stop/conversion events qualified; the process finished exit0 in5.342s, exceeding R without extending application runtime.
- **Manual close:** the running program called `close_at_exit()` from Python, then slept. No phase marker qualified; original recording budget terminated it in3.073s, returncode-15 / `RECORDING_SECONDS`.

These are lifecycle/budget checks, not performance A/B or model coverage. `RESULT.json` and original intent/launch/phase files retain the results. After the two cases, one narrow consumer guard was added to revoke an accepted event if its file later disappears; that deletion path was code-reviewed, not exercised by another capture. `ACTUAL_SOURCE_RECEIPTS.json` preserves the exact tested source identities and the pre-guard helper bytes; `FINAL_SOURCE_RECEIPTS.json` identifies the final source. Syntax/import, CLI help and production diff-check passed. No further case or large gate was run.
