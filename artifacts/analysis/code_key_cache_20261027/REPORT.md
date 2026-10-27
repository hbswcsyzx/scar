# Weak-identity code-key cache

Implemented on source snapshot `4f23a6d687919853d8c91f405859f473e6e0e6b9` in an isolated worktree.

`code_key()` now uses a bounded 2,048-entry cache whose values contain only a weak reference, the immutable `pycode-v2` key string, and encoder limits. Cache lookup checks `reference() is code`, so a reused address cannot inherit a key. Entries are added only after the complete code tree encodes successfully and the parameter layout passes validation. Unsupported constants do not enter the cache. `describe_code()` keeps its existing fresh mutable return containers and key recipe. `CallEdgeRecorder._code()` gets keys without allocating those containers for already-written code; it describes and writes a code only on first emission.

`site()` now gets its key from the key-only record and keeps the existing 128-offset LRU there. It does not call `dis.get_instructions`: the opcode comes from `co_code`, and an uncached offset obtains its position from `co_positions()`. No full instruction index was added.

The single archived `CodeType` check matched its manifest key, repeated lookup on the same object kept that key, a `co_filename` replacement received its own different key, and a code object with an unsupported constant was rejected without being cached. Repeated `site()` output matched. The validation and raw archive receipt are in [RESULT.json](RESULT.json); the runner is [run_validation.py](run_validation.py).

In this one warm local timing, 10,000 `code_key()` calls took 0.00785 s and 10,000 `describe_code()` calls took 0.01271 s. This only measures the key-only API against descriptor allocation for one code object. It does not measure capture throughput or explain the long offline reader run.
