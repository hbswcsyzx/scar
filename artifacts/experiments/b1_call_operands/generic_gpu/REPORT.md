# B1 generic CUDA/autograd public CLI experiment

Status: **PUBLIC_PIPELINE_PASSED** on frozen commit `c91876b73ed7b15351a0cb925d17c2e017d2c88d`; the worktree was clean before and after.

The original two-file project contains `choose(left, right) -> left`, `relay(a, b) -> choose(a, b)`, and `run(x, y)` making two reversed relay calls and returning the first. The driver uses distinct then shared CUDA leaf Tensors with `requires_grad=True` and actually runs `sum().backward()`.

## Observed

- CPython 3.14.7, PyTorch 2.13.0+cu132, CUDA 13.2, NVIDIA GeForce RTX 4090; driver 595.58.03.
- Both modes returned the left object. Backward succeeded and left.grad was present on CUDA. Distinct right.grad remained absent; shared right was the same object and shared its grad. Only reference and gradient state metadata was saved, with no Tensor values.
- Public commands `trace --call-operands`, `inventory-program --calls`, `link-operands`, `check-operand-links`, and both `query-operand-refs` calls all exited 0; all stderr logs are empty.
- Both independently replayed queries reached only their own `run.x`, through exactly one relay and one choose completion, without visiting the second sibling call.
- Four choose invocations retain eight actual routes: each pair has separate core Uses and LOAD occurrences.
- Base capture: 26 events, 13 entries, 12 code descriptors; sidecar: 87 events, 71 instructions, 8 attempts, 8 handshakes. Both collectors report zero drops/errors/gaps.

## Spend

- Command elapsed total: 20.236 s. Original micro-run: 2.621 s; traced run: 12.995 s; the difference includes collection overhead and separate process startup.
- Raw files: 61,086 bytes. Inventory, operand report and two query documents: 129,691 bytes.
- Pipeline children: 19.984 user CPU seconds, 1.914 system CPU seconds, peak RSS 812,984 KiB. This CPU measurement excludes the earlier micro-only runner process.
- Torch peak allocated: 2,560 bytes; peak reserved: 2,097,152 bytes. nvidia-smi reported 1,367 MiB in use before and after, including unrelated GPU allocations.
- Capture ceilings: 100,000 base events / 64,000,000 base bytes; 100,000 operand events / 32,000,000 operand bytes. Offline report budgets retain the independent public CLI defaults and are bound in the saved report.

## Boundaries

Queries stop at `run.x` with `ARGUMENT_ROUTING_UNVERIFIED` for the external driver caller. Every route retains eight explicit conditions, including `MONITORING_DELIVERY_CONTINUITY_UNVERIFIED`. Function environment, contents/effects, world equivalence, and transformation authority remain false; whole-program completeness remains false. This is a real small GPU/autograd fixture, not LeWM or whole-program acceptance.

`receipt.json` contains exact argv, absolute cwd, exit codes, times, runtime states, input/raw/report SHA256 manifests, and source freeze checks. `logs/` retains every stdout/stderr. `manifest.json` hashes all retained files except itself. The raw trace is unchanged. No product source, tests, documentation, or LeWM files were edited.
