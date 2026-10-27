# R3.2 Q denominator and scope review

**Status:** read-only design review; no product or test files changed, no tests run.

**Read base:** `/tmp/scar-structured-model-280qf4mi`, HEAD
`f0dbbd478095b07a684fe4d35ba3b53be20ed17c`; `git status --short` was empty.

## Conclusion

The current `ExecutionModel.observation_requirements` tuple is a denominator only for rows that are already present. It cannot detect a deleted requirement row. The current validator also does not report an existing requirement with no root. A query must receive or derive an active contract scope independently, then build an obligation ledger from that scope and the exact contract snapshot. It must keep every existing requirement, root, read, and operation visible even when those rows do not match the supplied scope.

Do not activate every `SemanticGraph.contracts` entry. A catalog is a collection of available definitions; it does not say which contracts apply to the run or call under review. A query-only scope is the smallest R3.2 interface that supplies this missing denominator without adding an execution-model table or duplicating the core graph. It is a caller declaration of analysis scope, not evidence that the contract matched runtime behavior.

## What exists

- `ContractRef` is artifact-scoped (`ProviderArtifact` plus `ContractID`). `ObservationRequirement` has one such contract, one `RequiredOutput` or `RequiredEndpoint`, a protocol reference, and a source. `ObservationRoot` names a requirement plus an actual value/endpoint, interval, state anchor, support, and source. These are frozen explicit associations, not source/runtime proof. See `observations.py:19-106`.
- `ContractDefinition.required_outputs` is a finite, exact tuple of `ValueSlotID`s. `facets` is a finite tuple of `(facet, required, ...)`; it states facet kinds but has no target endpoint or endpoint cardinality. `OperationDefinition.contract` and `OperationDefinition.resource_requirements` are static declarations. See `contracts.py:50-75`, `contracts.py:102-119`, `semantic.py:100-140`.
- Validation resolves the exact semantic artifact named by each existing requirement, checks that its contract/output slot/facet exists, and checks roots against extant requirements, current state, run, interval and known binding. It emits correspondence gaps rather than claiming protocol/runtime truth. See `observation_validation.py:88-190`.
- The current execution model has requirement/root tables but no active-contract-scope or completeness field. Roots have an anchor; requirements have no run, operation, activation, or endpoint owner. See `model.py:61-103`, `observations.py:49-105`.
- Source inventory can recover exact semantic artifacts from a captured bundle. `EnvironmentInterface.code_definition` ties a core region to a declared `OperationDefinitionID`; dynamic `CallActivation` ties a caller to a region activation. This is a candidate route for deriving contract scopes, but environment documentation explicitly says the static code declaration does not verify the runtime function binding. Missing/ambiguous source-to-code correspondence must remain a gap. See `environments.py:79-119`, `calls.py:15-40`, `inventory.py:55-83`.

## Concrete denominator holes

1. `observation_errors` iterates only `ctx.observation_requirements` and `ctx.observation_roots`. It does not derive expected requirements from an active scope or check `requirement -> at least one root`. If both rows disappear, there is no Q diagnostic.
2. The existing test `test_facet_label_alone_creates_no_observation_root` removes both tables and expects no issues or roots (`test_execution_observations.py:187-191`). This is correct for an inactive/unspecified analysis scope, but proves that the graph alone cannot report an omitted active obligation.
3. A required output slot can be enumerated from the exact contract, but a `RequiredOutput` row can be deleted with no remaining key. Even when it exists, `OutputValue` contains only a `ValueOccurrenceID`; validation explicitly leaves exact slot-to-value correspondence unverified (`observation_validation.py:96-100, 151-154`).
4. A required facet does not identify a core endpoint or say how many endpoints that facet covers. `RequiredEndpoint` rows enumerate declared targets only. Counting those rows as the expected set lets deletion shrink the set; expanding a facet to every `ProgramGraph.resource_requirement` would also be unjustified without an exact contract/operation/requirement bridge.
5. A root alone cannot assign an orphan requirement to one of multiple runs or activations: the requirement has no owner, while run/activation can only be read from root points. If the same contract is active twice in one run, current rows do not establish whether the contract is run-level or per-activation.

## Minimum query-only scope

Use an immutable query input with exact typed fields:

```text
CompositionScope(
    contract: ContractRef,
    owner: RunID | RegionActivationID | OperationOccurrenceID,
    source: FactSource,
)
```

