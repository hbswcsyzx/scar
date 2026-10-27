# M1 control interfaces: minimal canonical migration

Date: 2026-10-16. **Proposed; no implementation or automatic coverage claimed.**
Reviewed frozen HEAD `d5311a63211470500c6892af484f500e71c0d61f`.
Scope: types, interface composition, validators and wire migration. No tests run.
Authority: `docs/WHOLE_PROGRAM_MODEL.md` §5 and
`docs/model/PYTHON_CONTROL_PROTOCOLS.md`; their language rules remain unchanged.

## 1. Decision and present gap

Recommend ProgramGraph **v5**, retaining every v1–v4 interpretation. Add one
closed protocol Value family, typed interface declarations and three typed
terminator alternatives. Keep canonical producers, Uses, state SSA and CFG.
Do not extend NORMAL/RAISE until they ambiguously mean language completion,
host return, suspension and device readiness. These are different protocols.

Current `model.py` has Data/Reference/State/LocalBinding values; `ExitPort` and
`CompletionSignature` contain only ValueType, and INVOKE requires NORMAL/RAISE.
Current codec v4 adds resource tables, but supplies no pending/continuation/
environment type. Existing loops and frame overlays do not close this gap.

M1 can implement and validate the following records without an automatic
lowerer. A valid hand-built M1 fixture proves structural consistency only.
M3 must later generate the records from source and replay their construction.

## 2. Closed types and canonical payloads

The following is schema notation, not proposed executable Python syntax.
Every union arm has a fixed enum discriminant checked at construction/decode.
All collections are immutable tuples; IDs and integer indexes are exact types.

```text
ProtocolValue(id: ValueID, region: RegionID,
              origin: BlockArgument | OperationResult, type: ProtocolType)
ProgramValueType = ValueType | LocalBindingType | ProtocolType
ProtocolType = PendingType | ExceptionPacketType | ContinuationType
             | ResumeRequestType | EnvironmentType | ResourceProtocolType
UseRole += PROTOCOL

BlockTarget(region: RegionID, block: BlockID)
ReturnTarget(region: RegionID, port: ControlPortID)
LoopTarget(scope: ControlScopeID)
CompletionCase = Fallthrough(BlockTarget) | Return(ReturnTarget) | Raise
               | Break(LoopTarget) | Continue(LoopTarget)
PendingType(cases: tuple[CompletionCase, ...])
ExceptionPacketType(context_protocol: ExceptionContextProtocol)
ContinuationType(owner: RegionID, site: SuspensionSiteID,
                 resume: ResumeProtocol, frame: SavedFrameInterfaceID)
ResumeRequestType(protocol: ResumeProtocol, cases: tuple[ResumeCase, ...])
EnvironmentType(interface: EnvironmentInterfaceID)
```

`ResumeProtocol` is a closed versioned union: generator, native coroutine,
async-generator, await-iterator. Their allowed requests/results differ.
`ResumeCase` distinguishes FirstEnter/Next/Send/Throw/Close and asynchronous
request forms; Send carries a reference, Throw an ExceptionPacket. No generic
NORMAL token. FirstEnter and Send(None) remain distinct until a typed adapter.
A SuspensionSite declaration names its owner and resume protocol.
`SavedFrameInterface(id, slots: tuple[SavedSlot, ...])` has ordered typed slots;
each slot has a fixed role (BINDING/OPERAND/HELD_REFERENCE/HANDLER/PENDING),
ProgramValueType and optional ControlScopeID for handler/cleanup ownership.
Handler/cleanup stack order is part of this layout, including pending packets.

A protocol value has no arbitrary LiteralOrigin or self-declared source facts.
`Operation.protocol_action` is a closed union of construction/projection/adapter
rules; every payload field is an **operation-owned UseID**, never a new value
store. Its output is `operation.results[result_index]`, checked against type.
State before/after occurs exclusively in existing StateAccess and edge arguments.

```text
PackPending(case, payload: tuple[UseID, ...], result_index: int)
PackException(exception: UseID, traceback: UseID,
              handler_context: UseID, result_index: int)
CaptureContinuation(site, saved: tuple[UseID, ...], result_index: int)
PackResumeRequest(case, payload: tuple[UseID, ...], result_index: int)
BindEnvironment(interface, identities: tuple[UseID, ...], result_index: int)
ProjectProtocol(subject: UseID, field: TypedProtocolField, result_index: int)
AdaptProtocol(rule: AdapterRule, inputs: tuple[UseID, ...])
```

Return has exactly one reference payload; Raise exactly one exception packet;
Break/Continue/Fallthrough carry no data payload. PendingType.cases is a
nonempty unique closed set; packing produces its exact case or an explicit
checked widening. Projection requires a dominating case refinement, or an
invariant field present with the same type in every remaining case.
Unpacking records field provenance, not “depends on every input” identity.
PackException retains exception/traceback references (None is an actual reference)
and a current handler-context StateVersion Use also explained by StateAccess.
That Use is a provenance dependency, not a second current-state store; later
mutable-field/context reads consume current states. No immutable cause/context copy.
Reraise, traceback update and exception-group split/merge are distinct typed
rules using packet Uses and current handler/exception state, not label matching.

