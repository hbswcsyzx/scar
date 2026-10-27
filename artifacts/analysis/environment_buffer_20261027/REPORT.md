# Environment-sidecar transport batching

Only `scar/trace/callable_environment.py` changes. Environment fields and owner
associations are still observed synchronously at their original event; JSON is
still encoded there. A bounded 64KiB byte buffer batches writes, matching the
other call-side channels. Queued bytes count toward the existing byte budget.
Successful close flushes before writing the original metadata; failed writes
remain errors and are not retried at close. Child cleanup discards inherited
queued rows and closes its FD without a parent-row replay or inherited lock.
No schema, ordering, object lifetime, graph or capture qualification changes.

Pure transport validation passed: 1000 rows/259,893 bytes exactly match the old
writer. `os.write` calls including one metadata write decreased from 1001 to 5.
Byte-budget termination retained one row/rejected one; close/repeated close was
readable. A plain fork confirmed the child discarded the inherited queue while
the parent wrote its row once. No profile/capture/target was started. This is
not a measured runtime speedup and does not remove JSON CPU/GIL work.

Before SHA: `14e4a319ec9024752eff907422fbc886da1e735db88360b8871c345669c39428`.
After SHA: `f0bb30a8471ae87213154d4c9d71ae936552c447e97fe78cde2f735c945b5b95`.
The active LeWM collector remains the original frozen `4f23a6d6` source.
