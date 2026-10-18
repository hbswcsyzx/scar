# P4 followup: expanded method lookup receipt

## Bounded result

**Owned necessary focus: 25 new + 52 unchanged continuation tests = 77 PASS,
3.12 s, exit 0. The complete P4 sixteen-group gate remains OPEN.**

`attempt002/` retains raw stdout/stderr, JUnit, exact command, Python version,
registered source hashes before/after and exit. The registered-source fingerprint
was unchanged:
`d5d86be065efab759377e14834fbb7713375bdbab0f8b9868d90691558c1d242`.
This is not a component/full/native execution result.

```sh
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python artifacts/experiments/b1_call_operands/model_protocol_followup/run_focus.py continuations/attempt002 tests/unit/test_program_method_lookup_connections.py tests/unit/test_program_continuation_connections.py
```

The actual interpreter was conda Python 3.14.7. All attempts were sequential in
root's assigned testing window; the window was released after attempt002.

## Frozen source

| File | SHA-256 |
| --- | --- |
| `scar/ir/program/protocols.py` | `d665ffb437dddd18bc58f386f953c26ec521292d03947d5ecdc6cd0a247b5d01` |
| `scar/ir/program/protocol_rules.py` | `1333bfeccab26e2d7234ec790f1f4073eca98648c86610c94e00a910ac9f0bf6` |
| `scar/ir/program/protocol_continuations.py` | `ef26888f07aa6934fe50009a5afc50606dced4f231e52eea8da5d942fa494635` |
| `tests/fixtures/program_method_lookup_graphs.py` | `22d1b4c41d6813a24200fa99b9c9ada76affb220c9f5e53fe4bbeb88c2c85412` |
| `tests/unit/test_program_method_lookup_connections.py` | `7c2e597faec7523f535ce74799697a341c191d9c3138337a40dc9f7889502307` |

The implementation follows `docs/M1_PROTOCOL_FOLLOWUP_PLAN.md`, SHA
`44437087abfe3fa1a7b074ca973c06a0f863eb0c4fc9073ef26f8881de412f78`.
`source.final.json` is the machine receipt. Parent/A own the Program20 codec and
capability helper; this owned focused result is not their acceptance.

## Exact implemented relationship

The new closed enum rules are `DELEGATE_NEXT_LOOKUP`, `DELEGATE_SEND_LOOKUP`,
`DELEGATE_THROW_LOOKUP`, `DELEGATE_CLOSE_LOOKUP`. They reuse `ProtocolCall` and
only their corresponding original DELEGATE_ADVANCE/THROW/CLOSE clauses. There is
no new producer, state domain, use graph, lookup table or request history.

For each expanded path:

1. A separately declared iterator source is the lookup's expected receiver.
2. The original lookup CALL/INVOKE owns its receiver Use, state sites and selected
   NORMAL/RAISE output. Lookup has no request arguments or trigger. Broad
   descriptor/callback effects remain on the original coarse state ports.
3. The bound call's independently supplied expected source is the matching
   method lookup's **own NORMAL** ContractResult (or a canonical formal checked
   against independent inventory). Its original actual receiver Use must be a
   fresh copy of that result. The bound method is never inserted into the
   iterator's copy closure.
4. Raw trigger and ordered 1–3 THROW ordinals remain call operands. No RAW formal
   or fake method argument is introduced. The original call retains actual N/R,
   result and current state relationships.
5. The lookup NORMAL's fixed source is used to derive the original consumer
   inventory, reusing `common_connections(ctx)` and the same budget/context.
   This is not an actual-input search that selects the expected producer.
   Known calls must agree in kind and independently expected evaluation. A
   copied lookup result used as another role or without a matching callable
   consumer retains a specific missing-role/consumer condition. Deleting the
   input/target attachments preserves the original N/R obligations.
6. Lookup RAISE retains its exact own packet and real exceptional consumer,
   with `method_lookup_exception_category_unproved`. It is not automatically a
   missing-method event or permission to resume an old injected packet.

Old atomic helpers continue to accept their original independently named
iterator inputs. Their existence does not establish expanded internals. A fake
atomic expectation cannot make an actual bound-method receiver equal the
iterator. An unrelated lookup does not force every atomic call in a region to
be expanded. A discarded required lookup result remains incomplete rather than
proving the stage unnecessary. Wholesale removal of source/site declarations
still has the original source-inventory condition; there is no source parser
claim that discovers all deleted stages.

### Canonical formal, branch and lifetime cases

Direct completion formals are resolved from the **independently supplied
formal's original result**, not from the actual callable input. A later formal
uses the existing independent unique-rule inventory; multiple unselected
candidates retain an explicit gap rather than an ANY success. A known wrong
kind/result is still a contradiction. The two real branch fixture independently
selects each method result and raw source before the upstream merge/JUMP/call;
swapping same-kind sources rejects. The loop fixture executes one static method
lookup each iteration and carries a previous bound method on the original
backedge; using it after re-evaluation rejects on the original fresh-copy logic.

