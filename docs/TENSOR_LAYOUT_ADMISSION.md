# Physical Tensor layout spelling: actual defect and bounded fix

2026-10-23. **Observed → Implemented → bounded geometry Verified.**
Only `scar/trace/tensor_physical_import.py` changed. No old trace/bundle was
rewritten, no allocation was created, and no content/readiness fact was added.
Ownership is separate from capture_import.py; its owner confirmed no active
import dependency on this module.

The exporter reads a pinned PyTorch TensorMetadata layout object and serializes
`str(layout)`, yielding `torch.strided`. StorageRegion's canonical geometry
contract uses `strided`; `ValueGraph._region_errors`, provenance._byte_bounds
and execution.coverage recognize only that spelling. Previously imported
ordinary Tensor views therefore passed structural validation as an unknown
layout while their byte bounds/overlap remained unresolved.

The importer now calls `canonical_tensor_layout` under exactly
`scar.tensor-physical-event-tree-v1` and provider revision
`cf30153c4c131c8164ee7798e5022d810682e2cb`. It maps exactly `torch.strided` to
`strided`, preserving `provider_layout`, the normalization rule and all original
physical/ETO source references. Other provider layouts retain their opaque
spelling. The unqualified bare spelling `strided` is rejected as a provider
source token; unknown profiles/revisions cannot grant canonical geometry.
No global geometry validator was broadened and dtype/shape/stride/offset,
ObjectID, StorageRegionID, AllocationID and epoch semantics are unchanged.

The fresh experiment is
`artifacts/experiments/first_stage_tensor_layout_20261023/`. Its source producer
receipt pins the modified module SHA
`c834d0a1072b610d9cc23d163709171ae329b6b175f1a9388c95e9842a5f0372`.
The real bounded gate reads28 physical raw rows,70 original ETO nodes and16
old region rows, then regenerates four normalized region records from those
original metadata/ETO offsets. It reuses each old region and allocation ID.
The observed allocation receipt at physical line11 has provider epoch2 and
640bytes; no Allocation object or identity is constructed by the gate.

| Actual original view | Canonical byte bounds |
| --- | --- |
| float32[16,10], stride[10,1], offset0 | [0,640) |
| first row float32[10], stride[1], offset0 | [0,40) |
| scalar float32, offset0 | [0,4) |
| second row float32[10], stride[1], offset10 | [40,80) |

The old records all yielded no byte bounds. Normalized full/row and row/scalar
overlap; the two real row views in the same allocation are disjoint. An unknown
sparse layout still yields POSSIBLE/unknown geometry. Wrong profile/revision
and an unqualified provider spelling reject. Apart from layout and its two
provenance metadata fields, regenerated records match the original records.

Actual exit0; process wall1.08s, user0.97s, system0.10s, maximum RSS76292KiB;
gate's internal analysis0.343s. Report SHA
`834eeff0bb1fbca9f8fef4d7ee4210f2f3d34f4f2aaa61a903da4443ae563fa6`,
19808bytes. Prefix reading totals243863 decoded bytes; full raw/shard hashes
were not revalidated in this gate. The report explicitly records no whole-bundle
validation or full importer reexecution. The existing importer integration is
source-reviewed; its next full fresh projection will use this conversion.
No target, torch import, compile or broad test suite was run.

The generated records are a fresh bounded experimental projection, not appended
duplicates in the immutable old graph. The fix enables already-observed
geometry to reach existing bounds/overlap code. It proves no Tensor contents,
logical version, copy equivalence, permanent alias interval or GPU readiness.
The four previously empty content tables remain empty here.

The scalar audit was also checked: ETO `#/nodes/1` is node6 named
`torchvision::_cuda_version`, schema `() -> int`, observed output Int13020.
It is not the profiler process/PID sentinel, but it is also not an actual ATen
Tensor operation. No new logical/content record was created from it. The next
NativeBoundary bridge should prioritize the real ATen native slots and their
owned dispatch/physical associations, retaining that distinction.
