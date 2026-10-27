# Retained source-call ABI gaps: targeted review

## Scope and source receipts

This change addresses the 11 open candidates in the existing full candidate publication. It did not rerun the 201 source reader, the full trace reader, a capture, or a target. The prior full publication remains 2,672 selected of 2,683 direct body-linked candidates; this report does not relabel that denominator or publish a merged 2,683-call model.

The candidate manifest is SHA256 `867a8fa08f97977ccf8aba2add85cd2544691f8aff1c61bcc685dc61160bfb8d` (`artifacts/analysis/source_call_port_all_20261027/publication/manifest.json` in the original worktree). The full result records ten `unsupported source CALL/function positional ABI` issues and one issue worded as a missing CALL position/opcode. The bounded row receipt in [issue-event-summary.json](issue-event-summary.json) binds the original operand and frame files to their prior full-scan SHA receipts and confirms the files stayed stable. It did not rehash either full file.

Targeted reads examined 824 operand rows (296,165 returned bytes) and 1,496 frame rows (1,227,588 returned bytes), plus the two small metadata files. The normal source reader loaded only two source body groups and their existing code witnesses. Total targeted run time, including typed codec readback, was 3.58 seconds. No weak-reference token strings or tensor/value payloads are written into the report artifacts.

## Observed facts

Ten `CALL` sites all resolve to `v.check()` in the retained `Dict.check` body. The original `FunctionSignature` is `check(self, debug=False)`: `self` is required; `debug` has a declared `default_source`. The raw callee-entry layout is `(self, debug)`, and each of the ten attempt `arg0` tokens matches the captured entry reference for `self`. The check is an implicit receiver with zero explicit positional actuals; `debug` is omitted.

The remaining site is `CALL_KW` at `variation_space.check(debug=True)`. Its source location is present. The old error text called the source position/opcode absent, but the actual blocker was that the producer only accepted opcode `CALL`. The retained core `INVOKE` operation already has the exact `keyword:debug` Use and source expression, and the raw entry `arg0` reference matches the first formal `self`.

The full 201 reader receipt was used as the existing capture-wide boundary receipt. This targeted pass decoded only local intervals, verified their event indices/anchors, and ran the existing normal source/body readers against the receipt-qualified report, bindings, source artifacts, code witnesses, inventory, and signature.

## Implemented connection

The existing producer now accepts exact `CALL_KW` sites when the original AST call has explicit keywords, resolves each keyword value to the original ordered Use by its `keyword:<name>` role and exact source span, and routes it through the source signature. Existing positional call routing remains in place.

For normalized receiver calls, the producer now requires an attribute call with no explicit positional operands, a required first positional formal not explicitly supplied by keyword, a complete matching entry layout, and equality between the captured `arg0` reference and the first entry-formal reference. Each other formal must be supplied by an exact keyword Use or have a declaration default. Attribute calls with explicit positional operands remain unresolved because a plain function stored on an attribute can have the same observed arity and first-argument layout as a method.

The target record's normalized-receiver arity check now allows declared function parameters beyond the implicit receiver and explicit positional prefix; the source producer admits them only after checking the original signature. This allows the existing shared signature to remain the authority for default declarations rather than copying a second signature into each call record.

The local typed path built all 11 source bindings and decoded them through the existing record codec with exact equality. [local-bindings-final.json](local-bindings-final.json) contains their original operation/Use/formal/source locators and a concise machine summary. Counts: 10 `CALL`, 1 `CALL_KW`; 11 conditional receiver projections; one explicit keyword port; ten declared default omissions.

## Limits retained

The receiver route is conditional; the reference match is not an identity proof. `default_source` identifies the static source location of a default declaration, not its current runtime value. This work establishes no default-value snapshot, selected return, normal completion, ready state, content equality, effects, or tensor payload. It does not establish full attempt coverage or repair the full candidate publication denominator. Starred and double-starred arguments, variadic/keyword-only signatures, decorators, suspended functions, and ambiguous attribute calls with positional actuals remain outside this rule.

## Files

- `scar/analysis/retained_source_call_ports.py`
- `scar/ir/program/python_call_targets.py`
- `build_local_bindings.py` and `read_issue_events.py` are bounded, receipt-driven reproduction scripts.
- The two JSON artifacts contain only the 11 local event/typed results and receipts.
