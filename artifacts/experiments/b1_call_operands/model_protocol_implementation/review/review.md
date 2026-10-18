# P4.2 protocol-connection review and schema-19 receipt

## Scope

This bounded review covers the ProgramGraph P4.2 protocol-connection records, codec capability selection, original-port connection validation/query, and the ten stale global schema-version expectations. It is not a full P4 family acceptance, source/native applicability check, or runtime-equivalence proof.

Reviewed contract: `docs/M1_PROTOCOL_CONNECTION_CONTRACT.md`, SHA-256 `f8ec4ed141c5e9d8d25a201b9f978ea1b93d81d72a0dab9466d3fef33fa17eb8`.

## Global version assertion migration

Only the ten global `SCHEMA_VERSION == 18` assertions were changed to `19`. The per-graph wire versions and fixture bytes remain as before:

| Test file | Global assertion | Preserved graph wire version |
|---|---:|---:|
| `tests/unit/test_program_state_address_codec.py` | 19 | 15 |
| `tests/unit/test_program_literal_codec.py` | 19 | 16 |
| `tests/unit/test_program_admission_codec.py` | 19 | 18 |
| `tests/unit/test_program_no_body_codec.py` | 19 | 13 |
| `tests/unit/test_program_protocol_codec.py` | 19 | 17 |
| `tests/unit/test_program_session_release_codec.py` | 19 | 14 |
| `tests/unit/test_program_driver_codec.py` | 19 | 11 |
| `tests/unit/test_program_publication_codec.py` | 19 | 12 |
| `tests/unit/test_program_resumption_codec.py` | 19 | 10 |
| `tests/unit/test_lifecycle_composition_codec.py` | 19 | 14 (the frozen D2.3 wire) |

The admission test’s former chained assertion was split into `SCHEMA_VERSION == 19` and `document["schema_version"] == 18`; its actual fixture still selects the historical v18 wire. No fixture was edited. A repository search found no other `SCHEMA_VERSION == 18` assertion.

The original content hashes from `HEAD add4ba84c9529e1f864e4029bd7c145cfacdfafc` and current hashes are:

| File | Original SHA-256 | Current SHA-256 |
|---|---|---|
| `tests/unit/test_program_state_address_codec.py` | `d4f6fbb04f3ce1a38d0aef106bef766f84a0b0d0a4f7a1ea4f04b5bd3745ad4e` | `3b8f33ae312df0623445db88a1b6403996145c762f51cd5163415525a49abe87` |
| `tests/unit/test_program_literal_codec.py` | `866138fbb72ff63c37876eeafe6191d90a2fba98e5697d8647b1772d9d6ab133` | `03d13bb2d6ec55cb40286f5e7f54a2022a057d11357573c92061e787d37c1650` |
| `tests/unit/test_program_admission_codec.py` | `48dc867541d648e046c7ece96ba65ee993a923a32f7635e13d5af35869e1e243` | `2235e2e557d32dc16ea833f9f04cbac87a0f96fa5319b3b36f81963cbf622c57` |
| `tests/unit/test_program_no_body_codec.py` | `ecb680b79b0e58ee7f55157f8e6eccaebee7c10cb0cdcb2073bfbc1412975d00` | `2b046d3f640ce6ba395d60090aeb95ae4f45209dd894022a96b73eb85da4cb56` |
| `tests/unit/test_program_protocol_codec.py` | `148f4a81b4387f156c931b1fafead4301a126539822781bd2823ca0072493de8` | `fda20bc8df95f45ce5bba64e916867c520c647e3d7b86af4139a4a8897f7e70d` |
| `tests/unit/test_program_session_release_codec.py` | `fad3d50f698d8563c8b59f1bf8a408d2cba594f04a59640dce4d8d34e3d0bdec` | `55cfd1415d01534c594441276876fbe79f40793ca4ff74867d69de14f8c0fb2f` |
| `tests/unit/test_program_driver_codec.py` | `0f160e9776a590a0f6355099c1ba0afa3caf75b0e7a5596ea34eca6ddee42a04` | `daa4b133f410921b3bdaf2ccd5f5c9b2a7e5e414bcf2581f1a9b4eebac28f5b3` |
| `tests/unit/test_program_publication_codec.py` | `615297f4e6c2ad2845a46532e6c3ab6d2a25c156b8f6ab80517ef2506812c0a2` | `794a31659952abdda4959ccfe698af17f3a837193940664a61fdb1ebff1ec44e` |
| `tests/unit/test_program_resumption_codec.py` | `02fecc8a9977cd5b02254d5298e4a0e3a39bd145c0e851f1ea1e7c891c3d2f88` | `9cfc55a4250cd042d85087125fbcd26ad96fabc79344ed8b1079d098cefe4f1b` |
| `tests/unit/test_lifecycle_composition_codec.py` | `9c107f7101b786a4c780ebf9717ed78e94356b51a50e42b406d53d940fa6db18` | `3868b6f42368d3353ea375578f035b28c0e1adb08bb0c97d77026d9721de8796` |

