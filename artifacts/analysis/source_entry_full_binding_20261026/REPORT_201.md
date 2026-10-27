# Full 201-source binding

## Terminal and scope

**PASS** (shell exit code 0). The normal reader consumed the 201-row publication and returned a `CompositionIndex`; the original capture-coordinate binder and `bind_source_invocations(..., witness_mode="same_capture")` then completed for PID `272038`.

- Source commit: `5a858b1057be3c6f12f3433119695fecdf89a634`.
- Source snapshot: 420 Python files, 8,545,676 bytes, tree SHA-256 `a131d9ad2d11bf287ecd2ea4a6e5b12c92dc81451c9f072ec747d816725fd105`; receipt SHA-256 `52c5d46db078e6bb77d493f0dfdf2872795de7cb6a9f8aba978fefc6924bd298`. The duplicate 8.55 MB source payload is not in Git; it is reproducible from the pinned source commit.
- 201 publication: `/home/zyf/AAA/scar-worktrees/source-entry-publish201/artifacts/experiments/source_entry_incremental5_20261026/result/manifest.json`, 201 rows, 5,646,756 bytes, SHA-256 `1978e56b4f8974a167bc68ad21efadf6e10301ac1c2009cee767a1cd57b20c0b`.
- Original parent-196 manifest was restored byte-exact at its recorded URI: 5,505,173 bytes, SHA-256 `a124d78bb5e50e4ff96d1af2858357651cb9eda13918c328fd753a3a4bd4650b`. The 161 CP2 restore receipts are recorded in the committed restoration manifest (`f7009211`).
- Capture root: `/home/zyf/AAA/scar-worktrees/structured-program-model/artifacts/experiments/first_stage_lewm_dispatch_20261023`; trace: `/home/zyf/AAA/scar-worktrees/structured-program-model/artifacts/experiments/first_stage_lewm_dispatch_20261023/trace`; one process, 817 entered code groups, 100,438 invocations.

## Phase timings

| Phase | Seconds |
|---|---:|
| Composition public reader | 4709.446 |
| Capture coordinates | 5.554 |
| Same-capture source invocation binder | 2751.997 |
| Total | 7470.315 |

## Actual binding results

| Measure | Count |
|---|---:|
| Calls / exits | 100,438 / 100,438 |
| Orphan exits | 0 |
| Captured codes / complete descriptor matches | 855 / 817 |
| Invocation outcomes: body-linked / source-linked / unresolved | 93,237 / 2,251 / 4,950 |
| Source-code groups: body-linked / source-linked / unresolved | 293 / 375 / 149 |
| Raw call scan | 201,765 lines, 187,712,707 bytes |
| Same-capture raw manifest replay | `True` |

These counts describe source and capture associations; they do not complete program semantics. Each of the following remains unconnected for all 100,438 invocations:

| Unverified interface | Count |
|---|---:|
| `ACTUAL_FORMAL_ROUTING_UNVERIFIED` | 100,438 |
| `CANONICAL_CONTROL_COMPLETION_UNVERIFIED` | 100,438 |
| `FUNCTION_ENVIRONMENT_UNVERIFIED` | 100,438 |
| `RETURN_VALUE_ROUTING_UNVERIFIED` | 100,438 |
| `STATE_EFFECTS_UNVERIFIED` | 100,438 |

The run report also marks whole-program graph, first-stage completion, target execution, effects, and transformation authorization as false.

## Input raw receipts

The following are the exact raw input SHA-256 receipts used by the reader and binder. Complete source-publication dependencies and machine-readable scopes are in [`INPUTS_201.json`](INPUTS_201.json).

### Capture trace files

| Family | URI | Lines | Raw bytes | Raw SHA-256 |
|---|---|---:|---:|---|
| codes | `/home/zyf/AAA/scar-worktrees/structured-program-model/artifacts/experiments/first_stage_lewm_dispatch_20261023/trace/call-codes.272038.jsonl` | 855 | 226,156 | `4d1f4c2b675481a1af7bc65f7ad6073796e2f1e85695d3538ecdc92988d8eff4` |
| events | `/home/zyf/AAA/scar-worktrees/structured-program-model/artifacts/experiments/first_stage_lewm_dispatch_20261023/trace/call-events.272038.jsonl` | 200,876 | 187,485,595 | `f44ee6c7616566f8cf670b51de23afd0cae33cd4929cd18443af177d4e463ff9` |
| meta | `/home/zyf/AAA/scar-worktrees/structured-program-model/artifacts/experiments/first_stage_lewm_dispatch_20261023/trace/call-meta.272038.json` | 34 | 956 | `297df87ea99ff7fce1ce6ba1522878675ccdea4434bcd2d132eb713045c96747` |

### Compiler witness archive manifests

