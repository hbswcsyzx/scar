# Retained source call bridge

Base: `d2811f8ea9d994c718339a60f6b008ef2f865971` in the isolated `retained-call-ports` worktree.

The producer reuses the v4 retained source/body rows, existing `PythonSourcePortModel`, original CALL `Operation`/ordered Uses, original callee formal values, and the current same-capture attempt/entry pair. It does not rebuild the old proof owner or create operations. Receiver records are reference projections. The model does not establish runtime callable identity, selected normal return, object identity, content equivalence, effects, or world-state equivalence.

## Actual production result

`attempt03/terminal.json` records a normal PASS. It read the original PID 272038 capture once: 100,438 frame entries, 100,438 exits, 100,550 attempts, and 4,069 entry handshakes. The raw operand reader took 123.138 seconds; total builder time was 125.580 seconds. The exact source report SHA256 is `88e0ad71244ba59a455eb8bcd3a369fbe579e7c2e95bb3498d123bd4a965aa6f`, and `bindings.json` SHA256 is `096c5a53213bae9f480ba813c240a277220ce6ac636390c0edff3bde9a91f449`.

The bounded result has two calls and three body nodes:

- raw attempt 59197: `HDF5Dataset.get_col_data` → `HDF5Dataset._get_col` (one explicit argument, one receiver port)
- raw attempt 59200: `HDF5Dataset._get_col` → `HDF5Dataset._open` (one receiver port)

The generated typed model is `attempt03/source_ports.json`, SHA256 `4a78314ff0c840f37a694150d44fc4f7adfd798d19d3206c5a09f2fc792afde0`, 33,428 bytes. It selects 2 of 100,550 attempts; the other 100,548 remain unmaterialized. This is a real three-body chain, not full-attempt coverage.

The normal `SourceReturnSession` query ran for both binding ordinals in one session, with `include_state=True`, in 0.640 seconds. It decoded 20,631,693 bytes from 9,647,490 stored bytes across three body artifacts. Query receipt: `attempt03/return_query_check.json`. Returned normal and world-state views remain conditional; no runtime return or world equivalence was asserted.

## Compatibility and development records

The retained body locators include both SourceProgram/5 and body-construction-checkpoint/1 receipts. `attempt02/local_pair_check.json` records a no-raw-scan load of the actual `get_col_data` → `_get_col` pair, including its exact source AST call at line 141, columns 15–33, plus the v4 declaration check through the updated return reader.

Two earlier actual outcomes are preserved. `attempt01/terminal.json` is the 125.693-second reader failure from use of a nonexistent `OperandCollectionMetadata.dropped_codes` field; the field is `dropped_events`. `attempt02/terminal.json` records a 262.558-second zero-link transport result caused by the producer not yet accepting the retained legacy locator shape. It was an implementation incompatibility, not source-proof rejection. The successful attempt03 uses one-pass cached gap/issue indexes so candidate evaluation does not rescan the 312,812 operand events for every pair.
