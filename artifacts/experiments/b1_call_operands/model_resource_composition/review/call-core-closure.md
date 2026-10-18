# R3.1 independent call-core closure

2026-10-18. **PASS_WITH_SCOPE: no remaining blocking issue found in this bounded review.**
This closes the source finding preserved in `call-core-review.md`; that OPEN report is
unchanged (SHA256 `42de432fac569718339f4b29cb7929eeb15dfbd83b9f66a66c9a7aa5f63bfed1`).
`connection-preflight.md` also remains unchanged. This closure ran **no** tests/probes and
edited only this ignored report; all implementation/fixture/codec files remain frozen.

## 1. Thread finding: source correction and actual regression receipt

Final `call_validation.py` SHA256:
`79febd82eea06447ad045e8302a62a17164bb04771c9a2ef852b28640a127f4b`.

The reviewed final source now calls `_check_threads` independently of known/Unresolved
entry (`:333–335`). It compares the caller and **all captured child segments** (`:95–115`):
two different known threads cause `call_thread`, while unknown caller/segment threads stay
row-local gaps. This catches known child-completion thread conflict even when entry is
Unresolved, and conflicting known child segments even when caller thread is unknown.
Segments are indexed once by activation (`:278–280`), avoiding a per-call whole-graph scan.

Actual author-owned boundary execution was read, not rerun:
`boundary_calls/attempt001/{command.json,stdout.log,junit.xml,report.json,source.before.json,source.after.json}`.
**10 passed in0.60s**, exit0, wrapper1.2823873749s; Python3.14.7/conda lewm,
PYTHONDONTWRITEBYTECODE=1. JUnit reports10 tests,0 failures/errors/skips and includes both
thread cases by exact name. The validator and test hashes match before/after and current
files. Test SHA256:
`2214e4f0678ed22c282edd38431b6f5b3a85ab89c65102c25b148f6c50e99558`.

The original finding was **source-inferred**, not reproduced against the old implementation.
The boundary suite's first run was after the correction. No old product failure is invented;
the separate fixture-runner API failure remains in its original attempt001 archive.

## 2. Remaining targeted boundary checks

- Final source indexes actual RETURN/RAISE occurrences by activation and rejects multiple
  captured terminal completions for one linked synchronous activation (`:281–289,355–359`).
  The boundary case adds an actual disconnected child failure fragment to a real normal
  child execution, and asserts `call_multiple_completion` without duplicate-ID/definition
  failures. It does not fabricate an ordinary cross-segment edge.
- Caller and child one-to-one guards remain; duplicate caller/activation cases each get
  the corresponding issue, rather than relying on duplicate table IDs.
- Dynamic nesting cycle detection remains iterative and separate from static recursion.
  The positive recursive graph has a real boolean base branch and calls the same Region
  through distinct activations; the negative links the recursive call back into its own
  activation. Tests preserve false runtime/transform flags, not a runtime termination proof.
- Entry remains exact InitialEntry/canonical entry/owning activation/no backedge. Completion
  belongs to the chosen activation and named actual Return/Raise exit; the boundary case
  selecting another same-body activation's completion is rejected.
- Independent ProviderFactReferences and URI aliases at entry are not treated as different
  native entry identities. The corresponding two cases remain legal with pairing gaps.
- Partial capture still preserves known child exit Uses without defaulting caller NORMAL or
  inventing landing formals. Missing/Unresolved dynamic Uses are separate route gaps.
- Nothing in call completion seeds native work terminal/quiescence/borrow release/retirement.
  Canonical occurrences, per-visit definitions, original Uses and current state remain their
  sole sources. Same-scope consistent permutations of whole call declarations can remain
  structurally admissible; source/runtime/value identity is still unproved.

These conclusions combine selective rereading of the final source with actual test-code
and JUnit/log inspection. They are not another execution of those10 cases or of a full suite.

## 3. Five API text corrections checked against current source

Current `docs/M1_CALL_ACTIVATION_API.md` SHA256:
`bef143f321b03172742133ee20316f2e41b7bde1025bde1b902b052b42273f0b`.