| URI | Bytes | Raw SHA-256 | Modules | Sources |
|---|---:|---|---:|---:|
| `/home/zyf/AAA/scar-worktrees/structured-program-model/artifacts/experiments/first_stage_partitioned_operand_routes_20261023/result/code-witnesses/manifest.json` | 42,283 | `56355f7ef10d16d8ab4fb02a84988cf2f0070b75e4cd5fccbf1c86c1ea34170d` | 20 | 20 |
| `/home/zyf/AAA/scar-worktrees/structured-program-model/artifacts/experiments/model_run_dependency_gate_20261025/model/attempts/1792957279902353768-1410025/02-dependency-witness/archive/manifest.json` | 9,689 | `8c16a942e037c6a3a5357043e291df521ba67a809ed5d3770c98d663b5057c71` | 4 | 4 |
| `/home/zyf/AAA/scar-worktrees/source858-runtime/artifacts/experiments/lewm_archived_compiler_gate_20261026/result/archive/manifest.json` | 39,492 | `d3c67c93ff2da74c3fd51bcbe235382dc09a7ca2f363b56edc158fc1004791b1` | 8 | 8 |
| `/home/zyf/AAA/scar-worktrees/structured-program-model/artifacts/experiments/lewm_remaining_compiler_gate_20261026/result/archive/manifest.json` | 438,185 | `33f6fdbc0765ec8787159ced5b1d4acda031e85aba16f77fe0eaab041bb26179` | 94 | 94 |

Source inputs also included the inventory manifest (`/home/zyf/AAA/scar-worktrees/structured-program-model/artifacts/experiments/source_frontend_remainder_publication_20261025/result/publication/manifest.json`, SHA-256 `4959e7a58abe42415ad2a066f96572a83c83f5b4aaebe9462778d5569439ef5d`), composition canonical SHA-256 `70115d30961497ca9a3b8e4ceaa92c7bca2d6fc495083af92a197d2b6f004cc6`, and the source-admission attachments named in `INPUTS_201.json`.

## Output retention

Small evidence files are committed with this report. The remaining 39,722,475 bytes of binder outputs remain at their original local URIs and are not staged in Git; their URIs and raw hashes are preserved here:

| File | Local URI | Stored bytes | Raw SHA-256 |
|---|---|---:|---|
| `bindings.json` | `/home/zyf/AAA/scar-worktrees/source-entry-project/artifacts/analysis/source_entry_full_binding_20261026/actual_201/bindings.json` | 8,285,312 | `096c5a53213bae9f480ba813c240a277220ce6ac636390c0edff3bde9a91f449` |
| `capture-coordinates.json` | `/home/zyf/AAA/scar-worktrees/source-entry-project/artifacts/analysis/source_entry_full_binding_20261026/actual_201/capture-coordinates.json` | 665,555 | `dbfaa3248973d0256e658dab3c16e25ae9ef4d16e4dc3b503794adbcea0a164a` |
| `invocations.jsonl.gz` | `/home/zyf/AAA/scar-worktrees/source-entry-project/artifacts/analysis/source_entry_full_binding_20261026/actual_201/invocations.jsonl.gz` | 30,771,588 | `be0359963c1ea26df8e7b88d71c1409bdcc64de192fd0513dbfc2dcf27d37476` |
| `orphan-exits.jsonl.gz` | `/home/zyf/AAA/scar-worktrees/source-entry-project/artifacts/analysis/source_entry_full_binding_20261026/actual_201/orphan-exits.jsonl.gz` | 20 | `9ceffb7310338057cfe71a4ae1e2c98d2c485d81cdef906532a801f457a38d64` |

The original compressed invocation output reports 803,318,800 decoded bytes with raw SHA-256 `b2a848fc984e170590b814f273ea736baaa1c9eee5ebc7311ccc5c4951e30d35`; no invocation payload was copied into this report.

## Committed evidence

- `ACTUAL_RESULT_201.json` — SHA-256 `2200e3136abb3816a0e7360d062783e9ce01f7231e855c5c0d3b48fb122b3693`.
- `ACTUAL_TERMINAL_201.json` — SHA-256 `8c425711c72e5abdc087e2dfa4fe41479119f4f841d3bf42820a6daf0f071911`.
- `actual_201/report.json` — SHA-256 `88e0ad71244ba59a455eb8bcd3a369fbe579e7c2e95bb3498d123bd4a965aa6f`.
- `SOURCE_SNAPSHOT_RECEIPTS_5a858b10.json` — SHA-256 `52c5d46db078e6bb77d493f0dfdf2872795de7cb6a9f8aba978fefc6924bd298`.
- `run_201_full_binding_5a858b10.py`, stdout, stderr, exit code, and `INPUTS_201.json`.
