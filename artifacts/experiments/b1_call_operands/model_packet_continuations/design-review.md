# Design review — supplied packet continuation

2026-10-19, base f2b4781. Three read-only reviews inspected the original P4
contract, packet/frontier/close code and existing C1 two-cut fixtures. No reviewer
executed Python, probes, tests or workloads during this review.

- A (`cleanup_forward_review`): `_close_route` and `packet_frontiers` stop at
  C1 action, but only the latter explicitly retains the continuation gap.
  Suggested one shared full-continuation resolver with exact selector/port
  possibility, original saved/current roles and source-relative endpoint checks.
  Port possibility must be independent of expected payload support; otherwise a
  wrong-source branch could disappear. Dead packs must not poison active tokens.
- B (`value_resource_review`): the existing close cleanup test explicitly
  accepts local DECLARED at the action; that evidence cannot close F23/X25 or
  a later consumer obligation. Original exit-shim validation independently
  prevents substituting another final packet; do not bypass it to fabricate a
  new failing source test. A core-valid opaque operation after C1 exposes the
  missing continuation denominator without weakening core.
- C (`reuse_capture`): shared source_binding now reaches the actual terminal,
  but does not independently enumerate consumers. Full resolution must retain
  opaque siblings, partial inventories and budget cursors, and must not treat
  known helper input as the rule's final terminal. Two distinct two-cut fixtures
  prove different payload lifetimes, never one combined dynamic occurrence.

Decision: preserve the original frontier query, connect one internal complete
resolver to the existing close and fallback family queries, keep first-frontier
evidence separately, and derive its consumer obligations from the original CFG.
Temporal successors remain conditional declared paths; native/source identity,
P3 occurrence matching and transformation authority are not granted. All sixteen
original P4 groups remain open. Implementation acceptance is pending.

Frozen plan: docs/M1_PACKET_CONTINUATION_PLAN.md,
SHA256 3512314d9c9bef2535f6a68e2b7e802c8dd0b5556a7ccd27b2b9ec4035f21025.
