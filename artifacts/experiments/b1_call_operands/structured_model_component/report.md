# N2-STRUCTURED-BODY-COMPONENT independent criteria report

Status: **PASS**

Revision: `dcd498699e0cd1331cf496158b29575c3fc2c536`

Source digest: `bf7ccd18b51b843c53b6b49f290c5f7368c397f394209991eb1f13a1f313bf05`

| Criterion | Status |
| --- | --- |
| G1-binding-identities-state-and-strict-wire | PASS |
| G2-actual-python-differential-control-state-oracle | PASS |
| G2-complete-source-protocol-and-loop-interfaces | PASS |
| G3-public-source-construction-replay-and-nonexecution | PASS |
| legacy-source-frame-and-core-replay | PASS |

Scope: Automatically generated synchronous source CFGs preserve typed local bindings, loop-carried values, normal and exceptional world state, and ordered call inputs.

- This component is a dependency of whole-program modeling; generator, closure, try/with, full heap/library/resource and asynchronous completion interfaces are not closed.
- Unsupported control still reports a rejected core body; local body preservation and full source/inventory integration remain required later gates.
- Frame protocols remain conditional; exact RC/GC/finalizer/traceback timing is not established by the test oracle.
- No new detector/backend, LeWM-specific rule, approved transformation or acceleration result is provided.