## 3. Ports, edges and boundary adapters

Declare interfaces once in `ProgramGraph.control_interfaces`:

```text
ControlInterface(id, owner: RegionID | OperationID,
                 entry: ControlPort, outcomes: tuple[ControlPort, ...])
ControlPort(id, owner: RegionID, protocol: PortProtocol,
            payload_signature: tuple[ProgramValueType, ...],
            state_domain_signature: tuple[LocationID, ...])
PortProtocol = BodyEntry | ResumeEntry(ResumeProtocol) | OperationEntry
             | LanguageComplete(CompletionCase)
             | LanguageSuspend(SuspensionSiteID, ResumeProtocol)
             | HostReturned | HostThrew | ResourceOutcome(ResourceCase)
```

Operation-owned ports have the operation's containing Region as port owner;
Region-owned entry binds its existing Region.entry block. Declarations are
signatures, not another set of values or edges. All port IDs are graph-unique.
For a region with this typed interface, legacy Region.exits **must be empty**;
otherwise existing exits retain their meaning. No two canonical exit lists.
`ControlScope(id, region, parent, kind)` is a small declaration table: kind is
FunctionScope(return_port), LoopScope(header_block), CleanupScope or HandlerScope.
New-profile operations carry a scope ID. Target scopes must be legal ancestors;
loop-else operations belong to the surrounding scope, not the completed loop.
This is the canonical scope index of existing Region/source-control interfaces,
not another Region execution graph. Scopes add no control edges. Nested loop
else inherits the enclosing active break/continue target. M1 checks declared
nesting/ownership; independent source replay must later check truthful membership.

```text
ProtocolInvoke(interface: ControlInterfaceID, arguments: tuple[UseID, ...],
               successors: tuple[ProtocolSuccessor, ...])
ProtocolSuccessor(port: ControlPortID, block: BlockID,
                  arguments: tuple[UseID | CompletionResult, ...])
DispatchProtocol(subject: UseID, cases: tuple[CaseSuccessor, ...])
CaseSuccessor(case: TypedProtocolCase, block: BlockID,
              arguments: tuple[UseID | CompletionResult, ...])
EmitOutcome(port: ControlPortID, payload: tuple[UseID, ...],
            states: tuple[UseID, ...])
Operation.terminator = existing Terminator | these three alternatives
```

ProtocolInvoke references its own declared operation interface. Optional known
callee linkage must also match the callee interface through an explicit adapter;
merely declaring an interface does not establish the actual callable/target.
Legacy completions/invoke_arguments are empty for these new alternatives.
Every outcome has exactly one successor; Produced indexes refer only to that
outcome's ordered payload-plus-state signature, and become target block arguments.
Keep current private outcome-entry rule initially. Results never dominate the
invoke or another outcome. Dispatch cases exhaust the subject's closed cases;
its Produced fields come from that case, not an invented operation result.
EmitOutcome has no local successor; its Uses are the canonical boundary payload
and current states. Signature state domains are unique, ordered and complete.

Typed adapters are ordinary operations with explicit Uses/state/outcome edges.
`AdapterRule` includes SYNC_BODY_TO_HOST, GENERATOR_CREATE, GENERATOR_RESUME,
COROUTINE_RESUME, ASYNC_GENERATOR_RESUME, WITH_EXIT, ASYNC_WITH_EXIT and
FINALLY_RESOLVE, with versioned, individually checked signatures/transformations.
HostReturned after generator creation returns a generator reference; no body
entry occurred. Yield suspends its language activation; the resume adapter may
return that yielded reference to its host caller. Final generator Return becomes
protocolic exhaustion, preserving its value; it is not another yield.
WITH_EXIT may replace a pending Raise with Fallthrough after successful truth;
it cannot suppress Return/Break. FINALLY_RESOLVE preserves pending on cleanup
Fallthrough, replaces it on another completion, or suspends with pending retained.
These adapters declare language rules, not verified dispatch, termination or purity.

## 4. Environments, saved frames and occurrence separation

```text
EnvironmentInterface(id, code_definition: OperationDefinitionID,
  members: tuple[EnvironmentMember, ...])
EnvironmentMember(role: FunctionObject | GlobalsNamespace | Defaults | KwDefaults
                  | CapturedCell(slot: ValueSlotID, cell_position: int),
                  identity_type: ValueType(REFERENCE), domains: tuple[LocationID, ...])
```

Environment binding supplies canonical reference Uses, ordered exactly by the
interface. Defaults/kwdefaults/cells contain mutable state; the implicit body
EnvironmentValue and current StateVersion entry arguments are separate. The
same code may have different environments; different functions may share cells.
A LocationID is a static location/domain symbol, not a globally unique cell
instance. Different symbols do not imply disjointness, particularly with coarse
world: overlap/coverage must be explicit or conservatively retained. No new
independent cell state chain may bypass the current coarse-world dependency.

