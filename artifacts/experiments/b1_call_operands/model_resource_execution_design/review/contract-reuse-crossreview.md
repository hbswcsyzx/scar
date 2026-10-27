# R0 contract reuse cross-review

## Scope and verdict

Read-only review of `docs/M1_RESOURCE_EXECUTION_CONTRACT.md` §§1–3, 6 and the
existing core/provider/evidence/value interfaces listed below. No tests,
collector, workload, or product changes were run. The worktree was at
`309fb359be8665fc90979f270a6d4e4d20c6eb85`; the contract and plan were untracked
drafts at review time.

The layering is sound: static `ProgramGraph` remains the only source of
operations, values, uses, accesses, state locations, and CFG; runtime occurrence
records and provider/evidence links do not replace those objects. Resource
definitions/requirements are also distinct from runtime lifetimes. Before R0 is
frozen, two contracts need exact definitions: the canonical snapshot byte
algorithm and the typed execution-segment/thread identity already implied by
the resume text. Occurrence-to-static-port validation and identity-realm types
also need explicit validator rules; these are finite interface clarifications,
not reasons to build another graph or a full source compiler.

## Required before freeze

### 1. Canonical ProgramSnapshot bytes

`ProgramSnapshot` says it binds the exact bytes of the passed graph, but “exact
bytes” is underspecified. The current provider artifact is
`ProviderArtifact(uri, sha256, size_bytes, schema)`; it has no separate schema
version field. The current canonical core encoder is `scar.ir.program.codec.dumps`:
it validates the graph and emits deterministic UTF-8 JSON with sorted keys,
compact separators, `ensure_ascii=False`, and `allow_nan=False`; it selects
schema versions 2–14 from graph capability (`codec.py:174–230`).

Freeze one algorithm, preferably:

1. `canonical = dumps(graph).encode("utf-8")` using the exact codec version
   declared by the snapshot record.
2. Verify byte length and SHA-256 against `ProviderArtifact.size_bytes` and
   `.sha256`.
3. Verify the bytes decode to the expected `scar.program-graph` schema and
   supported `schema_version`; the version is inside the hashed canonical
   document.
4. Treat `uri` as provenance/location only. Do not hash a source path, arbitrary
   input JSON whitespace, or a caller-supplied schema label in place of the
   canonical graph bytes.

This keeps `ProviderArtifact` reusable without adding a second graph snapshot
encoding. If historical file bytes must also be retained, store them as a
separate input artifact; do not call both raw JSON and canonical `dumps(graph)`
“the exact graph bytes.”

### 2. Resume segments need typed thread ownership

The draft says a resumable body activation persists across suspension, while a
new resume visit/segment must not merge caller context (§2). But the declared
records contain `RegionActivation(ProcessInstanceID)` and `BlockVisit(activation,
BlockID)` only; no typed segment or host-thread incarnation exists. This leaves
no machine-checkable way to distinguish a resume on a different thread from
ordinary CFG transfer, and raw thread IDs can be reused.

Add the smallest execution-only records (or exact equivalent fields):

```text
HostThreadInstanceID
HostThreadInstance(process: ProcessInstanceID,
                   id: HostThreadInstanceID,
                   raw_tid: diagnostic-only,
                   incarnation_source: EvidenceRef | Unresolved)

ExecutionSegmentID
ExecutionSegment(id: ExecutionSegmentID,
                 activation: RegionActivationID,
                 host_thread: HostThreadInstanceID | Unresolved,
                 ingress: ENTRY | RESUME | CAPTURE,
                 start: ExecutionPoint | Unresolved,
                 end: ExecutionPoint | Unresolved)

BlockVisit(..., segment: ExecutionSegmentID)
```

