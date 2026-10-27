# Bounded source review for unified affected validation

Frozen implementation:

```text
d528e7da5568294ec445c01a1ee9145cebe70314dc278c02fa5846a07a0731ff  scar/ir/program/protocol_packet_routes.py
ada829d8a3f7764f9dd4f5398ac6394125e3e6a747cf8363081b9782e195c71a  scar/ir/program/protocol_continuations.py
c63a4da2d9f9eee82bc76b2c7c6e5a92c6ae175f08705e4f766eb5c1f3794380  scar/ir/program/protocol_lookup_fallbacks.py
```

A's author self-review reports the first-frontier body retained, actual active
pending selection, shared possible-port flow, original context/current-state
semantics and independent exact copy/callee-scope checks. A performed no tests.

B's independent read-only closure confirmed these exact hashes. Every pending
recipe's original CFG choices are correlated before currentness and payload
checks. Noncurrent candidates remain explicit unknown checks/boundaries and
cannot authorize a hard wrong-payload or override inference. Current candidates
carry their own port/context; sources are not combined by ANY. Each fallback
case/leg is checked separately and aggregate success requires all declared
compatible cases, no partial result and no truncation. B reported no remaining
blocker in this bounded source review, edited no source and executed no tests.

Root independently inspected the integration, the source-relative versus
possible-port distinction, shared budgets/caches, exact host tests and the
callee-scope/copy split. Root's actual repaired two-file run is 14 PASS at
stable 721-source fingerprint 4da7929e56cb8ab4629d12249972f1f3401d716f578c9f55edd5d75da2e732a4.
Those tests are separate from review and are not a full regression or complete
P4 acceptance.

C's independent read-only closure confirmed the same three implementation
hashes and its edge-test hash 8f4580aaabad8ddc5fb8c8a010c226f5b4618bb8650b96b25d63295972f74e70.
No remaining false-complete path was found within this bounded review. Unknown
callee structure prevents the caller from proceeding on a return-copy summary
alone; exact inner boundaries propagate, all receiver cases remain separate and
AND-combined, and shared-budget truncation remains incomplete. C executed no
tests and changed no frozen source.

C identified a reporting limitation: nested callee-scope truncation has no
precise inner resume cursor; the outer cursor returns to the enclosing call.
This does not grant success, but inner-position resumability is unimplemented.
It remains recorded rather than relabeled as a complete occurrence inventory.

All sixteen P4 groups, P5/M2, source/native correspondence and transformation
authority remain open. Unified affected validation is a separate receipt.
