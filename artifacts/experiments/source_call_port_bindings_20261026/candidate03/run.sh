#!/usr/bin/env bash
set -euo pipefail
cd /home/zyf/AAA/scar-worktrees/source-entry-project
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/zyf/AAA/scar-worktrees/source-entry-project
gate_dir=artifacts/experiments/source_call_port_bindings_20261026/candidate03
exec /usr/bin/time -v -o "$gate_dir/run.time.txt" timeout --signal=TERM --kill-after=10s 5460s python -B "$gate_dir/run.py" > "$gate_dir/run.stdout.jsonl" 2> "$gate_dir/run.stderr.txt"
