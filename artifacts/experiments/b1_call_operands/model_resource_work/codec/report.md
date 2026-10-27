# R2.1 execution codec v2 — limited implementation result

## Implemented

Owned changes are only `scar/ir/execution/codec.py`, `tests/unit/test_execution_work_codec.py`, and the two `execution_v1_frozen` fixture/proof files.

- Maximum schema version is 2. Default `to_dict/dumps` select v1 when all five work tables are empty, otherwise v2.
- `to_dict(model, *, schema_version=None)` and `dumps(model, *, schema_version=None)` permit explicit exact integer 1/2. Work capability cannot be forced into v1. Explicit v2 permits empty work tables and emits all of them.
- `from_dict/loads` select a closed field and tagged-type vocabulary for the document version. v1 rejects every new table even if empty and rejects new work tags; decoding old v1 supplies the five empty defaults strictly as migration, not absence-of-work evidence. v2 requires all declared tables and fields.
- All recursive ID/enum/record/union checks persist. Revalidation of the whole model occurs before capability detection, so a malformed false-like work table cannot silently disappear into v1.
- Program/v2 IDs keep their original namespace and wire form; work records get their exact new class tags. No provider/URI execution or graph-validation/proof grant is introduced.

## Independent v1 fixture

Generated successfully from immutable commit `6fcac0f778d56d7fe4fdb90e546b23e545f86f96` using `git archive scar tests/fixtures` into an owned temporary directory. Both child cwd and PYTHONPATH pointed exclusively at the archive; the child asserted historical codec version 1 and its module location before calling `resource_execution_program(native_handles=True)` and the historical `dumps`.

The exact archive/child commands, historical codec/fixture source hashes, interpreter, stderr, exit and proof are retained under `historical/` and `tests/fixtures/execution_v1_frozen.proof.json`. The temporary archive directory was removed by its own TemporaryDirectory scope. Current codec output was not used to generate expected bytes.

Frozen payload: **88,521 bytes**, SHA256 `66ce59c3f04c7b92babaf320127dd9c696b3cc6ecaada76e1e1b50a63095e391`.

The dedicated test checks both loading/re-encoding these bytes and independently generating the same factory with current code: both equal the immutable payload byte for byte.

## Actual focused verification

First and only dedicated test run: **35 passed in 0.83s**, exit 0.

```text
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python -m pytest -q tests/unit/test_execution_work_codec.py
```

Exact command/interpreter/cwd/environment, original output, return status and before/after hashes are in `attempt001/`. All seven hashed source/fixture files were unchanged during that run; no initial pytest failure occurred.

Meaningful cases: immutable v1 equality; explicit empty v2; each new table individually selects v2; forbidden downgrade; all five missing/extra table cases; new tagged type laundering into v1; Queued/Direct scheduling; WorkTicket/queue instance/access namespace distinctions; four retained-target fixture profiles; COMPLETED/FAILED/CANCELLED; normal/raise INVOKE completion/result-index/formal identities; external origin and explicit unresolved post/executor/retention/protocol results; wrong union/ID/enum; bool index/version; nested private mutation and false-like table corruption.

## Scope

This verifies strict record serialization and v1 migration compatibility, including declared fixtures. Isolated-table/variant cases intentionally do not claim complete foreign-key graph validity. Runtime work truth, canonical relationship validation, source applicability, event/order/consumer readiness, lifetime/quiescence truth and transformation authority are not established. No full suite, LeWM/GPU capture, environment installation or git commit/push was performed. Root owns graph/validator/query/CLI integration and the old max-schema test assertion update.

## Frozen owned-source SHA256

- `scar/ir/execution/codec.py`: `b9df39823e351e855702a8bdb324cb637da1431fd55b5a5bc1a3c3310e0fd890`
- `tests/unit/test_execution_work_codec.py`: `36acaadde22bcb25ef6ba23596bfad581f5334bdd6dc7f8dfa0f954cf5110609`
- `tests/fixtures/execution_v1_frozen.json`: `66ce59c3f04c7b92babaf320127dd9c696b3cc6ecaada76e1e1b50a63095e391`
- `tests/fixtures/execution_v1_frozen.proof.json`: `b3b99dfa7ec37e4f2a8087fa8c6338e111807163a6e540f1055ee3929f363669`
