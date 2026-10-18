# Proposed: R2.3-V validity and visibility gate

Status: design proposal only. This does not add records, validate a ready result, or close R2.3. Read-only review at `c84fbfe53d76da2ea6ebaf7cec01b59b502eac17`; no tests or workloads were run.

## Existing pieces and hard limit

The current model already has the canonical facts V should join:

- D: `ContentRead` and `ValueDenotation` refer to an original `UseRef`/`AccessRef`, exact `OccurrencePoint`, state support, scoped `VersionRef`/`MaterializationRef`, selector, and a source basis. `ObservationRoot` supplies an explicit Q requirement. A `HostConsumer`, `ResourceConsumer`, or `ObservationConsumer` distinguishes consumer kinds.
- Work: `WorkSubmission`, `ResourceOutcome`, `WorkQuiescence`, `WorkRetention`, `WorkStart`, and `WorkEnd` keep submission, host completion, partial effects, quiescence, retention, and release separate.
- Order: queue prefixes, exact `EventRecord` generations, `QueueWait`, queue profiles, and `order_path(WorkEnd, WorkStart)` derive a bounded conditional path. The path’s protocol-applicability and capture gaps are part of its result.
- P: `WriteAssociation` maps a scoped source stage to an existing host/work writer, original effect/value, and placement; `OutcomeProduction` selects a work outcome/frontier and actual selector. `production()` independently enumerates source candidates and refuses caller-supplied contribution lists.
- G: geometry compares exact scoped `RegionRef`s and computes byte coverage. It does not establish content, lifetime, or visibility.
- Resource lifecycle: exact `ResourceInstance`/`ResourceTarget`, ownership/handle facts, access state, allocation placement, and end/release points can identify some lifetime invalidators.

The blocking limit is still P’s `production_capture_unverified`: the enumerated manifests account for supplied files, not all writes, aliases, drops, external effects, or time windows. Therefore V may report conditional support for known source-derived candidates, but cannot return unconditional ready while the relevant source universe is open. `COMPLETE`, `FactSource`, or an arbitrary “ready” row must not close that gap.

## Minimal V relationship

Do not store a second producer graph or a caller-authored `required_contributions` tuple. For each exact `ContentReadID` / `ObservationRootID`, validation derives:

1. **Demand** from D: exact content identity, scoped placement and required selector, current-state support at the anchor, consumer kind, and actual read interval. Resource consumers use the ticket named by `WholeWorkRead`/`NativeWorkRead`; direct host or external observations do not get synthetic work tickets.
2. **Candidate universe** from all source rows and relevant EEG edges in the exact inventories for the consumer run/window, including unresolved or unvisited sources. Candidate identity remains `InventorySourceRef + SourceEdgeRef` or `InventorySourceRef + RawRecordRef(line, SHA)`; native ports retain their P1 boundary and entry/output occurrence/position. Enumerate before consulting `WriteAssociation` or `OutcomeProduction` rows, so deleting those rows cannot shrink the universe.
3. **Contribution view** by exact joins from each candidate to P rows: source stage/evidence, writer, original effect/value, placement, outcome/frontier, and actual selector. Keep the candidate even when a join is missing. Classify it as a possible current production contribution, lineage-only prerequisite, possible invalidator, or unresolved; these are derived query results, not trusted input labels.
4. **Per-demand coverage units** from the required selector and each exact contribution’s actual selector. A contribution with only a prefix/partial selector covers only that intersection. If several disjoint writes jointly cover a demand, partition or otherwise represent the demanded byte set so every required portion is supported. Do not let an alternative for one contribution cover another contribution’s obligation.
5. **Visibility alternatives** joined to that exact contribution, selector portion, content version, consumer, and domain. The validator checks alternatives independently and combines them only within that same tuple.

The static association record, if persisted for query efficiency, should have only foreign references: `read`, the derived source candidate key, optional exact `write`/`produced` IDs, exact selector/materialization references, and one or more typed visibility-evidence references. It must not contain a `satisfied: bool`, a freely supplied contribution universe, or a status that can override replay. The authoritative result is recomputed from original D/P/work/order/resource records and scoped artifact snapshots.

A minimal record sketch (names not frozen) is one `ContributionSupport(read, candidate, write, produced, visibility, source)` association. `candidate` is a scoped `SourceEdgeRef`/`RawRecordRef` or exact `NativeOutputRef`; unresolved joins remain explicit. `write` and `produced` point to existing P rows rather than copying their effects/frontiers. `visibility` is a strict union:

- `HostVisibility(start, end, protocol)` using the existing point types, from which exact host scope is derived;
- `QueueVisibility(producer_ticket, event_record, queue_wait, consumer_ticket, protocol)` naming exact existing order rows; the order path is derived and must reach the consumer start;
- `EndpointVisibility(root_or_observation, target, selector, protocol)` naming the exact endpoint observation/flush condition;
- `Unresolved(reason)`.

