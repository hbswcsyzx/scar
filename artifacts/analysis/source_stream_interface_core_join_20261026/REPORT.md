# Source stream CALL-to-core join

## Inputs and validation

- Retained capture: `artifacts/experiments/stream_interfaces_main_20261026/joint03/capture/trace`.
- Stream metadata SHA256: `dfc1ef4573c8640f33d1836e8b8f0c3eac861ad66e555d8a5af013057ca8a239`.
- Source file: `artifacts/experiments/stream_interfaces_main_20261026/joint03/program/stream_program.py`; fingerprint `sha256:ffcf5f70e97a6cbc033a59342f0ffbf42bc930cc0b99cc0fd8bb051ede0bd6ec`.
- The original typed `ProgramInventory` re-read and validated successfully. Its `run` definition is `opdef:op:74cef795f3cf97d272722fff`; its body remains `UNSUPPORTED` with no graph.
- A normal `STRUCTURED_ENV` source lowering under the same project root produced a 329-operation `SourceProgram5` with 46 explicit gaps. Its full `SOURCE_REPLAY` validation passed, including exact code-constant slot validation. It matches the original inventory `SourceSnapshot`, definition ID, `SourceReference`, and all seven stream `CallInventory` call IDs. Runtime code-object identity remains unproved.

The bridge accepts that validated source body as a temporary, exact-namespace input. It does not replace the historical inventory body. It uses the existing `_Sources._call_site_body` mapper, then checks each resulting CALL against the original typed `CallInventory` before exposing its source-body Operation and ports.

## Result

The original stream sidecar has seven calls: six `C_RETURN`, one `C_RAISE`. The query connected all seven to canonical `INVOKE` operations in the validated local `SourceProgram5`. Each result identifies `SOURCE_REPLAY_LOCAL_BODY`; the original inventory still has no graph. The combined inventory readback, lowering, replay validation, and query took 10.268 seconds in the recorded run; the typed inventory readback alone took 0.624 seconds. Machine-readable terminal counts and per-call references are in `terminal.json` beside this report.

| Attempt | Method | Observed | Original source Call ID | Source line | Source-body Operation ID | Callee Use | Actual Uses | World Use | Source completion edges |
|---:|---|---|---|---:|---|---|---:|---|---|
| 2 | `seek` | C_RETURN | `opdef:op:8612acb4e5094ad590f1f2a2` | 5 | `program_operation:ea6924b1dba0ce2a156367638b89da63` | `program_use:1834b13495ef2d0dde1535bda147c4cb` | 1 | `program_use:b4d2c97d1ca6317c6d90e0ff864113e2` | NORMAL, RAISE |
| 3 | `read` | C_RETURN | `opdef:op:3dcf0dda81d89f80b9975b08` | 6 | `program_operation:ed96e0abdbb321d5a183038de208bd04` | `program_use:f202288cf9c9d6949c53b6168473bcf8` | 0 | `program_use:0f25782bf8a8fb650945fed7e8383226` | NORMAL, RAISE |
| 5 | `write` | C_RETURN | `opdef:op:040cb3378d363eb1f23b5c7a` | 8 | `program_operation:e978bc92132b624afca890d84f219de9` | `program_use:50a2624e0d1e8ae05bfb7693fd3fbf25` | 1 | `program_use:fd4e9d589bc9090bf00fa43b68936911` | NORMAL, RAISE |
| 6 | `flush` | C_RETURN | `opdef:op:1a47c5e9ae92451fb3fb6026` | 9 | `program_operation:94c912f7b28bdccefbc5c2ea03a1e0b2` | `program_use:c51ac0593dc3dec42ef57124c41e7ced` | 0 | `program_use:5349372ddf0c16d24bc0057bdd2a763e` | NORMAL, RAISE |
| 7 | `close` | C_RETURN | `opdef:op:b5a59f64176b5261f400b94f` | 10 | `program_operation:a50aab424079a867a2c2fbcabdc55e20` | `program_use:10681f85f4a6e86d247314c67a7e06ca` | 0 | `program_use:08581ae73d408cfe433eb3c753a059a3` | NORMAL, RAISE |
| 8 | `close` | C_RETURN | `opdef:op:d985766b4f48131c49ea1dd3` | 11 | `program_operation:c38af5f5c7006b05f04342536019d05e` | `program_use:6f7d13edb0c9d8dad127903af981b08a` | 0 | `program_use:2e54136b50a17fb036f28fac5cb94ab7` | NORMAL, RAISE |
| 9 | `read` | C_RAISE | `opdef:op:d1809e96a717a2cbce721340` | 13 | `program_operation:9f0c852b1659e1844dca2ee0c5e6bb51` | `program_use:302a4493f5a965156ca80b8fc2073a7f` | 0 | `program_use:ffa452dd419b16afb9bbf2b80a27fa3e` | NORMAL, RAISE |

## API and limits

`read_source_stream_interfaces(trace=..., source_model=..., metadata=..., expected_sha256=..., source_program=..., language_options=...)` is the generic entry point. Supplying `source_program` requires a typed original `ProgramInventory`, the exact matching definition/source snapshot, its read-only `SourceCodeEvidence`, and a passing normal `SOURCE_REPLAY`. The body is only used to resolve the exact source CALLs; it is not written into the inventory or treated as a runtime invocation binding.

These ordered source Uses do not establish captured runtime argument values or bind the observed weak receiver token to a source Value or resource. The stream contracts remain incomplete declarations. C return/raise events do not select a source `CompletionResult`, and do not prove bytes, readiness, persistence, or complete effects.

## Main-package integration

The normal package now includes `CODE_CONSTANTS_314_V1` and the source/core join.
The parameterized runner is `artifacts/experiments/source_constant_core_20261026/run_source_stream_join.py`.
Its first main-package invocation exited 1 because the runner replaced the default source capability tuple
with two additions; the incomplete source body was rejected. The failure remains in
`terminal-main-code-failed.json`. The runner now extends the defaults and records the complete tuple.

The subsequent normal-package run exited 0 in 10.653196 seconds and connected 7/7 calls,
with 6 C_RETURN and 1 C_RAISE, using the 329-operation source body and full SOURCE_REPLAY.
See `terminal-main-code-v2.json` and `CURRENT_SOURCE_RECEIPTS.json`. This is analysis time,
not clean program timing, a LeWM episode result, or a speedup. No target rerun was needed.
