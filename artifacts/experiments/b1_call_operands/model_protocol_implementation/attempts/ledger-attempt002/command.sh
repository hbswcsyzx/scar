#!/usr/bin/env bash
set -o pipefail
attempt_dir=artifacts/experiments/b1_call_operands/model_protocol_implementation/attempts/ledger-attempt002
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=.
protocol_sources=(
  scar/ir/program/protocols.py scar/ir/program/protocol_rules.py
  scar/ir/program/protocol_flow.py scar/ir/program/protocol_validation.py
  scar/ir/program/protocol_query.py scar/ir/program/queries.py
  tests/fixtures/program_protocol_graphs.py tests/unit/test_program_protocol_ledger.py
)
sha256sum "${protocol_sources[@]}" > "$attempt_dir/source-before.sha256"
python --version > "$attempt_dir/environment.log" 2>&1
date -u +%FT%TZ > "$attempt_dir/started.txt"
/usr/bin/time -f 'wall_seconds=%e' -o "$attempt_dir/time.txt" \
  python -m pytest -q tests/unit/test_program_protocol_ledger.py \
  --junitxml="$attempt_dir/junit.xml" \
  > "$attempt_dir/stdout.log" 2> "$attempt_dir/stderr.log"
protocol_status=$?
printf '%s\n' "$protocol_status" > "$attempt_dir/exit_code.txt"
date -u +%FT%TZ > "$attempt_dir/ended.txt"
sha256sum "${protocol_sources[@]}" > "$attempt_dir/source-after.sha256"
cat "$attempt_dir/stdout.log"
cat "$attempt_dir/stderr.log"
exit "$protocol_status"
