# Control protocol language evidence

Date: 2026-10-16. Scope: standalone language probes for the M2 control protocol
specification. No SCAR imports, graph construction, target program, LeWM, pytest,
detector or backend runs.

Working directory: `/tmp/scar-structured-model-280qf4mi`.

Interpreter command:

```bash
/home/zyf/miniconda3/envs/lewm/bin/python -VV
```

Observed: Python 3.14.7, packaged by conda-forge, build Sep 2 2026,
GCC 15.3.0. Exact `sys.version` is stored in `results.json`.

Reproducible probe command:

```bash
PYTHONDONTWRITEBYTECODE=1 /home/zyf/miniconda3/envs/lewm/bin/python artifacts/experiments/model_control_protocols/probe.py
```

Final observed process exit code: **0**. Final result: **17 groups PASS, 0 FAIL**.
In-process wall time: **0.0035279514268040657 seconds**; this is not a benchmark.
The probe groups contain explicit assertions and additional recorded observations;
the count is not exhaustive language-path or SCAR validation coverage.

Files:

- `probe.py`: final reproducible fixtures, using only standard library and small
  locally defined Python objects.
- `results.json`: final command/version/source hash, 48 AST classes / 83 fields,
  and per-group observed results.
- `results.initial.json`: earlier 13-group report retained as historical evidence;
  it is not the final fixture version or a failed product test.
- `../../../docs/model/PYTHON_CONTROL_PROTOCOLS.md` (repository path is
  `docs/model/PYTHON_CONTROL_PROTOCOLS.md`): reviewed rule candidate and explicit
  untested-scope section. The relative location in this bullet is explanatory;
  use the repository path from the worktree root.

Final hashes at handoff:

```text
doc      a18fa9fe240c4dc8084d31a6bdff48fe4ee029f68aeef2d023bf2e48beccd925
probe    3a903bca77fe15472a7292cc4d9715ee3f2ead98507df5eb3e43eb0358e7089b
results  f2a768d793d5d249cd59eca010647bbc7518c8d74327a025b5d6a963ef46b5fe
```

The final document audit found none of the 48 recorded AST class names missing
from the document. This is only a textual inventory check, not a semantic proof.
Important observed boundaries include nested truth short-circuit counts, chained
comparison result identity, sync/async exhaustion scope, comprehension phases,
exception-group continuation and custom split/derive, pending completion override,
exit-before-enter descriptor lookup, generator close states, async-generator
method differences, pattern extraction before subpattern failure, and optimized
assert elimination. The specification explicitly preserves implementation choices
and does not generalize one observation to arbitrary user code/native behavior.

No further probes or file changes are planned after this handoff. This freezes the
control specification contribution, not the whole M2 gate or an implemented graph.
