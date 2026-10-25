# Minimal actual ATen protocol/core port bridge

2026-10-23. **Approved plan; bounded implementation/gate completed.**
See NATIVE_PROTOCOL_BRIDGE.md for actual implementation, first failed attempt,
second PASS, precise scope/cost and retained frontiers. The proposal below is
kept as the original design record. This follows
NATIVE_VALUE_CHAIN_AUDIT.md and the bounded layout fix. The acceptance target is
actual reference/port/physical-record correspondence, not making four content
tables nonzero. The driver-version scalar is excluded as a bridge target.

## Public entry and artifacts

Proposed normal entry:

```text
bind_native_protocol_window(
    coordinates: CaptureCoordinates,
    capture_directory,
    partitioned_native_manifest,
    out_dir, *, expected_manifest_sha256,
    window=NativeProtocolWindow(first_sequence=1, max_sequences=16),
    budget=NativeProtocolBudget(...), progress=None
) -> NativeProtocolWindowResult
```

Inputs are actual retained source paths and the explicit native archive receipt,
not caller-constructed slots, native instances or a validated=True flag. The
coordinates must have the exact payload/hash, Run/process and source memberships.
The entry opens/verifies the three raw sources itself, parses only the bounded
selected window, and creates a private owned NativePortEvidence session. It
neither calls the target nor accepts a serialized success claim as that session.
The window selector is a capture coordinate/budget; eligibility uses actual
OpOverload/schema identity and available slots/markers, never LeWM/function names.
Skipped/unqualified sequences and unvisited capture obligations remain explicit.

The result contains:

* a genuine typed protocol-interface ProgramGraph and its real ProgramSnapshot;
* an ExecutionModel for the actual selected native calls/ports;
* small ordinary existing-IR source projections and their exact artifacts;
* immutable owned provider-slot evidence for validation in this process;
* original manifest/chunk/row/raw references, counts, guards, measured read costs
  and remaining obligations; no transformation authorization.

Save program.json, execution.json, native-interface.json (the provider's declared
flat signature), source-projection artifacts/receipts and report. The interface
document and receipt index are proof inputs, not another Operation/Value/state IR.
The original capture, native archive and all identities remain intact. A later
public replay must reopen/reverify original inputs and compare rebuilt output;
loading report.status=PASS does not recreate an owned evidence session.

## Actual matching rule

For each selected BEGIN/OUTPUT/END group:

1. Verify closed metadata, exact original bytes/counts, nonce, shared process/
   Python-ident/native-thread qualifications, operator and marker paths. Require
   RETURNED and real output marker for the first normal-completion adapter.
   Raised/incomplete/unsupported observations stay accounted for as frontiers.
2. Resolve the original native span and output marker, with actual ETO ctrl_deps
   and the existing RF/host correspondence. Require one direct native child of
   that span whose versioned schema name/overload agrees with the recorded
   OpOverload identity. Children, wrappers or time-nearby operations cannot be
   substituted. Preserve their raw containment for expansion; do not create
   several canonical writes from the same composite call's repeated outputs.
3. Use the existing pinned schema parser/ordered-path logic. Map args positions
   and keyword names to exact formal ordinals, and result paths to exact declared
   returns. Validate actual boxed arity/type/container structure. Defaults or
   tuple/list mappings that cannot be established become concrete port gaps.
4. Tensor leaves map to the exact held marker objects and their original native
   provider slot. The collector holds input args/leaves through the call and
   observes the returned result before releasing it; that versioned protocol
   justifies point/interval reference correspondence. It does not justify stable
   contents, storage throughout the interval or cross-call equivalence.
5. Follow the original physical marker argument to its existing StorageRegion/
   allocation epoch and source receipts, checking device/dtype/shape/stride/ETO
   offset. Apply only the already-reviewed pinned layout spelling conversion.
   Geometry is attached at its actual marker observation, not silently moved to
   native entry/device execution when intervening state is unobserved.

The existing real examples supply such a view/partial-write stress window:
sequence5/7/8/9 and the corresponding direct children33/49/56/63. Production
selection must derive them through the rule above; these numbers are audit
locators, not selection conditions.

## Static representation and actual occurrences

`program/native_validation.py` requires NativeBoundary's owner to be a
DEFINITION_GRAPH provider. ETO is EXECUTION_EVIDENCE and must not be relabeled.
Create a versioned ATen-schema interface definition artifact/provider, use its
real typed Region/Operation/Uses and ProviderBindings, and retain a separate ETO
execution provider/observation scope. ProviderBindings name interface-definition
elements; actual ETO occurrences are linked in ExecutionModel, not smuggled into
static binding keys.

The Region describes the native protocol interface, not internal kernel code.
Use ReferenceValue for Tensor references and typed values for native boxed
scalar arguments/results. Input/result order is explicit, with the exact source
path/flat-signature guard. State/world before/after and normal/raise interfaces
remain conservative and effects_complete=False. Declared may-write/may-alias
annotations remain partial; no complete writer/effect or closed exception/RNG
contract is manufactured. No Python source body's required expansion is reduced.

ExecutionModel contains real RegionActivation/BlockVisit, the opaque invocation
and its actual normal completion, ValueOccurrence/UseOccurrence and native
input/output basis. Match observed native start/end evidence under its existing
clock/thread contract; host return is not a GPU-ready event. Tensor references
may have ObjectIdentity denotations through actual held WeakRef epochs. Unknown
scalar/state/exception denotations remain Unresolved. An observed scalar must
not become a static LiteralOrigin/code constant simply because its captured
value is known. No new LogicalValue/DataIdentity/Materialization is required for
this first reference bridge.

