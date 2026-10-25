# Proposed native-batch V2 reference domain

Design for root review before production edits. V1 remains strict and unchanged.
This uses existing IR records and codecs; it creates no new IR or content facts.

| Domain | Qualification and representation |
|---|---|
| A: native port/occurrence | Preserve every actual native Tensor leaf as ReferenceValue, ValueOccurrence, ordered Use and NativeBoundary slot, anchored to its exact ETO artifact/node/tree path. Complete source/ABI and actual-flow checks apply even without Python identity. |
| B: held Python object | Grant ObjectIdentity only for an exact original held path -> formal -> held marker -> native tuple mapping under the collector contract, with an existing original WeakRef ObjectInstance. |
| C: point geometry/allocation | Independently check original physical marker metadata, region, epoch and required birth/extent. Missing geometry, birth or an empty CPU storage witness is a per-port geometry gap, not permission to discard a qualified B fact. |
| D: contents/state/ready | Remain unproved. Neither A, B nor C creates a ValueVersion, content equality, complete world/state effects, aliases or readiness. |

The first B implementation can conservatively retain V1's full marker/native
Tensor tuple, type, shape and stride agreement, but require no physical metadata
or birth as a prerequisite for that held-reference match. The Python collector
holds each Tensor/Parameter leaf and passes the same ordered held list into its
actual marker. The pinned marker/ETO contract and exact original tuple/ordinal
link remain necessary. Missing Python-held identity is not repaired by physical
shape, pointer, allocation size or the provider's anonymous Tensor ID.

For a native-only Tensor port, emit the existing ValueDenotation with an
Unresolved identity, NativeInputRef/NativeOutputRef basis and exact native-slot
ProviderFactReference. Its Unresolved EvidencePoint names the actual Run/process
and source fact. For 3182 input 1, the source is the actual ETO node ordinal
20477, `inputs/values/1`. Do not label its boxing origin or scalar value known.
The known self input/output retain their independently checked ObjectIdentity.

Existing `ValueDenotation.identity` already accepts Unresolved. Generic content
validation already retains `content_denotation_unresolved` and unverified native
correspondence for that case; its resolver must not authorize Unresolved as an
object. No generic IR/codec schema change is currently needed. The V2 source-owned
resolver can add explicit geometry obligations with existing diagnostic records.

Required owner changes, after preserving the first source snapshot:

* `native_port_protocol.py`: add a fixed, explicitly versioned V2 capability;
  replay A, B and C independently, retain V1's exact bijection function, and seal
  source-derived per-port qualification in the live owner. Caller flags and saved
  inventory rows cannot authorize qualification.
* `native_protocol.py`: create all native Tensor occurrence/denotation records;
  B ports use original ObjectIdentity, other ports use Unresolved. Project original
  objects for B separately from the subset with complete C region/allocation
  witnesses. Source identity contradictions remain hard errors before absence
  classification. No invented object, allocation or state producer is added.
* `native_capture_batch.py`: select V2 explicitly, persist per-port A/B/C/gap
  counts and facts, and keep the exact full actual dispatch inventory. Geometry
  absence does not turn the whole invocation into an unmodeled reference frontier.

Independent V2 validation must check full static ordinals and every actual Use,
normal transfer and ValueOccurrence. Every native Tensor port must have exactly
one denotation at its actual slot. The source-replayed B set determines which
ports require exact ObjectIdentity; ports outside it require Unresolved and may
not borrow any existing ObjectID. Retain source identity/marker/owner/parent/RF/
thread checks and actual occurrence inventory checks. A newly sealed generic-valid
wrong port/Use/denotation order must still raise NativePortOrderError. Omitting
or rewriting a known held denotation cannot convert it to an unknown-port waiver.

The shared interface document, report and inventory declare V2 profile/capability
explicitly. Avoid an overloaded `qualified_dispatches` implying A=B=C=D. Publish
disjoint modeled-with-complete-B, modeled-with-per-port-gaps, and unmodeled-frontier
counts summing to actual enumerated dispatches; report B and C port coverage
separately. Metadata declaration, actual BEGIN/group counts and unvisited
obligations remain independent. Defaults, None, nested or empty containers use
actual provider tags plus formal structure; zero-dimensional Tensor shape `[]`
must not be confused with an empty container. Missing native leaf provenance is
an explicit gap, never an operator-name exception or guessed Python scalar.

Before editing, retain all 269 first-freeze source bytes and their SHA receipts
in a new baseline location; preserve the first freeze, runner, DB and time in
place. The second gate uses a fresh attempt directory and a fresh legitimate
source acquisition; the old SQLite file remains diagnosis-only. Keep the current
budgets, measure added costs, and do not expand the nearly full source index with
unbudgeted classification rows. Persist qualification inventories as ordinary
new artifacts. No automatic retry follows a failure.

Small preflight checks should cover 3182's held subset/native-only port, genuinely
optional None, omitted defaults, empty/nested containers, missing birth, empty CPU
geometry, identity contradictions and newly sealed wrong order. Root reviews
the new freeze and runner before one second real full-domain gate. That gate
requires complete actual accounting and exact independent proof for B-qualified
ports while retaining every A/B/C/D obligation. The old V1 16-prefix limits and
strict rejection contract remain unchanged.

For a future unified capture, original Profiler EventTree TensorMetadata for
native operations, not just held markers, is a candidate source for additional
C witnesses. That needs new collection fields and exact source contracts. The
current old capture cannot be retroactively supplied with those facts.
