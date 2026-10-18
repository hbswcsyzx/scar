# P4-1 await and coroutine connection review

**Status:** Proposed design review; no product changes or tests.  
**Read baseline:** `/tmp/scar-structured-model-280qf4mi`, clean HEAD `d507a1695a26e1d77c4f5145a29be64448ae7cf4`.  
**Scope:** F12–F15 await/coroutine/generator-coroutine interfaces, their original program ports, and P2/P3 dynamic links. This does not close P4 or claim source/runtime applicability.

## Observed: available records and routes

- The protocol contract already fixes the relevant profiles and clause denominators. `AWAIT_SITE_V1` requires `AWAIT_LOOKUP`, `AWAIT_CALL`, and `AWAIT_RESULT_ADAPTER`; `COROUTINE_AWAIT_WRAPPER_V1` requires the parallel wrapper clauses. `COROUTINE_BODY_V1` and `GENERATOR_COROUTINE_BODY_V1` require the body ingress, suspension, terminal, and adapter clauses. See `docs/M1_PROTOCOL_CONTRACT.md` §6.2 and `scar/ir/program/protocol_rules.py`.
- `ProtocolCall` records the actual receiver Use, ordered argument Uses, its own CALL/INVOKE result port, state sites, and a closed rule. It has no field naming the expected producer for its receiver or arguments. `OutcomeAdapter` names an exact input port and input Use, plus its own result, host terminal, or native exit. It does not generally name an expression-result consumer outside that operation. (`scar/ir/program/protocols.py`.)
- `ProtocolFlow.forwards(source, target)` follows original definitions, Use ownership, CFG edges, and CALL/INVOKE ports. It can check a declared source against a consumer; it cannot select which same-typed producer the source-language site was meant to consume. (`scar/ir/program/protocol_flow.py`.)
- P2 `CallActivation` connects a caller occurrence to one dynamic activation and original entry/completion. P3 `BodyDriveExecution` connects a BodyDrive occurrence to a persistent activation, exact entry visit, and outcome occurrence. These provide dynamic links without new actuals or a second CFG. They do not identify an await lookup/call's expected operand, nor the source of each BodyResume input. (`scar/ir/execution/calls.py`, `call_validation.py`, `resumables.py`, `resumable_flow.py`.)
- A body ingress is already concrete: `BodyResume` names the original Suspend and successor; `BodyResumeInput` names the original slot and Use. The validator checks that each supplied slot matches the original `ResumeSlot` type. `ResumeSlotKind` includes `SENT_VALUE`, `THROWN_PACKET`, `DELEGATE_VALUE`, and `DELEGATE_PACKET`. This proves port shape, not which prior operation produced the value. (`scar/ir/program/drivers.py`, `driver_validation.py`, `resumption.py`.)
- `protocol_obligations` derives BODY_INGRESS and body outcomes from existing drives. Its `source_inventory_complete` is always false, and it has no corresponding await-site/lookup inventory derivation. Thus row presence is not proof that all source await sites were declared. (`scar/ir/program/protocol_query.py`.)

## Inferred: concrete connection gaps

1. A lookup/call row can point at a valid receiver Use and a valid call result, yet there is no expected-source relation saying that this receiver must be the exact lookup result for this await site. Matching by type, region, name, or whichever producer reaches the Use would permit a same-typed wrong iterator/wrapper.
2. A coroutine body can have correct `BodyResumeInput` slots and a P3 execution row while the scheduler/result source is missing, stale, or from another call. Slot-type validation cannot distinguish those cases.
3. `AWAIT_STOPITER_TO_EXPRESSION` has a typed adapter rule, but a declared adapter alone does not close the await operation's full consumer route. Its exact helper/BodyDrive input and the source-language result consumer must remain connected through original ports; otherwise a correct-looking adapter row can be detached from the awaiting site.
4. Deleting all scope/rows cannot be treated as “no await work”: the query already preserves a global `SOURCE_SCOPE_INVENTORY_UNRESOLVED` gap. Keep that behavior. A supplied site scope is a declared analysis boundary, not proof that all sites in the program were found.
5. Do not equate `SuspensionFlavor.AWAIT` with one `ResumeSlotKind`. A coroutine's awaited iterator handoff and the scheduler's later resume of the coroutine are distinct layers. The actual BodyResume slot and its type come from core; the expected producer/meaning must be attached at the correct layer. The local control-protocol document says scheduler values/exceptions drive the await iterator and its `StopIteration.value` completes the await expression; it also permits zero suspensions. It does not license inferring a source port from enum names.

