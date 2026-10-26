# Source publication reader: necessary fixes

Implemented: factor per-entry CAS expectations out of the global parent planner. The compact reader authenticates the saved complete plan and global parent once, validates each file group immediately before ordinary body/source/compiler/checkpoint reads, then rechecks the global parent at the end. The existing private-session input guards remain. Global parent verification therefore occurs twice per batch rather than once per file group; the real 196-body manifest has 94 file groups. No target-program speedup is claimed.

Implemented: check the existence, canonical path and declared size of every original SP5/CP2 before expensive catalog/body decoding. These stats grant no graph/source/runtime qualification. Normal checksums and semantic validation remain required.

Verified: after byte-exact Git recovery, all 392 original artifact references in the 196-body publication passed the availability check in 0.043344s. This is a metadata check, not normal whole-publication readback or call binding. The two-source patch also received independent code review; no test matrix or target execution was run.

Previous attempts remain failed: the first shared-reader wall guard expired; the next attempt failed when an original CP2 file was missing. Its 161 checkpoint files and parent manifest have now been recovered from original Git blobs with all original stored/decoded SHA and byte receipts unchanged. Required paths were added to this development worktree's sparse retention patterns. See the restoration receipt and original failed-attempt records.

Next: consume the current publication once through the ordinary reader and bind the original PID272038 capture. Do not treat restored bytes, metadata checks or source body counts as dynamic binding evidence.
