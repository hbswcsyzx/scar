# Scoped source bridges and production-universe query (proposed)

Review baseline: clean tree `5ab22f8d8fcbabbc59d494b571651d480468f3d5`. This is a design proposal, not an implemented interface or a source/runtime proof. No tests or workload were run.

## What the current records establish

`ValueDenotation` and `ContentRead` already provide the right consumer-facing anchors. `VersionRef`, `ObjectRef`, `MaterializationRef`, and `RegionRef` carry `ProviderArtifact` scope; selectors and effects point back to existing execution records. The denotation basis can identify an EEG edge/observation or an exact native port. `content_validation.resolve_basis` can check those references against supplied graphs and preserve gaps. It does not create an occurrence, producer, write, or closed-world inventory.

The remaining join is between the exact endpoint in the evidence artifact and the exact value-graph endpoint. EEG edges name typed but artifact-local IDs; `ValueObservation.version` and `.materialization` are also local to that EEG graph. A matching bare ID, URI, shape, dtype, or representation is not a cross-artifact identity. The current data records have no proof that an EEG `MATERIALIZES` endpoint is a particular `MaterializationRef`, or that an EEG version endpoint is a particular `VersionRef`.

A second join is needed from source-side write evidence to an existing work/effect. `WorkEvidenceBinding` maps an evidence operation instance to a work ticket, but the correspondence is partial and can be many-to-many. It does not identify which original `AccessRef` or `InvokeBoundaryStateEffect`, selector, completion frontier, or write phase realizes a particular source edge. It must not be treated as complete merely because a row exists.

Finally, an immutable artifact hash proves which bytes were read, not that every write in a run or window was captured. An absent source edge cannot establish an empty writer set without a separately validated inventory boundary.

## Minimal bridge records to consider

Keep the current D records as the context and do not create another producer/value/use/state graph. Add only scoped joins that point back to exact existing records:

```text
EvidenceEndpointRef(
    artifact: ProviderArtifact,
    edge: str,
    side: EvidenceEndpointSide,  # SOURCE or TARGET
)
ObservationFieldRef(
    observation: EvidenceObservationRef,
    field: ObservationField,     # VERSION or MATERIALIZATION
)
ValueGraphEndpointRef = VersionRef | MaterializationRef | ObjectRef | AllocationRef | RegionRef

EndpointBridge(
    context: DenotationID | ContentReadID,
    source_endpoint: EvidenceEndpointRef | ObservationFieldRef
                    | NativeInputRef | NativeOutputRef,
    target: ValueGraphEndpointRef | Unresolved,
    source: FactSource,
)
```

`AllocationRef` should scope the existing allocation ID to its `ProviderArtifact`; it must not be a new allocation identity. Validate that the source endpoint exists in the exact evidence/native graph, the target exists in the exact supplied `ValueGraph`, and the endpoint kinds are compatible. For native ports, validate the exact boundary, initial entry or return/raise occurrence, and native slot index. A port match is a declared cross-representation association, not runtime identity proof.

Permit multiple bridge rows for one source endpoint/context. Derive `UNIQUE`, `AMBIGUOUS`, or `UNRESOLVED` from the distinct valid scoped targets; never select one by raw ID coincidence or by whichever graph happens to be loaded. D's existing `VersionRef`/materialization/selector constrains candidate compatibility but must not silently manufacture a bridge. A valid bridge remains a declared association whose runtime correspondence needs later evidence.

For writer linkage, add a narrow mapping to existing effects rather than new producer nodes:

```text
SourceEffectBinding(
    source_endpoint: EvidenceEndpointRef,
    instance: ScopedOperationInstanceRef,
    ticket: WorkTicketID | Unresolved,
    effect: AccessRef | InvokeBoundaryStateEffect | Unresolved,
    selector: RegionRef | EndpointSelector | Unresolved,
    phase: WritePhase | Unresolved,
    source: FactSource,
)
```

`ScopedOperationInstanceRef` must include the exact EEG artifact and operation-instance ID. Validate `ticket` against `WorkEvidenceBinding`, `effect` against `WorkSubmission.effects`, and selector/frontier against the actual existing effect and outcome. This map can be partial and many-to-many. An unmapped source write remains an unaccounted candidate; it cannot disappear from the universe.

