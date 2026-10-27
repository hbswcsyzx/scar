# Deterministic ProtocolFlow copy worklist: independent design review

Status: **DESIGN_ACCEPT_WITH_SCOPE**, not repaired-product or test PASS.
Read-only source review; no Python, seed experiment, pytest, component or full
run in this turn. The original full FAIL and eight-seed evidence are untouched.

Reviewed current `scar/ir/program/protocol_flow.py` SHA
`782e7460a21a41e215dd338cb210ed00ddee11990802e37e9c31b26d6b0a4984`, especially
`_edges` and `_fresh_copies`; also read `created_close.py` SHA `5c1088ff…`,
`protocol_query.py` SHA `1b17e1e5…`, `admission.py` and `ValidityBudget.spend`.
This is review of the proposed change to that source, not a claim it is applied.

## Decision

Accept the minimal design: construct a transient **entry-first reverse
postorder tuple** by explicit-stack DFS over the original ordered CFG successor
lists. Initialize both copy edge storage and the worklist using that tuple.
Retain `reached`/`queued` sets solely for membership, not scheduling. Do not
change meet/kill/reset/parallel rename, initialization facts or budget formulas.

The current nondeterminism is at `_fresh_copies:229–231`: edge initialization and
`deque(reached)` enumerate a frozenset. The earlier fresh-process seed5 reproduced
default-budget truncation without any class/enum pollution. That observation
supports repairing scheduling; it does not justify a larger public/test budget.

## Exact DFS requirements

1. Start only at the validated region entry. Mark a node on discovery; the
   explicit stack retains the next successor index. Append to postorder only
   after all original successors have been examined, then reverse once.
2. Retain every actual edge `(operation, successor_index)` and its original
   actual→formal assignment dictionary. DFS deduplicates **visited nodes**, not
   edges. Two BRANCH edges can target the same block with different actuals;
   both incoming alternatives still participate in the must meet.
3. Follow the existing successor tuple's order, without using set iteration or
   `Region.blocks` declaration order to choose the next node. Explicit stack
   avoids recursion-limit dependence on deep valid regions.
4. The reverse postorder is deterministic even when siblings appear in reverse
   visitation order: for entry→A/B→join, DFS first visits A, but RPO may process
   B before A. This is a solver schedule, not a new semantic edge order or a
   selected execution path.
5. If the private `_edges` return tuple gains an RPO element, update both actual
   callers (`_fresh_copies` and `reaches`) consistently. Keeping another private
   derived-order cache is also possible, but no new authoritative graph/table
   or stored producer is required.

## Remaining iteration and its effect on copy costs

| Source collection | Use after the proposed change | Consequence |
| --- | --- | --- |
| `reached`, `queued` | membership/add/remove only | Hash iteration no longer chooses worklist order. |
| `_universes[region]`, `current`, edge fact sets | membership, difference, intersection, union, equality and cardinality | Same logical sets give the same `len`/equality; internal Python set layout is not used to choose a query branch or a charged prefix. CPU hash-table cost is not the public work-unit budget. |
| `outgoing[block]` | Original successor enumeration and later enqueue order | Deterministic for the same original CFG. Real backedges/parallel edges remain. |
| `assignments.items()` | Original target formal order from `zip(edge.arguments, block.arguments)` | All RHS membership tests use the same pre-edge `current`; no sequential phi/swap update is introduced. |
| `incoming[block]` | All reachable parent facts, one intersection, one `sum(len(parent))` charge | Parent list order can change with block storage order, but no early exit/parent-wise budget check exists. Set intersection and integer sum are commutative; fact and charge are unchanged. |
| `_ports` / `_flows` | Exact-key lookup; no enumeration selects which fact wins | For a fixed query call order/cache lifetime, no additional hash-scheduled solve was found. |

Thus no other unordered iterator **inside this copy solve** was found that
changes `copy_blocks`, `copy_operations`, `copy_meet` or `copy_edges` counts once
initial scheduling is canonical. Dynamic requeues are deterministic because
outgoing order and `edges[edge_key] != renamed` become deterministic as well.

## Fixed point and loops

The lattice remains the finite product of powersets of original ValueIDs, one
fact per original edge. It starts at universe/top; entry is False/empty before
the selected source evaluation. Intersection, result kills, constant source
seeding and parallel formal overwrite are monotone transfers. RPO changes only
the order of a fair worklist: every reached block is initially queued, and every
changed outgoing fact queues its target if not already pending. Unlimited-budget
convergence therefore reaches the same greatest must fixed point. No arbitrary
iteration cap, path enumeration or new state identity is introduced.

Specific cases remain necessary and are not altered by the schedule:

- **No-seed cycle:** the reachable path from the empty entry still removes
  unsupported cycle facts; no node is omitted merely because DFS saw a backedge.
