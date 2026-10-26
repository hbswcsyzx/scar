#!/usr/bin/env bash
set -euo pipefail
cd /home/zyf/AAA/scar-worktrees/source858-runtime
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/zyf/AAA/scar-worktrees/source858-runtime
D=artifacts/experiments/lewm_archived_compiler_gate_20261026
/usr/bin/time -v -o "$D/run.time.txt" timeout --signal=TERM --kill-after=15s 180s python -B "$D/run.py" > "$D/run.stdout.txt" 2> "$D/run.stderr.txt"
