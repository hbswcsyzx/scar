#!/usr/bin/env bash
set -euo pipefail
cd /home/zyf/AAA/scar-worktrees/source858-runtime
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/zyf/AAA/scar-worktrees/source858-runtime
gate_dir=artifacts/experiments/first_stage_source858_current_20261026
python -B "$gate_dir/prepare.py" > "$gate_dir/prepare.stdout.json" 2> "$gate_dir/prepare.stderr.txt"
