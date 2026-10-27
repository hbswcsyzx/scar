# C2D core bridge: read-only field review

**Status: design review only.** Reviewed the frozen product tree at
`012db08a43c410745996d8bbaa021738f59d0c38` and the C2D proposal files
`driver-field-contract.md` and `driver-root-review.md`. No product files were
changed and no runtime/body-outcome probe was run; root is running the separate
stop-at-first-outcome probe. This review does not close C2.0, C2.4, or M1–M2.

## Finding

`BodyDrive` can fit the existing graph only as a new typed control operation
whose ordinary `Operation.uses` remain the sole local operands. Its
`instance`, `claim`, state, and resume-payload operands need separate owned
UseIDs. Its target body's saved formals/environment and its resume inputs have
different provenance: initial formals come from a particular Create site's
capture routes; resume inputs come from the selected Suspend case plus current
post-delegate state. They cannot be flattened into one position-only call
binding without losing which source supplies each body port.

The proposal's largest concrete mismatch is `BodyStart(creation: OperationID)`.
It pins a Start operation to one static Create site, but a shared driver can
receive the same body from multiple Create sites; one site can also execute
repeatedly and create distinct instances. Keep one body Region per code body,
target it by `RegionID`, and retain per-Create capture alternatives separately.
The dynamic `instance` Use selects an instance only at runtime. A static
Create-site relation is candidate provenance, not proof that this Use came
from that site or that it has not already been driven.

## Existing canonical connection points

| Need | Existing field or rule | Limit relevant to C2D |
|---|---|---|
| Actual operand identity | `Operation.uses`, `call_arguments`, `invoke_arguments` | Uses are unique within an operation. `invoke_arguments` currently exists only for `INVOKE`; a new BodyDrive variant must explicitly opt into one actual list without changing ordinary INVOKE's NORMAL/RAISE semantics. |
| Current state | `StateVersionValue`, `StateAccess`, `CompletionSignature`, `CompletionSuccessor` | INVOKE checks supplied state domains and returns current completion state. No body-driver state mapping exists. |
| Body ports | `EnvironmentInterface`, `FunctionEntryLayout` | Formal parameters and environment entries are a complete, disjoint entry partition, with state ports separate. `EnvironmentInterface.code_definition` is static and does not identify a live function object. |
| Saved and resumed ports | `ResumableBody`, `SuspendTerminator`, `ResumeSuccessor`, `SavedInput`, `ResumeInput` | A Resume case provides one current value for each body state domain and one delivered payload. It intentionally does not provide runtime instance/generation identity. |
| Call candidate | `bind_call()` / `ParameterBinding` | `bind_call` marks generator/coroutine calls `SUSPENDED_BODY` incomplete. Defaults are `DEFAULT_STATE` routes without an actual value; variadic routes describe packing but do not produce the tuple/dict. |
| Region call mapping | `ProgramIndex.environment_call()` | Maps existing call/invoke Uses to entry formals and env refs, but explicitly does not prove runtime target, environment extraction, alias realization, or a body activation. |
| External artifact/source | provider and native boundary records | These map declared artifact elements to graph elements/ports. Execution scope is not a live-instance binding; native flat ports do not establish generator creation, resume, or effects. |

The IR is therefore able to store the needed actual values and state versions,
but the proposed cross-region instance/capture mapping is a new typed relation.
It must not introduce another copied `ValueID` list or treat equal types,
labels, code identity, `LocationID`, or one static operation as runtime identity.

## Concrete gaps in the proposed fields

1. **`CreationCapture(formal: ValueID, argument: int)` only covers indexed
   actuals.** `gen(x, y=default)` has no call-argument index for `y`;
   `*args`/`**kwargs` routes can combine zero or multiple source arguments.
   Current `bind_call` does not resolve generator calls or materialize defaults
   and packs. It also cannot represent the five `EnvironmentInterface` roles
   and captured cells with a single `formal` field. A declared “complete capture”
   would either reject these cases or silently omit required entry ports.

2. **Function environment values are not derivable from body code alone.** Two
   function objects may use the same code Region but different globals,
   builtins, defaults, keyword defaults, and cells. `ResumableCreate.body` plus
   formal actuals does not identify those environment references. Model the
   function-object Use and explicit environment-reference sources. If reading
   the environment needs an operation, that operation must use the object and
   current state and expose any normal/raise and partial-state outcomes. Do not
   infer environment equality from shared `code_definition`.

