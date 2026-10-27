#!/usr/bin/env python3
"""Small CPU-only runtime probe for the PyPI torchview 0.2.7 wheel.

The wheel is unpacked under /tmp and supplied via PYTHONPATH; this script
never installs packages, renders Graphviz output, or invokes CUDA.
"""
from __future__ import annotations

import json
import pathlib
import platform
import sys
import time
from collections import Counter
from typing import Any

import torch
from torch import nn
from torchview import draw_graph
from torchview.computation_node import FunctionNode, ModuleNode, TensorNode

HERE = pathlib.Path(__file__).resolve().parent
NODE_TYPES = (TensorNode, ModuleNode, FunctionNode)


def _node_name(node: Any) -> str:
    return f"{type(node).__name__}:{node.name}"


def _hierarchy_shape(value: Any, indices: dict[int, int]) -> Any:
    if isinstance(value, NODE_TYPES):
        return {"node": indices[id(value)], "label": _node_name(value)}
    if isinstance(value, dict):
        return [
            {"key": _hierarchy_shape(key, indices), "value": _hierarchy_shape(child, indices)}
            for key, child in value.items()
        ]
    if isinstance(value, (list, tuple)):
        return [_hierarchy_shape(child, indices) for child in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return {"opaque_type": type(value).__name__}


def graph_summary(graph: Any) -> dict[str, Any]:
    """Export node/edge facts without storing tensor values or object refs."""
    nodes: list[Any] = []
    indices: dict[int, int] = {}

    def add(node: Any) -> None:
        if isinstance(node, NODE_TYPES) and id(node) not in indices:
            indices[id(node)] = len(nodes)
            nodes.append(node)

    def visit_tree(value: Any) -> None:
        if isinstance(value, NODE_TYPES):
            add(value)
        elif isinstance(value, dict):
            for key, child in value.items():
                visit_tree(key)
                visit_tree(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                visit_tree(child)

    visit_tree(graph.root_container)
    visit_tree(graph.node_hierarchy)
    cursor = 0
    while cursor < len(nodes):
        node = nodes[cursor]
        for neighbour in list(node.parents) + list(node.children):
            add(neighbour)
        cursor += 1

    tensor_tokens: dict[int, str] = {}
    callable_tokens: dict[tuple[type, int], str] = {}

    def token(table: dict[Any, str], key: Any, prefix: str) -> str:
        if key not in table:
            table[key] = f"{prefix}{len(table)}"
        return table[key]

    records = []
    for index, node in enumerate(nodes):
        record: dict[str, Any] = {
            "index": index,
            "kind": type(node).__name__,
            "name": node.name,
            "depth": node.depth,
            "parents": [indices[id(parent)] for parent in node.parents],
            "children": [indices[id(child)] for child in node.children],
        }
        if isinstance(node, TensorNode):
            record.update({
                "shape": list(node.tensor_shape),
                "is_aux": bool(node.is_aux),
                "runtime_tensor_object_token": token(tensor_tokens, node.tensor_id, "tensor-"),
            })
        else:
            record.update({
                "input_shapes_in_collected_order": [list(shape) for shape in node.input_shape],
                "output_shapes": [list(shape) for shape in node.output_shape],
                "runtime_compute_unit_token": token(
                    callable_tokens, (type(node), node.compute_unit_id), "unit-"
                ),
            })
            if isinstance(node, ModuleNode):
                record["is_container"] = bool(node.is_container)
                record["is_activation"] = bool(node.is_activation)
        records.append(record)

    graph_edges = [
        {"from": indices[id(tail)], "to": indices[id(head)]}
        for tail, head in graph.edge_list
    ]
    visible_body = list(graph.visual_graph.body)
    return {
        "node_count": len(records),
        "node_kinds": dict(sorted(Counter(row["kind"] for row in records).items())),
        "nodes": records,
        "edge_list": graph_edges,
        "edge_count": len(graph_edges),
        "hierarchy": _hierarchy_shape(graph.node_hierarchy, indices),
        "graphviz_body_line_count": len(visible_body),
        "graphviz_subgraph_line_count": sum("subgraph cluster_" in line for line in visible_body),
        "graphviz_body_serialized_as_text": True,
        "torchview_object_fields": {
            "graph": sorted(vars(graph).keys()),
            "tensor_node": sorted(vars(next(n for n in nodes if isinstance(n, TensorNode))).keys()),
            "function_node": sorted(vars(next(n for n in nodes if isinstance(n, FunctionNode))).keys()),
            "module_node": sorted(vars(next(n for n in nodes if isinstance(n, ModuleNode))).keys()),
        },
        "source_code_or_definition_field_present_on_node": False,
    }


def capture(label: str, model: nn.Module, sample: torch.Tensor, **draw_options: Any) -> dict[str, Any]:
    started = time.monotonic()
    record: dict[str, Any] = {
        "label": label,
        "requested_device": "cpu",
        "draw_options": draw_options,
        "render_requested": False,
    }
    try:
        graph = draw_graph(
            model,
            input_data=sample,
            device="cpu",
            save_graph=False,
            show_shapes=True,
            **draw_options,
        )
        record["status"] = "OK"
        record["graph"] = graph_summary(graph)
    except Exception as exc:  # keep a reproducible compatibility failure
        record["status"] = "ERROR"
        record["error"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        record["elapsed_seconds"] = time.monotonic() - started
        record["model_training_after_capture"] = bool(model.training)
        record["torch_module_call_restored"] = torch.nn.Module.__call__ is _ORIGINAL_MODULE_CALL
        record["torch_rand_restored"] = torch.rand is _ORIGINAL_TORCH_RAND
    return record


_ORIGINAL_MODULE_CALL = torch.nn.Module.__call__
_ORIGINAL_TORCH_RAND = torch.rand


class Twice(nn.Module):
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return x + x


class ViewThenInplace(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.returned: torch.Tensor | None = None

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        view = x.view(-1)
        view.add_(1)
        self.returned = view
        return view


class Inner(nn.Module):
    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self.events = events

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        self.events.append("inner")
        return torch.relu(x)


class Nested(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[str] = []
        self.inner = Inner(self.events)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        self.events.append("outer")
        return self.inner(x) + 1


class CounterAndBuffer(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.python_counter = 0
        self.register_buffer("ticks", torch.tensor(0, dtype=torch.int64))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        self.python_counter += 1
        self.ticks.add_(1)
        return x + 1


def main() -> None:
    results: dict[str, Any] = {
        "runtime": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "torch": torch.__version__,
            "torch_cuda_build_tag": torch.version.cuda,
            "execution_device": "cpu",
            "cuda_api_called_by_probe": False,
        },
        "captures": [],
    }

    twice = Twice()
    twice_x = torch.tensor([2.0, 3.0])
    results["captures"].append(capture(
        "x_plus_x", twice, twice_x,
        depth=4,
        hide_inner_tensors=False,
        hide_module_functions=False,
    ))
    results["captures"][-1]["forward_count_not_instrumented"] = True

    inplace = ViewThenInplace()
    inplace_x = torch.tensor([1.0, 2.0])
    inplace_before = inplace_x.detach().clone()
    inplace_version_before = int(inplace_x._version)
    results["captures"].append(capture(
        "view_then_inplace_add", inplace, inplace_x,
        depth=4,
        hide_inner_tensors=False,
        hide_module_functions=False,
    ))
    inplace_record = results["captures"][-1]
    returned = inplace.returned
    inplace_record["state_observation"] = {
        "input_changed": not torch.equal(inplace_x, inplace_before),
        "input_version_before": inplace_version_before,
        "input_version_after": int(inplace_x._version),
        "returned_is_present": returned is not None,
        "returned_shares_input_storage": bool(returned is not None and returned.data_ptr() == inplace_x.data_ptr()),
        "returned_base_present": bool(returned is not None and returned._base is not None),
        "returned_base_shares_input_storage": bool(
            returned is not None and returned._base is not None
            and returned._base.data_ptr() == inplace_x.data_ptr()
        ),
        "raw_tensor_values_recorded": False,
        "probe_model_retains_return_for_measurement": True,
    }

    nested_runs = []
    for expand_nested in (False, True):
        nested = Nested()
        nested.train()
        nested.inner.eval()
        before_modes = {"outer": bool(nested.training), "inner": bool(nested.inner.training)}
        run = capture(
            f"nested_expand_{str(expand_nested).lower()}", nested,
            torch.tensor([1.0, 2.0]),
            depth=4,
            expand_nested=expand_nested,
            hide_inner_tensors=False,
            hide_module_functions=False,
        )
        run["forward_event_order"] = list(nested.events)
        run["training_modes_before"] = before_modes
        run["training_modes_after"] = {"outer": bool(nested.training), "inner": bool(nested.inner.training)}
        nested_runs.append(run)
    results["captures"].extend(nested_runs)

    stateful = CounterAndBuffer()
    state_before = {"python_counter": stateful.python_counter, "ticks": int(stateful.ticks.item())}
    stateful_record = capture(
        "python_counter_and_registered_buffer", stateful,
        torch.tensor([1.0, 2.0]),
        depth=4,
        hide_inner_tensors=False,
        hide_module_functions=False,
    )
    stateful_record["state_before"] = state_before
    stateful_record["state_after"] = {
        "python_counter": stateful.python_counter,
        "ticks": int(stateful.ticks.item()),
    }
    results["captures"].append(stateful_record)

    destination = HERE / "torchview_probe.json"
    destination.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(destination)
    print(json.dumps({
        "runtime": results["runtime"],
        "captures": [
            {
                "label": row["label"],
                "status": row["status"],
                "node_count": row.get("graph", {}).get("node_count"),
                "edge_count": row.get("graph", {}).get("edge_count"),
                "elapsed_seconds": row.get("elapsed_seconds"),
            }
            for row in results["captures"]
        ],
    }, indent=2))


if __name__ == "__main__":
    main()
