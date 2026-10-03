# Local statement semantics v2

`scar.analysis.local_statement_semantics_v2` derives a source-replayed report for
a small subset of ordinary synchronous function bodies. It records statement
structure, exact local reads and writes, immutable builtin value facts, and
constant proof lineage. The report is an input to a later legality proof; it
does not by itself approve a motion.

## API

```python
report = derive_local_statement_semantics(
    semantic,
    source_semantics,
    control_flow,
    suite_id,
    source_texts=None,
    budget=EvaluationBudget(),
    control_budget=ControlFlowBudget(),
)

report.validate()
document = report.to_dict()
restored = LocalStatementSemanticsReport.from_dict(
    document,
    semantic=semantic,
    source_semantics=source_semantics,
    control_flow=control_flow,
    suite=suite_id,
)
```

The source semantics and CFG are both strictly replayed from the supplied
semantic graph and source snapshot. A saved report's coverage or certificate
fields are never trusted. The constant evaluator and CFG replay have separate
caller-controlled budgets; a serialized report cannot raise either ceiling.

The report contains the selected scope and suite, source version, semantic,
source-semantics and CFG digests, a combined model digest, deterministic usage
counts, `coverage`, ordered statement certificates, explicit gaps, and the
fixed required conditions. `Coverage.SUPPORTED` means every direct statement in
the function body received a certificate and no gap remains. Otherwise the
report is `Coverage.INCOMPLETE`; any individual certificates are diagnostic
records and must not authorize a move on their own.

Each `StatementCertificate` binds its stable ID to the function scope, suite,
source reference and statement operation. `ordered_reads` retains each exact
`BindingUseID` paired with its `StaticBindingID`; `read_bindings` is a derived
convenience property. Assignments also name the first local binding and slot,
expression/result static values, immutable builtin type, and constant proof
lineage. An alias certificate identifies the exact binding it reads. It does
not infer alias identity from equal constant contents.

## Supported body

The first rule version only accepts a synchronous `FunctionDef` with no
decorators, defaults, annotations or variadic parameters. The body must be one
straight-line suite with exactly one final `return`:

- `Assign` has one `Name` target that is a new local binding, not a parameter,
  outer, global or nonlocal slot. A local slot is assigned once in the body.
- The right side is an immutable literal or tuple of immutable literals, a
  finite closed builtin expression whose value and proof lineage the fixed
  constant evaluator recomputes, or a direct load of an earlier exact local
  binding.
- `return` returns an immutable literal or a direct load of an exact local
  binding. `pass` is allowed.
- Every `Name` read in the function scope must join exactly to its fingerprinted
  source operation and one preceding first-local binding. Unused local writes
  are allowed; the report does not perform dead-code elimination.

Calls, attributes, indexing, mutable containers, repeated assignments,
parameters used as values, closure captures, namespace declarations, branches,
loops, exception/context-manager suites, async/generator behavior, deletion,
augmented assignment, and unsupported expression forms create explicit gaps.
Known arithmetic exceptions are gaps. Floating arithmetic remains unsupported
until its floating-environment condition is part of the consuming Q model.

Source statement ownership, assignment's destination child operation, the
statement's RHS slot, and the function return slot are joined against the
SemanticGraph. Source binding uses and static value dependencies are replayed
against `SourceSemanticsGraph`. The complete lexical function body is matched to
one CFG suite. CFG query statuses are not used as authorization.

## Conditions still required by the caller

Every statement certificate carries the same typed conditions:

- target Python runtime matches the source semantics;
- resource failures are unobserved;
- asynchronous interruption is unobserved;
- frame and local-binding timing is unobserved;
- reference-count and finalizer observations are unobserved.

The report also names the applicable source preconditions for ordinary function
locals and no external namespace mutation. These conditions remain explicit Q
inputs. The CFG's `MAY_RAISE` routes are preserved: this report does not turn
arithmetic, allocation, interruption or control-flow failures into impossible
events.

The allowed statement forms have no user dispatch, RNG, autograd, hooks,
callbacks, external I/O or ordered external effects. The evaluator's constant
result establishes only builtin type/content and bounded proof lineage; it does
not certify whole-statement effects, resource totality, movement legality,
consumer closure outside the matched function, or profitability.
