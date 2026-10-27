# P1 F：Python resumable 协议义务的静态字段草案

**状态：Proposed，未冻结、未实现。** 本稿只给 F（静态协议连接）的最小字段、派生规则和边界；不把手写声明说成 source/runtime 证明，也不把 F 当作 O（动态发生关联）。不运行 Python、pytest、LeWM 或 workload。

## 1. 依据与重要结论

读取基线 HEAD `f9a568182e1672541261020bb9f919609179bb05`，工作树开始时 clean。实际指纹：

| 范围 | SHA-256 |
|---|---|
| `docs/M1_PROTOCOL_FAMILY_PLAN.md` | `b026b709ffb8c5d6c42a95781175f675225dea4c04299d2bbe763e5e2c11b49f` |
| `docs/M1_PROTOCOL_FAMILY_AUDIT.md` | `da0b30175af7387c4794957e4f52be2a91298103a4921d98453450ff562a333f` |
| `scar/ir/program/drivers.py` | `d1a4844d3b00fefed05e2fb743daaf32c9082ae8f0fec3a9db6bce255561aabd` |
| `scar/ir/program/resumption.py` | `ef9d208d57ff6d3cd834529df7b68f377d1ac210f3f262b421c15aeadf5109ac` |
| `scar/ir/program/lifecycle.py` | `326422e0b5c0a89fef3abda0f27037928d6c20bfc5adbd9afc875236678d17d7` |
| `scar/ir/program/structured.py` | `80cf6163b14de463c2e5588ff134b6775fea16ca5b15446903fd212085b6fd92` |
| `scar/ir/program/control.py` | `88d2640c7cb23c454f95888ced4130784fd829e8d1d60292a17000278fbe4ef2` |
| `scar/ir/program/driver_validation.py` | `4a195bab83850b5101c596ef92848a9081e8f3704b05374618b92d1e64a00bd3` |
| `scar/ir/program/lifecycle_validation.py` | `49dee4e82ebe09964a1a72c0d5d19fc91b67645822e7b1abc4961d13ba381daa` |
| `scar/ir/program/no_body_validation.py` | `22669aec4d7c608b1b60c7d161908452f1135e4a1b434b7b80fccccca12607ea` |
| `scar/ir/program/queries.py` | `189a66e66e81eead682adeeaf316ce14af023f9b6c4a453e123f67adcfc2c89d` |
| `scar/ir/program/model.py` | `5659733ce7138c56cf9070bbc970a4a954860aa121db5faed90447658f674152` |
| `scar/ir/program/providers.py` | `fb96fe41a8c5f6cf33a01fd6974830b9dd73ee622107b3659411cc0c4f8d1343` |
| `scar/ir/program/environments.py` | `14e9c16d89db388793236a3636adaac0557c410a5c633c65f7558d413db029f8` |
| prior family ledger `design/family-obligations.md` | `54dffe02e15494ce5e038d5afc7403e3372e96c238dc1083dd0b6622acfb70e7` |
| prior dynamic O proposal `design/o-execution.md` | `fbad0a15f7cfb7d23877f38d3b47beaab32d43689fd903e19042ec06250a505a` |

The existing graph already has `ResumableBody`, `SuspendTerminator`/`ResumeSuccessor`, `RawRequestDefinition`, `ResumableCreate`, `AsyncRequestCreate`, `RequestAssociationRead`, `DriverInterface`, `BodyStart`/`BodyResume`, `BodyDrive`, `BodyDriveResult`, `DriveOutcomeRef`, C1 frame/context and cleanup records, INVOKE NORMAL/RAISE completion signatures, and exact `ControlEdgeReference`. These preserve the sole producer/use/state/CFG graph. The missing piece is the fixed Python contract that joins their exact ports. A `DriverRule` profile name or `ProviderFactReference` locates a claim; neither establishes applicability or runtime execution.

### Startup throw evidence that constrains the design

Reuse, do not rerun, root's bounded CPython 3.14.7 witness: `created_throw_witness.json` SHA `a252e2b377fcbd227f1a188278f52dee9667b41b5a3d88c2e7d287768b0ebc0d`; script SHA `511abb54885c693fd10910fda359e247ed3ebcb3815dcab076d54f15f46009df`. It records: valid exception-instance throw into a Created generator/coroutine/async-generator has no user-body/finally log and closes the object; invalid raw `42` raises `TypeError` but leaves a generator CREATED and later `next` can enter; a custom exception constructor callback that raises `RuntimeError` is observed with the generator CLOSED; a Created throw of a `StopIteration` instance propagates that original exception with `cause=None` and closes; creating an asyncgen `athrow` request leaves it CREATED until the request is awaited. These six observations are narrow CPython 3.14.7 observations, not general rules for every family or implementation.

The archived first assertion attempt passed the empty-body-log check and stopped at the constructor-failure assertion because the script expected CREATED. A later StopIteration-to-`RuntimeError` assertion was never reached and belonged to the root-owned script; JSON shows original StopIteration. This review's earlier inference that every normalization failure restores CREATED is retracted. Do not infer that an arbitrary inner normalizer RAISE is terminal: a factory/normalizer RAISE can be caught and converted to a NORMAL packet/result. Only the real terminal route decides the no-user-entry outcome.

## 2. Minimum static records (proposed)

All records are frozen/exact, reference canonical IDs/Uses, and have no `verified`, `success`, copied state, payload value, or arbitrary phase field. Existing `FactSource`/`ProviderFactReference` are reused. The names below are a design vocabulary, not frozen API.

### 2.1 Fixed profile scope and its source extent

```text
ProtocolScope(
    id: ProtocolScopeID,
    profile: ProtocolProfileID,        # closed, versioned manifest key
    subject: ProtocolSubject,           # exact typed existing extent
    contract: ProviderFactReference,   # source/version locator
    source: FactSource,
)
```

`ProtocolProfileID` is a closed registry whose manifest fixes applicable F clauses, each clause's required endpoint roles/cardinality, and any explicit non-applicable clauses. It is not a user list of wanted checks. The first profiles should be limited to driver-family routes, a single `AWAIT_SITE`, a single `DELEGATION_SITE`, an `AWAIT_WRAPPER_SITE`, `CREATED_THROW`, and the already-special `CREATED_CLOSE`; Task cancellation remains a separate explicit profile if supported. Profile and source locator are conditional source assertions, never runtime authority.

`ProtocolSubject` is a strict union with at least:

| Subject | Exact scope | Constraint |
|---|---|---|
| `DriverSubject(interface_region)` | Existing `DriverInterface` and its body/receiver contract | Only this subject requires `DriverInterface`; it uses existing `BODY` or `ASYNC_REQUEST` as-is. |
| `BodySiteSubject(body_region, operation, site_role)` | One exact await/delegation/close/cancel/adapter Operation in the declared `ResumableBody` | `site_role` is a closed profile-compatible enum; operation must belong to the region. No fake driver or call is inserted. |
| `SourceDefinitionSubject(definition, site_role)` | Existing `OperationDefinitionID`/environment code definition and a source-located adapter site | Used for method lookup/wrapper applicability; it does not manufacture a ProgramGraph operation. |
| `NativeBoundarySubject(boundary, port_role)` | Existing native entry/exit port | Requires existing boundary and exact typed port; conditional unless its source mapping is independently established. |

This permits many await/delegation sites inside one body: declare a body extent plus one typed scope per exact site, or a fixed region-site inventory when that inventory is available. It must not demand that each await helper owns a whole-region `DriverInterface`, split one original body CFG into duplicate fake calls, or classify by spelling alone. If source coverage cannot enumerate all sites, return `SITE_INVENTORY_UNRESOLVED`; do not call the listed sites complete. A missing route under an existing scope is `MISSING`; a missing scope without an exhaustive source inventory means global family coverage is `UNRESOLVED`, not vacuously complete.

### 2.2 Typed route links to original ports

```text
ProtocolRouteLink(
    scope: ProtocolScopeID,
    clause: ProtocolClauseID,          # from profile manifest, not free text
    slot: int,                          # exact manifest endpoint position
    relation: ProtocolRelationKind,    # closed relation registry
    source_port: ProtocolPortRef | Unresolved,
    target_port: ProtocolPortRef | Unresolved,
    edge: ControlEdgeReference | None,
    source: FactSource,
)
```

Each manifest clause determines the number/order of links, relation kind, endpoint variants, and which side must be an exact selected CFG edge. A missing row or unresolved endpoint stays in the ledger. Duplicate/wrong slots, wrong owner Operation, wrong INVOKE edge/result, illegal resume slot, or a route that skips a required operation/state gate is an issue. No `complete=True` marker can erase a missing slot.

