# Content connection history receipt

This receipt records only the connection-fixture attempts already made. No
smoke or test was rerun to fill gaps in the older records.

## Smoke attempts

| Attempt | Preserved record | Outcome | Command/source provenance |
|---|---|---|---|
| `attempt001` | `smoke.log` | Fixture construction failed: `StateAccess.full_overwrite` received the reference `UseID` positionally. | Inline command and source hash were not captured. Do not infer them from the current fixture. |
| `attempt002` | `smoke.log` | Fixture construction failed core validation: the mutation operation had a read access but omitted `Behavior.READ`. | Inline command and source hash were not captured. |
| `attempt003` | `smoke.log` | Data, Work, Observation, and duplicate-Use variants validated; Reference failed because its fixture omitted the exact `AccessRef` effect. | Inline command and source hash were not captured. |
| `attempt004` | `smoke.log` | The five non-native smoke variants validated after adding `AccessRef` and correcting the observation details to use the current `model.content_reads`. | Inline command and source hash were not captured. |
| `attempt005` | `command.txt`, `smoke.log`, `exit_code.txt` | Native smoke failed on a missing `EvidencePoint` fixture import. | The saved command file is the available script record; no source hash was recorded. |
| `attempt006` | `command.txt`, `smoke.log`, `exit_code.txt` | Native path construction failed because `Block.arguments` contains `ValueID`s, not objects with `.value`. | The saved command file is the available script record; no source hash was recorded. |
| `attempt007` | `command.txt`, `smoke.log`, `exit_code.txt` | Six variants validated: host Data, host Reference, two Work tickets with distinct EEG instances, Observation without Work, and native Return and Raise. All reported no issues; expected proof gaps remained. | Exact inline script/command is saved. The fixture source hash was not captured at execution time. |

Attempts `005` and `006` have nonzero exits and retain their original output.
`attempt007` is the final smoke result; no later smoke was run.

## Owned test attempts

| Attempt | Result | Source hashes |
|---|---|---|
| `test-attempt001` | 11 passed, 2 failed. One assertion expected an issue where an absent exact source pair is intentionally an unresolved gap. The other expected `content_native_actual` for native output position 2 on a Return; that slot is a Raise port, so `content_native_exit` is the correct rejection. | Not captured. The original JUnit and stdout/stderr are preserved. |
| `test-attempt002` | 14 passed. | Before/after hashes are present in the attempt directory and match: fixture `cd1959d54ad7993b837fc51206cb78fbf3b4beb18778532e4060a00b14d707a3`; test `44de2d8e4b3e70227a8aae64722e5a97b8b79566300bed49ec6dad61c00eae5a`. |
| `test-attempt003` | 14 passed after adding a native actual-value mismatch check. | Before/after hashes are present and match: fixture `cd1959d54ad7993b837fc51206cb78fbf3b4beb18778532e4060a00b14d707a3`; test `2ab3cc2802867087cdc6cd3cca714a6489efa1d0b0eba147a765455e14456062`. |

The root component run covers the later EOF normalization. This agent did not
rerun a test for that normalization. The source changes are covered by the
root's component result, not by `test-attempt003`.

## Interpretation boundary

These fixtures test typed joins and known contradictions in supplied program,
execution, ValueGraph, and EvidenceGraph records. They do not establish that a
declared EEG/native association was observed at runtime, that the selected
content stayed stable during a read, or that a transformation is authorized.
