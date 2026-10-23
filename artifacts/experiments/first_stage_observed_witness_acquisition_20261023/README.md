# ONE observed compiler-witness acquisition

2026-10-23. **Observed / Verified, actual exit0, status COMPLETE.** This gate
acquires compiler evidence; it does not execute target code, lower a body or
increase current-Run coverage. The all-program modeling stage remains OPEN.

The approved public producer is `scar/analysis/compiler_witness_archives.py`,
SHA `8b7f9b3875098bd545775f9937d9a89c07ff4136fcdcbf6869fc228583f2c0a0`.
`preflight.py` checks imports/API signatures and the complete original worklist
without source graph reads or compilation. Its compressed and decoded table
receipts and full plan digest match. An initial preflight-only summary used a
wrong group field (`invocations`); the actual table uses `current_calls`.
`preflight-initial-failure.json` preserves that failure. No acquisition started
until the corrected standalone preflight succeeded; production code was unchanged.

The full saved plan contains2217 body records and817 groups/100438 calls. The
selection is exactly `metadata_status == CODE_WITNESS_MODULE_VARIANT_MISSING`,
mechanically yielding10 original definitions/8 files/53 current calls. Names,
reason strings and manually chosen indices do not select requests. Compressed
and decoded SHA/size are checked for all three plan tables, followed by its full
canonical digest. Original qualified references are obtained using regular
`CompositionIndex.prefetch_definition_references`, `definition_reference` and
`resolve_definition`, with exact snapshot/context/DefinitionID/source equality.
These are static source references, not new invocation/body activations.

| Actual acquisition | Result |
| --- | ---: |
| Requests / attempts | 10 /10 |
| ACQUIRED_VERIFIED | 10 |
| Distinct preferred module compile keys | 8 |
| Actual compile attempts | 8 |
| Source files / UTF8 source bytes | 8 /107344 |
| Published marshal bytes | 142822 |
| Internal read-only module loads / descriptor matches / compiles | 8 /10 /0 |
| Independent read-only module loads / descriptor matches / compiles | 8 /10 /0 |
| Historical archive module loads / compiles | 0 /0 |

The public API rederives requests from original observed CodeCapture and
CodeSourceLink records, then uses each link's lowest recorded matching optimize
level. Shared module keys compile only once. Compilation creates CodeTypes with
the original lexical compile filename and full compiler context; it does not
`exec` or import those target modules. Every saved nested descriptor equals the
complete original CapturedCode. The native archive is reopened read-only inside
the API and independently once more by this gate. The latter compares complete
descriptors, original constant paths and exact witness records for all10 requests.
Runtime code-object identity or a newly observed event is not asserted.

The new independent archive is `result/archive/manifest.json`, SHA
`2da1103c7e8fe0e941a13948391a6080e3de141c0f35733e24be7c7b6e305c72`.
It has8 source and8 module payloads. The historical20-key archive was admitted
read-only with a20-key reader ceiling, while the new writer had an8-key ceiling;
these budgets are separate. The historical manifest and all40 payload files
(41 files/676743 stored bytes) have identical before/after hashes. Neither its
manifest nor any payload was appended, rewritten or merged into the new store.

Limits were10 definitions/requests/attempts,8 compile keys/source files, source
and module ceilings2MB each, archive32MB and180s wall time. The runner also set
an independent180s wall alarm and forbade execution of code from selected target
files. No such execution was attempted. Original failures/BUILDING checkpoints
would have been retained; there was no actual acquisition failure or retry.

Actual session97388, Python PID670902, confirmed exit0. `/usr/bin/time -v`
reports wall40.86s, user38.89s, system1.89s and peakRSS717372KiB. Public acquisition
itself took4.02s; total runner elapsed39.39s includes full plan/source-reference
admission and independent replay. These are offline compiler/modeling costs,
not a target benchmark or LeWM acceleration measurement. Actual98 imported
SCAR source files were archived and checked unchanged from start to finish.

`producer.json`, `inputs.json`, `selected-qualified-definitions.json`, budgets,
progress/time/stdout, public report/checkpoint/plan, independent replay and old
archive snapshots preserve the evidence. This gate produced0 new body graphs,
0 target invocations, no source prepare, no new publication and no Run connection.
The next frontend can use an explicitly admitted new archive through the
archive-basis API; this gate does not silently change any saved body's old basis.
