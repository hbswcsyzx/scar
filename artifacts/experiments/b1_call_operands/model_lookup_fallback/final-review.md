# Bounded pre-acceptance source review

All authors are frozen. Three independent read-only reviews checked source,
packet/current-copy roles, C1 boundaries and codec/profile isolation. Reviewers
did not run tests; root owns the sequential evidence execution.

Final reviewed product hashes:

- lookup_fallbacks: 5288397ec6659022499276815343caf26dd19056b55e12ddf86b3908616685ed
- packet_routes: 455b9d33007f746b8b8a557c19a0a488ed8040c2f71386decc2e2d85f04b6a1f
- continuations: 64b5a4e1953c7913ddb8e8883d81159563d7c7aa27f10bab70f1d4a06f75d69e
- codec: 2ca1c589997ca4efdec69a4fcc1bab68d32b8413d7386aa5bee1deab4478bf5d

## Findings and disposition

1. Actual lookup matcher connection lacked the three independent fallback
   routes: reproduced 1F through the existing API, then implemented.
2. Sibling lookup rejected under source/packet codes but lacked the precise
   site code: first-connected 23P/1F, repaired and rerun 24P. No test weakening.
3. Reference masquerading as RAW_DRIVER_REQUEST was washed into an unresolved
   external-source gap: reproduced 1F, now rejects the known wrong role before
   raw-definition lookup. A genuinely unknown RAW origin still remains a gap.
4. Treating mutually exclusive receiver cases as one conjunctive tuple is a
   design risk. The concrete local merge positive passed before the change
   (1P in red-raw-and-case-review), so it is not a reproduced semantic bug.
   Complete input jobs now correlate within each case; all cases are retained.
   Cross-callee reproduction/closure is not claimed by that local positive.
5. Full binding tables were scanned for every lookup. One prepared site/matcher
   index now replaces those repeated scans and reports preparation counts.
6. Source-port budget exhaustion could be read as an ineligible site. A
   truncated resolution now stops without a false contradiction; a direct
   budget-one regression retains that distinction.
7. C1 fresh replacement alone cannot prove source applicability of finally.
   Override support retains applicability=False and explicit override plus
   continuation gaps. Dead packs do not discharge the active-token obligation.
8. Boundary-and-codec initial 81P/3F retained. Two failures were incorrect test
   fixture assumptions (a copied formal is not its producer ValueID; an
   incomplete JUMP remains opaque). Tests now use exact copy proof and start
   at the actual C1 frontier. The nested unknown E0 failure exposed a missing
   local gap; product now emits it, preserving the existing generic route gap.

All route reports are frontier-only. Unknown calls, original back-edges,
reevaluation and missing bindings preserve explicit gaps. Native/category,
normalized source and whole C1 continuation remain unproved. No new rule or
backend targets a workload. All sixteen original P4 groups remain OPEN.

This review permits one unified affected-focused execution, not component/full
or complete M0–M2 acceptance. The final run supplies its own source fingerprint.

Post-review archive note: first unified final-focused passed 965 cases at
eddce685c7747a84d531fdf8c0776f8134aa0570b9d67f5181cdf8b67ff4b698.
The cached whitespace check found one extra empty EOF line in the new edge
test. Root removed that one empty line, changed no assertion or product code,
retained the original pass and checkpoint-initial.json, and reran the same
affected selection to bind the final source. final-focused-repair passed 965
at d98ca13fc57cbd97185ecdbf45ece875918d26f1b1dd7b8068e7b9d97805179e
(713 sources, before=after; no failures/errors/skips). Product review hashes
above remain unchanged. This is neither a component nor a full run.