`ProtocolPortRef` is a narrow union of references, not another value table:

| Port reference | Existing canonical fact it resolves to |
|---|---|
| `UsePort(operation, use)` | One owned Operation Use; same Value at two UseIDs stays two ports. |
| `OperationResultPort(operation, index)` | One ordinary result on that original operation. |
| `NormalResultPortRef(operation, NormalResultPort)` | Existing INVOKE NORMAL signature result, resolved using `ProgramIndex.normal_result`. |
| `InvokeEdgePort(ControlEdgeReference, CompletionResult | None)` | Actual NORMAL/RAISE successor and its typed result/projection, never an invented common AFTER. |
| `ResumeInputPort(suspend, successor, slot)` / `SavedUsePort(suspend, saved_slot)` | Existing temporal edge or the exact saved Use from that suspension occurrence. |
| `DriveOutcomePort(DriveOutcomeRef)` / `BodyDriveResultPort(drive, index)` | Existing body first-outcome declaration and exact selected driver successor. |
| `StateAccessPort(AccessRef)` / `InvokeStatePort(InvokeBoundaryStateEffect)` | Original ordinary access or true invoke boundary effect, with canonical before/edge/post state. |
| `NativePort(boundary, EntryPortRef | ExitPortRef)` | Existing ordered native signature slot. |
| `ControlEdgeReference` | Exact source Operation and successor index. |

The resolver checks the original owner Operation and typed endpoint (including exact class and nested IDs), then returns original record references. It never reconstructs producer relations from matching ValueIDs, tuple order guesses, or port shape. Current and post-state come from existing StateAccess/INVOKE boundary StateVersion facts. `ExceptionPacketDefinition` only relates the packet's exception/traceback Uses; it does not assert exception construction, active exception state, or normalization.

### 2.3 No-user-entry result is a real route, not a Drive result

Use fixed clauses in the same route ledger for `PREENTRY_REJECT`, `PREENTRY_THROW_DELIVERED`, `PREENTRY_THROW_CONSTRUCTION_FAILURE`, and asynchronous request creation/delivery as applicable. Their expected route shapes are versioned by profile. They reference:

1. the exact original raw-request Operation/Use and `RawRequestDefinition` value/ordered operand Uses (including THROW omitted operand positions versus explicit `None`);
2. the current Created-state carrier at the actual admission point;
3. each real check, exception constructor/normalizer/helper CALL or INVOKE, its actual NORMAL or RAISE edge, and all relevant state effects;
4. the selected final host RETURN/RAISE or external native exit; and
5. any actual lifecycle commit through its original ordinary StateAccess or INVOKE completion state effect.

These are route references only. The clause must reach the real final host outcome through ordinary CFG successors; a nested helper's RAISE may be caught and followed by a NORMAL packet, so it cannot serve as the terminal anchor merely because it is a RAISE. If final lifecycle semantics or host transfer are not captured, report an exact gap. Do not turn a FactRef or the route row into a new producer/state transition.

Created.throw needs distinct ledger paths for (a) rejected input before injection, with TypeError host route and Created state retained; (b) accepted exception instance delivered before user entry, with original exception host route and the profile's observed closed-state effect; and (c) exception-class construction callback, whose own NORMAL/RAISE result is followed through any catch/conversion to the actual terminal. The third path is not uniformly `Created` or uniformly `Closed`: use the selected profile's exact native contract plus actual state route, otherwise retain an unresolved outcome. Initial StopIteration uses the original packet and is distinct from PEP 479 conversion of a StopIteration escaping an entered body. The witness does not specify every possible factory, callback, family, or interpreter version.

`NoBodyFinish` remains tied to its existing Created-close bool branch. It cannot encode initial throw, failed validation, asyncgen request delivery, delegate-only response, or arbitrary callback failure. If representing a no-entry state transition requires a new typed operation meaning, add only that operation when its original CFG/Uses/StateAccess are present; do not silently reinterpret a normal `BodyOutcomeCommit` (it requires `DriveOutcomeRef`) or invent a `BodyDrive`.

## 3. Family-specific connection rules and required negatives

| Path | Required original-port chain / rule | Concrete reject or unresolved case |
|---|---|---|
| Direct generator/Coroutine/GeneratorCoroutine drive | Raw method receiver/request/ordered operands → admission/normalization → exact final gate → `BodyDrive` inputs → `BodyStart` or exact `BodyResume` slots → first body outcome → selected `BodyDriveSuccessor`/host adapter. Use existing D1 `BodyDrive` and `first_body_outcome_operations`. | `SEND(v)` bound from another operation's same-typed Use; stale saved value across a cut; body Return used as host result without adapter; wrong NORMAL/RAISE transfer. |
| Suspended THROW/CLOSE | Raw THROW 1–3 ordered operands or operand-free CLOSE → actual conversion/invoke and NORMAL/RAISE state → exact `THROWN_PACKET` Resume slot and Attach only if parent body resumes → catch/cleanup or exact terminal adapter. | Treat CLOSE as ordinary return; attach parent before delegated close; use an arbitrary exception Value as packet; overwrite latest state on RAISE. |
| Created THROW | §2.3 route. No BodyStart/Resume until a real body entry occurs. The no-entry host result and lifecycle state remain separate from body outcome. | Invalid `42` accidentally closes; class-construction callback failure is forced to Created or Closed by label; initial StopIteration is converted by body PEP 479 rule. |
| Native coroutine await wrapper | Exact `__await__` lookup/call sites and original normal/raise results; link returned iterator through the ordinary call/value/capture relations to an inner BODY driver when one actually exists. Wrapper itself is not a body receiver and not an asyncgen latent request. | Add `DriverReceiverKind` for wrapper; use ASYNC_REQUEST for a native coroutine; clone the inner body CFG; claim every custom iterator is a coroutine. |
| `await` and `yield from` within bodies | Per-site subject in the original body region; exact lookup/call/INVOKE edges, state and resume slots. Scheduler handoff, await-expression result, delegate yielded item/exhaustion and parent expression value are distinct ports. | Require an artificial whole-region DriverInterface for every site; assume delegate method exists/returns normally; attach parent before direct delegate throw/close; map a yielded item to the await result. |
| Async generator request | `AsyncRequestCreate` and `RequestAssociationRead` retain separate request/body/latent original Uses and NORMAL ports; actual awaiting/delivery is a later route; only actual body ingress uses BodyDrive. `ASYNC_YIELD` completes one request/item while the body may remain suspended. | Treat request creation as body execution; infer delivery from request identity/type; treat item delivery as terminal body completion; map coroutine `__await__` wrapper to asyncgen latent. |
| Task cancellation | If in scope, exact task cancel request, later delivery of cancellation exception, handler/uncancel path and actual final task state are separate clauses/operations. | Add `RawRequestKind.CANCEL` for generator methods; infer cancellation delivered from `cancel()` returning; report `cancelled=True` when body catches and returns. Otherwise keep Task semantics as an explicit unsupported external boundary. |

For every CALL/INVOKE helper, include both actual NORMAL and RAISE completion route/state when the operation can raise. A helper's RAISE may feed a local handler and lead to NORMAL terminal publication; route validation follows the selected real CFG, not an exception-kind shortcut. Preserve INVOKE partial post-state on both edges. Source/native applicability, exact runtime object, method lookup success, callback behavior and transformation permission stay conditional/false until separately evidenced.

## 4. Native coroutine wrapper, local await sites, and O boundary

The native `coroutine.__await__` wrapper is a lookup/adapter around the coroutine object, not itself a new `DriverReceiverKind`. A profile-scoped wrapper site binds the original lookup/call and its exact result/exception ports. When that result is an inner generator iterator with a declared resumable body, the ordinary CFG/Uses/call-result/capture path can lead to that body's BODY drive. For a native wrapper that is opaque or external, keep the exact native boundary and an applicability gap. Do not claim that wrapper result identity follows from equal code, type, or ValueID.

There can be several `await` or delegation sites in one source body. The narrow subject is the original body Region plus one exact Operation and site role; a future fixed code-scope inventory may enumerate all of them. Do not require each process to have a `DriverInterface` over the whole region, insert fake operations, duplicate a body CFG, or infer a site from a method name. Missing source/site enumeration keeps `scope_completeness=UNRESOLVED`; it is not a successful “all sites checked” result.

Keep O separate. O's `BodyDriveExecution` links only a real BodyDrive occurrence to persistent activation, actual body ingress/segment and observed outcome. Created.throw rejection/injection before user entry and delegate-only response have no parent BodyDrive and therefore only use F's original host/helper/adapter route. A coroutine wrapper can be linked to an inner BodyDrive only where that drive actually occurs. Instance Use derives from the original Drive operation; an execution segment derives from its actual entry/resume visit. Do not store a second instance Use or duplicate segment fact in O. O does not supply the static F clause ledger; F does not manufacture an execution occurrence.

