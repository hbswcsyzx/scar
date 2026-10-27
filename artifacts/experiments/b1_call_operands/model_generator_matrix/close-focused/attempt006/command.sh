#!/usr/bin/env bash
set -o pipefail
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=.
close_evidence=artifacts/experiments/b1_call_operands/model_generator_matrix/close-focused/attempt006
close_sources=(
  scar/ir/program/protocols.py scar/ir/program/protocol_rules.py
  scar/ir/program/protocol_flow.py scar/ir/program/protocol_validation.py
  scar/ir/program/protocol_query.py scar/ir/program/validation.py
  scar/ir/program/lifecycle_flow.py scar/ir/program/queries.py
  tests/fixtures/program_protocol_graphs.py tests/fixtures/program_driver_graphs.py
  tests/fixtures/program_resumption_graphs.py tests/fixtures/program_publication_graphs.py
  tests/fixtures/program_session_release_graphs.py
  tests/fixtures/program_generator_close_graphs.py
  tests/unit/test_program_generator_close_contracts.py
)
sha256sum "${close_sources[@]}" > "$close_evidence/source-before.sha256"
python --version > "$close_evidence/environment.log" 2>&1
date -u +%FT%TZ > "$close_evidence/started.txt"
/usr/bin/time -f 'wall_seconds=%e' -o "$close_evidence/time.txt" \
  python -m pytest -q tests/unit/test_program_generator_close_contracts.py \
  --junitxml="$close_evidence/junit.xml" \
  > "$close_evidence/stdout.log" 2> "$close_evidence/stderr.log"
close_status=$?
printf '%s\n' "$close_status" > "$close_evidence/exit_code.txt"
date -u +%FT%TZ > "$close_evidence/ended.txt"
sha256sum "${close_sources[@]}" > "$close_evidence/source-after.sha256"
cat "$close_evidence/stdout.log"
cat "$close_evidence/stderr.log"
exit "$close_status"
