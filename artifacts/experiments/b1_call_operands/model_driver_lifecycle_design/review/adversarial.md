# D2 lifecycle contract review: minimal counterexamples and field constraints

Date: 2026-10-18. Product tree was read at `cc44e14a2d173328a4e2f89f405a5add401d85e1`.
This review changes no product, test, or shared documentation files. It does not close
D2, C2, or the whole-program model.

## Scope and evidence classes

Read `docs/M1_DRIVER_CONTRACT_V2.md` §4, `docs/M1_DRIVER_INTERFACES.md`, and current
`drivers.py`, `resumption.py`, `control.py`, `model.py`, `queries.py`,
`driver_validation.py`, and `driver_flow.py`. The records continue to describe static
sites/ports. `BodyDrive` targets one `ResumableBody` region or one exact suspension edge;
`first_body_outcome_operations` stops at the first Suspend/Return/Raise. `StateAccess`,
INVOKE completions, temporal saved/resume inputs, and driver CFG remain the canonical
sources for values and states.

**Observed** below means a CPython 3.14.7 standard-library experiment. **Prior witness**
means a separately archived CPython 3.14.7 probe. **Proposed** means an interface constraint
inferred from those observations. None of these observations establishes the corresponding
SCAR source map, runtime occurrence identity, provider applicability, or behavior on another
Python implementation/version.

## Small lifecycle probe

Command:

```sh
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 python \
  artifacts/experiments/b1_call_operands/model_driver_lifecycle_design/review/lifecycle_probe.py \
  > artifacts/experiments/b1_call_operands/model_driver_lifecycle_design/review/lifecycle_probe.log 2>&1
```

Result: process exit 0, CPython 3.14.7, no dependencies beyond the standard library. The
script contains no `assert`; this is an emitted observation record, not an assertion test.
It records only states, plain text, and return/identity facts. It retains no frames, locals,
exceptions, tracebacks, tensor values, or project objects. The final script SHA256 is
`5829655b35eca68d8c908fb075ee729a8173a6fc3b583eb315b95637ce9f1bc8`; JSON and log are
both `39f010353a01c8b0ed1b048e8ee26114ef28b4406528da4c18fba079bb2e2cb2`. The first
successful probe output is also preserved as `lifecycle_probe.attempt1.*`; its script was
extended for the final run, so attempt 1 should not be attributed to the final script bytes.

### Observed counterexamples

| Action | Request result | Body state / execution | Consequence |
| --- | --- | --- | --- |
| `close()` a never-started generator | returns `None` | `GEN_CREATED → GEN_CLOSED`; body/finally log remains empty | A successful no-body terminal path exists. Do not synthesize a body Return. |
| Never-started `close()` drops a captured argument with `__del__` | returns `None` | The destructor reads `GEN_CLOSED` | Commit closed state before dropping frame-owned references that can re-enter. |
| Return from a started generator while a local has `__del__` | `StopIteration(value)` | Destructor runs during frame release, reads `GEN_CLOSED`; reentrant `send(None)` sees `StopIteration` | Body terminal commit precedes reentrant frame-clear callbacks. |
| `close()` a suspended generator whose `finally` yields | raises `RuntimeError` | Remains `GEN_SUSPENDED` at that yield | A failed close request is not body completion and must not release/finish the frame. |
| Retry the same generator close | returns `None` | `GEN_CLOSED` | Later request can finish the same instance after the earlier failure. |
| Create an async-generator `__anext__()` awaitable | no body result yet | body log empty, `AGEN_CREATED` | Request/awaitable creation is not a body drive. |
| Await that request and receive an item | returns the item | `AGEN_SUSPENDED` | Request completion and body suspension coexist. |
| Create `aclose()` awaitable | no body result yet | still `AGEN_SUSPENDED` | Awaitable creation alone changes neither body outcome nor close state. |
| Await `aclose()` when `finally` yields | raises `RuntimeError` | Remains `AGEN_SUSPENDED` | Async close failure does not prove body terminality. |
| Retry awaited async close | this sample raises `StopAsyncIteration` | Still `AGEN_SUSPENDED` | Even this second request outcome does not establish body closure; the body may remain suspended. |

The raw observations show that frame-drop callbacks see the committed state, not an
intermediate RUNNING/SUSPENDED state. In the async-generator yielding-finally sample, a
second awaited `aclose()` raises `StopAsyncIteration` while `inspect.getasyncgenstate()`
still reports `AGEN_SUSPENDED`. This is a stronger separation between request outcome and
body state, not evidence that retry closed the body. It is a bounded observation of these
CPython paths, not a general claim that every finalizer is synchronous or completes
successfully.

### Prior language witnesses retained

- `model_resume_interfaces/review/language-runtime-probe.json`: create does not enter a
  generator/coroutine/async-generator body; async-generator `asend` returns an item while
  the body is suspended; task cancellation can be caught and suppressed.
