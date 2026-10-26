# Observed Python targets and receiver ports

`install_operands(recorder, python_targets=True)` explicitly enables
`PYTHON_CALL_TARGETS_V2` and `OBSERVED_PYTHON_CALLEE_SCOPE_V1` on fixed CPython
3.14.7. Default capture, the old operand/frame wire, ArgumentRoute and the
source-port v1 model retain their contracts. This is metadata for modeling,
not performance sampling.

The new sidecar records every original attempt. Exact functions retain their
function/code/layout; exact MethodType retains `__func__`, code and an independent
receiver. Observed exact Python callee code may enter the existing frame recorder
outside the project, bounded by the original code/event/reference limits. The
sidecar binds all five exact original frame/operand artifacts; the normal reader
checks their receipts, direct caller/site/code/entry and the full denominator.
Native builtins/wrappers are explicit boundaries; other callables remain
unclassified. It never probes an arbitrary object's `__call__` or invokes it.

CPython expands methods before monitoring CALL. The first receiver rule therefore
also recognizes a **conditional finite CALL ABI**: positional `CALL n`, nonvariadic
non-suspended code with n+1 parameters, no keyword-only parameters and no defaults.
Only a matching real entry whose first formal is the same live receiver completes
the relation. `NO_INTERVENING_CALL_LAYOUT_MUTATION` remains explicit. `arg0`
alone is never receiver proof. Missing weak receiver/method-owner continuity,
ambiguous/default/keyword layouts and suspended creation remain open.

`build_python_source_ports(trace=..., call_model=..., inventory=..., sources=...,
inventory_artifact=...)` reuses the same normal frame/operand scan, current code
witnesses, source call and `_Core.formal_ports`. It reads the original new sidecar
itself; a serialized model is never an owner token. Partitioned sources retain
their original namespace. A normal unpartitioned inventory requires its exact
saved artifact and receipt catalog. External entry observations do not waive the
existing source namespace/body guards.

The output is `scar.python-source-port-bindings/2`, read with
`scar.ir.program.python_call_targets.PythonSourcePortModel.loads(text)`.
`SourceReceiverPort` projects the original qualified callee Use/Value to the
original first formal. It creates no SSA value. Explicit AST argument i retains
its original Use/Value and ParameterBinding(ARGUMENT,i), and targets formal i+1.
Ordinary functions continue through `bind_call`/CandidateBinding. No receiver is
invented as a CallArgument, ValueOccurrence, Invocation or CallActivation.
The existing `link_call_operands` consumer still emits its original v1 model;
the new builder is an explicit same-normal-session API. A future full-capture
owned coordinator must forward a distinct v2 consumer, rather than silently
changing the v1 rule. No full LeWM v2 acceptance is claimed here.

The actual generic check retained 7 attempts, 5 exact entry relations, 2 receiver
ports and 3 explicit argument ports across 3 source calls. The external helper
has a real entry but no permitted source body; native len, the class construction
and a default-argument shape retain explicit boundaries. This does not establish
environment/default atomicity, reference/content identity, effects, ready/lifetime,
new method completion routes or whole-program completeness.

Primary contract: fixed [CPython 3.14.7 bytecodes.c](https://github.com/python/cpython/blob/v3.14.7/Python/bytecodes.c)
(`_MAYBE_EXPAND_METHOD`, `_MONITOR_CALL`, `_PY_FRAME_GENERAL`),
[CALL stack ABI](https://docs.python.org/3.14/library/dis.html#opcode-CALL), and
[monitoring callback arguments](https://docs.python.org/3.14/library/sys.monitoring.html#callback-function-arguments).
Actual inputs/results and prototype boundaries are in
`artifacts/experiments/python_call_targets_v2_20261026/REPORT.md`.
