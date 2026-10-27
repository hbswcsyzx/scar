# R3.1 call wire and historical compatibility receipt

## Status and scope

**FOCUSED_PASS; owned product/tests frozen.** This is wire/constructor capability checking,
not dynamic call validation, runtime pairing, full R3 composition, native semantics, or
transformation authority. No full regression, GPU, LeWM workload, capture, install or commit
was run by this agent. The independent design report is
`design/lifecycle-resources.md`, SHA256
`2368b67afbc4702cc16192799bb12eac4afb536450f2a7778e82cfeee4528a71`.

## Product changes

- `scar/ir/execution/codec.py`: maximum capability v7; `call_activations` is reachable only
  in v7's closed type vocabulary, auto-selects v7 only when nonempty, rejects downgrade
  with populated calls, permits explicit v7 with empty calls. Older versions omit this
  table on encode and supply its empty default on decode. Empty defaults are migration,
  never evidence that no call occurred. Existing field order/tags/JSON formatting remain.
- `scar/ir/execution/__init__.py`: public exact `CallActivation` and `CallActivationID`.
- No record, ID, model, validation, query or source-inventory implementation edited.

The codec does not join arguments/results/state or resolve facts. The new table references
existing caller/activation/entry/completion IDs; graph-wide checking belongs to the caller
validator. New wire-only test declarations deliberately do not assert valid physical graphs.

## Necessary old test migrations (all original case IDs retained)

| File | Exact migration |
| --- | --- |
| test_execution_validity_codec.py | Keep auto schema exactly 6; decouple maximum support as `SCHEMA_VERSION >= 7`. All old v1–v5 tag/table/downgrade and v6 nested checks retained. |
| test_execution_production_codec.py | Historical `test_schema_version_six_remains_unsupported` name retained; its next-unsupported value moves 7→8, bool/string rejection retained. |
| test_execution_content_codec.py | Unsupported upper version 7→8; bool/zero/string checks retained. |
| test_execution_work_codec.py | Existing `[7]` case becomes explicit newer-empty-version roundtrip like previous versions; add `[8]` rejection. |
| test_execution_order_codec.py | Existing loop keeps 7 and verifies explicit-empty-capability roundtrip; adds 8 rejection. |

New `test_execution_call_codec.py` covers v7 typed/Unresolved/FactSource variants, six
independent old golden bytes and lowest-capability selection, empty explicit-v7 migration,
populated calls rejected in every old schema, unreachable CallActivation/CallActivationID
tags in each old vocabulary, extra/missing tables/fields, wrong union-ID families,
namespace/wire/bool mutations, subclass/false-like local mutation, version strictness and
absence of artifact opening/graph-validation side effects.

## Independent v6 golden

Generated **once**, successfully, from immutable revision
`348d18277b963bc183fb420bf173f05594d667d8` using its original codec and original
`tests/fixtures/execution_validity_records.py:validity_record_model` (codec-only rich
declaration, not claimed valid execution).

- New payload: `tests/fixtures/execution_v6_frozen.json`, **94738 bytes**, SHA256
  `fa27345cfc12c97865e975206099970e61621b0689f60967fc6445045a96a570`.
- Proof: `tests/fixtures/execution_v6_frozen.json.proof.json`, SHA256
  `55e3bf39f26ae82689844f5acb3eba5595953dc7565160ae67f4a719995b165f`.
- Old codec SHA256 `b8520a675e5c07d1a6c6cfbba1d1efea790c445535fef4c2e3897d5b2bea7580`;
  old fixture SHA256 `a2c99cd2f7deba2c8aa1e03118d9d09476049082c15cd39ef5a78b1ec339d83c`.
- All four old validity tables populated: establishments2, target events2, orders2,
  supports7. No new call table was present on the old model.
- Generator exports only demanded immutable source blobs (`git show REV:path`) into its
  own temporary directory. Child verifies every imported `scar` module is under that
  directory and roundtrips with **old** v6 codec. The proof retains hashes for the actual
  imported closure plus original v5 input golden. No current checkout module is imported
  in the child and no protected worktree/checkout is created. Owned temporary directory
  removed after the child exited; no old golden changed.
- Generator `codec_golden/generate_v6.py` SHA256
  `1e01191a4c06f1ccac119cdb54c93e8658515b8d779db12e9aa5019e0ae27727`.
  Exact child command, environment, stdout/stderr/exit/proof and cleanup receipt retained
  in `codec_golden/attempt001/`; success, generator wall time **1.01970986 s**.

Generation command, executed from the task worktree:

```sh
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python artifacts/experiments/b1_call_operands/model_resource_composition/codec_golden/generate_v6.py
```

## First and final focused run

One run only: **243 passed in 4.89 s**, exit0; wrapper wall **5.5757177146 s**.
Environment: conda lewm Python **3.14.7**, PYTHONPATH exact task root,
PYTHONDONTWRITEBYTECODE=1, pytest no cacheprovider, owned basetemp cleaned after exit.
Exact command/first stdout/stderr/JUnit/source.before/source.after/report are retained at
`codec_wire/attempt001/`. No failed focused attempt exists to hide or overwrite.

```sh
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python artifacts/experiments/b1_call_operands/model_resource_composition/focus.py codec_wire tests/unit/test_execution_call_codec.py tests/unit/test_execution_validity_codec.py tests/unit/test_execution_production_codec.py tests/unit/test_execution_content_codec.py tests/unit/test_execution_order_codec.py tests/unit/test_execution_work_codec.py tests/unit/test_execution_codec.py
```

The 243 cases are the combined focused selection, not a modeling-coverage percentage,
not a full-suite result, and not additive to another run. Peer files could still be edited
during focused development; the later root component/frozen gate owns a whole-source claim.

## Frozen owned source hashes

| File | SHA256 |
| --- | --- |
| scar/ir/execution/codec.py | 90b6499f128fc1e716549c34de5ff42546d9d7af8554659499913004e5359be3 |
| scar/ir/execution/__init__.py | 05cfe31e4b30650c28aa25ddf93457b07b916007fa3da8f872c15eb86d71ac86 |
| tests/unit/test_execution_call_codec.py | 238bd6bf2a623bfe8e36af11ef1cce42bfcb0566d4e55d6e784315549ab79f12 |
| tests/unit/test_execution_validity_codec.py | 816276dff57dac27fe7dad46c3edfbbc78729494ed69018cc126e7812541b5ec |
| tests/unit/test_execution_production_codec.py | c4c81b85a0e9ced5b4ce489b6ce0ec83aa505485e9aff7e35bd016a6a040987e |
| tests/unit/test_execution_content_codec.py | b56a24c9ef912976c44497ae8ca74f7916083506aa999368b06a70ea00bfc9a3 |
| tests/unit/test_execution_order_codec.py | ba192b0eaefa977f35fa6f950e3c67e97cf6bc19e01fd31ea8925cffbe6c591f |
| tests/unit/test_execution_work_codec.py | 189cc2b17cc81f3f1eb17b457285e6ac78811c6ea5c9f07878db19992e8b126e |

Next: independent read-only review of other authors' call association/flow/query after
their freeze. This agent does not self-certify those graph relations from wire tests.
