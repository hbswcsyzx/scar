# P production integration cross-review

## Scope and verdict

Read-only review of the frozen production-source inventory, scoped source replay, public query, documentation, and codec-author evidence. No tests or workloads were run for this review. The source tree was at `5ab22f8d8fcbabbc59d494b571651d480468f3d5` and the shared component run reported 477 passing cases across 8 criteria with fingerprint `66e35626809a14cde497346a97d56e94697958d4895bd253f48a1975e9662c10`.

**PASS_WITH_SCOPE.** I found no remaining concrete correctness blocker in the reviewed paths after the fixes below. These interfaces expose source candidates and declared associations. They do not establish capture completeness, runtime identity, native writes, readiness, or transformation authority.

## Frozen inputs reviewed

| File | SHA256 |
| --- | --- |
| `scar/ir/execution/snapshot.py` | `7757c299a965e37f5e73eeaa1f4ed304da6b7bfb970cded5d274fdc4e8483107` |
| `scar/ir/execution/source_validation.py` | `34f1f929dec9f55ae74913ff19ec23820e262433ed59340bf5b70c79fd91b1e2` |
| `scar/ir/execution/production_query.py` | `3d3d2ab7798edbf9b284552587dc7b154fd676e8df39645a913d1c6864256eab` |
| `scar/ir/execution/query.py` | `cb14eb5de94a93f11dd2c0bfd076b1cf1bb66d01cdd606b768447f0fa03213b1` |
| `scar/ir/execution/validation.py` | `a59db9e27b4eaa924c1b7973ac995a36cc59c3cfdd63c23d00832447b7d8c0ac` |
| `scar/ir/execution/inventory.py` | `99ed4011ebd379cff8f9b8731b5fd5c2cf9611ff7865d1241dc83dfe67a9afb5` |
| `docs/M1_PRODUCTION_PLAN.md` | `6d5c2d5d24071532251d415a58b30cf1982ce0d3a690d45c84050e593f13a24f` |
| `docs/M1_RESOURCE_EXECUTION_CONTRACT.md` | `74a606fca89ecb94ad9a04f77d8ad41706bcdacb10210352ccad185272993729` |
| `docs/M1_PRODUCTION_API.md` | `1c5c8125b0af07bd3253ff238e6afa77afcf0f51ffebb263792d73eb12ba600f` |

## Source inventory and scoped identities

- `InventoryResolver` checks exact artifact schema, size, and SHA; parses strict UTF-8/JSON with duplicate-key and non-finite rejection; consumes bounded physical JSONL lines; and replays only the fixed installed normalizer. It does not open artifact URIs or execute a supplied recipe. A truncated or absent source remains pending/gap; a supplied malformed or contradictory artifact is an issue.
- Normalization replay compares the full bundle and coverage. Same `(manifest,index)` pairs reuse one replay within a fresh validation context; distinct inventory bindings retain distinct source identities. Per-resolver parsing budgets and the query's traversal budget are separate. The API now explicitly says there is no aggregate parse budget across distinct inventories.
- Provider process scope is not inferred from an absent or non-integer raw PID. Exact integer disagreement is an issue; absent/string/bool PID under a provider scope yields `inventory_process_scope_unresolved`, without coercion. This preserves string process identifiers as unresolved rather than declaring them malformed or equal to an integer scope.
- `SourceEndpointRef` and `SourceEdgeRef` retain inventory/stream scope. Same-bundle facets derive through the exact replayed EEG and ValueGraph. Cross-artifact bridges compare no bare IDs, retain multiple mappings instead of selecting the first, and remain explicitly unverified associations. Object targets are checked against the exact EvidenceGraph object registry where that is the declared artifact family.
- `ExternalSnapshots.graph` checks the requested graph family against the artifact schema before treating an absent catalog entry as missing. Thus a known artifact of the wrong family is an issue, while a correctly typed artifact whose bytes were not supplied remains a gap.

## Candidate and query behavior