`owner` is mandatory and selects the intended granularity. A run scope means one run-level contract obligation set. An activation or operation scope means a distinct obligation set for that dynamic owner. Do not silently collapse two calls to the same static contract. Echo every scope in the returned report. `FactSource` records where the scope declaration came from; it does not prove that the contract was active at runtime.

A query such as `resource_composition(scopes: tuple[CompositionScope, ...], budget=...)` should return a detached report containing:

- the exact requested scopes and `scope_status` (`COMPLETE_FOR_REQUESTED_SCOPES`, `PARTIAL`, or `UNRESOLVED`); it must never mean all contracts in the run unless a separate exhaustive scope source establishes that;
- an obligation ledger keyed by `(exact ContractRef, owner, obligation kind, target)`;
- all model `observation_requirements`, `observation_roots`, and `content_reads`, including unmatched/unscoped rows;
- for each obligation, matched requirement rows, matching roots, downstream reads, and explicit gaps;
- every existing `ContentRead`, even when it is outside the requested Q scopes;
- `source_runtime_verified=False` and `transformation_authorized=False`.

An empty scope list means “no Q scope requested,” not “the program has no Q obligations.” Without an explicit scope, the query may report scopes suggested by existing rows, but it must return `scope_status=UNRESOLVED`/incomplete. An unavailable exact semantic snapshot leaves that scope unresolved; it must not turn into an empty contract or empty obligation set. A wrong supplied artifact remains an issue.

### Ledger derivation and matching

1. Resolve each exact `ContractRef.artifact` through the normal `ExternalSnapshots` path and look up only its exact `ContractID`. Never enumerate unrelated catalog contracts.
2. Emit one output-slot obligation for each `required_outputs` member. This recovers a missing entire `RequiredOutput` row.
3. Emit one required-facet obligation for each facet with `required is True`. Until there is an exact endpoint bridge and a declared cardinality rule, label it `UNINTERPRETED_FACET_TARGET`; a present endpoint row is a candidate association, not proof that all targets were enumerated. Preserve the facet obligation when every `RequiredEndpoint` row is deleted.
4. Match existing requirements by exact artifact-scoped `ContractRef` and exact target key. `RequiredOutput` keys use the exact slot. `RequiredEndpoint` keys include exact facet and exact `ResourceRequirementID` (or explicit unresolved endpoint). Same `ContractID` under another artifact never matches.
5. Match roots through their existing requirement ID and exact owner-compatible anchor/interval/actual. A present requirement with zero matching roots produces `ROOT_MISSING`; a root from another known run/activation does not satisfy this scope. If a needed point, actual transfer, or cross-activation mapping is unavailable, report `SCOPE_CORRESPONDENCE_UNRESOLVED` rather than forcing a match or declaring it out of scope.
6. A root fulfills the structural “root supplied” link only. It does not itself prove a content read, source protocol, output-slot denotation, endpoint visibility, readiness, or successful materialization. Do not require a physical `ContentRead` for every `OutputValue`: an output may be a scalar literal or a reference identity with no declared content protocol. If no typed content requirement/source evidence classifies the root, retain its value/port dependency and report `CONTENT_PROTOCOL_UNCLASSIFIED`/`NOT_DECLARED`; do not invent a work ticket, materialization, or physical read. If typed content evidence does imply a read and its `ContentRead` was removed, preserve the expected read-to-root join as missing. Continue to query every existing `ContentRead` independently of Q-scope matching.
7. Keep all unrelated extant rows in the result as `UNSCOPED` or `AMBIGUOUS`; do not filter them away. If one requirement could match several same-contract scopes and its roots do not disambiguate them, preserve that ambiguity and a gap.

For an operation-owned scope, an exact root anchor on that operation or an actual output/binding whose existing origin/owner is that operation can establish structural compatibility. If these routes disagree or are absent, keep the scope join unresolved. For an activation-owned scope, require points to resolve to that activation; a cross-activation actual remains a correspondence gap. For a run-owned scope, compare known anchor/interval runs and never use a root from another run.

## Scope derivation boundary

A source-derived candidate may be assembled from the active `RegionActivation`, its `RegionID`, the region's `EnvironmentInterface.code_definition`, the run's exact source inventory, and the matching semantic `OperationDefinition.contract`. This is useful for proposing scopes, but each link is currently a declared/static relation. In particular, `EnvironmentInterface` does not establish which runtime function object executed, and `ProviderFactReference` is not proof of that identity. Missing inventory, multiple matching definitions/contracts, an unsupported body, or unmatched source identity must produce an unresolved candidate. The query-only `CompositionScope` remains the explicit denominator when a caller has selected the contract for review.