## 5. Complete preserved denominator and first acceptance set

Keep F01–F24 and X25–X28 exactly as numbered in `M1_PROTOCOL_FAMILY_PLAN.md` §2 and `family-obligations.md`; do not relabel, merge, or count the following as additional requirements. The first implementation/test matrix must map at least one positive and one wrong/missing route to each applicable clause:

| IDs | Acceptance family to retain |
|---|---|
| F01–F04 | Four body kinds; definition/create vs execution; multiple Create and external instance; raw NEXT/SEND/THROW(1–3)/CLOSE, omitted/None, Created admission and non-None rejection. |
| F05–F08 | Created throw no-entry outcomes; running reentry vs legal callback; YIELD and sent value; suspended throw packet/context/catch/partial state. |
| F09–F11 | Return vs body StopIteration adapter; closed repeated operations; close/GeneratorExit/ignored yield/retry and state. |
| F12–F15 | Native coroutine await protocol and zero suspension; scheduler handoff vs await result; reentry/reuse/throw/close; generator-coroutine direct/await distinction. |
| F16–F19 | Async request create/association/delivery; ASYNC_YIELD item vs ongoing body; asyncgen final completion/return restrictions; closed/version differences. |
| F20–F24 | Delegate iterator creation/first advance; next/send methods; throw method missing/failure/item/exhaustion; close/context/pending; Task cancel request vs delivered/caught/suppressed/final status. |
| X25–X28 | C1 cleanup/context/merge and current state; lifecycle/publication/release; O occurrence, entry and outcome; wire/query/CLI, budget, old-scope and explicit unknowns. |

Minimum cross-family positives/negatives: a true direct generator Start→YIELD→Resume→Return with original slot routes; the same graph with a different same-typed send Use; Created throw invalid raw (Created retained) versus valid exception packet (no entry, closed only when actual profile route says so); constructor INVOKE RAISE caught into NORMAL packet versus an actually terminal host raise; inner `__await__` wrapper returning an iterator connected through original result/use to inner BODY driver; two await sites in one region, each separately ledgered; delegate throw returning an item without parent entry versus the parent-resume route; asyncgen request creation without drive versus a later actual request delivery/body ingress; cancellation requested but caught and task returns; wrong INVOKE edge, deleted result link, stale state, and deleted entire scope with source inventory unavailable reported unresolved rather than empty success.

## 6. Explicit scope and next action

**Not implemented or proven here:** exact Python/source mapping for each scope, exhaustive enumeration of await/delegation sites, runtime request-to-object identity, lifecycle state meanings, exception constructor semantics, native wrapper equivalence, Task/event-loop behavior, execution occurrence collection, or transformation safety. The six startup observations constrain only the stated CPython 3.14.7 cases. Full M0–M2, F, O and D3 remain OPEN.

The next bounded decision is to freeze the closed profile/subject/clause schema and endpoint union with one independent review, then implement the fixed ledger/query and exact-port validator before broad records. First wire one synchronous driver and one local await/delegation site; keep startup throw and asyncgen request as distinct no-entry/create-vs-delivery clauses. Only after that should O's real BodyDrive relation be joined. Do not claim D3 complete until all F01–F24/X25–X28 have retained ledger coverage, source-site completeness is explicit, and the actual D3 gate—not a family name or hand-authored scope—passes.

---

## Revision 1 — endpoint and contract correction (supersedes initial §§2.1–2.3 schema)

The initial draft is preserved byte-for-byte as `f-static.initial.md`, SHA-256
`02bda9999214771ad3c2c4f46aa98ff594fb134e8e21b5560cc416533585ba32`. Root and C's
review found that its broad port/link proposal could be miswired while passing type/FK
checks. Treat the generic `ProtocolRouteLink(relation, source_port, target_port)` and its
execution-layer refs below as **withdrawn**. This revision narrows the schema.

### A. Static references must stay program-scoped

1. Static rows must not refer to execution `AccessRef`, `InvokeBoundaryStateEffect`,
   `EvidencePoint`, or execution `Unresolved` (the latter is run/process scoped). For a
   core state input/site, use the existing `scar.ir.program.state_addresses` union:
   `ExistingAccess(operation, index) | InvokeStateOperand(operation, state_use)`.
   For an INVOKE post, pair its original `InvokeStateOperand` with the exact
   `ControlEdgeReference(operation, successor_index)` and `CompletionResult(index)`;
   verify the edge's `CompletionSignature` carries that state location. For an ordinary
   operation's post, `ExistingAccess` resolves its existing `StateAccess.after`. No
   second state carrier or copied before/after value is introduced.
2. A missing static endpoint is `StaticProtocolGap(reason: closed StaticGapReason)`;
   it carries no RunID/process point and cannot be mistaken for an observed execution
   gap. A present but unsupported implementation route has its own reason code. Source
   or profile locators use `ProviderFactReference | StaticProtocolGap`, not execution
   `FactSource`/`Unresolved`.
3. A body-drive result endpoint is
   `BodyDriveOutcomePort(outcome: DriveOutcomeRef, result_index: int)`. `DriveOutcomeRef`
   names both owning `drive` and exact body `source`; a bare `(drive,index)` was
   ambiguous and is withdrawn. An INVOKE result endpoint always includes exact owner
   Operation, actual `ControlEdgeReference`, and `CompletionResult`. For NORMAL it also
   checks the matching existing `NormalResultPort`; for RAISE it checks the RAISE edge
   and its result signature. A naked `NormalResultPort`, naked `CompletionResult`, or
   arbitrary same-typed Value is not an end-to-end result relation.

### B. Only two static subject forms

```text
ProtocolScope(id, profile, subject, implementation, source)
subject = DriverSubject(interface_region: RegionID)
        | OperationSiteSubject(region: RegionID, operation: OperationID)
```

Both are exact ProgramGraph foreign keys. `DriverSubject` requires the already existing
`DriverInterface` and validates its `body`, receiver kind, body, lifecycle and `DriverRule`.
`OperationSiteSubject` requires only that the exact operation belongs to the exact region;
that region may be an ordinary non-resumable wrapper/helper region. Its closed
`ProtocolProfile` determines the expected role (e.g. await lookup, delegate method,
initial throw handler); there is no free-form `site_role`, source-name dispatch, or
invented interface. Code identity/source comes from the original region/environment and
the scope's `ProviderFactReference`, when available. Remove `SourceDefinitionSubject`:
an `OperationDefinitionID` alone is not scoped to a ProgramGraph/artifact here.

A scope is one fixed profile applied to one original driver region or exact operation
site. Each profile has a closed table of required clauses and allowed contract variants;
rows cannot author the clause list. For await/delegation, use one `OperationSiteSubject`
per actual site or a future source-indexed region inventory. If source cannot establish
that the site inventory is exhaustive, report `SITE_INVENTORY_UNRESOLVED`. Removing a
contract row under a declared scope leaves its precomputed clause MISSING. Removing the
scope itself is not detectable without an exhaustive source scope inventory, so global
coverage remains unresolved; it must not become empty-success.

### C. Replace the generic relation language with a closed operation-contract union

Use one canonical table, for example:

```text
ProtocolOperation(scope, clause, slot, operation, contract, source)
```

`(scope, clause, slot)` is an exact unique key. `clause/slot` must appear in the
scope profile's immutable clause table, and that table fixes the permitted exact
contract variant and endpoint roles. `contract` is a closed tagged union, not a
`relation` enum paired with arbitrary ports:

