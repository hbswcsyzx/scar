# Design review: original call path composition

2026-10-18. Base ea13ecf; model is Operation/Value/StateLocation/Region/Resource.
This checkpoint extends exact original-port queries, not the wire or backends.

Three explicit review assignments covered: (1) call order, input/CFG context,
all-route denominator and reporting; (2) independently reproduce a missing
route or copy false proof; (3) separately versioned state, N/R and future-result
rejection. Test authors did not execute test suites; root ran attempts serially.

Frozen plan: docs/M1_CALL_COMPOSITION_PLAN.md, SHA256
62d0417ebf8a6a65b8c134d583e6fe30ddd5770fa606ca78e49f8ad65e98729c.
Original P4 F12-F24/X25-X27 denominator is unchanged and remains all OPEN.
No component/full, new detector/backend or LeWM benchmark is part of this gate.

An actual valid-core missing-input-route counterexample required diagnostic
inventory completeness and gap propagation. These are derived query fields,
not a new producer relation, runtime identity or source applicability grant.
A completed recipe cannot stand in for an omitted input alternative.
