# Core driver proposal: resolutions to review findings

**Supplement only.** The earlier `core-connection-proposal.md` is left unchanged. This note narrows or corrects its claims; neither file describes implemented BodyDrive support. The accepted frontier remains the existing `ProgramIndex.body_outcomes` result.

## 1. Start uses the body interface, not a selected Create site

`BodyStart(body: RegionID)` must support an instance from outside the analyzed graph and a gate whose instance may have come from several Create sites. It must not require one unique local `ResumableCreate` producer.

The exact logical entry interface is already derivable:

```text
entry_ports(body) = FunctionEntryLayout.parameters.value
                 ∪ EnvironmentInterface.members.reference
```

The first set is ordered by the function signature; environment ports retain their declared role/cell order. Physical entry BlockArgument order remains independent. At Start, the current instance's saved frame provides these ports. This is an implicit, typed frame projection keyed by the existing body port ValueIDs; it creates no second caller-side Value list and does not replace the body BlockArguments as their definitions. Resume instead gets its saved/private ports from the exact existing Suspend case via `resumption_bindings`; only newly supplied ResumeSlots are explicit dynamic inputs. The private frame itself is never an ordinary BodyDrive argument.

`CreationCapture(formal, source)` remains a per-create recipe, not the source of a globally unique Start. For every locally known Create that can be associated with a Start instance, validate that its body and complete capture formal set are compatible with `entry_ports(body)`. Different Create sites may map the same formal slots from different source Uses and different runtime values. If their instance references merge, validate all known candidate recipes; do not pick one by tuple order. An external or unresolved instance remains admissible to the structural BodyStart interface, with its entry-port provenance reported unknown/unavailable until M4 occurrence evidence. Do not reject the Start merely because the producer is external or a unique Create cannot be recovered.

An implementable first pass can validate direct known producers and explicit block-edge forwarding. If it cannot soundly enumerate all possible Create origins through an arbitrary operation/alias, it must mark origin incomplete instead of asserting one producer. `BodyStart.body` is a declared body interface; it does not prove the runtime object's code is that body. A later source/runtime association must establish that relationship.

Known recipe checks are concrete: a local Create capture table must contain each logical entry Reference port exactly once, no extra port, with a Reference-typed operation-owned Use; repeated source ValueIDs are allowed only through distinct occurrence Uses. Function object, globals, builtins, defaults, keyword defaults, parameters, and cells retain their distinct interface roles. Missing default binding, pack, or cell/global lookup producer remains a source-lowering gap; it is not repaired by copying a guessed value into BodyStart.

## 2. A finite outcome frontier is sufficient; no synthetic divergence result

`body_outcomes(body, start)` enumerates the reachable first finite SUSPEND/RETURN/RAISE sites along ordinary CFG and stops at each. This is a finite set of possible completions, not a must-return or exhaustive-execution proof. A body with loops can diverge on some or all paths; the graph's CFG already represents those loops. No extra `DIVERGE` completion, missing-completion issue, or fabricated exit is needed.

An empty frontier is allowed: it means the selected root has no reachable finite first outcome in the represented CFG. A nonempty frontier still allows another path to loop forever. A BodyDrive may expose exactly the finite outcome routes returned by the shared frontier helper without claiming that every execution reaches one. The ordinary caller continuation is only reachable on a represented finite route. This matches ordinary opaque operations that may not return; it does not certify termination or absence of effects. Thus divergence is not, by itself, a reason to keep the static BodyDrive connection open.

## 3. Gate outputs use fresh state versions on both outcomes

For the first driver contract, require the gate INVOKE to produce a NORMAL and a RAISE post-state for every current driver `LocationID`. Each completion signature declares a fresh `StateVersionValue` for each domain, and the corresponding successor receives that exact `CompletionResult` through its edge Use. The BodyDrive landing consumes the NORMAL post-state. A gate RAISE target consumes the RAISE post-state and cannot enter BodyDrive.

This conservative rule removes the “changed versus unchanged” fork in the initial contract. A fresh StateVersion denotes the state after the gate; it does **not** assert that the underlying contents changed, nor that a copy occurred. Core state validation can check freshness, domain, and use order. It cannot establish the gate's actual data effect.

Owner and request remain different: both are the same ReferenceValue as the gate's input, forwarded with their own edge UseIDs to landing formals and consumed by distinct BodyDrive UseIDs. Do not model either as a new completion result. A driver-specific validator must reject a gate-produced replacement reference when exact identity forwarding is required. The corridor probe's six checks demonstrate that core alone accepts such a replacement, so this is not covered by existing INVOKE validation.

The normal target remains private and contains only the paired BodyDrive. The gate's error path follows the actual enclosing operation protocol. If a target-specific native/body applicability guard is false, the model does not invent a new Python exception or declare that guard failure equals a Python raise. There is simply no authorized BodyDrive association on that case; model the generic operation's actual CFG/source behavior separately. A guard that raises is included only when the source/native contract establishes that real behavior.

## 4. Keep raw requests to the four language operations

The raw request enum is exactly `NEXT`, `SEND`, `THROW`, `CLOSE`. Arity and ordered operands are:

| Kind | Raw operand count |
|---|---:|
| NEXT | 0 |
| SEND | 1 |
| THROW | 1–3 |
| CLOSE | 0 |

`SEND(None)` is one explicit Reference operand; it is not NEXT or an omitted argument. `THROW(exc)` and `THROW(exc, None)` remain distinct. Do not snapshot tuple contents or collapse operands. Async-generator operations are represented by their request object/interface creation and `RequestAssociation`; do not add ASEND/ATHROW/ACLOSE duplicates to the raw request enum. The concrete body Resume slot still records the actual sent reference or exception packet required by the selected ResumeSuccessor.

The request interface record and the raw body request have different roles: the former associates a wrapper/request object with a body instance; the latter records the exact NEXT/SEND/THROW/CLOSE operation and operands delivered at a drive site. Their relationship must be an explicit typed relation. Neither matching body code nor matching request/value type proves that an async wrapper belongs to the current instance.

## 5. Revised narrow contract summary

Keep the following fields as the initial structural boundary:

```python
CreationCapture(formal: ValueID, source: UseID)
ResumableCreate(operation, body, function_object, captures, handle_result)
BodyStart(body: RegionID)
BodyResume(suspend: OperationID, successor: int)
RawRequestDefinition(value, kind, operands)
RequestAssociation(operation, request, body, instance_result, raw_request_result)
BodyDrive(operation, gate, instance, start_or_resume,
          request, state_inputs, resume_inputs)
BodyDriveResult(site: OperationID, index: int)
```

`BodyStart` projects the complete declared entry interface from the active instance's frame; known per-site `CreationCapture` recipes are checked for compatibility but no single recipe is mandatory. `BodyResume` derives saved values from `resumption_bindings` and accepts only the missing ResumeSlot inputs. `BodyDriveResult` projects from the shared first-outcome frontier. A direct `gate: OperationID` pairing plus the private single-op NORMAL landing enforces the corridor; no free-standing/escapable permit Value is needed. Driver-only validation checks exact owner/request forwarding and all-domain completion states.

These are declaration and structure rules. They do not prove runtime instance identity, source-to-code identity, actual request-to-instance association, successful admission, or that a selected finite outcome occurred. Those remain later source/provider/runtime evidence obligations. In particular, never turn a static mismatch or unavailable native target into a fabricated Python exception to make the driver graph look complete.
