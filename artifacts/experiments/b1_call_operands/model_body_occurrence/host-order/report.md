# Owned P3 host-order implementation receipt

Status: **FROZEN — bounded focused PASS**, not whole P3 or full-regression PASS.

## Exact commands and attempts

Each attempt used the following activation and runner, with a unique output
directory; original stdout/stderr, JUnit, return code, elapsed time, before/after
registered-source maps and changed_paths are preserved in that directory.

```sh
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python \
  artifacts/experiments/b1_call_operands/model_body_occurrence/run_focus.py \
  host-order/attemptNNN tests/unit/test_execution_body_order.py
```

| Attempt | Actual result | Attribution |
| --- | --- | --- |
| 001 | exit1, 10P/1F, pytest1.59s, wall2.202s | New mixed fixture reused one caller-token Use in both INVOKE edges; original `control_binding` correctly rejected. |
| 002 | exit1, 10P/1F, pytest1.56s, wall2.168s | New fixture sent a recovery edge into the NORMAL private landing; original `completion_private_target` correctly rejected. |
| 003 | exit1, 10P/1F, pytest1.56s, wall2.192s | New unit called nonexistent `ProgramGraph.validate`; replaced only with the actual `program.validation.validate` API. |
| 004 | exit0, 11P, pytest1.69s, wall2.385s | New file passed, including actual core-valid mixed cycle. |
| 005 | exit0, 26P, pytest1.96s, wall2.657s | Same 11 plus 15 existing `test_execution_call_order.py` compatibility cases. |

Attempt005 appended `tests/unit/test_execution_call_order.py` to the exact
command above. No product guard or expected negative assertion was weakened.
The product host implementation did not change during these fixture corrections.

Final attempts004/005 both bind registered-source fingerprint
`4f661fb79c895639eaa067b0c5b0c7f93d5f8a1347182acdb140f92a8f99ed4b`
before and after; `source_unchanged=true`, `changed_paths=[]`.
Earlier attempt hashes and failures remain in their original directories.

## Frozen owned files

| File | SHA256 |
| --- | --- |
| `scar/ir/execution/host_order.py` | `c4578ff1cf51b7ac922453a8e89e951a5c2393ac63d4817ebaa8bd029e659a91` |
| `tests/fixtures/execution_body_order_graphs.py` | `c9c09b093497be480de398c405629c50b10ca9120d384062615ec91ad23b17c1` |
| `tests/unit/test_execution_body_order.py` | `435ddfe03e53330940cefff164a48773f2d0d6d6535a0594e3d01d9f824ea610` |

## Implementation boundary

`prepare_host_order` consumes root's already checked per-endpoint body view.
Entry and completion eligibility are independent. The completion bridge targets
only the taken BodyDrive EDGE and retains canonical missing-path support.
`host_cycle_errors(ctx, *, budget=None)` checks the union of original CALL
bridges, body bridges and compressed actual local chains with one Kahn scan.
It permits repeated persistent activations, preserves parallel-edge counts and
never adds an endpoint-pair Cartesian product.

Default cycle validation is finite canonical preparation with explicit counts;
query calls can supply their existing ValidityBudget, with no hidden allowance.
Exhaustion yields None/PARTIAL plus `host_cycle_unresolved`, not an acyclicity
claim. Snapshot/FK/container/detach costs remain outside derived traversal costs.

No native source applicability, object identity, whole-body termination, GPU
completion, content visibility, free, flush, persistence or transformation proof
is granted by these conditional host edges. No full/component/GPU/LeWM workload
or OS witness was run. Root owns complete integration review and remaining P3
validation/query acceptance.