Later body entry signatures add this **implicit**, nonformal parameter; the
new profile must update formal/ENTER validators explicitly. Existing BOUND_FRAME
and STRUCTURED_BODY profiles retain their exact replay/interface contracts.
Continuation capture saves private frame contents/held references, not a frozen
shared world. Resume consumes current shared state plus saved private state.
Escaped private state also requires current versions/alias handling; it cannot
be restored from an old captured version merely because its name says private.

One existing Region.entry suffices: a resumable activation entry receives request,
continuation/environment and current states, then dispatches to restored blocks.
Restored SSA values are newly defined entry/projection values. No illegal SSA
backedge from a prior invocation's suspended block. Suspension retains frame
state/lifetimes; it does not run final Frame EXIT or promise eventual resumption.

Static ReturnTarget/LoopTarget/site/layout IDs contain no PID, invocation,
object address, generation, ValueVersionID or MaterializationID. EEG binds them
through activation/resume occurrence correspondence; repeated loop visits and
recursive calls remain distinct. Once-per-suspension-generation consumption is
an execution protocol property; static validation alone cannot prove it.

## 5. Resource protocol branch and existing CFG reuse

Reserve a closed `ResourceProtocolType = WorkTicketType | ReadyType` branch,
not an escape-hatch string. WorkTicketType references a canonical producer Value
symbol and ResourceRequirementID(s); ReadyType also declares a typed visibility
requirement and expected logical payload type. Concrete ticket/data/allocation/
materialization generations belong to occurrence bindings and evidence, never
static type arguments. Producer/use scope and requirement ownership are checked.
Neither type can substitute for pending/continuation; Ready may be shared by
many consumers, unlike a continuation generation. Enqueue HostReturned cannot
construct Ready without its explicit resource protocol rule. This branch may
remain unimplemented in the first M1 code slice; reject unsupported variants.

Existing JUMP/BRANCH/block arguments/state accesses already represent if, direct
truth short circuit, loops/backedges, handler bodies and cleanup bodies. Keep
for-next exhaustion matching limited to the advance operation. except* split/
merge and match binding need typed operations, but no new top-level entity.
Packets, variant dispatch, typed ports/adapters and suspension/resumption need
new records/wire. An opaque invoke plus a protocol label is not their substitute.

## 6. File changes, compatibility and rejection gate

- `ids.py`: static ControlScope/ControlPort/ControlInterface/EnvironmentInterface/SuspensionSite/
  SavedFrameInterface IDs. No runtime occurrence IDs in this namespace.
- New `value_types.py`/`control.py`: leaf value types, closed cases, declarations,
  actions and terminators; re-export moved old leaf types from model.py to avoid
  import cycles and preserve imports. `model.py`: ProtocolValue, union/table wiring.
- New `control_validation.py`, called by validation.py: type/use ownership,
  targets/scopes, interfaces, case exhaustiveness, Produced/state availability,
  adapter signatures and complete state transfer. queries.py follows exact fields.
- `codec.py`/record codec: exact v5 tags/fields. Explicit historical projections
  must omit new nested Operation fields as well as top-level tables. Decode old
  versions through their original validators; reject v5 features under old tags.
  Resource-only graphs remain v4; protocol capability selects v5 independently.
- `functions.py`/frame validators: only declare future implicit-environment API
  in M1. New source profile and SourceProgram/inventory wire upgrades occur when
  M3 actually constructs them, never by relabeling historical reports.

Required rejection examples (structural tests, not source/frontend acceptance):
1. A callee Return targets its caller's Return port, or Continue targets another
   loop scope; source-target ownership and boundary adapter validation reject.
2. A NORMAL Produced value is forwarded on Raise, or a pending Return payload
   is projected from an unrefined Return|Raise union; edge/refinement checks reject.
3. Cleanup writes world but emits its incoming world; current-state SSA rejects.
4. Yield uses HostReturned directly or final Frame EXIT, bypassing suspension/
   resume adapter; interface/frame-rule validation rejects that claimed protocol.
5. Resume supplies wrong saved-frame layout, or restores a captured shared world
   instead of its entry current state; layout and state-transfer checks reject.
6. Environment arrives as an extra Python formal, or Ready substitutes for a
   continuation; entry-role and disjoint protocol-type validation reject.

Validation proves declared structure and specified rule consistency. It does
not prove actual call target, environment alias resolution, source completeness,
resource readiness, absence of finalizers, termination or transformation safety.
Historical source/raw replay remains independently required. This review adds
no automatic graph construction, trace capability, backend or simplification.
Passing this control design does not close whole M1 or the user's first stage:
bytes/complex/Ellipsis and other literal representation, typed Location owners/
selectors, and static-to-occurrence bridges still require the separate overall
model audit. A closed ProtocolValue union alone is not a complete model gate.
