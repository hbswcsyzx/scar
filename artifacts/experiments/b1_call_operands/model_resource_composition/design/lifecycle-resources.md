# R3 resource/lifecycle composition: independent design review

## Receipt and decision

2026-10-18; parent-provided clean/pushed baseline `348d18277b963bc183fb420bf173f05594d667d8`.
This is source review and proposed acceptance, **not a test or runtime result**. No Python,
pytest, GPU, LeWM workload, capture, installation, git operation, or tracked edit was run
for this review. Reads used `rg`, `sed`, `nl`, `sha256sum`; official API references below
were consulted. Source hashes are recorded in §8; files were read selectively, not audited
in full. The subsequent R3.1 implementation is a separate task and receipt.

**Decision:** preserve the original R3 denominator: read file → materialize → submit →
wait/consume → write file → flush/close, including error and cleanup paths. Most work is
composition, reconciliation and public inspection of existing records. One concrete missing
relationship is a synchronous caller occurrence ↔ exact child activation/entry/completion.
Add that narrow association; do not add another producer/state/lifecycle graph. Endpoint
read/flush/persistence interpretation remains an explicit unsupported protocol, rather than
a requirement to implement a general Python/native compiler before exercising R3.

This agrees with `M1_RESOURCE_COMPOSITION_PLAN.md`: R3.1 closes dynamic calls and declared
materialization-set consistency; it does **not** itself close R3.2/R3.3 or all M0–M2.

## 1. Existing facts that can actually be connected

| Stage | Existing canonical relation | Required check / remaining evidence |
| --- | --- | --- |
| open/acquire/dup | `ResourceDefinition`, `ResourceUse`, `ResourceLocation` → `ResourceRealization`, `RequirementBinding`, `HandleBinding` | Exact occurrence/activation, current support, target and namespace; Python object/fd value is not resource identity. |
| file read / host initialization | Original result or `StateAccess`; INVOKE uses `InvokeBoundaryStateEffect` with actual successor/result/formal | No ordinary INVOKE AFTER. Host/external initialization uses `HostWrite`/`ExternalEstablishment` + `EstablishedProduction`, no fake work. |
| content/materialization | Original scoped VG version/Mat/Region/Allocation + `ValueDenotation`, `ContentRead`, `StorageContent`/`EndpointContent` | Mutable reference identity is not permanent content. Endpoint/OFD/file-entity selector mapping needs its own conditional correspondence. |
| submit/partial output | `WorkSubmission.origin/effects/materializations/retention`; exact `ResourceOutcome` and `OutcomeProduction` | Host completion and work outcome independent. BytePrefix interprets a closed raw byte-count schema, not arbitrary footprint units or physical truth. |
| queue wait/consume | `QueuePrefix`, FIFO profile, exact `EventRecord.generation`, `QueueWait.selection`, actual `ResourceConsumer` | Exact queue incarnation and original input/effect; End(producer)→Start(consumer), not End(consumer). No Outcome is required for conditional future queue ordering. |
| host consume | `HostConsumer` + accurate protocol interval and current state | No fake consumer ticket. Native work conservatively retains its full WorkStart..WorkEnd read interval. |
| save/flush/observe | Actual file helper Uses/state/completion; explicit Q `ObservationRequirement`/`ObservationRoot` and `ObservationConsumer` | Output slot must belong to original required outputs; endpoint facet must be explicitly required. No root inferred from EXTERNAL, filename, close or an arbitrary FactRef. |
| cleanup | C1 pending/context and actual CFG state forwarding; real close/helper may NORMAL or RAISE | Preserve original pending only on valid Resume; new escaping exception uses fresh pack + Replace. Private tokens are CFG operands, never opaque helper arguments. |

Evidence: execution `effects.py:50–190`, `query.py:99–161,164–261`; program
`resources.py:20–35,124–179`; resource validator `:470–477,580–657`; work validator
`:200–250,355–472`; order validator `:330–394`; C1 contract §§3–5.

The original R3 requirement is explicit at `M1_RESOURCE_EXECUTION_PLAN.md:25` and READY
contract `:165`. Tables existing separately do not establish the above joins.

## 2. Eight events must remain separate

