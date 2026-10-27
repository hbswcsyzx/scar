# Generator profile intervals are not function activations

Read-only main source reviewed: call_edges SHA48360a3a65fcdae08444fc2522d83c7410cc7245d9fbed2ddfd93a684340c046. One CPython3.14.7 same-process case ran **0.020991s**, using one generator that yields3 times, its original profile callback and the ordinary collector followed by strict `scan_call_trace`. No production source or LeWM was modified.

Creation produced0 generator frame events. All8 raw call/return observations had the **same frame, code and original `f_generator` object**. The normal collector/reader produced:

| Interval InvocationID | Original call site | Original return site | Collector completion |
|---|---|---|---|
|1|RESUME0 @4|YIELD_VALUE @8|SUSPENDED|
|2|RESUME5 @10|YIELD_VALUE @16|SUSPENDED|
|3|RESUME5 @18|YIELD_VALUE @24|SUSPENDED|
|4|RESUME5 @26|RETURN_VALUE @32|SUSPENDED|

Every entry has suspended=True. The strict reader accepted the wire with0 issues. Raw identities/offsets and exact collector rows are in RESULT.json; the fixture's ephemeral IDs are not proposed production identities.

**Current meaning/boundary:** call_edges.py:417–419 increments InvocationID on each observed profile call and453 uses code flags for suspended. Return488 uses that same flag before checking the actual opcode, so it also labels final return SUSPENDED. These IDs are frame-execution intervals, not persistent generator activations. SOURCE_INVOCATIONS.md:134–135 already states this boundary; however the collector's metadata counters do not explicitly call them segments, and the final-completion classification is too coarse. M1_RESUMPTION_INTERFACES.md:19–34 requires separate object, continuing activation, drive request, actual resume and suspension generation.

There is **no observed false promotion to4 canonical ordinary calls**: analysis/call_edges.py:1046–1048 reports SUSPENDED_FRAME; source_invocations.py:946–956 reports FRAME_RESUMPTION_CONTINUITY_UNRECOVERED and withholds RegionActivation. Thus the existing conservative boundary is deliberate; sustained activation/segment reconstruction is missing. Old raw entry/call counts, especially generators such as tokenize, cannot be advertised as counts of distinct generator creations.

Minimum reuse proposal, not implemented:

- Keep each original InvocationKey as an ordered interval anchor. In an explicit versioned profile, observe the original frame.f_generator through the existing bounded weak-reference epoch mechanism; verify the exact generator/code association each time. Never persist only id(frame), retain a frame/generator strongly, or merge by equal CodeID.
- Record initial/resumed entry site and each real yield/terminal site, linked to the same observed weak owner and per-owner ordinal. Distinguish actual YIELD_VALUE from final RETURN_VALUE; a return caused by exception remains unknown absent appropriate original exception evidence. Keep all observed segments and payload references.
- Reuse existing `RegionActivation` and `ExecutionSegment` (execution/coordinates.py:114,172): one sustained body activation with multiple segments. Use `InitialEntry` only for actual initial entry. `ResumeIngress` needs the exact prior Suspend occurrence/successor; missing driver/selector/state uses existing `CaptureIngress` rather than guessing send/throw/close, parameter rebinding, exception packet or ready.

The new plain facts would need a versioned normal reader/adapter; old V1 wire and its conservative guards remain intact. This is not permission to remove generator events, a new runtime collector, or a LeWM performance measurement.
