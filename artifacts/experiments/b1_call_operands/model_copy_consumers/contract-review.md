# D6 model-first design and read-only review

Base:5c8b60a0f81739445fa240224b101197cb93db5d; previous checkpoint is verified
progress, not a waiting or blocked state. At this continuation's first read,
only the D6 contract and five new authored test/fixture files were untracked;
there were no edits to tracked product/tests or unrelated files.
Frozen contract SHA92f09c156a9949a75f4308e44ce0c82c2a58361f916ff223ae754cb47261bf0f.
The complete original A–H/16/P5/M2 scope is retained, not replaced by this view.

A/B/C read the existing CallReturns, ProtocolFlow, original Use indexes and
call_composition/input-origin routes. Return-copy summaries exist; internal
callee consumer inventory is explicitly pending. Query-local call frames
must retain complete actual/formal ordinal tuples, exact terminal Uses and
original N/R slots. Shared callee code does not imply the same input or value.

B identified two necessary contract refinements before freezing: root source
inside a called region has unresolved original outer callers; may-only legal
consumption is conditional, not a contradiction. A/B/C agreed to preserve those
boundaries rather than claiming complete dependencies. Return(x,y) and
Return(x,x) retain independent original Uses, not a collapsed HostTerminal.

A source-read finding while constructing the independent stronger fixture:
the canonical control validator requires every exception-packet OperationResult
to have a local PacketDefinition, while that definition forbids callee calls.
Thus an ordinary typed CALL returning a callee's packet cannot currently be
represented. A retains the genuine CALL/own result and full adapter chain;
neither a NORMAL-only INVOKE nor bypassing the helper's result substitutes for
this requirement. This finding is source-reviewed, pending root's actual red.

If reproduced, root will distinguish a typed call output carrier from a local
packet constructor, retaining strict constructor checks and other protocol
categories. Protocol copy checks must also use return-aware original ports;
False must not simply be weakened to None or skipped for calls. No new schema,
producer, backend or workload-specific logic is planned.

Root owns product code and all Python/test/probe/compile execution. A/C own only
their new fixture/test pairs; B owns only the new boundary file. Existing tests
and fixtures remain byte-identical. All authors freeze before each serial
attempt. Command/log/JUnit/source registries preserve actual failures.
