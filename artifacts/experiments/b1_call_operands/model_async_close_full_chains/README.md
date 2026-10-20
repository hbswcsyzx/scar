# F19 async close chains

**Verified conditional supplied-model structure**, not automatic source/native
recovery or a performance result. Base c02e973; source `d5d8919d624b2845f3d30d3023ae646d25a213d2c463286b1773e2f136f66edf` (922 inputs).

- verified-new:30 PASS, 357.117132s wrapper.
- verified-regression:302 PASS/26 modules, 571.604609s wrapper.
- Union:332; retained prior catalog2325, current known catalog2408.
- Program27/Execution8 and all previous test/fixture bytes unchanged.
- Original16 rows:10 conditionally accepted,6 open. P4/full/P5/M2 and first stage open.

See docs/M1_ASYNC_CLOSE_CHAINS_ACCEPTANCE.md and API/plan/progress for exact scope.
All attempts include original commands, input hashes, changed source snapshots,
stdout/stderr and JUnit; failed evidence is immutable. Native target runs this
gate:0; old22-call probe/reference source reused. No new LeWM speedup.

Root-only seal/check after reports: `PYTHONPATH=. python artifacts/experiments/b1_call_operands/model_async_close_full_chains/seal_gate.py`
and the same command with `--check`. No tests or target execution run by the seal.
