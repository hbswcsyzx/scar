# P4-1 delegation, yield-from and cleanup connections

Status: **Proposed implementation contract; not frozen or product acceptance.**

Worktree: `/tmp/scar-structured-model-280qf4mi`; parent supplied P3 revision
`d507a16`. This author read source only. No Python, probe, test, workload, git,
product/test/document edit or P3 archive change was performed. This is the sole
new owned report. Field names below are a concrete proposal for root's single
shared API, not a parallel API already agreed or implemented.

## 1. Observed

The fixed denominator is F20–F23/X25–X26, preserving F12/F13 and X27 connections
where the same original ports are used. `M1_REMAINING_PROTOCOL_PLAN.md` §3
requires positive, wrong-connection, missing-connection and budget results for
each group. This report does not replace that denominator with an enum list or
a count of future unit tests.

### 1.1 Existing canonical facts

- `ProtocolOperation` already has the natural key
  `(scope,clause,operation,slot)`. `ContractResult` selects that exact row and
  its exact own `OperationResult` or selected `InvokeLiteralResult`. The latter
  supplies both original successor and result index. A new result/producer ID
  or a generic NORMAL-only port is unnecessary.
- `ProtocolCall.receiver_use/argument_uses` select the existing ordered actual
  Uses. Validation checks the real CALL/INVOKE shape, membership in actual
  operands, own result and original state sites. It does not currently bind an
  independent expected lookup/iterator/raw source to those Uses.
- `ProtocolFlow.forwards` is evaluation-relative, resets stale copies when the
  producer runs again and does simultaneous CFG renaming/must joins. Its
  prepared indexes and one shared budget are suitable for same-region joins.
- `input_origins`, `paired_input_origins` and `request_input_binding` retain
  original caller/CFG contexts and raw operand ordinals. They are recipes over
  existing records, not runtime call or identity proofs.
- `SuspendTerminator` already has DELEGATION/AWAIT flavors,
  `SavedRole.DELEGATE_REFERENCE`, `DELEGATE_VALUE/DELEGATE_PACKET` input kinds,
  saved actuals and current state ingress. The current protocol consumer loop
  skips these two delegate input kinds; type/current-state checks alone do not
  establish their semantic source.
- `OutcomeAdapter` already preserves an expected `input`, actual `input_use`
  and its own result or host terminal. It has no exact parent-resume-slot or
  parent-expression sink field. Its producer result should remain intact.
- C1 already preserves pending and cleanup-context anchors through logical
  temporal edges using role-checked SavedInput resolution. Context Attach and
  Detach preserve the per-drive caller token contract; that token is not saved.
- E/F/T historical terminal facts and P current session facts are separate.
  `session_flow.py` kills P for calls, INVOKE, suspension, incomplete effects
  and lifecycle writes; a NORMAL SessionUpdate can establish a new post. A
  protocol label does not whitelist a broad helper.

### 1.2 Current bounded gaps

`protocol_validation.py::connection_errors` continues past OperationSiteSubject,
so the delegation/await fixed clauses do not yet supply complete consumer
checks. `protocol_query._derived` has no original delegation call/result sink
inventory. Fixed rows can currently list the mechanism without proving the
requested original-port joins. This is a source observation, not a run result.

One cross-call reuse limit also matters. In `request_inputs.py`,
`consumer_forward` is prepared only when the raw anchor operation is a call
and its raw Use is a **physical actual argument**. Later differing raw/input
caller contexts are otherwise skipped. Thus the existing helper cannot simply
be advertised as covering a caller raw anchor whose child helper receives only
the original exception/value/traceback References. P4 must extend the pairing
with the original input recipe's exact CALL context; adding a fake RAW formal
would change the represented program. No runtime reproduction was run here.

## 2. Inferred minimum design decisions

### 2.1 An actual producer is not an expected source

