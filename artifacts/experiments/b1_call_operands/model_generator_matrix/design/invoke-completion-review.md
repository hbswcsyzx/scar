# General INVOKE completion subsets — independent source review

## Scope and original finding

Observed by reading source, without executing the old implementation. The real
close/retry fixture's first attempt had exposed the inability to call a known
callee whose only actual exit is RAISE. Adding a fictional NORMAL exit would
change that program. The later Return/Yield branch fixture exercised a different
valid program; it did not repair or disprove this expressiveness limitation.

Old `model.py` required exactly two successors at its former lines 583–590 and
exactly two signatures at 683–688. The source review recommendation was a
nonempty unique subset of NORMAL/RAISE, with the signature-kind set **exactly**
equal to the edge-kind set. Nonempty is a local interface requirement, not a
termination proof; a callee with no exit remains outside this narrowly approved
change. No new producer, Use, state chain, or completion signature is introduced.

## Reviewed implementation and required boundaries

1. `scar/ir/program/model.py:583` now enforces nonempty, distinct kinds/targets;
   `:686` enforces unique signatures matching the actual edges. Empty, duplicate,
   extra, missing, or wrong-kind signatures must be rejected independently of
   whether downstream block types happen to agree.
2. `validation.py:305` checks each actual edge against its own signature;
   `:324` requires every produced slot exactly once. `:526` checks current state
   inputs and every actual poststate. `:549` compares a known callee's exact
   exit-kind/type interface to the invocation. These rules already support a
   real one-edge interface. The diagnostic text “both completion paths” at
   `:545` is historical wording; the loop checks the actual present paths.
3. `driver_validation.py:308` now diagnoses `driver_gate_completions` before
   selecting NORMAL. A FinalBodyGate remains a stronger N+R contract. Widening
   the generic INVOKE must not admit a partial gate or cause StopIteration.
4. `queries.py:696` now raises explicit ValueError when NORMAL is absent;
   `:704` preserves CompletionResult.index versus physical landing position.
   No NORMAL result is guessed from a RAISE-only operation.
5. `session_release_validation.py:90` already requires actual NORMAL for the
   NORMAL_COMPLETION post contract. `session_flow.py` seeds only its actual
   NORMAL edge; RAISE keeps partial state. `binding_validation.py:133` and
   `:351` use safe optional NORMAL lookup. The new core capability does not
   silently expand those specialized contracts.
6. `literal_validation.py:30` deliberately requires NORMAL for a literal
   evaluation. Protocol N/R result resolution remains a separate original-port
   lookup. A sole RAISE edge may have ordinal zero; ordinal is not ExitKind.
7. `execution/call_validation.py:135` derives child kind from its actual
   RETURN/RAISE; `:200` compares it to the caller's actual transfer edge.
   `execution/host_order.py` likewise uses the captured edge. This is a source
   compatibility check, not a claim of new execution tests or native capture.

## Wire decision

Program18 is still unreleased in this batch. `codec.py:207` recognizes the
single-completion capability; `:242` selects v18 for admission **or** that
capability. `:469` rejects partial INVOKE under every old family; `:471` accepts
either v18 capability. A bare partial INVOKE must not fall back to v2 merely
because it has no protocol tables. Dual-edge graphs retain their original
automatic version and bytes. The public `dumps(graph)` has no force-version
argument; downgrade tests alter the envelope and verify `loads` rejects it.

## Proposed and now-owned test denominator

- Genuine known-callee RAISE-only → actual caller exception handler, NORMAL-only
  → actual RETURN, and unchanged dual N/R; no invented callee exit.
- State is updated inside the callee, then caller completion formals contain
  the current poststate. Logical `(Reference, State)` result slots map to
  physical `(State, Reference)` formals, preserving original producers.
- Missing/duplicate/extra signature kinds, duplicate target/kind, wrong result
  projection, stale precall state, and a different genuine callee interface.
- Missing NORMAL getter returns ValueError; FinalBodyGate subsets produce a
  typed driver diagnostic over otherwise core-valid paths, including R-only.
- Auto v18 for partial INVOKE, all old envelopes rejected, old admission v18
  retained, legacy v2 and independent v17 bytes retained.

Fixture API: `invoke_subset_program(kinds=(ExitKind.RAISE,), *,
alternate_callee=False) -> (ProgramGraph, details)` and
`final_gate_subset_program(kind) -> (ProgramGraph, details)`. These are declared
manual IR fixtures. They do not prove native phase applicability, dynamic object
identity, protocol-family completeness, GPU completion, or transformation rights.

