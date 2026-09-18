# Constant provenance case audit

This document records a generic audit of a cross-module literal use. The
example is used to test the model; no package name or source location is part
of the analyzer's rules.

## What the current analyzer actually found

The static pass resolves an imported attribute through local source files:

```text
use expression
  -> import alias
  -> module attribute
  -> literal definition
```

For the LeWM entrypoint this produced one `ConstantProvenanceCandidate` whose
literal proof is `PROVEN`. Its value is a JSON-safe dictionary containing the
normalization mean and standard deviation. This is a real semantic fact, not a
name-based LeWM rule.

The candidate is **not** part of the ordinary `scar analyze` candidate stream.
`scar constants` is a separate report-only pass. If the candidate is passed to
the generic selector manually, the selector returns `UNKNOWN`, because two
legality obligations remain unknown and no backend is attached.

## Two transformations that must not be conflated

There are at least two different rewrites:

### Value substitution while retaining the import

```python
import package as alias
use(alias.module.CONSTANT)
```

becomes a literal use while the import remains. Package initialization and its
visible effects are preserved. The proof still needs to cover value identity,
mutability, attribute lookup behavior, monkey-patching, reloads, exceptions,
and the complete consumer contract.

### Value substitution plus import elimination

The import is removed as well. This can save package initialization, but it
must prove that every import effect is either irrelevant or explicitly
reproduced. Environment changes, logging setup, registration, import-time
exceptions, and effects reached through lazy attributes all belong to this
proof.

The current candidate uses an `import_effects_preserved` obligation that is
appropriate for the second rewrite, while its description says only that the
value may be inlinable. It therefore does not identify a concrete transform
boundary. This is a model deficiency, not evidence that the literal is
invalid.

## Runtime evidence in the example

An isolated process showed that importing the package changes process state
before the value is read: it sets environment defaults and installs logging
configuration. Accessing the lazy data attribute then imports a data package
with additional module initialization. The literal definition module itself is
syntactically pure.

This makes the conservative result for **import elimination** correct so far:
the package has visible effects that have not been sliced, reproduced, or
proven irrelevant. It does not by itself reject **value substitution while
retaining the import**.

## Missing connections in the current model

1. The static program graph has syntax and module-import edges, but the
   constant pass is an isolated report. It does not create a first-class
   value/provenance edge from the use site through the alias and lazy attribute
   access to the definition.
2. It does not compute whole-program import liveness. A package can be unused
   by one file and still be required by another reachable module.
3. It does not prove that the mutable literal object is never mutated or
   escaped. Literal content equality is weaker than object and alias
   equivalence.
4. It does not generate a transformed source region, run it, compare visible
   effects, or measure clean cost. `replacement_validated` is therefore
   correctly `UNKNOWN`.
5. It does not provide a generic constant-substitution backend. The report is
   detection evidence, not an applied optimization.

## Required generic model change

Constant opportunities should enter the optimization IR as explicit
alternatives, each with its own delta and obligations:

```text
ConstantSubstitution
    preserve import
    replace value expression

ConstantSubstitutionAndImportElimination
    remove import/lazy materialization
    preserve or reproduce required import effects
```

Both alternatives must connect the use, definition, value provenance,
consumer, import region, and effect slice. The planner can then choose a safe
lower-cost alternative or retain the original path. No package-specific rule
is needed.

