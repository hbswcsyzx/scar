# D1 driver validation — read-only adversarial review

Date: 2026-10-18. Worktree HEAD observed: `306a789c80ea7dd407b7fc88635056fa99fed1ad`.
No product, fixture, test, or documentation file was edited for this review.

## Scope and current source identity

Reviewed `driver_validation.py`, `driver_flow.py`, `control_validation.py`, and their
call order/use sites in `validation.py`. Current SHA256 values:

| File | SHA256 |
| --- | --- |
| `scar/ir/program/driver_validation.py` | `05883c4c05e1f39f00299b70451a4df7683774d23286cd20f69eb163ad60b521` |
| `scar/ir/program/driver_flow.py` | `57fb2c403878f751d69d43b7e94a07125a0c647ddc77fdb179b75d8bdaf0ef26` |
| `scar/ir/program/control_validation.py` | `deae20c2c5056a5feac096bce4202cf7c646c334267f01c9f73d3a1ab945ed3a` |
| `scar/ir/program/validation.py` | `f1ea5e9c3799c341d778a4268fe099ee668aa6e3088620a236343b41c142dfc0` |

## Findings

One real undercheck was reproduced and fixed by the owner during review. The raw-request
producer was described as a pure interface constructor but initially accepted behavior
labels `WRITE`, `READ`, `MEMORY`, `TRANSFER`, `ORDER`, and even an empty behavior tuple.
Those mutations all passed `validate(raw_only_program())`. The owner tightened the check
to nonempty labels contained in `{COMPUTE, CONTROL, REPRESENT}`. The independent owner
regression records seven failures before the fix and seven passes after it at
`../graph/raw-behaviors.before-fix.log` and `../graph/raw-behaviors.after-fix.log`.
Those logs are the evidence for the before/after result. The source SHA table above is for
the **post-fix** files only; it must not be used as the identity of the earlier process's
in-memory module.

No additional concrete bypass or validator crash was found in the bounded probes.

## Cross-table and state checks inspected

- `driver_errors()` cross-checks operation ownership, raw definitions, Create body and
  environment, full Reference capture partition, function-object capture, typed NORMAL
  result slots, async request/association ports, interfaces, gate/drive pairing, and body
  targets. Duplicated metadata keys and conflicting operation roles are rejected.
- Gate success is a private NORMAL landing with exactly the paired Drive. Gate input
  values must be independently forwarded through edge Use → landing formal → Drive Use.
  Receiver/scheduler copies use all actual CFG predecessors and a seeded must-forward
  fixed point. Each gate completion carries all driver state domains; body state inputs
  cover body domains by `LocationID` and must be the NORMAL completion's produced state.
- `driver_flow` resolves only a declared resumable body or one real Suspend successor.
  The first-outcome helper traverses the ordinary CFG, including INVOKE and C0/C1 routing,
  stops at the first Suspend/Return/Raise, and makes no must-terminate claim.
- RAW_DRIVER_REQUEST is intentionally excluded from C0 lexical protocol checks and gets
  its own producer/operand checks in `driver_errors()`. It does not become a pending
  completion or exception packet.
- The ordinary core still rejects direct CALL and INVOKE of a declared resumable body.
  The driver graph accepts C1 cleanup plus nested INVOKE and loop bodies through the
  existing resumption validators; no alternate producer graph was added.

Malformed metadata probes failed closed: an out-of-range resume case returns
`driver_target`, an out-of-range Create NORMAL result returns `driver_result`, a missing
body-state Use is rejected earlier as `control_binding`, and post-construction corruption
of a target variant or a bool result index returns `schema`. None raised an exception.

## Verification

Python: CPython 3.14.7, conda environment `lewm`.

Focused command:

```sh
source /home/zyf/miniconda3/etc/profile.d/conda.sh && conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. pytest -q \
  tests/unit/test_program_driver_graph.py \
  tests/unit/test_program_driver_queries.py \
  tests/unit/test_resumption_invoke.py \
  tests/unit/test_program_cleanup_graph.py
```

Result: **82 passed** in 1.25s. This includes valid Create/Drive, C1+INVOKE body
frontier, loop frontier, and direct resumable-body call rejection. It is a focused
component check, not a full repository or runtime test.

The read-only probe and its current post-fix output are
[`core-adversarial.py`](core-adversarial.py) and
[`core-adversarial.log`](core-adversarial.log). Their SHA256 values are
`4aa3a1d33b1760cec2980d56ef8386f3e032287c4f399e0a464e0de2ee48f586` and
`61d27cac61b40faba620ae7f9532f1f4002f994cd9c53e787bf22f397ef48fac`.

## Limits of this result

These records and validators establish a structural declaration over current Uses,
completion ports, and CFG edges. They do not establish that a runtime request is associated
with the declared body, that a guard executed, that no callback or frame interposition
occurred, or that a provider implements the declared rule. Opaque dynamic calls remain
opaque; unknown runtime instances are not treated as known Create outputs. D2 request and
session lifecycle semantics remain open.
