# Protocol ledger review

Status: the owned focused ledger test passed after correcting one fixture lookup. This file records a bounded public-ledger review; it does not claim runtime or source-profile verification, and these six tests are not the complete P2 matrix.

## Findings

- `required_clauses(profile)` supplies a fixed clause denominator. `protocol_obligations` preserves it when rows are missing and emits `SOURCE_SCOPE_INVENTORY_UNRESOLVED`; an absent scope is not evidence that no protocol exists.
- The exact edge ledger must come from original INVOKE successors, not the number of protocol rows. The reviewed query now derives `(operation, successor_index)` bindings from each known invoke helper row. Removing the RAISE row while retaining NORMAL must leave the RAISE edge as `MISSING`, set the clause to `PARTIAL`, and retain `protocol_required_edge_unbound`.
- A `ContractResult` may cross scopes when it names a real producer row, so the negative case targets an existing row in another scope but supplies a result port other than that row's own port. This tests the producer-key/own-result join without banning legitimate cross-scope references.
- `GENERATOR_RETURN_TO_STOP_ITERATION` consumes a body `DriveResult`. A request-processing helper result cannot satisfy that role even if it is another valid protocol result port.
- Rule-table construction is now closed after import: `ALLOWED_RULES` remains a `MappingProxyType`, and module bindings `_allow` and `_allowed` are deleted so callers cannot mutate its backing dictionary through the builder.

## Owned tests

`tests/unit/test_program_protocol_ledger.py` covers the exact INVOKE RAISE slot, fixed clauses after row deletion, budget-one denominator/cursor, wrong cross-scope result port, wrong generator adapter source role, unresolved source inventory, and hidden rule-table builders.

Focused execution used Python 3.14.7 after sourcing Conda and activating `lewm`:

- `ledger-attempt001`: 5 passed, 1 failed. The failure was a test-only fixture typo (`ProgramGraph.region` instead of `ProgramGraph.regions[0].id`). The original command, output, JUnit, exit code, and source hashes are preserved.
- `ledger-attempt002`: 6 passed in 0.64 seconds. The typo was corrected. Source-before and source-after hashes match. The exact command and raw logs are preserved under `artifacts/experiments/b1_call_operands/model_protocol_implementation/attempts/ledger-attempt002/`.

These cases verify the public ledger joins and role guards above. They do not close unimplemented protocol families, source inventory completeness, native applicability, or the full P2 acceptance denominator.

## Reviewed source hashes

| File | SHA-256 |
|---|---|
| `scar/ir/program/protocols.py` | `9dd2832716269f86ce9f98b73dea6a634caa084a18d0f974ccaec401322dcacb` |
| `scar/ir/program/protocol_rules.py` | `e72627e8d6b2ab215e057c29f8f2774e8484da16b26960af6d6d3d99a3f35064` |
| `scar/ir/program/protocol_flow.py` | `3410733f931ba9f15340ea4af30f7f5b92860258a00d94ad78d60250b455c4bd` |
| `scar/ir/program/protocol_validation.py` | `72f7ec09256c0c46496ee6751da33a71e8055354703542d6946ffdb2e402ca3e` |
| `scar/ir/program/protocol_query.py` | `15c3e4dbfb80a6732fc391b9760efb505969d5b79073db3dcd6ab23a244005b0` |
| `scar/ir/program/queries.py` | `94139fe8dda97b52d98aaa62f927871af2c98618786a822b673550a549ca7e97` |
| `tests/fixtures/program_protocol_graphs.py` | `7e15b2955336a0f82e406189ae7ec55c6dc12dbfbb25f7c20660c2f8a50110e9` |
| `tests/unit/test_program_protocol_ledger.py` | `41e8a82b18790cd3e07324d1135802575c815cc5f6afc8b6fdc1c2310a1ff5ce` |

No full suite, component gate, or workload was run here.
