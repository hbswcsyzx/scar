# R2.2 execution order codec v3 — bounded implementation report

## Changes

- Maximum execution wire schema is 3. The model's three implemented order tables are `queue_order_profiles`, `event_records`, `queue_waits`.
- Default selection: no work/order → v1; work only → v2; any order table → v3. Explicit v1/v2 may not discard order capability; explicit v1 may not discard work. Explicit v3 can encode empty capability tables.
- Each historical schema has its own exact root fields and reachable tagged vocabulary. v1/v2 reject all new order fields even if empty and reject order tags in old unions. v3 requires all three fields. Migration alone fills new defaults; it creates no evidence about absent work/order.
- Existing ID/enum/record/union validation and nested rechecking remain; malformed false-like order tables cannot disappear during version choice.
- Old resource codec test changed only its max-version assertion (2→3). Old work codec test changed only max-version (2→3) and unsupported-version sentinel (3→4), as additionally authorized. All original v1/v2 byte/explicit-version assertions remain.

## Independent historical v2 bytes

Source: immutable commit `bb1b402b498e9ce80a701658a59c1471e8ec32ce`, archived with `scar tests/fixtures` into an owned temporary directory. Child cwd/PYTHONPATH were the archive. It asserted codec max2, codec/model/work/fixture module paths, and all actually imported SCAR/testfixture module paths were inside that archive.

Historical factory: `ordinary_work_execution(queued=True, two_tickets=True, retained='allocation')`; all five work tables are nonempty. The child used only historical dumps. The exact commands, interpreter, source hashes, stderr, exit and proof are preserved in `historical/` and `tests/fixtures/execution_v2_frozen.proof.json`.

Payload: **56,435 bytes**, SHA256 `b03a304a582a662d71ebdbe4685776aef9ec4fc357142f0fa2e6656cdae03234`.

The test compares both historical load/re-encode and current same-factory generation byte for byte. The existing v1 golden was not regenerated or modified and remains exact too. The owned temporary historical directory was removed by its own TemporaryDirectory scope.

## Actual focused run

First and only pytest attempt: **108 passed in 1.55s**, exit 0; 33 new order codec cases plus 75 cases in the two prior codec files. All eight hashed source/fixture files were unchanged throughout the run.

```text
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python -m pytest -q tests/unit/test_execution_order_codec.py tests/unit/test_execution_codec.py tests/unit/test_execution_work_codec.py
```

Exact command/interpreter/cwd/environment and original output/result/hashes are retained under `attempt001/`. No pytest failure was overwritten or discarded; the first run passed.

New cases include exact event r1/r2 identities and captured prefixes, wait fixed to r1 after record-table reordering, each order table's capability selection, empty explicit upgrades, forbidden downgrades, legacy empty-field injection and new-tag laundering, required v3 fields, queue/resource/record ID mismatch, strict generation AccessRef/InvokeBoundaryStateEffect/Unresolved variants, exact completion indices, RecordedPrefix ID/QueueStart/Unresolved variants, wait selection/gap variants, query-only tag rejection, missing/extra fields and private nested mutation.

## Limits

The new helper is explicitly a constructor/serialization witness; it does not establish source/native correspondence or validate physical ordering. Codec success cannot prove FIFO, event generation truth, queue-wait placement, dependency graph consistency, visibility, completion, content readiness, quiescence/free or transformation authority. Those graph/protocol rules remain in root's separate validator/query/gate work. No full suite, GPU/LeWM run, provider execution, installation or commit/push occurred. Git was used only for the authorized read-only historical archive.

## Frozen owned SHA256

- `scar/ir/execution/codec.py`: `1835a75c44b039a02a7ff79535e78786318ac37dd0e0e6bbf122e1d8f8d61ea4`
- `tests/unit/test_execution_order_codec.py`: `0ab7be56081707bfd85757f337aed91292b4d6db933cd80ec9a18f9f6088213d`
- `tests/unit/test_execution_codec.py`: `b35bde9b25e3058bc035855a7ebedeef89fb08ed8583f0d283e106932aeff0f9`
- `tests/unit/test_execution_work_codec.py`: `fe7a72118bf1269ca4de59c31badb282359d8346334092a8f792137360195bdd`
- `tests/fixtures/execution_v2_frozen.json`: `b03a304a582a662d71ebdbe4685776aef9ec4fc357142f0fa2e6656cdae03234`
- `tests/fixtures/execution_v2_frozen.proof.json`: `4552256870cc07589f1d7e15851758295b43048a1915db307be2f5d538dfb948`
