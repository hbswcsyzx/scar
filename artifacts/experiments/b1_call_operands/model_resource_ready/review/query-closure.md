# Materialization coverage query review

## Verdict

`PASS_WITH_SCOPE` for the requested `ExecutionIndex.materialization_coverage` + shared geometry path. No correctness blocker found in this source snapshot. This query reports selector geometry only; it does not prove content equality, production, lifetime, visibility, readiness, or transformation authority.

## Checks

- **MatRef to selector:** the query resolves each exact `MaterializationRef` against its artifact-scoped detached `ValueGraph` snapshot. It uses that row's existing `region` to create a `RegionRef`; it does not synthesize storage coordinates. A `region=None` materialization remains `unmapped` with a placement gap. If it is required, the query stays `UNRESOLVED`; if offered, it cannot fill known holes or make an `INCOMPLETE` comparison look complete.
- **Missing offers:** a missing graph or `region=None` offer is retained as a gap. The query downgrades an otherwise `INCOMPLETE` geometry result to `UNRESOLVED`, because an unmapped offer might cover the missing bytes. A known exact subset may still establish selector coverage; the result retains the missing offer and gap. This says nothing about content or readiness.
- **Version and authority boundary:** geometry compares byte selectors within a scoped allocation coordinate. It does not join different logical versions into content equality. Both the geometry result and the public query keep runtime/source and transformation authority false.
- **Budget:** the query charges its reference visits, then passes only the remaining budget to the shared geometry walk and adds the geometry consumption back. Failure to visit all references or finish geometry returns `UNRESOLVED` with a budget gap. External snapshot serialization/hash validation is a separate cost, as documented in `coverage.py`.
- **Artifact validation and isolation:** each query constructs a local `_ValueCatalog`; it does not trust the execution context's mutable external graph cache. For each supplied artifact, the resolver checks graph validation and canonical bytes against schema, size, and SHA, then strictly decodes those checked bytes into the local snapshot used by geometry. The query resolves all budget-visited materialization references before invoking geometry, so a missing graph cannot mask a malformed later visited graph or foreign key. A malformed supplied graph or absent materialization row raises `ValueError`; an artifact not visited because the shared reference budget was exhausted leaves an explicit unresolved result.

The low-level exported `storage_coverage` helper can short-circuit once an empty required selector or exact offered-region identity proves geometric coverage; its module documentation explicitly says unvisited offers are not catalog-verified. That behavior does not affect the reviewed public materialization query, which resolves its whole visited `MaterializationRef` list first. The two APIs should retain this documented distinction.

## Source snapshot

Read-only review at worktree HEAD `2d6f1d44d81e36a3f0638d79a60d4f4c1c4312fc`. No tests or workloads were run and no product code was changed.

| File | SHA256 |
|---|---|
| `scar/ir/execution/query.py` | `1dd206368dba9a2ef9d3e3ed5bc15fce266ef3dd139d58874ab681c69dae892d` |
| `scar/ir/execution/coverage.py` | `f818c78087d2855162868aaaf81420fdfe89038a2ddba6e7f2773744e58b55d5` |
