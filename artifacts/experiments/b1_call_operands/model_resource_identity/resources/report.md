# R1 resource records — limited constructor result

Implemented: `scar/ir/execution/resources.py` and its dedicated constructor test file only.
All records are frozen/slotted with exact IDs/enums/tuples and nested revalidation.
Resources, native-handle lifetimes, existing object/allocation identity and requirement bindings remain separate.
Rights completeness, release authority and sharing are independent declarations; unresolved facts remain explicit.
Implicit bindings require no fabricated handle value; no readiness, resource-state or proof authority is added.

## Verification

- Conda environment: `lewm`; `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.`.
- Command: `python -m pytest -q tests/unit/test_execution_resource_records.py`.
- First and only pytest run: **26 passed in 0.38s**, exit 0.
- Exact interpreter, command, environment, initial stdout and source hashes are preserved alongside this report.
- Tests include static/dynamic ID confusion, fd incarnation separation, alias acquisition of an existing target, explicit/implicit/unresolved associations, independent rights/ownership axes, exact indices and recursive private-mutation rejection.

## Scope

Only local record construction and direct small-record codec round trips were exercised.
Graph existence/owner/current-state/constraint checks, snapshot wire, queries, runtime collection, GPU causality and actual permission/lifetime validity are not established by this run.
No workload or GPU execution, full suite, installation, source transformation or git action was performed.

## Frozen source hashes

- `scar/ir/execution/resources.py`: `657fca489d07fd3e32e5552782e02c6b6b58c8ed061c3c0040313d442a2e3000`
- `tests/unit/test_execution_resource_records.py`: `822f038d5eedf3ac026cec8bb1b5b109636fcd9a1bd944cbc27dc3aba5591a38`
