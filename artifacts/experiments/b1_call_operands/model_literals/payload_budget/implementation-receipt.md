# L1 Literal Payload Implementation Receipt

This receipt records only the owned literal payload/legacy-boundary work. It is
not a full-suite or M1 completion claim.

## Implemented

- `PythonLiteral.from_python(value, exact=False)` keeps historic kinds by
  default; `exact=True` adds binary64-pair `COMPLEX128` and lossless
  `STR_CODEPOINTS` for strings containing surrogates.
- Added iterative, shared fixed-budget checks for materialized trees, wire
  trees, conversion, generic record encoding/decoding, and v2 wire validation.
  Shared subtrees are charged by expansion; cycles are rejected. Integer
  conversion uses bounded base-1e9 chunks without changing Python's global
  integer-string setting.
- Added `literal_builtin_type`, `require_exact_literal`, and
  `require_legacy_literal`. Legacy SourceSemantics/OIR paths keep raw surrogate
  `STR` behavior and reject only `COMPLEX128` and `STR_CODEPOINTS`; the exact
  profile rejects raw-surrogate `STR` and requires `STR_CODEPOINTS`.
- Both legacy source frontends explicitly use `exact=False`.

The frozen plan uses root depth zero with maximum depth 64. An earlier L0 draft
used root depth one; implementation follows the frozen plan. This receipt does
not claim that adjacent raw surrogate pairs in legacy JSON are lossless.

## Focused attempts

All five owned pytest attempts used the required `lewm` environment and the
same focused command. No owned test attempt failed. Attempts 001–004 predate
the boundedness and nested-tag review findings below; attempt 005 is the final
post-fix run.

```text
source /home/zyf/miniconda3/etc/profile.d/conda.sh && conda activate lewm && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python artifacts/experiments/b1_call_operands/model_literals/focus.py payload_budget tests/unit/test_literal_payloads.py tests/unit/test_literal_codec_boundaries.py
```

| Attempt | Result | Change in coverage |
| --- | --- | --- |
| 001 | 19 passed | Initial bounded exact/legacy payload and codec cases. |
| 002 | 22 passed | Added bit-preserving complex values and exact budget boundaries. |
| 003 | 22 passed | Added mutated OIR record writer guard. |
| 004 | 22 passed | Added nested codepoint type/legacy checks and cyclic wire rejection. |
| 005 | 25 passed | Added early string-length guard, scheduled-node budget precedence for materialized/Python/wire trees, and nested generic record-tag roundtrip/rejections. |

The original B-side import traceback for tuple preflight (`size` was not
initialized for tuple values) was preserved by that agent; the tuple branch
was fixed before owned attempt 001. A metadata-only shell command accidentally
called an unavailable, unactivated `python` executable and returned
`command not found`; no Python code ran. Attempt reports and commands remain
under `payload_budget/attempt001` through `attempt005`.

## Review follow-up

Root source review found two budget-preflight risks: an oversized exact string
could be scanned for surrogates before the cheap length rejection, and the
iterative preflights bounded expanded nodes but could queue unexpanded siblings
past the node budget. These were fixed by checking string length before the
surrogate scan and accounting for all scheduled occurrences before pushing
children. Attempt 005 includes regressions for both; the fanout fixture asserts
node-budget rejection before descending into its over-depth child for Python,
materialized-record, and wire trees.

A separate source review found generic record tags were stripped only from the
root PythonLiteral before decoding, leaving nested tagged literals rejected.
The generic codec now passes the locally registered exact tag through the
bounded iterative decoder at every node. Attempt 005 verifies nested roundtrip,
wrong/missing child tags, and strict untagged shape rejection. This was a source
finding followed by a post-fix regression; no pre-fix runtime attempt was made.

## Final owned source hashes

```text
a2ef2cb826378d034143134f3c85f0e3fb91c9adb67415ce88e74b64812f24f9  scar/ir/literals.py
0954c05e53a6dcb31f449461db71c63fdcdd9f95a9c053424d86bf5217a89ef3  scar/ir/record_codec.py
f1c640101d6d9ffc8baa7a647cad2862353fcdcd196c698f1f97b7764be04ede  scar/ir/v2/_validation.py
25cb12cdb94e0e907d4dee649812a14da038ce2d8fc5226733170cbfcb5d6147  scar/ir/v2/codec.py
5d943b7d48b159cfb8512ffff228236aee29d3c4f795ff0319d44489a81a4094  scar/ir/semantics_v2.py
429313a4b30d82fb0dbbb908d48caec5d4849142ac72cc1ab10cdf2bd919620f  scar/ir/v2/optimization.py
2c20b09a3affc372f1103904bdf100dd3e0963c6ed89463bd57dbcae1e512a96  scar/analysis/source_semantics_v2.py
acc97151e208982c35ef0c49dc8b45105508f202aab97ec008f189cc861e7dfc  scar/analysis/local_statement_semantics_v2.py
3c776d7d5c86ffd5242806bbf4d5f870b7d28e41caccc92149920550e74a21f0  tests/unit/test_literal_payloads.py
b99d4b1857abf9843b20f953fe95a81dbdd21e514f0efdf69afd81d97127794d  tests/unit/test_literal_codec_boundaries.py
```

Only the two listed owned unit files were run. No full suite, backend, GPU, or
LeWM workload was run by this task.
