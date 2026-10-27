"""Conditional return-reference paths, separate from state/effect obligations.

The query replays raw source before following exact core reference edges. It
never follows all inputs of an opaque operation as if they were output aliases.
"""
from __future__ import annotations

from scar.analysis.program_lowering import SourceProgram
from scar.ir.program.frames import FrameExit
from scar.ir.program.functions import BodyLoweringProfile
from scar.ir.program.model import BlockArgument, CompletionResult, LiteralOrigin, OperationResult
from scar.ir.record_codec import encode


def query_return_references(document, *, max_operations=10000, max_reference_steps=4096):
    """Replay a source-program document and report each completion's payload.

    Edge paths describe conditional reference routing, not path feasibility,
    content equality, purity, runtime dispatch, or permission to transform.
    """
    if type(max_reference_steps) is not int or not 1 <= max_reference_steps <= 100000:
        raise ValueError("reference query steps must be an integer in [1, 100000]")
    result = SourceProgram.from_dict(document, max_operations=max_operations)
    if result.profile is not BodyLoweringProfile.BOUND_FRAME or result.graph is None:
        raise ValueError("return-reference query requires a supported bound-frame source program")
    graph = result.graph
    operations = {operation.id: operation for operation in graph.operations}
    values = {value.id: value for value in graph.values}
    formals = {port.value: port.slot for port in result.interface.parameters}
    region = next(region for region in graph.regions if region.id == graph.root)
    blocks = {block.id: block for block in region.blocks}
    incoming = {}
    for operation in graph.operations:
        if operation.terminator is None:
            continue
        uses = {use.id: use for use in operation.uses}
        for edge_index, edge in enumerate(operation.terminator.successors):
            for index, operand in enumerate(edge.arguments):
                route = {"operation": operation.id.wire, "successor": edge_index,
                         "block": edge.block.wire, "port": index}
                incoming.setdefault(blocks[edge.block].arguments[index], []).append((uses, operand, route))

    completions, steps, exhausted = [], 0, False
    for transition in result.frame.transitions:
        if not isinstance(transition, FrameExit):
            continue
        operation = operations[transition.completion]
        uses = {use.id: use for use in operation.uses}
        payload = uses[operation.terminator.values[0]]
        post_world = uses[operation.terminator.values[1]]
        origins = []
        pending = [(payload.value, (), frozenset())]
        while pending:
            value_id, path, visited = pending.pop()
            if steps >= max_reference_steps:
                exhausted = True
                origins.append({"kind": "QUERY_BUDGET", "value": value_id.wire,
                                "path": list(path), "pending_routes": len(pending) + 1})
                break
            steps += 1
            base = {"value": value_id.wire, "path": list(path)}
            if value_id in visited:
                origins.append({"kind": "CYCLE_BOUNDARY", **base})
                continue
            value = values[value_id]
            origin = value.origin
            if value_id in formals:
                origins.append({"kind": "FORMAL_REFERENCE", "slot": formals[value_id].wire, **base})
            elif isinstance(origin, LiteralOrigin):
                origins.append({"kind": "LITERAL_REFERENCE", "literal": origin.value, **base})
            elif isinstance(origin, OperationResult):
                origins.append({"kind": "OPERATION_RESULT_BOUNDARY", "operation": origin.operation.wire,
                                "index": origin.index, **base})
            elif isinstance(origin, BlockArgument):
                edges = incoming.get(value_id, ())
                if not edges:
                    origins.append({"kind": "ENTRY_BOUNDARY", **base})
                for edge_uses, operand, route in reversed(edges):
                    if isinstance(operand, CompletionResult):
                        origins.append({"kind": "COMPLETION_RESULT_BOUNDARY", "index": operand.index,
                                        **base, "path": [*path, route]})
                    else:
                        pending.append((edge_uses[operand].value, (*path, route), visited | {value_id}))
        completions.append({
            "completion": operation.id.wire, "kind": operation.terminator.kind.value,
            "source": encode(transition.source), "payload_use": payload.id.wire,
            "payload_value": payload.value.wire, "post_world": post_world.value.wire,
            "reference_origins": origins,
        })

    return {
        "schema": "scar.frame-reference-query", "schema_version": 1,
        "status": "QUERY_BUDGET" if exhausted else "REPLAYED_CONDITIONAL_ROUTES",
        "entry": result.metadata.entry, "profile": result.profile.value,
        "completions": completions, "reference_steps": steps,
        "max_reference_steps": max_reference_steps,
        "frame_rules": encode(result.frame.rules),
        "source_conditions": [condition.value for condition in result.metadata.assumptions],
        "incomplete_effect_operations": [op.id.wire for op in graph.operations if not op.effects_complete],
        "scope": "payload reference routing; state and frame lifetime obligations remain separate",
        "runtime_target_verified": False, "contents_or_effects_established": False,
        "transformation_authorized": False,
    }


__all__ = ["query_return_references"]
