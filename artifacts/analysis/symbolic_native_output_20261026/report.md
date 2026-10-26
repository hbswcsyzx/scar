# Symbolic native output bridge

The new bridge adds a conditional payload symbol to the existing v2
`ValueGraph` while retaining the original `ProgramGraph` and `ExecutionModel`
records unchanged. It does not create an operation, value occurrence, object
binding, evidence edge, or a second producer/use graph.

## Existing and projected layers

For `aten::lift_fresh(Tensor(a) self) -> Tensor(a)`, the canonical program
output is a `ReferenceValue`. Its existing execution denotation remains an
`ObjectIdentity` based on the original `NativeOutputRef`. The bridge records a
separate association from that qualified output occurrence to the original
ETO output port and `OUTPUT_REFERENCE` edge, then to one symbol in the existing
ValueGraph vocabulary.

The symbol IDs are deterministic from the `ProgramSnapshot`, original output
`ValueOccurrence`, `NativeOutputRef` operation/boundary/position, ETO source
ordinal/path, native instance and provider descriptor. Distinct IDs only name
distinct endpoints; they do not assert numerically different Tensor contents.
They also include the snapshot URI and the execution artifact URI/SHA, so the
same occurrence string in another saved execution does not collide.
The added graph delta contains one `LogicalValue`, one `ValueVersion`, one
`UNKNOWN` `ProvenanceRecord`, and one inferred `Materialization` with
`region=None`. The materialization retains the observed `Tensor(float)`
representation and `cpu` device.

The existing `ValueDenotation` variants are `DataIdentity`, `ObjectIdentity`,
or `Unresolved`; they cannot carry a second payload projection beside the
object reference. `SourceEndpointBridge` and `OutcomeProduction` describe
already-resolved production/source associations, while `stored_value_projection`
requires a declared stored-read contract and state interval. None represents
this inferred symbolic payload endpoint, so the bridge adds one association
record rather than changing those contracts or rewriting the denotation.

Input content versions, alias/copy relation, numeric contents, normal
completion/effects, storage region/bytes, and device readiness remain unknown.
The symbol revision is endpoint-local and is not Torch `Tensor._version`.

## Real-source readback

Command:

```text
/home/zyf/miniconda3/envs/lewm/bin/python -B artifacts/analysis/symbolic_native_output_20261026/run_lift_fresh.py --output /tmp/lift_fresh_output_reproduce_20261026.json
```

The checked v2 run completed in 3.614 seconds. It resolved existing output occurrence
`...:4:outputs:0` through its original denotation and normal `NativeOutputRef`
to ETO node 18, output path `[0]`, formal slot `...:schema:output_slots:0`,
provider token `...:tensor-token:19`, and original edge
`native:...:edge:4` (`output_reference`). The runner decoded the publication
through the normal strict record and ValueGraph codecs, queried by the original
`ValueOccurrenceID`, merged the delta into a copy of the source graph, and
validated the result.

The earlier v1 publication remains unchanged at
`publication/lift_fresh_output.json` (SHA-256
`5058b03ece42f0f6852a0296a303e719a307f9278fe0fd239267d1d5053e3cf9`). The
checked v2 publication is
[lift_fresh_output_checked.json](publication/lift_fresh_output_checked.json),
SHA-256 `5f57a59432ea9882bf1d13c5d25eda054012ee1612cb1a33cbff6576cd20c813`,
10,305 bytes. Its normal reader enforces a 128 KiB cap, reads a stable regular
file, and recomputes the qualified symbol IDs before returning it. The v1 file
is retained as a historical artifact; current v2 queries use the checked file.

Source graph counts changed only in the merged view: 0 to 1 logical values,
versions, provenance records and materializations. Existing counts remain 82
allocations, 560 regions and 194 objects; no bindings were added. The source
ProgramGraph, ExecutionModel, evidence/value graph shards, and native port
index SHA-256 receipts were identical before and after the run.
The checked receipts were: program `d70685d1521bf28527fa32beb319fa0f9d66db257b6df3ce2559f013141d5bc6`,
execution `d58eaa17e99f207f5a7780ab6e7904615e9376ab472dfcdb81ce7922a28f6dbc`,
source evidence `465f4b2aca85aac6479a097e362f038e84ea13fc4d12fe03ea81e693961648f9`,
source values `02220cb60c22a26b13e45743628283089d510fab0d914d72ec860c4ba370b907`,
and native port index `54f9dfbcc8a4e3cfc720c2dfb0c377d61707cde3f70c1360f1f68fd54cbf17b2`.
Six focused validator mutations were rejected: an added object record,
`Observed` logical status, `Observed` provenance status, a nonempty parent list,
an ID inconsistent with its qualified endpoint scope, and an attempt to replace
the prior publication.

The builder is a conditional join over records the caller already limited and
resolved. It checks their internal cross-references; it does not replay the
complete source artifact or all port shards. The publication query checks its
stored receipt and internal typed consistency only; callers separately resolve
its artifact references when they need source replay.

## API

`build_symbolic_native_output(...)` returns the typed projection association
and its one-symbol `ValueGraph` delta. `write_symbolic_native_output(...)`
and `query_symbolic_native_output(path, output_occurrence,
expected_sha256=...)` provide deterministic publication and normal readback.
`merge_symbolic_native_output(base, delta)` creates a validated merged view
without mutating the source graph.