## Proposed minimal connection records

Keep the existing `ProtocolOperation` natural key `(scope, clause, operation, slot)` and current canonical producers/Uses/state. Do not create another operation/SSA/phase graph.

1. **`ProtocolOperationRef(scope, clause, operation, slot)`** is a strict reference to one existing protocol row. Use it anywhere an input/output relationship must name a protocol producer; a loose `(operation, value)` pair is insufficient where one operation has multiple clauses or result slots.
2. **`ProtocolCallInputs(site, receiver, arguments)`** is a narrow side record keyed by `ProtocolOperationRef`, not a second `ProtocolOperation`. `receiver` and each ordered argument source are `ProtocolSourcePort | StaticProtocolGap`; `arguments` preserve ordinal. The actual receiver/argument Uses remain solely `ProtocolCall.receiver_use` and `.argument_uses`. The validator matches each expected source to those exact owned Uses through `ProtocolFlow.forwards`.
   - For `AWAIT_LOOKUP` / `WRAPPER_LOOKUP`, bind the exact source-language awaitable/wrapper operand to the lookup receiver.
   - For `AWAIT_CALL` / `WRAPPER_CALL`, bind the expected receiver to the exact preceding lookup `ContractResult` (or an explicit gap). Do not discover the expected result by tracing the actual receiver backward.
   - Keep raw-only/external forms representable; do not require an invented local lookup or argument Use. Missing expected sources stay gaps. A wrong known source is an issue.
3. **`ResumeSourceBinding` as a `ProtocolOperation.contract` variant** is only for original BODY_INGRESS rows. Its row uses the original BodyDrive operation and the exact original resume slot as `slot`; it stores only `source: ProtocolSourcePort | StaticProtocolGap`. The actual consumer is derived from that drive's `BodyResumeInput` for that slot, and its target Suspend/successor from `BodyResume`. The existing derived ingress denominator remains authoritative: deleting the binding leaves a MISSING source obligation, not an absent ingress. Do not duplicate actual Uses, resume slots, state values, or edges.
4. For an await-result adapter whose output has no unambiguous original consumer anchored by its site, add one exact consumer reference (`OwnedUse`, `HostTerminal`, `NativeExit`, or explicit static gap) at the adapter/site boundary. Only add this if core lowering does not already make the result consumer uniquely derivable. Never select a consumer from arbitrary reachability or same type.
5. Use existing `ContractResult` and `ProtocolSourcePort` constraints to require a source result port to be produced by the referenced row's own original result. Use both `InvokeLiteralResult` edges/results for N and R; do not substitute a NORMAL-only port for an RAISE route. `StaticProtocolGap` represents unobserved source/ports, not a successful connection.

A profile/site inventory still needs an explicit completeness condition before a report can call every required await site covered. Preserve `SITE_INVENTORY_UNRESOLVED` (or the existing global source-inventory gap) when supplied scopes cannot be shown exhaustive. Fixed profile clauses supply the per-scope denominator; actual original call/branch/drive sites supply the sub-denominator. Missing rows remain MISSING, and truncation retains the pending scope/row cursor.

## Required route checks

- **Lookup → call:** fixed await/wrapper rule selects the expected lookup result; `ProtocolCallInputs` binds that `ContractResult` to the exact call receiver Use. Check normal and raise result edges independently. A type-compatible result from another lookup is rejected when its source is known; an unobserved path remains a gap.
- **Call/wrapper → body:** where the call creates or returns the body receiver, connect the original call completion to P2 `CallActivation`, then to P3 `BodyDriveExecution` and its exact body entry. Keep missing dynamic association as a gap. Do not join by code region, type, or name.
- **Scheduler handoff → resume:** for every observed BodyResume slot, match the explicit expected source to the exact original `BodyResumeInput` Use and exact predecessor/resume edge. `SENT_VALUE` and `THROWN_PACKET` are distinct; delegate slots are only used when the original operation is actually delegation. Slot type is a validation constraint, not the producer selector.
- **Final await result:** distinguish an intermediate yielded/scheduler handoff from the final body return/raise. A normal adapter consumes the exact body/contract completion that produced the await result; exception completion follows the exact RAISE edge/packet path. The adapter's output is linked to the actual await-expression consumer. Zero body suspensions are valid if the supplied CFG has a complete direct terminal route; absent body/terminal capture is still a gap, not a zero-suspension proof.
- **Generator-coroutine:** direct host completion and wrapper/await completion each point to the same exact P3 body occurrence where the supplied model claims they share a body. A normal generator with matching type or region is not sufficient. The current fixed profile already requires both DIRECT_HOST_ADAPTER and AWAIT_COMPLETION_ADAPTER; do not drop one because one path is absent from the supplied rows.