| Contract variant | Required endpoints and mechanical checks |
|---|---|
| `RequestProcessing(raw_request_use, ordered_operand_uses, rule, normal, raise, state_sites)` | Request and operands are the exact owned Uses of the named source Operation and agree with its `RawRequestDefinition` kind/arity/ordinal. `rule` is from the profile's fixed validation/normalization clause, not caller-authored. If the operation is INVOKE, `normal` and `raise` resolve to the actual NORMAL and RAISE edge projections (including `CompletionResult` and matching normal signature); preserve per-edge state. If an exceptional route is not represented, record a gap, never treat its absence as impossible. `state_sites` use `ExistingAccess | InvokeStateOperand`. |
| `ProtocolCall(receiver_use, ordered_argument_uses, selected_result, state_sites, rule)` | The Uses are owned by the exact CALL/INVOKE `operation`; receiver and argument order match the canonical op. `selected_result` is an ordinary `OperationResultPort`, an exact NORMAL INVOKE result+edge, an exact RAISE edge result, or a static gap. `rule` is the finite profile-specific lookup/factory/delegate/adapter clause. A CALL without explicit RAISE cannot discharge a required exception path. |
| `PacketConstruction(packet_value, exception_source, traceback_source)` | `packet_value` must resolve to the existing `ExceptionPacketDefinition`; each component source is an exact existing input/result port. The validator checks its producer/forwarding chain through real CFG edge argument positions and owned Uses. Same type, same protocol tag, or a `ProtocolValueKind.EXCEPTION_PACKET` alone cannot associate an arbitrary Q with this packet. |
| `OutcomeAdapter(outcome: DriveOutcomeRef, input_use, output, rule)` | The exact source first outcome is owned by `outcome`; `input_use` is owned by this adapter operation and must-forward from the selected source through real edge/call routes. `output` is an exact CALL result, exact INVOKE N/R result, or exact host terminal. `rule` is fixed (e.g. generator exhaustion/StopIteration, coroutine await completion, asyncgen item, close result), never a free assertion. |
| `NoEntryOutcome(instance_use, effective_request_use, selected_input, before_site, after_site, terminal, rule)` | Raw request and instance are exact owned Uses. `selected_input` points to the exact accepted exception/result port or a static gap. `before_site` uses `ExistingAccess | InvokeStateOperand`; `after_site` uses the original ordinary `ExistingAccess`, or a typed reference to an actual INVOKE completion state projection, or a static gap. `terminal` is an actual final RETURN/RAISE in the owning region or exact native ExitPort. `rule` is one fixed no-entry disposition clause. The validated route follows actual CFG to that terminal; an inner helper RAISE is not terminal by kind alone. |

The profile fixes which variants/fields discharge each clause. A row cannot claim
`COPY`, `PACKET_OF`, `selected_edge`, or “closed” with a caller-chosen relationship.
Direct copy is derived from canonical core Use ownership, successor index/ordered
argument, and formal producer; when that exact chain is absent or branches without a
must-forward result, return MISSING/UNRESOLVED. Packet construction is accepted only
when its `ExceptionPacketDefinition` components lead to the exact declared sources via
those routes or a fixed factory result. No content equality or arbitrary same-typed
port matching is allowed. A semantic adapter claim remains conditional on its source
profile; the mechanical checker proves the links and shape, not that the implementation
really obeys Python.

For a CALL/INVOKE's state, the contract can name only original program-level sites.
`ExistingAccess` carries the ordinary access index; for INVOKE the edge's
`CompletionResult` is checked against the corresponding state-typed
`CompletionSignature` result and actual ordered successor argument. Do not use the
execution `InvokeBoundaryStateEffect` or silently copy an AFTER state onto both N/R.

### D. Locked corrections to the initial examples

- Native `coroutine.__await__` is an `OperationSiteSubject` in its real wrapper region.
  It is neither `DriverReceiverKind.BODY` nor `ASYNC_REQUEST`, and it does not create an
  asyncgen latent request. A `ProtocolCall` contract references the original lookup/call
  and exact return/raise ports. If the result routes to an inner resumable generator,
  connect through the real result/copy/Create relation to that inner body's existing
  BODY driver. If no such route is captured, keep the gap; do not invent another
  receiver enum or duplicate the inner CFG.
- Await and delegation can have multiple sites within one body, but each local scope is
  an exact `(region, operation)`; it does not demand a `DriverInterface` for every site
  or a synthetic Python call. A future exhaustive source index can supply a region site
  inventory; until then global source-site completeness stays unresolved.
- The six startup-throw observations describe the final action in each tested path;
  they do not identify every intermediate normalizer RAISE. A factory RAISE may be
  caught/packed and the handler may complete normally. `NoEntryOutcome.terminal` must
  point to the actual final host/native exit after selected CFG routing, with current
  state from the actual original access/completion. Do not infer terminal status from
  “factory”, “normalizer”, or exception kind.
- O links only an actual BodyDrive occurrence to an entered segment/first body outcome.
  Initial throw, pre-entry rejection, close-without-entry, and delegate-only routes are
  F-only and point to their real host/helper/adapter operation. They cannot fabricate a
  parent BodyDrive, entry, or `DriveOutcomeRef`.

The preserved initial schema is historical review evidence, not a second competing API.
This appendix supersedes its generic link, execution-state, source-definition, and
ambiguous result endpoint proposals. Full F01–F24/X25–X28 denominator and the status
“Proposed, not frozen” are unchanged.

### E. No-user-entry outcomes must name the transition, not just the exit

The `NoEntryOutcome` row above needs the following narrowing before implementation:

```text
NoEntryOutcome(scope, clause, slot, instance_use, effective_request_use,
               transition, transition_state_sites, selected_input,
               terminal, disposition, source)
```

`transition` is the exact original operation that performs the no-entry state
transition. `transition_state_sites` are only that operation's original
`ExistingAccess | InvokeStateOperand` records. For an ordinary operation, the current
state and actual post-state come from its existing access. For INVOKE, the before-state
comes from its original state operand and each selected NORMAL/RAISE post-state comes
from that exact edge's `CompletionResult` and state-typed `CompletionSignature`; a
single post-state cannot stand for both edges. The row may not borrow state access from
another operation that happens to produce the final host exception.

`terminal` is the exact host RETURN/RAISE operation and, where applicable, its real
`ControlEdgeReference`/completion port. The checker follows the captured ordinary CFG
from `transition` to `terminal`, verifies the selected result or exception packet via
the existing owned Uses and ordered successor arguments, and resolves the state at the
terminal from the original state SSA. A merely reachable same-region RAISE is not
enough. If the edge, packet source, post-state, or path is not captured, retain a
specific gap; do not fill it from equal types or matching names. Several branch-specific
transition rows may reach one shared terminal. They need not be collapsed into one
invented producer.

`disposition` is a closed profile-table value, not a free outcome label:

| Disposition | Static meaning | Lifecycle consequence |
|---|---|---|
| `PREENTRY_REJECT` | The exact selected host outcome occurs before body entry. | Does not seed a finished-body fact. |
| `INITIAL_INJECTION_FINISH` | The closed profile clause identifies the accepted initial exception injection, its actual state transition, and the final terminal route. | May supply the no-body terminal source consumed by lifecycle/publication/release derivation. |

Neither disposition is inferred from RAISE, a state type, or a write by itself. In
particular, `INITIAL_INJECTION_FINISH` is a conditional source-level contract: its
mechanically checked operation/result/state links establish the declared route, while
provider/native correspondence remains an independent evidence obligation. A callback
or factory may itself INVOKE, raise, be caught, and return a packet normally; only the
profile's final no-entry clause is terminal. The final host terminal must reflect the
latest state after the real transition and any intervening captured operations.

This does not generalize `CreatedCloseTest`/`NoBodyFinish`: those existing records remain
specific to a created object's close test. Do not add a new phase flag, finished boolean,
or transferable permit. A later lifecycle derivation can consume the exact
`INITIAL_INJECTION_FINISH` clause and its original terminal/state references. It must
not treat a `PREENTRY_REJECT` as body completion. O still records only actual
`BodyDrive` occurrences; no-entry outcomes have no fabricated drive or entry. Work that
needs a broader profile or source proof remains outside this proposed static layer.

### F. Finite profile and contract table (final design appendix)

This appendix closes the remaining schema choices in Rev1/E. It is a finite first
profile set, not a rule language. Future protocol families need a new versioned profile;
they cannot add a row-authored rule or clause.

#### F.1 Exact record shape and row identity

```text
ProtocolScope(
    id: ProtocolScopeID,
    profile: ProtocolProfile,
    subject: DriverSubject | OperationSiteSubject,
    source: ProviderFactReference | StaticProtocolGap,
)

OperationSiteSubject(region: RegionID, operation: OperationID)

ProtocolOperation(
    scope: ProtocolScopeID,
    clause: ProtocolClause,
    operation: OperationID,
    slot: int,                           # exact non-bool >= 0
    contract: RequestProcessing | ProtocolCall | PacketConstruction |
              OutcomeAdapter | NoEntryOutcome,
    source: ProviderFactReference | StaticProtocolGap,
)
```

The unique key is `(scope, clause, operation, slot)`. The operation belongs to the
scope's exact Region. `slot` is not a caller-supplied coverage list: profile derivation
fixes the required slot set from canonical source records. It is `0` for a single
operation clause, and the original `successor_index` for an INVOKE-edge clause. A missing
derived key is MISSING. `ProtocolOperation` owns the transition for a nested
`NoEntryOutcome`; there is no nested scope/clause/slot/source/transition copy. The outer
operation must be the exact transition operation.

