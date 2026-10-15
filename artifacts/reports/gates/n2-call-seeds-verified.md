# N2.call-source-seeds.D0 independent criteria report

Status: **PASS**

Revision: `39e8f2219d0883c2b1a74218527607ba61ea2286`

Source digest: `81d6a6b675055eaa70a8e4dff566107dc3329859e999e7f918050bd983c26909`

| Criterion | Status |
| --- | --- |
| D0.raw-stream-validation | PASS |
| D0.typed-compact-records | PASS |
| D0.real-capture-source-replay | PASS |
| D0.public-cli-budgets-and-preservation | PASS |
| D0.legacy-call-witness-and-reference-replay | PASS |
| D0.legacy-public-interfaces | PASS |

Scope: Strict streaming raw call validation and compact entered-code/source seeds; no inventory scheduling, actual-formal binding, effect equivalence or transformation.

- D1 inventory demand integration is not implemented by this gate.
- Code/source identity does not establish a function instance or its environment.
- No caller/value/effect connection or LeWM acceleration is certified.