| Event | Exact existing anchor | Does not establish |
| --- | --- | --- |
| host NORMAL / RAISE | Actual invocation `ControlTransfer` and original completion signature | Work terminal, no submission, no partial writes, quiescence. |
| native work terminal | `ResourceOutcome(ticket, kind, actual frontier/result)` | Whole requested output; FAILED/CANCELLED can retain partial output; no universal quiet. |
| no further access by work | `WorkQuiescence(ticket, observed_at, source)` | Every borrower released, content unchanged, ownership exclusive. |
| end one borrow | `WorkRetention.release = BorrowRelease(point, same-ticket quiescence, source)` | Handle closed, target retired, all borrowers ended, or allocation free. |
| end handle binding | `HandleBinding.end = EndedAt(actual point, source)` | OFD/file/allocation retired; another dup may still refer to it. |
| end actual target incarnation | `TargetLifetimeEvent(RETIRED, exact ResourceTarget, point, stage/effect)` | A replacement at the same fd/address/path is that old target; physical semantics still conditional. |
| buffer flush | Actual helper operation/state/real completion and endpoint protocol requirement | Durable persistence, directory-entry durability, global device completion. |
| persistence observation | Explicit scoped Q endpoint requirement/root + interpreted platform protocol if available | Guaranteed by close, queue wait, successful write count, or matching facet/FactRef alone. |

`WorkRetention` is a holder relation, not content stability. Scan all writers/opaque effects
through the whole read interval even if the allocation remains retained. A write followed
by restore can leave identical endpoint bytes and still invalidate an intervening read.
LIVE at an anchor is not whole-interval life; state at host enqueue is not native last-read.

`TerminalFrameRelease` is a **narrow frame-reference relinquishment attempt**. Its fixed
FrameRules are MAY_NOT_COMPLETE, effects UNKNOWN, release NOT_GUARANTEED. It cannot stand
for a source file `.close()` wrapper that propagates exceptions, a buffer free, or a native
borrow release (`frames.py:47–77`; lifecycle contract `:115–120`). Historical finished F
survives unknown callbacks under its profile; current session P does not. Neither F nor
SessionPost.COMPLETE/ABANDON proves an external ticket quiet or a file persistent.

## 3. Concrete type gap: synchronous call occurrence

Observed: `RegionActivation` has region/process/entry evidence but no parent call
(`coordinates.py:114–124`); actual `ControlTransfer` stays in one activation (`flow.py:30–40`).
`formal_route` only follows a local predecessor (`query.py:172–186`). Core `callee` already
checks static argument/result interfaces (`program/validation.py:541–557,576–622`), but cannot
choose which of two executions of that callee supplied this result.

Proposed narrow `CallActivation(caller, activation, entry, completion, source)` is sufficient:

1. Caller must be a real ordinary call or INVOKE with that exact static callee. Do not use
   same EEG parent/span, a name or an opaque callback to infer the child. A native wrapper
   invoking several Python callbacks is not one direct callee activation.
2. Same run/process; known host threads must match. Unknown thread evidence stays a gap.
   Caller↔child pairing unique and dynamic association tree acyclic. Static recursion is
   legal through distinct activations. Cross-thread work remains WorkSubmission.
3. Entry is the child's real InitialEntry entry visit, not a loop/resume/capture visit.
   Inputs derive in original `call_arguments`/`invoke_arguments` order. Keep child formal
   ValueOccurrence and caller UseOccurrence distinct; do not bypass cross-activation checks.
4. Completion is this child's actual RETURN/RAISE and original exit Uses. Ordinary call
   supports only its canonical NORMAL interface; INVOKE matches its actual taken kind and
   exact CompletionResult→landing formal. No new result producer or result-value copying.
5. Missing entry/completion/actual transfer stays Unresolved/gap. Child unobserved does not
   mean no effect; child returned does not mean all submitted work is terminal/quiet.
   BodyDrive/Suspend is not a synchronous function return and needs no invented call row.
6. Query may derive caller-BEFORE→child-entry and child-return→caller actual post under this
   declared synchronous protocol. It must not promote a source span or internal native
   stage into WorkEnd/WorkStart. Existing work-boundary mapping remains conditional.

Other gaps require **relationship checks**, not more producer types: COMPLETE work Mat set
versus all declared exact read/write placements; incomplete sets gap; explicit Q requirements
with missing roots/reads/support stay obligations. OFD→file entity, path namespace update,
native flush/persist meaning, unknown alias closure remain explicit protocol gaps. Current
CHILD_RESOURCE has no containment interpreter (`resource_validation.py:722–724`); do not
pretend the tag proves the relation or require a general filesystem semantics engine.

