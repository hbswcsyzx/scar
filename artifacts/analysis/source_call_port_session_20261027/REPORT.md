# Retained source-call port session

One normal reader session consumed the retained raw call trace for PID 272038 and emitted receipt-bound shards using the existing `PythonSourcePortModel`. The run completed with exit code 0 in 137.003 s; the raw reader took 126.511 s. A normal typed readback verified all 15 shards and all 449 selected attempt IDs in about 4.1 s.

The source report and adjacent bindings are the original v4 same-capture artifacts (SHA256 `88e0ad71244ba59a455eb8bcd3a369fbe579e7c2e95bb3498d123bd4a965aa6f` and `096c5a53213bae9f480ba813c240a277220ce6ac636390c0edff3bde9a91f449`). The raw trace root is the report-qualified `first_stage_lewm_dispatch_20261023/trace`. The reader revalidated exact raw file receipts against the report.

## Scope and result


- Raw denominators: 100,438 frame entries, 100,438 exits, 100,550 call attempts, 4,069 entry handshakes, 207,248 operand instructions, 312,812 operand events, 945 gaps, and 855 code captures.
- Candidate funnel: 100,550 attempts in the captured process; 96,481 lacked a unique entry handshake, 1,386 had a source body not linked in the retained catalog, and 2,683 were direct body-linked candidates.
- This run examined the first 512 of 2,683 direct candidates and built 449 bindings across 15 shards. The other 63 examined candidates remain unconnected: 52 source inventory references did not resolve to the required partitioned-file record shape, one captured CALL lacked a source position, and 10 were outside the fixed positional source ABI supported here.
- 2,171 candidates remain outside this bounded session. Full candidate and full attempt coverage are false.
- Shards total 416,923 stored bytes and 10,519,249 decoded bytes; the manifest is 160,512 bytes. It references source/body namespaces and existing IDs instead of embedding complete bodies.

The runner and production sources are receipt-listed in `actual_result.json`; the runner can be called again with the listed report/bindings receipts and explicit capture path/PID. The final manifest is `publication/manifest.json` (SHA256 `118a189761ddefe33d03b548e5ba8c699a1c3fe35baa34f82832ff6519b50c36`). It is closed for the declared 512-candidate scope, while explicitly incomplete for the full 2,683-candidate and 100,550-attempt denominators. Candidate ordinal is navigation order only; it does not prove happens-before, runtime identity, selected return, effects, or content equality.

The session kept at most eight decoded body graphs / 64 MB, 32 body views, 16 inventory partitions, 32 call partitions, eight syntax trees, and 512 static call templates. The actual run loaded 17 body artifacts (48,197,045 decoded bytes), used 14 static templates, and ended with eight cached body graphs occupying 31,699,689 bytes.

A first runner invocation failed before import because the artifact script lacked the repository root on `sys.path`; it did not invoke the raw reader. The runner was corrected, and the successful scan above was the only raw-reader run.

## Receiver classification audit (read-only)

The source-port builder's `_selected_binding` and `_reuse_binding_template` classify a normalized receiver from an AST attribute call, `callee argcount == explicit positional argument count + 1`, a synchronous fixed positional shape, and the captured `arg0` token matching the first retained frame formal. `_checked_formal_ports` checks that source formals match their canonical graph entry ports, but it does not rule out `FormalParameter.default_source`. A plain attribute-held function such as `f(x, y=default)` called with one explicit argument can satisfy those checks: the `arg0` token can denote explicit `x`, while this builder labels it the implicit receiver and shifts the source actual to the next formal.

For the 449 selected bindings in this bounded output, 106 have `NORMALIZED_RECEIVER_FUNCTION`; all 106 selected callee source signatures have no declared defaults. That excludes the example's source-declared-default shape within this selected scope only. It does not establish the runtime function object's `__defaults__ is None`, since the older call record has no defaults snapshot and runtime defaults can be changed.

The retained `OperandCallAttempt` records `CallableShape` (callable reference, code, and layout) plus `arg0`; `LoadObservation` records the loaded slot/reference and callable shape. Neither carries `__defaults__`. The exact PID 272038 trace directory has no `python-call-targets.272038.jsonl` or `python-call-target-meta.272038.json`. The newer `PythonTargetObserver.on_call` explicitly requires `func.__defaults__ is None` before emitting its normalized-function receiver kind, and rechecks this at frame entry; that evidence is absent here.

Therefore, interpret the old `NORMALIZED_RECEIVER_FUNCTION` / `SourceReceiverPort` data as a conditional receiver candidate and a raw `arg0` endpoint reference. It does not prove bound-callable identity, implicit receiver role, or actual formal routing. Any later consumer that needs those claims must require the matching current target/entry evidence (including the defaults guard), or keep the route conditional. No source/model bytes or publication manifest were changed for this audit.
