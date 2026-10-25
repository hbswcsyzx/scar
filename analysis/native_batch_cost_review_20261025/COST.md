# Attempt02 in-flight code-only cost diagnosis

No runtime producer/freeze/budget was changed, no API check or second gate was run, and no profiler was attached. Root owns session4258. This note uses frozen source and small progress rows only. It proposes sampling; attribution below is Inferred until sampled.

Progress through shard0–10: cumulative whole404.52s at shard0,414.84s at1,425.06s at2,477.67s at7,511.63s at10. First ten subsequent intervals average10.71s, ranging10.22–12.73s. Discovery completed actual39,796 groups and127 static interfaces. If nearly every group materializes and all chunks remain256 activations, ceil(39,796/256)=156 shards; frontier gaps or Tensor/flat limits can create smaller shards, while unmodeled frontier groups reduce materialized calls. No exact remaining shard count is asserted without the final classification inventory. At10.5s/shard plus roughly394s discovery,156 shards imply roughly2030s whole (Inferred), above the unchanged1800s alarm.

Confirmed repeated source paths per materialized shard:

1. `native_protocol._build_execution:623` calls `program_dumps` only to read schema_version, despite receiving the shared program artifact. `NativePortEvidence.__init__:729` dumps it again to seal program SHA. Generic `validation._analyze:473` dumps again to verify Snapshot, then `NativePortEvidence.require_scope:747` dumps it again to verify exact scope. These are at least four complete shared-program encodings per shard, in addition to the single initial publication. Each `program.codec.dumps:273` invokes `_require_record_and_graph_valid`; they repeat full graph validation, not only hashing. Generic callers must still reject modified programs; this is not permission to remove validation.
2. `_native_port_order_errors` runs once in owned ctor and again in require_scope per shard. It reconstructs all127 static catalog definitions and validates every shared formal/native slot. At `native_port_protocol:548`, every target searches the full `program.provider_bindings` list, so this phase repeats catalog-slots × global-bindings scans. It also repeats needed shard-local actual occurrence/denotation/producer checks, which must remain independent.
3. For each held denotation, `NativePortEvidence.resolve:782` scans the shard's operations for its activation's INVOKE and the evidence bindings again. This is a shard-local quadratic candidate, separate from global-program work.
4. Projections are encoded, validated and detached by existing external snapshots. These costs concern actual shard content/parent closure and are not raw-source rehash or full original-bundle import. No measured time share is claimed.

Root-only minimal optional sampling, with an already available `py-spy` executable and exact gate-Python PID (not shell/time session ID):

```
py-spy dump --pid <actual gate Python PID> > <new exclusive sample file>
```

Take3–5 separate stack dumps during different shard phases, a few seconds apart, preserving raw output/timestamps and tool/version. Do not signal the Python process, inject profiling code, install/change dependencies, or restart it. If ptrace/tool permissions prevent sampling, retain that failure and use progress/source inference; do not loosen runtime permissions or mutate the producer. A stack dump is a sample, not a timing profile. Repeated `program.codec.dumps` / graph validator stacks would support item1; `_native_port_order_errors`/provider-binding list comprehension item2; `ExternalSnapshots`/record codec item4. Parent may choose an already available bounded sampling profiler for better proportions, but none is invoked here.

If the unchanged wall cap triggers, keep each exclusively published shard, complete source receipts, shared program/interface, private diagnostic index and first failure. Do not mark all dispatches modeled, do not increase the timeout to hide repeated work, and do not retry automatically. A later reviewed fix could validate/seal immutable static canonical program/catalog bytes once in an owned session, reuse indexes keyed by the exact artifact and immutable source, and keep per-shard Run/occurrence/source/denotation checks. That requires an explicit safe validator contract for static reuse rather than caller trust flags or removal of checks; no implementation is proposed for the active run.
