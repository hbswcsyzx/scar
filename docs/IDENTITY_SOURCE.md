# Identity source adapter

The identity source adapter establishes one narrow link for a loaded ordinary
Python function:

```text
required parameter slots
  -> separate source READ / BindingUse occurrences
  -> one replayed `is` or `is not` primitive
  -> that primitive's SG output slot
  -> the SG Return operation
  -> the function return slot
```

It supports only a synchronous `FunctionType` whose complete body is one
undecorated `return <Name> is/is not <Name>` statement. Each name must be a
required positional or keyword-only parameter. Repeating the same parameter is
allowed, but its two reads and bytecode subindices remain separate.

## API

```python
from scar.analysis.identity_source_v2 import (
    IdentityFunctionSource,
    prepare_identity_source,
    validate_identity_source,
)

source = prepare_identity_source(semantic, source_semantics, function)
source.assert_valid(semantic, source_semantics, function)
```

`source_texts` can provide the decoded source snapshots for all fingerprinted
module paths. When omitted, the adapter reads the current files. A
`ControlFlowBudget` is the single caller-supplied ceiling. `to_dict()` and
`from_dict()` use the strict record codec and rederive the evidence against the
supplied graphs and callable.

The record includes the fixed `PrimitiveSemanticsCertificate`, an exact
`CodeSourceWitness`, two `SourceIdentityOperand` occurrences, a
`ReturnValueUse`, and the normalized meaningful bytecode instructions.
`SourceIdentityOperand.slot` is the required parameter's input slot;
`read_output_slot` is the distinct slot produced by that AST `READ` and
consumed by the identity operation. `load_offset` and `load_subindex` join the
source occurrence to the statically checked instruction sequence.

The code witness uses `reproduce_code_source_witness`, which shares
correspondence's source fingerprinting, recursive code-constant walk, compile
contexts and exact `marshal.dumps(CodeType)` SHA256 policy. A matching compile
context is a reproducible hypothesis; it does not attest the loader's original
settings. Code hashes are not normalized to create a match.

## Accepted bytecode

The adapter accepts the observed CPython 3.14 dual borrowed-local load. The
body must compile to exactly `RESUME`, that fused load, one polarity-matching
`IS_OP`, and `RETURN_VALUE`. The fused load retains one instruction offset
with operand subindices 0 and 1. Unknown interpreter versions, opcodes, extra
instructions, or local-name mappings are rejected.

## Evidence boundary

The certificate covers the identity primitive's fixed operator semantics.
The operand and return records connect this primitive through one source and
SG path; they do not declare the function pure, prove external callers are
closed, or establish that the operands have stable contents. The adapter does
not execute the target or import its module. A validator checks that the
callable still holds the exact `__code__` object captured at preparation and
then replays source, overlay, primitive semantics, code witness and bytecode.
The adapter never reads `function.__annotations__`: on CPython 3.14 that access
can execute a lazy annotation resolver. It rejects a non-`None`
`function.__annotate__` resolver without invoking it.

This source evidence alone does not prove a runtime call occurred. A capture
must separately observe the actual invocation arguments, load/operator/return
events and returned bool, and retain one result occurrence for that invocation.
Those observations describe the captured path only. Future calls need an
independent guarded plan with an event-time validity check and an original
computation fallback. This adapter does not supply that plan or approve a
positive REUSE delta.
