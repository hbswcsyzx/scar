# R3.1 canonical call fixtures

Owned new file: `tests/fixtures/execution_call_graphs.py`, SHA256
`6fa0d2eca706edc3a371d4d8d8581973b7e28b94ce5623e89048789e3fc8c90b`.
Frozen after the five-variant smoke. No old fixture, product or test file changed in this
fixture batch. These are complete hand-authored canonical declarations, not runtime recovery.

## Stable factories

- `shared_calls_execution() -> (program, model, details)`: unchanged canonical
  `shared_body_calls_program()`; one caller activation and two distinct child activations
  for its two ordinary calls to the shared callee. Each activation has its own real
  InitialEntry visit, operation/value/Use occurrences and current states. Two CallActivation
  rows select the exact declared children; no source/name/static-callee matching.
- `invoke_call_execution(*, raised=False, caller_transfer=True) -> (program,model,details)`:
  ordinary non-resumable two-exit child, real child branch and RW state transition before
  actual RETURN/RAISE; caller INVOKE has matching completions and independently permuted
  result-slot→landing-formal order. NORMAL signature is `(reference,state)`, RAISE is
  `(state,string)`; both landing argument lists reverse the result slots. This exercises
  actual CompletionResult routing, not positional guesses.
- `caller_transfer=False` omits the caller's transfer, landing visit/formals and terminal
  occurrence, while preserving the child's actual completion and association. No default
  NORMAL result, common INVOKE AFTER, synthetic producer or absent-effect conclusion.

Both expose `callers`, `children`, `links`, `entries`, `completions`, `caller_activation`,
`caller_entry`; `caller` is the first/single caller occurrence. Invoke also exposes `child`,
`link`, `normal_target`, `raise_target`, `taken_target` (None without caller transfer), and
`caller_transfer`. Root/query tests can derive everything from canonical records instead.

## Preserved attempts

Command for both attempts (conda lewm, Python3.14.7, no bytecode):

```sh
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python artifacts/experiments/b1_call_operands/model_resource_composition/call_fixtures/smoke.py
```

`attempt001`: original ignored runner failed before printing its first case because it
treated program `validate()`'s tuple as a report with `.issues`. Original stdout/stderr,
command and before/after source hashes remain; **not a product or fixture failure**.
Only the ignored runner's handling of the core return API was corrected.

`attempt002`: exit0, child wall **0.61232985s**; all five program/execution graphs have
zero structural issues and exact v7 codec roundtrip. Shared graph has14 gaps; each complete
INVOKE graph10; each missing-caller-transfer graph11. Missing source/runtime pairing and
partial-capture gaps are intentionally retained. This is a small smoke, not five pytest
cases, a frozen component gate, or an independent review of call_validation.

Ignored runner SHA256 `2d69558791dc464cca613e5774e082359ae0e5cbd4525dae23bd8147e0afd03e`.
Current call validator was still under root development; its smoke-time SHA was
`2ec40356d5bc4238a3d5bada4468c6e7df3686d074f76a7facffc2dd119559e2`.
Later root graph/query tests own their results. No full/LeWM/GPU test or runtime capture ran.
