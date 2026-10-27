# Full source reader failure record

The attempt used the ordinary `CompositionIndex.from_source_entry_publication` path against the exact 196-row publication SHA. The public reader did not return a `CompositionIndex`, so `bind_source_invocations` was never called and no call was bound.

- Terminal: exit 1 after 2699.923103s.
- Failure: `ValueError: source fragment wall budget exceeded`.
- Process/session: PID 1979848 / exec session 82170.
- Stack: `SourceEntryPublication` -> `_read_source_entries2` -> `_entry_program` -> `_SharedEntryProgramReader.writer.write` -> `SourceFragmentWriter._check`; the shared source-fragment writer's 1800s batch wall guard expired. The cleanup `finish()` then encountered the same wall guard.
- Scope: manifest SHA a124d78bb5e50e4ff96d1af2858357651cb9eda13918c328fd753a3a4bd4650b, 196 declared body rows; intended same-capture scope PID272038 / 100438 entered invocations. The binder and capture-coordinate reader did not run.
- Output: no composition return, coordinate artifact, or binding output.
- I/O: raw per-process counters and deltas are in `IO_COUNTERS.json`.

This is a preserved failure, not a partial success or binding count. The runner and per-file source receipts are retained; the 8.47MB private source snapshot, publication payload, source archives, and capture files are intentionally excluded from this commit.

The initial invocation was attached directly to the tool session rather than redirected. `ACTUAL_TERMINAL.json` and `STRUCTURED_EXCEPTION_TRACEBACK.txt` preserve the exact terminal object and complete inner exception chain. `STDOUT_RECONSTRUCTED.log` rebuilds the three observed phase lines and printed terminal JSON; it is not byte-capture evidence. The uncaught stderr wrapper was not separately retained; `STDERR_CAPTURE_NOTE.md` records that limit. Later reruns use separate stdout/stderr log files.