A separate inventory-scope record is needed before any closed-world claim. It should bind the exact source artifacts and their validated run/process/window/segment boundary, covered relation families, and capture status such as truncation, gaps, or dropped events. The provider artifact hash alone is insufficient. Keep this record thin: it describes what the source inventory covers and does not copy EEG edges or core effects.

## Read-only query shape

The query should take an exact `ContentReadID` plus the validated source inventory and bridge rows. It should derive its candidate set by enumerating the complete relevant typed relations from every in-scope evidence artifact. Do not accept a caller-supplied `required_writers` tuple that could shrink the universe.

Return three independent views:

1. **Lineage** — scoped `VersionRef` ancestry and `ProvenanceRelation` path from the supplied `ValueGraph`. This explains logical derivation, not physical production.
2. **Current production candidates** — exact materialization/version bridge, selector/region, matched source relation, operation instance, mapped ticket/effect, and observed outcome/frontier. This reports candidates and unresolved joins; it is not “ready”.
3. **Possible invalidators** — all in-scope `OBSERVED_WRITE`, `OVERWRITES`, and relevant alias/storage-overlap candidates that could affect the selected content after production and before the read. Exclude a candidate only with exact selector/version and ordering/kill evidence; unknown overlap or order stays a conflict/gap.

The result should also expose `unmatched_source_facts`, `closure_gaps`, and per-contribution support. Support is OR across valid alternatives for one exact contribution; all required contributions are ANDed. Failed/cancelled work and partial frontiers retain their actual writes and state effects. Do not infer rollback or success from `Completion` status alone.

A `PRODUCES` edge or `ValueObservation.role` is not by itself a physical writer. A normalizer may report a view or a logical output. `MATERIALIZES` and `Materialization.producer` are useful candidate links, but still need exact scope, selector, work/effect mapping, and inventory coverage. `ALIASES` and `USES_STORAGE` help find possible invalidators; they are not writes on their own. Keep those classes separate in the result.

## Candidate universe and safe deduplication

Enumerate, at minimum, all relevant `OBSERVED_WRITE`, `OVERWRITES`, `MATERIALIZES`, `PRODUCES`, `ALIASES`, and `USES_STORAGE` edges plus their endpoint observations/materializations in every scoped source artifact. Classify each as a possible production, lineage relation, alias/overlap candidate, or unresolved relation. Do not flatten every logical ancestor or every historical alias writer into a required AND set: those relations describe different possibilities and may refer to earlier versions or unrelated selectors.

Deduplicate multiple source rows as one physical write only when they map to the same exact canonical write identity: scoped run/process and operation instance, exact `WorkTicketID` when applicable, exact `AccessRef` or `InvokeBoundaryStateEffect`, exact selector, completion frontier, and write phase/generation. Multiple evidence edges that point to that one effect are multiple evidence links for one contribution. Do not deduplicate by bare operation instance, ticket, materialization, output version, URI, or shape.

A single ticket can contain distinct effects or phases. Those remain distinct contributions unless their exact canonical effect identity is the same. If the mapping is missing, retain both candidates or an ambiguity gap; do not erase a possible writer by assuming one ticket means one write.

If an in-scope graph is incomplete, has unknown aliases, missing bridge rows, or capture truncation, report an open writer universe. Deleting a work/effect binding must leave the corresponding source candidate unmatched. Deleting both the binding and a caller-provided required-list entry must still not yield an empty complete universe, because the query derives candidates from the independent source inventory.

## Existing machinery and limits

- `ValueGraph.ancestors` and `ProvenanceRecord` support lineage only; `VIEW`, `COPY`, `TRANSFORM`, `MUTATE`, and `MATERIALIZE` are not interchangeable physical-write evidence.
- `content_validation.resolve_basis` already checks typed EEG edge/observation references and known contradictions. Extend its result with the scoped bridge state rather than weakening its gaps.
- `WorkSubmission.effects`, `ResourceOutcome` frontiers, `EventRecord`, `QueueWait`, and `QueueOrderProfile` provide canonical effects and partial ordering. They do not establish source inventory completeness.
- `storage_coverage` provides geometry over exact `RegionRef`s. It does not prove version identity, write occurrence, lifetime, or readiness.
- `SLOT_VERSION` correspondence can support source-slot lineage, but it lacks materialization/selector and exact work/effect linkage.

