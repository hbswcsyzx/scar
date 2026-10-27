# Generic model-run source-entry-bindings CLI candidate

Root session71666 actualexit0/40.817239653s; see RESULT.md. The implementation is in cli.py/source_entry_run.py, with no experiment
imports or fixed workload URI. Root first confirms all participating sources are
stable, then prepares the actual source/input SHA freeze with:

```bash
python -B artifacts/experiments/model_run_source_entry_bindings_gate_20261025/run.py \
  --prepare --head-label ROOT_HEAD --input IMMUTABLE_SOURCE_ENTRY_TERMINAL
```

Preparation calls only the bounded metadata planner and stats original SP5/graph
declarations. It reuses original stored receipts for graph/code payloads, hashes
current SCAR sources and small control files, and never executes a producer.
The real gate (Root holds the session) uses the resulting pinned input:

```bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/zyf/AAA/scar-worktrees/structured-program-model timeout 180s python -B /home/zyf/AAA/scar-worktrees/structured-program-model/artifacts/experiments/model_run_source_entry_bindings_gate_20261025/run.py
```

One public CLI call performs normal independent publication of the same original
SP5, ordinary qualified body reader/query, fresh genuine coordinate acquisition
and ordinary same-capture v4 source binder. This validates the new generic command
and profile, separately from the earlier API gate. It does not lower/copy the SP5,
restore a lower owner, rebuild native/OS models, execute the target or grant old SBA
qualification. Code/source/body links and all remaining interfaces are separate.

Default binding profile is one program/4000ops, source/provider decode128MB,
record64MB/output128MB post-stage, actual raw2MB/2048lines/1024events, coordinates
64MB reservations and explicit seed-metadata verifier ceilings. Every ceiling has
default/CLI provenance; earlier profile flags cannot be mixed. All-input cumulative
I/O and runtime binary closure remain OPEN. Counts come from the ordinary binder.

api-check-final.json records the bounded existing small source-entry metadata
scope/namespace check:9groups/271calls,1 saved successful SP5, no blockers;
stored641856B/decoded785889B, graph/raw/compile/target0, Torch not imported.
The same input was used for the initial development metadata check. CLI help and
syntax/import pass. The actual CLI gate now independently completed all four
stages, preserving9/271 with260body/5source/6unresolved. Final366source hashes
including Root's SP7/native applications are in freeze.json.

Library plan-only writes a partial navigation/immutable attempt but reads no
graph/raw/source/code payload. It selects every saved successful SP5; over-window
or missing project-body publication support blocks explicitly without dropping
declarations. New upstream entry products pin per-artifact worker terminal refs;
legacy all-success products are accepted only when unambiguous. Resume creates a
fresh attempt, retaining old failures and pinned source scope without ownership
restoration. Failure detail remains in the workflow terminal and gate result.