## 4. Minimal complete composition fixtures

Use two small source shapes, then mutate exact relations. They are **proposed**, not run here.

**A, ordinary file pipeline:** open source/destination → read into bytes/bytearray → explicit
Mat/content version → submit a CPU worker → await/result or queue dependency → exact consume
→ write/returned count → buffered flush / optional fsync → finally close both handles. Put
raising operations on real INVOKE NORMAL/RAISE CFG. A worker's actual writes and wrapper
RAISE are separate observations. Direct host stages have no invented work. Model only work
that actually exists; ThreadPoolExecutor is not implicitly a FIFO queue protocol.

**B, active cleanup plus outstanding work:** body submit or yield → body terminal publication
→ owner phi → driver C1 Enter → real helper/close → normal Resume or fresh Raise Replace →
dispatch. Maintain current states after every stage. An independent pending ticket retains
the relevant allocation/handle past body Return, session COMPLETE and TerminalFrameRelease.
Add quiet/borrow release later as separate facts, then precise target retirement; no order
or completion fabricated merely because finally ran.

Reusing fixture *builders* is safe; counting old independent tests as this combination is not.
Exact available factories:

- `execution_paths.declared_path(program, path)` captures original visits/Uses/actual
  transfers; its current helper is rooted at `program.root`, so do not silently use it to
  label another callee Region as the root. Extend a new owned fixture with explicit genuine
  child entries when the call API freezes; no fake half-CFG.
- `execution_work_graphs.invoke_work_execution(raised=False, queued=False, quiescent=True)`
  provides differently ordered actual NORMAL/RAISE state formals (`:194–215`). Its raised
  variant currently chooses FAILED too; R3 must also explicitly construct host RAISE with
  work **still pending**, since those facts are independent.
- `execution_order_graphs.event_order_execution(same_queue=False, with_wait=True)`;
  `execution_visibility_graphs.visibility_execution(...)`: actual p1/r1/w/c/p2/r2 six-work
  path, exact event generation, mixed actual/guarded pending contribution, no CPU sync.
- `execution_lifetime_graphs.host_lifetime_execution()` returns program/model/VG/EEG/
  payloads/details; `queue_lifetime_execution(terminal=False)` preserves real consumer work.
- `execution_resource_graphs.resource_execution_program(...native_handles=True,close=True)`
  has distinct descriptor lifetimes for dup/shared OFD versus separate open/other OFD.
- `program_lifecycle_cleanup_graphs.driver_cleanup_release_program(helper=False|True)`
  preserves actual body Return/Raise commits, owner phi, private pending/context and real
  helper NORMAL/RAISE. `helper=True` forwards tokens only on edge operands and fresh-packs
  the actual failure packet before Replace (`test_lifecycle_cleanup_composition.py:75–143`).

## 5. R3 acceptance matrix

Legend: **I** structural contradiction → issue; **C** legal declaration with conditional
support; **G** precise missing/unsupported evidence; **X** legal unsafe program → conflict.
No row expects source/runtime/transform authority to become true.

