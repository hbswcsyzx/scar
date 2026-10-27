# Implementation review findings before first connected run

These are source-review findings, not runtime results.

1. Original core forbids non-route instructions in a post-pop corridor and
   requires the final jump immediately after a C1 exit. The first two new-fixture
   failures demonstrate those constraints; no core rule was weakened.
2. Original C1 Enter/Resume/Replace must retain `effects_complete=False` and
   whole-domain RW post-state. They cannot be marked pure to make a test pass.
   The new explicit transfer declaration covers only actual no-extra-behavior
   ordinary transfers; typed C1 effects remain conditional/unproved.
3. A source-relative payload support must not prune a wrong-source branch.
   Conversely, carrying each candidate payload down every other candidate's
   port creates an artificial cross product. Active ControlPort is a temporary
   correlation fact, not a new program value. Same-port sources all remain.
4. Dead pending definitions are not active consumers. Old `_close_frontier`
   scanned every pack it passed; A removed that scan, keeping actual token
   sources and preserving independent wrong-first-handoff checks.
5. Root's review identified that a `CallReturns.project` current-copy summary
   does not inventory the callee's opaque internal operations. A confirmed the
   source-level risk. C is adding a real known-helper internal-opaque example;
   its actual result and any repair will be preserved separately. Never claim
   this is reproduced until the test executes.

No new backend, native/source interpretation or dynamic occurrence authority
follows from these supplied-program relationships. Full P4 remains open.
