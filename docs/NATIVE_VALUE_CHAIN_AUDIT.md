# Actual native value → core → content gap

2026-10-23. **Observed bounded records/source audit; Proposed implementation.**
No production file, active source gate, target, compiler or source frontend was
changed/run. The reproducible stdlib-only read is
`artifacts/analysis/native_value_chain_audit_20261023/audit.py`; its audit.json is
196233bytes, SHA256
`843f04254a497922d184e7447ac3af6143e6e7cde031c28620a06c7cb6ec8832`.
That script reads623878 decoded prefix bytes plus the72965-byte manifest,
retaining69 sample records. It explicitly does not claim full raw/shard SHA
replay; declarations and sampled row hashes/locators remain separate.

## 1. Why the four content tables are exactly zero

The actual manifest is
`first_stage_joined_physical_20261023/result/native/bundle-partitions/manifest.json`.
It declares461242 instances,73923 provider references,41993 Python objects,
74955 allocations and108682 storage regions, but zero logical_values, versions,
provenance, materializations and bindings. This is the native bundle's ValueGraph,
not a count of the source ProgramGraph's existing typed Values.

The reason is an explicit adapter boundary, not missing Tensor observations:

| Actual writer | What it writes | What it deliberately does not establish |
| --- | --- | --- |
| `trace/native_import.py:_Importer.__init__/tensor/slots` | Empty ValueGraph; actual ETO instances, opaque Tensor provider tokens, INPUT_REFERENCE/OUTPUT_REFERENCE edges and exact ordered paths | No logical content, lifetime generation or content producer/read; non-Tensor boxed values are ignored by slots |
| `trace/native_schema.py:recover_schema_contracts` |100 provider schema/effect contracts,481 formal slots; actual Tensor paths annotated with qualified schema slots | Effects remain PARTIAL may-write/may-alias, not actual writes, complete reads, RNG/state closure or readiness |
| `trace/dispatch_import.py:import_dispatch_evidence` | Original held Python ObjectIDs and exact marker/object/provider slot associations | No direct Python→ATen callsite, content version or future object/storage binding |
| `trace/tensor_physical_import.py:import_tensor_physical` | Existing add_allocation/add_region and USES_STORAGE edges at exact owned markers | Explicit logical_version=None; no logical/materialization records, persistent association or ready |

The native path never calls add_logical_value/add_version/add_provenance/
add_materialization. Running it again cannot populate those tables.
`trace/normalize_v2.py:snapshot` does create provisional independent snapshot
roots/materializations for a different legacy format, but supplies no cross-
snapshot equality and invents snapshot-scoped allocation placeholders. Applying
that routine here would discard the better existing epoch identities and would
not establish the missing producer/use/content chain. `TensorObserver` is a
live opt-in adapter, not an offline reconstruction of this capture; its registry
also owns a separate graph/lifetime ledger. Neither is an automatic bridge.

## 2. A real same-Run chain, with original locators

All examples use process369749, ETO artifact SHA
`625558680ced281fc2b4789d9d742bc97dd4fed57106701e98adea3ebe0428b6` and native
scope `native:2a622492625eb1b2a7a105036e0ac792b5a6249fc60cf111443bf7fe53140d88`.
These are audit examples, not name-based production selection rules.

| ETO pointer / instance node ID | Observed ports |
| --- | --- |
| `#/nodes/26`, node34, empty | output token35, shape[16,10], stride[10,1] |
| `#/nodes/27`, node37, zero_ | input/output token35, schema Tensor(a!) |
| `#/nodes/28`, node33, zeros | output token35; contains the preceding two native children |
| `#/nodes/38`, node50, as_strided; `#/nodes/39`, node49, select | token35→token51, output shape[10], stride[1], offset0 |
| `#/nodes/43`, node46, outer select | same returned token51, enclosing the selected native implementation |
| `#/nodes/50`, node63, copy_; `#/nodes/54`, node60, outer copy_ | ordered self token58 and src token40; returned token58; scalar view into token35's storage |

The original dispatch JSONL has sequence5 at lines13–15 (zeros), sequence7 at
lines19–21 (select), sequence8 at22–24 (select), and sequence9 at25–27 (copy_).
BEGIN records contain the actual observed OpOverload string; END is RETURNED.
The imported bridge retains exact marker ancestry/slot paths but currently
does not retain BEGIN.operator in its compact observations. This omitted
field is still in the original raw records; no target rerun is needed to read it.

