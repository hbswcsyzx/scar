# Source fragments and move references

Source fragment records identify a complete source statement against the
current semantic graph, source-semantics overlay, control-flow graph, and
source snapshot. They provide stable references for a later transform delta;
they do not prove that moving the statement preserves behavior.

## Records and wire format

`SourceFragment` and `StaticSourceMove` are core optimization IR records. The
`scar.ir.source_fragments_v2` module re-exports those same classes and provides
strict, schema-versioned dictionary and JSON readers and writers:

- `source_fragment_to_dict` / `source_fragment_from_dict`
- `source_fragment_to_json` / `source_fragment_from_json`
- `static_source_move_to_dict` / `static_source_move_from_dict`
- `static_source_move_to_json` / `static_source_move_from_json`

Every reader checks the exact outer fields, schema name, version, nested record
types, and record invariants. A move contains a fragment and an
`InsertionPointID`; the insertion point itself is resolved by the caller's
current control-flow graph.

## Derivation

`derive_source_fragment(semantic, source_semantics, control_flow, statement,
sources=None, verification_budget=ControlFlowBudget())` validates the
source-semantics and control-flow overlays by replaying them against the
supplied semantic graph and current source text. It then requires one
source-anchored `Assign` statement with one name target, in a single suite. It
collects the statement owner and every SG/source-semantics operation whose
source atoms fall within that statement span, including nested right-hand-side
operations and name reads/bindings. IDs are unique and sorted by wire form.
The text digest is SHA256 over the exact AST source segment.

`validate_source_fragment(fragment, ...)` reruns the derivation and compares
the complete record. Stored IDs and digests do not authorize themselves.
Changed source, stale anchors, omitted or forged operation membership,
duplicate statement positions, nested-scope or conditional expression
regions, and unsupported statement shapes return an explicit validation error
or raise from derivation. Caller-provided verification budgets constrain
source bytes, CFG replay, AST nodes, nesting, and local derivation work.

No imports, expressions, descriptors, or user functions are executed. The
extractor does not use labels, variable names, mutable operation metadata, or
purity hints as source-membership or legality rules.

## Scope and proof boundary

Version 1 accepts only a standalone, one-target `Assign` in a statement node.
It rejects compound suites and expressions with nested scopes or conditional
evaluation. It also rejects semicolon-sharing and inline-comment spans, since
the current source reference does not identify a safe trivia-preserving edit
envelope.

A source fragment does not establish input availability at an insertion,
all-path execution, commutation with crossed statements, exception or resource
equivalence, finalizer timing, frame/local observation closure, consumer
closure, or profitability. Those obligations belong to the caller's fixed
motion proof. A CFG insertion candidate, source operation list, or constant
fact is not a MOVE approval.
