# Static CALL metadata reuse

Four trace files only, based on `b5c1c3cc`. No CLI/OS/profile/schema changes.
`PythonTargetObserver.on_call` previously traversed `dis.get_instructions` on
each FUNCTION+arg0 observation to recover one static site. It now uses a bounded
weak CodeType/offset cache holding only `(opname, arg)`, including EXTENDED_ARG;
the cold decoder is unchanged. Existing site/descriptor public results remain
fresh mutable containers. Formal-name tuples use the validated key cache with
a separate 512KiB total bound; frozen FunctionLayouts use a 2048-entry weak cache
with at most 256 parameter-name characters per entry. Every cache checks
`weakref() is code` and current encoder limits. No frame, function or constant
value is retained by these caches.

CALL shape/pending/target observations now request `code_key` instead of complete
descriptor mappings. Frame entry requests only its immutable parameter tuple.
Complete descriptors remain on first CodeID emission. Dynamic function.__code__,
defaults, receiver and environment associations are still observed at their
original events; neither function-to-code association nor state is cached.
The duplicated JSON layout fields remain on the existing wire.

One metadata-only micro passed: old/new target sidecars are byte-identical
(6 rows, 2131B). Defaults mutation changes receiver normalization as before;
function.__code__ replacement changes the observed key/layout. Eight same-site
requests cause one disassembly. EXTENDED_ARG/CALL257, stricter limits, changed
CodeType and mutable-return isolation passed. No hook, capture, target or
runtime-speed benchmark was run. These results do not claim LeWM acceleration.

The first micro invocation stopped at a harness-only exact-budget-class check;
the comparison now passes each implementation its own PythonTargetBudget type.
No producer failure or target run was retried.
