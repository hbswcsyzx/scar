# W2/W3 windows GPU public CLI acceptance

Status: **W2_W3_PUBLIC_GPU_PASSED**. Frozen HEAD `8a300eb068d992b3737eee0bdf43fa2bf8c8aea1`, source fingerprint `38dfe6c34545b405fa5e8f08e2828f7357c862527500a6a1f2b3d97072796574`. Source fingerprint matched at every check; Git HEAD/status were identical and clean before/after.

## W2: old rule replay

The new public `check-operand-links` independently rebuilt the original stable `generic_gpu/reports/operands.json.gz` with its `CPYTHON_LOAD_OCCURRENCES_V1` rule, exit 0. The entire original artifact tree, including its sources, raw records, inventory and report, was hashed before/after and is byte-for-byte unchanged. No old report or input was rewritten.

## W3: new original CUDA/autograd program

Copied the original two-file choose/relay/run source into the new stable `inputs/project` and adapted only the driver's path. The raw program ran with distinct and shared CUDA leaf Tensors (`requires_grad=True`), returning the left object and actually executing sum().backward(). left.grad existed on CUDA and did not require grad; distinct right.grad remained absent, while shared inputs referenced the same object and grad. No Tensor values were saved.

Public trace used explicit `--call-operands --operand-capture windows`; inventory-program --calls, link-operands, check-operand-links and both query-operand-refs calls all exited 0, with empty stderr. CPython 3.14.7; PyTorch 2.13.0+cu132 / CUDA 13.2; NVIDIA RTX 4090 / driver 595.58.03.

- Base: 26 events, 13 invocations, 12 code descriptors. Window sidecar: 48 events, 32 instructions, 8 attempts, 8 handshakes, 24 load occurrences. Both collectors report zero drops/errors/gaps.
- Automatic v6 inventory and source/core routes retain four choose invocations and eight parameter routes; each pair has two distinct Uses and LOAD occurrences.
- Distinct query: run 4 -> relay 5 -> choose 6, excluding sibling relay 7 / choose 8. Shared query: run 9 -> relay 10 -> choose 11, excluding relay 12 / choose 13. Each sole endpoint is its own run.x.
- Each query retains all eight conditions, frame obligations and an ARGUMENT_ROUTING_UNVERIFIED endpoint for the external driver. Environment, contents/effects, world equivalence, transformation authority and whole-program completeness remain false.

## Acceptance cost

Fourteen commands all exited 0. Total command wall time 21.165 s: old replay 0.966 s, untraced micro-run 2.620 s, traced run 12.838 s, inventory 0.766 s, link 0.916 s, check 0.966 s, queries 1.066 / 0.916 s. Traced peak RSS 810,944 KiB; per-phase /usr/bin/time -v logs and exact argv/env/cwd are preserved. Torch peak allocated 2,560 B, reserved 2,097,152 B. These timings are acceptance costs, not workload acceleration evidence.

See receipt.json and result.summary.json for exact costs and states. The manifest directory preserves original-input before/after hashes, every source fingerprint, new raw hashes, and the join proving that every protected raw file still matches its public report SHA. logs contains all stdout/stderr/time-v files. No product, test, documentation or LeWM file was changed; the LeWM acceptance remains separate.