| # | Genuine positive path / negative variation | Required result and original anchor |
| --- | --- | --- |
| 1 | Full A NORMAL, exact load/save source and Q output/endpoint requirements | Every stage query reaches original Uses/results/state; Host consume C where interpreted, Endpoint flush/persist G. |
| 2 | Two calls same callee; recursive call with new child activation | Exact input/output routes; swapped child, wrong entry/process/thread/completion I; missing pair G, no child guessed. |
| 3 | submit then wrapper RAISE while worker pending | Actual RAISE post-state, ticket/effects/retention retained; no inferred Outcome or cancellation. |
| 4 | COMPLETED short write, FAILED partial, CANCELLED partial | Only exact actual selector counts; whole demand missing, no successful order fills absent bytes. |
| 5 | cancellation requested or Future.cancel returns false / timeout | Pending stays pending; later real terminal/quiet separate; cancel request/result not synthetic work outcome. |
| 6 | terminal but no quiet; quiet but borrow not released | Valid G lifetime/free obligations; no free assertion. Wrong-ticket or release before cited quiet I. |
| 7 | same queue / accurate cross-queue r1 wait with no host sync | End→consumer Start C. Wrong queue incarnation/generation/selection I; no FIFO/wait G; ConsumerEnd is insufficient. |
| 8 | rerecord same event r2 after wait captured r1 | r1 remains original wait basis; p2 not covered. No Outcome invented by record/wait. |
| 9 | same ready contribution consumed twice | Each exact consumer/domain/interval checked, no consumed-permit bit. Queue support does not satisfy Host read. |
| 10 | read whole interval with overwrite→restore between endpoints | Exact actual overlapping post-establish write X; uncertain phase/alias G. Retention/current endpoint equality does not remove threat. |
| 11 | same address allocation reused, or same path/fd number rebound | New target/allocation/handle lifetime, old support not reused. Same NativeHandleLifetime with changed target/namespace I. |
| 12 | dup handle, close one, use other; separate open same file | Separate handle lifetimes; close-one is not target RETIRED. Exact ended handle use I; unresolved OFD/entity/offset relation G. |
| 13 | rename/replace pathname while original descriptor held | Namespace state changes; old open target not chosen by path equality. New open result must bind accurate target; unresolved file-entity correspondence G. |
| 14 | B owner phi then narrow frame release | F copied on each real edge; unfinished/wrong owner I. Pending resource work still retained after F/release; no automatic target retirement. |
| 15 | B real close/helper NORMAL and RAISE, including partial close/flush effects | Current actual completion states; private tokens only CFG-forwarded; failure packet fresh Replace; stale state/token escape I. F may persist while session P is invalidated. |
| 16 | cleanup callback writes/launches work or does not finish | Unknown effect remains threat/G and no downstream actual occurrence fabricated. Do not apply unraisable narrow frame semantics to a raising user helper. |
| 17 | Host initialized and externally established content | EstablishedProduction, exact point/result/selector; no fake ticket. Wrong actual Mat/allocation/result port I; unsupported byte/layout/protocol G. |
| 18 | buffered write→flush→fsync→close; fail flush or fsync | Distinct actual operations/endpoints/requirements. Count/close/queue order never proves durability. Known close-on-RAISE only with its actual protocol/effect, otherwise G. |
| 19 | required output/endpoint Q root vs missing/foreign roots | Exact semantic contract/required slot/facet/target/run; known mismatch I; missing root/read/support G, no empty successful conjunction. |
| 20 | remove support/Outcome/Produced/write/work join but retain original source | Independent candidate universe persists; known native short result blocks requested-whole fallback. Missing associations G, never smaller demand. |
| 21 | two work stages share ticket / multiple tickets share host op | Exact stage/effect/selector/consumer input retained; no same-ticket dedup or same-host native slot match. Wrong exact port I. |
| 22 | small shared query budget / changed or missing supplied snapshots | TRUNCATED never success; wrong supplied digest/schema/FK I; missing artifact G. Old wires and original canonical IDs unchanged. |

This covers NORMAL, real RAISE, pending cancellation, handles, rename/reuse, C1/D2 release,
public traces, scope, source deletion, Q denominator and bounded computation. It is a proposed
matrix to freeze; no count is claimed as modeling coverage or as already executed tests.

## 6. Public surface, denominator and costs

Start from the **complete supplied semantic Contract.required_outputs/required facets plus
explicit ObservationRequirement rows**, not from already joined successful ContentReads.
R3 must report a required slot with no requirement association, an explicit requirement with
no root, a root with no read, and a read with missing source/support separately. Legacy facets
with no typed endpoint requirement remain unresolved interpretation, not a guessed endpoint.
Deleting the supplied contract itself leaves missing observation scope; it does not prove
there was no obligation. Supplied inventory capture/window/alias completeness stays unproved.

Public composition is a derived receipt of existing references: required observation →
root/read → exact consumer Use/effect/work → version/Mat/selector → independent source
universe → writes/actual production → alternatives/order/interval invalidators/lifetime;
also exact call routes and program cleanup/lifecycle points. Do not accept a caller-selected
contribution/work list as the complete denominator, or return ready/free/persist booleans.
Use `ExecutionIndex` existing methods `definition_for_use`, `formal_route`, `state_at`,
`canonical_effect`, `resource_access`, `work`, `production`, `content_read`, `observation_root`,
`work_order`, `validity`; ProgramIndex `body_publication`, `lifecycle_before/edge`,
`terminal_release_publication`. Raw handle/retention/retirement records can remain exact input
references; additive read-only getters need no new canonical table if public ergonomics demand.

