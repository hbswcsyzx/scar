#!/usr/bin/env bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=.
identity_dir=artifacts/experiments/b1_call_operands/model_generator_matrix/full-failure-investigation/identity-order
sha256sum "$identity_dir/probe.py" > "$identity_dir/script.sha256"
/usr/bin/time -f 'wall_seconds=%e' -o "$identity_dir/time.txt" \
  python "$identity_dir/probe.py" > "$identity_dir/result.json" 2> "$identity_dir/stderr.log"
identity_status=$?
printf '%s\n' "$identity_status" > "$identity_dir/exit_code.txt"
exit "$identity_status"
