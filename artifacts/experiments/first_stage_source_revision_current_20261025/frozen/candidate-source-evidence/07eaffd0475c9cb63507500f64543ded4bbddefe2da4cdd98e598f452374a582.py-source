#!/usr/bin/env bash
set -euo pipefail
cd /home/zyf/AAA/scar-worktrees/structured-program-model
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/zyf/AAA/scar-worktrees/structured-program-model
gate_dir=artifacts/experiments/first_stage_source_revision_current_20261025
test ! -e "$gate_dir/inputs.json"
test ! -e "$gate_dir/frozen"
python "$gate_dir/prepare.py" --phase inputs > "$gate_dir/prepare-inputs.stdout.json" 2> "$gate_dir/prepare-inputs.stderr.txt"
python "$gate_dir/prepare.py" --phase frozen > "$gate_dir/prepare-frozen.stdout.json" 2> "$gate_dir/prepare-frozen.stderr.txt"