For a known `OutcomeProduction`, its `actual` selector supplies the produced geometry; a row cannot widen it. If one output covers several demand units, matching is recomputed per unit. The row’s `source` is provenance for the association, not evidence that its visibility union variant occurred.

For every derived required contribution/coverage unit `c`, require:

```text
AND(c in source-derived required units:
    OR(exact completed-and-visible support for c,
       exact ordered-before-consumer-start support for c,
       an explicitly parsed endpoint/protocol support for c))
```

The visibility option must match the same demand, scoped version/materialization, selector portion, consumer, and domain. `A completed OR B ordered` is valid when both concern the same contribution; support for A cannot discharge B. A lineage prerequisite is not automatically a current contribution. A possible invalidator must be excluded by exact disjointness or ordered/version evidence, not relabeled irrelevant.

## Typed visibility options

Keep the visibility domain a closed union; unresolved is a first-class outcome.

- **Host:** exact process/address-space/thread scope and interval. Reuse `HostThreadInstanceID`, occurrence points, state support, and checked interval order. An anchor’s `current(state)` value is point evidence only. Proving stability across a multi-point read also needs a closed enough writer/alias universe and no overlapping invalidator in the interval. Equal endpoint state versions do not rule out a write followed by a restore.
- **Queue:** exact producer ticket, queue/resource incarnation, event-record generation and wait selection, and exact consumer ticket/start. Reuse the existing order graph and accept only a conditional path that reaches the consumer’s `WorkStart`; a path ending at `WorkEnd(consumer)` is too late to prove the input was visible before execution. Queue evidence does not authorize a host or other-queue read. An event record’s value/generation and wait’s selected `UseRef` must remain the exact pair; “latest event” or same queue name is not enough.
- **Endpoint:** exact `ResourceTarget`, selector, source/observation endpoint, and protocol condition such as read, flush, or persistence. Do not promote a queue or host result to endpoint visibility. An unparsed protocol reference remains conditional/unresolved.
- **Unresolved:** missing source, ambiguous bridge, unsupported protocol, or budget truncation. None of these is false independence or successful visibility.

Order paths and source facts are still conditional declarations. `ProviderFactReference` identifies a protocol claim; it does not prove that the runtime used that protocol or that the provider honored it.

## Outcomes, partial writes, and invalidators

- Join `OutcomeProduction` to the exact `WriteAssociation` and exact `ResourceOutcome.ticket`. A state production’s `frontier` selects the original effect at that exact index; a value production has no state frontier. The actual selector is the only region eligible for coverage.
- `COMPLETED` does not enlarge the actual selector to the requested region. `FAILED` and `CANCELLED` retain whatever exact produced prefix is justified; those bytes may be considered only if their visibility is independently supported. A known failure cannot be turned into success by an order path. No outcome means pending/unresolved, not failed and not complete.
- `WorkQuiescence` is separate from output visibility. Quiescence supports end/release reasoning; it does not say what bytes were written or whether another consumer can observe them. Retention protects a borrow lifetime, not content stability.
- Enumerate invalidators from the same independent source universe plus exact core/resource accesses: `OVERWRITES`, alias/storage relations, native/raw effects, writes through another handle, and allocation/resource retirement. Check exact scoped target and geometry. Unknown alias, write, source gap, or unsupported selector remains a possible invalidator. A new `ResourceInstance` or `MaterializationRef` is a new incarnation even if URI, shape, or bare ID looks the same.
- Exclude an earlier write only when exact version/selector semantics establish that a later write supersedes its whole relevant portion, or exact geometry proves disjointness. Historical lineage writers are not all current AND contributions; possible overlapping historical writers cannot be silently dropped without a version/kill basis.

## Concrete integration issue to resolve first

`production_validation._effect` can resolve an `InvokeBoundaryStateEffect` for a `HostWrite` without a `WorkSubmission`, but `content_validation` currently rejects `ContentRead.effect=InvokeBoundaryStateEffect` unless it is in `ctx.work_effects`; public `ExecutionIndex.canonical_effect()` has the same work-membership requirement. This prevents a host-side INVOKE read from being represented unless a fake work ticket is added.

Proposed narrow fix for the future V implementation: share one pure canonical-effect resolver that checks the original INVOKE, exact `invoke_arguments` state input, actual transfer, and exact `CompletionResult`/landing formal. Let a host content read resolve that core effect with no ticket. When the content consumer is actual resource work, separately require the effect to belong to that exact submission. In either case, the effect only establishes state transport; it does not prove a native read or footprint. Do not manufacture a ticket to satisfy the current membership check.

## Closure matrix for the next gate