The original physical sidecar SHA is
`d666fa820e88d95a6ea0a2539c8241126ac605ea48094bb2e330318c7756a778`.
Existing regions point to its line12/arg0 (zeros output shape[16,10]),
line16/arg0→17/arg0 (select input→output), line18/arg0→19/arg0 (scalar select),
and line20/args0,1→21/arg0 (copy_ arguments→result). These original regions all
name the existing physical epoch ending
`dc84edf549c8f021c2f0cbb57d0ef0f4352e33b2a78059f308eb02a4a27edfe1`
for token35/51/58; source token40 names a different epoch. Region geometry is
available. Allocation identity does not supply a logical content identity.

There is also an actually captured scalar: `#/nodes/1`, node6, returns Int13020
from a zero-argument schema. The raw JSON contains the value, not a Tensor
sample; native_import currently drops it. A generic strictly decoded boxed Int
output can have an exact observation-local content value. It must not be
turned into a static code constant or global/environment-invariant value.

## 3. Existing core/content endpoints and the exact blocking checks

The necessary records already exist; no second producer/state IR is needed:

* `program/model.py`: Operation, ordered Use, ReferenceValue/DataValue,
  OperationResult, StateAccess/StateVersionValue and completion ports.
* `program/providers.py`: ProviderEnvelope/ProviderBinding/ProviderElement
  with typed OPERATION/REFERENCE_VALUE/DATA_VALUE/USE and original operand paths.
* `program/native.py`: NativeBoundary plus ordered NativeInputSlot/OutputSlot.
* `execution/coordinates.py`: real OperationOccurrence, ValueOccurrence,
  UseOccurrence; `execution/content.py`: ValueDenotation, ObjectIdentity,
  DataIdentity/VersionRef, NativeInputRef/OutputRef and ContentRead.
* `v2/values.py`: original LogicalValue/ValueVersion/ProvenanceRecord,
  Allocation/StorageRegion/Materialization. `execution/production.py` supplies
  SourceEndpointBridge/WriteAssociation/OutcomeProduction; work.py supplies
  WorkSubmission/ResourceOutcome/WorkQuiescence.

But trace/analysis has no automatic constructor of a NativeBoundary from these
actual provider slots. Source calls/retained ancestors cannot substitute for
that native/core port mapping. Core ReferenceValue denotes a Tensor reference;
its referenced mutable contents are a separate identity/version obligation.

Two validators make the current disconnect concrete:

1. `execution/production.py:_validate_evidence_reference` rejects
   PROVIDER_REFERENCE as a source-content endpoint. A token is not content.
2. `execution/content_validation.py:resolve_basis` leaves
   `content_exact_port_unresolved` for the old evidence graph: its generic
   operation/value edge lacks an original typed Use/result ordinal. The
   NativeInputRef/OutputRef branch checks real core entry/completion ports but
   still leaves `content_native_correspondence_unverified`. A NativeBoundary
   declaration alone is not replay of the actual provider argument/result.

Therefore filling ValueGraph with fresh nonce IDs would leave both checks
unresolved. A useful implementation must carry the existing ordered provider
slot evidence into actual canonical ports and independently validate it there.

One further mechanical bug blocks the available byte geometry: physical import
stores `layout='torch.strided'`, while `ValueGraph._region_errors`,
`provenance._byte_bounds` and execution coverage accept canonical `'strided'`.
Bounds/overlap therefore remain unresolved even for the sampled ordinary views.
The fix needs an explicit versioned provider-layout normalization at admission,
preserving the raw layout and old immutable artifacts; it is not permission to
assume arbitrary layouts are strided or silently rewrite old graph bytes.

## 4. Smallest next implementation with real leverage

Implement one native-slot→existing-core bridge, not a content-ID cache:

1. Consume the already checksum-bound original native/schema/dispatch/physical
   fragments and shared capture coordinates. Read original BEGIN.operator and
   outcome, rather than inventing them from labels. Use the pinned provider
   OpOverload/schema identity, exact owned span/direct-child structure and
   ordered actual paths. Require a unique consistent native boundary; composite
   parents/children remain distinct observations, not duplicate semantic writes.
2. Build only a genuine native **protocol-interface** ProgramGraph fragment
   with the existing typed core/ProviderBinding/NativeBoundary records. Tensor
   arguments/results are ReferenceValues, not contents. Boxed scalar leaves
   retain exact typed observation values; a dynamic output remains OperationResult
   with an observation denotation, not LiteralOrigin asserted as source constant.
   Unknown state/effects/exception ports remain explicit. Use its real artifact
   namespace/ProgramSnapshot, not the Python composition manifest as one graph.