The scope of this proposal is a source-endpoint bridge and a non-authoritative production-universe query. Full capture completeness, source-to-runtime correspondence, selector soundness for an unknown native operation, and final readiness remain separate gates.

## Reuse path: capture manifest and normalized source bundle

There is a useful offline reuse path before adding per-edge bridge rows. `normalize_v2` creates one `IRBundle` from a raw trace, and `IRBundle.validate()` cross-checks its EEG observations against that bundle's ValueGraph: observation versions must exist, observation materializations must exist, and a materialization's `value_version` must equal the observation's version. The normalizer creates the observation, version, materialization, and edge from the same raw record/snapshot token. Therefore a strict, same-bundle projection can derive an internal endpoint bridge without asking a caller to repeat it.

A small derived index can expose that mapping:

```text
NormalizationIndex(
    raw: RawRecordRef,                 # exact raw artifact + line + row SHA
    bundle: ProviderArtifact,           # exact normalized IRBundle artifact
    coverage_record: CoverageRecordRef, # exact normalizer coverage row
    recipe: NormalizerRecipeRef,
)
```

The index should be regenerated or strict-validated from the raw bytes and exact bundle/coverage snapshots. Its per-row mapping comes from the normalizer's `coverage.records[*].normalized` IDs, then resolves those IDs through the bundle's typed records. The independent `CaptureManifest` owns the set of raw artifacts/rows, run/process/window scope, covered event families, and capture gaps/drops. A query takes an `InventoryBindingID` that names this manifest/index scope plus the D-side `ContentReadID`; it derives every candidate edge from the listed bundle(s). It must not take a caller-supplied required-writer tuple.

This makes deletion of a `WorkEvidenceBinding`, `SourceEffectBinding`, or other association detectable: the raw/index and normalized EEG candidate remain, so it becomes an unmatched source fact. Deleting the association cannot shrink the source universe. It does not make a missing raw event detectable by itself: the manifest must bind the actual capture's counters, drop/truncation status, and relation-family coverage. Normalizer accounting says how raw rows were projected, not whether the collector observed every physical write.

Keep the cross-bundle boundary explicit. For the **same** normalized bundle, derive its own EEG endpoint to its own ValueGraph endpoint from validated typed IDs. If D's `VersionRef`/`MaterializationRef` points to a different ValueGraph artifact, require an explicit `SourceEndpointBridge`/`InventoryBinding` association. Do not join source and D graphs by matching the normalizer's synthetic IDs, legacy version strings, object IDs, storage IDs, URI, shape, or dtype. Preserve all valid external candidates and return ambiguity when several bridge targets remain.

The normalizer's semantics are a further limit. It labels each captured input snapshot with `OBSERVED_READ` but the edge is inferred with the assumption “captured argument; actual read not proven.” It labels output snapshots `PRODUCES`; this describes a normalized output observation, not necessarily a physical write. Its ValueGraph identities are explicitly provisional per snapshot (`equivalence=UNKNOWN`); the old `object_id` is retained as a hint with unresolved lifetime, and snapshot storage geometry is marked `snapshot_only`. Thus the derived internal bridge establishes where one normalized bundle placed the same captured snapshot record. It does not prove cross-snapshot identity, actual read/write semantics, selector completeness, or current physical production.

This reuse is sufficient to avoid hand-writing bridges for every endpoint inside one validated normalized bundle and to derive the source-candidate universe from independently bound inventory artifacts. Keep explicit bridges for D-to-source equivalence, native-port correspondence, exact ticket/effect/selector pairing, and capture completeness. Do not treat `NormalizationIndex` or its recipe as authority beyond that deterministic projection.

Additional reviewed source hashes: `scar/trace/normalize_v2.py` `7733fb9b02a8f657d2413a982a3203ee2d3dee7d532400118ca7b1902538b2a5`; `scar/ir/v2/schemas.py` `4c54102f84f342c0f51f32bf3632494cecbd5b65131ad0783ba4d2fa798f2025`; `scar/ir/v2/codec.py` `511daa3a5d1ee89ae7f7c545dd5f7161ea3a3a6c9f3c1b4224c0ba751fcc1`.
