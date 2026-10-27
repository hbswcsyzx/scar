# Retention and qualification

The original single gate exited 1 after all three public body readers passed.
Its runtime participant audit lacked `_compat_pickle.py` in the pre-run freeze.
The original failure, freeze, inputs, journal and entry points remain unchanged.
The metadata-only postflight exited 0; it does not qualify the original gate.

Git retains the scripts, receipts, metadata, published inventory shards and
checkpoints. The 17,063,742-byte composition index and 354 source-snapshot files
remain local and are not duplicated in Git. Exact composition size/SHA and
original qualified URI are recorded in postflight01/receipt.json; the source
freeze records the source bytes, and the local source-snapshot directory keeps
the corresponding copies. No files were deleted during this delivery.

The published inventory still references original source programs, unchanged
parent composition and code-witness archives. This is not a self-contained
cloneable capture or an implicit relocation format. Stored roots, declared
identity and model qualification remain distinct.
