# Lifecycle public query / CLI cross-review

**Result: PASS_WITH_SCOPE.** Read-only review against D2.3 baseline HEAD
`fdf9d0d37ab043db297f095bfafa685b32b0b058`. The baseline had no lifecycle-scope
query/CLI additions. The current diff is confined to `scar/ir/program/queries.py`
and `scar/cli.py`; the two named tests are new worktree files. No tests or workloads
were run.

## Reviewed file identity

| File | SHA256 |
| --- | --- |
| `scar/ir/program/queries.py` | `584fc4b40c83d3618b42f84c71c06d750e264465195f62676bc542e29f0d3ad1` |
| `scar/cli.py` | `f01c732d085173355c8048f99c9496cb7a2cf2b25e7a7956b96e2b4278fad32d` |
| `tests/unit/test_lifecycle_scope_queries.py` | `b7434157245b788cfbad01ec7e6ac1da4f0c599ed9bd07778029ec63eb735101` |
| `tests/unit/test_lifecycle_scope_cli.py` | `5b11ae56c84b26432b2467b6bd60525b24ced74c508f692a635139872bc49bfb` |

## Findings

- **Original declaration chain is retained.** `ProgramIndex.__init__` runs the existing
  validator once and consumes its private lifecycle-facts output (`queries.py:246-278`).
  Each scope view stores the graph's original `DriverLifecycle` and `DriverInterface`
  objects (`:270-273`); `.rule` returns `interface.rule` itself (`:132-145`). A point
  view stores the original `Operation` (`:458-490`) and, for `EDGE`, resolves
  `.successor` through that operation and the exact index (`:154-183`). Body/session/
  release publications carry that same point and existing records/UseSites
  (`:492-520`). The tests check object identity for declaration, interface, rule
  implementation, operation, successor and source commit, including after deleting the
  index (`test_lifecycle_scope_queries.py:18-38,61-83,99-130`). The implementation fact
  remains a raw `ProviderFactReference`; this query does not resolve or replay its artifact.
- **No authority is added.** A scope exists only for an explicit `DriverLifecycle`; an
  otherwise valid D1-only region returns `None` (`queries.py:383-394`). Applicability is
  fixed to `ProofStatus.UNKNOWN` (`:139-145`). Lifecycle facts are validator-derived
  static CFG summaries (`lifecycle_analysis.py:15-32`), not observations. CLI keeps
  `driver_lifecycle_verified` and `transformation_authorized` false; it reports the
  rule, scope, and `UNKNOWN` applicability as declarations (`cli.py:525-540,640-675`).
  `conditional_lifecycle_facts_derived` is correctly distinct from runtime verification.
- **The actual NORMAL edge is used.** For `NORMAL_COMPLETION`,
  `session_publication` enumerates the operation's real successors, selects the one
  whose kind is `NORMAL`, and passes its actual index into `lifecycle_edge`
  (`queries.py:492-510`). The test reverses successor order and verifies index `1`, the
  identical successor object, and the same publication point (`test_lifecycle_scope_queries.py:99-128`).
- **Unknown and invalid requests are distinct.** An unscoped valid region returns no
  lifecycle point; wrong ID types and missing IDs fail at the query boundary. EDGE
  rejects bool/negative/out-of-signature indices, while BEFORE/AFTER reject an attached
  index (`queries.py:458-490`; `test_lifecycle_scope_queries.py:41-97`). Invalid wire and
  input/output path alias cases return CLI `INVALID` with an empty scope list and no
  derived-facts flag (`test_lifecycle_scope_cli.py:63-76`).
- **CLI schema-version flags match the four exercised capabilities.** The tests serialize
  the D1-only, publication, no-body, and session/release examples and assert versions
  v11/v12/v13/v14 respectively. v11 reports no lifecycle scope/facts; v12/v13 derive
  scoped facts without claiming session-release validation; v14 reports that structure
  only when session/release rows exist. All versions retain false source/runtime/
  transformation claims (`test_lifecycle_scope_cli.py:16-49,51-61`; `cli.py:624-675`).

## Scope note

`LifecycleScope` and `LifecyclePoint` are ordinary frozen view dataclasses, not
unforgeable proof objects. A caller can construct a lookalike view with fabricated facts;
the reviewed APIs do not treat such a directly constructed object as verified authority.
Consumers must use views returned by a `ProgramIndex` built from a validated graph.
Within that boundary, I found no concrete incorrect linkage, version misclassification,
NORMAL-index error, or authority escalation in the reviewed four files. This review did
not inspect or certify the lifecycle fixed-point algorithm beyond its existing validator
handoff, and it provides no runtime/native applicability evidence.
