# First-stage model reset and automatic inventory baseline

Product revision: `221819f5c13f8b5867cd93d66f600d5038431e0a`.
Environment: conda `lewm`, Python 3.14.7.

`rebuild-inventory.sh` ran the current public inventory command on the original
LeWM entry and archived successful calls trace. It did not execute LeWM, import
the target, change model/data files, enable optimization, or perform a benchmark.
The exact command, exit status, analysis time and output are retained.

`audit_inventory.py` independently recounts serialized inventory records with
the standard library. It checks that body and definition counts agree with the
inventory summary; it does not independently prove dependency correctness.

It was run on both the historical inventory and `inventory.json.gz`, producing
`historical-inventory-audit.json` and `current-inventory-audit.json`. Both commands
exited 0, with empty stderr. Full raw output remains; scripts require fresh paths.

The coverage counts remain 151 files, 2,217 definitions, 50 local graphs with
gaps, 206 unsupported bodies and 1,961 not attempted. There are 32/425 eligible
runtime code/source groups connected to core. These are source/call inventory
facts, not full program or resource coverage. No whole-model acceptance or
speedup is established.

The target and primary worktrees remained clean at their original revisions:
LeWM `f70fed80288462ca4d006cb3607ec6da6eaa851f`; main SCAR
`84f165fce1e2e37617c974ce9fee574ea816406b`. No product source or tests changed in
this checkpoint; it adds design/audit documents and reproducible analysis evidence.

Governing scope: `docs/FIRST_STAGE_MODEL_CONTRACT.md`. Current result and next
implementation: `docs/FIRST_STAGE_MODEL_STATUS.md`. Complete first stage: OPEN.