Within one validity demand, source/joins/formula/geometry/order/threat scans share one budget;
no per-alternative reset. Multiple public validity calls currently have **separate** budgets:
an R3 receipt must report those per-demand costs and aggregate them honestly, or explicitly
thread one shared budget through a new coordinator. It cannot claim a global 4096 bound by
calling each child with 4096. FK/declaration validation, raw normalizer replay, snapshot
hash/schema/byte checks and detached copying are separate costs (`query.py:50–79`,
`validity_query.py:290–294`, `snapshot.py:51–58`). Recheck caller mutable catalogs per query;
no stale trusted cache, URI fetch or arbitrary decoder. Keep all historical wire bytes and
goldens; version new call capability only when used, without upgrading old empty-table meaning.

## 7. Reuse real tools without adding a compiler

- Stdlib `tempfile`, binary file IO, `os.pread/pwrite`, `dup`, `replace`, `fsync`, `close`,
  `ThreadPoolExecutor`, `threading.Event`/barriers suffice for bounded CPU/OS witnesses.
  Deterministic worker-start/release handshakes avoid sleeps masquerading as order. Record
  actual syscall request/result separately from a wrapper's larger intended output and
  later RAISE; requesting four bytes and writing four is **not** a syscall short-write8→4.
- Future.cancel cannot stop a running Future, result can propagate worker exceptions or
  timeout, and done includes cancelled; these are useful adversarial interfaces, not
  universal device-work semantics. See installed `_base.py:359–398,424–459,653–676` and
  [official Future API](https://docs.python.org/3.14/library/concurrent.futures.html#future-objects).
- Buffered flush and `os.fsync` are different calls; Python documents flushing the Python
  buffer first. `pwrite` reports actual bytes. Preserve platform applicability and no crash-
  durability claim from a read-back witness. [Official OS API](https://docs.python.org/3.14/library/os.html#os.fsync),
  [pwrite](https://docs.python.org/3.14/library/os.html#os.pwrite); fetched docs identify 3.14.8,
  not a version measurement of the installed interpreter. Local `_pyio.py:1277–1322` also
  shows real partial buffered writes and finally-close after flush errors.
- Installed PyTorch source is `2.13.0+cu132`, CUDA build `13.2` (`torch/version.py`, read only).
  Existing Stream/Event wait/record/query/synchronize APIs map to existing queue/event records;
  `wait_event` returns without CPU waiting (`streams.py:48–77,199–254`). `record_stream`
  concerns allocator lifetime/reuse, not content visibility (`_tensor_docs.py:3976–4037`).
  Reuse their versioned source as protocol conditions; no torch import, GPU run, new capture
  backend or LeWM-specific detector is needed for this review/R3 combination.

No native endpoint parser is implemented by this report. A future narrow interpreter should
read exact original result/selector/endpoints with closed protocol guards, as BytePrefix does,
not recognize success from an enum or unparsed FactRef. Until then the complete path and Q
obligation are still representable and inspectable with an explicit unsupported endpoint.

## 8. Actual source receipt

All paths below are worktree-relative except the installed-source suffixes. SHA256 was read
with `sha256sum`; hash equality is source identity, not independent behavioral verification.

| Read file / scope | SHA256 |
| --- | --- |
| docs/M1_RESOURCE_EXECUTION_PLAN.md, full | 5708b647e226335f02a6ac53b236063ae4b1dd9769e0d285a6e6730da40576a7 |
| docs/M1_RESOURCE_COMPOSITION_PLAN.md, full, after parent proposal | 1d115816998115cd3a3f8893ea7b01d0d9ab0c260b4f4e11416a8128d2ebd3de |
| docs/M1_RESOURCE_EXECUTION_CONTRACT.md, §§4–6 and resource validity clauses | 74a606fca89ecb94ad9a04f77d8ad41706bcdacb10210352ccad185272993729 |
| docs/M1_RESOURCE_READY_CONTRACT.md, §§2–9 | b222e95fc46773f2b681fc2f44f8f9461fdaa094b567b1401635c79046a6866f |
| docs/M1_VALIDITY_API.md, full | 26e6812924b8ef2628a0a0642d8af1d01ccf264aeaf5b03b866d813db909e445 |
| docs/M1_DRIVER_LIFECYCLE_CONTRACT.md, §§5–7 and declarations | 94e0e84e918129875ae0f913095015ecef42ee9c25bb8305d96135ce9b8ef699 |
| docs/M1_CLEANUP_INTERFACES.md, §§2–5 | c31e9e3b453c286ed5388399e2317e2bf08f470a8ef85663b03fc6143f2a0dde |
| docs/M1_RESUMPTION_BODY_COMPONENT.md, §§2–3 | e775feb2ef44e5f73fcdf94a963974a377e984b9c99a12e0231507bf4cb30c25 |
| scar/ir/program/resources.py, types/owner constraints | 167f0b2e1267278362341e6622e5cb164292e93484da94c8403b382e1e6e434f |
| scar/ir/program/model.py, Operation/Region | 3a72c7692afdb19f74f19df5990527140e360748954c64dde3e335551580b2b1 |
| scar/ir/program/validation.py, call/INVOKE interfaces | 04ed471b6164b14e738ed0c22aee16f256f2a925038321a478834ef68aff7264 |
| scar/ir/program/frames.py, fixed FrameRules | 4c24a8719043778fdfaec6285c5b579a8855b6b0c8b31bde6c9ec2e81613cba2 |
| scar/ir/program/lifecycle.py, full records | 326422e0b5c0a89fef3abda0f27037928d6c20bfc5adbd9afc875236678d17d7 |
| scar/ir/program/session_release_validation.py, full | b96e989a611a518630e2c33bbf61b5f69d4cc015b54166d27f78a6486482e0fc |
| scar/ir/program/lifecycle_analysis.py, full | 153c309f0cd32a6b6b719f0266dbc68209a107c9746bb88c2463194d7d650dd7 |
| scar/ir/program/queries.py, publication/lifecycle getters | 584fc4b40c83d3618b42f84c71c06d750e264465195f62676bc542e29f0d3ad1 |
| scar/ir/execution/model.py, tables | 5b7bcefb18bfaaf4b8548f2ebdd4c8346046913dcb5adac528929f85306d5a6d |
| scar/ir/execution/coordinates.py, activation/segments/occurrences | b19e45c8af710b93d7197ca91e7cbcdfa7a9ee239a7faf73903d2ff85003ce09 |
| scar/ir/execution/flow.py, actual transfers/incarnations/current states | 2b6189a1ad658072176a00bc4c72a4c5af4c66e96edc844bad904471c8eb0501 |
| scar/ir/execution/validation.py, occurrence/scope validation | 41baacad27c685901fd0aa2d2607b95d2211d76a3af1da66af6aa32b4231a1fc |
| scar/ir/execution/resources.py, lifetimes/handles/targets | 657fca489d07fd3e32e5552782e02c6b6b58c8ed061c3c0040313d442a2e3000 |
| scar/ir/execution/resource_validation.py, handles/access/constraints | 3a8bcd72fc07231360b9c9bdc4b35adc9dbc21b569026bba25712d84639b1c08 |
| scar/ir/execution/work.py, work/retention records | c092b7b39691fce22d8cc00d8922cce5df4800c6ece615d28492edbd3fc6bd70 |
| scar/ir/execution/work_validation.py, scope/outcome/retention | 290d8fe51c9cc091bddae107b7428bce4ef181949954c3a8751a5fd6d3adb765 |
| scar/ir/execution/effects.py, full resolver | fd3d756ea382af33916ae6076b17e71a7bc3bc59a45db30c2b7974b573534e6d |
| scar/ir/execution/content.py, consumer/work/placement records | 1eee1822056e59a0be9f4f3a1524f97948df91497ad57072c7c0ca53c670cf9e |
| scar/ir/execution/order_validation.py, event wait and joint order | cbea6d0b1072c0cf7a3579e07a13a3a9bad808b807c779e66ac76acf43f6ea09 |
| scar/ir/execution/observations.py, records | 8c8237c855680e78f6e1c256a30086105636c2af5ad6fb59958385840ed7d882 |
| scar/ir/execution/validity.py, records | 55df8f7cc20c06b246e92822ea51ea4fcf9a64647ede17613e4325b8b8d0f120 |
| scar/ir/execution/validity_validation.py, support/domain rules | b347ece5df59c8a6aeeb0e7421a533f1decb1c21eacd6cbaf755c3254c6a161e |
| scar/ir/execution/validity_stability.py, intervals/threats/lifetime | c394f306fe4ff318ee80badf112881f5c2b8c310b881b74253eeca66afe9aadd |
| scar/ir/execution/validity_query.py, formulas/receipt | de6313dc979859a7c92d79a67e36b49c6f29d6bb0ce4bc34a1bbfef52d6113b9 |
| scar/ir/execution/query.py, public methods/content replay | b2bb3bfd92f2dd1ee6d71cc9a8b0bdebad519cfa43065244b1d2e1621739deec |
| scar/ir/execution/production_query.py, source universe/joins/groups | 3d3d2ab7798edbf9b284552587dc7b154fd676e8df39645a913d1c6864256eab |
| scar/ir/execution/validity_budget.py, full | e1b297345fc1a63716da5d8d7f2434b4999e3200ad3b6ee4f3823c5d99244b10 |
| scar/ir/execution/snapshot.py, external snapshot resolver | 7757c299a965e37f5e73eeaa1f4ed304da6b7bfb970cded5d274fdc4e8483107 |
| tests/fixtures/execution_paths.py, full builder | f9f0023e212adfb251b5f8e33fc79c868f3aac45d076df79b58eb5d51f3f832b |
| tests/fixtures/execution_resource_graphs.py, resource/dup/end builders | e72ea43784824f7c8f1d72eecd1672f69b99ace49ff5f74eb26d7cea370a05ce |
| tests/fixtures/execution_work_graphs.py, factories/actual invoke ports | 7428d0bd7a1597232d49587d5378cce3b4fae077a306d51d474e8d46e6aec60f |
| tests/fixtures/execution_order_graphs.py, factory/API | d4e21e8c63ebdb279bafae66ce14b5f78b917f05d3d1e37e3c56b94a2a203e2a |
| tests/fixtures/execution_visibility_graphs.py, mixed contribution builder | 478eb976dc8aef267bce1d5fbd50beacb6cdeef6797d7c6c417c0cc21895a5fe |
| tests/fixtures/execution_lifetime_graphs.py, host/queue factories | 1d0323fb080758156ee10f4f675bdab5acb990fe60bcd6963498b7577c9d7c3e |
| tests/fixtures/execution_observation_graphs.py, requirement/root factory | fef4e061a5af321f1173b34366df908495ed2505345994f19169e9baeaa419d9 |
| tests/fixtures/execution_produced_graphs.py, original-effect builder | 751b40a5c3e5190c5bf08341dc7c68c4fafe76aed3cdae7fb50fba9546c79aa6 |
| tests/fixtures/program_lifecycle_cleanup_graphs.py, B builder | 2c50833ec7571796d9c500e7a43a8daf46ada860676f4bf6203e3662cc841238 |
| tests/unit/test_lifecycle_cleanup_composition.py, source assertions only | aae51c755e934eeaa43c88a57d4f6af16ab2c5ff779c0b37ca67dd58c7bbf5c5 |
| installed lib/python3.14/concurrent/futures/_base.py, Future/Executor methods | 0932abfae68a9bc4807a367ab60bd2ef31d98ae305ee8b70f9e595a747c3b2a1 |
| installed lib/python3.14/_pyio.py, flush/close bodies | e07d55084185e40255084d409a126ab9889c76ff1d9cc67fc9157450e78770f1 |
| installed torch/cuda/streams.py, event/stream methods | 28d90fd68be59e8dd9a30d230e7df6f61a4b020e6e2da9fa89839691a1cfced5 |
| installed torch/_tensor_docs.py, record_stream doc | b1a46e328a74e39383dbecf04fb48620af70c7780467cf923864d1b5cf992e99 |
| installed torch/version.py, version constants | aef3753721b655fb4e1369862a57652bde68009ba2cad63668b98288482542bf |

Installed-source root: `/home/zyf/miniconda3/envs/lewm/lib/python3.14/` (torch suffixes under
`site-packages/`). No loaded runtime/native status was inferred from these source files.

**Bounded conclusion:** accept R3 as actual composition and precise missing-relation reporting,
with the narrow call association and declared-set/Q-denominator guards above. Full arbitrary
endpoint protocols, full writer/alias capture, runtime correspondence, transformation authority,
automatic source recovery, remaining M0–M2 obligations and LeWM speedup remain unproved.
