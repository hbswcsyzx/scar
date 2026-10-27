"""Small CPU-only probes for installed torch.fx (no third-party installs)."""
from __future__ import annotations

import json
import operator
import platform
import random
import sys
from pathlib import Path
from typing import Any

import torch
from torch import nn
from torch.fx import GraphModule, Tracer, symbolic_trace
from torch.fx.proxy import TraceError
from torch.fx.passes.shape_prop import ShapeProp
from torch.fx.experimental.proxy_tensor import make_fx


def arg_repr(value: Any) -> Any:
    if hasattr(value, "op") and hasattr(value, "target") and hasattr(value, "name"):
        return {"node": value.name}
    if isinstance(value, tuple):
        return [arg_repr(item) for item in value]
    if isinstance(value, list):
        return [arg_repr(item) for item in value]
    if isinstance(value, dict):
        return {str(k): arg_repr(v) for k, v in value.items()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return {"python_type": f"{type(value).__module__}.{type(value).__qualname__}"}


def target_repr(target: Any) -> str:
    if isinstance(target, str):
        return target
    return f"{getattr(target, '__module__', type(target).__module__)}.{getattr(target, '__qualname__', getattr(target, '__name__', type(target).__qualname__))}"


def graph_rows(gm_or_graph: Any) -> list[dict[str, Any]]:
    graph = getattr(gm_or_graph, "graph", gm_or_graph)
    rows = []
    for node in graph.nodes:
        rows.append({
            "name": node.name,
            "op": node.op,
            "target": target_repr(node.target),
            "args": arg_repr(node.args),
            "kwargs": arg_repr(node.kwargs),
            "users": {user.name: count for user, count in node.users.items()},
            "meta_keys": sorted(node.meta),
            "has_stack_trace": bool(node.meta.get("stack_trace")),
            "nn_module_stack": sorted(node.meta.get("nn_module_stack", {})),
        })
    return rows


class Basic(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.relu = nn.ReLU()

    def forward(self, x):
        shared = x + x
        return self.relu(shared)


def inline_helper(x):
    return torch.sin(x) + 1


def wrapped_helper(x):
    return torch.cos(x) - 1


torch.fx.wrap("wrapped_helper")


class Helpers(nn.Module):
    def forward(self, x):
        return inline_helper(x) + wrapped_helper(x)


class CountingLeaf(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.forward_calls = 0

    def forward(self, x):
        self.forward_calls += 1
        return x * 3


class LeafParent(nn.Module):
    def __init__(self, child: CountingLeaf) -> None:
        super().__init__()
        self.child = child
        self.root_forward_calls = 0

    def forward(self, x):
        self.root_forward_calls += 1
        return self.child(x)


class ForceCountingLeaf(Tracer):
    def is_leaf_module(self, module, qualified_name):
        if isinstance(module, CountingLeaf):
            return True
        return super().is_leaf_module(module, qualified_name)


class SideEffect(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.forward_calls = 0

    def forward(self, x):
        self.forward_calls += 1
        return x + 1


class BufferMutation(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.register_buffer("counter", torch.zeros((), dtype=torch.int64))

    def forward(self, x):
        self.counter.add_(1)
        return x + 1


class StaticLoop(nn.Module):
    def forward(self, x):
        for _ in range(3):
            x = x + 1
        return x


class RandomConstant(nn.Module):
    def forward(self, x):
        sample = torch.rand(2)
        return x + sample


class RandomLike(nn.Module):
    def forward(self, x):
        return x + torch.rand_like(x)


class DataBranch(nn.Module):
    def forward(self, x):
        if x.sum() > 0:
            return x + 1
        return x - 1


class StackTracer(Tracer):
    def __init__(self) -> None:
        super().__init__()
        self.record_stack_traces = True


result: dict[str, Any] = {
    "runtime": {
        "python": platform.python_version(),
        "torch": torch.__version__,
        "device": "cpu",
    },
}

basic = Basic()
basic_gm = symbolic_trace(basic)
add_node = next(node for node in basic_gm.graph.nodes if node.op == "call_function" and node.target is operator.add)
result["basic"] = {
    "graph": graph_rows(basic_gm),
    "same_input_node_twice": add_node.args[0] is add_node.args[1],
    "input_occurrence_count_in_args": sum(arg is add_node.args[0] for arg in add_node.args),
    "placeholder_unique_user_count": len(next(node for node in basic_gm.graph.nodes if node.op == "placeholder").users),
    "shape_prop": None,
}
ShapeProp(basic_gm).propagate(torch.ones(2, 3))
result["basic"]["shape_prop"] = {
    node.name: {
        "shape": list(node.meta["tensor_meta"].shape),
        "dtype": str(node.meta["tensor_meta"].dtype),
    }
    for node in basic_gm.graph.nodes
    if "tensor_meta" in node.meta
}

helpers_gm = symbolic_trace(Helpers())
result["helpers"] = {"graph": graph_rows(helpers_gm)}

leaf = CountingLeaf()
parent = LeafParent(leaf)
leaf_tracer = ForceCountingLeaf()
leaf_graph = leaf_tracer.trace(parent)
leaf_gm = GraphModule(parent, leaf_graph)
result["leaf_module"] = {
    "graph": graph_rows(leaf_gm),
    "root_forward_calls_during_trace": parent.root_forward_calls,
    "child_forward_calls_during_trace": leaf.forward_calls,
}

side_effect = SideEffect()
side_gm = symbolic_trace(side_effect)
result["python_side_effect"] = {
    "counter_after_symbolic_trace": side_effect.forward_calls,
    "graph": graph_rows(side_gm),
}
side_gm(torch.zeros(1))
result["python_side_effect"]["counter_after_graphmodule_run"] = side_effect.forward_calls

buffer_mutation = BufferMutation()
buffer_gm = symbolic_trace(buffer_mutation)
buffer_after_trace = int(buffer_mutation.counter.item())
buffer_gm(torch.zeros(1))
result["buffer_mutation"] = {
    "buffer_after_trace": buffer_after_trace,
    "buffer_after_graphmodule_run": int(buffer_mutation.counter.item()),
    "graph": graph_rows(buffer_gm),
}

static_loop_gm = symbolic_trace(StaticLoop())
result["static_loop"] = {
    "call_function_add_count": sum(
        node.op == "call_function" and node.target is operator.add
        for node in static_loop_gm.graph.nodes
    ),
    "graph": graph_rows(static_loop_gm),
}

random.seed(914)
torch.manual_seed(914)
rng_before = torch.random.get_rng_state().clone()
random_gm = symbolic_trace(RandomConstant())
rng_after_trace = torch.random.get_rng_state().clone()
rng_after_replay_before = torch.random.get_rng_state().clone()
random_gm(torch.zeros(2))
rng_after_replay = torch.random.get_rng_state().clone()
result["random_constant"] = {
    "rng_changed_during_trace": not torch.equal(rng_before, rng_after_trace),
    "rng_changed_during_graphmodule_run": not torch.equal(rng_after_replay_before, rng_after_replay),
    "graph": graph_rows(random_gm),
    "graphmodule_code": random_gm.code,
}

random_like = RandomLike()
torch.manual_seed(207)
rand_like_rng_before = torch.random.get_rng_state().clone()
rand_like_gm = symbolic_trace(random_like)
rand_like_rng_after = torch.random.get_rng_state().clone()
result["random_like"] = {
    "rng_changed_during_trace": not torch.equal(rand_like_rng_before, rand_like_rng_after),
    "graph": graph_rows(rand_like_gm),
}

make_fx_calls: list[str] = []
def make_fx_sample(x):
    make_fx_calls.append("entered")
    return torch.sin(x) + torch.rand_like(x)
torch.manual_seed(312)
make_fx_rng_before = torch.random.get_rng_state().clone()
make_fx_gm = make_fx(make_fx_sample, tracing_mode="real", record_stack_traces=True)(torch.ones(2))
make_fx_rng_after = torch.random.get_rng_state().clone()
result["make_fx"] = {
    "called_python_function_during_capture": make_fx_calls,
    "rng_changed_during_capture": not torch.equal(make_fx_rng_before, make_fx_rng_after),
    "graph": graph_rows(make_fx_gm),
}

def make_fx_branch(x):
    if x.sum() > 0:
        return x + 1
    return x - 1
branch_probes = {}
for label, sample in (("positive", torch.ones(2)), ("negative", -torch.ones(2))):
    try:
        branch_gm = make_fx(make_fx_branch, tracing_mode="real")(sample)
    except Exception as exc:
        branch_probes[label] = {
            "error_type": f"{type(exc).__module__}.{type(exc).__qualname__}",
            "message": str(exc),
        }
    else:
        branch_probes[label] = {
            "targets": [target_repr(n.target) for n in branch_gm.graph.nodes],
            "code": branch_gm.code,
        }
result["make_fx_data_branch"] = branch_probes

try:
    symbolic_trace(DataBranch())
except Exception as exc:
    result["data_dependent_branch"] = {
        "error_type": f"{type(exc).__module__}.{type(exc).__qualname__}",
        "message": str(exc),
        "partial_graph_attached": hasattr(exc, "partial_fx_graph"),
    }
else:
    result["data_dependent_branch"] = {"error_type": None}

stack_tracer = StackTracer()
stack_gm = GraphModule(basic, stack_tracer.trace(basic))
result["source_metadata"] = {
    "default_basic_nodes_have_stack_trace": any(bool(node.meta.get("stack_trace")) for node in basic_gm.graph.nodes),
    "custom_tracer_stack_trace_nodes": {
        node.name: node.meta.get("stack_trace")
        for node in stack_gm.graph.nodes
        if node.meta.get("stack_trace")
    },
    "custom_graph": graph_rows(stack_gm),
}

out = Path(__file__).with_name("fx_probe.json")
out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(out)
print(json.dumps(result, indent=2, sort_keys=True))
