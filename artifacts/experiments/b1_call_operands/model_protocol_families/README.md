# C2/D3 protocol-family audit and plan evidence

Baseline: `08c4cbfc6b675919ab15e8654567889727f3c466`.
Status: **AUDITED_FIELDS_OPEN**. P0 audit is complete; exact P1 fields, F/O
implementation, D3 and complete M0–M2 remain open. This is not a product or
native-protocol PASS and grants no transformation authority.

The current documents are `docs/M1_PROTOCOL_FAMILY_AUDIT.md` and
`docs/M1_PROTOCOL_FAMILY_PLAN.md`. They retain F01–F24/X25–X28 and distinguish:

- F: protocol obligations joined to original CFG/Uses/results/current state.
- O: actual BodyDrive occurrence joined to a persistent body activation and its
  current ingress/first outcome. No-body/delegate-only paths have no parent
  BodyDrive; they use the original host/helper/adapter relations in F.

`design/` contains the language, core-connection and independent scope audits.
Initial source assumptions, later counterexamples and withdrawn candidate
shapes remain visible. Their row counts overlap and are not test coverage.
One staged whitespace notice is a blank final line in the frozen language
review report; its original reviewed bytes/hash are retained. The maintained
source/docs/tests/gates whitespace check passes separately.

`current_core_probe.py/.json` records five old-IR observations: four generic D1
structures validate, including an unvalidated body-Return→host-Return adapter;
the existing wrong-family/flavor guard rejects COROUTINE+YIELD. It executes no
Python resumable workload or pytest and does not call these native equivalents.

`created_throw_witness.py/.json` is one new bounded stdlib CPython3.14.7 execution
recording six startup-throw observations. The data was saved before a wrong
expected CREATED assertion failed with exit1. The original script is unchanged,
and the traceback returned by the tool is transcribed in `.first_failure.txt`.
The later StopIteration→RuntimeError assertion was not reached; the saved data
also contradicts it. Constructor failure actually closed the generator while
invalid raw42 preserved Created; startup StopIteration propagated unchanged.
These observations changed the next modeling action. They are not six passing
SCAR/native-protocol tests, and empty user-body logs do not prove no VM work.

`check_created_throw_observation.py` reads saved data only. It does not rerun or
repair the failed original witness. `check_archive.py` likewise starts zero
tests, witnesses, compilers, profilers or workloads. It binds current source,
fixtures, documents, original observations, protected checkouts and baseline
regression evidence to the manifest. With conda lewm active, use:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python artifacts/experiments/b1_call_operands/model_protocol_families/check_archive.py
```

All603 registered source hashes and78 fixtures remain those of the prior L
implementation. The prior clean frozen5,294-case full run remains attributed
to `4bc55eb`; no new pytest/component/full run was performed for this audit.
No LeWM checkout, environment, shared cache or driver change, new backend,
detector, lowerer, heavy profiling or speedup is claimed. Next is P1 joint field
review, then the connected implementation gates in the plan. The user-requested
explanation boundary remains after complete M0–M2, not after this audit.
