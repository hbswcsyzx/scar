# C2 resumable-body wire / CLI component

Read/implemented against the frozen field contract in `docs/M1_RESUMPTION_BODY_COMPONENT.md`. Source tree was `/tmp/scar-structured-model-280qf4mi`, base `b4bc1a4`; I changed only `scar/ir/program/codec.py`, `scar/cli.py`, the two assigned test files, and the isolated v9 golden/proof fixture pair. The root/records/validator files were concurrently owned elsewhere and are not part of this change.

## Wire behavior

- v10 is selected when a valid graph carries any resumable-body table, exact `SuspendTerminator`, `FRAME_CONTEXT`/`DRIVE_CALLER_CONTEXT` value or type, or saved/resume projection. The v10 envelope contains the four new tables.
- `SuspendTerminator` is encoded with the exact `kind: SUSPEND` discriminator; v10 decoding accepts that tag together with the existing C1 `CLEANUP_ROUTE` tag. C0's old dispatch shape is untouched.
- v1–v9 field sets still exclude all four new tables. Loading those versions rejects the SUSPEND tag, the new context protocol kinds, and any new table. v10 with no resumption marker, or with a marker but no explicit `ResumableBody`, is rejected.
- Non-resumption graphs are filtered back to the historical field set; the archived v9 C1 fixture round-trips byte for byte.

## CLI behavior

`check-program` reports `resumable_bodies`, `suspensions`, and `frame_context_actions` after `loads()` has completed full validation. `body_structure_validated` defaults to false and becomes true only for a fully valid graph declaring resumable bodies. `body_driver_verified`, `body_source_verified`, `body_runtime_verified`, `body_exclusivity_verified`, `source_recovery`, and `transformation_authorized` remain false.

## v9 golden provenance

`tests/fixtures/program_graph_v9_frozen.json` was generated with the isolated `git archive b4bc1a4` tree and that revision's codec, using `tests.fixtures.program_cleanup_graphs.resume_multistate_graph`; it was not generated with the modified codec. The logical wire SHA256 excludes the single terminal newline; the fixture file SHA256 includes it. See the adjacent `.proof.json` for the exact codec and payload hashes.

## Owned tests

Attempt 1 is preserved under `body-wire/initial/`:

```text
PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 python -m pytest -q tests/unit/test_program_resumption_codec.py tests/integration/test_resumption_program_cli.py --junitxml=artifacts/experiments/b1_call_operands/model_resume_interfaces/body-wire/initial/results.xml
60 passed in 1.74s
```

After adding the concrete downgrade guard for a v10 marker with its `ResumableBody` table removed, attempt 2 is preserved separately under `body-wire/attempt2/`:

```text
PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 python -m pytest -q tests/unit/test_program_resumption_codec.py tests/integration/test_resumption_program_cli.py --junitxml=artifacts/experiments/b1_call_operands/model_resume_interfaces/body-wire/attempt2/results.xml
60 passed in 1.72s
```

Both attempts used `conda activate lewm`. `git diff --check` passed on the four owned source/test files. No full suite, LeWM run, install, or commit was performed.