1. Four false flags are explicitly named and match `_view`/`call_entries`:
   source_runtime_verified, runtime_identity_verified, value_identity_verified,
   transformation_authorized.
2. INVOKE routing distinguishes `CompletionResult.index` (child result slot) from the
   argument's landing position. `_outputs` follows that order; the canonical fixture
   reverses both normal and exceptional landing order and uses different state slots.
3. The missing-end matrix distinguishes missing entry, missing child completion and missing
   caller transfer. Empty `outputs` with a completion gap means unobserved output routes,
   not zero results/pending/divergence. Existing static caller/callee interfaces remain.
4. Callback wording excludes an opaque wrapper's internal callback/native span masquerading
   as the whole synchronous call, while allowing a separately canonicalized callback call.
5. NO_DECLARED_CALLEE describes only the absence of an explicit core target, not absence of
   calls/effects or purity; MISSING is not failure. Query statuses and false flags agree.

The wrappers return detached dictionaries/records, retain strict ID namespaces, and never
pick a child using static callee, source parent, name, denotation or equal values.

## 4. Existing test receipts and scope

Read author `core/attempt004`:23 passed in0.77s, exit0, final validator hash in
`source-sha256.txt`; this is the records/graph baseline, not evidence that the new boundary
cases existed earlier. Read `query_calls` report:11 passed in0.66s against its recorded
earlier validator snapshot; query-owned files are unchanged, but that focused result is
not relabeled as a final whole-source gate. The agent's separate codec receipt records
243 passed in4.89s and unchanged historical bytes. These selections overlap; no summed
modeling-coverage or full-suite claim is made.

Root still owns the unified component/frozen full gate. R3.1 is dynamic call/declaration
set connection, **not** R3.2/R3.3 end-to-end Q observation closure, arbitrary endpoint
read/flush/persist interpretation, native whole-work extent, source capture/alias closure,
runtime recovery, complete M0–M2, transformation authority or LeWM speedup.

## Final source hashes checked

| Source | SHA256 |
| --- | --- |
| scar/ir/execution/call_validation.py | 79febd82eea06447ad045e8302a62a17164bb04771c9a2ef852b28640a127f4b |
| scar/ir/execution/calls.py | a287446babd077c072f51182d12ecc5e670bd2e1700b6396e914e134d95a183f |
| scar/ir/execution/call_query.py | 9cecb45f6da0ee59a4e86faa1ae05fe5de3d019ed362d5e42aa91830cf1ebe42 |
| scar/ir/execution/query.py | 94b098d75a0568cf48240ff7078f8d4a99b9353c5abd73ccbef804c28803400a |
| scar/ir/execution/validation.py, original scope and new hook | e3a440dc32c4aacba3b4a53b536d11341c0892a4bb5dda08007448bc5dba395d |
| scar/ir/execution/flow.py, original flow precondition | 2b6189a1ad658072176a00bc4c72a4c5af4c66e96edc844bad904471c8eb0501 |
| scar/ir/execution/model.py, table/rechecks | 14a28d9531b744924e24ba1633b691cdb91019e37829665e5f711369c7f2a126 |
| tests/unit/test_execution_call_boundary_review.py | 2214e4f0678ed22c282edd38431b6f5b3a85ab89c65102c25b148f6c50e99558 |
| tests/unit/test_execution_call_validation.py | 843b486b8cdeb917aa230056c6c88731a07e4cf100a1174dfe01ba95ab1e964c |
| tests/unit/test_execution_call_records.py | ecdd19730b63cdeda4d9eb0a9ec0a28fbb1d84aaf8c176fdbd406c717f201f3c |
| tests/unit/test_execution_call_query.py | d2f0236c58e155092506be4a08e3323dbb2a21672bfdc62c74c69de2ccd6609a |
| tests/fixtures/execution_call_graphs.py, disclosed self-authored context | 6fa0d2eca706edc3a371d4d8d8581973b7e28b94ce5623e89048789e3fc8c90b |

The boundary attempt's recorded source hashes equal these current modules/fixture/test.
No claim about a not-yet-run unified component fingerprint is made here. This review batch
is now frozen; no new source edit, test/probe or scope expansion is pending from this agent.
