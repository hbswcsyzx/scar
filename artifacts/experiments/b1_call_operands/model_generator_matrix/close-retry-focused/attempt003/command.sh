#!/usr/bin/env bash
set -o pipefail
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=.
retry_evidence=artifacts/experiments/b1_call_operands/model_generator_matrix/close-retry-focused/attempt003
retry_sources=(
  scar/ir/program/model.py scar/ir/program/protocols.py scar/ir/program/protocol_rules.py
  scar/ir/program/protocol_flow.py scar/ir/program/protocol_validation.py
  scar/ir/program/protocol_query.py scar/ir/program/validation.py
  scar/ir/program/lifecycle_flow.py scar/ir/program/queries.py
  tests/fixtures/program_protocol_graphs.py tests/fixtures/program_driver_graphs.py
  tests/fixtures/program_resumption_graphs.py tests/fixtures/program_publication_graphs.py
  tests/fixtures/program_session_release_graphs.py tests/fixtures/program_generator_close_graphs.py
  tests/fixtures/program_generator_close_retry_graphs.py tests/unit/test_program_generator_close_retry.py
)
sha256sum "${retry_sources[@]}" > "$retry_evidence/source-before.sha256"
python --version > "$retry_evidence/environment.log" 2>&1
date -u +%FT%TZ > "$retry_evidence/started.txt"
/usr/bin/time -f 'wall_seconds=%e' -o "$retry_evidence/time.txt" \
  python -m pytest -q tests/unit/test_program_generator_close_retry.py -k two_actual \
  --junitxml="$retry_evidence/junit.xml" \
  > "$retry_evidence/stdout.log" 2> "$retry_evidence/stderr.log"
retry_status=$?
printf '%s\n' "$retry_status" > "$retry_evidence/exit_code.txt"
date -u +%FT%TZ > "$retry_evidence/ended.txt"
sha256sum "${retry_sources[@]}" > "$retry_evidence/source-after.sha256"
cat "$retry_evidence/stdout.log"
cat "$retry_evidence/stderr.log"
exit "$retry_status"
