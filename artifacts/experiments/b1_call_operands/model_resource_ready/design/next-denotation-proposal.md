# Proposed — R2.3-D occurrence denotation and content reads

**Status: Proposed.** This is a bounded field/validation proposal for the next D layer, not an implementation or a frozen interface. It adds no second producer/use/state graph, new capture manifest, backend, or source lowerer.

## 1. Reuse canonical identities

Use the existing execution graph as the only dynamic coordinate system:

| Need | Existing canonical record/query | D-layer rule |
|---|---|---|
| Dynamic SSA value | `ValueOccurrence(id, value, origin)` | Join by exact `ValueOccurrenceID`, then read the ProgramGraph `ValueID` and its typed variant. Do not join by label or static `ValueID` alone. |
| Actual operand | `UseOccurrence(operation, use, value)` / `UseRef(operation, use)` | Resolve the exact `(OperationOccurrenceID, UseID)` pair. A static `Use` is not evidence that its operand was consumed as content. |
| State at a read | `OccurrencePoint` + `ctx.current(point)` | Use the state occurrence currently mapped at that exact point and `LocationID`; no independent state-version table. |
| State effect | `AccessRef(operation,index)` | Resolve the original `StateAccess`; preserve its before, after, mode, reference, and footprint. It does not itself name bytes or a tensor selector. |
| Geometry | `MaterializationRef` and `RegionRef` | Reuse them. Resolve `Materialization.region` to a `RegionRef` in the same artifact; never duplicate shape/stride/allocation in a D record. |
| Logical content | new scoped `ValueVersionRef(artifact, version)` | `ValueVersionID` is a dataclass, not an `Identifier`; recursively validate its exact class, exact `LogicalValueID`, and exact non-bool integer `version >= 0`. |
| Object identity | new scoped `ObjectRef(artifact, object)` | Exact `ProviderArtifact` plus exact `ObjectID`. Never merge equal bare IDs across artifacts. |
| Runtime source | new exact `EvidenceEdgeRef(artifact, edge_id)` and `EvidenceObservationRef(artifact, observation_id)`; a typed native-port reference described below | Resolve the referenced row in the exact parsed source artifact. `ProviderFactReference.locator` alone is not proof of a parseable input/output port. |

`MaterializationRef`, `RegionRef`, `ValueVersionRef`, `ObjectRef`, evidence references, and any provider-port reference must retain the source artifact identity (hash, schema, size, typed ID/locator). A missing artifact yields an explicit unresolved result. A supplied artifact with invalid bytes, schema, typed row, or foreign key is rejected; it must not be downgraded to an ordinary gap.

## 2. Denote only the cross-graph facts that need denotation

Use two small exact record variants, keyed by dynamic occurrence:

```text
DataOccurrenceDenotation(value: ValueOccurrenceID,
                         version: ValueVersionRef,
                         basis: DenotationBasis)
ReferenceOccurrenceDenotation(value: ValueOccurrenceID,
                              object: ObjectRef,
                              basis: DenotationBasis)
```

`DenotationBasis` should be a strict union of `EvidenceEdgeRef`, `EvidenceObservationRef`, a parseable native-port reference, and an explicit missing/unresolved source. Each variant has a source-specific validator; an arbitrary string or a naked `ValueVersionID` is not a basis.

The core already supplies the other denotations, so do not add duplicate rows for them:

- `StateVersionValue` denotes its own canonical `LocationID` and dynamic state occurrence. To claim it currently contains a logical version, a separate read/content association must join that state occurrence to an exact `ValueVersionRef` with source evidence. Do not equate a core state version with a v2 `ValueVersionID`.
- `LocalBindingValue` denotes a binding token/slot. Derive BOUND/UNBOUND/MAYBE from `BindingDefinition`, `BindingRead`, and actual CFG transfers. A BOUND payload is the exact `UseOccurrence` selected by the binding relation; UNBOUND has no payload; UNKNOWN or an unresolved incoming path remains a gap. Do not denotate the token as `None`, a Python object, or its possible payload without that relation.
- `ProtocolValue` denotes its exact `ProtocolValueKind`; it is not data, reference identity, or a state contents version. Only an explicit typed protocol source can relate it to an external protocol record.
- A core `LiteralOrigin` can explain a declared exact builtin literal without a ValueGraph version. It does not manufacture a runtime observation or storage materialization.

`ObjectBinding` is useful as a scoped candidate relation from `ObjectID` to `ValueVersionID`, but not as a universal occurrence mapping or a permanent object-to-content equality. Its `scope` and `evidence` are strings, its table is a list, and multiple bindings are possible. Check its relation and exact artifact membership; preserve ambiguity or an unscoped binding as a gap. The exact runtime/reference evidence must still identify which `ValueOccurrence` denotes the object.

## 3. Minimal content-read association

For each actual resource-content read or observation root, add one `ContentRead`-style relation with these fields:

