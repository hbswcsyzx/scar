# Live source-entry plan selector adapter

`derive02.py` actually exited0 in0.200328451s. One existing retained generic program was reused; no capture, source prepare/lower, target execution or compiler invocation occurred. A normal live `SourceEntryFrontendPlan` selected two dependency admission entries. The adapter resolved the original typed references and readonly code witnesses:1 module load,2 complete descriptor matches,0 compile attempts,0 archived source bytes read by CodeWitness. Catalog prepare/AST/symtable counts were all0.

Both selectors preserve the original `SourceSnapshot` and `CapturedCode`; CALL offsets come from those exact archived code objects. The1566B selector was published and normally read with its exact SHA; wrong SHA was rejected. Current filesystem source checks are version guards, not a way to infer archived code identity. The plan does not prove source-body expansion, runtime membership, contents, state, or readiness, and deserialization never restores a catalog owner.

The first `derive.py` completed derivation/publish/normal read/SHA rejection, then failed while formatting its report because it called nonexistent `archives.metadata()`. Its script, failure and artifact remain unchanged. `derive02.py` uses the actual `receipts()` API and records fresh counters; the old failure is not rewritten as PASS. There was no new target capture or broader matrix.

API is in `scar.trace.lean_capture`: `LeanCapturePlan.from_source_entry_plan(live_plan, *, namespace_root, max_codes=4096)` and `read_plan(path, *, expected_sha256, max_bytes=16_000_000, max_codes=4096)`. Parent integration owns CLI/site/source-entry publication. The seven-source lean capture behavior and old default profiles are unchanged by this commit.
