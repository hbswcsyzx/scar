# Optional snapshot transport in the real recorder

Implemented: the five dense streams (frame events, code descriptions, operands,
Python targets, function environments) can freeze collector-owned plain facts
with marshal, enqueue bounded bytes, and batch IO on excluded writer threads.
JSON encoding and complete record-tree validation run in separate processes
after collection stops. Existing typed metadata is published only after a
successful SHA-qualified conversion within the original JSON byte/line bounds.
Closed raw journals and separate close/materialization receipts remain local.
No application values are queued for later observation. No Tensor contents are
dumped, no GPU synchronization is added by this transport.

The public CLI was run with `target.py`: changing function defaults every
iteration, alternating two bound receivers, 300 main-thread and 30 worker-thread
iterations. `process-ports --capture-transport snapshot` exited0, stdout
`{"result": [46950, 645]}`, stderr empty. `verify.py` used the ordinary frame,
operand and Python-target readers: **822 entries/822 exits, 1,024 attempts,
787 handshakes/target entries, zero observation issues and target gaps**. All five
close receipts have accepted=written, zero rejections, and writer_thread_alive
false. No application frame event has any recorded writer-thread ID. Output
file SHA/lengths match conversion receipts, and their input SHA matches each
closed journal. These checks passed in verify02; verify01 failed only because
the script's import path omitted the project, and its stderr is retained.

Earlier JSONL/windows also exited0 and returned the same program results, but
had an `INSTRUCTION_FRAME_UNAVAILABLE` gap; its target reader correctly refused
that input. The first snapshot/windows run passed its ordinary readers with
697 attempts. These are different Runs/scopes with scheduling-sensitive counts,
not a byte-for-byte or performance comparison between whole executions.

This is a scoped transport verification, not full LeWM modeling or proof that
every collector is lightweight. Stream/native providers still have separate
recording paths. JSON quotas are verified offline; runtime limits apply to the
raw temporary representation and bounded queues. Default DRAM queues total
40MiB across these five streams, plus bounded record/batch and identity state.
Temporary marshal format is bound to the exact CPython/marshal version.
Fork cleanup closes inherited journal descriptors without taking parent locks;
failure paths close sibling writers independently. These mechanisms are also
reviewed separately from the successful workload path; success here does not
prove every failure path or an unobserved program branch.

The fixed-field metadata change has an independent paired microbenchmark in
`artifacts/analysis/call_hotpath_profile_20261027`; it is not an A/B measurement
of this transport. No clean workload benchmark, LeWM speedup, complete graph or
logical content/ready/effect proof is claimed. Stage1 remains OPEN.
