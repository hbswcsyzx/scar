# R0 resource execution relation design

**PASS for the relation-design gate; R1/R2 product remains unimplemented.**
Baseline: `309fb359be8665fc90979f270a6d4e4d20c6eb85`.
Final contract SHA256:
`74a606fca89ecb94ad9a04f77d8ad41706bcdacb10210352ccad185272993729`.

## Saved evidence

- `contract.md` and `plan.md`: exact final byte snapshots of the reviewed relation
  contract and ordered implementation/acceptance plan. They are not an executable
  record schema or a claim that ResourceInstance/WorkTicket/ready was implemented.
- `review/`: three independent source audits, reverse reviews, original candidate
  hashes/problems, storage/consumer note and three final bounded closeouts. The
  last small-diff receipts bind the final contract hash rather than overwriting
  the earlier candidates as if they had already included the fixes.
- `root-decisions.md`: accepted/rejected alternatives, ownership and evidence
  boundaries, and the precise scope of the six witnesses.
- `witnesses/`: one real run of six asserted stdlib CPU/OS cases. Raw stdout,
  exact command, Python/platform, script hash and return code retained. Owned
  temporary resources were released. No CUDA execution or power-loss test.
- `research/sources.json`: official reference URLs, successful retrieval versus
  cache misses, online/local version differences and SHA256 of installed local
  PyTorch/CUDA source/header. No entire external webpage is redistributed.
- `source-continuity.json`: all 451 registered source/test/gate files match the
  accepted D2.4 source. The existing 4,050-case run is prior evidence only; no
  new component/full regression was started for this design/documentation gate.
- `protected-checkouts.json`: main SCAR and original LeWM remain at unchanged
  expected clean revisions.

The witness `submit` returned normally before the worker failed; host
`Future.result()` then raised. It does not test an enqueue API itself raising
after a partial submission. That case is represented in the contract through
the original INVOKE state Uses and actual completion ports, not claimed as an
observed GPU behavior. A successful fsync return is not a power-loss experiment.

## Next implementation gates

R1: exact core occurrences plus resource identity/requirement/handle/access
bindings. R2: work/outcome/event/order and per-consumer ready support. R3:
generic load/materialize/consume/save composition, strict public interfaces,
independent review, component and one frozen full regression. Complete first
modeling stage and automatic LeWM simplification remain open.

See [the acceptance report](../../../../docs/M1_RESOURCE_EXECUTION_DESIGN_ACCEPTANCE.md).

## Read-only verification

```bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 python artifacts/experiments/b1_call_operands/model_resource_execution_design/check_evidence.py
```

This checks saved hashes, cases, review bindings and prior-source continuity;
it does not run the witnesses, tests or workload again.
