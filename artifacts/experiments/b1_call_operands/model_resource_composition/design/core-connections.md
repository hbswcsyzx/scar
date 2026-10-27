# R3 execution composition: read-only core connection audit

**Scope.** Read-only review of the current model and the general R3 composition contract. No product, test, or documentation source was changed; no tests, LeWM run, GPU work, or capture was run. Reviewed worktree: `/tmp/scar-structured-model-280qf4mi`, HEAD `348d18277b963bc183fb420bf173f05594d667d8`.

## Conclusion

The execution records can represent a generic load → materialize → submit → consume → write composition without another producer, Use, or state graph. Their validators already connect many of the individual ports and preserve unresolved physical/source joins. The current worktree does not yet provide a single end-to-end composition fixture or public aggregate query, and the records do not prove runtime correspondence. Those are R3 composition tasks, not evidence that the constituent typed interfaces are absent.

Two concrete join obligations need explicit handling. First, `WorkSubmission.materializations` needs one exact meaning and cross-checks against materialization-bearing reads, writes, and retentions when its coverage says `COMPLETE`. Second, cross-function dynamic ports need a caller-to-callee activation association. Static `ProgramIndex` routes and per-activation `ExecutionIndex.formal_route` cannot choose the correct child activation among repeated calls. The latter is a real R3.1 connection gap; it must remain unresolved until an explicit occurrence association exists.

## Existing composition path

| Stage | Existing records and validation | Queryable view and limit |
|---|---|---|
| Observation obligation | `ObservationRequirement` binds a semantic contract to a required output slot or endpoint facet. `ObservationRoot` binds that obligation to an output value, bound endpoint, or explicit external endpoint, with an interval, anchor, and state support. `observation_errors` checks the root against the original Q contract and selected actual. | `ExecutionIndex.observation_root(id)` returns the requirement, contract, and selected actual. It does not verify a runtime return value or endpoint persistence. |
| Read/input | `ContentRead` identifies an original `UseRef` or `AccessRef`, a `ResourceConsumer`/`HostConsumer`/`ObservationConsumer`, a `StorageContent`/`EndpointContent` placement, support, and a scoped denotation basis. `content_errors` checks the original Use/Access, current state at the anchor, selected ValueGraph materialization/version/region, and the associated ticket or observation root. | `content_read(id)`, `denotation(value_occurrence)`, `resource_access(id)`, `state_at(point)`, and `canonical_effect(effect)` expose original ports and gaps. A state/reference occurrence is not thereby proven equal to current materialized bytes; interval stability remains a gap. |
| Submission/order | `WorkSubmission` associates a ticket with its origin, executor, queue prefix or direct thread, effects, materializations, dependencies, and retentions. `EventRecord`/`QueueWait`/`QueuePrefix` produce conditional queue-order edges from exact generations and prefixes. `work_errors` and `order_errors` check ticket/effect/queue ownership and cycles. | `work(id)`, `queue_prefix(id)`, `order_path(source, target)`, and `work_order(producer, consumer)` expose declared associations. `work_order` is specifically `WorkEnd → WorkStart`; it is not host synchronization or proof of content visibility. |
| Consume | `ResourceConsumer` links the read to a ticket and whole-work or native interval. The read keeps its own subject, materialization, selector, anchor, and support. | The read query returns both conservative work interval and a declared native interval, if present. The native interval does not replace the ticket boundary or prove the native operation consumed the selected materialization. |
| Write/output | `WriteAssociation` links a `WorkWrite`, `HostWrite`, external establishment, or unresolved writer to an original value/state production and a placement. `ResourceOutcome` plus `OutcomeProduction` selects an actual effect frontier and selector; `production_ranges` checks the selected physical range/placement. `validity` derives source candidates and per-contribution support rather than accepting a caller-supplied smaller writer set. | `write(id)`, `outcome_production(id)`, `production(id)`, `validity(read_id)`, and `materialization_coverage(required, offered)` are available. They are source-derived/conditional views, not native or runtime truth. |
| Retain/release | `WorkRetention` ties a ticket to a target and an original Use/Access/resource access/materialization basis, with start, support, and optional quiescence-backed release. Outcome, quiescence, and release are distinct. | `work(id)` returns retentions and quiescences separately. A terminal outcome or ready result does not release a borrow. |
| Endpoint finish | Q endpoint facets and `EndpointContent` can describe an endpoint/materialization relationship while preserving an unresolved selector or parser boundary. | There is no general protocol parser here proving flush, close, durable persistence, or external visibility. Close, outcome, and endpoint establishment must remain distinct. |

