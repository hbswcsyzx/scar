# Resumable body driver: core connection proposal

**Status:** design proposal only; no driver records or runtime adapter are implemented by this review.  Reviewed tree: `499d708f9092a8bf35915e8db9a004631a223d7b`.  The existing `corridor-probe.py/.json` is a small core-wiring probe, not product validation or runtime evidence.

## Decision

Use a narrow **gate → drive corridor**.  An existing `INVOKE` performs the admission/request gate.  Its `NORMAL` successor is a private landing block with exactly one operation: the paired `BodyDrive`.  The `RAISE` successor cannot reach that drive.  The gate and drive are statically paired; there is no general transferable permit value and no arbitrary CFG path carrying permission.

The `INVOKE`'s `CompletionResult`s carry only state/results actually declared by its normal signature.  In particular, the owner and request are **not** new completion results: each remains the same `ReferenceValue`, forwarded on its own ordinary successor `UseID` into a landing `BlockArgument`, then consumed by a distinct `BodyDrive` `UseID`.  The UseIDs preserve the separate occurrences even when they point to the same ValueID.  Core validation already checks the edge and current state.  A dedicated driver validator must additionally reject a newly constructed owner/request result where exact forwarding is required.

This shape makes the intermediate state visible.  If the gate changes a driver state domain, its `NORMAL` `CompletionSignature` declares the post-gate state, the `CompletionResult` is forwarded to the landing's StateVersion block argument, and the drive reads that current version by `LocationID`.  A pre-gate version then fails the existing stale-state checks.  If a state did not change, its exact current version is forwarded instead.  No state is inferred from list position.

The corridor is deliberately strict: there is one normal predecessor, no operation between admission and drive, and each loop iteration must pass through a new gate.  Normalization, callbacks, or user code belong before the gate as ordinary operations and their latest states must feed it.  This rule is narrow enough to check without an affine permit dataflow analysis.  It does not prove that the gate itself has no hidden callbacks or that it tested the actual Python object; those require later source/provider/runtime evidence.

## Records

Reuse `ProgramGraph` values, `UseID`s, `OperationID`s, `RegionID`s, StateVersionValues, `FunctionEntryLayout`, `EnvironmentInterface`, `ResumableBody`, `SuspendTerminator`, and resume records.  Add typed records in a new resumption-driver table family; do not add a parallel value/provenance graph.

```python
CreationCapture(formal: ValueID, source: UseID)
ResumableCreate(
    operation: OperationID,
    body: RegionID,
    function_object: UseID,
    captures: tuple[CreationCapture, ...],
    handle_result: ValueID,
)

RawRequestKind = NEXT | SEND | THROW | CLOSE | ASYNC_SEND | ASYNC_THROW | ASYNC_CLOSE
RawRequestDefinition(
    operation: OperationID,
    value: ValueID,                 # ProtocolValue(RAW_REQUEST)
    kind: RawRequestKind,
    operands: tuple[UseID, ...],  # ordered; arity preserves omission vs explicit None
)
RequestAssociation(
    operation: OperationID,
    request: UseID,
    body: RegionID,
    instance_result: ValueID,
    raw_request_result: ValueID,
)

BodyStart(body: RegionID)
BodyResume(suspend: OperationID, successor: int)
BodyStateInput(location: LocationID, source: UseID)
BodyResumeInput(slot: int, source: UseID)
BodyDrive(
    operation: OperationID,
    gate: OperationID,
    instance: UseID,
    start_or_resume: BodyStart | BodyResume,
    state_inputs: tuple[BodyStateInput, ...],
    resume_inputs: tuple[BodyResumeInput, ...],
)
BodyDriveResult(site: OperationID, index: int)
BodyDriveSuccessor(site: OperationID, block: BlockID,
                   arguments: tuple[UseID | BodyDriveResult, ...])
BodyDriveTerminator(successors: tuple[BodyDriveSuccessor, ...])
```

