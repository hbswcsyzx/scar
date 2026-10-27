# Original post-conversion cleanup attempts

Base `107ff11efd0d8369583b613282dfca5450692c48`. Original A–H, sixteen
groups, P5 and M2 remain open. Root alone runs Python/pytest/probes serially,
after every author explicitly freezes. Attempts are immutable.

| Attempt | Actual result | Attribution |
| --- | --- | --- |
| first-red-static | 0 passed / 7 failed; pytest 1.19s | New fixture author errors, before any new product field/assertion: rebuilt final driver lost its non-root parent; LiteralOrigin(None) Reference incorrectly defaulted targets=None instead of the required empty tuple. Core validator is correct. Root requested fixes only to the newly authored fixture, keeping tests/old graphs/validator unchanged. |
| first-red-connections | 1 passed / 14 failed; pytest 8.08s | B: continuation receipts/public query absent; legitimate Replace misrejected by legacy direct-copy/RAISE assumptions. C: new H call reused one private caller Use on two outgoing edges, violating exact owned-port control validation. New fixture only corrected to two Uses of the same caller reference; corresponding new structural test expectation corrected, copy/state expectations unchanged. |
| static-connection-repair | 21 passed / 4 failed; pytest 8.62s | Product: CleanupRoute incorrectly filtered the replacement token by the old active completion port before Replace could consume old/new tokens. Author: new P host declared an unused NORMAL exit although every actual host terminal RAISEs; new fixture now declares actual exits only. Old packet query mode retained. |
| first-red-dynamic | 19 passed / 3 failed; pytest 32.93s | Product: missing actual pending payload Use left terminal-to-parent delivery True without conjoining current-source evidence. Static nested result export used edge-only seeds; pending payload flow only inspected ordinary port.values, losing the source across P dispatch. Both repaired in shared relations; old tests unchanged. All six actual-parent tests passed in this attempt. |
| continuation-copy-repair | 36 passed / 0 failed; pytest 36.02s | All22 new items plus14 existing packet continuation items;831 stable sources, SHA117fe2a2ae0be1e70db5f0690ed03df70051d35382204f1d2f7f99d783988e37. Targeted verification only. |
| verified-final | 1693 passed / 0 failed; pytest298.75s, runner299.76331656146795s | First frozen affected regression,831 stable sources SHA117fe2a2ae0be1e70db5f0690ed03df70051d35382204f1d2f7f99d783988e37. Original1671 plus22 new. Final contract audit then found supplementary metadata missing on manually built C1/BODY_PACKET checks; this immutable green run cannot verify the later field completion. Final checkpoint uses a separate verified-final-receipts directory. |
| receipt-fields-red | 3 passed / 6 failed; pytest6.96s, runner7.702088792808354s | Independent assertions strengthened only the new9-item file; same item identities. All failures observed KeyError root_source in manually built C1 check receipts.831 stable sources SHAc2db6cf938c7fb04603de4d722a984d37dcc74094506d44c911390a0ea76b681. No old test edited. |
| receipt-fields-repair | 9 passed / 0 failed; pytest6.90s, runner7.688223986886442s | Four manual check branches now include receipt fields. C1 uses the exact candidate choices used by its binding, not merely the enclosing route choices.831 stable sources SHA1c0c38b00f9ce7b510a9fc52640272e1178bd064e7410e163479865c7d7f68ec. Final affected regression runs separately on this source. |
| verified-final-receipts | 1693 passed / 0 failed/error/skipped; pytest300.30s, runner301.3771510431543s | Final affected regression on831 stable sources SHA1c0c38b00f9ce7b510a9fc52640272e1178bd064e7410e163479865c7d7f68ec. Original1671 exact identities plus22 authored items. This is the checkpoint source; not full regression, not native execution/automatic recovery or LeWM speedup. |

First-red-static ran against 824 stable sources, SHA
`d0230ae487669552fa6810291267ed774b025dd8f530feebd5fc617e4a27b2d2`.
C's temporarily frozen parent-program/execution drafts were hashed but were
not imported or executed in this static-only attempt. This failure does not
yet constitute runtime evidence of the product continuation gap.

Finite independent source review additionally identified and repaired two
three-valued joins: unknown root preservation cannot grant OVERRIDE or cancel
completion extraction, and failed/unknown delivery cannot lend a DECLARED
consumer to that outcome. Two additional independently authored boundary items
exercise those relation inputs without mocking structured_completion itself.
They are explicitly controlled join tests, not automatic source recovery.

Dynamic review additionally required explicit unsupported-source, next-Drive
and intervening-call boundaries. The actual cursor now checks exact per-segment
Drive association/outcome in addition to transfer/ResumeIngress. No native
identity or transformation authority is granted by those declarations.

Every run has its own original command, stdout/stderr, JUnit, result and before/
after source registries. No historical attempt or old fixture/test was edited.
