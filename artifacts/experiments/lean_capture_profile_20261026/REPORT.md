# Lean source-port capture: finite actual result

One generic nested Python+Torch CPU program, fixed source/inputs: selected run/method/leaf and an unsupported starred-call body; callback bridge intentionally unplanned. Imports and caller-owned Tensor construction were outside the declared capture scope. No LeWM, GPU episode, Tensor-content read, extra copy/sync, or performance benchmark.

Legacy process21332 and final indexed lean process83594 actually exited0. Normal typed readers plus a fresh owned link_call_operands consumer (session12347) exited0 in1.239869s. Every retained PythonSourcePortBinding was rechecked in that same session and the saved model ordinary loads passed; JSON was not used to restore a producer owner.

| Observation | Legacy windows | Final lean |
|---|---:|---:|
| Stored capture bytes (all files, including lean plan/cache diagnostic) | 61182 | 45286 |
| Instruction rows | 28 | 0 |
| Observed target attempts | 9 | 7 |
| Typed source-port bindings | 4 | 3 |
| Planned source-call bindings | 3 | 3 |
| Planned independent receiver / explicit argument ports | 1 / 4 | 1 / 4 |

The three planned call-site/formal-role tuples match exactly (run→bridge, run→Box.step, step→leaf). Identities from different captures are not conflated. The one extra legacy binding inside the unplanned callback bridge is intentionally not claimed by lean; its dynamic interior remains an explicit expansion/dispatch debt. Native dispatch metadata records9 events, errors[]/gaps[] for the real Torch operations; this does not establish tensor content/state/ready or a full native model.

Blocked CALL_FUNCTION_EX generated two code/activation SCOPED_GAP records (static unexpanded-site frontier and observed unsupported callback), owner5. Later run→Box.step and step→leaf still bound normally: the local failure did not become a global epoch gap. Final capture reported0 drops/errors,4 targets still open,3 conditional bound calls,1 receiver and4 explicit ports; these counts are finite evidence, never whole-program coverage. Old reference-equality routes remain unsupported for the new rule.

Private CodeType matching now has a source-key index, weak identity memo and independent default4096-code budget; normal-close diagnostic confirms memo size0. No frame, Tensor, callable or mutable IR validity is cached. Source version/install/stop guards remain. Global integrity stop is implemented by the old mechanism with explicit global lean epoch, but no separate hook-corruption matrix was run.

First-scope lean captured unnecessary unplanned descendants:46 frame events/62,333B, so it was rejected as the design direction. Its files and exact first source snapshot remain. The scope was narrowed to direct thin interfaces and explicit planned re-entry; final capture has20 frame events. The first offline consumer script incorrectly used nonexistent model.dumps; its failure is retained. Normal to_dict/loads was then used. No failure was relabeled PASS.

Seven production sources only; final exact hashes and main preimages are SOURCE_RECEIPTS.json and the net MAIN_LEAN_ONLY.diff. Existing main buffering was the test baseline and remains outside the semantic lean commit delta. Public CLI, automatic entry-plan generation, archived multi-version selection, broader thread/provider completeness and remaining effect/lifetime/ready obligations are not implemented/qualified by this gate. Model remains OPEN.