`StaticProtocolGap` has only these members: `SOURCE_SCOPE_INVENTORY_UNRESOLVED`,
`SITE_INVENTORY_UNRESOLVED`, `EXTERNAL_RAW_UNAVAILABLE`,
`RAW_OPERAND_PROJECTION_UNRESOLVED`, `PORT_UNCAPTURED`, `STATE_POST_UNCAPTURED`,
`CALLBACK_BEHAVIOR_UNPROVEN`, `NATIVE_APPLICABILITY_UNPROVEN`,
`TASK_IDENTITY_UNMODELED`, `TERMINAL_ROUTE_UNRESOLVED`, and `UNSUPPORTED_PROFILE`.
Each has a fixed diagnostic meaning. It is not an arbitrary reason string and does not
carry an execution RunID. A malformed or contradictory known endpoint is an issue, not
a gap.

#### F.2 Closed profile members and required clauses

`ProtocolProfile` has exactly these initial members:

| Profile | Required subject and family constraint | Clauses derived from the original graph |
|---|---|---|
| `GENERATOR_BODY_V1` | `DriverSubject`; `ResumableKind.GENERATOR`, receiver `BODY` | `RAW_ADMISSION`, `REQUEST_PROCESSING`, `BODY_INGRESS`, `BODY_SUSPENSION`, `BODY_TERMINAL`, `HOST_ADAPTER`, `CLOSE_ROUTE` |
| `COROUTINE_BODY_V1` | `DriverSubject`; `COROUTINE`, receiver `BODY` | `RAW_ADMISSION`, `REQUEST_PROCESSING`, `BODY_INGRESS`, `BODY_SUSPENSION`, `BODY_TERMINAL`, `AWAIT_COMPLETION_ADAPTER`, `CLOSE_ROUTE` |
| `GENERATOR_COROUTINE_BODY_V1` | `DriverSubject`; `GENERATOR_COROUTINE`, receiver `BODY` | `RAW_ADMISSION`, `REQUEST_PROCESSING`, `BODY_INGRESS`, `BODY_SUSPENSION`, `BODY_TERMINAL`, `DIRECT_HOST_ADAPTER`, `AWAIT_COMPLETION_ADAPTER`, `CLOSE_ROUTE` |
| `ASYNC_GENERATOR_BODY_V1` | `DriverSubject`; `ASYNC_GENERATOR`, receiver `ASYNC_REQUEST` | `ASYNC_REQUEST_SOURCE`, `ASYNC_REQUEST_ASSOCIATE`, `ASYNC_REQUEST_DELIVERY`, `BODY_INGRESS`, `BODY_SUSPENSION`, `ASYNC_ITEM_ADAPTER`, `BODY_TERMINAL`, `CLOSE_ROUTE` |
| `AWAIT_SITE_V1` | One `OperationSiteSubject` in an original body/helper Region | `AWAIT_LOOKUP`, `AWAIT_CALL`, `AWAIT_RESULT_ADAPTER` |
| `DELEGATION_SITE_V1` | One `OperationSiteSubject` whose original body site has `DELEGATION` flavor | `DELEGATE_ITER_LOOKUP`, `DELEGATE_ADVANCE`, `DELEGATE_THROW`, `DELEGATE_CLOSE`, `DELEGATE_PARENT_OR_HOST_RESULT` |
| `COROUTINE_AWAIT_WRAPPER_V1` | One exact lookup/call site in the original wrapper Region; no DriverInterface required | `WRAPPER_LOOKUP`, `WRAPPER_CALL`, `WRAPPER_RESULT_ROUTE` |
| `CREATED_THROW_V1` | One exact created-object throw/normalization site | `RAW_ADMISSION`, `THROW_NORMALIZATION`, each source-inventoried applicable `PREENTRY_REJECT`, `INITIAL_THROW_DELIVERED`, and/or `INITIAL_THROW_CONSTRUCTOR_FAILURE` route, `HOST_TERMINAL` |
| `CREATED_CLOSE_V1` | One exact created-close site | Existing `CreatedCloseTest` true/false edges and the matching `NoBodyFinish`; no generalized NoEntry row |
| `SUSPENDED_CLOSE_V1` | One exact close site for a suspended body | `CLOSE_INJECTION`, `BODY_INGRESS`, `BODY_TERMINAL`, `CLOSE_HOST_ADAPTER` |
| `TASK_CANCEL_EXTERNAL_V1` | One exact task cancellation API site; it does not require a fabricated RawRequestKind | `TASK_CANCEL_REQUEST`, `CANCEL_DELIVERY`, `CANCEL_HANDLER_OR_TERMINAL`, `TASK_STATUS_ROUTE` |

For a DriverSubject, the four family/receiver pairs above are exact and exhaustive for
this version; e.g. COROUTINE+YIELD, ASYNC_GENERATOR+BODY, or a Task site declared as a
generator driver is an issue. Operation-site profiles do not require a whole-region
DriverInterface. Await/delegation sites are scoped one operation at a time, even when a
body contains many sites. Task clauses with no Task identity or delivery link remain
specific gaps; the profile does not infer cancellation from `.cancel()` returning.

The profile table derives expected clauses/slots from existing `RawRequestDefinition`,
`AsyncRequestCreate`, `RequestAssociationRead`, `BodyDrive`, `BodyStart`/`BodyResume`,
`SuspendTerminator`, `BodyOutcomeCommit`, `CreatedCloseTest`, and actual call/invoke
operations. Each source record has the exact slot rule in this table (single slot 0,
or one per actual INVOKE successor index). If the source/profile says a lookup or
normalizer clause is required and its row is absent, that slot is MISSING; it cannot be
omitted to make a shorter contract pass. Removing an entire scope cannot be detected by
the static model unless an exhaustive source scope inventory is available; in that
case global coverage is `SOURCE_SCOPE_INVENTORY_UNRESOLVED`, never empty-success.

#### F.3 Finite contract variants and rule members

The five variants have these exact fields and closed rule sets. Endpoint aliases below
are tagged references to original records, not new producer/value tables.