Expanded InitialAdvance still names the iterator evaluation, not the bound
method. Its port check now targets the lookup's original iterator input. The
opaque lookup may callback, so first-advance applicability remains partial;
the marker itself never grants a native protocol fact. Existing actual loop
known-repeat rejection remains in the unchanged 52-test file.

### Necessary InitialAdvance correction and evidence

B's source review identified a separate existing risk: prior atomic SEND's
receiver phi can be A on one incoming and B on another. `bind(A, phi)` being
must-false does not mean neither route advanced A. A later A NEXT cannot be
certified InitialAdvance on that basis.

`prior_advance_case_program()` evaluates B then A, branches the original SEND
receiver/argument/state tuple and then performs A NEXT. Its test first establishes
three public original-port facts: unguarded must-false, A-incoming true,
B-incoming false. Original core validation passes. The fixture contains no
opaque operation after A's evaluation other than the typed advance steps;
ordinary branch/copy/exit primitives are explicitly complete CONTROL operations.
This is a supplied abstract primitive declaration, not native frame-cleanup
proof or permission to omit known effects.

| Attempt | Actual result | Meaning |
| --- | --- | --- |
| `attempt001` | 24P / 1.44 s | Initial new method tests, before the additional prior-case risk. |
| `prior-case-red001` | **1P** / 0.81 s | Candidate did not reproduce: old builder's incomplete CONTROL operations already forced unknown. This is not called a red result. |
| `prior-case-red002` | **1F** / 0.82 s | After making the new fixture's genuine control primitives complete, the original core and three bindings still passed, but the later InitialAdvance was falsely DECLARED. Product code was not reverted to create the red. |
| `attempt002` | **77P** / 3.12 s | Necessary fix plus new 25 and unchanged original 52; source before/after identical. |

The fix jointly uses each prior input case's original guard with the current
case guard. Conflicting static visits stay unknown. A must-false result with a
possible copy is not treated as absence. Mixed true/false or unknown cases
remain partial; only a complete proved alias step sets the definite advanced
flag. This is conservative declaration-level transfer, not path enumeration or
a dynamic instance/alias proof. The old known repeated-advance path still
rejects. All original attempt stdout/JUnit/source hashes remain unchanged.

## Acceptance denominator and remaining work

`coverage.json` preserves all sixteen original groups individually OPEN, including
the earlier ledger's exact test mapping and uncompleted requirements. This
followup adds a bounded delta to F20–F23, not a whole-family pass.

- F12–F15: full coroutine eligibility, phase/reuse/throw/close and the same
  generator-coroutine body directly/awaited remain required.
- F20–F23: expanded method acquisition and own N/R/call ports are now expressible
  and exercised. Full missing-method category interpretation and fallbacks
  remain required. In particular, raw THROW plus the exact original injected
  packet in a noDriver helper is not represented by the raw-only trigger alone;
  no actual handler packet is chosen backwards to fill this missing reference.
  Raw CLOSE/THROW(GE) normalization/category routes also remain explicit work.
- F16–F19/F24: async/cancel owner's separate evidence is not inferred from this
  result; integrated original consumer and session obligations remain.
- X25: one-cut C1 positives are not the at-least-two-cut/local binding/loop/merge
  group. X26 requires new publication/session/partial RAISE/narrow release and
  broad helper combinations. X27 requires these protocol sites with actual P3
  persistent activation, entry/outcome/current segment and capture identities.
- The direct formal, local guarded branch and loop fixtures do not constitute a
  new cross-helper bound-method or native descriptor identity proof. Existing
  shared caller-input machinery is reused; unseen capture/source applicability
  remains conditional.

Program20's capability boundary is required because Program19 is archived.
That separate codec source review records old-byte/oracle provenance and new
capability downgrade rejection; no serializer result grants native correctness.

## Limits and freeze

Every supplied state/version/result/producer/Use remains canonical. State-address
metadata is PARTIAL and does not compress descriptor callbacks into a dictionary
read. No exception category is inferred from a label, no missing lookup swallows
an exception by default, and no delegate-only route invents a parent Drive,
Attach, F or release. Runtime/source identity and transformation flags remain
false. Shared derivation cost is reported; snapshot/FK/preparation/copy and all
CPU time are not claimed to fit the query budget.

The five owned files were frozen and the testing window released after the
77-pass attempt. No component, full regression, native probe, backend, detector,
LeWM rule, workload or acceleration experiment was run. The complete M0–M2
objective and full P4 gate are not declared complete.
