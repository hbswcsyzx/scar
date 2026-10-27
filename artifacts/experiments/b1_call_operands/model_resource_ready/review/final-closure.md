# Resource coverage review — final source snapshot

## Conclusion

`PASS_WITH_SCOPE` for the reviewed public materialization-coverage query and geometry helper. This closes only the requested query-level review. It does not close D/P/V or R2.3; G remains a geometry prerequisite.

The updated contract preserves the host/Q case without inventing a WorkTicket: a direct host read can attach to its original occurrence point/protocol interval, and an external observation root has its own point/interval. A WorkTicket is required only when actual resource/native work exists. The query/source revisions also preserve exact artifact validation and the budget boundary described below.

## Verified clarifications

- **Host read and Q observation:** `M1_RESOURCE_READY_CONTRACT.md` §3 now distinguishes an actual resource-work consumer from direct host reads and external observation roots. It does not require a ticket merely to populate a field. For real resource work, it still requires an exact ticket/effect/input mapping and a conservative WorkStart..WorkEnd interval absent a precise last-read point.
- **Catalog shape and a present `None`:** `coverage.py` requires an exact dict with exact-string keys. `_ValueCatalog.graph` distinguishes an absent digest key (unavailable graph gap) from a present key whose value is `None` or another wrong type (rejects with `ValueError`).
- **Snapshot integrity:** Each query uses a fresh local catalog. A supplied graph must validate, serialize to bytes matching the artifact schema/size/SHA, and decode into the detached snapshot used for geometry. Known invalid graph structure or foreign keys are not downgraded to an unknown gap for a visited reference.
- **Unvisited references:** The shared budget covers reference visits and the subsequent geometry walk. If it prevents the public query from visiting the whole materialization tuple, the query remains `UNRESOLVED` with a budget gap. The coverage plan now also states that low-level empty/identity fast paths do not validate remaining offers; those offers are not treated as valid. The public MatRef query resolves its budget-visited materialization list before geometry.
- **Geometry scope:** `region=None` remains unresolved placement, and geometry does not establish logical-version equality, content production, readiness, or transformation authority. D/P/V remain required follow-on gates.

## Bound source snapshot

Read-only review in worktree HEAD `2d6f1d44d81e36a3f0638d79a60d4f4c1c4312fc`. The earlier `design/contract-production-closure.md` and `review/query-closure.md` remain unchanged as historical snapshots; this note records the final source/doc hashes below. No tests or workloads were run for this follow-up.

| File | SHA256 |
|---|---|
| `docs/M1_RESOURCE_READY_CONTRACT.md` | `b222e95fc46773f2b681fc2f44f8f9461fdaa094b567b1401635c79046a6866f` |
| `docs/M1_RESOURCE_COVERAGE_PLAN.md` | `ce09b76000644522f21b90c697c644897de1fc75631aaf8dc85f4b41f8917704` |
| `scar/ir/execution/query.py` | `1dd206368dba9a2ef9d3e3ed5bc15fce266ef3dd139d58874ab681c69dae892d` |
| `scar/ir/execution/coverage.py` | `e674cc01a0115f3d71a245a3878438969bdfa74953dff87a99cd89d63575687f` |