| Variant / rule members | Required input and owner | Output and fixed applicability |
|---|---|---|
| `RequestProcessing(raw_use: UseID, operand_bindings: tuple[RequestOperandBinding,...], result: ProtocolResultPort, state_sites: tuple[ExistingAccess|InvokeStateOperand,...], rule: RequestProcessingRule)`; rules `CHECK_NEXT`, `CHECK_SEND`, `CHECK_THROW`, `CHECK_CLOSE`, `CHECK_ASYNC_REQUEST`, `CHECK_INITIAL_ASEND`, `NORMALIZE_THROW_INSTANCE`, `NORMALIZE_THROW_CLASS`, `NORMALIZE_GENERATOR_EXIT`, `NORMALIZE_ASYNC_THROW` | `raw_use` is owned by this exact operation. Each `RequestOperandBinding(request_ordinal, operation_use)` names an actual additional owned Use of this operation; it is optional, and no extra Use is fabricated. If an original `RawRequestDefinition.operands` pack exists, the checker follows its exact ordinal source through canonical CFG/must-forward to the listed Use. | Raw-only helpers and external raw objects are valid shapes. If the profile requires expanded arguments but their source cannot be resolved, retain `RAW_OPERAND_PROJECTION_UNRESOLVED`; do not require normalizer operand UseIDs to equal the pack operation's UseIDs. `result` is an exact ordinary `OperationResultPort`, exact INVOKE NORMAL/RAISE `ControlEdgeReference+CompletionResult` (and exact NORMAL signature port), or a gap. Rules are permitted only in the profile table: generator/coroutine raw checks for their family; async request/initial-asend checks for async generators; throw/close normalization only in their matching clauses. |
| `ProtocolCall(receiver_use: UseID, argument_uses: tuple[UseID,...], result: ProtocolResultPort, state_sites: tuple[ExistingAccess|InvokeStateOperand,...], rule: ProtocolCallRule)`; rules `AWAIT_LOOKUP`, `AWAIT_CALL`, `DELEGATE_ITER`, `DELEGATE_NEXT`, `DELEGATE_SEND`, `DELEGATE_THROW`, `DELEGATE_CLOSE`, `ASYNC_REQUEST_AWAIT`, `TASK_CANCEL_CALL`, `EXCEPTION_CONSTRUCTOR` | Receiver and every ordered argument are distinct owned Uses of the exact original CALL/INVOKE; shared Value is allowed, reused UseID is not. `AWAIT_*` only in await/wrapper clauses; `DELEGATE_*` only in delegation clauses; `ASYNC_REQUEST_AWAIT` only in async request delivery; `TASK_CANCEL_CALL` only in task external profile; constructor only in throw-normalization clauses. | Ordinary result is the original operation result; INVOKE result names exact owner, successor edge and `CompletionResult`, with NORMAL checked against `NormalResultPort`. A CALL cannot discharge a RAISE clause without a real RAISE port. The result may feed a later `OutcomeAdapter` or a delegate-only host outcome without any parent Drive. |
| `PacketConstruction(packet: ValueID, exception_source: ProtocolSourcePort, traceback_source: ProtocolSourcePort, rule: PacketRule)`; rules `THROW_PACKET_FROM_NORMALIZED`, `GENERATOR_EXIT_PACKET`, `CANCEL_PACKET_FROM_DELIVERY`, `FORWARD_EXISTING_PACKET` | `packet` must have the existing `ExceptionPacketDefinition`. Each component source is an exact owned Use, ordinary result, INVOKE edge result, BodyDrive outcome result, or reference to an earlier required ProtocolOperation result port. | The definition's exception/traceback fields must resolve to the exact chosen sources through must-forward routes or the fixed constructor call result. This rule only checks the packet links; it does not prove exception construction, active exception semantics, or traceback correctness. |
| `OutcomeAdapter(input: AdapterInputPort, input_use: UseID, output: ProtocolResultPort|HostTerminal|NativeExit, rule: OutcomeAdapterRule)`; rules `GENERATOR_RETURN_TO_STOP_ITERATION`, `GENERATOR_ESCAPE_STOPITER_TO_RUNTIME_ERROR`, `COROUTINE_RETURN_TO_STOP_ITERATION`, `AWAIT_STOPITER_TO_EXPRESSION`, `ASYNCGEN_YIELD_TO_REQUEST_ITEM`, `ASYNCGEN_RETURN_TO_STOP_ASYNC_ITERATION`, `DELEGATE_ITEM_TO_PARENT_YIELD`, `DELEGATE_STOPITER_TO_PARENT_VALUE`, `DELEGATE_ONLY_HOST_ITEM`, `DELEGATE_ONLY_HOST_EXCEPTION`, `CLOSE_RETURN_VALUE`, `CLOSE_IGNORED_EXIT_TO_RUNTIME_ERROR`, `ASYNCGEN_CLOSE_YIELD_ERROR` | `AdapterInputPort` is either `DriveResult(outcome: DriveOutcomeRef, index: int)` or `ContractResult(scope, clause, operation, exact_result_port)` for a required earlier `ProtocolOperation`. `input_use` is owned by this adapter operation and must-forward from that exact input. `DELEGATE_ONLY_*` and throw/normalizer adapters can therefore consume a real CALL/INVOKE result without fabricating a BodyDrive. | Output is an exact ordinary result, exact INVOKE edge/result, host RETURN/RAISE terminal, or native exit. Profile table fixes allowed input role and output role per rule. Body RETURN and host StopIteration/await result remain distinct. |
| `NoEntryOutcome(instance_use: UseID, effective_request_use: UseID, selected_input: AdapterInputPort|StaticProtocolGap, state_sites: tuple[ExistingAccess|InvokeStateOperand,...], selected_edge: ControlEdgeReference|None, terminal: HostTerminal|NativeExit)` | The enclosing `ProtocolOperation.operation` is the actual no-entry transition. `instance_use`, `effective_request_use`, and any direct input Uses are owned by that operation; state sites belong to that same operation. `selected_edge` is required for an INVOKE transition and names its exact NORMAL or RAISE successor; for an ordinary operation it is required when a real branch selects the terminal route, and is absent only when the source has one unambiguous continuation. | The enclosing `ProtocolClause` fixes meaning: `PREENTRY_REJECT` never seeds body-finished state; `INITIAL_THROW_DELIVERED` and `INITIAL_THROW_CONSTRUCTOR_FAILURE` may seed the no-entry terminal source only when the original state transition and terminal route validate. For INVOKE, each selected branch uses its own original CompletionResult/post-state. The terminal is the exact original host RETURN/RAISE op or native ExitPort. Intermediate routes are checked over canonical CFG and must-forward; an unrelated reachable RAISE is not accepted. No nested scope/clause/slot/disposition/transition/source fields are allowed. |

`ProtocolResultPort` has exactly: `OperationResultPort(operation,index)`,
`InvokeCompletionPort(operation,edge,result,normal_port)` (with `normal_port` present only
for NORMAL), or `StaticProtocolGap`. `ProtocolSourcePort` additionally admits
`DriveResult(outcome,index)` and `ContractResult(scope,clause,operation,result_port)`.
`HostTerminal` names an original RETURN/RAISE operation (its payload Uses are derived
from that operation); `NativeExit` names an existing exact native ExitPort. For the
NoEntry `selected_edge`, an INVOKE edge must be owned by the transition operation. For
an ordinary branch, it must be the actual terminator edge selected from the transition
block; its target must lead to the named terminal through original CFG successors. If
more than one branch route needs distinct terminal/state treatment, each exact edge gets
its own derived slot. No route is accepted from region membership or reachability alone.

This table fixes endpoint shape and clause coverage, but does not claim native method
lookup, exception factory behavior, task identity, source completeness, or runtime
object correspondence. Unprovided source/profile clauses remain visible as MISSING or
UNRESOLVED. It preserves all F01–F24/X25–X28 obligations; it does not assert that this
finite first profile set implements every native variant in that denominator.

#### F.4 Last shape clarifications from source review

These clauses supersede any looser interpretation in F.1–F.3:

1. **Raw request projection is not UseID equality.** `RequestProcessing.raw_use` is one
   Use owned by the processing operation. `operand_bindings` contains only operands that
   this operation actually owns. Each binding names the source request ordinal and that
   separate owned Use; the checker relates them by the existing must-forward/source
   projection. A helper that consumes only the raw request is valid, as is a raw value
   with no local pack. If a required source operand cannot be recovered, leave the
   ordinal gap; never require a normalizer UseID to equal the pack operation's UseID or
   invent helper operands. This applies equally to externally supplied raw requests.
2. **Adapter inputs are source-relative.** `OutcomeAdapter.input` is the closed union
   `DriveResult(DriveOutcomeRef, result_index)` or
   `ContractResult(scope, clause, operation, exact_result_port)`. The latter is limited
   by the fixed profile table to an earlier `RequestProcessing` or `ProtocolCall` result.
   `input_use` must-forward from that exact port. Thus delegate-only item/raise and
   normalizer/factory results can be adapted without a parent BodyDrive; no Drive is
   fabricated for them. `NoEntryOutcome.selected_input` is narrower:
   `NoEntryInputPort = ProtocolResultPort | ContractResult` (or a static gap); it cannot
   refer to any `DriveResult`.
3. **NoEntryOutcome has no duplicate identity or disposition.** Its complete contract
   fields are `instance_use`, `effective_request_use`, `selected_input`, `state_sites`,
   `selected_edge`, and `terminal`. The enclosing `ProtocolOperation` supplies the
   unique `(scope, clause, operation, slot)` and its operation is the true transition.
   The clause alone fixes whether it is `PREENTRY_REJECT`, `INITIAL_THROW_DELIVERED`,
   or `INITIAL_THROW_CONSTRUCTOR_FAILURE`; there is no second transition/scope/clause/
   slot/source/disposition field to disagree with the outer row. The two `INITIAL_*`
   clauses are the only no-entry clauses that can seed an initial-injection terminal;
   both still require the actual transition and exact selected branch.
4. **Exact edge selects the state contribution.** For an INVOKE transition,
   `selected_edge` must be its exact NORMAL or RAISE `ControlEdgeReference`. A lifecycle
   or session derivation may seed `INITIAL_*` only from that selected edge's existing
   `CompletionResult` and current post-state, never both successors because they share
   one operation ID. For a non-INVOKE transition, `selected_edge` names the exact
   outgoing branch edge when a branch chooses the route; it is absent only for a unique
   straight-line continuation. The terminal is checked from the selected target using
   canonical CFG and state SSA; an unrelated reachable RAISE is not a substitute.
   This preserves original state and edge records and adds no phase bit or permit.
5. **Slots cannot shrink the obligation set.** `ProtocolOperation` key remains
   `(scope, clause, operation, slot)`. For a clause tied to a concrete core marker,
   derivation enumerates every matching static operation ID; loop iterations reuse that
   static key and belong to O, not extra F slots. For each branch-specific N/R or
   BodyDrive successor obligation, `slot` is the original `successor_index`; all
   required source/result edges are enumerated from the canonical operation signature.
   For source-described lookup/normalizer/adapter sites, the fixed profile source
   inventory supplies exact operation IDs and required slots. Missing any listed row is
   MISSING. If the source inventory itself is absent or non-exhaustive, scope coverage
   remains `SOURCE_SCOPE_INVENTORY_UNRESOLVED`; deleting the whole scope or its source
   inventory never yields empty success. Slot integers are not a caller-authored list.