Tracing a consumer backwards to some lookup/pack is useful evidence but does
not select which lookup/pack belongs to this language site. The expected source
must be independently named by the site contract. Known wrong same-typed values,
another scope, another raw ordinal or another selected N/R result must reject.
Lack of the independent source remains missing, not automatically matched.

### 2.2 Keep producer, consumer and trigger roles distinct

The original call/result is sufficient to describe lookup and invocation.
What is missing is an expected-input attachment and an exact sink attachment.
They must reference original records only; no actual tuple, producer, current
state stamp, native phase, permit or request-history copy is required.

A zero-argument next/close call still has a semantic trigger. That trigger is
not necessarily a physical call argument, and a current injected packet is
not RAW_DRIVER_REQUEST. Treating all close triggers as raw CLOSE is incorrect.

### 2.3 Initial, parent-resuming and delegate-only routes coexist

Initial GetIterator/advance can exhaust without a parent suspension. An item
may go to an actual parent Suspend export. A native delegate-only drive can
return an item/error to its host without entering the parent's body at all.
Only a route actually entering the parent gets a parent BodyDrive/Attach and
P3 association. Delegate exhaustion does not itself imply parent termination.

## 3. Proposed shared records — no new identity family

### 3.1 Exact existing row key and expected raw operand

```text
ProtocolOperationRef(scope, clause, operation, slot)
RawOperandSource(raw: OwnedUse, ordinal: exact nonnegative int)
```

The reference resolves an existing row, not a replacement result. RawOperandSource
references the exact current raw Use plus an ordinal in its original pack;
it is expected-source metadata and is never appended to call_arguments or
invoke_arguments. A missing raw anchor is StaticProtocolGap, not a guessed
nearby pack. Existing original literal/None declarations can refine a known
operand but cannot invent an argument or erase omitted-versus-present shape.

### 3.2 Closed trigger union

```text
RawRequestTrigger(raw: OwnedUse)
InjectedPacketTrigger(packet: ProtocolSourcePort)
InitialAdvance()

CallTrigger = RawRequestTrigger | InjectedPacketTrigger |
              InitialAdvance | StaticProtocolGap
```

- RawRequestTrigger must resolve RAW_DRIVER_REQUEST. For next, allow NEXT or
  the genuine SEND(None) route; for send and throw use their original ordered
  operand sources. Zero actual arguments do not make the trigger optional.
- InitialAdvance is valid only for the first advance of the current GetIterator
  evaluation, before crossing this delegation site's cut. It is not a writable
  Created/Suspended flag. Derive this from the original iterator producer and
  CFG; a path returning from that site's suspension cannot silently use it.
- Close can be raw CLOSE, raw THROW on the actual GeneratorExit-class branch,
  or a current injected GeneratorExit packet. InjectedPacketTrigger checks an
  exact packet port, including its original selected edge where applicable.
  Do not put that packet in a field defined as RAW.
- The trigger variant does not prove exception class. Retain the exact original
  predicate/helper branch and a source/native classification condition where
  no interpreter establishes that classification. Do not add a CLOSE-only fake
  argument or assume every raw THROW is GeneratorExit.
- Lookup/getiter that is not request driven can have a not-applicable trigger;
  requested next/send/throw/close cannot use absence to erase its obligation.

### 3.3 Expected call inputs

```text
ProtocolInputCase(
    guard: ControlEdgeReference | None,
    receiver: ProtocolSourcePort,
    arguments: tuple[ProtocolSourcePort | RawOperandSource, ...],
    trigger: CallTrigger | None)

ProtocolCallInputs(
    site: ProtocolOperationRef,
    cases: tuple[ProtocolInputCase, ...])
```

Natural key is the existing site reference; no independent ID. In a single
unconditional route there is one case and no guard. A reference of an expected
lookup/iterator producer uses an exact same-site ContractResult and role, not
the result of backwards searching the actual receiver. An independent original
expression input or saved delegate Use can also be the explicit expected anchor.
When using a saved delegate anchor, check the original Suspend saved slot is
DELEGATE_REFERENCE, not merely another Reference slot.

