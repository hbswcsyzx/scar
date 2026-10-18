# Input origin routes: bounded implementation receipt

This receipt covers only the owned `input_origins.py`, its fixture, and two
focused unit files. It does not close the broader protocol or runtime/source
association work.

## Implemented shape

- `input_origins(graph, operation_id, use_id, budget=4096)` checks exact IDs
  and a positive exact-int budget, creates one `ProgramIndex`, then delegates
  to `_input_origins(index, operation_id, use_id, *, accounting)`.
- `_input_origins` reuses an already validated index and a caller-owned
  `ValidityBudget`; it does not construct a second `ProgramIndex`. Its private
  shared-flow helper lets paired traces reuse the same `ProtocolFlow` cache.
- Raw definition rows, each raw operand, each literal-evaluation row, each
  matching Suspend/BodyResume candidate, and each pair candidate are charged
  before extending the result. Truncation returns the current cursor and
  pending counts/coordinates.
- `paired_input_origins(index, left, right, *, budget=None, accounting=None)`
  accepts exact `OwnedUse` endpoints. Its narrow pairing scope is
  `RAW_REQUEST_PACK_OPERAND_ONLY`: `left` carries a raw request and `right`
  must be the exact pack operand named by that request's original
  `RawRequestDefinition`. It is not an AdmissionPredicate input join and does
  not establish a raw-request/`is None` relation.
- A pair key retains both sides' full supplied
  `CALL_ACTUAL_TO_FORMAL` keys (caller, caller region, callee, ordinal,
  actual UseID, formal ValueID) plus original CFG edge identities. A route
  that cannot be rooted at the supplied program entry leaves
  `raw_pack_caller_context_unresolved`; it does not pair on a ValueID or
  ordinal alone.
- The loop fixture keeps its original backedge and unselected-visit gap. All
  source/runtime/identity/transformation flags remain false; supplied static
  caller scope remains explicitly incomplete.

## Focused attempts

Commands were run after `source /home/zyf/miniconda3/etc/profile.d/conda.sh`
and `conda activate lewm`, with `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.`.

- `origin_routes/attempt006`: exit 2 during collection. The newly added test
  imported `LiteralEvaluation` from `literal_sources`; the actual class is in
  `program.model`. This was a test import mistake. The original command,
  environment, stdout, stderr, and JUnit output are retained unchanged.
- `origin_routes/attempt007`: exit 0, **15 passed**. It includes the existing
  source-route cases, exact pair positive, wrong-caller negative, shared
  recursive-callee gap, original loop-edge preservation, raw operand and
  literal-row budget cursors, and private-helper/index reuse checks. Exact
  command, source snapshots, stdout/stderr, and JUnit output are retained.

No full suite, component gate, GPU, or runtime workload was run for this
change. Resume-candidate charging is present in the bounded implementation;
this focused fixture set does not exercise a BodyResume candidate.

## Final owned-file SHA-256

```text
8d958396586b3d17788c628a4b63ef059983a577182435722f25b74ab49082ef  scar/ir/program/input_origins.py
bde0efc64ae037455365140528138b9e42670b0ca0fd1be98fff8e0e47319ec2  tests/fixtures/program_input_origin_graphs.py
0ed11028ff40850ce8ac3784090770d1af791311a1a7107c4e68e595fd509aeb  tests/unit/test_program_input_origins.py
7cf8956439b31079d3eadcc54dcbda1099b416ead3c91d0aa3c8f100ce14e750  tests/unit/test_program_input_origin_pairs.py
```
