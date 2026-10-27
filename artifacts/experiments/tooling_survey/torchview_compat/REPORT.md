# torchview 0.2.7 CPU probe

## Scope and setup

This is a runtime check of the **PyPI torchview 0.2.7 wheel**, not a test of the upstream `main` commit named in the existing survey. The wheel was downloaded to a temporary directory, SHA-256 checked against the PyPI JSON record, unpacked, and imported through `PYTHONPATH`. The `graphviz` Python wheel was handled the same way. Neither package was installed into `lewm`; the temporary third-party files were removed after the probe.

The runtime was Python 3.14.7 and PyTorch 2.13.0+cu132. Each `draw_graph` call used `device="cpu"`, `save_graph=False`; the probe did not call CUDA APIs, `dot`, Graphviz `render`, or replay a captured graph. Five captures (the nested case ran once folded and once expanded) all returned successfully. Full bounded node/edge summaries and state observations are in `torchview_probe.json`; code and wheel/source hashes are in `SOURCE_MANIFEST.json`.

## Observed

- **Repeated input `x + x`:** `FunctionNode("add")` reports two ordered input-shape entries, `[[2], [2]]`, but has one unique parent TensorNode. The raw Node parent/child containers are ordered sets, so they represent adjacency without two distinct operand occurrences. The display `ComputationGraph.edge_list` has two edges for the visible operation/output path in this configuration; it is a filtered visualization edge list, not a positional-use table.
- **View followed by in-place update:** the graph contains `FunctionNode("view")` then `FunctionNode("add_")`. The original input changed, its tensor version advanced from 0 to 1, and the returned view shared its storage. The graph records the named operations, shapes, and Node lineage; the inspected Node fields contain no storage identity or alias edge. The probe model deliberately retained its returned tensor only to measure this result; that retention belongs to the fixture.
- **Nested module fold/expand:** both captures have the same 10 Node objects and 4 raw display edges; the expanded capture adds one Graphviz subgraph cluster. Each run recorded one outer and one inner forward event. Thus `expand_nested` changed presentation here, not which forward calls ran or the in-memory node count.
- **Capture side effects:** the counter module's Python counter changed 0→1 and its registered buffer changed 0→1 during capture. The graph contains the visible `x + 1` operation but no node for the Python increment or buffer `add_`. This is a direct example where graph omission does not mean the forward was effect-free.
- **Module mode:** the nested sample began with parent `training=True`, child `training=False`. After capture both were `True`. The wheel runs the forward in eval mode by default and its cleanup calls `model.train(saved_model_mode)`, which recursively reapplies the parent mode to children; the child’s original mixed mode is not restored.
- The observed `ComputationGraph` contains `root_container`, `node_hierarchy`, `edge_list`, and a Graphviz object. Its Node objects expose useful in-memory data, including parents/children and input/output shapes. The tested `TensorNode` fields include `tensor_id` and `tensor_shape`; `ModuleNode`/`FunctionNode` store `compute_unit_id` integers and shape lists. In the inspected wheel source these are IDs and metadata, not fields holding the original module or activation Tensor object. Nodes do not expose a code object or source span.
- `torch.nn.Module.__call__` and `torch.rand` were restored after each capture. The wheel also temporarily wraps a list of `torch` tensor factory functions during the forward.

## Inferred reuse boundary

From those observations, `torchview` is more informative than a module-only summary: this wheel exposes module, function, and tensor Node kinds and nested hierarchy. It is useful as a CPU/shape/dataflow visualization cross-check. Its in-memory objects are machine-readable, but their schema is library-specific and unversioned; `edge_list` is generated for display and can omit structural edges, while the Node adjacency deduplicates parents/children. `input_shape` happens to retain input shape occurrences in order but does not bind each shape entry to a distinct input edge or value reference. It cannot serve as a positional-use or source-semantic graph contract.

The probe also confirms that a torchview run executes the model and can mutate Python state, buffers, and mode. Any reuse must treat capture as an effectful forward pass. Missing nodes cannot establish purity, unexecuted control paths, state preservation, or alias absence.

## Evidence limits

**Observed:** the five small cases above on Python 3.14.7 / PyTorch 2.13.0 CPU using the PyPI 0.2.7 wheel. The source hashes, exact wheel URL/SHA, command, and unchanged conda package-list digest are recorded in `SOURCE_MANIFEST.json`.

**Source-derived for this wheel:** `draw_graph` delegates to `ComputationGraph`, uses `RecorderTensor` plus a temporary `Module.__call__` wrapper, calls `.to(device)`, defaults to eval, runs under `torch.no_grad()`, and restores by calling `.train(saved_model_mode)`. This agrees with the mode and side-effect observations above.

**Not verified:** multi-output positional output mapping, arbitrary kwargs/container inputs, GPU execution, native Graphviz rendering, large networks, exception paths, all tensor factory wrappers, or equivalence with upstream commit `241d22b5cdeb2c227acee2c85611f0442f15c091`. No LeWM source or workload was accessed.