Multiple branch alternatives must stay as **whole correlated input tuples**.
For lookupA/rawA/argsA versus lookupB/rawB/argsB merging at one call, independent
source sets would accept lookupA with rawB. Each finite case has its original
edge/caller context; no per-loop-path entries are stored. The implementation
must account for each supplied reaching consumer tuple with one compatible
case, not find one successful pair and ignore known mismatching alternatives.
If an independent expected merge formal already expresses that choice, prefer
referencing it and the original actual→formal bindings. Referencing the actual
receiver itself is not an independent expected-source proof.

Root may choose equivalent multiple attachments keyed by `(site,guard)` rather
than a cases tuple. This representation choice must not change the tuple
correlation, denominator or rule checks.

Rules restrict the sources and arity: GetIterator from the site's original
expression; method call receiver from the selected lookup result; direct
iterator-advance helper from the selected iterator; send from ordinal0; throw
from all original 1–3 ordinals in order; close has no invented actual payload.
Explicit lookup and a combined helper are not forced into one shape. A combined
opaque helper remains a boundary with unproved internal lookup/class behavior.

### 3.4 Exact sinks, preserving adapter output

Reuse the existing OutcomeAdapter source/input_use/output. Add only references
to where its existing own output, or a ProtocolCall own result, must be used:

```text
ProtocolResultConsumers(
    site: ProtocolOperationRef,
    targets: tuple[OwnedUse | SuspendExport | HostTerminal | NativeExit, ...])

SuspendExport(suspend: OperationID)

ResumeSourceBinding(source: ProtocolSourcePort)
# stored as ProtocolOperation with operation=original BodyDrive,
# slot=original BodyResumeInput.slot, in the permitted ingress/result clause
```

ResultConsumers has natural key site, no new producer port. Targets can share
an original result where the actual CFG branches/fans out; the rule determines
which kind of sink is legal. SuspendExport resolves only the original term's
exported Use. An OwnedUse sink names the actual parent-expression operation,
not any same-typed reachable Use. HostTerminal/NativeExit use their existing
ports. Missing exact expression/source-site correspondence remains a condition.

ResumeSourceBinding's target is derived from the outer original Drive and slot;
it does not repeat target operation, Use or after-state. Require BodyResume,
the exact old parent suspension and correct DELEGATE_VALUE/DELEGATE_PACKET
slot. Compare source to the original resume_inputs source Use, which D1 already
connects through the private gate corridor; then inspect the exact parent landing.
Do not expand OutcomeAdapter.output to a sink and thereby lose its own producer.

For the common await/scheduler extension, the same ingress attachment can refer
to the appropriate original SENT_VALUE/THROWN_PACKET slot. That is shared API
scope, not a claim that this report freezes the other author's family rules.

## 4. Exact required chains

| Route | Independent source → actual consumers |
| --- | --- |
| F20 acquisition | Original expression result/Use → get-iterator receiver → that call's own selected result → exact initial advance receiver. Acquisition failure packet takes its own error route, never natural exhaustion. |
| F20 first item | Current advance item result → actual Suspend.exported or explicit host item sink. Store the actual delegate Reference with the original saved role when a parent cut occurs. |
| F20 initial exhaustion | Exact advance exhaustion result/packet branch → real value-extraction adapter own NORMAL result → exact parent expression Use. No executed parent cut or ingress is invented. Extraction failure uses its own RAISE packet. |
| F21 next/send | Current initial/raw trigger → selected next/send dispatch; iterator/lookup result → actual receiver; send ordinal0 → actual argument0; call own item/exhaustion/failure result → its corresponding sink. Missing send is not silently next. |
| F22 throw | Current raw anchor → exact original 1–3 Reference arguments in order → selected delegate.throw receiver/call. Its item stays item, exhaustion becomes parent expression value, other error propagates current packet. Missing method routes the original injected packet to the parent. |
| F23 close NORMAL | Selected raw CLOSE/current GE trigger → real delegate close call. On success continue the original injected GE packet, or the actual source-relative GE construction after raw CLOSE, into the parent. The close helper's None is not an exception packet. |
| F23 close RAISE | Same selected close operation's RAISE packet and actual poststates → fresh pending Raise/parent DELEGATE_PACKET/host error as appropriate. It replaces the older GE/pending reason; never forward a stale same-typed packet. |
| Delegate-only | Exact delegate own result → explicit host item/error consumer. No parent BodyDrive, Attach, NoEntry finish or F seed. If exhaustion/error actually resumes the parent, only then connect the real parent ingress and P3 occurrence. |

