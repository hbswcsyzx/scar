# P4-2 owned continuation implementation receipt

## Result and scope

**Owned focused result: 52 PASS / 2.26 s, exit 0. Parent P4: OPEN.**

Final attempt: `continuations/attempt009/`. Its full registered-source fingerprint was
`3af821cb7b9486a8f7b0befc89ed56747b3ef7dcb54abf91e79a7f9be5982459`
before and after, with no changed paths. This is a necessary owned focused file,
not a component gate or full regression, and not acceptance of all sixteen groups.
`P4-2-coverage.json` and `P4-2-coverage.md` retain F12–F24 and X25–X27 individually
as OPEN, including the other owners' groups without claiming uninspected tests.

The command and Python receipt are preserved in `attempt009/command.json`:

```sh
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python artifacts/experiments/b1_call_operands/model_remaining_protocols/run_focus.py continuations/attempt009 tests/unit/test_program_continuation_connections.py
```

The runner used conda Python 3.14.7 and `python -m pytest -q` on only the owned
unit file. Raw stdout, stderr, exit, JUnit, before/after source hashes and timings
are all preserved. No xfail/skip masks a failing assertion.

## Exact frozen owned files

| File | SHA-256 |
| --- | --- |
| `scar/ir/program/protocol_continuations.py` | `97ec80c4a5aaf4615a4239d57dac0eb61ed1d95b1ae008e9f4695bc5f31eee40` |
| `tests/fixtures/program_continuation_graphs.py` | `0137c37ebc5d4c101c36f77a1bdd624ce88d987b3b258b25943541f356b43733` |
| `tests/fixtures/program_continuation_cleanup_graphs.py` | `71f27991640be83ddaebf6c2525b8b0964662cda7e2ec2e1c1822f45dfc778e7` |
| `tests/unit/test_program_continuation_connections.py` | `fc8730283979c569a5338d7dcb0c04ecf77a0a7e78757ab9e0fd6ae43032ad53` |

`source.final.json` also records the shared modules and three contract/plan
sources read for this receipt. Their hashes bind the scope of the source review;
they are not independent acceptance of the other authors' entire implementation.

## Implemented original-port connections

- `continuation_connections(ctx)` uses the caller's shared `ConnectionContext`,
  fresh-copy analysis, canonical source ports, branch guard/tuple correlation and
  budget. It does not construct another ProgramIndex or producer/state graph.
- Await call receivers require an independently selected own NORMAL await lookup
  result. Await-call iterator, yielded item, extracted expression value and own
  failure packet remain distinct original producers and uses.
- Delegation requests retain actual raw trigger and ordered raw ordinals. THROW
  has one to three original arguments; zero-argument NEXT still has a trigger or
  an iterator-specific `InitialAdvance`, not a free initial bit.
- Original selected N/R outputs and payload roles separate item from
  exhaustion/failure. Same-typed wrong lookup results, wrong branch tuple,
  reordered raw operands and STATE-as-output metadata are rejected on core-valid
  graphs.
- `InitialAdvance` scans a finite original-CFG operation-position/advanced-Boolean
  worklist between the exact iterator evaluation and its replacement. A genuine
  advance backedge is rejected. Unknown callbacks retain an unproved condition;
  they do not erase a separately reachable explicit repeated-advance violation.
- Every supplied `ResumeSourceBinding` row is checked, including rows outside the
  canonical inventory. BodyStart, nonDrive, missing operation, STATE/nonexistent
  slot and wrong source cannot disappear merely because no slot iteration sees
  them. Every actual nonSTATE BodyResume slot remains an obligation after a
  relation is deleted. Slot role is not inferred from AWAIT/DELEGATION flavor.
- Close NORMAL continues the case's independently selected current injected
  packet; the call's own None is not an item or replacement packet. Close RAISE
  supplies its exact own new packet. Independent selected N/R choices and input
  guard are checked together through real merges into a shared fresh
  PendingRaise/actual CleanupReplace. The private pending/context/frame/caller
  tokens remain original edge/saved resources and never opaque helper arguments.
- Delegate-only paths have no invented parent BodyDrive/Attach/F/publication or
  terminal frame release. Worklist visits, canonical edges, source candidates
  and packet/token matches consume the shared budget. Truncation preserves
  unchecked sites and a cursor; preparation/source/FK/record costs are not
  advertised as bounded by the derivation budget.

The active C1 fixture has one real cut. It saves original pending/context/frame
and delegate resources, resumes into the true Attached window, then routes close
N/R through fresh pending and current handled-context state. This is useful
composition evidence, but **not** X25's required two-cut/local-binding group.

## Failure history retained

Each directory below is separate. Earlier failures were not overwritten by a
green result or by altered assertions.