## Bounded acceptance matrix

| Area | Positive cases | Negative cases / required result |
|---|---|---|
| F12 await lookup/call | One await site with correct lookup result; a normal completion; a raising lookup/call; direct terminal with no suspension | Same-typed result from a different lookup; deleted lookup/call row; wrong N/R port; ordinary generator treated as awaitable. Known mismatch = issue; unobserved source = gap. |
| F13 handoff/resume | Multiple handoffs to one exact coroutine body; correct normal and raised delivery to exact resume slots; final StopIteration value reaches the await expression | Stale prior state, another child/call result, dropped exception, or an intermediate handoff treated as final result. |
| F14 phase/reentry | Exact state read, boolean producer, real branch, and current per-drive route; duplicate/reentry attempt stays within the same recorded body/session routes | Stale predicate across callback, wrong bool result/edge, or duplicate await represented as a fresh body. Missing phase-site inventory stays a gap. |
| F15 generator-coroutine | Direct drive and await-wrapper route each connect to the same body activation/drive result via original P2/P3 records | Ordinary generator mislabeled, wrapper/body joined only by type/region, adapter fed another Drive's result. |
| Budget / deletion | Full fixed clause and supplied-site denominator returned; budget truncation retains cursor | Removing all scope/rows must not report success or erase the global incomplete-source gap. |

These are design acceptance cases, not executed tests. Source/runtime applicability and transformation authority remain false until separately established.

## Read set and hashes

- `docs/M1_REMAINING_PROTOCOL_PLAN.md` `87a5c029e4a1666b4f8fc73bf7d3886329c64ce8e8f707f76314f35f16676317`
- `docs/M1_PROTOCOL_CONTRACT.md` `2a5d982907ed8d9d9e93586f8cf9979002cbac6e27c73de8aac8ce4d0c45c4ac`
- `docs/model/PYTHON_CONTROL_PROTOCOLS.md` `28d2ac164049598921f7f01c24d6638afdb17161f9a637b555e6192a8c31d02f`
- `scar/ir/program/protocols.py` `a51bd800af0b767e8477b95a07aa77ff0a47a0de3222c2804818c295b215fc03`
- `scar/ir/program/protocol_rules.py` `be4b601e16401f677b4cbf4e7ba4d2b2d895f4364ce4d1f90d68ed778f92dbe1`
- `scar/ir/program/protocol_validation.py` `963e352d3b88ff6d4dcdd220542130fe873859d3f0610af8ab7c44e07a45b049`
- `scar/ir/program/protocol_flow.py` `a3518f4fa83ceba2d748d0b7e5d44fbc1ac7c0f629e103d8aad3c0c852ba87a7`
- `scar/ir/program/protocol_query.py` `1b17e1e55128d0af2a1080c6e85a3d00f8582e7b5ae7597fdb7f28f3ca9e64ba`
- `scar/ir/program/resumption.py` `ef9d208d57ff6d3cd834529df7b68f377d1ac210f3f262b421c15aeadf5109ac`; `resumption_validation.py` `3e8f0a60bc9b636af1b4e25abc1caeaadfa208dc54b6abf9db89e8d468bf182a`
- `scar/ir/program/drivers.py` `d1a4844d3b00fefed05e2fb743daaf32c9082ae8f0fec3a9db6bce255561aabd`; `driver_validation.py` `cdd8439fb1cd63c3ecd52c42f796a4c0cf15ec53591b0859f25137bee2f0e4d6`
- P2/P3: `scar/ir/execution/calls.py` `a287446babd077c072f51182d12ecc5e670bd2e1700b6396e914e134d95a183f`; `resumables.py` `fdb741f337f7537533c77b2461dcbd424e9723f3ef3e4402907499519c52203f`; `resumable_flow.py` `ea600a4dc8dff0368c17a9a84591d7e30bf6302b76b0602543469da23b27502e`.

No tests, Python probes, full runs, or runtime/source applicability checks were performed for this review.
