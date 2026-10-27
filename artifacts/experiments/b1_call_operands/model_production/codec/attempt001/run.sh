#!/usr/bin/env bash
set -euo pipefail
cd /tmp/scar-structured-model-280qf4mi
ATTEMPT=artifacts/experiments/b1_call_operands/model_production/codec/attempt001
COMMIT=5ab22f8d8fcbabbc59d494b571651d480468f3d5
ARCHIVE="$ATTEMPT/legacy-source.tar"
ROOT="$ATTEMPT/archive"
PAYLOAD="$ATTEMPT/execution_v4_frozen.json"
MODULES="$ATTEMPT/imported-source-hashes.json"
test ! -e tests/fixtures/execution_v4_frozen.json
git archive --format=tar "$COMMIT" scar tests/fixtures > "$ARCHIVE"
sha256sum "$ARCHIVE" > "$ATTEMPT/archive-sha256.txt"
tar -xf "$ARCHIVE" -C "$ROOT"
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$ROOT"
python "$ATTEMPT/generate_v4_golden.py" "$ROOT" "$PAYLOAD" "$MODULES"
cp "$PAYLOAD" tests/fixtures/execution_v4_frozen.json
cp "$MODULES" "$ATTEMPT/imported-source-hashes.json"
sha256sum tests/fixtures/execution_v4_frozen.json > "$ATTEMPT/payload-sha256.txt"
stat -c '%s' tests/fixtures/execution_v4_frozen.json > "$ATTEMPT/payload-size.txt"
