# Final main Lambda consumer

The single ordinary `SourceProgram.read_structure` call returned normally using the unchanged successful SP5 and its archived source text. The wrapper then failed its own `len(graph.operations)==170` assertion; original exit1, 33.759860s, receipt and script remain unchanged. No reader rerun or extra graph/context decode was performed.

The artifact is exactly the successful resume01 program, also matching BODY_QUERY and delta1: physical SHA `53e9e49864a80dcd230e83ce21c58587fc68475eafa00c988f70e90ac8b20c8a`, decoded SHA `5be82f2418cd5c580ecd1b704806c92cfb0c65d15c7ae90ee739c9bbb8344d66`. Actual graph size is 187 operations (170 outer + 17 Lambda child), two Regions, one Lambda body. The 187 unique original operation-source records and prior exact-artifact query establish these counts; the first wrapper did not log each count before asserting. The main reader verified canonical document equality and normal STRUCTURE/source correspondence before returning.

The original producer's `operations_emitted=170` omitted the child's shared-buffer operations because `_ExpressionBody.emit` incremented its copied integer counter. Root's separate one-line owner-budget correction is outside the source bytes consumed here. The old artifact/count and original producer receipt are preserved.

STRUCTURE readback consumed 3,754,035 stored / 31,853,405 decoded SP5 bytes once, plus normal archived text/manifest handling. It grants no new independent CodeWitness or runtime evidence. All source SHA before/after matched; exact feature-source SHA and source count are in EXPLANATION.json, full pins in receipt.json. No lower, compile, target, publication or currentRun binding ran. The full first-stage model remains OPEN.
