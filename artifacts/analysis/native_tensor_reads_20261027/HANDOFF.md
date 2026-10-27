# Occurrence-scoped native read API

```python
from scar.analysis.native_tensor_reads import (
    build_native_tensor_read, read_native_tensor_read,
)
from scar.ir.execution.native_tensor_reads import NativeTensorRead, NativeReadCondition

artifact = build_native_tensor_read(navigation: ProviderArtifact,
    storage_index: ProviderArtifact, out_dir,
    row=None, path=None, native_input=None, value_occurrence=None, execution=None,
    max_input_bytes=256_000_000, max_seconds=60)
record, values, measurements = read_native_tensor_read(artifact,
    max_input_bytes=256_000_000, max_seconds=60)
```

`artifact.schema='scar.native-tensor-read'`; a `ProviderArtifact` must carry exact original URI/SHA/size/schema. Input selector semantics match `query_native_input_allocation` (typed NativeInputRef or ValueOccurrenceID requires original execution artifact). One currently supported explicit protocol is `PINNED_CPU_COPY_SRC_READ_V1`, exact fixed-provider copy_ src slot1; other schemas/accelerator/layouts reject. No workload names, time/correlation guesses or original ID replacement.

`NativeTensorRead` adds exactly the missing `ContentRead → result:VersionRef` relation. `record.input` is the original reference ValueOccurrence, not the read payload. The result is in ordinary v2 ValueGraph. Original UseRef/NativeInputRef, state support/normal state effect, actor/interval/Run/process/snapshot and original AllocationTarget remain typed endpoints. The graph has one read-local LogicalValue/Version/ORIGIN, no Object/Storage/Materialization or new core occurrence. ORIGIN is a symbolic root in this read's namespace, not an assertion of physical data genesis; upstream numeric contents remain unknown. Distinct reads have independently scoped symbols and do not prove equal/different numerical contents.

Qualification is `CONDITIONAL_READ_RESULT`. The reader verifies original immutable artifacts and uses `query_native_normal_completion` to join the actual selected normal interface; it never restores a live owner from JSON. Closed typed conditions preserve implementation assumptions, actual storage-read branch, state footprint, interval stability and upstream origin gaps. Reference ObjectIdentity is unchanged. No DataIdentity is assigned to the reference input. No immutable content snapshot, actual write, source Materialization, readiness or optimization legality is granted. Actor may remain original UnresolvedHostThread.

The normal CLI/model-run can create per-selected native input fragments and then read the exact receipt. This implementation does not automatically enumerate/import every native read or install records in an ExecutionModel; its old wire/validator and old UNKNOWN native fragments are unchanged. The independent normal-completion module is an explicit source dependency, not a second native execution authority. Root owns CLI/automatic import integration.
