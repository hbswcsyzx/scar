# D5 frozen review

Baseline: `287c906c95658d25200d057fe9002fc3d1f8479c`.
D5 contract SHA-256: `5f49d6efb28d2902d02800c986978b332312abe08890cbbf40aa51879dbcd07f`.
Original A–H and F12–F24/X25–X27 remain required and OPEN.

Before product changes, A/B/C independently read the original static and
execution queries and proposed no new wire records. Review did not execute
Python, tests, probes or workloads.

- A: use original exact advance CallActivation chain and BodyDriveExecution;
  never search the same static converter/extractor globally. Two instances
  with one exact consumer Use missing are a stronger valid counterexample
  than a cross-activation Use mutation already rejected by canonical validation.
  Keep converter NORMAL/RAISE, packet components, extraction NORMAL/RAISE and
  HANDOFF separate. Dynamic drive/body_outcome are original occurrences.
- C: source-owned failure must survive with no advance/body capture. Expanded
  terminal must be the exact source call's completion. Packet and state use
  that call's original outputs, with precise parent R slot/formal.
- B: NOT_APPLICABLE needs a captured negative choice; missing evidence is
  PARTIAL. Unselected legs do not poison the selected leg. Count checked parent
  anchors, not derived Drive route rows; all routes must be checked first.

Frozen-contract clarification agreed before tests: when static obligations
have not been fully enumerated, the global weighted occurrence_count and
pending_occurrence_count are None, with observed_occurrence_count separately
reporting captures attached to enumerated obligations. Per-obligation counts
remain original parent-site capture counts. No budget-free complete Cartesian
product is claimed. This does not change D5 bytes or original completion scope.

Ownership: root owns product and all serial execution. A/C own their new
fixture/test pairs; B owns only the new boundary test file. Existing tests and
fixtures remain byte-identical to the base. Authors freeze before each run.
