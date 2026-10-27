# Process Python ports V2

`trace --capture-profile process-ports` explicitly selects
`SCAR_PROGRAM_PORTS_V2`. Unlike V1/project descendants, V2 retains every actual
Python call delivered by installed hooks in the target owner process, including
library worker-thread roots without a project parent. Such roots keep their
actual ancestry/absent caller invocation; no submission or direct callee is
invented. Both profiles use CALL-only local monitoring, original CodeIDs and
per-file source capture. Old profiles/wires and instruction/load route guards
are unchanged.

The pinned Python 3.14 `threading.py:76` implements `setprofile` for future
`threading.Thread` threads only. `setprofile_all_threads` at line 85 additionally
calls `sys._setprofileallthreads`. V2 uses the latter and records a
`sys._current_frames` snapshot count/IDs, installing Python/native thread IDs,
known current and future hook presence, and unknown other-thread hook history.
Existing active frames receive no fabricated entry. Future native/_thread-created
threads bypassing `threading` are not guaranteed. Shutdown restores only the
known current/future hooks when still owned; other threads' unknown hooks are
not overwritten to pretend restoration. A still-installed closed collector is
a no-op. Fork children disable this owner and close the inherited source FD;
exec children inherit the owner-PID guard and skip Python collection. Their OS
interfaces remain observable, but their Python execution is a scope frontier.

The existing collector barrier excludes its whole synchronous subtree. V2 also
finds already-active collector/bootstrap ancestors when first attaching below
them, so installation/stdlib work does not become target work. Transparent
dispatch and original import calls now use `_begin_target_forward`/
`_end_target_forward`: a thread-local LIFO saves the barrier and actual frame
floor, restores it in finally, and does not relax new probe/cleanup barriers.
Only the actual transparent adapter's own barrier can be left; an enclosing
observer import/Torch probe stays suppressed. Modern dispatch's three target
paths and ExecutionEvidence's original import are covered; legacy inject's
import/module/transfer/dispatch forwards use the same API only with an existing
genuine V2 owner. Original target/import calls occur once, with unchanged
exception propagation. No contextlib adapter is exposed as program work.

The first target frame across each forward floor has no proven direct caller;
its original source caller site/path/ancestor remain context, and a bounded
compact metadata list references the original invocation plus forward kind.
The ordinary operand reader checks these references and prevents source-call
handshakes from claiming those boundary roots. A one-million-byte independent
context budget retains its exact roots-seen denominator/frontier; V2 emits
compact metadata. This does not establish submission, actual content or alias.

Eleven files, including the three explicitly authorized forward adapters.
Syntax/import/CLI help passed; no new CPU capture, target,
lowering or CodeWitness compilation was run. The V1 CPU capture remains the
separate pre-barrier 177-entry result in commit `9fc397d0`; it does not validate
V2. The eventual unique LeWM capture must validate the final V2 producer and
report actual scope frontiers. Archived-text consumers are intentionally not
changed in this patch.
