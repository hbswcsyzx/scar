# Native evidence coexistence checkpoint

`check-capture.sh` ran five new real CPU subprocess integration cases and
33 existing directly affected call/operand CLI cases: 38 passed, no failures,
errors or skips, 109.68 seconds pytest, 110.38 seconds command wall time.
This is validation cost, not a benchmark or whole-model acceptance.

The new tests check real operator counts/target state, lazy Torch import, hook
preservation and foreign ETO/profiler continued operation after SCAR closes.
No old test or fixture changed. Raw command, stdout/stderr, JUnit and time output
are retained. The full repository was not rerun.

The collector is raw EXECUTION_EVIDENCE only. Whole-program source/call/data/
resource connection and the first-stage LeWM acceptance remain OPEN. Future
LeWM execution evidence, if produced, is reported separately from this checkpoint.
