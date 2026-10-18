# R3.1 call core review and focused record

Review scope: the owned call activation records and validator, plus their existing
baseline tests and shared call fixture. This is a component-level note; it does not
claim the broader R3 composition work or M0–M2 complete.

## Final owned source snapshot

| File | SHA256 |
| --- | --- |
| `scar/ir/execution/calls.py` | `a287446babd077c072f51182d12ecc5e670bd2e1700b6396e914e134d95a183f` |
| `scar/ir/execution/call_validation.py` | `79febd82eea06447ad045e8302a62a17164bb04771c9a2ef852b28640a127f4b` |
| `scar/ir/execution/ids.py` | `3d5097166d01f177ec7295e74b74567c0a93ef2482cd371138d3e23578df7d29` |
| `scar/ir/execution/model.py` | `14a28d9531b744924e24ba1633b691cdb91019e37829665e5f711369c7f2a126` |
| `scar/ir/execution/validation.py` | `e3a440dc32c4aacba3b4a53b536d11341c0892a4bb5dda08007448bc5dba395d` |
| `tests/unit/test_execution_call_records.py` | `ecdd19730b63cdeda4d9eb0a9ec0a28fbb1d84aaf8c176fdbd406c717f201f3c` |
| `tests/unit/test_execution_call_validation.py` | `843b486b8cdeb917aa230056c6c88731a07e4cf100a1174dfe01ba95ab1e964c` |
| `tests/fixtures/execution_call_graphs.py` | `6fa0d2eca706edc3a371d4d8d8581973b7e28b94ce5623e89048789e3fc8c90b` |

The new record remains a relation between the original caller occurrence, child
activation, initial entry visit, actual terminal occurrence, and provenance. Inputs,
outputs, states, CFG edges, and dynamic values continue to come from the original
ProgramGraph and occurrence tables. The query/validator does not infer runtime value
identity, source correspondence, or transformation authority.

## Review findings and corrections

An earlier source review found that thread comparison only ran when the entry visit
was known. That could let an unresolved entry hide a known caller/child thread
contradiction. The validator now checks all captured segments indexed for the child
activation, independently of entry availability. It reports a mismatch when the
union of known caller and child thread IDs has more than one member, while keeping
each unresolved thread as a gap. The original finding was source-derived; no claim is
made that the pre-fix validator was run on that constructed counterexample. A separate
boundary test is being added by the query/records reviewer; this report does not count
that regression as passed.

The validator now also indexes actual RETURN/RAISE occurrences per activation and
reports `call_multiple_completion` when a linked synchronous child has more than one
captured terminal occurrence. This avoids treating disconnected extra terminal
occurrences as multiple valid returns merely because the entry-to-selected-completion
path is incomplete. Its targeted boundary regression is likewise pending and is not
counted among the baseline tests below.

Known provenance inequality is not treated as proof of a different event: the static
activation entry and `InitialEntry` can carry distinct FactReferences while agreeing
on their run/process and canonical activation/entry visit. Missing source
correspondence remains unverified. Dynamic call nesting is checked iteratively; static
recursive Regions may use separate activation IDs.

The implementation builds activation-to-segment and activation-to-terminal indexes
once, and traverses the captured visit chains and dynamic call graph iteratively. These
specific indexes/traversals are linear in their input rows and edges; this is not a
claim about the total cost of core validation, canonical port checks, or other
execution validators.

## Focused test record

The exact command for attempt 004 was:

```sh
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. pytest -q tests/unit/test_execution_call_records.py tests/unit/test_execution_call_validation.py
```

Attempt 004 passed **23 tests in 0.77s** after the current thread/terminal-index
changes. Its full output, exit code, Python version, command, and current source hashes
are in `../core/attempt004/`. Attempts 001–003 are retained unchanged:

| Attempt | Command scope | Result | What it records |
| --- | --- | --- | --- |
| 001 | `test_execution_call_records.py` | 14 passed, 0 failed | Record-only constructor/ID/frozen cases. |
| 002 | records + baseline call validation | 23 passed, 0 failed | First combined core/validator baseline. |
| 003 | records + baseline call validation | 23 passed, 0 failed | Rerun after route/gap review changes; source hashes are preserved with the attempt. |
| 004 | records + baseline call validation | 23 passed, 0 failed | Current source after thread and multiple-terminal guard changes; no targeted new boundary case is included. |

The nine baseline validation cases are the two-call/shared-body case; INVOKE normal
and raise successor selection (two parameter cases); missing caller transfer;
disconnected entry-to-completion path; wrong entry; unresolved endpoint with known
process conflict; missing association; and unresolved endpoint scope preservation.
The fourteen record cases cover frozen typed endpoints, explicit missing endpoints,
six wrong nested-type inputs, five nested-ID mutation checks, and an explicit missing
provenance source.

Attempt 004's source hash list is in
`../core/attempt004/source-sha256.txt`. Earlier attempts without a captured hash file
remain without one; no historical hash has been reconstructed. No full suite, target
program, GPU task, or LeWM run was started by this review.