| Scenario | Expected outcome |
| --- | --- |
| Two required contributions A and B; A has completed-visible support, B has exact event/wait path to consumer start | Conditional support only if both joins, selectors, source completeness, and domain match. Removing B’s P association leaves B’s candidate pending and prevents ready. |
| Same physical raw stage has several EEG relations; same ticket has two distinct raw stages | Coalesce only evidence for an exact same physical stage/production/placement. Distinct stages remain distinct candidates even under one ticket. |
| One request asks 8 bytes; outcome records an exact 4-byte prefix with `FAILED`, `CANCELLED`, or short `COMPLETED` | Only the 4-byte selector can be supported. The other 4 bytes remain missing; status does not expand the selector. |
| Host state at read interval endpoints is equal but an overlapping write occurs between them | Not stable. With a complete source universe, the exact write is an invalidator unless ordered/version-killed; with open source coverage, unresolved. |
| Producer event record is generation r1, consumer waits on r2; or wait is on another queue/resource incarnation | Reject a known generation/target contradiction; unknown mapping is unresolved. Never substitute a later event or queue name. |
| Queue path reaches only consumer `WorkEnd`, not `WorkStart` | Does not establish input visibility before consumption. |
| Endpoint output has only a host or queue signal and no endpoint read/flush/persistence condition | Endpoint visibility unresolved. |
| Allocation/handle ends or an aliasing overwrite occurs before/in the read interval | Invalidate the candidate support unless exact lifetime, selector, and order evidence establishes otherwise. |
| Inventory has dropped/opaque/unsupported windows, absent raw PID scope, missing bytes, or traversal truncation | Keep enumerated candidates, add explicit gaps, and do not report empty or complete writer set. |
| `ContentRead` is a host INVOKE with a valid core boundary state effect but no resource work | Resolve original invocation/state ports without a fake `WorkSubmission`; still retain native-read/footprint gap. |
| A row contains a `FactRef`, `COMPLETE`, quiescence, or arbitrary “ready” boolean but lacks exact output/selector/visibility relation | No support is granted by the label. |

## Scope boundary

This proposal does not implement V or prove a complete source universe. It depends on later closure of D (read identity, interval, consumer) and P (source-to-writer/effect/selector correspondence and capture completeness). It adds no core producer/use/state, does not normalize all Python/native protocols, and does not infer purity, freshness, or a runtime equality from shapes or IDs. Until those joins are established, the valid result is a conditional candidate report with explicit gaps, not unconditional ready.

## Reviewed source fingerprints

| Input | SHA256 |
| --- | --- |
| `docs/M1_RESOURCE_READY_CONTRACT.md` | `b222e95fc46773f2b681fc2f44f8f9461fdaa094b567b1401635c79046a6866f` |
| `scar/ir/execution/content.py` | `1eee1822056e59a0be9f4f3a1524f97948df91497ad57072c7c0ca53c670cf9e` |
| `scar/ir/execution/content_validation.py` | `bd163c92244a06dae9e5756882124cab350ffeec09bbe22e3137278712f5b298` |
| `scar/ir/execution/production.py` | `cd829f5c62533f5ab38c2d8b44b9c1b251358b526c41061d83fb6a135c5fa098` |
| `scar/ir/execution/production_validation.py` | `c824c947a3ecf745b95096cdd6b69a529c2563ed02f6b951e261783ce4bb8c1e` |
| `scar/ir/execution/production_query.py` | `3d3d2ab7798edbf9b284552587dc7b154fd676e8df39645a913d1c6864256eab` |
| `scar/ir/execution/work.py` | `c092b7b39691fce22d8cc00d8922cce5df4800c6ece615d28492edbd3fc6bd70` |
| `scar/ir/execution/work_validation.py` | `7494f8e16a3cf8d6b91224e1f75f3c4fa7f14c1a43a361fbc5818948baf7852b` |
| `scar/ir/execution/order.py` | `e4ce65c33bb8169e643eb5bebd8bf5f3620d8d2cc5c8d333b62b52e2e4aea43a` |
| `scar/ir/execution/order_validation.py` | `e26435e2ddbf71d7276e9ece32875f24983cbbbcb470ec973fa330437e1057ba` |
| `scar/ir/execution/coverage.py` | `43a0f21c7a5e5815f3e4408dcf76ff39eeb96f30f4fc0af655a8ccf0aff3a32b` |
| `scar/ir/execution/resource_validation.py` | `3a8bcd72fc07231360b9c9bdc4b35adc9dbc21b569026bba25712d84639b1c08` |
| `scar/ir/execution/query.py` | `cb14eb5de94a93f11dd2c0bfd076b1cf1bb66d01cdd606b768447f0fa03213b1` |
| `scar/ir/execution/validation.py` | `a59db9e27b4eaa924c1b7973ac995a36cc59c3cfdd63c23d00832447b7d8c0ac` |
| `scar/ir/execution/resources.py` | `657fca489d07fd3e32e5552782e02c6b6b58c8ed061c3c0040313d442a2e3000` |