#### F.5 Fixed rule applicability

The rule enums in F.3 are permitted only in these profile/clause combinations; all other
combinations are invalid. `ProtocolCall` receiver/argument Uses and `RequestProcessing`
raw Use always belong to the exact enclosing operation. The fixed map is:

| Contract rule | Allowed profile / clause | Exact source and output role |
|---|---|---|
| `CHECK_NEXT`, `CHECK_SEND`, `CHECK_THROW`, `CHECK_CLOSE` | Generator, Coroutine, GeneratorCoroutine `RAW_ADMISSION` / `REQUEST_PROCESSING` | Existing `RawRequestDefinition` kind and owned raw Use; any expanded operand binds original ordinal to an owned Use. Result is exact ordinary result or exact INVOKE N/R completion, with edge-specific state. |
| `CHECK_ASYNC_REQUEST`, `CHECK_INITIAL_ASEND` | AsyncGenerator `ASYNC_REQUEST_SOURCE` / `ASYNC_REQUEST_DELIVERY` | Existing request/body/latent/scheduler roles and exact delivery ports. If `AsyncRequestCreate` or `RequestAssociationRead` is present, validate its exact Uses/NORMAL port; neither standalone op is mandatory. First-send argument is checked at actual delivery. |
| `NORMALIZE_THROW_INSTANCE`, `NORMALIZE_THROW_CLASS`, `NORMALIZE_GENERATOR_EXIT`, `NORMALIZE_ASYNC_THROW` | Matching THROW/CLOSE normalization clauses in Generator/Coroutine/GeneratorCoroutine/AsyncGenerator or `CREATED_THROW_V1` | Exact raw input or prior contract result Use into the actual normalization CALL/INVOKE; exact NORMAL packet result or exact RAISE completion and state. Inner RAISE is not by itself the final host terminal. |
| `AWAIT_LOOKUP`, `AWAIT_CALL` | `AWAIT_SITE_V1`, `COROUTINE_AWAIT_WRAPPER_V1` | Original awaitable receiver and ordered lookup/call operands; output exact method CALL/INVOKE result. Result must route to an actual iterator/body or retain native/applicability gap. |
| `DELEGATE_ITER`, `DELEGATE_NEXT`, `DELEGATE_SEND`, `DELEGATE_THROW`, `DELEGATE_CLOSE` | `DELEGATION_SITE_V1` | Original delegate iterator/result and actual method receiver/ordered operands; output exact CALL or INVOKE N/R. Direct callback return is allowed to feed delegate-only host adapter without parent body ingress. |
| `ASYNC_REQUEST_AWAIT` | AsyncGenerator `ASYNC_REQUEST_DELIVERY` | Exact association roles at the existing await/delivery operation, whether standalone or inlined; output must link to the exact request result and, only if present, a real BodyDrive ingress. |
| `TASK_CANCEL_CALL` | `TASK_CANCEL_EXTERNAL_V1` | Original task receiver and cancel operands; call result is only the request result. Actual delivery, handler, and final status remain independent clauses/gaps. |
| `EXCEPTION_CONSTRUCTOR` | `CREATED_THROW_V1` / `THROW_NORMALIZATION` | Exact constructor/factory CALL/INVOKE and actual result. Both normal packet construction and callback RAISE are retained; source contract chooses no-entry clause only after following the actual final route. |
| `THROW_PACKET_FROM_NORMALIZED`, `GENERATOR_EXIT_PACKET`, `CANCEL_PACKET_FROM_DELIVERY`, `FORWARD_EXISTING_PACKET` | Matching packet clause for THROW, suspended close, or task delivery | Exact `ExceptionPacketDefinition` exception/traceback component sources. The task rule remains conditional on external Task identity/delivery. |
| `GENERATOR_RETURN_TO_STOP_ITERATION`, `GENERATOR_ESCAPE_STOPITER_TO_RUNTIME_ERROR` | Generator `HOST_ADAPTER`; GeneratorCoroutine `DIRECT_HOST_ADAPTER` | Exact body RETURN or escaped body RAISE/first-outcome port into the fixed host adapter result. Never equate body RETURN with host RETURN. |
| `COROUTINE_RETURN_TO_STOP_ITERATION`, `AWAIT_STOPITER_TO_EXPRESSION` | Coroutine / GeneratorCoroutine `AWAIT_COMPLETION_ADAPTER`, Await `AWAIT_RESULT_ADAPTER` | Exact body first outcome or await-call completion port to the original StopIteration.value/await-expression result. A scheduler handoff is not this result. |
| `ASYNCGEN_YIELD_TO_REQUEST_ITEM`, `ASYNCGEN_RETURN_TO_STOP_ASYNC_ITERATION` | AsyncGenerator `ASYNC_ITEM_ADAPTER` / `BODY_TERMINAL` | Exact ASYNC_YIELD item or body terminal and exact current request completion result; body suspension and request completion remain separate. |
| `DELEGATE_ITEM_TO_PARENT_YIELD`, `DELEGATE_STOPITER_TO_PARENT_VALUE`, `DELEGATE_ONLY_HOST_ITEM`, `DELEGATE_ONLY_HOST_EXCEPTION` | Delegation parent/host result clause | Exact prior delegate ProtocolCall result/raise or exact parent Drive outcome. Parent ingress is required only for parent-resumed routes; delegate-only routes use their real helper/host terminal. |
| `CLOSE_RETURN_VALUE`, `CLOSE_IGNORED_EXIT_TO_RUNTIME_ERROR`, `ASYNCGEN_CLOSE_YIELD_ERROR` | Created/Suspended close and matching generator family adapter clauses | Existing CreatedCloseTest true edge for created close; otherwise exact injected GeneratorExit/BodyDrive outcome and actual body terminal. A host RuntimeError after yield does not rewrite body state as closed. |

`PREENTRY_REJECT`, `INITIAL_THROW_DELIVERED`, and
`INITIAL_THROW_CONSTRUCTOR_FAILURE` are clause IDs, not a caller-chosen
`NoEntryOutcome.rule`. Only the latter two are conditional finished/no-entry sources;
`PREENTRY_REJECT` never seeds F. The table supports the six observed startup-throw
cases without turning an unobserved normalizer or native method into a proved rule.

The immutable profile manifest fixes, for each row above, its allowed rule, owner kind,
original input role, exact output variant, and whether a NORMAL/RAISE alternative is
required. If a profile requires a lookup, normalizer, constructor, adapter or successor
slot and its ProtocolOperation is absent, report that exact clause/slot MISSING. If the
entire scope is absent, only an exhaustive source-scope inventory can identify it;
otherwise the whole family stays explicitly UNRESOLVED. This is the completeness limit,
not permission to treat omitted scopes as irrelevant.

#### F.6 Derived ingress/terminal rows and edge-specific lifecycle source

Several profile clauses are obligations over existing canonical records, not new
`ProtocolOperation` contracts. In particular, `BODY_INGRESS`, `BODY_SUSPENSION`,
`BODY_TERMINAL`, `ASYNC_REQUEST_ASSOCIATE`, and `CREATED_CLOSE_BRANCH` are derived from
the existing gate/driver/suspension/outcome/lifecycle records. Their profile rows state
which original route must be checked; they do not copy a second port or producer table.

For every actual BodyStart/BodyResume path, `BODY_INGRESS` derives and checks the
consumer chain: the driver's raw/effective request and the selected `RequestProcessing`
result must reach the exact `FinalBodyGate.delivery_arguments`, then the actual
`BodyDrive`'s `resume_inputs`, then the exact existing `ResumeSlotKind`. The required
mapping is fixed:

| Input route | Required BodyStart/BodyResume consumer |
|---|---|
| Initial NEXT | `BodyStart` with no resume slot; it cannot claim a sent value. |
| Initial SEND(None) | `BodyStart` only when the original raw definition/ordinal resolves exactly to Python None. |
| Suspended NEXT | The exact canonical None delivery required by the profile; no same-typed arbitrary None Use. |
| SEND(value) | Original raw operand ordinal 0, or its exact selected processing result, to `ResumeSlotKind.SENT_VALUE`. |
| THROW(args) | The selected normalized packet or exact `ExceptionPacketDefinition` components to `ResumeSlotKind.THROWN_PACKET`; raw args alone are not a packet. |
| CLOSE | The selected GeneratorExit packet to `THROWN_PACKET` only on the real close injection/resume path. |
| Async-generator request | The actual associated request/item handoff to the existing async request resume slot; request creation alone is not delivery. |

