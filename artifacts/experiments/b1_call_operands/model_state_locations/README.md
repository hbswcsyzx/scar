# S typed state-address gate archive

Scope: owner/selector refinements on original canonical state carriers and actual
operand/completion occurrences. Complete M0–M2, native address/alias interpretation,
automatic program recovery and LeWM simplification remain open.

Implementation: `805c670a12ea15cf12b32395180c8fcd954beda2`.
Registered source: 590 files, SHA256
`b0a340543b4015b903196f1cb5f0ffe202d864a57e56382ef674896310c95ef1`.

- Component: 1,317 unique cases /25 criteria, PASS, 44.578 seconds.
- One clean frozen full: 5,144 passed, zero failed/error/skipped, five warnings;
  wall516.7538779713213s, maxRSS1,026,572KiB. This is acceptance cost, not speedup.
- Original5,055 case identities and72 fixtures preserved; current74 fixtures.
  Old578 sources:566 unchanged,12 extended;12 new registered files.
- Before/after source and protected checkout receipts agree. The owned full-run
  basetemp was removed only after all driver child processes terminated.
- All agent writers stopped before full. No concurrent SCAR tests/profilers,
  source/docs/report edits or automatic retry occurred during the full run.

`design/` contains three independent design audits and a compile-only 15-snippet
literal probe. It does not execute the target snippets. `address_records/`,
`codec_queries/`, and `dynamic/` retain every original attempt and final receipts.
Early failing attempts remain, including invalid test signatures correctly rejected
by the old validator. The independent `review/state-addresses.md` preserves its
initial OPEN, corrections, withdrawn compatibility inference, D01–D10 mapping and
PASS_WITH_SCOPE. Twenty alias mechanisms are not twenty runtime PASS cases.
Two new-unit EOF blank-line style warnings were retained without changing the
accepted source; all old semantic/golden assertions survive the six mechanical
highest-supported-schema updates.

`component/final/` is the exact 25-criterion report. `full/` holds the immutable
driver, command/environment, logs, JUnit, individual cases, source snapshots,
resource measurements, process/cleanup evidence and manifest. `preservation.json`,
`closure.json`, `protected.*.json` and the top manifest bind the final archive.
The current API/plan/acceptance and five progress documents are hashed in closure.

With conda lewm active, run `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python
artifacts/experiments/b1_call_operands/model_state_locations/check_archive.py`.
The checker starts zero tests/profilers/workloads. It validates all archive bytes,
current source/fixtures/documents, frozen implementation ancestry and old-case
preservation; it does not repeat the full regression.

No new detector/backend, special LeWM rule, source-runtime/value identity proof,
transformation authorization or workload speedup is claimed by this archive.
Next: reuse PythonLiteral for precise scalar/complex payloads, bounded validation,
core wire and explicit source/identity boundaries; then C2/D3 and M2 obligations.