The public dynamic index accepts `ExecutionIndex(model, program, *, value_graphs=None, evidence_graphs=None, semantic_graphs=None, artifact_bytes=None)`. Content-facing query methods rebuild and validate a fresh external snapshot for each call. A composite report should either use immutable graph snapshots for all calls or be a read-only aggregate over one fresh context; separate calls against mutable catalogs can observe different snapshots. No persisted aggregate record is needed for that view.

## `WorkSubmission.materializations` and its three joins

The current field is `tuple[MaterializationRef, ...]` plus `materializations_coverage`. The composition plan defines the exhaustive set as this ticket's declared content reads, content production, and borrow whose `WorkRetention.target` is a `MaterializationRef`; `COMPLETE` must include those exact scoped materializations. The list itself does not distinguish read from write, so it cannot identify a producer. A materialization used only as a basis for retaining an allocation does not by itself say the ticket borrows that logical materialization.

Under that exhaustive-set interpretation, the same exact `(artifact, MaterializationID)` must be reconciled at three existing relation points:

1. A `ContentRead` with `ResourceConsumer(WholeWorkRead(ticket) | NativeWorkRead(ticket), ...)` and `StorageContent(mat, selector)` says the ticket consumed/read from `mat`.
2. A `WriteAssociation` with `WorkWrite(ticket)` and `StorageContent(mat, selector)` says the ticket is associated with a write to `mat`.
3. A `WorkRetention` owned by the ticket may name a `MaterializationRef` as its target; that exact materialization must be in the work set under `COMPLETE`. A `MaterializationRef` used only as the basis for an `AllocationTarget` is not membership evidence. The retention validator separately checks target/basis consistency and any checked ValueGraph materialization-to-allocation relation; matching names are insufficient.

At the reviewed snapshot, these are validated separately. `work_validation.py` validates listed refs and reports incomplete coverage, then validates retention ownership/basis. `content_validation.py` validates the read placement and consumer ticket/effect. `production_validation.py` validates a write placement, writer ticket, and effect frontier. None checks that a materialization-bearing read, write, or retention target is present in that ticket's materializations tuple when `materializations_coverage is COMPLETE`. Nor should this list be used to claim producer identity: `WriteAssociation`/`OutcomeProduction` are the separate writer/effect/frontier records.

I did not find an existing fixture that claims complete materialization coverage while contradicting one of these associations. The inspected end-to-end candidates (`execution_visibility_graphs.visibility_execution`, `execution_content_graphs.content_connection_fixture`, `execution_order_graphs.event_order_execution`, and `execution_work_graphs.ordinary_work_execution`) use `UNKNOWN` materialization coverage; the work-only fixture that has a materialization reference uses it in a retention example but still does not claim complete coverage. This means the specific malformed-complete-set case is not currently covered; it does not establish that a contradictory model is accepted by an existing test.

R3 acceptance should state the exhaustive-set interpretation and add one valid fixture plus three focused mutations: remove a consumed mat, remove a written mat, and remove a retained `MaterializationRef` target while coverage remains `COMPLETE`; require rejection. A `MaterializationRef` used only as an allocation-retention basis should not fail this membership check. The corresponding `PARTIAL`/`UNKNOWN` cases must remain gaps rather than being treated as proof of no other materializations. Compare exact artifact identity and original materialization ID, not URI aliases.

## Cross-function ports: substantive R3.1 gap

`ProgramIndex` is a static index over one `ProgramGraph`. `environment_call(operation_id)` derives declared arguments from the operation's original `call_arguments`/`invoke_arguments` and the callee's entry formals/environment layout; `entry_arguments(region_id)`, `function_entry_layout(region_id)`, `exit_port_uses(exit_port)`, and `body_outcomes(region_id, start=None)` expose the static side. The result is explicitly a declared binding and does not identify a runtime callee object or choose a dynamic activation.

`ExecutionIndex.formal_route(value_occurrence)` follows one actual CFG transfer into a block argument and returns its original `source_use`. It follows the same activation's CFG; it does not connect a caller's actual to the formal occurrence in a separate callee activation. `ExecutionModel` records operation/value occurrences and region activations, but at this snapshot there is no typed `caller OperationOccurrence → child RegionActivation` association. Therefore two calls to the same callee cannot be disambiguated by these APIs alone, and neither equal `DataIdentity`/`ObjectID`, names, nor shared denotation may be used as a substitute.

