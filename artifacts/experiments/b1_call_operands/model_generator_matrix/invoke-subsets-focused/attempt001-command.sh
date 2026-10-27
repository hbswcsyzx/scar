#!/usr/bin/env bash
set -o pipefail
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=.
subset_base=artifacts/experiments/b1_call_operands/model_generator_matrix/invoke-subsets-focused
subset_sources=(
  scar/ir/program/model.py scar/ir/program/codec.py
  scar/ir/program/queries.py scar/ir/program/driver_validation.py
  scar/ir/program/validation.py scar/ir/program/session_release_validation.py
  scar/ir/program/protocol_flow.py scar/ir/program/protocol_validation.py
  tests/fixtures/program_driver_graphs.py tests/fixtures/program_admission_graphs.py
  tests/fixtures/program_protocol_graphs.py
  tests/fixtures/program_invoke_subset_graphs.py tests/unit/test_program_invoke_subsets.py
  tests/fixtures/program_graph_v2_frozen.json tests/fixtures/program_graph_v17_frozen.json
  tests/unit/test_program_completion_records.py
)
sha256sum "${subset_sources[@]}" > "$subset_base/attempt001.source-before.sha256"
python artifacts/experiments/b1_call_operands/model_generator_matrix/run_focus.py \
  invoke-subsets-focused/attempt001 tests/unit/test_program_invoke_subsets.py
subset_status=$?
sha256sum "${subset_sources[@]}" > "$subset_base/attempt001/source-after.sha256"
cp "$subset_base/attempt001.source-before.sha256" "$subset_base/attempt001/source-before.sha256"
exit "$subset_status"