The gate's and drive's Uses remain the canonical consumers. The validator checks owned
Use identity, ordered arguments, exact selected N/R edge, must-forward path, slot kind,
and current state; it does not add consumer Uses to `ProtocolOperation`. A missing gate
argument, wrong ordinal, unselected packet, BodyStart with a resume slot, or BodyResume
without the required actual slot is MISSING/invalid under the existing graph relation.
`BODY_SUSPENSION`/`BODY_TERMINAL` similarly query `SuspendTerminator`,
`first_body_outcome_operations`, and existing `DriveOutcomeRef`/`BodyOutcomeCommit`;
they do not demand duplicate contract rows for every core result.

`PacketConstruction` is an endpoint contract within an existing clause, not another
profile clause. Its legal placements are `REQUEST_PROCESSING` for delivered raw THROW,
`THROW_NORMALIZATION` for class/instance normalization, `CLOSE_INJECTION` for
GeneratorExit, or `CANCEL_DELIVERY` for the explicitly external Task profile. The
profile fixes which placement is legal; a row cannot add a packet clause to shrink or
expand the denominator.

For `NoEntryOutcome`, the outer `ProtocolOperation.operation` is the actual transition;
the nested contract does not repeat it. Its `state_sites` must belong to that operation,
and `selected_edge` must be the exact selected CFG edge as defined above. For an INVOKE
transition with NORMAL and RAISE successors, only the selected clause edge contributes
its original `CompletionResult` and current post-state to no-entry lifecycle/session
derivation. The same operation ID does not license seeding both edges. For an ordinary
transition with no state write, current state remains whatever the original state SSA
derives; the contract cannot invent a write. A `PREENTRY_REJECT` never seeds finished
state. `INITIAL_THROW_DELIVERED` and `INITIAL_THROW_CONSTRUCTOR_FAILURE` can provide a
finished/no-entry source only when their exact transition edge, terminal route and
latest state are all linked. This is conditional source-level semantics, not runtime
proof and not `NoBodyFinish`.

The body outcome/async request/lifecycle joins remain O/C2 interfaces: only an actual
`BodyDrive` makes a BodyDrive execution; delegate-only or initial no-entry paths use
their real host/helper/adapter operations. They do not gain an invented BodyDrive just
to share the ordinary outcome adapter. The resulting table is the finite static F
proposal; the full F01–F24/X25–X28 denominator remains visible, and unsupported native
or source-inventory branches remain explicit gaps rather than a completeness claim.

#### F.7 Final join refinements from the independent review

1. **Result references identify a required producer row.** `ContractResult` is exactly
   `(scope, clause, operation, slot, result_port)`. It must resolve to one required
   `ProtocolOperation` row, and `result_port` must be that row's own declared result
   endpoint. Self-reference, cycles without a source endpoint, unrequired producer rows,
   and another result from the same or a same-typed operation do not supply an input.
   Profile rules list the only permitted predecessor clause/slot for each input role.
2. **Packet construction has fixed incoming roles, never self-justifying sources.** A
   `THROW_PACKET_FROM_NORMALIZED` packet takes its exception component from the exact
   `NORMALIZE_THROW_*` result selected by the profile and its traceback component from
   the exact raw THROW traceback ordinal (or the exact profile-specified absent-None
   port). `GENERATOR_EXIT_PACKET` takes its exception component from the selected
   GeneratorExit construction result and its traceback component from that clause's
   fixed None/traceback source. `CANCEL_PACKET_FROM_DELIVERY` requires the exact external
   cancellation delivery source. `FORWARD_EXISTING_PACKET` takes both components from
   one already-defined `ExceptionPacketDefinition` source. In all cases the new packet's
   own definition is only the destination being checked; neither component may name a
   Use/result produced by the packet row itself as its source. Missing input source is
   a specific gap, not a type-based substitution.
3. **Adapter source role is fixed per rule.** Generator-return adapters take the exact
   body `DriveOutcomeRef`/result index for that drive's RETURN; escaped-StopIteration
   conversion takes the exact body RAISE outcome. `AWAIT_STOPITER_TO_EXPRESSION` takes
   the exact await-call RAISE/StopIteration source, while coroutine body Return is
   normalized by the caller/await adapter from that body's exact Return outcome.
   Asyncgen item delivery takes the exact `ASYNC_YIELD` BodyDrive outcome and associated
   request completion; delegate parent-yield/exhaustion rules take the exact delegate
   ProtocolCall result/RAISE; delegate-only host rules take those same actual callback
   ports and have no parent Drive input. Close adapters take the selected GeneratorExit
   injection/body outcome or the actual close callback result. Each rule rejects a
   different source role even when its type matches.
4. **Created-throw coverage is source-derived.** `PREENTRY_REJECT`,
   `INITIAL_THROW_DELIVERED`, and `INITIAL_THROW_CONSTRUCTOR_FAILURE` rows are not a
   caller-selected “one applicable” list. The immutable profile/source inventory and
   original raw-request/normalization CFG determine the applicable routes and exact
   branch slots. Every applicable route must be represented; a missing route is
   MISSING. If the source inventory cannot show whether another validation, constructor,
   or exception route exists, global Created-throw scope coverage remains unresolved.
   The six CPython observations are examples constraining these clauses, not an
   exhaustive route inventory.
5. **Async request associations are role obligations, not mandatory standalone ops.**
   The AsyncGenerator profile checks the fixed BODY/request/latent/scheduler roles and
   the actual delivered request at the existing FinalBodyGate and BodyDrive consumers.
   A present `AsyncRequestCreate` or `RequestAssociationRead` is checked at its exact
   owned Uses and result ports, but neither independent operation is required: creation
   may be external, and association may be inlined in a combined helper/gate. In that
   case the current body/request/effective values must still come from the helper's
   exact owned Uses and selected result/state ports; missing source correspondence is a
   gap, not an inferred equality. `ASYNC_REQUEST_CREATE` therefore means
   `ASYNC_REQUEST_SOURCE` in the clause table: local create if captured, otherwise an
   explicit external source/gap. It never forces a local Create row.
6. **Slot key covers every static branch, not every dynamic visit.** A row for an
   INVOKE-selected no-entry outcome has `slot == selected_edge.successor_index` and
   that exact `ControlEdgeReference`. For an ordinary updater followed by a BRANCH in
   its block, each required selected terminal route has a row keyed by that real
   terminator successor index; do not pin all of them at slot 0. Slot membership is
   derived from the profile's required operation/site inventory plus the original
   outgoing edges/results. A static loop reuses the same operation/edge key; O owns
   repeated dynamic occurrences. Lifecycle/session derivation consumes only the
   selected edge's current post-state, never every edge from the operation.
7. **Names and clauses are consistent.** The GeneratorCoroutine driver's direct host
   clause is `DIRECT_HOST_ADAPTER` everywhere (not `HOST_ADAPTER` in one table and
   `DIRECT_HOST_ADAPTER` in another). `PacketConstruction` is a contract within an
   existing `REQUEST_PROCESSING`, `THROW_NORMALIZATION`, `CLOSE_INJECTION`, or
   `CANCEL_DELIVERY` clause; it does not create a `PACKET_CONSTRUCTION` clause. The
   finite clause/rule tables above are the only initial choices, with the async-source
   adjustment in item 5.

The resulting F core shape remains exactly `ProtocolScope` plus rows keyed by
`(scope, clause, operation, slot)` and one of the five fixed contract variants. It adds
no free relation enum, no alternate payload/state/call graph, no extra async receiver,
and no proof flag. Scope and source inventories remain separate evidence obligations:
removing a row cannot remove a required clause, and removing an unenumerated scope
cannot be called complete.

#### F.8 Reuse the existing result port records

For the implementation boundary, the result-port names in F.3/F.7 are aliases, not new
record variants: ordinary operation output is the existing
`scar.ir.program.model.OperationResult`; an INVOKE output is the existing
`scar.ir.program.model.InvokeLiteralResult(edge: ControlEdgeReference,
result: CompletionResult)`. `InvokeLiteralResult` is a generic completion port name; it
does not mean its payload must be a literal. The operation owner is derived from the
exact edge, and whether an INVOKE result is NORMAL/RAISE plus any matching
`NormalResultPort` is derived from the original `CompletionSignature`. Do not add a
wrapper `InvokeCompletionPort`, duplicate `operation` or `normal_port` fields, or a
second result identity. `DriveResult` continues to reuse exact `DriveOutcomeRef` plus
result index; all existing IDs and nested records are revalidated exactly.
