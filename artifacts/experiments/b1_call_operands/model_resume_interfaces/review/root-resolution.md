# Root design resolution and remaining implementation work

2026-10-17. This is a specification decision, not a C2 gate PASS.

## Settled architecture

1. Keep one logical body Region and canonical producer/Uses. Suspend has typed
   temporal successors; driver handoff and future body execution are distinct.
   Segment lowering is a derived representation only.
2. Derive logical CFG and cut availability from the same edges. Saved operands
   bind new landing parameters. Extra availability roots do not reset C1 cleanup
   activation or pending freshness. The five root checks demonstrate why a
   transitive loop omission escapes ordinary dominance.
3. Ingress gets current shared state immediately before actual body entry,
   including any preceding gate/delegate effects. No shared StateVersion enters
   the saved private frame. Mutable object identity does not freeze contents.
4. Each actual initial/resumed body landing Attach captures its own caller token
   as one canonical result, then installs the relocatable body context fragment.
   ResumeInput supplies pre-install state, not a second caller token. This
   supersedes the initial reports' alternative token/input source. Detach saves
   the body fragment and restores that drive's caller. Private C1 context anchors
   retain inheritance semantics; caller tokens never cross a temporal save.
5. Context-switch intrinsics are callback-free and completion-preserving abstract
   protocols. Real lookup/retention/release/hook work and its normal/raise outcomes
   must be explicit. Full-path attachedness and exact token forwarding are still
   required; a tag or operation name alone cannot prove them.
6. Admitted driver requests can run a delegate and return a host item without
   restoring the parent body. The later four Python observations support the
   context distinction identified by source review. Distinguish drive epoch from
   body continuation generation and request intent from actual body ingress.
7. Synchronous FrameExit adjacency cannot silently combine with Detach. Final
   frame release/finalizer activity belongs to an explicitly modeled driver
   phase; the old synchronous profile remains unchanged.

## Original evidence and revisions

The initial three reports remain frozen. The language follow-up was requested
after control review found CPython's direct delegate throw/close path. It uses
new filenames and does not overwrite the earlier observations.
The main specification was independently reviewed as a 166-line draft. The
review did not find a concrete contradiction; it did not freeze exact records.
Root subsequently strengthened the shared-state wording to explicitly require
post-delegate state at ingress. This is a documented clarification, not a product
fix or a repeated successful test.

## C2.0 remains open

Before product edits, freeze exact records and machine-checkable endpoints for:
Create/Start and deferred bound references; Suspend outputs/private slots/typed
resume cases; pre-Attach current-state producers and context fragment routes;
all-block attachedness and token privacy; gate/delegate/body/host outcome
adapters; terminal frame-release profile. Request families, failures and version
differences retain the denominator in the control protocol catalog.

Then implement C2.1–C2.5 on generic fixtures, strict old wire, public queries and
one frozen full acceptance. Missing source/runtime correspondence, actual
instance/generation exclusion and physical readiness remain explicit obligations.
Do not report any partial component as full C2, first-stage completion, automatic
whole-program modeling or optimization authority. No new detector/backend.