The record names are illustrative and can be adjusted to the pending field freeze.  Important properties are the single source of each actual operand, explicit state keyed by location, and typed outcome references keyed by source site.  If a request kind is already represented by an accepted protocol variant, reuse it rather than introduce a second enum.  The raw request record must retain operand order and count: `THROW(exc)` differs from `THROW(exc, None)`; explicit `None` is an ordinary ReferenceValue/Use, not a missing operand.  Do not snapshot argument contents or synthesize a packed tuple.

`BodyStart` does not pin one creation site.  For a local instance, the exact producer of its `instance` ValueID selects the matching `ResumableCreate` and its capture recipe.  The body entry's existing BlockArguments remain the canonical formal values.  `CreationCapture(formal, source)` maps each such entry formal to the original operation-owned Use; it does not create another ValueID.  A repeated execution of the same static Create site may still create distinct runtime objects.

For `BodyResume`, `ProgramIndex.resumption_bindings(suspend, successor)` is authoritative: saved values are selected from the original Suspend-owned Uses and supplied slots are the declared ResumeSlots.  `BodyResumeInput` gives one source Use per non-state slot supplied by this drive.  The private frame/context and `SavedInput`s are never copied to a driver-owned actual list.  Existing suspend and landing BlockArguments remain their only definitions.

`BodyDriveResult(site, index)` is analogous to a typed edge projection, not a persistent Value.  The source signature is derived from `ProgramIndex.body_outcomes(body, start_or_landing)`: for SUSPEND it is exported value plus state handoff; for RETURN/RAISE it is the existing terminator values.  Do not duplicate the source body's output values in the caller graph.  Do not interpret the stable sorting of outcome sites as execution order.

### Existing `INVOKE` corridor

No new Permit Value is needed.  Static pairing can be a `gate: OperationID` field on `BodyDrive` plus validator-derived reverse lookup.  Require:

1. `gate` is an `INVOKE` in the same parent driver region; its normal target is a private block with the paired drive as its sole operation and sole terminator.
2. On that normal edge, each gate-owned owner/request Use has a distinct edge Use forwarding its exact ValueID to a landing BlockArgument.  `BodyDrive.instance` and request operand Uses consume those landing arguments.  No `CompletionResult` may replace either reference unless a separately typed normalization rule explicitly authorizes that new value.
3. Each parent state domain is forwarded on the normal edge.  A changed domain uses the declared NORMAL CompletionResult; an unchanged domain forwards its current Use.  `BodyDrive.state_inputs` covers exactly the body-required domain subset by LocationID.  Any additional driver state domain remains current and is explicitly forwarded on every drive outcome.
4. The gate's RAISE edge does not lead to the body drive.  A merge of accepted and rejected paths is invalid.  There are no intervening operations, branches, or callback-capable regions between gate and drive.
5. All drive outcome edges carry body state from that site's actual output slots, mapped by `LocationID`; non-body driver domains are exact-forwarded current Uses.  The validator rejects omitted, stale, duplicated, or swapped domains.

An INVOKE can also model a creation or request-association operation that may raise before producing an instance/request.  Its result must be anchored to the NORMAL result projection, never the RAISE side.  The ordinary INVOKE validator continues to own state completion and successor typing.

## Validation contract and reuse points

Run the existing core validator first.  The driver validator then uses already validated graph relationships and should report its own typed issue codes; it must not infer proof from labels, filenames, “empty” metadata, or a record's declared status.

### Creation

- `body` names a `ResumableBody`; its region has the canonical `FunctionEntryLayout` and `EnvironmentInterface`.
- The `captures.formal` set is exactly the complete entry Reference partition: every formal parameter ValueID plus every environment member reference ValueID, once each. Preserve the logical formal order from the layout and environment-member order; do not require physical block-argument order to match.
- Every capture source is an ordinary operation-owned Use whose endpoint is a ReferenceValue. Each formal occurrence has a distinct UseID; two positions may intentionally reference the same ValueID. The function-object source is the exact capture source for `EnvironmentRole.FUNCTION_OBJECT`.
- `handle_result` is a ReferenceValue produced on the operation's normal path (ordinary result for a supported non-raising operation, or a NORMAL CompletionResult projected to the normal landing). It cannot be a raise result, unrelated dominating value, or arbitrary block argument.
- A create's extra capture operands must be explicitly accounted in the owning operation's input partition alongside its invocation operands; they must not be silently left “forwarded.” This is a small core/input-accounting integration point. If one Use serves both a function-object argument role and the environment's function-object capture role, the records may reference that same UseID; it remains one physical operand, not two uses. Distinct semantic roles do not justify duplicating the UseID.
- The row declares a structural association only. It does not prove that the function object has the named code, that capture contents correspond to CPython closure cells/defaults, or that runtime creation followed the record.

