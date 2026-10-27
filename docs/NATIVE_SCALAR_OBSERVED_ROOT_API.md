# Owned native scalar input observed roots

`SCAR_NATIVE_SCALAR_OBSERVED_ROOT_V1` is opt-in on `bind_native_capture_model_batches(..., scalar_input_profile=..., static_program=ProviderArtifact, static_interface=ProviderArtifact)`. Static descriptors require exact original bytes; independently rebuilt schema/catalog/program bytes must match. This does not enable a caller-valid flag. The underlying V2 reference profile and default/V1 API retain their meaning.

For each supported original input port at each actual occurrence, the producer uses existing LogicalValue/ValueVersion, ORIGIN provenance with producer=None and no upstream inputs, plus ValueDenotation(DataIdentity(VersionRef)), NativeInputRef, ValueOccurrence and exact ETO FactSource. Equal literal contents keep separate observation roots; they do not establish unequal values/upstreams, object identity, constants, aliases or writes. Scalar values never enter a shared static signature/LiteralEvaluation or free-form content metadata.

The actual parser supplies leaf type.kind and real_type.kind under the original ordered boxed path. Existing decode_pinned_scalar alone defines the bounded Int/Bool/None/ASCII String interpretation. None requires the original tagged sentinel; defaults and opaque companion fields cannot supply it. Double (including NaN/-0/nonfinite representations), symbolic/enum/Device/container/unsupported leaves remain precise frontiers. A Tensor, including0D/numel1 native-only Tensor, always follows the reference path rather than scalar reconstruction. Unsupported scalar denotations retain exact source/Run/process/port and are not converted to arbitrary versions.

The live owned evidence offers:

```python
answers = lease.native_port_evidence.scalar_values(
    lease.execution, lease.program, ordered_denotations, lease.values)
# tuple[NativeScalarObservation, ...]
# fields: literal:PythonLiteral, builtin_type:str, source:ProviderFactReference,
#         version:VersionRef, value:ValueOccurrenceID
```

Use the batch API for multiple values. It checks the exact model/program scope and canonical value-projection bytes once, then performs ordered indexed source/slot/version lookups. scalar_value is the single-item convenience API and delegates a one-item batch. The current scope's immutable owned projection and independently checked complete ORIGIN inventory remain authority; the per-scope denotation index does not grant a bare-ID/global cache bypass. Saved JSON/SQLite/query results cannot mint or restore a live source lease.

Generic validation distinguishes this exact owned typed result from old reference-only bool results. Local scalar content does not establish its upstream producer or a content-read/write effect, and never grants Tensor content, complete state/alias effects or readiness. Default held-reference correspondence still leaves content unproved. Wrong source, formal kind, occurrence, version, basis, projection or original producer/ordinal is rejected independently, including equal-content source/version swaps.

The actual20261025 CPU gate qualified2 None, Bool(False), Int(0) observed roots. It did not demonstrate general numeric/String support or establish upstream provenance. Its264 scalar ports are a different unit from native dispatches, Tensor ports and source-call inventories. REPORT.md under artifacts/experiments/native_scalar_provenance_20261025 records exact scope, raw namespace, budgets and open frontiers.

The separate explicit `SCAR_NATIVE_SCALAR_OBSERVED_ROOT_V2` capability additionally
accepts original `NumberType/NumberType` leaves with actual pinned ETO `Int` or
`Bool` and exact compatible payloads. Import `SCALAR_INPUT_CAPABILITY_V2` from
`scar.ir.execution.native_port_protocol` and pass it to the same batch binder.
The pure decoder's optional `profile` keyword still defaults to V1. V2 preserves
the original formal kinds; it does not replace NumberType with an inferred
primitive formal. Enum real formals, Device/Enum tags, incompatible None/String,
Double, symbolic and container leaves receive no new qualification.

For both capabilities, `builtin_type` names the normalized literal
representation. It never identifies the original Python object's class or
excludes an earlier enum/symbolic conversion. The pinned NumberType conversion
can lower dtype/qscheme/layout objects to integer IValues; only the observed
native boxed content at the exact original port is claimed.

The V2 actual offline gate qualified256 NumberType/Int roots while preserving
the original four roots, within the same264-port domain. Four frontiers remain:
Device1, symbolic real-kind2 and empty-container1. This is evidence for these
observations, not general numeric coverage or upstream/state/ready completeness.
Its single equal-Int source/Version exchange was independently rejected by the
fresh owned checker. Exact receipts are under
artifacts/experiments/native_scalar_union_20261025; no new capture was run.