This is a real connection gap if R3 is expected to expose the complete call chain. The minimum generic bridge is one per-call association from the original caller occurrence to the exact callee activation, exact initial entry visit, and actual caller completion occurrence (or explicit unresolved boundary). Derive each input/output route by joining that association to the original static call arguments, environment/formal layout, actual entry block arguments, actual callee return/raise uses, and the caller's real return or `INVOKE` transfer. Do not store duplicate argument/producer/state tables. Until present and validated, nested input/output matching is a gap, not a mismatch or a proof. The R3.1 plan now names this exact missing relation and preserves ordinary recursion by allowing different activations.

## R3 acceptance surface and boundaries

A single generic composition fixture should start from a Q output requirement, create a read root and `ContentRead` selecting one exact scoped materialization/region, submit one queued work ticket with the canonical original effects/materializations, wait on an exact event generation/prefix, consume through a second `ContentRead`, then create a write and actual outcome frontier for only the produced region. It should attach one Q output root to that same logical output or endpoint. Queries should return the original Use/Access, StateVersion, ValueGraph Materialization/Region, ticket, queue path, outcome frontier, write, and Q requirement. They should retain `source_runtime_verified=False`, `native_*_verified=False`, `endpoint_*_verified=False`, and `transformation_authorized=False` wherever the corresponding proof is absent.

Required counterexamples: wrong materialization/version or allocation; a missing ticket↔materialization association under `COMPLETE`; a stale event generation or wrong consuming queue; a partial write mistaken for a whole output; an outcome/result copied from another ticket; a wait used as proof for a host read; a completed ticket with no quiescence used to release retention; close treated as durable endpoint persistence; absent Q root incorrectly shrinking output obligations; and a caller/callee route inferred from matching values when two dynamic child activations exist. The malformed-work-set fixtures described above are currently absent from the reviewed fixture set.

This is a finite composition/reconciliation task, not a requirement to parse every native API or build a second compiler. Source replay, runtime occurrence capture, exact native-port correspondence, endpoint flush/persist protocol interpretation, and transformation authority remain separate and false unless separately established. Manual composition records do not become automatic source recovery.

## Reviewed source hashes

| File | SHA-256 |
|---|---|
| `scar/ir/program/queries.py` | `584fc4b40c83d3618b42f84c71c06d750e264465195f62676bc542e29f0d3ad1` |
| `scar/ir/execution/query.py` | `b2bb3bfd92f2dd1ee6d71cc9a8b0bdebad519cfa43065244b1d2e1621739deec` |
| `scar/ir/execution/validation.py` | `41baacad27c685901fd0aa2d2607b95d2211d76a3af1da66af6aa32b4231a1fc` |
| `scar/ir/execution/work_validation.py` | `290d8fe51c9cc091bddae107b7428bce4ef181949954c3a8751a5fd6d3adb765` |
| `scar/ir/execution/content_validation.py` | `1f308c4e27ff02f751d1129eaeacfda23e0716974d248ab7934546da5e19a1ba` |
| `scar/ir/execution/production_validation.py` | `4610410f2d367d99a6abdc355ee55b628184a78ea48882b10bd6ae4bacbaa734` |
| `scar/ir/execution/observation_validation.py` | `eaae52e54664107ac7baa7aa5707fbf2a19be6e9b59346f0ce37040f563ff983` |
| `scar/ir/execution/validity_query.py` | `de6313dc979859a7c92d79a67e36b49c6f29d6bb0ce4bc34a1bbfef52d6113b9` |
| `scar/ir/execution/coverage.py` | `53da83b9cb3b67ae63a12163d74e58cf9d9d6d76511e2d4011a6918d43c59411` |
| `tests/fixtures/execution_visibility_graphs.py` | `478eb976dc8aef267bce1d5fbd50beacb6cdeef6797d7c6c417c0cc21895a5fe` |
| `tests/fixtures/execution_content_graphs.py` | `cd1959d54ad7993b837fc51206cb78fbf3b4beb18778532e4060a00b14d707a3` |
| `tests/fixtures/execution_order_graphs.py` | `d4e21e8c63ebdb279bafae66ce14b5f78b917f05d3d1e37e3c56b94a2a203e2a` |
| `tests/fixtures/execution_work_graphs.py` | `7428d0bd7a1597232d49587d5378cce3b4fae077a306d51d474e8d46e6aec60f` |

This review did not execute any test; no pass count is asserted.