The current entry/environment tables are enough to define the formal partition, but not to extract runtime defaults, cells, or globals from a FunctionType. Their values must come from real typed operations/source recovery or remain an explicit unavailable boundary.

### Requests and associations

- Validate request kind/arity without value inspection: NEXT/CLOSE have zero raw operands; SEND/ASYNC_SEND one; THROW/ASYNC_THROW one to three. Arity preserves omitted operands versus explicit `None`. If a supported protocol requires another arity, add a versioned kind/rule rather than guessing.
- `RawRequestDefinition.value` is exactly `ProtocolValueKind.RAW_REQUEST`; all ordered operands are ReferenceValue Uses owned by the declared defining/request operation. The operation's state reads/writes remain in ordinary `StateAccess`/INVOKE completions. A record cannot synthesize values from a tuple's contents.
- `RequestAssociation.request` is an exact Reference Use for the wrapper/request object; `instance_result` is a normal-path ReferenceValue and `raw_request_result` a normal-path RAW_REQUEST ProtocolValue. The body is explicit and must agree with the associated local Create when the result's producer is known. If the request object is external or the creation producer cannot be uniquely derived, leave it structurally unassociated/unavailable; do not guess by Python method name.
- The graph can declare a request-to-instance association, but this validator alone cannot prove that an asend/athrow wrapper actually belongs to the generator instance. That requires source/runtime object-identity evidence in a later phase.

### Body drive

- `BodyStart.body` equals the body associated with the drive's local instance producer. Start has no resume payload slots. Its complete non-state entry mapping is derived from the instance's `ResumableCreate.captures`; the drive does not repeat captures.
- `BodyResume.suspend` is a SUSPEND operation in that body; `successor` is an exact existing ResumeSuccessor index. Require exactly one `BodyResumeInput` for every non-STATE ResumeSlot and none for STATE slots. Each slot source Use must match `resume_slot_type`; each body state input is keyed by the same LocationID and consumes the latest caller state.
- Derive `saved` inputs only via `ProgramIndex.resumption_bindings`. They stay body-private; do not duplicate `FRAME_CONTEXT`, cleanup state, saved locals, or pending completion into BodyDrive inputs. Resume does not rerun creation captures.
- Require `BodyDriveTerminator` to enumerate the exact body outcome sites returned by the accepted `body_outcomes` query for that entry/landing. Validate each result index against that site's signature and type; validate state locations, payload roles, and edge arity independently. An unrelated body's site or a result index valid at another site is rejected.
- `body_outcomes` is a first-outcome frontier, not a totality proof. A path that loops forever may have no outcome. Mixed terminating/diverging paths are not made exhaustive by listing the terminating sites. Until a divergence/partial-completion contract exists, label the drive routes as declared possible outcomes and do not claim all body executions are represented.
- Reject `CALL`/`INVOKE` whose `callee` directly names a ResumableBody (existing resumption rule). Only this typed drive protocol may cross the body boundary.

## Queries, wire, and integration

Reuse `ProgramIndex.body_outcomes`, `resumption_bindings`, `suspension_handoff`, `entry_arguments`, `function_entry_layout`, `environment_interface`, `environment_call`, and `use_site`. Add read-only queries such as `resumable_create(operation)`, `request_association(operation)`, `body_drive(operation)`, and `body_drive_routes(operation)`. Return existing `UseSite` objects for endpoint inspection; queries are declarations and must not return a runtime “verified” status.

Implement in this order:

