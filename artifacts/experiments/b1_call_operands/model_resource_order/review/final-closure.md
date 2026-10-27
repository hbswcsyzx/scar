# R2.2 order-layer independent review — final closure

Date: 2026-10-18 UTC  
Worktree: `/tmp/scar-structured-model-280qf4mi`  
Reviewed base/head at start: `9c7a91392751f6623073e2099baae4b6408c41bc`

## Scope and result

This was a bounded review of the R2.2 conditional order validator and query:
exact event-generation linkage, wait-state selection, queue-prefix/FIFO edges,
combined cycle detection, external queue scope, endpoint lookup, and whether
queries add runtime or transformation authority. I did not run native/GPU work,
LeWM, full regression, or a gate. No product files were edited by this review.

The root-reported component result is **497 passed / 7 criteria / 9.382 s**;
source fingerprint `10e12c818eb8c8adaeb3a4e0e4cf4dd4927137f568da590b02f648e013c4a3e5`.
This is root's broader component result, not a test run performed here.

## Findings checked

- Event generations are selected from the marker's original `AccessRef` or a
  validated `InvokeBoundaryStateEffect`; the event resource access must point
  back to the matching static resource use/location. A wait names an exact
  `EventRecordID`, compares its selected state against that record's generation,
  and cannot retarget when the event is recorded again. A known different
  recorded generation is rejected; an unassociated intervening state remains
  a gap.
- The earlier bare-INVOKE concern is closed in the reviewed validator: an
  `invoke_arguments` state operand alone does not authorize the wait edge. For
  an INVOKE wait without a matching `InvokeBoundaryStateEffect.state_input` in
  that work ticket, the validator records
  `wait_selection_read_unresolved` and emits no event-wait order edge. Ordinary
  operations still require the exact original READ/READ_WRITE
  `StateAccess.before`.
- Queue completion and consumer start remain distinct. A wait orders the wait
  work's end after the event signal; FIFO can then order a later work's start.
  A prefix that merely includes a consumer does not create an edge to that
  consumer's start. The test `test_event_wait_can_constrain_wait_end_without_constraining_wait_start`
  exercises this distinction.
- Same-run work in two processes sharing a declared external queue produces a
  scope gap and no conditional cross-process work-order path. A prefix/FIFO
  chain that attempts to connect two known runs produces an order run-scope
  issue and no cross-run FIFO edge.
- FIFO, explicit dependencies, prefix frontiers, event capture, and event waits
  enter one combined cycle check. `order_path` accepts only typed existing
  endpoints and reports `CONDITIONAL` or `UNRESOLVED`; returned query records
  keep runtime-order/source-runtime/transformation flags false.

## Review probe record

Command:

```sh
source /home/zyf/miniconda3/etc/profile.d/conda.sh && conda activate lewm && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python -m pytest -q tests/unit/test_execution_order_review.py
```

The first run was **2 failed** because the adversarial fixture moved the second
activation to a new process/run but left its `ExecutionSegment` ingress at the
old process's `InitialEntry`. This was a fixture construction error, not an
order-validator result. The failure log is preserved at
`review/attempt001/output.log`; its note records this distinction.

After setting the cloned segment's `InitialEntry` to the matching point, the
focused review probe passed **2/2 in 0.43 s**. The exact command and output are
preserved at `review/attempt002/command.sh` and `review/attempt002/output.log`.

## Reviewed file hashes

| File | SHA-256 |
|---|---|
| `scar/ir/execution/order_validation.py` | `e26435e2ddbf71d7276e9ece32875f24983cbbbcb470ec973fa330437e1057ba` |
| `scar/ir/execution/query.py` | `4a45323b4f213ac5fd86f2a9054f6adc1a9371fcee0414ee44348cf0505aee72` |
| `scar/ir/execution/validation.py` | `6c167f7a3594bcc2e6c8872520e1b14f7c453d7f3439026028a36343e6b48f2d` |
| `scar/ir/execution/work_validation.py` | `7494f8e16a3cf8d6b91224e1f75f3c4fa7f14c1a43a361fbc5818948baf7852b` |
| `scar/ir/execution/order.py` | `e4ce65c33bb8169e643eb5bebd8bf5f3620d8d2cc5c8d333b62b52e2e4aea43a` |
| `scar/ir/execution/model.py` | `6d592afa5a7b8f9eab774c41f52322da6ad742c405a03e2f8448e06afdd1dd92` |
| `tests/fixtures/execution_order_graphs.py` | `d4e21e8c63ebdb279bafae66ce14b5f78b917f05d3d1e37e3c56b94a2a203e2a` |
| `tests/fixtures/execution_work_graphs.py` | `7428d0bd7a1597232d49587d5378cce3b4fae077a306d51d474e8d46e6aec60f` |
| `tests/unit/test_execution_order_graphs.py` | `9e12801664040125006d751f50ae91147a43d95d1c539969e3170d63995f1ab7` |
| `tests/unit/test_execution_order_queries.py` | `ee27b9a8dba9b1816f92e92fed4f3c9e54816fd2ebcbde0f19a37bb86ebc27a1` |
| `tests/unit/test_execution_order_review.py` | `36b23327d1a6262f8a39bb86f2c5244ad9c637c973b1f2f32e03ab2c3266f0fd` |

This review establishes structural consistency for the checked declarations and
queries only. Protocol applicability, native event behavior, actual queue
ordering, readiness, host visibility, and transformation authority remain
unverified.