Boundary granularity is source-relative. A true Python method RAISE carrying
StopIteration and an internal native helper returning a status/value may encode
the same language event differently. Select original result/predicate/edge
contracts; do not require a nonexistent RAISE, fabricate NORMAL or infer an
exhaustion category merely from arbitrary helper RAISE. Unparsed classifications
are precise conditions, not interpreted opaque internals.

## 5. Validation and query algorithm

1. Prepare one ProtocolFlow, original site/row indexes, parent cut/slot indexes
   and original call/CFG origin indexes. Reuse one graph/caller context and
   shared ValidityBudget across all fields and cases.
2. Resolve each expected source by its independent exact reference. Check
   known FK, scope, selected N/R edge, payload role and own-result conditions
   before comparing actual Uses. Reject State/Binding/private context slots
   used as iterator, argument or item payload.
3. For local copies use the evaluation-relative must solver. For cross-call
   sources retain a single original caller/edge context for the full input
   tuple. Extend the raw pairing for metadata-only caller raw anchors using the
   exact call already present in the input recipe, without changing callee
   formals. Different caller/branch/old-evaluation pairs cannot be combined.
4. Check each actual selected result sink against its exact expected producer.
   DELEGATE_VALUE consumes a final expression value; DELEGATE_PACKET consumes
   the correct current packet. Do not accept a State result, another own result
   index or another Drive/static outcome of the same type.
5. Derive state before/posts only from ExistingAccess or InvokeStateOperand and
   the original selected completion. Callback/partial RAISE updates must stay
   current. Do not enforce a universal normalize→Attach→delegate ordering.
6. Bound finite tuple/context/CFG work; cache immutable original indexes and
   static source recipes. Never instantiate a ProgramIndex/flow or reset budget
   for every receiver, argument, loop visit or consumer. Truncation keeps full
   port/case/consumer counts, NOT_CHECKED entries and a cursor.

## 6. Denominator under deletion

- Every existing ProtocolCall row requires its actual receiver plus every
  original language argument to have an expected-input result; deleting only
  CallInputs leaves MISSING with unchanged counts.
- Every existing semantic adapter/result obligation requires the exact sink
  inventory; deleting only ResultConsumers cannot mean the output is unused or
  the protocol completed.
- Every actual BodyResumeInput is inventoried, including DELEGATE_VALUE/PACKET,
  before reading source bindings. Deleting the binding leaves that exact slot
  missing. All original DELEGATION/AWAIT Suspend markers independently remain
  site/cut inventory even if a protocol relation or scope row is removed.
- The fixed scope/clause ledger preserves missing call/adapter rows. Deleting
  both a protocol row and its attachment does not turn a required clause N/A.
- Zero-cut language sites cannot generally be recovered from arbitrary opaque
  CALL names. They need the explicit original site/scope/source association.
  Without a complete source-site inventory, retain the existing global inventory
  gap; do not claim deleting all site metadata proves no yield-from/await exists.
  This is an exact source-applicability limit, not permission to drop known core
  markers or supplied consumer rows from the denominator.

## 7. X25/X26 composition without new lifecycle records

Use `resumption_cleanup_program`/`resumption_cleanup_invoke_program` for the
existing activation-local C1 mechanisms and `driver_cleanup_release_program`
for commit/session/release corridors; these old fixtures are building blocks,
not coverage of the new delegation consumers.

