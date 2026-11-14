"""Order-preserving scalar DAG transformations for array regions.

The structural key deliberately does not hash Expr: its attrs contain mutable
JSON containers. Operand order and the exact type/sign of constants are part of
the key; no associative or commutative arithmetic identities are used.
"""

from dataclasses import dataclass
import heapq
import math
import operator

from scar.compiler.model import ArrayRegion, Expr


_ARITY = {"input": 0, "const": 0, "slice": 1, "neg": 1,
          "add": 2, "sub": 2, "mul": 2, "div": 2}
_ARITHMETIC = {"add": operator.add, "sub": operator.sub,
               "mul": operator.mul, "div": operator.truediv,
               "neg": operator.neg}
MAX_EXACT_INTEGER = 2**53


def ordered_nodes(region: ArrayRegion) -> tuple[Expr, ...]:
    """Validate graph connectivity and return stable topological order.

    Unsupported operators are left for the profile proof. Malformed graphs are
    errors, including malformed nodes that happen to be unreachable.
    """
    nodes = {}
    for node in region.nodes:
        if not isinstance(node.id, str) or not node.id:
            raise ValueError("expression IDs must be nonempty strings")
        if node.id in nodes:
            raise ValueError(f"duplicate expression ID: {node.id}")
        nodes[node.id] = node
        if node.op in _ARITY and len(node.inputs) != _ARITY[node.op]:
            raise ValueError(f"invalid input arity for {node.id}: {node.op}")
    if region.output not in nodes:
        raise ValueError(f"dangling region output: {region.output}")
    positions = {node.id: index for index, node in enumerate(region.nodes)}
    indegrees = {node.id: len(set(node.inputs)) for node in region.nodes}
    users = {node.id: [] for node in region.nodes}
    for node in region.nodes:
        for operand in set(node.inputs):
            if operand not in nodes:
                raise ValueError(f"dangling expression input: {node.id} -> {operand}")
            users[operand].append(node.id)
    ready = [positions[key] for key, count in indegrees.items() if count == 0]
    heapq.heapify(ready)
    result = []
    while ready:
        node = region.nodes[heapq.heappop(ready)]
        result.append(node)
        for user in users[node.id]:
            indegrees[user] -= 1
            if indegrees[user] == 0:
                heapq.heappush(ready, positions[user])
    if len(result) != len(nodes):
        raise ValueError("expression graph contains a cycle")
    return tuple(result)


def numeric_value(value):
    """Return whether a literal is a supported exact-profile Python number."""
    return ((type(value) is int and abs(value) <= MAX_EXACT_INTEGER)
            or (type(value) is float and math.isfinite(value)))


def canonical_value(value):
    """Canonical nested JSON key preserving float -0.0 and numeric types."""
    if value is None:
        return ("none",)
    if type(value) is bool:
        return ("bool", value)
    if type(value) is int:
        return ("int", value)
    if type(value) is float:
        return ("float", value.hex())
    if isinstance(value, str):
        return ("str", value)
    if isinstance(value, (list, tuple)):
        return ("sequence", tuple(canonical_value(item) for item in value))
    if isinstance(value, dict):
        entries = [(canonical_value(key), canonical_value(item))
                   for key, item in value.items()]
        return ("mapping", tuple(sorted(entries)))
    raise ValueError(f"unsupported expression attribute type: {type(value).__name__}")


def constant_result(node, constants):
    """Evaluate just one original scalar operation, never reassociating it."""
    if node.op not in _ARITHMETIC or not all(i in constants for i in node.inputs):
        return None, None
    try:
        result = _ARITHMETIC[node.op](*(constants[i] for i in node.inputs))
    except (ArithmeticError, ValueError) as error:
        return None, type(error).__name__
    if not numeric_value(result):
        return None, "nonfinite_or_out_of_profile_result"
    return result, None


@dataclass
class SimplifiedGraph:
    nodes: tuple[Expr, ...]
    output: str
    source_operation_map: dict
    eliminated_nodes: list[dict]
    folded_nodes: list[str]
    retained_constant_operations: list[dict]


def simplify(nodes: tuple[Expr, ...], output: str) -> SimplifiedGraph:
    """Fold scalar constants, eliminate identical DAG nodes, then close DCE."""
    aliases, constants, representatives = {}, {}, {}
    rewritten, reasons, folded, retained = [], {}, [], []
    for source in nodes:
        inputs = tuple(aliases[i] for i in source.inputs)
        node = Expr(source.id, source.op, inputs, dict(source.attrs))
        value, refusal = constant_result(node, constants)
        if refusal is not None:
            retained.append({"id": node.id, "reason": refusal})
        elif node.op in _ARITHMETIC and all(i in constants for i in inputs):
            node = Expr(node.id, "const", attrs={"value": value})
            folded.append(node.id)
        key = (node.op, node.inputs, canonical_value(node.attrs))
        if key in representatives:
            aliases[source.id] = representatives[key]
            reasons[source.id] = "common_subexpression"
            continue
        representatives[key] = node.id
        aliases[source.id] = node.id
        rewritten.append(node)
        if node.op == "const":
            constants[node.id] = node.attrs["value"]

    by_id = {node.id: node for node in rewritten}
    optimized_output = aliases[output]
    # Input bindings are part of the region signature even if their array data
    # are unused. Retaining these descriptors does not retain any array loads.
    live, pending = set(), [optimized_output] + [n.id for n in rewritten if n.op == "input"]
    while pending:
        current = pending.pop()
        if current not in live:
            live.add(current)
            pending.extend(by_id[current].inputs)

    mapping, eliminated = {}, []
    for source in nodes:
        replacement = aliases[source.id]
        if replacement not in live:
            reason, replacement = "dead_dependency", None
        else:
            reason = reasons.get(source.id, "constant_fold" if source.id in folded
                                 else "preserved")
        mapping[source.id] = {"source_op": source.op, "optimized_node": replacement,
                              "reason": reason}
        if replacement != source.id:
            eliminated.append({"id": source.id, "reason": reason,
                               "replacement": replacement})
    return SimplifiedGraph(tuple(n for n in rewritten if n.id in live),
                           optimized_output, mapping, eliminated, folded, retained)


def value_kinds(nodes):
    """Arrays vary across calls/elements; scalar expressions are setup only."""
    result = {}
    for node in nodes:
        result[node.id] = ("scalar" if node.op == "const" else "array"
                           if node.op in ("input", "slice") else
                           "array" if any(result[i] == "array" for i in node.inputs)
                           else "scalar")
    return result
