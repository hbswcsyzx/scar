# StopIteration route composition

Status: **PASS_WITH_SCOPE**, supplied static connections only. The final owned
file has 20 cases, not 20 distinct native behaviors and not full P2 acceptance.
No product or old fixture/unit file was edited.

## Exact API and semantic boundary

`tests.fixtures.program_generator_stopiter_graphs.stopiter_program(*,
route='internal'|'escaping'|'caught'|'created', selected=NORMAL|RAISE,
wrong_source_kind=False) -> (ProgramGraph, details)`.

- **Internal:** a true SENT ingress invokes a body exception factory. Its
  NORMAL Reference is placed into a new original ExceptionPacketDefinition and
  then RAISEs at the body. Factory RAISE is a separate body outcome that directly
  propagates its own packet. The new internal packet is not the injected one.
- **External escaping:** caller raw THROW ordinal→normalizer actual→the exact
  THROWN_PACKET resume input→body RAISE. Both this route and internal escape
  use `GENERATOR_ESCAPE_STOPITER_TO_RUNTIME_ERROR` on the exact DriveResult
  payload, then a real constructor INVOKE. NORMAL Reference→exact exception
  packet→host RAISE; constructor RAISE→its own packet→host RAISE.
- **Caught:** the exact injected packet reaches a body that actually YIELDs;
  its exported Reference is the current host item and publication does not seed F.
- **Created:** original Create/caller raw THROW→NoEntry selected actual N/R
  completion→host RAISE. There is no BodyDrive or fabricated body entry.
  The selected original packet is forwarded without an escape adapter; only
  that edge publishes historical F.

Exception-class/source applicability is an explicit unproved condition. Operation
labels do not identify StopIteration, native constructor behavior, cause identity,
or actual object state. These are manually supplied protocol contracts over
original producers, Uses, completion results, world/context and frame operations.
No ExecutionModel or same-runtime-activation claim was added.

## Necessary counterexamples

All metadata-only source/rule mutations first validate the same core graph with
protocol tables removed. This prevents core-invalid fake IR from being counted
as protocol rejection. Cases include:

- an available same-typed **old packet** at either constructor host exit;
- a same-typed driver owner Reference replacing the constructor's own Reference
  in the resulting ExceptionPacketDefinition;
- old pre-driver state at the final host; the core rejects it as stale;
- YIELD relabeled as the RAISE-only escape rule; STATE as payload/result and
  Return-to-StopIteration used against the actual RAISE source;
- deleted optional adapter rows: the different current host packet cannot become
  a valid direct propagation merely by removing its relation;
- an initial no-entry packet relabeled through a real ContractResult as a body
  escape input: the profile requires the exact DriveResult and rejects it.

## Every actual focused attempt

Each preserved `attemptNNN-command.sh` explicitly sources
`/home/zyf/miniconda3/etc/profile.d/conda.sh`, activates lewm and sets
`PYTHONDONTWRITEBYTECODE=1`, `PYTHONPATH=.`. It invokes the existing bounded
runner with only `tests/unit/test_program_generator_stopiter.py`. Each directory
retains command/environment, stdout/stderr, JUnit, return code, duration, complete
registered-source manifests and an explicit 20-file before/after hash list.

| Attempt | Actual result | Cause and treatment |
| --- | --- | --- |
| 001 | 16 passed, 2 failed / 1.18s; exit1; wall1.800430s | New caught fixture reused a generic packet helper that drops NORMAL; its real YIELD host RETURN then lacked its original exit port (`exit_binding`). The initial negative test used an inadmissible bare InvokeLiteralResult instead of the exact ContractResult union. Original fixture/unit copies and raw failures remain in attempt001. Fixed only these owned constructions, without changing product or weakening assertions. |
| 002 | 18 passed / 1.18s; exit0; wall1.806041s | All initial routes/counterexamples passed. Its source fingerprint was `f423dde5d4ce5ec479e4041de508d38c7dabfeca365487840a003064bf82d7d4`. |
| 003 | **20 passed / 1.21s**; exit0; wall1.843065s | Added the two explicitly required own-Reference→packet-component counterexamples. This is the final whole owned file. |

Do not sum repeated attempts/subsets. There were no additional hidden smoke or
syntax runs. All three attempts had unchanged registered-source before/after
inventories; final fingerprint:
`6602dd48fec023f6418556f8aa1cad9ad8e4df15591a1a91e28af74764a8e0ec`.
The 20-file local list also matched. No component/full/workload/profiler/GPU run.

## Frozen files and remaining scope

Final hashes are recorded in `attempt003/source-after.sha256`; this report is
additional evidence, not a replacement for the original failed attempt. The
bounded implementation closes these three explicit source-to-consumer route
shapes. It does not close the whole 16-cell generator matrix, Running reentry,
P3 dynamic body association, native/source applicability, M2, or M0–M2. Those
remain in `../design/p2-consumer-coverage-review.md` and the parent fixed plans.
No transformation, native identity, completion or LeWM acceleration authority.
