# Source freeze and bounded independent review

Base cd25456357ec3e569d32ad246bd5890ef8fc628f. Three independent read-only
reviews have closed the finite source/fixture review; all authors are frozen.
Only root starts sequential tests. Reviewers did not execute Python/probes/tests.

Product hashes:

- pending_payload_flow: b1230cc9757844ab22a476b6025a8785f6a13aad42b79fe2350c6493ff6f3037
- protocol_flow: a2c219d06ef83b8f92aa68ec1e5b4943e3202c3d11e52b9130c1032bc6ac6f03
- input_origins: 1c3ccb3010b42bebf8081f0ebb5bc760c1893bba1a4c8e424d6e9dc8575aae98
- generic fixture: b4063333ae7363206fa34cdb40d489e523c5be66ee35ed52f995510756dff9e4
- generic tests: 6187d751e1b73db3b19039bd4c37fc395ce224fe6d440a3a2eb1253abf62e232
- C1 fixture: ba66ebbfa257f0ff8d78c5bf25fa9eb8db8516a572573b8ac01e73461cc07e51
- C1 tests: ed5ed97fc5894522e7b9c03e27aab9db09f3cba80e990bdbd6e98aea99e3c2b8

Checked invariants: independent possible/support domains; same-port all-incoming
meet and different-port filtering; no vacuous port success; source reset keeps
old-token possibility while clearing its source-relative support; constructor
reset preserves other old carriers of an unchanged immutable payload. Existing
current-copy, must/may, call-return/cache and shared-budget contracts remain.
No new wire/producer/state graph or workload rule is introduced.

Origin witnesses retain actual selector/port/ordinal/formal, original definition
and constructor/payload OwnedUse, original token/CFG/caller paths. Static cycles,
unresolved token origins and truncation retain the missing-route denominator.
A naked PendingPayload marker is not accepted as an owned source. Private tokens
remain prohibited as arbitrary CALL/INVOKE actuals.

Both C1 graphs contain two real Detach/Suspend/Attach cuts. The RAISE example's
new packet is generated after cut one and held only by the fresh pending across
cut two. The normal example's old Return payload predates both cuts and crosses
both to the exact terminal. No packet is fake-saved as VALUE; old caller is not
saved, world/context use new ResumeInput, and current caller is rebuilt by Attach.
Guarded helper RAISE differs from the unguarded common host source inventory.

Observed attempts before final acceptance:

- red-original-projection: 1F, original valid graph/source_binding False.
- first-connected: 20P/4F. Two new different-port fixtures reused an exact state
  Use across edges; one C1 normal fixture guessed landing ordinals; one negative
  expected a late freshness code but core correctly rejected its port set first.
- repaired-core-fixtures: 25P/1F, remaining normal fixture passed a Value record
  where a ValueID was required. Product/semantic assertions were not weakened.
- repaired-normal-two-cuts: single required normal selector 1P after ID repair.

These counts are not added together as one run. All original failures are kept.
The final affected selection also includes original pending INVOKE and saved
forwarding/current-cleanup tests because those are concrete shared-flow risks.
Original965 obligations must remain unchanged; no migration is planned.

This review permits unified affected-focused execution only. It does not close
all sixteen P4 groups, complete X25 occurrence combinations, P5/M2 or M0–M2.
Source/native/runtime identity and transformation-authority flags remain false.

Final execution receipt: 1018 PASS, zero failures/errors/skips, pytest41.83s /
runner42.680510396137834s. Source718 before=after at
1b92351bac44522b6cbe84afeee1f3ed32eab4deed679c6260dec6da81df00fa.
Original965 obligations retain their exact IDs; new26 and additional existing27
are reported separately. This is affected-focused, not component/full or LeWM.

Archive first check caught one new attempt-ID rename when the old-RETURN-as-
RAISE negative was correctly reattributed to the earlier C0 port-case check.
archive-attempt001.json preserves that verifier failure. The explicit mapping
retains the same mutation and expected rejection; its target must belong only
to the new tests. All original965 IDs remain exact. No tested product/test
source changed and no tests restarted for this archive-only correction.
