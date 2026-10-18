#!/usr/bin/env bash
set -o pipefail
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=.
stopiter_base=artifacts/experiments/b1_call_operands/model_generator_matrix/stopiter-focused
stopiter_sources=(
  scar/ir/program/model.py scar/ir/program/codec.py scar/ir/program/queries.py
  scar/ir/program/driver_validation.py scar/ir/program/validation.py
  scar/ir/program/protocols.py scar/ir/program/protocol_rules.py
  scar/ir/program/protocol_flow.py scar/ir/program/protocol_validation.py
  scar/ir/program/protocol_query.py scar/ir/program/lifecycle_flow.py
  tests/fixtures/program_driver_graphs.py tests/fixtures/program_resumption_graphs.py
  tests/fixtures/program_protocol_graphs.py tests/fixtures/program_publication_graphs.py
  tests/fixtures/program_generator_admission_graphs.py tests/fixtures/program_generator_close_graphs.py
  tests/fixtures/program_generator_close_retry_graphs.py
  tests/fixtures/program_generator_stopiter_graphs.py tests/unit/test_program_generator_stopiter.py
)
sha256sum "${stopiter_sources[@]}" > "$stopiter_base/attempt003.source-before.sha256"
python artifacts/experiments/b1_call_operands/model_generator_matrix/run_focus.py \
  stopiter-focused/attempt003 tests/unit/test_program_generator_stopiter.py
stopiter_status=$?
sha256sum "${stopiter_sources[@]}" > "$stopiter_base/attempt003/source-after.sha256"
cp "$stopiter_base/attempt003.source-before.sha256" "$stopiter_base/attempt003/source-before.sha256"
exit "$stopiter_status"