Across at least two real cuts, save pending with PENDING_COMPLETION, cleanup
anchor with CLEANUP_CONTEXT, private frame fragment with FRAME_CONTEXT and
delegate with DELEGATE_REFERENCE; local bindings use LOCAL_BINDING. The current
caller token is never saved. Resume uses new current shared state and an actual
Attach; the owning cleanup Enter is not rerun.

A lookup/call/close helper may fail after writes. Forward pending/context only
as separate ordinary edge operands, never actual opaque helper arguments. Its
RAISE packet feeds a **new** PendingCompletionDefinition and CleanupReplace;
its NORMAL path may CleanupResume the old pending. Preserve LIFO ownership,
actual poststates and fresh-replacement rules through loops/merges.

AWAIT/DELEGATION suspension and a delegate-only host return do not establish
parent F. A request completing can coexist with a suspended body. Terminal F
comes only from actual body Return/Raise publication or a separately legitimate
existing no-body mechanism. It cannot be borrowed from child/delegate completion.

Keep P current: broad helper/INVOKE kills prior session post; an exact NORMAL
SessionUpdate can reseed and RAISE retains partial current states without that
post. Historical F/T can survive under their fixed no-reset/frame conditions;
release neither consumes F nor proves held references/free. Narrow release can
be inside active driver cleanup only after the correct parent's actual F.
No new request-history, borrow, lifetime or scheduler state graph is needed.

## 8. Required positive/negative/missing matrix

These are future acceptance groups, not reported test results.

| Group | Positive | Required counterexample / missing boundary |
| --- | --- | --- |
| F20-1 | Correct expression→GetIterator→advance | Same-typed lookup/iterator from another site; deleted input attachment. |
| F20-2 | Initial exhaustion reaches parent expression without a cut | GetIterator failure misclassified exhaustion; fabricated parent Drive/Attach. |
| F20-3 | First item reaches exact exported/host Use | Wrong own result index, STATE payload, unused item but a row exists. |
| F21-1 | NEXT and SEND(None) next path; SEND(non-None) send path | Omitted versus explicit None, missing method silently falls back to next. |
| F21-2 | Lookup result→this call receiver with current result | Old loop-carried lookup result after new evaluation; swapped same-typed receiver. |
| F21-3 | BranchA/branchB inputs merge as whole paired tuples | ReceiverA with raw/argumentB; missing case not hidden by another successful pair. |
| F22-1 | THROW 1/2/3 original ordered arguments | Swapped ordinals/raw packs/callers; normalized packet substituted for raw arguments. |
| F22-2 | Caller raw anchor, child helper receives References only | Demanding fake RAW formal; unrelated caller accepted by static callee coincidence. |
| F22-3 | Throw yields item versus exhausts versus propagates error | Item used as final expression; wrong error packet/result edge. |
| F22-4 | Missing delegate.throw injects original exception into parent | New arbitrary same-type packet or no parent ingress when one is required. |
| F23-1 | Raw CLOSE or injected/raw-THROW GE trigger | All close forced raw CLOSE; caller's packet treated RAW; missing zero-arg trigger. |
| F23-2 | Close NORMAL continues exact old GE; RAISE overrides with new packet | Close None used as packet; new exception lost; stale normal-path state after partial RAISE. |
| F23-3 | Delegate-only host item/error with no parent entry | Fake parent Drive/Attach/finished seed to make the graph convenient. |
| Parent slot | Exact own extraction/packet result→DELEGATE_VALUE/PACKET | Wrong slot, other parent cut, wrong old suspension/evaluation or same-type source. |
| X25-1 | Active C1 through two cuts, delegate/pending/context saved, local binding loop | Wrong saved role, caller token saved, repeated Enter, old state or broken LIFO. |
| X25-2 | Helper NORMAL Resume versus RAISE fresh Replace | Pending/context passed as helper actuals; old pending reused as replacement. |
| X26-1 | Real parent terminal→commit→correct owner release | Parent release after delegation/await Suspend or delegate terminal only. |
| X26-2 | HOLD killed by broad helper; NORMAL reseed; RAISE partial | Entire helper whitelisted by protocol tag, stale P after callback or wrong request/body pair. |
| X27/budget | Same persistent activation/actual segment and finite shared accounting | Wrong instance/thread/old occurrence, deleted row removes obligation, budget reset or truncated empty success. |

