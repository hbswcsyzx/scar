# Independent sparse call-window review

These are standalone safe Python probes, with no product or workload source changes. Nine fresh CPython 3.14.7 processes all exited 0. Six semantic cases used a second independent monitoring tool to retain the full executed instruction tail while the first tool disabled irrelevant locations. Among **11 admitted windows**, no accepted sparse window crossed an unrecorded same-frame instruction. This is bounded observed evidence, not a general execution proof.

## Observed

- Loop reentry: six accepted windows, all equal to the independent full instruction tail.
- A raised-and-caught handler case, native `sorted` callbacks, generator resumes, and materialized methods retained owner-separated traces. The failed unbound-local case yielded no supported narrow windows and must not be reported as positive exception routing.
- A three-invocation 5,000-element inline comprehension produced 135,051 instruction callbacks in dense mode. Sparse mode with a persistent local mask produced 36 callbacks (12 selected + 24 first-hit DISABLE). Clearing/re-enabling local masks each invocation produced 84 (12 + 72). Thus mask toggling re-enables disabled locations on this local runtime; the remaining visits still scale with static locations per invocation, rather than loop iterations.
- The generator probe concerns control isolation only. New production routing must conservatively reject suspended caller flags. Name-bound methods remain a raw MethodType boundary; optimized attribute calls are outside the Name-load rule.

## Required reasoning and boundaries

A single-entry guard is useful only together with physical contiguity. Let the required window be the consecutive logical instruction interval w0..wn, where wn is CALL and earlier operations are only supported LOAD/PUSH_NULL/NOP. If no ordinary jump or handler target enters w1..wn, ordinary control flow reaching the CALL must have entered at w0 and fallen through all required instructions. Restarting from w0 after a loop or handler emits a fresh complete prefix. An older partial prefix cannot replace this most recent prefix when all required events are delivered and previous-attempt/owner/epoch checks hold. CACHE/EXTENDED_ARG handling must preserve the exact disassembled logical interval; do not skip unfamiliar instructions to manufacture a window.

This reasoning does not prove that every recorded pre-execution callback was followed by the intended load, or exclude debugger frame jumps, another tool, callback/audit interposition, namespace mutation, signals, or lost monitoring delivery. All existing conditions remain necessary; no new unconditional VERIFIED authority follows.

Counterexample to an arbitrary LOAD subsequence: `fn(x if flag else y)` contains real control flow between callee and selected argument. Dropping the branch instructions can make LOADs appear adjacent even though they are not a straight-line source occurrence chain. Such expressions and any window with an internal jump/handler target must be rejected. Likewise, ordinary branch joins elsewhere in the source still require CONTROL_SELECTION_UNVERIFIED; sparse observation must not select a core predecessor by reference equality.

CALL and entry are distinct: builtin/C calls have no exact Python entry; bound methods, partials, and generators change binding/resumption conventions. Keep actual dispatch/layout/direct-entry checks and reject unsupported conventions. Preserve all CALL-family attempt barriers and every normal CALL continuation/handler expiry callback. A callback must not return DISABLE at an expiry point just because its first visit has no pending attempt; a later binding failure at the same code location would otherwise leave a stale pending attempt. Profile RETURN/unwind cleanup remains required. No C_RETURN event proves a Python entry or a normal Python completion.

New metadata must select the rule per PID. Old CPYTHON_LOAD_OCCURRENCES_V1 archives keep their original algorithm, conditions, and canonical replay. New windows must be independently recomputed from a complete source/code descriptor match, not trusted raw offsets or source spans. Static-plan construction also remains bounded; fewer dynamic rows does not eliminate source compilation/disassembly work.

The [official monitoring documentation](https://docs.python.org/3.14/library/sys.monitoring.html) describes INSTRUCTION as pre-execution and DISABLE as local to the code location; online docs currently identify 3.14.8. All measurements here used local 3.14.7. No Tensor values, private stack access, ctypes, extension, target workload, or full suite were used.
