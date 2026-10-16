# N2-CALL-OPERANDS-B1-COMPONENT independent criteria report

Status: **PASS**

Revision: `6a7410d6049390dbc78167a9af0d3a7c00e5ed58`

Source digest: `33d92b1635ac614ab817388dbeb45cda5fe6f71a6af99b115193e473582d1933`

| Criterion | Status |
| --- | --- |
| B1-A-bounded-wire-and-independent-reader | PASS |
| B1-B-original-program-collector-lifecycle | PASS |
| B1-C-position-sensitive-routes-and-control-boundaries | PASS |
| B1-D-public-command-query-and-tamper-replay | PASS |
| B1-E-bound-inventory-raw-and-decoded-ceilings | PASS |
| B1-F-legacy-frame-and-source-link-regression | PASS |

Scope: Automatically capture original two-file programs, bind supported positional Name-call actual occurrences to formals and normal completions, and query the exact upper-level reference through public CLI replay.

- This is component acceptance only; full regression, persistent external GPU evidence and a new unchanged-LeWM capture/analysis remain required before B1 end-to-end acceptance.
- Routes remain conditional on source and monitoring observations; reference provenance does not establish tensor contents, function environments, effects or world-state equivalence.
- Receiver/default/pack binding, dynamic control selection, loop-carried state and complete whole-program graphs are not delivered.
- No new detector/backend, LeWM-specific rule, transformation or measured LeWM speedup is delivered.