## P4.2 record/codec implementation summary

`scar/ir/program/protocol_connections.py` adds exact frozen connection records and closed unions for expected call inputs, result-consumer declarations, request/session association, task target/status, and cancellation links. `ProgramGraph` adds default-empty `protocol_call_inputs`, `protocol_result_consumers`, and `protocol_bindings` with exact tuple, nested-record, and natural-key checks. Expected ports reuse canonical `OwnedUse`, `BlockArgument`, `OperationResult`, `InvokeLiteralResult`, `DriveOutcomeRef`, and original control/state records; these records do not introduce another producer/use/state graph.

ProgramGraph schema 19 is selected by the new connection capability. The v18 field set excludes all three new tables, the older v1–v18 field/tag paths remain separately selected, and a v19 envelope without a real capability is rejected. `Execution` codec/version was not changed.

The owned records/codec tests are `tests/unit/test_program_protocol_connection_records.py` (current SHA-256 `e93b28418c8e32dcc0601e5b0f8204839459c64103ae2d24751ca3736798593e`) and `tests/unit/test_program_protocol_connections_codec.py` (current SHA-256 `378c9c7b58388ac49c85ac3e0c7746e513f0f84cd67d980369598b18da48e3ec`). The earlier owned 18-case run is preserved at `artifacts/experiments/b1_call_operands/model_remaining_protocols/records-codec/focused/attempt008/`: **18 passed**, exit 0, source fingerprint `5731bed97e368464778bdad0dfc3acaf7865b10d0d96161e522b20e20f182360`. That attempt predates later source/test edits and is historical evidence only; the combined post-fix run below retests both files at its own snapshot.

## Connection review

### Possible-copy inventory is not a proof

`ProtocolFlow._fresh_copies` has distinct `must` and `may` modes, with separate cache keys. Must transfer is used by `forwards`, expected-source binding, current-state queries, and guard-specific checks. `may_forwards` uses the same original CFG transfer engine with a union at incoming joins and is called only while building the potential consumer inventory. A possible-but-not-must consumer is retained with `consumer_condition_correlation_unresolved`; it does not make an input match, establish caller identity, or authorize a transformation. This is source review of `scar/ir/program/protocol_flow.py` SHA-256 `adae20a363e4d7be1b5fa1e5611719e4577b6fad93d80cea40897dfda061bc32` and `scar/ir/program/protocol_connection_validation.py` SHA-256 `b4189e9b5020cff96d5bab3a2478ab0ef0737fc677972dcc2eea354f9ae14912`.

The nested-consumer regression exercises the essential boundary: `may_forwards` returns possible while the unguarded and individual guarded must checks are false; the consumer remains in the denominator with an unresolved correlation gap. Existing input-route tests also reject mixed receiver/argument sources, wrong caller routes, and wrong raw ordinals rather than joining equal values by ID or type.

### Cross-region unknown consumer inventory

An earlier source review found that unresolved cross-region consumer candidates could be omitted. The current `consumer_ledger` keeps `consumer_cross_region_inventory_unresolved` when the original route check is unknown across regions. This is a source-level closure at validation source SHA `b4189e9b5020cff96d5bab3a2478ab0ef0737fc677972dcc2eea354f9ae14912`. I did not run a dedicated cross-region mutation for this closure; do not count it as separately regression-tested.

### Input and result denominators

Call-input records attach to the exact `(scope, clause, operation, slot)` row. Guarded cases must name original incoming edges to one merge; the ledger derives incoming edges from original CFG rather than trusting the listed subset. It verifies merge formals through original copies and then joins receiver, ordered arguments, and trigger on common caller/CFG context. A missing input attachment remains MISSING; omitting one known incoming edge remains PARTIAL.

