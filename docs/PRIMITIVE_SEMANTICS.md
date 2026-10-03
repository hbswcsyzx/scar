# Primitive semantics: Python identity comparison

`scar.analysis.primitive_semantics_v2` records one narrowly defined fact about a
source-replayed `is` or `is not` operation. It does not establish that replacing
the expression is legal, and it does not mark an operation, expression, or
function as pure.

## Fixed rule

The rule is `python.identity_comparison`, version
`scar.primitive-semantics.v1`. It applies only to one binary comparison whose
operator is `is` or `is not`. Its certificate records the source operation,
result, and the source overlay's ordered `left` and `right` operands.

The operator itself:

- compares object identity without invoking user-defined comparison methods;
- does not inspect operand contents, access RNG state, write state, or create an
  autograd edge;
- returns one of Python's `True`/`False` boolean singletons.

Operand production is outside the certificate. For example, `make_left() is
make_right()` certifies only the identity comparison after both calls have
produced their results. It says nothing about either call's effects, failures,
RNG use, or output identity.

Equality, membership, ordering, and chained comparisons remain opaque. They
may invoke user code or conditionally evaluate later operands. The extractor
records a specific gap for these forms and never calls `__eq__` or other user
methods. The overlay tags these barriers with typed
`COMPARISON_DISPATCH` or `COMPARISON_SHORT_CIRCUIT` boundary kinds; report
classification depends on those records, not reason text.

## Scope and preconditions

Each certificate is limited to the operator itself. The report separately
records the source abstraction's caller-scoped preconditions, the analyzer's
Python runtime identity, a target-runtime compatibility requirement, and these
observation boundaries:

- debugger tracing;
- frame tracing;
- resource observation;
- exception observation.

These are scope metadata, not accepted assumptions. The rule does not claim
that operands or the containing expression are effect-free, that instrumentation
cannot observe execution, or that a source rewrite preserves surrounding
behavior. A later fixed legality ledger must decide whether its own scoped Q
accepts applicable conditions.

## Derivation and validation

`derive_primitive_semantics(semantic, source_semantics, operations=None, *,
source_texts=None, budget=...)` source-replays the overlay once per batch. With
`operations=None`, it reports modeled identity comparisons and opaque comparison
gaps. A requested unsupported operation yields a typed `PrimitiveGap` instead
of a certificate.

The strict report records semantic and source-overlay digests, rule identity,
runtime scope, source preconditions, target operations, certificates, gaps, and
bounded usage. `to_dict`/`to_json`, `from_dict`/`from_json`, and `validate`
rederive the report from caller-supplied models under a verification budget.
Stored report fields cannot raise that budget. Source replay uses current files
unless the caller explicitly supplies decoded `source_texts` for the replay.
The report retains source fingerprints and model digests, not source text; a
caller replaying a preserved snapshot must supply that snapshot again when
validating or serializing the report.

Adding `IS` and `IS_NOT` does not change the source-semantics schema. Existing
schema-v1 documents continue through the existing strict migration path; their
operation opcodes and operand order are still checked by source replay.