3. **Cross-region Capture is not a BodyDrive local argument.** The body formal
   ValueIDs live in the body Region, and the Create input Uses live in the
   creator Region. They must be joined through a record that names both exact
   canonical endpoints and checks types/entry ownership. `BodyDrive.instance`
   is a separate Use of the generator object; it does not itself expose the
   stored formal values as local Uses. For Resume, the selected
   `ResumeSuccessor` supplies the payload and saved values, while the state
   actuals must come from the post-delegate versions. Do not reuse the
   Create-time or gate-time state.

4. **State domain sets may differ.** If a body has a domain absent from its
   driver, there is no caller current version to supply; it needs a typed
   instance-state source or an initializer. If the driver has an extra domain,
   it still needs an explicit unchanged-forward path through every BodyDrive
   outcome. A single `lifecycle: LocationID` does not map either case and does
   not prove per-instance ownership. Smallest safe first version: require exact
   body/driver domains and one current-state Use per domain. To admit differing
   sets later, add a total per-domain map with explicit `CURRENT(driver-domain)`,
   `INSTANCE(instance-state-slot)`, or `FORWARD(driver-domain)` variants; reject
   a body-only domain without an initialized instance-state source.

5. **Body outcomes need source-relative reachability.** Region-wide exit
   declarations are not enough: one Start or Resume ingress may reach different
   body terminal operations. Outcome discovery must start at the exact body
   entry or selected resume landing, traverse validated ordinary CFG and cleanup
   routing, and stop at the first reachable Suspend. It must not cross that
   Suspend's temporal successors. Return/Raise and Suspend signatures are
   derived from their actual source operation. Nonterminating paths need not
   manufacture an outcome. The root-owned probe will determine the exact
   bounded traversal rule; this review does not claim it was observed.

6. **Completion operands are scoped to an outcome source.** In a
   `BodyOutcomeSuccessor`, an ordinary UseID must belong to the BodyDrive
   operation; a completion-result index must be interpreted against that row's
   `source`, not an unrelated INVOKE or another outcome. Validate each source
   row against the source-derived signature, exact destination block arguments,
   and exclusive ingress. Prefer an explicitly source-scoped result reference
   if reusing `CompletionResult(index)` would be ambiguous in codec/query code.

## Minimal field correction

Keep the proposal's one actual list and operation-local Uses, with these
changes before freezing:

```text
CreateCaptureTarget = FormalTarget(ValueSlotID)
                    | EnvironmentTarget(EnvironmentRole, cell_slot?)
CreateCapture(target, source: UseID, origin: CaptureOrigin)
ResumableCreate(operation, body, function_object: UseID,
                captures: tuple[CreateCapture,...], handle_result, lifecycle, rule)

BodyStart(body: RegionID)
BodyResume(suspend: OperationID, successor: int)
BodyOutcomeSuccessor(source: OperationID, block: BlockID, arguments: ...)
BodyDrive(instance: UseID, claim: UseID, target: BodyStart|BodyResume, ...)
```

`source` must be an owned Use of the Create operation and identify the canonical
input slot used for that capture; the target resolves through
`FunctionEntryLayout` or `EnvironmentInterface` to exactly one non-state entry
port. `origin` is a typed route (explicit argument, materialized default,
variadic pack, keyword pack, or environment read), not a text label. A route
that has no materialized canonical Use stays incomplete. If Create continues to
be an ordinary helper INVOKE, the route must identify its `invoke_arguments`
Use; defaults/packs/environment reads must be explicit producer operations
before that INVOKE. Capture rows are grouped by `ResumableCreate.operation`, so
two Create sites for one body retain separate capture sets.

`BodyStart(body)` selects code, not a unique object. All compatible
`ResumableCreate` records for that body remain candidate origins. `instance`
must be a distinct owned Use from `claim` and every `invoke_arguments` Use; the
`invoke_arguments` tuple holds only the current state/resume inputs and any
explicit driver-domain pass-through values. It must not duplicate captures,
instance, or claim. Static validation can check candidate target/body and
forwarding; it cannot conclude which Create occurrence produced the live
instance. Runtime evidence is needed for that binding and for single-consume
generation/claim checks.

