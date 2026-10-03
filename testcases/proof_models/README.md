# Source proof model testcase

This is external source input, not a SCAR optimization rule. It contains normal
statement order, identity comparisons, branches, zero-trip loops, break/continue
and unsupported exception/context-manager boundaries. The final raise catches
accidental execution. Undefined callbacks are source boundaries, never invoked.

```bash
conda activate lewm
python -m scar.cli proof-models-v2 testcases/proof_models/program.py \
  --out artifacts/reports/proof-models.json.gz
```

The report contains independent control and primitive models. It does not claim
that `stage`, operand evaluation, a loop or callbacks are pure; it does not grant
legality or select/apply a rewrite.