Result-consumer targets are inventoried by scanning original owned Uses and terminators before reading the supplied target tuple. A supplied list cannot shrink that denominator, a missing listed consumer remains in `missing`, and a known wrong target is an issue. Opaque effects and possible cross-region routes retain gaps rather than being treated as no consumer. Related tests include `test_missing_incoming_case_keeps_an_obligation_instead_of_accepting_the_good_subset`, `test_removing_attachments_does_not_remove_input_or_result_use_denominators`, wrong-source/caller checks, and the nested-merge consumer test. This inventory is still only complete for the supplied model: `source_inventory_complete` remains false and the report retains the global source-scope gap.

### Prepared index and closed aliases

`validate` runs common connection analysis only after canonical core/provider/native checks and only when the Program19 capability predicate says the graph needs it. It builds the private `ProgramIndex._from_validated_core` directly from already computed facts; that constructor calls `_prepare`, not `validate`, so connection validation does not recurse. Public indexed queries reuse the supplied index. `test_prepared_query_does_not_construct_a_second_program_index` verifies that query path.

The first source review also found that `__init__.py` imported `AssociationPort`, `ExactResultPort`, and `ExpectedSourcePort` before `model.py` rebound their module placeholders. A fresh-process regression was added and first failed at the stale package alias identity assertion (alias-export attempt001). The fix moves only those three package re-exports after the canonical model import/binder. A later test-only failure (alias-export attempt002) showed that Python flattens nested `typing.Union` members; the test was corrected to compare flattened members. The post-fix independent-process test verifies package/module alias identity, no `Any` member, and canonical `BlockArgument`, `OperationResult`, and `InvokeLiteralResult` members. This is verified by attempt003 below; current `__init__.py` SHA-256 is `86272c82b8503840723bb54537956e1d327447010d607f8d412a4d6e191afbe0`.

## Independent v18 wire oracle and cleanup evidence

The immutable source revision was `add4ba84c9529e1f864e4029bd7c145cfacdfafc`. A source archive was made from only `scar` and `tests/fixtures`; the first archive command additionally named absent `tests/__init__.py` and failed with exit 128. The successful archive command omitted that absent path. Its retained tar is `artifacts/experiments/b1_call_operands/model_remaining_protocols/records-codec/oracle-v18/source/oracle-source-good.tar`, 5,918,720 bytes, SHA-256 `6e136bc23f73796b051d429489a0a707276e10913462c7d3cbc25abfcac13bc4`.

The old encoder was run from that extracted archive, not from the current encoder. It used the immutable ProgramGraph v18 codec SHA-256 `355d5863e59a0714c14ad3e4bffb1e6423a6900b924cb94df8e7654310bc7a94` and fixture builder SHA-256 `41aba0cbde2c4d761b18b991cbccecc1f292836a88a1d79792c0896899b60dc5`; the script SHA-256 is `c95eb65d4e264e84194784e1d4c9ccf90cf6e7143e7d2ef5b6f3ec3bbc59921e`. Attempt002 records Python 3.14.7, exit 0, matching before/after hashes, exact schema 18, and a single-completion INVOKE. It produced the existing `tests/fixtures/program_graph_v18_frozen.json` (13,215 bytes, SHA-256 `a1300ed97379e76455cd09e996ff2e5ca158bdca8f5e97149135a1a987c266d2`) and its proof (`7f5ef765ebbbb34ac538e465ff787c64e21ff1054713f80ebd8f58ace20c44d1`). The fixture has no connection tables and current codec roundtrip preserves its bytes exactly.

The successful extracted source and tar are retained under the ignored oracle evidence tree for reproduction. A final read-only `/tmp` search found no `scar-protocol-v18*` scratch directories; the artifact does not claim that the retained archive tree was deleted. The failed archive attempt and its error are preserved separately.

## Focused verification and attempt history

All attempts used Python 3.14.7 via `source /home/zyf/miniconda3/etc/profile.d/conda.sh; conda activate lewm`, with `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.`. The initial affected selection needed a small custom runner because the shared `run_focus.py` selector guard excludes `test_lifecycle_composition_codec.py`; that runner and exact command are preserved with each attempt.

