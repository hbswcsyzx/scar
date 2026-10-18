# D / R review record

2026-10-18. Base b73d8c5d2150decf4787e6c3f4225d47471ff5f5.
This is an intermediate P4 return-connection repair, not one of the complete16
groups being closed. Frozen contracts and historical evidence are unchanged.

## Before implementation

Root inspected ProtocolFlow, ConnectionContext, ProgramIndex, input_origins,
request_inputs and canonical validation. Three independent read-only reviewers
(cleanup_forward_review, value_resource_review, reuse_capture) agreed that
known-callee RETURN/RAISE could not generally reconnect to caller outputs.
They required exact actual ordinals, kind/slot/edge separation, per-call seeds,
source re-evaluation reset, shared budget, no empty-terminal success, and None
for unresolved recursion/context. No new wire or authoritative producer graph.

The fixture authors were assigned only new fixture/test files. Root ran all
tests sequentially. Read-only reviews did not execute Python/pytest or alter
source. The public query reuses the original prepared ProgramIndex.

## Findings retained and resolved

- R0: legal identity CALL returned False in the original connection query.
  red-identity:1FAIL; identity-first-fix:1PASS. Both source registries stable.
- First ordinary run:17PASS/1FAIL. The failure was a fixture unbound_exit, not
  evidence against the implementation. Replaced only that new fixture's
  invalid endless callee with a valid C1 pending Return intercepted by cleanup.
- Independent state reviewer found that separate internal-source exports miss
  same-call RETURN(x,x,state) followed by alternative caller Uses. Root archived
  an actual False result in red-multiple-exports:1FAIL. Grouped original slots
  within one exact call; INVOKE seeds remain separate per actual edge.
- State reviewer found first-query exit_port_uses sorted/materialized outside
  budget. Reuse the already prepared raw exit inventory without copying/sorting;
  terminal iteration remains charged before work.
- Shared gaps could accumulate unrelated old diagnostics. Top-level bind now
  resets query gaps; cached summaries replay their own unresolved reasons.
- Adversarial reviewer requested explicit guard and terminal-use evidence on
  internal-source export. Export frames now contain guards/projection, routes
  contain guard, public report echoes selected_guards/conditional. A specific
  report-contract regression covers the conditional internal-source case.
- Adversarial reviewer found empty completion-edge iteration could escape
  argument-only charges. Both transfer/export now charge each candidate edge
  first, including empty arguments; projection charges each exit kind as well.
- A suspected cross-region guard ValueError was withdrawn by its reviewer:
  ConnectionContext already filters the guard to the local flow region. Keep
  full guards in the summary context so nested helper choices are not lost.

## Narrow checks before final freeze

state-first:13PASS, stable source registry.
grouped-and-query-first:11PASS (two export paths, eight query invariants and the
repaired valid C1 no-terminal case), stable source registry. These are distinct
partial attempts, not complete18/whole-P4/full acceptance.

Two reviewers approved the grouping/reset/prepared-inventory source at
call_returns28647c12... /protocol_flow69365bd5.... Later call_returns changes
only expose export evidence and add candidate-edge/exit budget charges; their
final read-only confirmation is recorded separately. No full or LeWM run here.
