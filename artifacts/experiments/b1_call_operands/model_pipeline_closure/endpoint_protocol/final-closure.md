# Endpoint coverage and selector closure

This is a bounded focused result for the endpoint byte profile and the current
pipeline compatibility tests. It is not a full component or full repository
result.

## Changes

- `validity_query._endpoint_coverage` charges endpoint offer checks, boundary
  construction, boundary sorting, and each portion-label scan (`1 + number of
  accepted offers`) to the caller's shared `ValidityBudget`.
- When the budget stops geometry work, the result is `UNRESOLVED`, with the
  required interval intact, the complete offered tuple retained, known prefix
  geometry retained, and a cursor for unvisited offers or portions. The outer
  validity status remains `TRUNCATED`. The default budget was not changed.
- `_coverage` reports a pending contribution-fragment range if its offer
  collection itself reaches the budget limit. The original contribution
  inventory remains available in the parent query result.
- `production_validation.produced_errors` retains the already-derived
  `actual_selector` from `resolve_actual_range`; work-produced V fragments can
  therefore use the original `RegionRef` or endpoint range instead of losing
  it.
- The same-version/different-materialization negative fixture uses a second
  endpoint materialization in the same ValueGraph and rebinds the model's
  references to that same artifact before changing only the read materialization.

## Verification

Command, run in the `lewm` environment with `PYTHONPATH=.` and
`PYTHONDONTWRITEBYTECODE=1`:

```sh
python artifacts/experiments/b1_call_operands/model_pipeline_closure/focus.py endpoint_protocol tests/unit/test_execution_endpoint_protocol.py tests/integration/test_execution_io_pipeline.py
```

Attempt 004 completed with exit 0: **26 passed**, one pre-existing pytest
`record_property`/`xunit2` warning, in 12.78 seconds of pytest time. The unit
tests verify both offer-scan and portion-scan budget stops, preserve the full
required interval and original offers, preserve the unvisited cursor, and keep
the public query status `TRUNCATED`. The pipeline case verifies a valid
work-produced `RegionRef` remains connected to validity. The integration set
covers the current multi-function buffered endpoint path.

Earlier attempts are preserved unchanged:

- Attempt 001: 10 passed (parser/profile checks).
- Attempt 002: 12 passed, 1 failed. The alternate-materialization test used a
  CPU storage materialization and correctly failed earlier with
  `content_endpoint_storage`; it did not reach the intended endpoint identity
  check.
- Attempt 003: 24 passed, 2 failed. It exposed the test's earlier Mat setup and
  incorrectly targeted a host `EstablishedProduction` as an `OutcomeProduction`.
- Attempt 004: corrected same-artifact alternate endpoint Mat and work outcome
  selector coverage; 26 passed.

## Source hashes at attempt 004

| File | SHA-256 |
| --- | --- |
| `scar/ir/execution/validity_query.py` | `cf1ff0f076939d04357cb64a2b03af5d77fb7aad7a1d9243465d2ad452ffea0c` |
| `scar/ir/execution/production_validation.py` | `63f55ef4c4270f137d62799874ee51b783f562fc5086005e3f1769e8571158aa` |
| `scar/ir/execution/endpoint_protocol.py` | `4b9cf7163c498ce85e654c3c1ff2ac863dab8efb9fae471bf07398535ed037fb` |
| `tests/unit/test_execution_endpoint_protocol.py` | `91aa0af9c7a8241fa3a820ceccf9cea48898a15a09850347166ea77a6110db3d` |
| `tests/fixtures/execution_endpoint_protocol.py` | `0208fa302ba3f520a6edd127ea73d0376ddaadb28a68d6f2a286ebadf5ff4894` |
| `tests/fixtures/execution_io_pipeline.py` | `42723a1144309cc544a39a71c78d364de922cd757a0fc0364fc7a8af3cc89c97` |
| `tests/integration/test_execution_io_pipeline.py` | `54ac956439232e9cffaa006485b248fa26a1a45003cd168ef70ffe5c4764fdf7` |

No full gate, LeWM workload, GPU run, or default-budget change is claimed here.
