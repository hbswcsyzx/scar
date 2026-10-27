# Snapshot, native, and owned OS integration smoke

This is one small independent Python integration capture. It does not run or model LeWM and does not replace the open LeWM stage. The target creates a temporary input file under this artifact, constructs a 2×2 CPU tensor, copies it to CUDA, multiplies it, copies it back, writes a temporary output file, and checks the exact result `[7, 10, 15, 22]`.

## Actual capture

The immutable collector source was the frozen snapshot at `structured-program-model/artifacts/experiments/lewm_snapshot_ports_20261027/collector-source`, source tree SHA256 `17f64b651f02e40e500325277d261a7f6542b6cc375e1ae9c237f5fd3cb555c2` (snapshot commit `7afd39bef3d180ab24278999068a26efb4b88e58`). The runner used only `--calls-only --python-call-targets --execution-evidence --tensor-physical --capture-transport snapshot --os-capture-root ... --os-profile program-interfaces`; it did not enable `process-ports`. `SCAR_NATIVE_TENSOR_INPUTS=1`; collector witness and process-image receipts were omitted because V1 is not accepted by the ordinary coordinate binder and V2 is unnecessary for exact capture membership here.

Capture terminal: exit 0, wrapper PID `2149382`, target PID `2149392`, CLI elapsed `39.795 s`; target `run.json` reports `37.249 s` and stdout reports the expected CUDA result. The ordinary coordinate binder retained 37 artifacts, including ETO, Kineto, tensor physical/input, Python call-target, and OS syscall evidence. Run ID: `capture:4b80048c87d46c98c84e43a4150456c3f551786432bdfd831064ddb378b8b308`.

## Normal OS fragment and worker roles

The normal `import_os_resources(..., coordinates=coordinates, interface_work=True)` path produced an `OSResourceFragment` in the same Run. Its published interface manifest is `os-resource-fragment/manifest.json`, SHA256 `97058f5968b6900929ae16227a957a70445cfab8f197de395c7a0a3064d2b3d3`. It contains 65,352 interface observations across 19 TID artifacts; 45 I/O rows were connected in the existing conservative profile. Effects, quiescence, source correspondence, and whole-model completeness remain unproved. `OSInterfacePartitions` normally read back an observation and submission.

Using the role bridge from `os-postprocessing-roles` commit `176faced`, the same-run coordinates and ordinary interface fragment positively identified all five snapshot materializer child processes from their exact parent birth, `execve` argv, and retained per-TID source lines. Each exact `exec` endpoint queried back to `SCAR_OFFLINE_POSTPROCESSING`; there were no role frontiers in this five-receipt scope. The five worker PIDs were `2149484`, `2149492`, `2149481`, `2149495`, and `2149494`, all parented by target PID `2149392`. This labels only their postprocessing intervals; it does not relabel or remove the original syscall observations, and unclassified activity is not asserted to be application work.

## Receipts and limits

- Machine results: `CAPTURE_TERMINAL.json`, `POSTPROCESS_RESULT.json`, `SNAPSHOT_ROLE_BRIDGE_RESULT.json`, and `ACTUAL_TERMINAL.json`.
- Reproduction inputs/programs: `INPUTS.json`, `run_small_capture.py`, `consume_snapshot_roles.py`, and `small_cuda_file_program.py`.
- Capture and compressed OS fragment files remain at this artifact's original local paths and are intentionally excluded from Git; the committed reports contain their receipts. No retry or second capture was run.

This validates a narrow same-Run postprocessing association path only. It makes no claim about LeWM coverage, Python-to-Torch operation identity, tensor contents/aliasing, GPU readiness, or transformation authority.
