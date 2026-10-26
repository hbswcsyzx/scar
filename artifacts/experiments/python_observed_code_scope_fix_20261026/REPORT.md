# External observed-code frame scope fix

The v2 selector installed a CodeType-local instruction mask for an observed external function. In call-window mode the mask remains installed after that invocation. A later entry through an unobserved external wrapper failed `_observe_entry`, so the frame recorder supplied no base state. An active instruction callback then emitted `INSTRUCTION_FRAME_UNAVAILABLE` and stopped the operand observer globally.

The single predicate now retains real entries for explicitly v2-observed CodeTypes as well as pending exact targets. The existing operand profile can then use their real base state. Exact target/entry proof still requires its separate pending-call rule; this change does not manufacture a direct-call handshake. It does not return monitoring DISABLE, change the old default scope, or alter buffers/close/fork behavior.

The one generic CPU example directly calls external `selected`, then a `functools.partial` wrapper calls the same code indirectly, then a project sentinel runs. `selected` itself has a CALL window. All three executions returned the same token. Normal `read_call_operands` and the v2 normal target reader passed (`check.py`, actual exit 0).

| Actual execution | selected entries | attempts | sentinel attempts | GAP |
|---|---:|---:|---:|---|
| Exact main preimage, v2 enabled | 1 | 3 | 0 | event 15, INSTRUCTION_FRAME_UNAVAILABLE |
| Predicate fixed, v2 enabled | 2 | 5 | 1 | none |
| Predicate fixed, v2 off (default) | 1 | 3 | 1 | none |

Only the first selected entry has an exact target/entry relation. The indirect second entry has a retained frame and no fabricated handshake. See `RESULT.json` for the normal reader observations and all three tested source hashes.

The original LeWM operand event104 has null invocation and no CodeID/offset. Its frame watermark22 follows previously observed external code and the root `Path(...).resolve().parent` sequence. This supports the same failure mechanism but does not uniquely identify the failed callee. `LEWM_PREFIX.json` preserves the bounded first24 frame observations (24,104 decoded bytes); the small code stream was independently read to EOF/SHA. No LeWM retry or large frame scan was performed for this diagnosis.

The CPU runs used exact current-main buffered trace sources. The commit stages only the `_observe_entry` predicate against this branch; the other two trace sources remain exact synchronized test dependencies, not new production changes. Apply `MAIN_SCOPE_FIX.diff` to the recorded main preimage, or cherry-pick the predicate commit. `PATCH_RECEIPT.json` distinguishes branch bytes from expected main bytes. Contents/state/ready and unknown external closure/call relations remain unproved.