- **Anchored loop:** current source results and their forwarded formals remain
  copies, including a real backedge; resetting at the source evaluation prevents
  an older visit's copy from masquerading as the new evaluation.
- **Phi swap:** remove all target formals first, then derive every formal from
  the unchanged pre-edge set; statement order must not turn one actual into
  another or mix branches.
- **Source before/after/edge:** preserve the existing phase-specific seed and
  reexecution kill exactly. In particular, an edge seed belongs only to its
  selected ordinal; other actual completions must not receive it.

## Declaration block reorder and precise scope of determinism

Pure reordering of `Region.blocks` while retaining entry, block contents and
successor tuples should **not** change this copy result or these copy costs.
RPO depends on reachable CFG structure, not storage order. `incoming` insertion
order is the only residual block-storage influence here, and its complete
intersection/cardinality-sum operation removes that influence mathematically.
Likewise reordering unrelated definitions does not change universe cardinality.

This does not promise representation-independent budgets for arbitrary changes
to protocol row order, literal row order or CFG successor order; those original
ordered inventories can legitimately choose different bounded query prefixes.
Nor is this a claim that every other analysis has no unordered scheduler:
`admission_routes` has a separate Kahn ready list built from a seen-node set.
Its accounting is outside this copy solve and outside the observed exact
CreatedClose scope. Do not extend this repair's claim to whole-program query
determinism without a separate concrete need/review.

The extra DFS/RPO preparation remains finite O(blocks+edges), replacing the
existing reachability preparation; it is not a new promise that all record/FK/
preparation CPU fits the public4096 derived-work budget. Public defaults,
charging formulas, saturation/truncation and conservative Unknown remain intact.

## Acceptance boundary for root's subsequent implementation

No structural counterexample to the proposed minimal repair was found, under
the exact requirements above. Product correctness/actual4096 success still
requires the separate repair regression receipt: the formerly failing seed,
hash-independent costs, declaration-block permutation, cyclic copy freshness
and existing query/truncation behavior. This reviewer has not run those checks
or modified their assertions. No source/native applicability or transformation
authority is inferred, and the original frozen full remains FAIL until separately
repaired and reaccepted by root.

## Actual implementation receipt (append)

Read the applied repair at `protocol_flow.py` SHA
`a3518f4fa83ceba2d748d0b7e5d44fbc1ac7c0f629e103d8aad3c0c852ba87a7`.
It matches the accepted minimal design:

- `_edges:209–224` uses stack entries `(block, iterator(original outgoing))`,
  marks discovery once, emits postorder on iterator exhaustion and reverses it.
  The existing outgoing/incoming structures retain every original edge and
  exact assignment; no second producer/CFG is created.
- The private result adds only its RPO tuple. A whole-source search finds just
  two `_edges` callers: `_fresh_copies` and `reaches`, both updated to five-item
  unpacking. Reachability's own port/path semantics are unchanged.
- `_fresh_copies` initializes edge facts and `deque` from the RPO tuple; `reached`
  and `queued` remain membership sets. The old meet, cardinality charges,
  operation-result forget, phase reset/seed and simultaneous assignment code
  is retained. No new result shortcut, budget limit, iteration cap or relaxed
  source/target check was introduced.

No actual-diff blocker was found for cycles, must convergence, edge-specific
seeding, ordinary Use resolution, noncopy completion/resume inputs or parallel
edges. Declaration-block order cannot select this worklist after the repair.
This is a **bounded SOURCE_REVIEW_CLOSED** for that diff, not whole P2/full PASS.

Read the new `test_program_protocol_flow_determinism.py` SHA
`180444b0d63ad0d09b0c8c41ad8daa1f9b68f77ed6d7b5cf3dce54ac3566588b`:
eight fresh process seeds compare the actual None answer and full budget snapshot;
the table permutation reverses operations/values/regions/blocks without changing
the actual successor order; budget1 preserves the fixed clause denominator and
cursor. Existing loop/current-evaluation tests remain meaningful; no assertion
was weakened to accept None at the default budget.

Also read root's preserved receipts, without executing them:

- `repair/red/attempt001/result.json`: returncode1, wall7.337439s,
  stable registered fingerprint `91b661d7…`; this retains the pre-repair failure.
- `repair/focused/attempt001/stdout.log` and result JSON: **47 passed / 7.36s**,
  returncode0, wall7.980259s, stable registered fingerprint
  `ecacbd8d0f5fe17948b09037f83e06d211964d2d75f8205d7b5007ff485ac215`.
  This is root's focused execution, not an independent rerun by this reviewer.

The original `full/` FAIL remains untouched. No new test, standalone seed,
script, product or test-file write was performed in this design/source review.
Only this append-only ignored report changed; reviewer stops writing now.