- `language-exception-context-probe.json`: an exception caught in a generator survives
  yields; caller `sys.exception()` is restored after each drive; a yielded `finally` can
  preserve pending Return/Raise independently of current handled context.
- `language-delegation-probe.json` and `language-delegate-context-probe.json`: delegate
  throw/close are separate callback paths. A delegated throw may return a delegate yield
  without the parent reaching the `yield from` result expression. In the tested
  parent-except-A / caller-except-B case, delegate `throw`/`close` fast callbacks observe
  B; ordinary parent-driven `next`/`send` callbacks observe A. If delegate throw raises
  back into the parent, the parent can catch it and continue under its restored context.

These prior probes are cited as small language witnesses only; their full group matrices,
implementation provenance, and limits remain in their existing files.

## What the D2 metadata must keep separate

The minimal counterexamples require three independently updated facts, all backed by the
existing core state/value graph rather than copied post-state fields:

1. **Body instance lifecycle:** created, running, suspended, terminal. The body outcome is
   derived from the exact D1 `(drive, source)` frontier site. Suspend leaves a resumable
   instance; Return/Raise is terminal. The request kind alone cannot select the transition.
2. **Request/awaitable lifecycle:** created, being driven, completed, failed, or abandoned.
   Each request has its own owner/actuals. An async-generator item request can complete
   while its body remains suspended. A failed close request can leave the same body
   suspended; for sync generators this probe's retry closes it, while the async-generator
   retry raised `StopAsyncIteration` and still left the body suspended. Keep request-result
   classification separate from the inspected/body-phase transition.
3. **Driver/session occupancy:** whether a family-specific request currently owns a body or
   may be retried/continued. Do not equate this with either the body phase or the single
   request object's phase. Existing `LocationID`/`StateVersion` records should represent
   each mutable domain; D1's `D` remains the full driver state set and `L ⊆ D` its lifecycle
   subset. Extra driver domains must flow through actual state ports, not be silently reset.

Recommended narrow interpretation of the §4 candidates:

- `DriveOutcomeRef(drive, source)` identifies a static, privately selected BodyDrive
  frontier source. It does not identify a dynamic occurrence or an instance by itself.
- `BodyOutcomeCommit(operation, outcome, instance, session)` may mark terminal lifecycle
  only when `source` is the actual Return/Raise outcome for this drive. Its operation must
  be the first non-callback operation on that private outcome path, own real Uses for the
  current instance/request/session it changes, and perform its state transition through
  ordinary `StateAccess`/completion. Derive `SUSPENDED` versus `FINISHED` from the source;
  do not accept a separate status label that contradicts it.
- A Suspend-side commit/session update may set the particular request COMPLETE while
  leaving body SUSPENDED (e.g. the observed async-generator item); another Suspend can
  leave a coroutine/session pending. These need distinct versioned transitions, not a
  single `complete => closed` rule.
- `NoBodyFinish` is narrower than “no body outcome”: it is a typed, normal, state-guarded
  terminal no-body path such as close on a CREATED instance. Its witness must be the exact
  successful protocol edge, and the operation must update the current body's lifecycle
  before it releases captured/frame references. A normal helper result by itself is not
  sufficient. An already-CLOSED idempotent reply is request completion with no new body
  transition; a delegate-only yielded item is request completion with the parent body
  still suspended; rejection is a failed request with body state preserved.
- Do not classify every `close()` as `NoBodyFinish`. On a SUSPENDED generator it executes
  body cleanup. If cleanup yields, the request raises while the body remains suspended; if
  cleanup exits, the body reaches a real terminal outcome. The current protocol state and
  body frontier decide which path occurred.
- `TerminalFrameRelease` must follow the closed-state commit and may run reentrant user
  finalizers while dropping references. It should claim only that the owner references
  were dropped/transferred, never that the object was freed or finalized. For a narrow
  versioned frame-clear primitive whose finalizer errors are unraisable, do not invent a
  host RAISE edge. If the actual release helper can propagate, model its normal/raise
  completion and partial state explicitly as an INVOKE.
- A frame `finally` suite, delegate callback, lookup/close helper, or host adapter callback
  that executes before the body source is known remains ordinary CFG/body work. Do not
  move the terminal commit before these operations just to protect it from reentry. The
  observed ordering is: complete body cleanup/derive Return or Raise; commit terminal
  state; only then drop terminal frame references that may re-enter.
- Session/update `source` must identify a real path event and current owner/request Uses.
  A static normal edge is not proof that the request was created, driven, or associated with
  the current body. The edge and its `StateAccess` post-state must be checked on the actual
  CFG. Static records cannot supply dynamic occurrence, epoch, generation, or callback
  ordering proof without separate runtime/source evidence.

## Multiple creates, external instances, and extra driver state

The existing D1 shape is the right non-name-based basis and does not need a per-Create
driver:

- Each `ResumableCreate(operation, body, function_object, captures, handle_result, rule)`
  states one static constructor site and its own entry-port capture recipe. Two sites may
  name the same body Region but provide distinct global/default/cell references. Repeated
  execution of one site may create many dynamic instances. Nothing should infer that a
  static `OperationID` is one object.