## Honest bounded source snapshots

Existing ExternalSnapshots requires an exact complete ordinary ValueGraph or
EvidenceGraph artifact. The partition manifest/chunk cannot impersonate that
artifact, and a partial dictionary cannot use the full original graph SHA.

Use small explicit read-only source-window projections in the existing graph
schemas. Selected original ObjectInstance/Allocation/StorageRegion and legacy
native instance records retain their IDs, fields and actual source records.
They get their own projection artifact SHA plus an exact parent manifest/chunk/
row witness. Canonical producers/Uses/state exist only in the new core graph;
source projections do not invent another producer/state graph or a new physical
allocation. The layout-qualified representation retains its raw layout/rule.

Legacy instance projection needs actual parent closure, including original root
sentinels; never clear parent fields or synthesize an observed root. Existing
capture-model metadata supplies record-position hints (for example37449 native
memory allocation rows before the physical rows). A hint only locates a candidate:
whole-chunk SHA, row ordinal and exact original ID/record must still agree.
The small actual capture-model.json also retains native.inventory.eto_nodes;
the final original ETO-instance ordinal can therefore locate the candidate root
sentinel without decoding intervening instance chunks. For the sampled epoch2,
37449 plus its original physical epoch-insertion offset locates the allocation
candidate. These are index hints from this saved producer, not trusted counts
or hard-coded identity rules; a wrong candidate must fail exact record matching.
Missing closure/record or budget exhaustion is a frontier, not permission to
create a stand-in. No source table is silently declared complete by this window.

Add a bounded selected-ordinal reader to BundlePartitions using its existing
whole-chunk physical/decoded receipt checks. This avoids walking preceding
chunks or reconstructing the multi-GB bundle. It changes storage access, not IR.
Source-window metadata may hint the root/epoch/object positions, but never grants
record semantics or runtime identity on its own. The projected graphs pass the
ordinary codecs and validators and remain exact original-source projections.

## Independent provider-slot replay in the existing validator

Add a closed-profile native-port resolver, following the existing native-memory
resolver pattern. Its data come only from the private owned raw reader/session.
It independently recomputes native child selection, schema/path/marker/held-object
and original physical-record correspondence against the supplied canonical
ProgramSnapshot, execution occurrences, Run and projection receipts. The session
must match all exact source scopes and the sealed program; it is not a public
dataclass accepting success flags. It is discarded on source/snapshot/Run change.

`execution.validation.validate/require_valid` gain an optional exact concrete
native-port evidence input, propagated to their normal context. Old calls keep
their contracts and gaps. In content_validation's NativeInputRef/NativeOutputRef
branch, invoke that resolver after the ordinary native_port check. Suppress only
`content_native_correspondence_unverified` for the exact independently matched
reference/port. Unmatched/declared-only cases keep the original gap. Keep generic
provider-token rejection and the old evidence-edge port gap intact.

Core ObjectIdentity/actual ordered references and original observed geometry can
then be queried. They still do not constitute ContentRead of a known logical
version. No logical-content read/write/ready proof is authorized merely by
accepting the native interface. A standalone artifact replay must construct a
fresh owned session from the exact original raw inputs, never restore a boolean.

## Exact minimum code surface

| File | Purpose |
| --- | --- |
| NEW `trace/native_protocol.py` | Owning public window reader, actual matching, existing typed core/execution construction and source projections. |
| NEW `ir/execution/native_port_protocol.py` | Closed provider-slot proof/session resolver; no target/provider callback execution. |
| `ir/execution/validation.py` | Optional concrete owned native evidence in the existing validation context. |
| `ir/execution/content_validation.py` | Conditional independently replayed NativeInputRef/OutputRef branch; legacy behavior preserved. |
| `trace/native_schema.py` | Extract/reuse the current pinned parser/port helper rather than duplicate schema matching. |
| `store/bundle_partitions.py` | Selected-ordinal/chunk reads through existing exact byte checks. |

No core/execution wire entities, state model, source program, optimizer or backend
need changes. This proposed six-file surface is subject to root source review
before implementation; a newly discovered blocker must be reported, not solved
by broadening the proof or fabricating source facts.

## Cost and one real acceptance window

The current three raw source declarations total546619922 bytes: ETO321287818,
dispatch78870130 and physical146461974. If full raw hashes are independently
rechecked, stream them once with an explicit source-byte bound and retain only
the selected records; do not parse/materialize the entire bundle. If shared
owned coordinate ingestion already performed that exact verification in-process,
reuse only that genuine owned result and record the I/O once. A saved membership
boolean or a prefix hash is not a substitute. Actual I/O/time/RSS must be reported.

Whole selected chunks are independently bounded (existing producer chunks are
about16MB decoded). Preflight the exact closure/chunks and measured declarations;
do not guess a huge bound and launch an unobservable scan. Count unselected
records/relationships as outside this window, preserving full-capture totals.

One offline gate should validate actual ATen ordered references through a real
view and scalar partial-write selector, actual held ObjectIDs, original storage
regions/epoch and both new/native namespaces. Reject a swapped input/result path,
wrong child/schema, wrong Run or missing original source record; leave aliases/
contents/ready unresolved where evidence is incomplete. Compare original snapshot
SHA/metadata and preserve every failure/checkpoint. No new target, compile, full
source preparation, multi-GB bundle replay or content-table count target belongs
to this gate. First-stage modeling remains OPEN.
