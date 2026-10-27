# C2F body outcome frontier: focused result

Scope: the derived `ProgramIndex.body_outcomes(region_id, start=None)` query and its private first-outcome traversal helper. This is a structural query over an already validated graph. It follows ordinary CFG successors, reports first `SUSPEND`/`RETURN`/`RAISE` operations, and does not traverse a suspension's temporal successor. A resumable body can return an empty frontier when its current drive diverges; this says nothing about termination or absence of effects.

The helper now reads only the final operation of each validated block. An empty block or missing final terminator fails fast. Query results reuse canonical `UseSite` objects from `ProgramIndex`; suspension results expose exported and handoff uses, not saved/private operands. The query leaves graph values and their producer origins unchanged. This adds no runtime, source, or transformation authority.

## Runs

Environment: CPython 3.14.7, pytest 9.1.1, conda environment `lewm`, `PYTHONDONTWRITEBYTECODE=1`, `PYTHONPATH=.`.

- `initial/`: 6 passed, 1 failed. The hand-built diverging fixture omitted the region's world state argument; core validation correctly rejected it with `state_parameters`. This was a fixture defect.
- `attempt2/`: after forwarding world state through the loop, 7 passed.
- `final/`: after the final helper and canonical-UseSite assertions, 7 passed in 0.39s. Exact command is in `final/command.txt`; full stdout/stderr is in `final/output.log`; JUnit is in `final/junit.xml`.

No full suite, target workload, LeWM, GPU, or runtime driver was run for this focused query change.

## Final source SHA-256

- `scar/ir/program/resumption_flow.py`: `c7c6b5c8e6d84d568fa87e52f71f9b66a6c1a50930633d0e97ea8613ce014cbc`
- `scar/ir/program/queries.py`: `7cb8fe59dee3bff30030ecf96ba05015c14f4d3c62530d0f2a51a9474ab7a05e`
- `tests/unit/test_body_outcome_frontier.py`: `375bbb7a561058a2c73394042676d16f4de9cd2d1ae00f7daf2ae4c5facede27`

Final test output SHA-256: `9c2bc789bf2cba75cc5ed822cd3fccab9cf3d7a226611daf566ceea5ed0c55b1`.
