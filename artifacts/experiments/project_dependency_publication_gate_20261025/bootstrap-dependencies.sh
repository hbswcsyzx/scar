#!/usr/bin/env bash
set -euo pipefail
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/zyf/AAA/scar-worktrees/structured-program-model
RUN=/home/zyf/AAA/scar-worktrees/structured-program-model/artifacts/experiments/project_dependency_publication_gate_20261025
python -B "$RUN/offline_freeze.py" --check
mkdir -p "$RUN/offline"
set +e
/usr/bin/time -v -o "$RUN/offline/bootstrap.time.txt" timeout --signal=TERM --kill-after=15s 180s python -B -m scar.cli model-run --from-capture "$RUN/capture" --out "$RUN/offline/bootstrap" --max-calls 512 >"$RUN/offline/bootstrap.stdout.txt" 2>"$RUN/offline/bootstrap.stderr.txt"
code=$?
printf '%s\n' "$code" >"$RUN/offline/bootstrap.exit.txt"
set -e
if [ "$code" -ne 0 ]; then exit "$code"; fi
set +e
/usr/bin/time -v -o "$RUN/offline/dependencies.time.txt" timeout --signal=TERM --kill-after=15s 180s python -B -m scar.cli model-run --from-model-run "$RUN/offline/bootstrap" --stage dependency-sources --out "$RUN/offline/dependencies" >"$RUN/offline/dependencies.stdout.txt" 2>"$RUN/offline/dependencies.stderr.txt"
code=$?
printf '%s\n' "$code" >"$RUN/offline/dependencies.exit.txt"
set -e
python -B "$RUN/offline_freeze.py" --check
exit "$code"
