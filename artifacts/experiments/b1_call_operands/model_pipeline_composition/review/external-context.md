# P3 external-context and shared-query review

## Scope

Read-only review at `31bf2e4ef8d3cd6df5c0387d5c27f571b5643d41` (clean worktree). I reviewed `refresh_external_context` and `_external_stages`, the shared P/V entry points, their external snapshot layer, the canonical effect/call foundations, and the existing refresh/budget tests. I did not run tests or a workload; this is a source review. The reported 16 P3 focused passes and 45 legacy passes are parent-provided results, not rerun here.

## Findings

**No blocking issue found in the reviewed refresh and normal public-query paths.** The initial `_analyze` constructs canonical coordinate/flow state, validates call links, then stores `_canonical_gaps` before running external stages (`validation.py:463-492`). Refresh reuses those canonical maps and call views; it does not rerun `_coordinates`, `derive_flow`, or `call_errors`. That is consistent with the unchanged frozen model/program and is reflected by `external_preparation.canonical_flow_reused=True` (`validation.py:428-460`). Call activation caches are retained as recursively copied derived containers; they do not depend on caller-supplied external graph catalogs (`call_validation.py:273-398`). The shared canonical effect resolver is used by work, content, production, order, and validity validation (`effects.py:38-193` and corresponding callers), keeping original `AccessRef`/INVOKE ports and actual transfer/result/formal relationships in one resolver while leaving caller-specific policies local.

Refresh starts from a shallow context copy, drops all external-stage caches, recursively copies the internal dict/list/set/tuple containers, retains the caller catalogs as live inputs, and constructs a new `ExternalSnapshots` instance (`validation.py:414-460`). The dropped cache set covers source resolutions/bridges, order steps, content/denotation resolutions, writes/results, and validity support/lifetime views. `_external_stages` rebuilds them in the declared order: source inventory, resource, work, order, evidence bindings, observation, content, source bridge, write, produced, and validity (11 stages; `validation.py:371-405`). It stops at the first issue; refresh then raises rather than returning a partly prepared context. If no issue occurs, `stage_calls` records all 11. Canonical gaps are the refresh baseline; external gaps are regenerated, and neither refreshed diagnostics nor maps are written back to the construction context.

`ExternalSnapshots` rechecks exact catalog shape, graph family, graph validation, canonical bytes, schema, digest, and byte length. It decodes a detached graph and caches it only within that snapshot object (`snapshot.py:31-181`). Each refresh gets a new snapshot cache, so a changed or newly supplied caller catalog is observed on the next query; a missing graph cached as absent in the construction context does not stay absent after refresh. Source inventory replay and shared-bundle inclusion are also rebuilt locally by each external-stage pass (`source_validation.py:19-41`). These checks establish supplied-snapshot consistency only; they do not establish source/runtime identity or complete capture.

The ordinary composite path has one budget owner. `ExecutionIndex.resource_composition` constructs one `ValidityBudget` and passes it through Q joins, per-read V/P, route projection, and lifecycle projection (`composition_query.py:172-200`, `query.py:67-76`). `validity_shared` sends that same object into `production_shared`, records before/after usage and cost deltas, then charges its remaining traversals directly (`validity_query.py:160-180` onward; `production_query.py:56-75,474-488`). The composer performs one final detach. The legacy single-read `production` and `validity` wrappers intentionally create per-call budgets and detach their results; they are not used by the shared composite path (`production_query.py:491-495`, `validity_query.py:303-305`). Existing focused tests cover shared-budget exhaustion across reads, no-budget-left behavior, shared P→V accounting, one refresh replay across shared reads, and context non-mutation (`test_execution_composition_budget.py`, `test_execution_composition_refresh.py`; not rerun in this review).

One bounded internal-API caveat: `production_shared` and `validity_shared` accept `isinstance(budget, ValidityBudget)` rather than an exact instance (`production_query.py:480-481`, `validity_query.py:162-163`), and the shared adapter calls the passed object’s `spend` method (`production_query.py:56-75`). A Python subclass could override that method and make reported deltas unreliable. This is source-inferred and was not probed. It is not a bypass through the normal public entry points: `ExecutionIndex.resource_composition` and `ExecutionIndex.validity` construct a fresh exact `ValidityBudget` from an exact positive integer, and the legacy wrappers do likewise. Per the root’s scope decision, I record this as an internal trusted-caller constraint, not as a P3 or public-budget blocker.

## Limits

This review does not establish completeness of the external inventories, native effects, runtime identity, readiness, or transformation authority. Preparation/replay work is explicitly reported separately from the derived traversal budget and detached copying (`validation.py:401-405`; production budget scope at `production_query.py:469-470`). Concurrent mutation of caller catalogs during a single refresh is not covered by the reviewed tests or this source review; the refresh provides a fresh per-query snapshot, not an atomic multi-catalog transaction.

## Source hashes

| File | SHA-256 |
|---|---|
| `scar/ir/execution/validation.py` | `94dbd22027c328fa2a33b678f5a555f16c176f61c0d1f18bab80776a7260c930` |
| `scar/ir/execution/snapshot.py` | `7757c299a965e37f5e73eeaa1f4ed304da6b7bfb970cded5d274fdc4e8483107` |
| `scar/ir/execution/production_query.py` | `dd275a767d8da5f54f5abf5e67126ed6c471ba10a25ec9d00f22a773df7a1737` |
| `scar/ir/execution/validity_query.py` | `fbf10cb04c44f0e3562b7b746b846ca2c77d09905689f9ab1adb13f43f012780` |
| `scar/ir/execution/validity_budget.py` | `e1b297345fc1a63716da5d8d7f2434b4999e3200ad3b6ee4f3823c5d99244b10` |
| `scar/ir/execution/composition_query.py` | `ed631511a56893d419edf76c8ddbf15862761c7e851227db772348471587aa6c` |
| `scar/ir/execution/effects.py` | `fd3d756ea382af33916ae6076b17e71a7bc3bc59a45db30c2b7974b573534e6d` |
| `scar/ir/execution/call_validation.py` | `79febd82eea06447ad045e8302a62a17164bb04771c9a2ef852b28640a127f4b` |
| `scar/ir/execution/source_validation.py` | `34f1f929dec9f55ae74913ff19ec23820e262433ed59340bf5b70c79fd91b1e2` |
| `scar/ir/execution/production_validation.py` | `6eda717b717581c91b9301fcb6995e199ae98fb2f618066f79dfe509819da256` |
| `scar/ir/execution/content_validation.py` | `92afdb38caf716c4187c4a2a9173207c8dc2cc6110a3fd3d83f22852b67ed49a` |
| `scar/ir/execution/order_validation.py` | `cbea6d0b1072c0cf7a3579e07a13a3a9bad808b807c779e66ac76acf43f6ea09` |
| `scar/ir/execution/validity_validation.py` | `b347ece5df59c8a6aeeb0e7421a533f1decb1c21eacd6cbaf755c3254c6a161e` |
| `tests/unit/test_execution_composition_refresh.py` | `205a4d49e9c2544842ab2a0d0ca12e61a1a575658bd883b0591ed7d3d59e8c80` |
| `tests/unit/test_execution_composition_budget.py` | `619d717ca4ae43f9c8fee818eb2d017a192adfe8770e09677c5c0db4f8390be9` |