```text
port: UseRef | AccessRef
operand: ValueOccurrenceID | Unresolved
at: OccurrencePoint | EvidencePoint
content_version: ValueVersionRef | Unresolved
materialization: MaterializationRef | Unresolved
selector_source: exact RegionRef-derived placement | typed external selector | Unresolved
state: ValueOccurrenceID | Unresolved | None
basis: DenotationBasis
consumer: exact WorkTicket/read-port mapping | direct host point | exact observation root | Unresolved
```

This relation is sparse: it represents an asserted content read, not every pass-through `Use`. The query must also retain parse/capture incompleteness for the read inventory; absence of a row must not silently mean “no read.”

Validation rules:

1. A `UseRef` must resolve the exact `UseOccurrence`; `operand` must be that row's exact value. A `Use` can pass a reference without reading its contents, so the source basis must establish the read operation/port.
2. An `AccessRef` must select the exact original `StateAccess`. For a content dereference, use the actual `reference` Use (when present) and `before` state at the read point. `READ_WRITE` additionally has its exact after state; a pure write is not a read. Never translate `Footprint.INTERVAL(0,16)` into 16 bytes without a typed coordinate mapping.
3. For a `ReferenceValue`, `operand` denotes object identity, not content. If `state` is supplied, it must be the exact value for the relevant `LocationID` in `ctx.current(at)`; its activation and edge must be valid. If the current state is absent, unknown, stale, or the reference targets are unknown, preserve a gap. The relation from this state to `content_version` still needs an exact source basis.
4. For a direct `DataValue` read, `content_version` must agree with that occurrence's data denotation. If a materialization is selected, its row must reference the same exact scoped `ValueVersionRef`. Derive the `RegionRef` from that materialization. If the read is a subview/subselector, require an exact typed selector mapping; do not assume the whole materialization or infer byte coordinates from core state footprints.
5. For `InvokeBoundaryStateEffect`, resolve the actual invocation input and actual selected successor/completion formal. Completion results are post-state ports, not input contents. A boundary effect alone proves neither content read nor byte footprint.
6. If an actual resource/native work exists, `consumer` must identify the exact `WorkTicket` and provider input port/effect. Do not assign all same-operation tickets to one read. For direct host reads or external Q roots, use the actual point/root and do not invent a ticket. If an unknown consumer kind or selector could change coverage, return unresolved.

The selector field should normally be derived from the exact `MaterializationRef` using the shared geometry query, rather than stored a second time. If an explicit selector is necessary, it must be a source-backed typed selector and be checked against the materialization's region. `region=None` remains an endpoint-placement gap; it does not become a synthetic allocation or whole-storage selector.

## 4. Parseable source basis

The minimum useful source references are:

- `EvidenceEdgeRef(ProviderArtifact, edge_id)` resolved in the exact `EvidenceGraph.edges` map, with relation and typed endpoints checked;
- `EvidenceObservationRef(ProviderArtifact, observation_id)` resolved in `EvidenceGraph.observations`, checking its exact `version`, optional `materialization`, and optional operation;
- `NativePortRef(ProviderID, RegionID, ProviderElement, ProviderFactReference)` resolved against the exact `ProviderEnvelope`, `ProviderRegion`, and matching `ProviderBinding` plus the schema-specific captured port record.

For EEG, an observation's `role` is a string, not a typed port. An operation-level `OBSERVED_READ` edge plus a `ValueObservation` may still be ambiguous among repeated or same-valued operands. Join a source operation to the core operation only through the exact artifact-scoped `OccurrenceEvidenceBinding`, then join the source operand to the exact core `UseID` through a parsed port/operand relation. `OccurrenceEvidenceBinding` alone is not a use mapping. `CorrespondenceGraph.SLOT_VERSION` is static slot correspondence, not a dynamic `ValueOccurrence` content observation.

For native providers, `ProviderBinding` maps declared provider elements to core IDs; it is not itself a run-time observation. Require a typed external port key/path and parseable artifact row. If the artifact or parser cannot resolve that port, retain `Unresolved`; a `ProviderFactReference` locator by itself cannot fill the mapping.

`ProvenanceRecord.inputs/outputs`, `ValueVersion.parent_versions`, and `Materialization.value_version/region` are useful derivation and physical-placement edges after the scoped artifact has been validated. They do not identify which dynamic use consumed a version or which work produced it. Never match by data type, operation label, `ValueObservation.role`, newest numeric revision, `ObjectID` equality across artifacts, or same-host operation alone.

## 5. Bounded result rules and counterexamples

- Missing source graph, unknown state/current read, ambiguous port, unsupported selector, absent provider mapping, or budget truncation yields a specific `UNRESOLVED`/gap. If a supplied graph is malformed or an exact declared FK is absent, reject it rather than masking it behind another gap.
- Geometry status remains relative byte-set coverage only. It cannot make a denotation, writer inventory, outcome, host/queue/endpoint visibility, or readiness true.
- Use a per-query canonical snapshot cache keyed by the full artifact identity. Revalidate mutable caller graphs on each query, verify canonical bytes/hash/schema/size, and use a strict detached decoder snapshot for joins. Do not persist trust across queries or open artifact URIs implicitly.
- The denotation budget counts port/occurrence/evidence joins and selector work; geometry consumes the remainder of the same query budget. If a read/source is unvisited, report the query unresolved rather than claiming no denotation or a complete read inventory.

