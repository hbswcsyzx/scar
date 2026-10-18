# R3.1 call-boundary regression closure

This supplements, and does not overwrite, `core-author-review.md`. It records the
independent boundary matrix for the two final validator guards. It is not a full
repository or runtime acceptance report.

## Reviewed snapshot

| File | SHA256 |
| --- | --- |
| `scar/ir/execution/call_validation.py` | `79febd82eea06447ad045e8302a62a17164bb04771c9a2ef852b28640a127f4b` |
| `scar/ir/execution/calls.py` | `a287446babd077c072f51182d12ecc5e670bd2e1700b6396e914e134d95a183f` |
| `scar/ir/execution/ids.py` | `3d5097166d01f177ec7295e74b74567c0a93ef2482cd371138d3e23578df7d29` |
| `scar/ir/execution/model.py` | `14a28d9531b744924e24ba1633b691cdb91019e37829665e5f711369c7f2a126` |
| `scar/ir/execution/validation.py` | `e3a440dc32c4aacba3b4a53b536d11341c0892a4bb5dda08007448bc5dba395d` |
| `tests/fixtures/execution_call_graphs.py` | `6fa0d2eca706edc3a371d4d8d8581973b7e28b94ce5623e89048789e3fc8c90b` |
| `tests/unit/test_execution_call_boundary_review.py` | `2214e4f0678ed22c282edd38431b6f5b3a85ab89c65102c25b148f6c50e99558` |

## Boundary evidence

`tests/unit/test_execution_call_boundary_review.py` passed **10 tests** in the saved
`boundary_calls/attempt001` run. The saved command used CPython 3.14.7 in `lewm`, with
`PYTHONPATH=/tmp/scar-structured-model-280qf4mi` and bytecode writes disabled. The exact
argv, stdout, JUnit, source manifests, and report are preserved in that attempt
directory; pre/post source manifests have the same SHA256
`60d727f74fe34ac30da0f554aaa09222b2aba5cb4b1baa0eca96c7501c5489f8`.

The cases establish these structural outcomes:

- An unresolved child entry does not hide a known caller-versus-completion-thread
  mismatch (`call_thread`). An unresolved caller thread also does not hide two known,
  conflicting child segment threads (`call_thread`); missing thread identity remains a
  gap.
- A linked synchronous child with separately captured RETURN and RAISE occurrences is
  rejected as `call_multiple_completion`, even when one occurrence is a disconnected
  partial fragment. This does not interpret that fragment as another execution.
- Caller and child-activation endpoints cannot be reused. Dynamic activation cycles are
  rejected, while static self-recursion through distinct activation IDs with a base-case
  path remains structurally valid.
- Distinct entry FactReferences, including a URI alias, do not imply distinct execution
  entries. A completion from another same-code activation is rejected.

These are hand-authored canonical execution relations. They verify the typed structural
guards; they do not demonstrate recovery from a real trace, native caller/value
identity, complete source coverage, runtime semantics, or permission to transform.

## Owned baseline runs

The preceding author report records four owned focused attempts: records-only attempt
001 (14 passed), combined attempt 002 (23 passed), combined attempt 003 (23 passed),
and combined attempt 004 after the final thread/terminal-index changes (23 passed).
Attempt 004's command, output, exit code, Python version, and hashes are retained under
`../core/attempt004/`. Its baseline validation test file did not itself contain the new
thread and multiple-terminal cases; those are independently exercised by the 10-test
boundary file above. Historical attempts without their own source-hash manifest remain
without a reconstructed hash.

The implementation pre-indexes child segments and terminal occurrences once and uses
iterative visit-chain and call-cycle traversals. This complexity note applies only to
those new indexes/traversals, not the total validator or the other execution checks.
No full-suite, LeWM, GPU, or target-program execution was run for this closure.