| Attempt | Actual result | Attribution / later change |
| --- | --- | --- |
| `fixture-smoke/attempt001` | exit 0; twelve old-core structural graphs had no issues | Constructor/old-core smoke only; generic close was later replaced by a real injected-packet close fixture. |
| `attempt001` | collection error, exit 2 | Owned test used pytest's reserved parameter name `request`; no product tests ran. |
| `attempt002` | 32P/1F | Owned expected diagnostic name differed from correct shared `protocol_input_source`; assertion aligned to the same wrong-source meaning. |
| `attempt003` | 32P/4F | Owned close fixture retained an unbound NORMAL region exit after changing its normal host path to RAISE; original core correctly rejected it. |
| `attempt004` | 39P | First corrected direct close/request sites. |
| `paired-attempt001` | 3P | Real upstream two-lookup merge tuple positive/crossed/missing. Shared conditional-consumer repair preceded this run; no old red is claimed. |
| `attempt005` | 49P | Only root's shared `protocol_connection_flow.py` changed during the run; the runner lists that path. This is not called a globally frozen result. |
| `attempt006` | 49P | Source before/after unchanged. |
| `cleanup-attempt001` | 3F | Owned fixture removed the original Return route but kept its pending dispatch case; core correctly rejected the inconsistency. |
| `cleanup-attempt002` | 3F | Owned new Attached block lacked the current caller formal; core correctly rejected resumption caller routing. |
| `cleanup-attempt003` | 3P | Real close N/R share fresh pending/current CleanupReplace with selected packet bindings true. |
| `attempt007` | 51P/1F | Owned loop graph had moved the old item host operation to a BRANCH but an old HostTerminal consumer still referred to it; `protocol_result_reference` was correct. |
| `attempt008` | 51P/1F | After fixing that consumer target, no issues were emitted for the genuine loop: `_first_advance` returned unknown on another extraction INVOKE path before inspecting the known backedge. |
| `attempt009` | 52P/0F, exit 0 | Own checker retains unknown and continues other paths, so known repeated advance is rejected. No fixture/expectation was weakened for this fix. |

Root's concurrent `ambiguity-green001` 119P/1F is a separate preserved aggregate,
not this agent's run. Its old loop failure must not be replaced with attempt009's
result or called green retroactively.

### Loop diagnostic receipt

`loop-diagnosis003/` ran the current supplied loop through full `validate(graph)`
and enumerated all six actual ResultConsumers sites. Before the checker repair:
`FULL_ISSUES []`, every site existed, and the continuation report retained unknown
source gaps. The six sites are lookup N/R, advance N/R and extraction N/R. There
is no separate item-adapter ResultConsumers attachment to rename. The old item
OutcomeAdapter itself already referenced the new actual terminal operation.
The validator issue was therefore no longer masked by a bad natural key.

Two diagnostic-script errors are also retained: `loop-diagnosis001/inspect.py`
shadowed stdlib `inspect` during `dataclasses` import (the enclosing shell's final
cat returned zero despite the Python traceback); `loop-diagnosis002/` then used a
private ProgramIndex constructor with missing required arguments (recorded Python
exit 1). `loop-diagnosis003/` used public ProgramIndex and completed with exit 0.
These were evidence-script errors, not product defects or test passes.

## Explicit remaining implementation work

1. **Independent delegation method lookup is a structural rule/interface gap.**
   The current DELEGATE_NEXT/SEND/THROW/CLOSE contracts can describe an atomic
   helper whose receiver is the iterator. A real separately represented
   `getattr(delegate, method)` produces a bound-method Reference which must be
   the actual call receiver. No closed delegation-method-lookup rule currently
   ties this independent expected stage to its result. DELEGATE_ITER means
   GetIterator and AWAIT_LOOKUP is not a substitute. Next work needs the minimal
   closed stage/rule and exact result/source relationship, followed by true N/R,
   raw ordinal and branch tuple fixtures. Atomic helper applicability remains
   conditional and does not establish those internals.
2. Complete missing-method paths and raw CLOSE/THROW(GE) through actual original
   normalization/PacketDefinition/category branch sources. The injected-packet
   fixtures do not fill those routes.
3. Complete F12–F15's coroutine eligibility/phases/reuse/throw/close and the same
   wrapper body used both directly and through await. Helper-site tags alone do
   not satisfy these groups.
4. Complete X25's at-least-two cuts/local binding/loop/merge and X26's actual
   publication/session kill/reseed/partial RAISE/narrow release compositions with
   the new protocol sites. Existing standalone C1/lifecycle regression passes
   are not credited as these new combinations.
5. Complete X27's P3 occurrence combinations with current saved/delivered inputs,
   persistent activation, first outcome, thread/run/identity and partial capture.
   These supplied static graphs do not assert runtime occurrence recovery.

All sixteen groups retain OPEN status in the ledger. Async/cancel owner evidence
is not inferred from file presence or uninspected totals. Runtime source
applicability, exception class matching, actual object identity and native
protocol interpretation remain explicit unproved conditions. Both public
authority flags stay false. No backend, detector, native capture, LeWM rule,
automatic program reconstruction, GPU proof, transformation or speedup is claimed.

## Freeze

The four owned source/test files are frozen at the hashes above. No optional
expansion or full/component test was started. This receipt and the OPEN ledger
are the final owned writes for this midpoint; root owns the next affected focus,
archive and remaining P4 plan.