Counterexamples that the first D gate should accept/reject explicitly:

1. **Same object, new contents:** a NumPy array and `torch.from_numpy` tensor retain object identity and data pointer while a NumPy write changes bytes and leaves the PyTorch version counter unchanged. Reuse the `ReferenceOccurrenceDenotation`; require the new current state/content evidence for a later read.
2. **Two input occurrences:** `f(x, x)` has two distinct `UseID`s even if both resolve to the same `ValueOccurrenceID`. An operation-level observation cannot be arbitrarily assigned to one input or collapsed into one read.
3. **State is not logical version:** a state read at `BEFORE` must match `ctx.current(point)[location]`. A prior ObjectBinding/ValueVersion does not survive a state update without a new source-backed state-to-content relation.
4. **Footprint is not byte geometry:** an abstract core interval does not prove the corresponding `RegionRef` byte interval or stride holes.
5. **Regionless endpoint:** `Materialization.region=None` must stay unresolved until an exact endpoint selector is supplied; no CPU allocation or whole selector may be fabricated.
6. **Same ID, different artifacts:** identical bare `ValueVersionID`, `MaterializationID`, or `ObjectID` under distinct artifact hashes must not join.
7. **Binding/protocol confusion:** UNBOUND/UNKNOWN local binding cannot be treated as a payload object/version, and a protocol token cannot be interpreted as data content.

## 6. Current implementation boundary

Already present: occurrence/use/access coordinates; canonical state-flow/current lookup; local binding definitions/reads; typed `MaterializationRef` and `RegionRef`; ValueGraph versions, provenance, object bindings, materializations and allocation geometry; EEG edges and value observations; static provider bindings; a per-query artifact validator and storage-geometry coverage query.

Still proposed: cross-namespace dynamic `ValueOccurrence` denotation, exact EEG/provider port-to-Use bridge, content-read selector/source association, and writer/consumer completeness. Existing `ValueGraph`, EEG, provider and static correspondence fields cannot be promoted to these dynamic claims without the explicit joins above.

## Source snapshot

Read-only preparation in worktree HEAD `aa2b9178e7a23ccfd86695b68524bf3817fe1673`. The full gate was running; no tests, scripts, or workloads were run and no product/tests/docs were modified.

| File | SHA256 |
|---|---|
| `docs/WHOLE_PROGRAM_MODEL.md` | `ea4bb6cd1d4976ad7e6d1b7ccd214c5cdeafa0f657623e2363fd110bada9e509` |
| `docs/M1_RESOURCE_READY_CONTRACT.md` | `b222e95fc46773f2b681fc2f44f8f9461fdaa094b567b1401635c79046a6866f` |
| `scar/ir/execution/coordinates.py` | `b19e45c8af710b93d7197ca91e7cbcdfa7a9ee239a7faf73903d2ff85003ce09` |
| `scar/ir/execution/validation.py` | `6c167f7a3594bcc2e6c8872520e1b14f7c453d7f3439028a36343e6b48f2d` |
| `scar/ir/execution/model.py` | `6d592afa5a7b8f9eab774c41f52322da6ad742c405a03e2f8448e06afdd1dd92` |
| `scar/ir/execution/work.py` | `c092b7b39691fce22d8cc00d8922cce5df4800c6ece615d28492edbd3fc6bd70` |
| `scar/ir/execution/query.py` | `1dd206368dba9a2ef9d3e3ed5bc15fce266ef3dd139d58874ab681c69dae892d` |
| `scar/ir/execution/coverage.py` | `e674cc01a0115f3d71a245a3878438969bdfa74953dff87a99cd89d63575687f` |
| `scar/ir/program/model.py` | `3a72c7692afdb19f74f19df5990527140e360748954c64dde3e335551580b2b1` |
| `scar/ir/program/bindings.py` | `8bb4dfaddbeaf0fb70f675da4db60ba655f9b8f4ee56047f0b9a95f0009e3a46` |
| `scar/ir/program/providers.py` | `fb96fe41a8c5f6cf33a01fd6974830b9dd73ee622107b3659411cc0c4f8d1343` |
| `scar/ir/v2/ids.py` | `d11e038a6a4c7de6dee5c8050182a97ddb4a6a6a399c466836ca64d6d9cb0a23` |
| `scar/ir/v2/values.py` | `2c4ab8a69d46ef312f454c487329150cd7f3f4a12819e51bf8a8ae218210f259` |
| `scar/ir/v2/evidence.py` | `dba2dffc93e0f7dba0f5a0196c1f802e909644106c9380426fdf1472dc3a61c5` |
| `scar/ir/v2/correspondence.py` | `7882dfa21e7877f41dc441f40875433d6b340f4fdb657df547ca57fc34953de5` |