1. Add typed RawRequest/Creation/Association/Drive records, exact row maps, and a typed RAW_REQUEST protocol value. Extend operation input accounting only for declared creation captures/association inputs; preserve one owned UseID per operand occurrence.
2. Add the dedicated BodyDrive terminator/projection variants to core type, successor, and final-block validation. Reuse `value_type`, ordinary edge argument checks, INVOKE's typed completion projection pattern, and current-StateAccess validation.
3. Add a driver validator after core and resumption validation. Derive capture, resume, state, and outcome mappings from existing indexes; apply the narrow gate→drive corridor without a global permit analysis.
4. Add strict codec schema v11. Detect every driver-capability marker (new tables, RAW_REQUEST, BodyDrive terminator/result variants) so old versions v1–v10 reject such graphs rather than drop semantics. Keep old bytes and replay unchanged. New CLI counts may say `driver_structure_validated=true` only after full validation; source/runtime/instance/exclusivity/transform claims remain false.
5. Test focused round-trip and query fixtures, then the frozen old-version golden suite. The existing v10 resumption graph is not a source of new driver capability.

## Minimal positive and negative fixtures

**Positive start.** A Create INVOKE consumes a function object and explicit actual/capture references. Its NORMAL signature produces a new handle plus changed world state; the edge forwards the exact handle and state. `ResumableCreate` maps each logical function/environment entry reference to its owned source Use. A later gate INVOKE forwards the exact same instance/request References on distinct edge Uses and emits a post-gate world state. Its sole normal landing contains BodyDrive(Start). The drive reads the post-gate world by LocationID and sources the body entry mapping through the handle's Create record. The body's first outcome is a yield; its exported ref and handoff state are mapped through typed drive result projections.

**Positive resume.** A Resume targets an exact suspend successor. The gate's state update is consumed; the body-owned saved value comes from the original Suspend saved Use by `resumption_bindings`, while a sent value has one explicit ResumeInput slot Use. The body's subsequent first outcome may be a normal Return or a raise. No saved frame/context is an ordinary driver actual.

**Reject these mutations.** Drop one environment capture; duplicate a formal or reuse one UseID for two distinct actual occurrences; replace the forwarded owner with a new NORMAL Reference CompletionResult; use the old pre-gate state; put a callback operation in the gate landing; send the RAISE edge to BodyDrive; reuse one gate on a loop re-entry; route a stale/mismatched request object to a different instance; omit a ResumeSlot or pass a saved frame as a ResumeInput; map state by tuple order after swapping locations; use a body outcome site/result index from another body; pass `callee=ResumableBody` to CALL; omit the body's diverging path yet claim exhaustive outcomes.

The ignored corridor probe already illustrates the core-level baseline only: real NORMAL completion state can be connected to a successor, the same owner Reference can be forwarded through a distinct Use, stale pre-gate state is rejected by core, while a newly minted owner is accepted by core and therefore needs the driver-specific exact-forwarding check. It also shows that inserting an operation violates the proposed corridor rule. None of those checks executes a Python generator or validates a BodyDrive record.

## Remaining evidence boundary

Static graph identity is not runtime generator identity. A `RegionID` identifies one declared body, not one FunctionType object or one generator/coroutine instance. A static Create operation can execute repeatedly; aliases can exist; the same code can be built with different globals/defaults/cells. An external generator may have no local Create row. `ValueID`, `ReferenceValue.referent_identity`, source witnesses, provider rows, and an empty cost/guard table cannot prove those runtime relationships. Runtime proof would need occurrence-scoped actual function/instance references, process/thread/invocation/epoch anchors, and exact Create→request→drive observation links, with weak identity lifetime rules. Until then, queries should report declared/unknown/unavailable, never “same instance” or “this request resumed this body.”

The whole-program model remains open on partial/diverging BodyDrive behavior, dynamic call binding, default/closure/global extraction, asynchronous wrapper association, callbacks and reentrancy, and occurrence-scoped runtime identity. This proposal closes no source-recovery, runtime-truth, exclusivity, or transformation gate.