Known current-port/FK/role/copy contradictions are issues. Unavailable source,
native class/lookup behavior, external identity/capture or incomplete original
caller inventory stay specific gaps. No record or source FactRef is a writable
verified bit. Native/source automatic recovery belongs to later work and is not
claimed here; structural omissions identified above must be implemented in P4.

## 9. Actual source SHA256

All `program/` paths below are under `scar/ir/`.

| Read file | SHA256 |
| --- | --- |
| `docs/M1_REMAINING_PROTOCOL_PLAN.md` | `87a5c029e4a1666b4f8fc73bf7d3886329c64ce8e8f707f76314f35f16676317` |
| `docs/M1_PROTOCOL_CONTRACT.md` | `2a5d982907ed8d9d9e93586f8cf9979002cbac6e27c73de8aac8ce4d0c45c4ac` |
| `docs/M1_PROTOCOL_FAMILY_PLAN.md` | `c516739abd42d200d5709dc87da0a4ff352f86543c22a7d7377586ef3e1c412c` |
| `docs/model/PYTHON_CONTROL_PROTOCOLS.md` | `28d2ac164049598921f7f01c24d6638afdb17161f9a637b555e6192a8c31d02f` |
| `program/protocols.py` | `a51bd800af0b767e8477b95a07aa77ff0a47a0de3222c2804818c295b215fc03` |
| `program/protocol_rules.py` | `be4b601e16401f677b4cbf4e7ba4d2b2d895f4364ce4d1f90d68ed778f92dbe1` |
| `program/protocol_validation.py` | `963e352d3b88ff6d4dcdd220542130fe873859d3f0610af8ab7c44e07a45b049` |
| `program/protocol_flow.py` | `a3518f4fa83ceba2d748d0b7e5d44fbc1ac7c0f629e103d8aad3c0c852ba87a7` |
| `program/protocol_query.py` | `1b17e1e55128d0af2a1080c6e85a3d00f8582e7b5ae7597fdb7f28f3ca9e64ba` |
| `program/request_inputs.py` | `2c93d60c50f786d7e603e5a38314c77fbfb48f4d1a38f4385e05ea42da865415` |
| `program/input_origins.py` | `6212a9aeb8a170387f102ba02be4ae480d641075e52232ded09ac5fca4866631` |
| `program/resumption.py` | `ef9d208d57ff6d3cd834529df7b68f377d1ac210f3f262b421c15aeadf5109ac` |
| `program/resumption_validation.py` | `3e8f0a60bc9b636af1b4e25abc1caeaadfa208dc54b6abf9db89e8d468bf182a` |
| `program/cleanup_forward.py` | `ff99ec4320a1e65079c0988d483faec604838f0e84a260962d85a3a1955629a2` |
| `program/session_flow.py` | `13e90d83f74bd46281a678c778c559ad1d6d52d3d5722137be38848f853a7387` |
| `program/lifecycle_flow.py` | `9fc23f943b8389764876856579db2e82797b2fb375a8c9ecc701b785b094d7f7` |
| `program/session_release_validation.py` | `b96e989a611a518630e2c33bbf61b5f69d4cc015b54166d27f78a6486482e0fc` |
| `tests/fixtures/program_resumption_graphs.py` | `fa6a5bc90cf6605f8498b07835ee68bddd3c043a1ae04263431d41a30af5d93e` |
| `tests/fixtures/program_lifecycle_cleanup_graphs.py` | `2c50833ec7571796d9c500e7a43a8daf46ada860676f4bf6203e3662cc841238` |
