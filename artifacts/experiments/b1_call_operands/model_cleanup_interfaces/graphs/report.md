# C1 cleanup graph fixture report

## Scope

Hand-authored IR composition only. These fixtures do not recover Python source,
prove runtime cleanup behavior, or authorize transformation. The INVOKE partial
write case is owned by the separate cleanup INVOKE fixture/test. The
nonterminating-cleanup/no-exit-site case is owned by the cleanup-forward review
test, which is being integrated independently.

Owned files:

- `tests/fixtures/program_cleanup_graphs.py`
- `tests/unit/test_program_cleanup_graph.py`
- `tests/unit/test_program_cleanup_codec.py`
- `tests/integration/test_cleanup_program_cli.py`

## Fixture construction evidence

The first nested-graph validation probe was run before the protected edge and
post-pop routing were completed. Its output was:

```text
resume issues []
resume VALID 15 39
nested issues [('cleanup_route_final', 'program_operation:nested.inner.route',
  'completed obligations go to a final C0 dispatch-only block'),
 ('cleanup_protected_bypass', 'program_operation:nested.inner.protected.to-cleanup',
  'every physical exit from protection first enters its cleanup via a route'),
 ('cleanup_entry_edge', 'program_operation:nested.inner.protected.to-cleanup',
  'cleanup entry only accepts a derived Enter route')]
```

The graph was corrected according to `docs/M1_CLEANUP_INTERFACES.md`: the
protected-to-inner-cleanup edge is a one-case `CleanupRoute`; inner
Fallthrough goes from the post-pop route to a C0 dispatch-only block, then to
the still-active outer cleanup's Resume continuation. The inner Return still
routes through inner Replace and outer Replace.

The first unit-test attempt had 7 failures / 2 passes, all in fixture/test
expectations: the cleanup stack query contains cleanup scopes only (not LOOP
scopes); a helper double-wrapped an `OperationID`; and mutations were initially
asserted against C1-only diagnostics even when core validation rejected them
earlier. The next attempt exposed that C0's pending-dispatch wire is
intentionally tagless, plus core `edge_arity`/`control_binding` checks rejected
malformed test mutations before C1. The assertions were narrowed to the
actual protocol boundary; no product validator or codec was changed here.

## Final focused result

Environment: `/home/zyf/miniconda3/envs/lewm/bin/python`, `conda activate lewm`,
`PYTHONDONTWRITEBYTECODE=1`, `PYTHONPATH=.`.

```text
pytest -q tests/unit/test_program_cleanup_graph.py \
  tests/unit/test_program_cleanup_codec.py \
  tests/integration/test_cleanup_program_cli.py
24 passed in 1.70s
```

The positive graph cases cover multi-state Return/Raise Resume, nested
Fallthrough-to-outer-Resume and new-Return double Replace, and local Break /
Continue dispatch within a cleanup while carrying its pending token, saved
context, and current state separately. Negative cases reject omitted state
advancement, wrong activation context, stale outer pending substitution,
protected-scope bypass, skipping the C0 final dispatcher, and cleanup-entry
reentry. Codec checks assert v9's explicit `CLEANUP_ROUTE` tag, unchanged
tagless C0 dispatch shape, v8 golden byte stability, and strict rejection of
C1 tables/route/context capability under schema v1-v8. CLI checks retain
`cleanup_unwinding_verified`, source recovery and transformation authority as
false.

## Follow-up: C1-specific negative assertions

The first broad mutations were not evidence of C1 rejection: direct rewrites of
the nested route made a now-unreferenced block unreachable, so core validation
stopped first. Those observations are retained here: the original direct
fallthrough-to-Resume mutation and the original outer-entry reentry mutation
both produced `unreachable_block` before reaching the intended C1 guards.

The final test mutations now preserve or restore core-valid graph structure:

- Protected bypass changes the typed cleanup route into a JUMP while preserving
  its destination and all actual arguments; it asserts
  `cleanup_protected_bypass` and `cleanup_entry_edge`.
- The C0-skip case keeps the route's destination and actuals but changes the
  target dispatcher operation into a JUMP and removes its no-longer-used
  pending selector Use; it asserts `cleanup_route_final`.
- Outer-entry reentry forwards the target entry's exact pending/world/ambient
  operands and drops unused saved-pending/context Uses. Since that mutation
  disconnects the old outer Replace target, the test removes that now-dead
  block, its operation, and its action declaration. The remaining graph reaches
  C1 and reports `cleanup_stack_merge`; it does not rely on an unreachable-block
  failure.
- Old-pending substitution asserts `cleanup_route_pending` specifically.

Follow-up command and result:

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. pytest -q tests/unit/test_program_cleanup_graph.py
9 passed in 0.39s
```

Full output is preserved in `test_program_cleanup_graph.followup.log`.