## Existing-unit audit

The sole explicit blanket one-edge rejection found was
`test_program_completion_records.py::test_invoke_requires_one_distinct_normal_and_raise_completion_target`.
Root retained the case identity and changed its one-edge assertion to positive;
duplicate-kind/target checks remain. Its operation-signature test only needed
the new diagnostic wording. Other `len(...)=2` assertions inspected are specific
dual fixtures: `test_program_no_body_graph.py:109`,
`test_program_state_address_query.py:99`, and
`test_resumption_invoke.py:32–35`. They do not assert all single-edge INVOKEs
invalid. The completion adversarial file's `[1-index]` swap is deliberately
testing its fixed dual signature types; it remains meaningful. No old test was
edited by this reviewer and no old suite was run here.

## Source receipt before new focused tests

```
002675cf3f627f29b56a55bdaca39fa261bbaab410af33608dbffec3c18d82b6 model.py
355d5863e59a0714c14ad3e4bffb1e6423a6900b924cb94df8e7654310bc7a94 codec.py
853ade72319d7fbc6f06337fcc23ca56b358e627d6463b935e4bf32ea1144f89 queries.py
cdd8439fb1cd63c3ecd52c42f796a4c0cf15ec53591b0859f25137bee2f0e4d6 driver_validation.py
c65ff8590068bed8c8c0bd8fbbbe44a33e4bfc2afce1ae218b936a90207a465e validation.py
b96e989a611a518630e2c33bbf61b5f69d4cc015b54166d27f78a6486482e0fc session_release_validation.py
498e7515e4951013822befc419c85b842159be70c1ced08e5cd6ab74d8cd99cd binding_validation.py
1c0cc6ce2464804dfb29fced4cdf9ba7f4f0ffa65407b62073e0f17fd91436ca literal_validation.py
9b9de07e1002e4f2c973dba2a48fac44e7ecfde546caf191a8b47c192adb09c2 execution/call_validation.py
a3dacaf57ec45fc1e57d3139a82675c5af6a1b3d19409cdec3b990edc2fabc02 execution/host_order.py
```

Status: **SOURCE_PASS_WITH_SCOPE; focused results pending**, not full P2 closure.

## Focused receipt (append; original source receipt retained)

New `test_program_invoke_subsets.py` first attempt: **47 PASS / 0.87s**, exit 0,
wall 1.475025s. Original JUnit reports 47 tests, zero errors/failures/skips.
Evidence: `../invoke-subsets-focused/attempt001/`, including command/environment,
stdout/stderr, JUnit, result JSON, all-source inventory and 16-file local hashes.
Both inventories were stable during this run; registered-source fingerprint
`63019101896ebfb9da1c18564b12f543bd5c048a43e2108efaf78f69820facb4`.

Root added the separately authorized input-origin query wrappers before this
attempt. Consequently the tested `queries.py` is
`b5a22aa7c7acc620100be6f53961097f3f52facce39665a856e5d728e6ca5060`, rather
than the earlier source-reading receipt `853ade72…`. The reviewed normal_result
change is retained. The other three product hashes above match the focused run.
There was no in-run source change and no repeat/hidden earlier pytest attempt.

Both specialized gate counterexamples returned exactly
`driver_gate_completions`: no preceding core issue hid the typed check, and
RAISE-only did not crash. All three callee subsets passed real graph validation;
stale poststate, wrong result projections and mismatched genuine callee exits
were rejected. Historical-envelope tests include v17's identical graph field
shape; older envelopes may also reject on their narrower fields. The independent
v2/v17 golden encoder bytes remained unchanged; the old admission capability
still selected v18 and roundtripped. No new historical golden was generated.

Final new file hashes:

```
41aba0cbde2c4d761b18b991cbccecc1f292836a88a1d79792c0896899b60dc5 tests/fixtures/program_invoke_subset_graphs.py
9a5b5f4b645ee8e09655c4cd5666e54808d1b602dfdf2cce4c859ab157c7f841 tests/unit/test_program_invoke_subsets.py
11b533212e91c210b622c63e1259a0dbdbd2632e798bcc18174ff5d5ddfa6a13 attempt001/junit.xml
```

Final bounded status: **PASS_WITH_SCOPE** for the general nonempty completion
subset interface and its specialized gate/wire boundaries. These 47 tests are
new declared fixtures, not native/source applicability or full protocol-family
coverage. No full suite, component, Python observer, workload, GPU execution,
or product edit was performed by this reviewer. New fixture/tests are frozen.
