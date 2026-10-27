#!/usr/bin/env bash
set -euo pipefail
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/zyf/AAA/scar-worktrees/structured-program-model
RUN=/home/zyf/AAA/scar-worktrees/structured-program-model/artifacts/experiments/project_dependency_publication_gate_20261025
python -B "$RUN/late_freeze.py" --check
set +e
/usr/bin/time -v -o "$RUN/offline/entries.time.txt" timeout --signal=TERM --kill-after=15s 180s python -B -m scar.cli model-run --from-model-run "$RUN/offline/dependencies" --stage source-entries --out "$RUN/offline/entries" --entry-max-dispatch-entries 16 --entry-max-catalog-groups 32 --entry-max-catalog-entries 32 --entry-max-source-files 6 --entry-max-total-operations 16000 >"$RUN/offline/entries.stdout.txt" 2>"$RUN/offline/entries.stderr.txt"
code=$?
printf '%s\n' "$code" >"$RUN/offline/entries.exit.txt"
set -e
if [ "$code" -ne 0 ]; then exit "$code"; fi
set +e
/usr/bin/time -v -o "$RUN/offline/bindings.time.txt" timeout --signal=TERM --kill-after=15s 180s python -B -m scar.cli model-run --from-model-run "$RUN/offline/entries" --stage source-entry-bindings --out "$RUN/offline/bindings" --binding-max-programs 16 --binding-max-catalog-groups 32 --binding-max-catalog-entries 32 >"$RUN/offline/bindings.stdout.txt" 2>"$RUN/offline/bindings.stderr.txt"
code=$?
printf '%s\n' "$code" >"$RUN/offline/bindings.exit.txt"
set -e
python -B "$RUN/late_freeze.py" --check
exit "$code"