The validator should require the segment’s activation to match the visit’s
activation and the host thread’s process to match the activation’s process.
Ordinary CFG edges stay within a segment; an actual suspend/resume boundary
starts a new segment for the same body activation. A thread ID alone is
diagnostic and must not key identity. Missing thread/ingress evidence stays
explicitly unresolved rather than merging caller contexts. If process/thread
objects later appear as resource targets, reference these same instance IDs in
a tagged `ResourceTarget`; do not mint a parallel `ResourceInstance` for the
same process or thread lifetime.

This is necessary for the contract’s own resume promise, not a claim that all
providers can currently observe host-thread incarnation. Unobserved boundaries
can remain unresolved.

## Reuse boundaries and validator rules

| Concern | Reusable canonical source | Required rule / counterexample |
| --- | --- | --- |
| Operation and ordered operands | `ProgramGraph.operations`, `Operation.uses`, static block ownership | `OperationOccurrence` identifies one original `OperationID` at one `BlockVisit`; derive its position from the owner block. `UseOccurrence` is keyed by `(OperationOccurrenceID, UseID)` and preserves each ordered use, so `f(x, x)` has two occurrences even when both resolve to one value occurrence. Do not add a second producer or ordered-use table. |
| Value definitions and transfer | `Value.origin`, `OperationResult`, `BlockArgument`, CFG successor arguments, `CompletionResult`, `ResumeInput` | A `ValueOccurrence` must resolve through that static origin at the exact activation/visit/segment. A block argument’s incoming actual comes only from the real predecessor edge and exact successor index. Same static `ValueID` on two visits is not one dynamic occurrence. |
| State accesses | `Operation.accesses`, each original `StateAccess` and `LocationID` | `AccessOccurrence` points to `(OperationOccurrenceID, static access index)`. Its before/after values are the dynamic values for that access. Do not create another state chain. Core `StateVersionValue` identifies a graph value/location; v2 `ValueVersionID` is a separate logical value-version identity. Equal IDs, shape, or payload do not join them. |
| Literals | Existing `LiteralOrigin` on `DataValue`/`ReferenceValue` | A literal occurrence is scoped to its activation/definition. Equal literal spelling is not Python object identity; a literal reference does not acquire an `ObjectID` merely because its payload repeats. |
| Created but unentered body | `ResumableBody`/body declaration and actual `RegionActivation` | Creating a generator/coroutine/request does not create a body activation. Only an observed entry may create one. A not-yet-entered body must not be represented as a zero-visit activation or a resource producer. |
| Resource definitions/use | `ResourceDefinition`, `ResourceRequirement`, `ResourceUse`, `ResourceLocation` | Static `CreatedResource(OperationID)` is a possible origin declaration, not proof that each execution freshly created a resource. `ResourceUse.requirement` is not an instance; runtime binding names an exact operation occurrence or activation entry. Repeated execution of one static create may yield distinct instances. |
| Allocation/materialization | Existing `StorageAllocationID`, `StorageRegion`, `MaterializationID` | One allocation lifetime remains one allocation identity. `AllocationPlacement(allocation, pool/device instance)` is a relation, not a second `ResourceInstance` for the allocation. A materialization is not a logical content version and its `ready_event` string is not a work generation. |
| Event correspondence | Existing v2 `CorrespondenceRecord`, EvidenceGraph claims, `CallRecordAnchor`/`InvocationKey` | Keep correspondence as explicit many-to-many scoped links with both typed endpoints, evidence, and unresolved/ambiguous status. One profiler/native event may map to several static/dynamic occurrences; one occurrence may have multiple observations. Timestamp proximity, filename, invocation number, or matching string IDs does not establish the link. |

The current v2 tools are useful evidence inputs but are not the new occurrence
model. `OperationInstance` contains old definition/process/thread IDs and
metadata; parentage is containment, not happens-before. `Materialization`
contains `ValueVersionID`, storage region, producer instance, and legacy
`ready_event`/scope strings. `CorrespondenceRecord` connects only legacy
definition↔instance, source↔instance, or slot↔value-version pairs. The older
`ExecutionGraph` is an event list plus entities; its `Event` timestamps and
metadata do not provide activation, state-version, or host-thread-incarnation
identity. These records can be linked as evidence under an explicit scope, but
must not be cast to core IDs or treated as complete occurrences.

