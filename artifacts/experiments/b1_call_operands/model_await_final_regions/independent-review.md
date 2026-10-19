# Independent finite review and frozen author ownership

Root authored product and documentation; only root executed interpreters,
tests, probes and archive checks. A/C authored new static/execution fixtures
and tests; B authored independent boundary tests. They never ran Python or
pytest. All authors froze before each root run. All previous files under
tests/ remain unchanged from f35939ad9d91572d51e1e0d3d928d6ecc0f0647c.

## Findings and resolution

1. A identified output-local prefix completion: a budget failure at the
   second required terminal could leave a True prefix DECLARED. Each output
   now has enumeration_complete, cleared on failed exit/terminal/witness
   work. DECLARED requires completed enumeration and every original terminal.
   A independently authored one two-terminal regression, which passed.
2. B identified unpaid derived scans: frame filtering, frame/call indexes,
   quadratic ordinary-input matching and witness aggregation/copies. These
   now charge before traversal, use one linear Use lookup and incremental
   witness OR, and reuse prepared complete unknown input templates on failure.
3. B identified may-input promotion: an own result can return unchanged even
   if the same primitive sometimes receives a different packet. input_support
   and contribution are now separate; must source input plus own-result copy
   are required for an unconditional contribution. B's independent legal
   P/Q merge case passed, preserving the output-copy True but not coverage.
4. Root identified static outputs being exposed as dynamic receipts, plus
   missing input-gap aggregation. Execution outputs now select this exact
   root frame completion and actual terminal/value/dynamic witness. Frame and
   stage input gaps propagate. C independently tested complete state outputs,
   a missing outer return, and a missing state terminal Use against a complete
   sibling. All passed after fixing one new-test ID selector.

Final finite source review, with no extra interpreter execution:

- A/B reviewed program/region_implementation.py at
  06ae780292613cd76784fdc6590b496e8d20738da182b15ff3f9d0ae4dcac39e:
  exact frame parent, full N/R/state slots, independent input and result
  support, per-terminal OR / all-terminals AND and budget completeness.
- A/B reviewed program/copy_consumers.py at
  cba94fd9eda8b291d5ede409dad832de54f0f44377f2249bf87efc85ea32e811:
  only original ordered argument/Use templates prepared once, no return join
  or new copy producer introduced.
- C reviewed execution/region_implementation.py at
  30f6193deda3ae56f0a7129be72560b5fefe30118623da55c507ed8542c926dd:
  exact caller-to-CallActivation descent, original completion/slot validation,
  actual output witnesses, missing capture and independent sibling isolation.

The reviewers reported no remaining blocker within these finite scopes.
Their source reviews do not grant complete A-H/16 or runtime/native semantics.
Dynamic new positive child paths cover zero cut only, depth1 NORMAL/depth2
RAISE; static two-cut and old dynamic two-cut evidence do not close that gap.

## Final newly authored inputs

| File | SHA256 |
| --- | --- |
| tests/fixtures/program_await_final_region_graphs.py | 54f3a56a2b7b8658513fae5ec787b95976691e890aa57ffcf98a4dd5c9f1c1f6 |
| tests/unit/test_program_await_final_regions.py | 7534141aa8181c939d2fff0e6518a0d2b01523715c8cdff0345be37f924df9c8 |
| tests/fixtures/execution_await_final_region_graphs.py | d243df8d8d1affd24157d9450d2a0f3e9d9985ec5374e3c1cec9b5d20e1416e1 |
| tests/unit/test_execution_await_final_regions.py | 0de93283efa66e8f31a072ad511d30e10d247dfdb511cc02aaca5b707a78b41c |
| tests/unit/test_program_await_final_region_boundaries.py | f12e0aaa6a3df0ed7eedec3611fd0cf9ba32804be2e2c1f9c4a05e20bf76d32e |
| tests/unit/test_program_await_final_region_input_support.py | 43b0a09f534e3cb4ac114e5630a65bfb1cead8ace422ef2a6b9ccb5f0b55e05b |
| tests/unit/test_program_await_final_region_output_budget.py | 17ca93c0445766e5eebe12a51e215b25f58529fb94e14728224d2ccbd304e477 |
| tests/unit/test_execution_await_final_region_output_evidence.py | c408c78692ae79f351dbb70abb32254c58ccb4e29a16507204b37cb20e401fa6 |
