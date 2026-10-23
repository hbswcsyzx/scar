#!/usr/bin/env bash
set -euo pipefail
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/zyf/AAA/scar-worktrees/structured-program-model
scar_task_root=/home/zyf/AAA/scar-worktrees/structured-program-model
scar_case_root="$scar_task_root/artifacts/experiments/first_stage_dispatch_bridge_20261023/case"
scar_result_root="$scar_task_root/artifacts/experiments/first_stage_tensor_physical_20261023"
test ! -e "$scar_result_root/trace"
git -C "$scar_task_root" rev-parse HEAD > "$scar_result_root/base.git.txt"
git -C "$scar_task_root" diff -- scar/cli.py scar/trace/execution_evidence.py > "$scar_result_root/integration.patch"
sha256sum "$scar_task_root/scar/trace/tensor_physical.py" "$scar_task_root/scar/trace/dispatch_evidence.py" "$scar_case_root/app.py" > "$scar_result_root/producer.sha256"
cd "$scar_case_root"
/usr/bin/time -v -o "$scar_result_root/run.time.txt" \
  python -m scar.cli trace --call-operands --execution-evidence --tensor-physical \
    --project-root "$scar_case_root" --out "$scar_result_root/trace" -- \
    python app.py > "$scar_result_root/run.stdout.txt" 2> "$scar_result_root/run.stderr.txt"
