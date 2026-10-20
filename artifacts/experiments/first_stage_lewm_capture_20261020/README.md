# LeWM first-stage evidence capture

**FAILED / INCOMPLETE.** The owned strace supervisor was stopped after severe
capture overhead (about 67% tracer CPU). Its wrapper returned 137; the target
and CLI did not remain alive and no run.json/final call metadata was produced.
The native JSON is incomplete. This does not establish a LeWM defect, a normal
episode result or complete resource coverage. Original partial files and
os-stop.json are retained. The intended native-only continuation did not finish;
the exact cause of that subsequent termination has not been established.
command.time.txt describes the stopped supervisor, not a completed target.

`run.sh` uses the known original one-episode pusht checkpoint command with
25 evaluation/goal-offset steps. It enables no optimizer and changes no target
code. Output is isolated under this directory; data and checkpoint roots are
the original locations. This is instrumented evidence collection, not a clean
performance measurement or whole-model acceptance.

The same run collects Python calls/operands, delayed native ETO/Kineto and an
independent strace of file/process/memory/descriptor syscall families. OS data
buffer arguments are raw pointers/counts, not dumped read/write payloads.
Path strings are limited to 256 bytes; unfinished/resumed calls, truncation and
uncovered syscall families are not silently promoted to full resource coverage.

strace also observes the launcher/collector and descendants. Provider and OS
clocks differ. PID/TID, source, native correlation and lifecycle evidence need
explicit adapters; time proximity alone must not create data dependencies.
The native collector does not establish all-child/all-thread scope, logical
versions, canonical graph import or GPU materialization readiness.

Actual results, if the command completes, will be recorded separately. Presence
of raw files is not proof that all required graph connections have been recovered.