## Additional field precision before implementation

The draft uses names such as `identity_realm`, `identity_evidence`,
`constraint_obligations`, `binding_site`, and `Unresolved(reason, scope,
original_fact)`. Freeze these as typed unions/references, not unconstrained
strings or arbitrary metadata. In particular:

- A resource `identity_realm` must distinguish a typed process incarnation,
  run namespace, and externally evidenced realm. It must never be the provider
  window/clock, since those delimit observation, not identity lifetime.
- A `ResourceOrigin.CreatedAt` occurrence must point to a canonical
  `OperationOccurrence`; its “fresh instance” assertion remains a separate
  evidence/identity claim.
- Unresolved/ambiguous correspondence retains the original provider fact and
  its evidence scope. It must not be a null endpoint that can later be
  interpreted as a successful join.
- Resource target unions must preserve role/kind. A memory allocation remains
  an `StorageAllocationID`; a process or host thread, if admitted as a target,
  uses its execution identity type; these are not interchangeable merely
  because both carry a resource label.

These are type/validation requirements. They do not require a new static
ProgramGraph schema or make source/runtime reconstruction a precondition for
having the structural execution interfaces.

## Frozen evidence / hashes

Worktree HEAD: `309fb359be8665fc90979f270a6d4e4d20c6eb85`.

| File | SHA-256 |
| --- | --- |
| `docs/M1_RESOURCE_EXECUTION_CONTRACT.md` (draft) | `247a09628b279a34ce6ccc904ef788e97a656c7924d8cd49f314e3a6d833ec2c` |
| `docs/M1_RESOURCE_EXECUTION_PLAN.md` (draft) | `9f7647b905a9ed8ace399cb16570c49e0ea5abe40360581905145f0b1cbcad37` |
| `scar/ir/program/codec.py` | `415cd3c7832e00c5ffb9ae7332802514944c98b672136a0d010c640d0c9acec0` |
| `scar/ir/program/model.py` | `3a72c7692afdb19f74f19df5990527140e360748954c64dde3e335551580b2b1` |
| `scar/ir/program/providers.py` | `fb96fe41a8c5f6cf33a01fd6974830b9dd73ee622107b3659411cc0c4f8d1343` |
| `scar/ir/program/resources.py` | `167f0b2e1267278362341e6622e5cb164292e93484da94c8403b382e1e6e434f` |
| `scar/analysis/call_edges.py` | `e62a19fcfac138cc5560a51fa71387a942d17d2394a6f8113a0fe907dc753a36` |
| `scar/ir/v2/evidence.py` | `dba2dffc93e0f7dba0f5a0196c1f802e909644106c9380426fdf1472dc3a61c5` |
| `scar/ir/v2/values.py` | `2c4ab8a69d46ef312f454c487329150cd7f3f4a12819e51bf8a8ae218210f259` |
| `scar/ir/v2/ids.py` | `d11e038a6a4c7de6dee5c8050182a97ddb4a6a6a399c466836ca64d6d9cb0a23` |
| `scar/ir/v2/common.py` | `691a7ec169c81cb51e271731ea11ee4c2aed38b5553b1f48f072a8ff368979b9` |
| `scar/ir/v2/schemas.py` | `4c54102f84f342c0f51f32bf3632494cecbd5b65131ad0783ba4d2fa798f2025` |
| `scar/ir/v2/correspondence.py` | `7882dfa21e7877f41dc441f40875433d6b340f4fdb657df547ca57fc34953de5` |
| `scar/ir/record_codec.py` | `2facc7de22eadf2c095181a6f258ecbb7a529079d5c92b6414bbb0a0968ec6c4` |

No test or workload result is claimed by this review.
