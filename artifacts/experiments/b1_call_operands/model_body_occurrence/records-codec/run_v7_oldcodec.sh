#!/usr/bin/env bash
set -euo pipefail

ROOT=/tmp/scar-structured-model-280qf4mi
ATTEMPT="$ROOT/artifacts/experiments/b1_call_operands/model_body_occurrence/records-codec/attempt001"
ORACLE=/tmp/scar-p3-v7-oracle-a740661

git archive --format=tar a740661 > "$ATTEMPT/legacy-source.tar"
sha256sum "$ATTEMPT/legacy-source.tar" > "$ATTEMPT/legacy-source.tar.sha256"
mkdir -p "$ORACLE"
tar -xf "$ATTEMPT/legacy-source.tar" -C "$ORACLE"
cd "$ORACLE"
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.
set +e
python "$ROOT/artifacts/experiments/b1_call_operands/model_body_occurrence/records-codec/generate_v7_oldcodec.py" \
    "$ATTEMPT/execution_v7_frozen.json" \
    "$ATTEMPT/execution_v7_frozen.proof.json" \
    > "$ATTEMPT/generator.stdout.log" 2> "$ATTEMPT/generator.stderr.log"
status=$?
set -e
printf '%s\n' "$status" > "$ATTEMPT/generator.exit-code"
exit "$status"
