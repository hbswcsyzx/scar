#!/usr/bin/env bash
set -o pipefail
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=.
protocol_release_evidence=artifacts/experiments/b1_call_operands/model_protocol_implementation/release-focused/attempt001
protocol_release_sources=(
  scar/ir/program/protocols.py scar/ir/program/protocol_rules.py
  scar/ir/program/protocol_flow.py scar/ir/program/protocol_validation.py
  scar/ir/program/protocol_query.py scar/ir/program/model.py
  scar/ir/program/validation.py scar/ir/program/queries.py
  scar/ir/program/lifecycle_flow.py scar/ir/program/session_flow.py
  scar/ir/program/lifecycle_analysis.py scar/ir/program/session_release_validation.py
  tests/fixtures/program_protocol_graphs.py tests/fixtures/program_session_release_graphs.py
  tests/fixtures/program_protocol_release_graphs.py
  tests/unit/test_program_protocol_release_connections.py
)
sha256sum "${protocol_release_sources[@]}" > "$protocol_release_evidence/source-before.sha256"
python --version > "$protocol_release_evidence/environment.log" 2>&1
date -u +%FT%TZ > "$protocol_release_evidence/started.txt"
/usr/bin/time -f 'wall_seconds=%e' -o "$protocol_release_evidence/time.txt" \
  python -m pytest -q tests/unit/test_program_protocol_release_connections.py \
  --junitxml="$protocol_release_evidence/junit.xml" \
  > "$protocol_release_evidence/stdout.log" 2> "$protocol_release_evidence/stderr.log"
protocol_release_status=$?
printf '%s\n' "$protocol_release_status" > "$protocol_release_evidence/exit_code.txt"
date -u +%FT%TZ > "$protocol_release_evidence/ended.txt"
sha256sum "${protocol_release_sources[@]}" > "$protocol_release_evidence/source-after.sha256"
cat "$protocol_release_evidence/stdout.log"
cat "$protocol_release_evidence/stderr.log"
exit "$protocol_release_status"
