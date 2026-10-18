# Body execution CLI receipt

Status: **FROZEN — 24 focused PASS**, not whole P3/full/native acceptance.

## Public command and scope

```text
scar query-body-execution PROGRAM EXECUTION
  (--drive exec_operation_occurrence:<value> |
   --activation exec_region_activation:<value>)
  [--budget 4096] [--out PATH]
```

The new thin `execution.cli` module reads both UTF-8 documents with the original
strict program/execution codecs and calls the existing ExecutionIndex queries.
The root CLI has only a parser increment and lazy delegate. It never imports or
executes the supplied program, resolves no automatic external catalog, and adds
no collector, provider, backend, detector or native authority.

Original Identifier values retain their kind/value/wire record encoding. View
map keys such as `origin.captures` use the original full ID wire, with a collision
guard; record values reuse the existing `record_codec.encode`. This is a JSON
report projection, not another graph/record codec.

The original query status is preserved inside `query`. Fresh global diagnostics
come from `view['validation_gaps']`, separately from per-binding/route gaps. When
the original view is DECLARED but validation gaps remain, the top report says
PARTIAL. Both top-level authority flags remain false. Errors report ERROR and
return 2. `--out` is rejected if it resolves to, or is an existing hardlink of,
either input; path protection happens before loading or writing.

## Actual attempts (all retained)

Commands used, replacing NNN with 001/002/003:

```sh
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python \
  artifacts/experiments/b1_call_operands/model_body_occurrence/run_focus.py \
  cli/attemptNNN tests/unit/test_execution_body_cli.py
```

The runner records the exact interpreter (`lewm` Python3.14.7), command,
stdout/stderr, JUnit, exit, wall duration, registered-source maps and changed
paths independently for each attempt.

| Attempt | Actual result | Meaning |
| --- | --- | --- |
| 001 | exit1, 21P/3F, pytest3.97s, wall4.676s | Tests expected absent external catalogs to be visible as PARTIAL. Original query could remain DECLARED with empty local gaps; CLI initially omitted the separate global diagnostics. Original failure retained. |
| 002 | exit0, 24P, pytest4.34s, wall5.064s | CLI separately exposed construction report gaps and preserved query DECLARED while top-level PARTIAL. Historical pass, superseded by fresh diagnostic hookup below. |
| 003 | exit0, 24P, pytest3.93s, wall4.596s | Final CLI uses root's new fresh `view.validation_gaps`, not construction-time `index.report`; tests verify the exact projected diagnostics and missing catalog gap. |

Attempt003 registered-source fingerprint before and after:
`419488a11cb13282e34d9e49afc04278df44a4ab3087103f349eea7d39263fe2`;
`source_unchanged=true`, `changed_paths=[]`.
Earlier attempts' registered sources were also unchanged during each run.
The 24 final cases are the same set across attempts, not cumulative 69 cases.

## Verification boundary

All cases call `scar.cli.main(argv)` using real canonical codec files from B's
frozen resumable fixture. They cover Start and Resume drive IDs, activation
capture-key namespaces, budget1 with full input/output/capture denominators and
cursor, independently missing entry/outcome, strict prefix and known wrong-kind
IDs, absent IDs, malformed JSON/duplicate key/unknown field, output to either
input or a resolved symlink, successful machine output, invalid budget, exact
preservation of both input byte streams and false authority flags.

No external catalog was fabricated to turn identity declarations into a proof.
No whole P3 protocol, runtime instance identity, materialization, readiness,
native thread behavior, transformation or M0–M2 completion is asserted.
No component/full/GPU/LeWM workload or native witness was run.

## Frozen source SHA256

| File | SHA256 |
| --- | --- |
| `scar/cli.py` (minimal parser/delegate increment) | `40ed6ece6a10e7c2bfc23afe4dcdc80eba71bd64b8ba8a163a1da2d5325ad7f5` |
| `scar/ir/execution/cli.py` (new) | `28d6c8729b6caa52ddc8238453b4933fb88369ad03a669831e7211be03f14baa` |
| `tests/unit/test_execution_body_cli.py` (new) | `b97d638e9854142f42c7fd221a3d9eb96f6748a82016cc74653e991893f7ccd5` |
| `scar/ir/execution/resumable_query.py` (root, fresh diagnostic interface consumed) | `bafc2331433dfb025d5f9db2833812de98b10f84b2d4e522e09de1ca6fdb1fd5` |

All owned source/test writing and test execution stopped after attempt003.
