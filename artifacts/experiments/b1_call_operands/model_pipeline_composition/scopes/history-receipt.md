# Composition-scope focused history

This receipt records the owned focused test attempts. Earlier raw outputs and command files are retained in their original `attemptNNN` directories; no failed attempt was overwritten.

| Attempt | Result | Notes |
|---|---:|---|
| 001 | collection error | Initial import failure (`ObservationConsumer` was imported from the wrong module). The original command/output are retained. A source hash and reliable shell exit code were not captured at the time. |
| 002 | 3 passed, 5 failed | The assertions treated the contract as having only one obligation; the canonical fixture declares both an output and a required facet. This was a test expectation error, not a validator/model failure. |
| 003 | 8 passed | Updated assertions to distinguish output and uninterpreted-facet obligations. |
| 004 | 8 passed | Refined scope correspondence checks. |
| 005 | 9 passed | Added the empty-scope unresolved case. |
| 006 | 9 passed | Added current actual/interval and external-artifact checks. |
| 007 | 9 passed | Rechecked after exact `ObservationConsumer` variant matching. |
| 008 | 10 passed | Added a valid three-requirement/three-root case that exhausts the shared budget during the second requirement group; verifies the cursor identifies the current requirement and the unvisited later group. |

Attempt 008 used `conda activate lewm`, `PYTHONDONTWRITEBYTECODE=1`, and `PYTHONPATH=.`. Its exact command, raw output, exit code, and four owned source hashes are preserved in `attempt008/`.

## Frozen owned-file hashes

- `scar/ir/execution/composition.py`: `6190ab8faa17c4b2823a061ce5179fb850fa9dd32c77806f04bc478052171852`
- `scar/ir/execution/composition_requirements.py`: `7f3c536a36ddcc905a0200c440c2e2d62660aba49fd1be3104bd9de7893da601`
- `tests/fixtures/execution_composition_scopes.py`: `af07ffb38760a981e9594783482da6afb3e0b1436c7a77c8315d16c69b0a103b`
- `tests/unit/test_execution_composition_scopes.py`: `2accdc3ee3992892fba56f5f97bc71dddf457ee3eb7e4b4785e3a3cc2d2d080e`

`git diff --check` passed for these four owned files. This focused validation does not establish broader resource/composition behavior or source/runtime correspondence.