- `BodyStart(body)` selects the code/interface; the actual `BodyDrive.instance: UseID`
  selects the current runtime reference. One shared driver may accept instances from
  multiple Create sites and an explicit external boundary. External instances can be
  structurally admitted as reference inputs without inventing a `ResumableCreate`; their
  capture/source correspondence stays unknown until evidence connects that runtime object
  to an interface. Same code or method name does not supply it.
- For an unknown external instance or merged set of creators, keep the instance reference
  as the actual driver Use and retain a typed unresolved-origin boundary. Do not force one
  creator, clone the body graph, merge captures by code identity, or claim a unique
  CreationCapture. When a Create is known, validate that its recipe is compatible with the
  body entry/environment layout; occurrence-to-create is a later runtime/source relation.
- Request/latent request and body owner stay distinct Uses. In particular an async-generator
  `asend`/`athrow`/`aclose` request object is not the body instance and is not the raw
  operation that advances the body. Current request association must be read/guarded on the
  path immediately before drive; stale association from Create is not enough.
- Use the region's complete state domains `D` at gate NORMAL/RAISE and preserve state by
  `LocationID`. Only body-required state is consumed by the body entry; `L` may be a strict
  subset of `D`. Extra `D - body_domains` must have explicit actual successor Uses or a real
  state effect. Avoid positional zipping and a second handwritten state list.

## Small D2 acceptance nodes

These are finite structural/language checks, not a claim of complete Python lifecycle
coverage:

1. **Created close:** a real no-body close success; the frame-drop callback reads CLOSED;
   no BodyDrive outcome is fabricated. Negative: attach a body Return to this route.
2. **Suspended close fails then retries:** first `close`/`aclose` RAISE leaves the body
   SUSPENDED and its frame retained. The sync-generator retry in this probe terminates;
   the async-generator retry reports `StopAsyncIteration` yet remains SUSPENDED. Negative:
   infer FINISHED or run terminal release from either request result alone.
3. **Async item request:** `__anext__`/`asend` creation is distinct from driving; successful
   item result marks that request complete while body remains SUSPENDED. Negative:
   request COMPLETE implies body FINISHED.
4. **Body terminal plus reentrant finalizer:** Return/Raise is committed before reference
   drop callback; callback reentry sees CLOSED; negative: callback can cause a second body
   drive through the terminal owner.
5. **Delegate-only result versus parent resume:** delegate `throw` returning a yield value
   completes the outer request without claiming a new parent body Return/Raise. If delegate
   throws back, the parent handler/cleanup path is a real body continuation with caller
   context restored. Negative: method name `throw` alone chooses one route.
6. **Multi-create/external/multiple runtime instances:** same body Region with two differing
   capture recipes and an external instance interface; each drive retains its actual
   instance Use; no unique Create assumption. Negative: same code means same captures.
7. **Extra state domain:** `D = {body_state, request_state, context_state}` and
   `L = {body_state, request_state}`; commit/release updates only explicitly modeled
   domains and transfers context_state. Negative: omit the extra domain or infer it by list
   position.
8. **Caught cancellation/throw and callback failure:** request failure/cancellation can be
   suppressed by body code; terminality follows the body source, not the request label.
   Keep delegate callback exception context and return shape separate from parent body
   outcome.

## Open points that should remain explicit

- The probe checks CPython 3.14.7 only. Runtime/source pairing, other CPython versions,
  alternate implementations, C-level delegates, GC cycles, and deferred finalization are
  untested here.
- The exact finite `NoBodyFinishRule` set and how state proves CREATED/CLOSED must be
  supplied by a versioned rule/provider contract. Do not recognize `close`, `send`, or
  `throw` from labels or names.
- Exact ordering between async request completion and terminal frame release is not fully
  measured by this probe. Preserve both transitions explicitly and require source/provider
  evidence before asserting their relative order for each family.
- The second async `aclose()` result here is specifically `StopAsyncIteration` with body
  state still `AGEN_SUSPENDED`; its API-level request category needs a family-specific
  rule. Do not recast it as a successful terminal commit without further evidence.
- No actual D2 lifecycle records, adapters, runtime occurrence trace, source mapper, or
  LeWM behavior were exercised. This is a design review and bounded stdlib evidence only.

## Review correction record

The first report draft, preserved without edits as `adversarial.initial.md` (SHA256
`729319f0f3b4d24ccb1a1d6f6f8198929771ad51b586e7f8fc7884e685cc8e1c`), incorrectly
described the second async `aclose()` as leaving `AGEN_CLOSED`. Root identified that this
contradicted the raw JSON. Both `lifecycle_probe.json` and the preserved attempt-1
`lifecycle_probe.attempt1.json` say `retry_error="StopAsyncIteration"` and
`final_state="AGEN_SUSPENDED"`. The final report now follows those records. The probe,
JSON, logs, and attempt-1 files were not rerun, edited, or overwritten during this
correction.
