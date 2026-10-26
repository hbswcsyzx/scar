# Owned v2 consumer and qualified external bodies

The public fresh `link_call_operands` end-to-end case actually passed in 3.66065s. Its normal retained/gzip read passed independently in 2.37968s. All 8 original attempts remain represented: 5 conditional source-call bindings, 2 independent receiver ports and 5 explicit argument ports; 6 actual entry relations. The three remaining source boundaries are class construction, native len and the non-supported default-argument layout. This is a generic 2-file Python example, not LeWM or a full-program completeness result.

Two external ordinary SourceProgram5 artifacts were produced through the existing dependency admission → compiler witness → SourceEntryCatalog → bounded ordinary source worker → publisher → CompositionIndex reader path. Both project→external and external→external calls resolve to those original SP5 namespaces/Regions. The external functions were not relowered during retained consumption. The compiler acquisition explicitly built one source module and independently replayed it readonly; this is not an all-compile-zero claim. The small actual capture was executed once; no LeWM episode or prior LeWM bodies were replayed.

`link_call_operands` and `connect_current_capture` expose four explicit kw-only arguments:

- `python_source_port_consumer(model, check)`: receives the distinct v2 model and same-session semantic rechecker.
- `python_source_port_budget`: exact `scar.ir.program.python_call_targets.PythonSourcePortBudget`; sidecar stored and decoded ceilings apply separately, plus row/attempt/output-port limits.
- `python_source_body_composition`: optional normal `CompositionIndex.from_source_entry_publication(...)` with its original qualified body publication.
- `python_source_inventory_artifact`: original `SourceArtifactLocator` only for the ordinary nonpartitioned inventory path; partitioned owned source access uses its original body locators.

The consumer runs while the original call model, inventory, operand scan and `_Sources` are still live. No saved JSON reconstructs an owner or substitutes a previous raw scan. The historical `source_port_consumer`, ArgumentRoute, CallOperandReport/wire and all default behavior retain v1 meanings. The `connect_current_capture` owned-forward path was API/implementation checked; this small actual case exercised the public normal fresh linker, not a full retained-Run `_OwnedCurrent` orchestration.

External lookup starts from a full bound SourceDefinitionReference, then `CompositionIndex.body_reference`/`typed_qualified_body` and the original SourceEntryCatalog/compiler archive. With an ordinary inventory, the catalog must additionally bind the exact same original raw frame manifests and process/code group. `_Core` reuses the existing formal/environment/world guard inside this qualified context. External records do not enter bare DefinitionID maps; no graph, environment, Value/Use, Invocation or CallActivation is created as a surrogate. A source-only record without an admitted body remains open. The old source-invocations2/3 checker and the same-capture4/5 contracts were left closed.

Every selected actual binding passed `check`. A wrong receiver→formal1 relation was rejected by recomputation from the original source/code/ports. A wrong expected-definition signature was rejected by the preserved old formal guard. One existing default-off route test passed (1.90s). Native/state/content/effect/ready/closure atomicity, broad default/keyword/nonweak dispatch and new method return-identity routes remain OPEN.

The new target stream was losslessly archived in place to its sole same-logical-URI `.jsonl.gz`. The reader uses `scar.trace.files.resolve/open_binary`, rejects ambiguous/symlinked forms, bounds stored bytes before decoding, and verifies original decoded EOF/SHA/rows and all five legacy manifests. No namespace/anchor URI changed; the full model is identical before and after archive. Metadata remains plain JSON.

Exact model: `case01/model.json`, 90,578B, SHA **d71743e6e58a4b90975a725cfa0ac53486e1abc7178754085fd404288037288b**. Reader remains `PythonSourcePortModel.loads`; use `binding.entry.caller/callee`, `binding.arguments`, optional `binding.receiver`, and their original body artifact/namespace.

Two harness failures are retained: the first guessed `composition/index.json` instead of the real `.json.gz`; the second guessed `admissions/report.json` instead of the real `admissions.json`. `run03.py` reused those original completed metadata artifacts and succeeded; neither failure was changed to PASS. The production semantic guards were not relaxed.

Root owns CLI/sitecustomize, OS membership/archiver and main integration. Capture enablement is exactly `SCAR_PYTHON_CALL_TARGETS=PYTHON_CALL_TARGETS_V2` (unset/0 off), or explicit `install(...python_targets=True)`. This commit does not edit those Root-owned files or `trace/call_edges.py`; its previous entry guard must still be semantically merged with main's buffer/fork fixes.