- `production_query._universe` enumerates independent inventory streams, source EEG edges, and raw rows before joining declared write/outcome associations. Removing a Work, WriteAssociation, or OutcomeProduction row therefore cannot erase the underlying source candidate universe. An absent inventory is `production_inventory_missing`, not an empty AND set.
- The source candidate relation set includes `PRODUCES`, `MATERIALIZES`, `OBSERVED_WRITE`, `OVERWRITES`, `ALIASES`, `USES_STORAGE`, and `ESCAPES`. `ESCAPES` is retained as an unresolved/potential source candidate; write validation does not accept it as a write stage/evidence relation. A `PRODUCES` edge records an observed result and adds a condition that it is not a native write. Neither relation alone proves physical mutation or readiness.
- Exact source stage/edge/raw-line references are required for joins. Same-host or same-ticket similarity does not create a join. Multiple endpoint bridges are retained with ambiguity; URI, shape, or cross-artifact numeric ID equality is not treated as identity.
- Lineage parents remain prerequisite evidence, not a flat list of current writers. Spatial overlap can identify possible invalidators, with unresolved geometry/holes staying conservative. `current_production` is a precisely matched declared association view, not a closed writer set or readiness result. `source_runtime_verified`, `readiness_verified`, and `transformation_authorized` remain false.
- Query traversal has one exact-int budget over lineage, source rows/edges, association joins, and selector ranks. Snapshot validation and inventory parsing have their own byte/line/artifact limits. Truncation leaves pending/unresolved sources; it does not claim independence. This is not a single upper bound on total CPU, memory, or parsing across arbitrarily many distinct inventories.
- Each public content query reconstructs external snapshots and revalidates caller-provided catalogs, while returning detached results. A catalog changed after index construction is not trusted from stale cached state.

The query owner's report records `26 passed` in attempt004 (`2.27s`), with the frozen query hash above. This is cited evidence from that report, not a test run performed for this review. The shared component run later reported 477 passing cases and no source fingerprint change.

## Codec author evidence and preserved failures

The v4 compatibility oracle was generated from immutable revision `5ab22f8d8fcbabbc59d494b571651d480468f3d5`, not from the new encoder. Its proof records canonical wire SHA256 `55ed3e05850fbcb30c44c1894feb81062fc8aaba6976b8d4b0048d44da4735af`, size 29,951 bytes. The archive cleanup receipt records the removed source tar SHA256 `a574d8c2b58a98e4aef5b657204acedf1e263535600d89675db8531c2bb437d2` and size 4,382,720 bytes; logs, commands, hashes, golden, and proof remain preserved.

The retained codec attempts show these failures and corrections:

- Attempts 001 and 002 produced the golden, then exited nonzero because the wrapper copied `imported-source-hashes.json` onto the same path. The original outputs are retained; attempt003 finalized the proof and exited 0.
- Attempt004 failed during test collection: `AllocationTarget` was imported from the wrong module. This was an import/setup failure, not a codec assertion.
- Attempt005 had 143 passes and 7 errors, all fixture setup indexing a nonexistent bridge (`IndexError`); it did not establish a product rejection.
- Attempt006 had 146 passes and 4 failures. The new typed `EvidenceEndpoint.reference` variants were rejected by the closed `Identifier` union/tag vocabulary. The encoder's new schema vocabulary was subsequently extended narrowly for the typed endpoint classes while the v1–v4 vocabulary remained closed.
- Attempt008 had 148 passes and 2 fixture/indexing failures after the fixture stopped containing the previously assumed bridge slot.
- Attempt009 passed all 150 focused tests in 3.31s, including the immutable v4 byte oracle, v5 table selection/no-downgrade, legacy tag closure, malformed nested-field rejection, and typed endpoint roundtrips.

The retained archive contains attempts 001–006, 008, and 009; no attempt007 directory was present when reviewed. No missing attempt result is inferred. The cleanup manifest preserves the exact oracle source hash so the deleted duplicate archive can be regenerated from the immutable revision.

## Limits

This review checks source-inventory replay and the connection/query layer only. It does not establish that all runtime writes were captured, that an EEG edge corresponds to a physical write, that a cross-artifact bridge reflects runtime identity, that a producer set is complete, or that a resource is ready/free. Those limits are explicit in the API and output flags and remain necessary until the corresponding source/runtime evidence exists.
