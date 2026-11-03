"""Structural lookup-interface checks against original core ports.

No selector is promoted to an address/effect, and no receiver/result identity
or selected runtime dispatch is inferred. Independent source/compiler replay
must separately establish the request's static source and name-resolution rule.
"""
from __future__ import annotations

from scar.ir.program.attribute_lookups import AttributeLookupForm, AttributeLookupInterface
from scar.ir.program.model import (BlockArgument, CompletionResult, DataValue, ExitKind,
    LiteralOrigin, ProgramGraph, ReferenceValue, StateVersionValue, TerminatorKind,
    UseRole, ValueKind, value_type)
from scar.ir.program.literal_sources import ExactLiteralOrigin
from scar.ir.literals import LiteralKind


def attribute_lookup_errors(graph: ProgramGraph) -> tuple[tuple[str, str, str], ...]:
    if type(graph) is not ProgramGraph:
        return (("attribute_lookup_graph", "graph", "expected exact ProgramGraph"),)
    if graph.attribute_lookups is None:
        return ()
    issues = []
    def error(code, path, message):
        issues.append((code, path, message))
    operations = {row.id: row for row in graph.operations}
    values = {row.id: row for row in graph.values}
    blocks = {block.id: block for region in graph.regions for block in region.blocks}
    seen = set()
    for ordinal, row in enumerate(graph.attribute_lookups):
        path = f"attribute_lookups[{ordinal}]"
        if type(row) is not AttributeLookupInterface:
            error("attribute_lookup_record", path, "expected exact AttributeLookupInterface")
            continue
        try:
            row.__post_init__()
        except (TypeError, ValueError) as exc:
            error("attribute_lookup_record", path, str(exc))
            continue
        if row.operation in seen:
            error("attribute_lookup_duplicate", path, "one original operation has multiple lookup interfaces")
        seen.add(row.operation)
        operation = operations.get(row.operation)
        if operation is None:
            error("attribute_lookup_operation", path, "lookup operation is absent from this graph")
            continue
        term = operation.terminator
        if (term is None or term.kind is not TerminatorKind.INVOKE or operation.callee is not None
                or operation.effects_complete):
            error("attribute_lookup_invoke", path,
                "lookup must retain its original incomplete opaque INVOKE, without a fixed callee")
            continue
        uses = {use.id: use for use in operation.uses}
        receiver, world_use = uses.get(row.receiver), uses.get(row.world)
        receiver_value = values.get(receiver.value) if receiver is not None else None
        before = values.get(world_use.value) if world_use is not None else None
        if (receiver is None or receiver.role is not UseRole.REFERENCE
                or type(receiver_value) is not ReferenceValue or row.receiver not in operation.invoke_arguments):
            error("attribute_lookup_receiver", path, "receiver is not this INVOKE's actual reference Use")
        if (world_use is None or world_use.role is not UseRole.STATE_CONTENT
                or type(before) is not StateVersionValue or row.world not in operation.invoke_arguments):
            error("attribute_lookup_world", path, "world is not this INVOKE's actual coarse-state Use")
            before = None
        expected_uses = (row.receiver, *((row.selector.key_use,)
            if row.selector.key_use is not None else ()), row.world)
        if operation.invoke_arguments != expected_uses or tuple(use.id for use in operation.uses) != expected_uses:
            error("attribute_lookup_operand_layout", path,
                "lookup must retain exactly the original ordered receiver/optional key/world Uses")
        key_id = row.selector.key_use
        if key_id is not None:
            key = uses.get(key_id)
            value = values.get(key.value) if key is not None else None
            if key is None or key.role is not UseRole.REFERENCE or type(value) is not ReferenceValue:
                error("attribute_lookup_key", path, "lookup key is not its actual original reference Use")
            elif row.selector.lookup_name is not None:
                origin = value.origin
                name = (origin.value if type(origin) is LiteralOrigin and type(origin.value) is str else
                    origin.literal.to_python() if type(origin) is ExactLiteralOrigin
                        and origin.literal.kind in (LiteralKind.STR, LiteralKind.STR_CODEPOINTS) else None)
                if name != row.selector.lookup_name:
                    error("attribute_lookup_key_name", path, "literal key differs from the declared actual lookup name")
        for name, completion, kind in (("normal", row.normal, ExitKind.NORMAL),
                                       ("raised", row.raised, ExitKind.RAISE)):
            own_path = path + "." + name
            index = completion.edge.successor_index
            if index >= len(term.successors):
                error("attribute_lookup_edge", own_path, "completion edge is absent from the original INVOKE")
                continue
            edge = term.successors[index]
            signatures = [signature for signature in operation.completions if signature.kind is kind]
            same_kind = [successor for successor in term.successors if successor.kind is kind]
            if edge.kind is not kind or len(signatures) != 1 or len(same_kind) != 1:
                error("attribute_lookup_completion", own_path, "lookup needs its unique actual NORMAL/RAISE signature and edge")
                continue
            signature = signatures[0]
            block = blocks.get(edge.block)
            if block is None or len(edge.arguments) != len(block.arguments):
                error("attribute_lookup_landing", own_path, "lookup completion lacks its original landing block/formals")
                continue
            slots = {}
            for actual, formal in zip(edge.arguments, block.arguments):
                if type(actual) is not CompletionResult:
                    error("attribute_lookup_completion_argument", own_path,
                        "lookup landing must retain original produced completion slots")
                    continue
                if actual.index >= len(signature.types) or actual.index in slots:
                    error("attribute_lookup_completion_slot", own_path, "lookup completion slot is out of range or repeated")
                    continue
                slots[actual.index] = formal
            if set(slots) != set(range(len(signature.types))):
                error("attribute_lookup_completion_slots", own_path, "lookup completion does not expose every original signature slot")
                continue
            world_slots = [i for i, typ in enumerate(signature.types) if getattr(typ, "kind", None) is ValueKind.STATE]
            if len(world_slots) != 1:
                error("attribute_lookup_post_world", own_path, "lookup completion needs one actual post-world slot")
                continue
            world_slot = world_slots[0]
            actual_world = slots[world_slot]
            payloads = tuple(slots[i] for i in range(len(signature.types)) if i != world_slot)
            if completion.payloads != payloads or completion.world != actual_world:
                error("attribute_lookup_completion_values", own_path,
                    "lookup payload/world IDs differ from original completion formal slots")
            after = values.get(actual_world)
            if type(after) is not StateVersionValue or before is not None and after.location != before.location:
                error("attribute_lookup_post_world", own_path, "lookup post-world changed its actual state carrier")
            for i, formal in slots.items():
                value = values.get(formal)
                position = block.arguments.index(formal)
                if (value is None or value.origin != BlockArgument(block.id, position)
                        or value_type(value) != signature.types[i]):
                    error("attribute_lookup_formal", own_path, "lookup landing value type/origin differs from its original slot")
            if kind is ExitKind.NORMAL:
                normal_values = tuple(values.get(formal) for formal in payloads)
                if row.form is AttributeLookupForm.CPYTHON_LOAD_METHOD:
                    valid = (len(normal_values) == 3 and type(normal_values[0]) is ReferenceValue
                        and type(normal_values[1]) is ReferenceValue and type(normal_values[2]) is DataValue
                        and normal_values[2].data_type == "builtins.bool")
                else:
                    valid = len(normal_values) == 1 and type(normal_values[0]) is ReferenceValue
                if not valid:
                    error("attribute_lookup_normal_abi", own_path,
                        "getter needs one reference; normalized method lookup needs callable/self references and builtin-bool flag")
    return tuple(issues)


__all__ = ["attribute_lookup_errors"]
