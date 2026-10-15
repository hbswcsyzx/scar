# N2.call-source-seeds.D0 independent criteria report

Status: **PASS**

Revision: `0f42d5f606878596966ea4ec833f9d06bec96621`

Source digest: `8aa53b4f2c6a7480aafca90b67db247f38a1b2deb1ca623dcea649ced639f37e`

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
