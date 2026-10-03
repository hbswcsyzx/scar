# External source-motion fixture

`program.py` is ordinary Python without SCAR imports. The analysis query asks
whether its complete alias assignment at line 4 can move to the insertion
immediately after line 2. No source is changed, and the query is not an
automatically discovered workload optimization.

The positive fixture explicitly declares the following observation contract:
the current target Python runtime matches; resource failures and asynchronous
interruptions are outside the observations; frame/local-binding timing, trace
event order, reference-count and finalizer observations are outside the
observations; function locals follow ordinary semantics without external
namespace mutation. This is a **synthetic declared contract**, not evidence
that these observations are absent in LeWM or an arbitrary target.

The acceptance report archives the exact source-bound `ProofQ` JSON separately.
Its scope/subjects include source identity, rule version and runtime. A moved
checkout, changed source or runtime requires a fresh caller contract rather
than automatic acceptance of the saved one.

```bash
cd ~/AAA/scar
conda activate lewm
PYTHONPATH=. python scripts/measure_static_motion_v2.py \
  testcases/source_motion/program.py --statement-line 4 --after-line 2 \
  --out artifacts/reports/gates/g7-2b-motion-no-q.json.gz
PYTHONPATH=. python scripts/measure_static_motion_v2.py \
  testcases/source_motion/program.py --statement-line 4 --after-line 2 \
  --q artifacts/reports/gates/g7-2b-motion-example-q.json \
  --out artifacts/reports/gates/g7-2b-motion-example.json.gz
```

The first report needs the contract. The second may establish conditional
legality under this exact fixture contract. Both retain zero selected/applied
transformations and pending cost; timings measure SCAR analysis only.