The query scope does not certify that the caller supplied every active contract. It closes deletion of requirement/root rows **within the requested scope**. A claim covering all active Q contracts in an execution still needs a complete, validated scope inventory or a sound source-derived exhaustive traversal; do not label a partial request globally complete.

## Finite acceptance cases

- Active run/activation/operation scope + exact semantic snapshot + every required output row and matching root: ledger lists each obligation; scope is complete for that request but correspondence/readiness gaps remain as appropriate.
- Remove a required-output requirement row while retaining the scope: output-slot obligation remains and reports `REQUIREMENT_MISSING`.
- Retain requirement but remove all roots: report `ROOT_MISSING`; do not pass by treating an empty root list as an empty conjunction.
- Remove requirement, roots, and the read together: active scope still reconstructs expected obligations and reports missing rows.
- Supply an unrelated contract with required outputs/facets in the semantic artifact but omit it from scopes: it creates no active obligation.
- Same `ContractID` under different artifact hashes: no cross-artifact match.
- Same contract in two runs: a root from run A cannot satisfy run B. Same contract with two activation scopes in one run: do not merge them.
- Required facet with no exact endpoint derivation: retain an uninterpreted-facet obligation/gap. Do not infer target count from the existing `RequiredEndpoint` rows.
- Output root with no typed content expectation: retain the root and its original value/port route; do not demand a physical read. If typed content evidence exists but the read row is removed, report the missing read association rather than silently dropping that content obligation.
- Missing/ambiguous inventory-to-definition link: return unresolved scope; do not infer “no contract.”
- Exhausted query budget: return a stable partial ledger/cursor and `TRUNCATED`; do not return the unvisited suffix as empty/satisfied.

## Scope of this review

This review establishes the Q denominator/API gap only. It does not close endpoint protocol parsing, dynamic function identity, output-slot-to-`ValueOccurrence` mapping, complete active-contract discovery, readiness, native read/flush behavior, or the complete R3 pipeline.

## Source fingerprints

| File | SHA-256 |
| --- | --- |
| `docs/M1_RESOURCE_COMPOSITION_PLAN.md` | `467d92987aafbfa686ce3116f9bbd0e0e6aca437d31c924d420b50cbfe12110f` |
| `scar/ir/execution/observations.py` | `8c8237c855680e78f6e1c256a30086105636c2af5ad6fb59958385840ed7d882` |
| `scar/ir/execution/observation_validation.py` | `eaae52e54664107ac7baa7aa5707fbf2a19be6e9b59346f0ce37040f563ff983` |
| `scar/ir/execution/model.py` | `14a28d9531b744924e24ba1633b691cdb91019e37829665e5f711369c7f2a126` |
| `scar/ir/execution/validation.py` | `e3a440dc32c4aacba3b4a53b536d11341c0892a4bb5dda08007448bc5dba395d` |
| `scar/ir/execution/query.py` | `94b098d75a0568cf48240ff7078f8d4a99b9353c5abd73ccbef804c28803400a` |
| `scar/ir/execution/calls.py` | `a287446babd077c072f51182d12ecc5e670bd2e1700b6396e914e134d95a183f` |
| `scar/ir/execution/inventory.py` | `99ed4011ebd379cff8f9b8731b5fd5c2cf9611ff7865d1241dc83dfe67a9afb5` |
| `scar/ir/program/environments.py` | `14e9c16d89db388793236a3636adaac0557c410a5c633c65f7558d413db029f8` |
| `scar/ir/v2/contracts.py` | `c7aaae3ea0e292e425cfbe820d4508363b9e26e0c94427cefc5a4bb0ae6e15b1` |
| `scar/ir/v2/semantic.py` | `9d0af8a2b4a868df00388ccb910cdabdc93066aad7ff0e593d1c8d0e969885ab` |
| `scar/ir/v2/schemas.py` | `4c54102f84f342c0f51f32bf3632494cecbd5b65131ad0783ba4d2fa798f2025` |
| `tests/fixtures/execution_observation_graphs.py` | `fef4e061a5af321f1173b34366df908495ed2505345994f19169e9baeaa419d9` |
| `tests/unit/test_execution_observations.py` | `e89e400a81ad680270632224755310781a204fe169df36b7357c903e2f4acbc8` |
