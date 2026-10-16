# PyTorch graph tooling survey: torchview, torchviz, and torch.fx

**Scope.** Read-only reuse survey; no SCAR implementation or completeness claim. The installed environment is PyTorch 2.13.0+cu132 on Python 3.14.7. torchview and torchviz are not installed, so those tools were inspected in their original repositories and not executed. No packages were installed, no LeWM code or workload was touched, and the only runtime experiment was a small CPU-only torch.fx probe.

## Versions and evidence

| Tool | Source/version pinned for the survey | Local availability | Evidence |
|---|---|---|---|
| PyTorch FX | Installed torch 2.13.0+cu132, Python 3.14.7; source tag v2.13.0. | Installed; CPU probe ran. | Installed source, [probe script](fx_probe.py), [probe output](fx_probe.json), [official FX docs](https://docs.pytorch.org/docs/stable/fx.html). |
| torchview | Upstream main commit [241d22b5cdeb2c227acee2c85611f0442f15c091](https://github.com/mert-kurttutan/torchview/commit/241d22b5cdeb2c227acee2c85611f0442f15c091); pyproject reports 0.2.7. | Not installed; source review only. | [README](https://github.com/mert-kurttutan/torchview/blob/241d22b5cdeb2c227acee2c85611f0442f15c091/README.md), [torchview.py](https://github.com/mert-kurttutan/torchview/blob/241d22b5cdeb2c227acee2c85611f0442f15c091/src/torchview/torchview.py), [recorder_tensor.py](https://github.com/mert-kurttutan/torchview/blob/241d22b5cdeb2c227acee2c85611f0442f15c091/src/torchview/recorder_tensor.py), [base_node.py](https://github.com/mert-kurttutan/torchview/blob/241d22b5cdeb2c227acee2c85611f0442f15c091/src/torchview/computation_node/base_node.py), [compute_node.py](https://github.com/mert-kurttutan/torchview/blob/241d22b5cdeb2c227acee2c85611f0442f15c091/src/torchview/computation_node/compute_node.py), [computation_graph.py](https://github.com/mert-kurttutan/torchview/blob/241d22b5cdeb2c227acee2c85611f0442f15c091/src/torchview/computation_graph.py). |
| torchviz | Upstream master commit [5cf04c13e601366f6b9cf5939b5af5144d55b887](https://github.com/szagoruyko/pytorchviz/commit/5cf04c13e601366f6b9cf5939b5af5144d55b887); setup.py reports 0.0.2. | Not installed; source review only. | [README](https://github.com/szagoruyko/pytorchviz/blob/5cf04c13e601366f6b9cf5939b5af5144d55b887/README.md), [dot.py](https://github.com/szagoruyko/pytorchviz/blob/5cf04c13e601366f6b9cf5939b5af5144d55b887/torchviz/dot.py), [setup.py](https://github.com/szagoruyko/pytorchviz/blob/5cf04c13e601366f6b9cf5939b5af5144d55b887/setup.py). |

Pinned upstream SHAs were read from GitHub on 2026-10-16. The torchview and torchviz conclusions are source inspection, not local compatibility tests. Current stable PyTorch docs may describe a newer release than installed 2.13; local 2.13 behavior is called out separately.

## What each graph means

| Tool/API | Nodes | Edges | Expansion and source mapping | Machine-readable form |
|---|---|---|---|---|
| <code>torchview.draw_graph</code> | Internal node kinds are TensorNode, FunctionNode, and ModuleNode: tensors, tensor operations, and modules. The README lists tensor operations, nested/recursive modules, rolling/unrolling, and input/output shapes. This is more than a module summary. | Forward tensor lineage and module nesting/attachment. Tensor ops are intercepted with RecorderTensor.__torch_function__; Module calls are wrapped. This is a forward tensor-flow graph, not a Python CFG. Its parent/child NodeContainer is an ordered set, so duplicate operand positions are not separate edges. | Nested module calls are recorded during forward. depth, roll, hide_module_functions, and hide_inner_tensors change graph traversal or display. Nodes identify functions/modules by name/type/object, optionally stringify attributes, but have no definition identity, source span, condition, or binding provenance. | ComputationGraph exposes root_container, node_hierarchy, edge_list, and a Graphviz Digraph. Useful objects exist, but retain Python/module/tensor objects and are not a neutral versioned interchange schema. |
| <code>torchviz.make_dot</code> | Autograd grad_fn objects, leaf/output tensors, optional saved tensors/attributes, and a view output’s base tensor. | Traverses grad_fn.next_functions backwards toward the result. Optional saved-tensor links and a specific output _base view link are included. It is gradient/autograd connectivity, not general forward dataflow. | It does not trace Python functions or modules. The caller computes the output before make_dot. An output with little/no autograd history provides little beyond its tensor node. | Returns Graphviz Digraph text with labels and runtime id(...) names. Useful for visualization/debugging, not typed executable-program IR. |
| <code>torch.fx.symbolic_trace</code> | placeholder, get_attr, call_function, call_method, call_module, output. A node has op, target, args, kwargs, meta; GraphModule also emits Python code. | A directed value-use graph: Node references appear recursively in args/kwargs. Those fields preserve occurrence order and repeated use. Node.users is a unique consumer map, not an occurrence list. | Symbolically executes Python with Proxy values. Ordinary Python helpers are usually traced through; torch.fx.wrap makes a function a call_function leaf. The default tracer treats torch.nn modules (except Sequential) as leaves and emits call_module; custom modules may be traced through or forced to be leaves with a custom Tracer. The default local trace had module-stack metadata for call_module but no stack trace. A custom Tracer can enable stack traces; these are optional runtime hints, not verified source witnesses. | Graph/Node objects and GraphModule.code are a strong machine-readable start for operator/value uses. Targets may be Python callables, get_attr refers into module state, and meta is extensible. This is not a language-neutral effects schema or stable semantic interchange contract. |
| <code>torch.fx.experimental.proxy_tensor.make_fx</code> | Dispatch-level FX nodes for operators executed on supplied examples, often aten targets, plus inputs/output. | Operator value uses in FX args/kwargs; often lower-level names than symbolic_trace. | Runs the function with example values under proxy-tensor/dispatcher capture. The local 2.13 probe called Python once and torch.rand_like advanced the real CPU RNG while an aten.rand_like node was emitted. A data-dependent branch raised under default error behavior for both positive and negative sample inputs. record_stack_traces=True populated no stack_trace in this local build, despite current official docs describing the option. | Same FX graph objects/code generation. The official [make_fx API](https://docs.pytorch.org/docs/stable/generated/torch.fx.experimental.proxy_tensor.make_fx.html) describes operations performed during one execution; that is not whole-program coverage. |

The official [FX overview and Node reference](https://docs.pytorch.org/docs/stable/fx.html) describe node kinds, Proxy tracing, graph inspection, and code generation. The torchview README/source above document its tensor/function/module graph and implementation. The torchviz README/source above document its autograd graph and optional saved variables.

## Concrete local FX observations

Command:

~~~bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
python /tmp/scar-structured-model-280qf4mi/artifacts/experiments/tooling_survey/visual_fx/fx_probe.py
~~~

The probe used small CPU tensors. Exact output is in <code>fx_probe.json</code>.

- <code>x + x</code> is one call_function whose args contain the same placeholder twice: two uses, one unique consumer. An adapter must walk every argument occurrence; users alone loses multiplicity.
- <code>x + x</code> followed by <code>nn.ReLU</code> became call_function(operator.add) and call_module("relu"), confirming the graph is not module-only.
- One ordinary helper was inlined into sin/add operations. A helper marked with torch.fx.wrap remained one call_function with meta[is_wrapped].
- A custom tracer forced a child module to be a leaf. Parent.forward ran once during tracing; the child.forward did not run and became call_module. A leaf call in the FX graph is not proof that its body ran while tracing.
- A Python counter in root.forward incremented during symbolic_trace but was absent from the graph; graph-module replay did not increment it. A registered buffer mutated by counter.add_(1) also changed 0→1 during trace, but the graph contained only x+1 and replay left the buffer unchanged.
- <code>torch.rand(2)</code> with no Proxy input ran during symbolic_trace, advanced RNG, and became get_attr('_tensor_constant0'). GraphModule replay did not advance RNG. <code>torch.rand_like(x)</code> with a Proxy input became call_function and did not draw RNG during symbolic_trace. Do not treat all RNG paths alike.
- <code>symbolic_trace</code> of <code>if x.sum() &gt; 0</code> raised TraceError. A static <code>range(3)</code> loop became three add nodes: an unrolled body, no loop/backedge.
- ShapeProp added shape/dtype meta to nodes. It interprets/executes the graph on supplied arguments, so with real inputs it is another effectful execution for stateful nodes. It gives value metadata, not effect proof.
- The local default symbolic trace had no stack_trace. Custom Tracer with record_stack_traces=True recorded file/line for op nodes. Local make_fx(..., record_stack_traces=True) added no stack traces. Source metadata availability must be checked per version and capture path.

These are observed only for installed PyTorch 2.13.0 CPU probes. They are not torchview/torchviz or LeWM runtime tests.

## State, alias, RNG, control, and IO boundaries

### Data and alias

- FX is best for ordered operator argument occurrences: args/kwargs preserve each use. These are graph values, not general Python object identity or tensor-storage alias analysis. get_attr and an in-place-looking call such as add_ reveal access/target spelling, not state versions, mutation footprints, or alias classes.
- torchview records tensor ancestry and shapes. TensorNode stores a tensor_id and recorder history is updated for in-place operations, but parent/child nodes are uniqued. The source does not model general storage/view aliases; compare torchviz’s specific output _base view link.
- torchviz gradient edges answer what autograd functions contribute to an output gradient. They do not enumerate every forward operand or dependency. Saved tensors are optional autograd internals.

### Control and dynamic calls

- Standard symbolic FX does not represent arbitrary Proxy-dependent if/while/iteration: Proxy boolean conversion and iteration raise TraceError. Static Python control executes while tracing, so branches choose a path and loops can unroll; concrete_args may specialize inputs. wrap/custom leaf modules preserve a call boundary, not the hidden body/control semantics.
- make_fx captures lower-level ops for one supplied run; the local probe rejected a data-dependent branch. Its local source metadata differed from current stable docs.
- torchview executes a concrete/synthetic-input forward and records intercepted calls. Its node model has no condition/branch nodes, so a data-dependent branch contributes the operations of the executed path only.
- torchviz follows autograd edges from a supplied result; it has no Python call graph or control graph.

### State, RNG, side effects

- symbolic_trace executes root Python. Traced-through child/helper code can mutate globals, buffers, files, object state, or RNG. Failures do not roll these effects back. Leaf call_module bodies are emitted without running forward during tracing. FX does not automatically classify side effects from pure calls.
- The probe demonstrates two FX RNG cases: a no-Proxy random tensor becomes a concrete graph attribute; a Proxy-dependent rand_like remains a call. Neither graph has typed RNG-state effects.
- make_fx uses dispatch capture while running a function on the example arguments; the probe consumed CPU RNG. Captured targets do not specify complete resource effects or guarantee identical behavior under other tracing/decomposition settings.
- torchview calls model.to(device), temporarily changes train/eval mode, and executes forward under torch.no_grad(). It patches torch.nn.Module.__call__ plus a list of tensor-factory functions. Recorder restores patched call/factory functions, but the forward may alter buffers and other state. Its finally clause calls model.train(saved_model_mode), which does not restore buffers and can erase intentionally mixed child training flags. Device moves, hooks/callbacks, RNG, IO, and mutations are real effects. Its tracing run needs a controlled environment.
- torchviz consumes a precomputed result and reads its autograd graph. make_dot does not invoke forward, though show_attrs/show_saved inspects saved runtime attributes.
- None records arbitrary Python IO/global effects as typed edges. A missing graph edge is not proof of no dependency or purity.

### Source mapping and exports

- FX may expose nn_module_stack or Python stack traces, depending on tracer/mode. They are source hints, not code/source identity witnesses. Default trace had no stack in the local probe; wrapped helpers and leaf module bodies can be hidden intentionally.
- torchview uses module/function names and optional stringified attrs; its inspected node schema has no source span/code identity.
- torchviz uses autograd labels and runtime object IDs; no source locator.
- FX provides the best in-memory graph interface. Node.normalized_arguments() can normalize some calls, but the official Node docs say positional-only and varargs parameters are unsupported.

## Reuse recommendation for SCAR

1. **Use FX as an optional PyTorch model/operator/value-use candidate adapter.** Walk Graph.nodes and recursively enumerate every Node occurrence in args/kwargs, preserving order and duplicates. Retain op, target identity/spelling, call argument shape, get_attr, module stack, and any stack_trace as separate evidence. A location stays a hint until matched to current source/code and independently replayed. This can supply useful tensor model structure without creating a second PyTorch operator tracer.
2. **Keep FX symbolic and execution captures distinct.** symbolic_trace proxies Python and can omit effects or skip leaf bodies. make_fx records operators under concrete execution but has one input path and can execute effects/RNG. Record capture mode, version, sample/guards, and errors. Missing nodes never imply no effect.
3. **Use torchview as a visual/cross-check for module nesting, tensor operations, and shapes.** It is more detailed than module-only, but its unique-edge model loses argument multiplicity and it has no source/CFG/state protocol. Avoid using its graph as SCAR IR. It executes forward and globally patches Module.__call__ and selected factories; any future run should be explicit, isolated, bounded, and use disposable state.
4. **Use torchviz for autograd/gradient-flow diagnostics only.** It can independently show gradient edges and selected saved/view relations. It cannot supply source calls, Python argument binding/defaults, effects, RNG, control, IO, or general tensor identity.
5. **Keep source discovery, whole-program control/state/effects, and replay in SCAR.** These tools provide candidate facts and visual audits, not proof of source correspondence, execution identity, complete CFG, aliasing, resource versions, or absence of hidden effects.

## Probe files

- [fx_probe.py](fx_probe.py): CPU-only local reproducer.
- [fx_probe.json](fx_probe.json): full machine-readable observations, no tensor values.

