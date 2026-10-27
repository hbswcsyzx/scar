# Measured CALL metadata encoding cost

Base: `75ee9dcf1b01a4c29c6ceaace034983a375c443f`. Independent worktree `call-hotpath-profile`, CPython 3.14.7. Main and the frozen collector were not changed. No LeWM, target episode, Tensor contents, hooks or new capture were run.

The owned workload makes 5,000 lightweight Python calls while changing `__defaults__`/`__kwdefaults__` on every iteration and alternating two live receivers. It directly exercises the real operand `_shape`, Python target `on_call`/`emit`, and callable-environment `dispatch`/`entry` methods. cProfile and the frame collector both use the profiling hook, so this measures those production methods directly; it does not identify the hot stack of the live LeWM process or measure whole-capture throughput. The target-entry handshake is not invented or profiled.

The initial profile took 2.775s: generic target serialization accumulated 0.821s, including 0.735s in recursive `_encode`; the static `_key_record` cache accumulated only 0.076s. The fix therefore specializes the closed V2 target wire projection, retaining the same exact kind/type and all `__post_init__` checks. Operand and target serialization share a fresh projection of the already cached frozen `FunctionLayout`. The environment observer requests the current code key directly instead of allocating an unused descriptor. All dynamic fields are still read for every CALL. No runtime objects, default values, cells or receiver associations are cached; no mutable wire container is shared.

| Same-process comparison, 5,000 calls | Base | Changed |
| --- | ---: | ---: |
| cProfile wall time | 2.71235s | 1.92621s |
| target wire function, cumulative | 0.80720s | 0.23508s |
| operand `_shape`, cumulative | 0.20195s | 0.08385s |
| `PythonCallTarget.__post_init__` calls | 10,000 | 10,000 |
| unprofiled median, 3 alternating pairs | 1.04720s | 0.87106s |

The unprofiled workload was **16.82% lower**, a local method-workload result, not a measured LeWM speedup. Cumulative profile times overlap and must not be added. The before/after run emitted byte-identical 5,000 TARGET rows (2,958,163B), 10,000 environment rows (7,192,801B, zero gaps), and operand-shape hashes; IDs and budgets are unchanged. Temporary sidecars were deleted, not archived as captured model evidence.

The small ordinary typed readback checked seven `on_call` outputs covering Python function/normalized receiver/bound method/native/unclassified TARGETs and two metadata-only ENTRY/GAP codec inputs against `target_record`. Those ENTRY/GAP inputs are not runtime observations. Changed defaults and two receiver references remained distinct. Mutating one returned layout list did not affect later output; an invalid typed target remained rejected. See `wire-check.json`.

Only `trace/call_operands.py`, `trace/callable_environment.py`, and `trace/python_call_targets.py` change. `code_snapshot.py`, `call_edges.py`, the generic codec, IR schema and asynchronous transport are untouched. Exact pre/post hashes are in `SOURCE_RECEIPTS.json`; runnable checks, profiles and timings are retained here. No further capture or benchmark is needed for this patch's stated scope.
