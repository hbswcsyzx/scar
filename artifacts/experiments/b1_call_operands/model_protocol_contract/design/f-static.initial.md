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
