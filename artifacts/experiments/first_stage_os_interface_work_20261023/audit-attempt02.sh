#!/usr/bin/env bash
set -euo pipefail
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/zyf/AAA/scar-worktrees/structured-program-model
cd /home/zyf/AAA/scar-worktrees/structured-program-model
/usr/bin/time -v -o artifacts/experiments/first_stage_os_interface_work_20261023/audit-attempt02.time.txt \
    python artifacts/experiments/first_stage_os_interface_work_20261023/audit-attempt02.py \
    > artifacts/experiments/first_stage_os_interface_work_20261023/audit-attempt02.stdout.jsonl \
    2> artifacts/experiments/first_stage_os_interface_work_20261023/audit-attempt02.stderr.txt
