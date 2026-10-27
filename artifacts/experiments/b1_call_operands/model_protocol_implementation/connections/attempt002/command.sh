#!/usr/bin/env bash
set -o pipefail
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=.
protocol_evidence_dir=artifacts/experiments/b1_call_operands/model_protocol_implementation/connections/attempt002
protocol_sources=(
  scar/ir/program/protocols.py scar/ir/program/protocol_rules.py
  scar/ir/program/protocol_flow.py scar/ir/program/protocol_validation.py
  scar/ir/program/protocol_query.py scar/ir/program/model.py
  scar/ir/program/validation.py scar/ir/program/queries.py
  scar/ir/program/lifecycle_flow.py scar/ir/program/session_flow.py
  scar/ir/program/lifecycle_analysis.py scar/ir/program/session_release_validation.py
  tests/fixtures/program_protocol_graphs.py tests/unit/test_program_protocol_connections.py
)
sha256sum "${protocol_sources[@]}" > "$protocol_evidence_dir/source-before.sha256"
python --version > "$protocol_evidence_dir/environment.log" 2>&1
date -u +%FT%TZ > "$protocol_evidence_dir/started.txt"
/usr/bin/time -f 'wall_seconds=%e' -o "$protocol_evidence_dir/time.txt" \
  python -m pytest -q tests/unit/test_program_protocol_connections.py \
  --junitxml="$protocol_evidence_dir/junit.xml" \
  > "$protocol_evidence_dir/stdout.log" 2> "$protocol_evidence_dir/stderr.log"
protocol_status=$?
printf '%s\n' "$protocol_status" > "$protocol_evidence_dir/exit_code.txt"
date -u +%FT%TZ > "$protocol_evidence_dir/ended.txt"
sha256sum "${protocol_sources[@]}" > "$protocol_evidence_dir/source-after.sha256"
cat "$protocol_evidence_dir/stdout.log"
cat "$protocol_evidence_dir/stderr.log"
exit "$protocol_status"