| Evidence | Result | Source stability / explanation |
|---|---|---|
| `shared/schema19/attempt001/` | 376 passed | global version updates before alias fix; SHA `b462e9254d11398ec65d17a69f84816bed61433619362b4d54af38f3e51af6db` before/after |
| `shared/alias-export/attempt001/` | 1 failed, expected red | fresh child process showed package alias still held placeholder; SHA `56cc2b4677e2fdccf20c51b3cd22f18fc785c730b7d89cb5cb930afb664099d9` unchanged |
| `shared/schema19/attempt002/` | 376 passed, 1 failed | source fix was present; test incorrectly expected nested rather than flattened Union args; SHA `643e9f3df2bf4c43eeb680d2143243d0aaef0e4f68b78d43e5e2d216d78cabf2` unchanged |
| `shared/schema19/attempt003/` | **377 passed** | corrected union-members assertion; SHA `e5bea705a138ca9b15e6d5111fd31a7d866a730b9904069820af7187305b6f57` before/after |

The post-fix focused selection covers the ten migrated codec files, the owned record and codec files, and the new fresh-process alias regression. It is not a component or full-suite result. No execution-codec file, frozen fixture, product codec, or unrelated test was changed in the version assertion migration. This review does not claim the complete P4 family denominator, source/runtime applicability, or native Python behavior.

## Current reviewed source hashes

| File | SHA-256 |
|---|---|
| `docs/M1_PROTOCOL_CONNECTION_CONTRACT.md` | `f8ec4ed141c5e9d8d25a201b9f978ea1b93d81d72a0dab9466d3fef33fa17eb8` |
| `scar/ir/program/protocol_connections.py` | `86ea3d6d5822d14a72680c569baa90c4a91569007c280a33ce25f45975e6fde9` |
| `scar/ir/program/protocol_flow.py` | `adae20a363e4d7be1b5fa1e5611719e4577b6fad93d80cea40897dfda061bc32` |
| `scar/ir/program/protocol_connection_flow.py` | `0248f271ae9f92fccc5329a33bbc1fbb28f72b77e7df9001cb674c3e95fa0b12` |
| `scar/ir/program/protocol_connection_validation.py` | `b4189e9b5020cff96d5bab3a2478ab0ef0737fc677972dcc2eea354f9ae14912` |
| `scar/ir/program/protocol_query.py` | `ee615684aee662d0f80e7448edfcd654c250bef036f21e9800cb13867c43a963` |
| `scar/ir/program/protocol_rules.py` | `557096cb3b90536f482b5fe0ca7cbe0f2940f82c0ba0fdac2a864fa0b3d000e8` |
| `scar/ir/program/validation.py` | `db8bddfca7b84cc9d9a76e93b7d2859ff13990b574ed81e663458ccecf88a394` |
| `scar/ir/program/queries.py` | `37c84efe0a23d6213b4daf2219a304becfe95f41519b6a2066ca3001703d9fcb` |
| `scar/ir/program/codec.py` | `125d0d3e56a6f07abf00633e3c178dcc1ba3ef497a68025b950341ba59bc41fe` |
| `scar/ir/program/model.py` | `ce0b05e3d26ead9c9f623e86606c23c76a65d794244e4da0920bbe880e280dc9` |
| `scar/ir/program/__init__.py` | `86272c82b8503840723bb54537956e1d327447010d607f8d412a4d6e191afbe0` |
| `tests/unit/test_program_connection_flow.py` | `e8b470d7974144fcef7d0faa533bd6d35d17f51c3e6d012503c8fb02fee4c9b2` |
| `tests/unit/test_program_protocol_connections.py` | `49f8e0fa235dbb734428c8744fb174e6f7f776f1c328eed61bb564dccddb3389` |
| `tests/unit/test_program_protocol_connection_records.py` | `e93b28418c8e32dcc0601e5b0f8204839459c64103ae2d24751ca3736798593e` |
| `tests/unit/test_program_protocol_connections_codec.py` | `378c9c7b58388ac49c85ac3e0c7746e513f0f84cd67d980369598b18da48e3ec` |
| `tests/unit/test_program_protocol_path_safety.py` | `3d728045ce36e5459e03507d7d4adc284647bcb6eee5ccb0a1fee2f1efa087f7` |