3. Bind that actual native entry/completion and ordered uses through the fixed
   provider-slot replay into ValueOccurrence/UseOccurrence and original held
   ObjectIdentity where available. Then follow the existing marker object/
   region/epoch association. Missing object or nonunique port remains a frontier.
   Extend the existing content resolver only for this independently checked
   native-port profile; do not suppress either unconditional gap with a caller
   boolean or declared coverage field. Keep SourceEndpointBridge's provider-token
   rejection intact.
4. Add exact boxed scalar observations to the existing ValueGraph and their
   true producer/port bridge. IDs are occurrence+original slot scoped; equal
   observed literals need not share lineage. Unknown dependency/state closure
   stays partial. A serialized scalar materialization may have region=None;
   do not fabricate a DRAM allocation to make its count nonzero. Its observed
   host/serialized value does not prove any GPU tensor ready.
5. For Tensor contents, first emit the exact remaining demand at each ordered
   port/physical selector. A future versioned provider contract may establish a
   normal write/view/copy relation and its actual footprint. Existing schema
   may-write/may-alias is insufficient for actual content transfer, exact copy,
   write completion, missing scalar parameters or a closed writer set. Do not
   turn the current storage epoch into LogicalValueID or propagate one version
   across repeated token/metadata observations.

This is a small concrete adapter/resolver path, but complete Tensor lineage is
not available merely by connecting the existing metadata fields. New general
provider-contract evidence or capture fields are necessary for the final step.

## 5. What the present artifacts do not prove

| Relation | Available | Missing / required frontier |
| --- | --- | --- |
| producer and ordered argument/result **references** | ETO instance, exact slots/schema paths, dispatch-held objects | Formal native→core occurrence/port replay adapter; compact bridge dropped operator field |
| alias/view geometry | Same provider physical epoch at held markers; shape/stride/offset | Canonical layout normalization; association is point-scoped, not a permanent object/storage binding or full content equality |
| post-write content version | Schema Tensor(a!) declaration and returned reference | Actual data-write/footprint contract, pre/post interval and external/concurrent-write coverage; copy_ of one scalar cannot replace the whole[16,10] version |
| copy/materialization identity | Actual CPU/GPU copy work may exist separately | Exact source/destination content versions and operation/work endpoints; `.to` call or matching dtype/shape is not a physical copy |
| allocation lifetime | Existing capture-local epoch and allocator receipts | No merge with old Kineto namespace by pointer; an open birth/free boundary remains open |
| ready/valid interval | Native host end and correlated work activities | Tensor output→specific work/write frontier, queue/context/order and completion/quiescence proof; host RETURNED is not GPU completion |
| same content across calls/Runs | No complete coverage in these sidecars | Same ObjectID/token/_version/shape/sample/source does not supply it; all IDs stay in original capture/process/artifact scope |

`ProvenanceRegistry.origin/transform` default their new materialization to
ready=True, and the live registry creates its own allocation/lifetime graph.
Blindly feeding this offline capture into that API would create incorrect
readiness and duplicate physical identities. Reuse the existing records in the
original graph, with readiness unresolved unless actually established.

## 6. One bounded acceptance after implementation review

Use a declared small native window selected mechanically by available schema/
ordered slots/owned span/physical association, preserving the whole capture's
denominators and reporting all untouched obligations separately. Verify one
original scalar content result and one Tensor reference→view→partial-write
window through actual core ports and original storage regions. Preserve the
two nested native output observations without counting two independent writes.
Negative checks must leave content equality/readiness unresolved when an input
is mutated, aliases overlap, foreign-write coverage is missing, operator matching
is nonunique or the evidence belongs to another Run. Run only this bounded
offline model gate: no target/compile, no105-source-graph replay and no full
multi-GB bundle scan. A partial useful bridge is not first-stage completion or
an optimization result; mandatory content/ready gaps remain OPEN.


## Follow-up bounded layout fix and scalar clarification

The layout defect is now narrowly implemented and geometry-tested against four
actual original views; see [TENSOR_LAYOUT_ADMISSION.md](TENSOR_LAYOUT_ADMISSION.md).
Old artifacts and content/readiness qualifications remain unchanged; no full
importer rerun or native/core bridge is claimed.

ETO #/nodes/1 was independently checked as node6, torchvision::_cuda_version,
with exact raw type Int and output13020. It is not the process/PID sentinel, but
it is not an ATen Tensor operation either. No records were added to the four
empty content tables from this query. The next NativeBoundary bridge should
start with the actual observed ATen slots/owned spans/physical associations,
keeping numeric observations separate from source constants and GPU readiness.