For simple state layouts, require exact body/driver state-domain equality. If
the driver needs extra internal state, make its unchanged forwarding explicit
per outcome. Do not silently zip state tuples by physical position; join by
`LocationID`. The selected Resume case's payload and state inputs must use
separate owned UseIDs and be passed from the latest completed delegate/callback
state. Body-only state remains unavailable until a typed instance-state source
exists.

## Validator and query order

1. Strict record/wire checks; preserve all old versions and reject any new
   driver tag in old versions.
2. Run ordinary graph/type/state/CFG validation, then C2B resumption and C1
   cleanup validation. Do not let a BodyDrive relation rescue an invalid body.
3. Validate each Create INVOKE: owner, function-object Use, normal handle result
   index/type, current lifecycle domain, and complete disjoint capture partition
   over formals plus environment entry roles. Check each capture source is an
   owned canonical Use and any declared route is supported by its typed
   producer; reject bare index guesses for defaults/packs.
4. Validate BodyDrive shape: `callee=None`, no ordinary results/accesses or
   INVOKE completion signatures, owned distinct `instance`/`claim` Uses, unique
   actual list, typed target, exact state/resume-input mapping. Do not pass
   private FRAME_CONTEXT or DRIVE_CALLER_CONTEXT as ordinary arguments.
5. Validate Start target and per-Create candidate capture layouts. Validate
   Resume target is the exact Suspend case of that body, with every payload and
   state input supplied by the corresponding `ResumeSuccessor`. Require current
   post-delegate values; reject stale pre-gate or pre-callback versions.
6. Derive outcome sites from each ingress using the bounded stop-at-first-
   Suspend traversal. Require one exact source-scoped row per reachable terminal
   site and no extra unreachable source. Check destination args and current
   state forwarding. Do not infer that all declared body exits execute.
7. Check CFG must-forward for the Create normal handle into candidate driver
   instance inputs and gate claim/owner routes where possible. If state/container
   mutation prevents exact static resolution, report conditional/unavailable;
   no location/type-based guess. Queries return declarations/candidates, never
   runtime identity or transformation authority.

Useful derived queries are `create_captures(operation)`,
`body_drive_target(operation)`, `body_drive_inputs(operation)` and
`body_drive_outcomes(operation)`. Return canonical `UseSite`s and the selected
source signature, not copied ValueIDs. Absence of a mapping means
`UNAVAILABLE`/`NO_DECLARED_ROUTE`, not proof that the body has no driver.

## Small acceptance set

- Two Create operations share one body but capture different formal and cell
  references; one BodyStart has both candidate origins. Reject merging their
  capture rows by body/code identity.
- One Create site executes twice and yields two distinct runtime instances;
  static graph checks the route but does not claim one instance or one drive.
- `gen(x, y=default)`, empty/nonempty `*args`, and `**kwargs` either have explicit
  materialized binding Uses or remain incomplete. Reject using `x` for `y` or
  silently dropping a pack.
- Same code with different globals/cells retains separate per-create
  environment routes; shared `code_definition` does not merge them.
- Body and driver share one state domain plus driver-only lifecycle state: body
  receives the latest shared version and every outcome explicitly forwards
  lifecycle. Reject stale gate state, missing body state, and an unforwarded
  driver-only domain.
- Delegate normal and raise both update state; a following BodyResume consumes
  the selected completion's latest versions, not the gate's originals.
- Entry-root and each selected Resume landing have distinct reachable outcome
  sets. A later Suspend is an outcome; its temporal landing is not traversed in
  the same BodyDrive. No synthetic Return/Raise is added for a diverging path.
- Same Value may back instance, data, and repeated arguments only through
  distinct owned UseIDs. Reject a reused UseID, wrong claim, wrong ResumeSlot,
  foreign-region terminal source, duplicate outcome source, and private frame
  token passed through ordinary `invoke_arguments`.

## Evidence boundary

The repository already supplies canonical operands/state (`Operation.uses`,
StateVersion/StateAccess), exact body entry partitions, C2B saved/resume ports,
conditional signature binding, provider/native provenance, and strict graph
validation. It does **not** currently supply a BodyDrive terminator, live
generator-instance/environment extraction, dynamic Create-to-instance
association, lifecycle/generation guard, or host outcome adapter. Provider or
native declarations do not fill those gaps. This is a field-level bridge
review, not evidence of LeWM source coverage, Python driver behavior, or an
authorized transform.
