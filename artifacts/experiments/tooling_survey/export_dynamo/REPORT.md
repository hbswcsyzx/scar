# PyTorch export / Dynamo / AOTAutograd integration survey

Date: 2026-10-16. **Research and bounded CPU observations; no SCAR integration implemented.**
Recommendation: reuse PyTorch's existing tensor graph, signatures, operator schemas,
functionalization and differentiation. SCAR should supply the verified connections
between these subgraphs and the encompassing Python program, rather than reproduce
PyTorch's compiler internals or replace its backend.

## 1. Reproducibility and version boundary

- Interpreter: CPython 3.14.7, conda-forge; environment `lewm`.
- Installed torch: **2.13.0+cu132**, build commit
  `cf30153c4c131c8164ee7798e5022d810682e2cb`.
- Installed source root:
  `/home/zyf/miniconda3/envs/lewm/lib/python3.14/site-packages/torch`.
- Online `stable` redirects to **2.14**; `main` is another moving target. The
  attempted `/docs/2.13/...` pages yielded empty/inaccessible browsing results.
  The matching official [build-commit export source](https://github.com/pytorch/pytorch/blob/cf30153c4c131c8164ee7798e5022d810682e2cb/torch/export/__init__.py)
  is accessible. Local API/source and observations govern the 2.13 conclusions.
- Local `export` signature defaults to **strict=False**. Some online explanatory
  prose still says strict is default; do not use that prose to configure capture.
- No applicable AGENTS.md was found in this worktree or its ancestor directories.
  No installs/upgrades, GPU work, workload execution, custom backend or SCAR import.
- This directory is the only write destination. Existing tracked changes belong
  to concurrent owners; this survey did not edit product/tests/shared docs.

Command, from `/tmp/scar-structured-model-280qf4mi`:

```bash
PYTHONDONTWRITEBYTECODE=1 CUDA_VISIBLE_DEVICES='' OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  /home/zyf/miniconda3/envs/lewm/bin/python \
  artifacts/experiments/tooling_survey/export_dynamo/probe.py \
  > artifacts/experiments/tooling_survey/export_dynamo/probe.log 2>&1
```

Final run: exit 0; **9 probe groups completed, 0 harness errors**, body wall
**3.879678 s** excluding import/startup. This is not a performance benchmark or
SCAR acceptance gate. PASS means the observation routine completed; deliberate
Unsupported/guard/alias rejections are retained as results, not hidden failures.
The initial serializer failed on SymInt and is preserved in `probe.initial.log`/
`results.initial.json`; it was fixed by encoding symbolic metadata explicitly.
A second run exposed shared exported state between comparison modules; its
`pre_isolation` files remain. Final comparisons deep-copy module state separately.

## 2. What is already provided, and what it proves

| Provider | Reusable result | Scope / important limit |
| --- | --- | --- |
| `torch.export.export` | FX/ATen graph; lifted params, buffers, constants and inputs; pytree call spec; constrained symbolic dimensions | A captured module forward under recorded specialization. Not the loading-to-saving Python program. |
| `ExportGraphSignature` | Typed input/output roles and mutation/gradient targets | Stage-sensitive: raw training graph can retain mutation inside operators, so USER_OUTPUT-only does not imply no mutation. |
| `run_decompositions({})` | Functionalized export while retaining more ATen operators; explicit mutation outputs | Keep the epilogue that applies mutation and the original alias/lifetime boundary. Graph functionalization is not whole-function purity. |
| `run_decompositions(None)` | Existing Core ATen decomposition machinery | Select only when analysis needs it; flattening/decomposition can weaken convenient source hierarchy. No need to reimplement ATen lowering. |
| Dynamo / `torch._dynamo.explain` | Captured graph fragments, guards and graph-break reasons/source stacks | A compilation diagnostic, not the complete eager execution graph between fragments. Private API and effectful execution. |
| AOTAutograd | Forward/backward and joint tensor graphs; lifted inputs, gradient routing, mutation/alias metadata | Internal APIs are version-sensitive; a joint loss graph is not the optimizer, arbitrary autograd hooks or all host control. |
| `torch.func.functionalize` | Tested existing mutation/view rewrites and input write-back | Not a general Python state transform; exported numerical behavior does not establish Python identity/alias equivalence. |
| ATen operator schemas | Formal argument layout, mutable/alias annotations; typed operator overload | Reuse rather than hand-listing tensor mutations; schema is not complete external-effect/exception/readiness evidence. |

The official export overview distinguishes training IR from functional inference
IR, and limits export to supported tensor computation. These distinctions agree
with the local observations; the generic API/docstring word “functional” alone
is insufficient to identify the actual graph stage.
[Export overview, 2.14](https://docs.pytorch.org/docs/stable/export.html).

### 2.1 Input/output signatures and mutable state

Local `torch/export/graph_signature.py:81,121,166` has InputKind PARAMETER,
BUFFER, USER_INPUT, CONSTANT_TENSOR, CUSTOM_OBJ and TOKEN; OutputKind includes
BUFFER_MUTATION, PARAMETER_MUTATION, USER_INPUT_MUTATION and gradient roles.
Import the role and target **with its containing module instance/capture**:
`target='b'` is a qualified attribute route, not a globally unique StateLocation.
Lifted constants are capture-relative facts, not proof that their original Python
sources or referenced contents are invariant across program executions.

The raw mutation probe graph has two `aten.add_` nodes and three USER_OUTPUTs.
Its decomposed graph has BUFFER_MUTATION(b), USER_INPUT_MUTATION(x), then the
three outputs; raw and decomposed module executions both produce x=1, b=2 and
first output=3 after independent state initialization. The parameter probe under
`torch.no_grad()` yields PARAMETER_MUTATION(p) after decomposition.
**Do not reconstruct mutation solely from output_specs on a raw training graph.**

### 2.2 Aliasing is a separate contract

The mutation fixture returns both x and x.view(-1). Raw execution reports
`output2 is x=True` and view/input alias=True. Decomposed execution still returns
x by identity, but view/input alias=False in this installed build. Public
functionalize tests also copy the changed content back while returned view/input
alias=False. `remove='mutations_and_views'` emits view_copy, and both modes keep
an ending copy_ for input write-back. These observations forbid inferring original
Python alias relations from a standalone functional graph.

For two aliased actual inputs with one mutated, raw export succeeds but
`run_decompositions({})` fails in this fixture with `AssertionError: expected
compiled_fn to be GraphModule, got <class 'function'>`. This is one observed
unsupported/error path, not proof that all aliased-input models are unsupported.

Existing AOT `OutputAliasInfo` distinguishes is_input, alias_of_input and several
intermediate-base forms, with base_idx; InputAliasInfo distinguishes data,
metadata and storage mutation. `ViewAndMutationMeta` also describes intermediate
bases and wrapper behavior. Reuse its established logic through a version adapter,
but do not treat internal metadata as a stable public all-program alias oracle.
[Official 2.13 AOT schema](https://github.com/pytorch/pytorch/blob/v2.13.0/torch/_functorch/_aot_autograd/schemas.py).

Official functionalize documentation expressly describes input write-back and
limitations around nonlocal state, overlapping as_strided and direct autograd
calls. This supports preserving a boundary adapter, not dropping state edges.
[functionalize, 2.14](https://docs.pytorch.org/docs/2.14/generated/torch.func.functionalize.html).

### 2.3 Guards, specialization and ordinary Python effects

The guard fixture exports with `3 <= batch <= 8` and flag=True: batch=5 executes;
batch=2 and flag=False each fail an exported-module guard. Dynamo explain returns
19 guard records for its two fragments, covering tensor/environment properties.
Guards establish conditions for selecting a compiled specialization, **not**
purity, input-content invariance, no RNG, no finalizers or safe result caching.
[Dynamo guard model](https://docs.pytorch.org/docs/2.14/user_guide/torch_compiler/torch.compiler_dynamo_overview.html).

Non-strict probe: capture executes `SIDE.append` once. Exported module execution
adds no event; ordinary eager execution adds another. Changing global SCALE from
2 to 5 after capture leaves exported result=[2,2], while eager result=[5,5].
This shows trace-time Python execution and capture-relative specialization; it
is not evidence that Python side effects/global dependencies were preserved in
FX. Never run an arbitrary live program capture assuming it is observational.
Strict mode adds Dynamo's Python checks but does not turn a tensor graph into a
complete model of globals, exceptions, frames or external interactions.

### 2.4 Control, source provenance and hierarchy

The ordinary `if x.sum() > 0` fixture raises Unsupported under strict export.
Native `torch.cond` and `torch.while_loop` fixtures export higher-order nodes with
branch/condition/body GraphModules. Thus reuse existing structured tensor control
when present. Do not claim export automatically converts arbitrary Python loops,
try/finally, generators or video I/O into those nodes; SCAR should not require a
user rewrite merely to claim whole-source discovery.

`preserve_module_call_signature=('child',)` retains nested dict I/O metadata;
`torch.export.unflatten` reconstructs a `child` module in this fixture. Call nodes
have stack_trace, nn_module_stack, source_fn_stack and FakeTensor val metadata.
Use those as provenance candidates into SCAR's source snapshots, not proof of a
specific dynamic call/argument occurrence. Decomposition/inlining is many-to-many,
and a module path is not a runtime object identity.
[Export IR source metadata](https://docs.pytorch.org/docs/2.14/user_guide/torch_compiler/export/ir_spec.html).

The Dynamo graph-break fixture yields **2 graphs, 1 break**. Its gap remains
ordinary Python even though each tensor fragment is usable. ExplainOutput is a
diagnostic API; its aggregate guard collection is not already a verified per-edge
SCAR model. `explain` executes the function and resets Dynamo caches, so isolate
it from an application's ongoing compilation state.

### 2.5 AOTAutograd is usable without building a backend

The installed private `aot_export_module(..., trace_joint=True,
output_loss_index=0)` returns a functional joint FX graph plus GraphSignature.
For loss=sum((p*x)^2), p=[1,1], x=[2,3], executing the graph returns loss=13,
parameter gradient=[8,18], input gradient=[4,6]; signature maps both gradient
outputs correctly. This probe added no compiler backend.

Local `aot_autograd.py:1538` documents restrictions on metadata mutation, aliasing
mutated inputs and loss/output requirements. Its traditional restrictions must
not be extrapolated to every newer public export path (the parameter-mutation
export probe succeeds). Pin the precise API/stage, and report unsupported cases.
Official documentation confirms AOTAutograd's forward/backward graph role.
[AOTAutograd integration](https://docs.pytorch.org/docs/2.14/user_guide/torch_compiler/torch.compiler_custom_backends.html).

## 3. Proposed SCAR reuse boundary: import once, preserve the host model

No new IR is recommended. Translate provider facts into the existing canonical
Operation/Value/Use/state/Region/resource interfaces, retaining the original
provider artifact and a versioned correspondence:

1. **Capture identity and envelope:** torch version/build, source/code snapshot,
   strictness, exact API/stage, module-state binding, input pytree and specialization,
   decomposition settings, guards/constraints, supported/failed region coverage.
   An export name or process-local FX node name is insufficient identity.
2. **Data flow:** preserve ordered args/kwargs **occurrences** from each FX node.
   Do not use only `all_input_nodes` or a set of dependencies: `f(x,x)` has two
   argument positions even when both refer to one node. Expand nested HOP graphs
   through their actual interfaces; flattening must not lose condition semantics.
3. **State boundary:** link lifted parameter/buffer/user-input roles to canonical
   reference/location versions; link every mutation output to its matching input
   and write-back. Preserve overlap/alias and coarse-world dependencies until
   enough evidence permits refinement. Keep functional value lineage distinct
   from original object identity and physical Storage/materialization.
4. **Source and execution correspondence:** use stack/module metadata for indexed
   source candidates, then SCAR's actual call/environment/ordered-use evidence for
   occurrence bindings. Module call metadata alone cannot prove actual→formal.
5. **Failures and conditions:** retain graph breaks, missing operators/fake kernels,
   specialization rejection and uncovered code as explicit boundaries. Do not
   lower an export failure into a pure opaque node or count it as internal coverage.

These are narrow import/verification responsibilities, not replacement compiler
passes. Prefer public export/signatures/serialization; isolate private Dynamo/AOT
metadata behind version-pinned read adapters and reproducible compatibility cases.
Retain richer pre-decomposition provenance when importing a lower-level graph.
No need to introduce an optimizer/backend to inspect an ExportedProgram.

## 4. Whole-program connections SCAR still owns

- Entry/import/definition-time defaults/decorators/model loading, Python binding
  and function environment, exceptions/cleanup/generator and callback protocols.
- Actual host call→captured region→return/state links, including binding failures
  before entry, graph-break execution and multiple invocations of the same module.
- File/codec/video outputs, RNG/environment state, lifetime/escape/finalizers,
  process/thread interactions and external observable roots.
- Device enqueue versus completion/visibility, resource identity and versions.
  Tensor device metadata is not GPU readiness; **no GPU behavior was tested here**.
- Contract and evidence needed to remove/reuse computation, including content,
  alias, state, exceptions and ordering. A functional ATen fragment plus satisfied
  guards does not establish that repeated calls are cacheable.

Integration acceptance should automatically import a small real raw-source tensor
region, preserve mutation/alias boundaries and both actual positions of `f(x,x)`,
then reject reuse after buffer/input mutation or a violated specialization. A
Python effect between two fragments must remain connected. This is a proposed
future gate; the present deliverable is research only, not a workload graph.

## 5. Evidence index

- `probe.py`, `probe.log`, `results.json`: exact source, output and full graph/
  signature/guard/metadata observations, including expected errors.
- `results.initial.json`, `probe.initial.log`: original SymInt serialization issue.
- `results.pre_isolation.json`, `probe.pre_isolation.log`: previous shared-state
  comparison, retained to explain the final isolated comparison.
- `source_manifest.json`: precise installed source paths/hashes/line anchors and
  official primary URLs; `SHA256SUMS` binds this final research bundle.

This is nine bounded CPU observations plus source/document review, not exhaustive
operator/control/autograd coverage. No LeWM-specific rule, detector, manual
workload graph, new backend or runtime capture mechanism was added.
