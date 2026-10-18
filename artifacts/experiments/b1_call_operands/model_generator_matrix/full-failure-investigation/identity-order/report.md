# Created-close full failure: identity versus hash-order budget

Status: **REPRODUCED_BUDGET_NONDETERMINISM**, not a PASS or a product fix.
No product/test/old evidence was edited. No pytest/component/full rerun occurred.

## Original failure retained

Read `../../full/stdout.log:81–94` and `../../full/report.json`. The once-run
full at revision `44d56af52d65cd3440f4600fa05ea34fd03ad7f1` has **5,672 passed,
1 failed, 0 errors, 0 skips**, five warnings, wall545.049493s. All646 source
files stayed at fingerprint `fc6ebabbd4fd670dbe497cfcb61c53e9db83fbf198b3081055134b9da93e0ef0`.
The only failure is `test_created_close_derived_obligation_keeps_exact_test_finish_and_none_host_consumer`:
the derived actual finish/host route exists, but `declared_none_result` is None
instead of True at the default4096 budget. The original failure did not print
the budget fields, so it alone does not identify which mechanism caused None.

## Old-test pollution source audit

Searched all tests for `reload`, `importlib.reload`, `sys.modules` mutations and
LiteralKind/PythonLiteral assignments/patches. No scar literal/model/enum reload
or persistent literal-class replacement was found. The scar `sys.modules`
substitutions in `test_program_records.py` and
`test_program_completion_records.py` are function-scoped pytest `monkeypatch`
fixtures for the **validation** module and are restored. User fixture module
eviction in `test_call_demand_schedule.py` names entry/m_caller/a_callee/etc.,
not scar. The literal `_has_surrogate` patch also is scoped monkeypatch.

This source search cannot prove absence of every possible pollution mechanism.
The fresh-process reproduction below establishes that pollution is **not needed**
to produce the observed None/default-budget failure.

## One bounded standalone experiment, eight seeds total

Exact command is preserved in `command.sh`: explicitly activate lewm, set
`PYTHONDONTWRITEBYTECODE=1`, `PYTHONPATH=.`, then run `python probe.py`.
The parent script launches exactly eight fresh children with PYTHONHASHSEED0–7.
Each builds the original canonical Created CLOSE fixture and ProgramIndex and
queries only its actual CreatedClose scope, at4096 then65536. It neither imports
nor executes the failing unit function, runs pytest, or modifies the graph.
Each child has a20s timeout. The command exited0, wall5.76s, stderr empty.

| Seed | Default4096 result | Default used/truncated | Sufficient-budget used |
| --- | --- | --- | --- |
| 0 | True | 3530 / False | 3530 |
| 1 | True | 1712 / False | 1712 |
| 2 | True | 2588 / False | 2588 |
| 3 | True | 2384 / False | 2384 |
| 4 | True | 2076 / False | 2076 |
| **5** | **None** | **4096 / True** | **4676** |
| 6 | True | 2178 / False | 2178 |
| 7 | True | 2380 / False | 2380 |

All eight children observed:

- `created_close.PythonLiteral is scar.ir.literals.PythonLiteral` true;
- same LiteralKind enum class, annotation exact PythonLiteral type true;
- annotation kind is the current `LiteralKind.NONE`, `to_python() is None` true;
- literal module path points to this worktree.

Seed5 default reports `created_close_none_result_unproved`, cursor and
`budget.truncated=True`; sufficient budget returns True without gaps. Every
other seed also returns True at sufficient budget. The initial worklist/meet
costs differ by seed; seed5 needs78 copy blocks,2020 edge units and2452 meet
units for the full answer, versus seed1's42/680/914. Raw child commands,
stdout/stderr, identity diagnostics, costs, gaps and source hashes are retained
in `result.json`. Seven watched source files remained unchanged.

## Bounded conclusion and minimum repair surface

`ProtocolFlow._fresh_copies` at `protocol_flow.py:230–233` initializes both edges
and `deque(reached)` from a frozenset. Equal logical models can therefore take
different numbers of worklist iterations under different hash seeds, consume
different public budgets, and return different resolved-versus-truncated views.
The returned None is conservatively unproved, not a false native/None proof;
the acceptance regression is real nondeterminism at the chosen finite budget.

A repair should make the initial worklist and derived traversal canonical,
preferably entry-before-successor order over the original CFG. Preserve the
must solution, fresh-evaluation reset, parallel rename, budget charging and
truncation ledger. Merely increasing this test's budget would hide the unstable
cost. A correct local same-block exact-value fast path could also avoid a whole
region solve, but is a separate implementation choice for root; this reviewer
has not implemented or verified a fix.

The original full failure remains authoritative. This bounded probe supports
the hash-order explanation without claiming it is the only possible cause in
the original process. No further seeds or scripts/tests will be run by this
reviewer; the eight-seed allowance is exhausted.
