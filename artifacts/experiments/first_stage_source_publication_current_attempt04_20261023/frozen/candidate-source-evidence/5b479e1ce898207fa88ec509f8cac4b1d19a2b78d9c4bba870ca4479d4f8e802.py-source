"""Recover provider-declared schema ports and bind real ordered ETO slots.

This enriches the existing semantic/evidence graphs. Alias annotations are
may-alias contracts, not logical equality, physical copy or runtime lifetimes.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import math

from scar.ir.v2.common import Completeness, EvidenceClaim, EvidenceKind
from scar.ir.v2.contracts import EffectSet, EffectSummary, EffectTarget, EffectTargetKind
from scar.ir.v2.ids import EffectSummaryID, ValueSlotID
from scar.ir.v2.semantic import SemanticEdge, SemanticEndpoint, SemanticNodeKind, SemanticRelation, ValueSlot


PROVIDER_REVISION = "cf30153c4c131c8164ee7798e5022d810682e2cb"


def _default(value, *, depth=0):
    """Encode only bounded scalar/container defaults, never Tensor data."""
    if depth > 8:
        return {"status": "not_serialized", "reason": "depth_budget"}
    kind = type(value)
    if kind in (type(None), bool, int):
        return {"status": "literal", "value": value}
    if kind is float:
        return ({"status": "literal", "value": value} if math.isfinite(value)
                else {"status": "not_serialized", "reason": "nonfinite_scalar"})
    if kind is str and len(value) <= 4096:
        return {"status": "literal", "value": value}
    if kind in (tuple, list) and len(value) <= 64:
        return {"status": "container", "kind": kind.__name__,
                "items": [_default(child, depth=depth + 1) for child in value]}
    return {"status": "not_serialized", "reason": "nonliteral_or_budget"}


def _unwrap_optional(jit_type):
    for _ in range(32):
        if jit_type.kind() != "OptionalType":
            return jit_type
        jit_type = jit_type.getElementType()
    raise ValueError("nested optional type budget exceeded")


def _tensor_path(jit_type, path):
    """Check each actual container coordinate against its formal JIT type."""
    if len(path) > 64:
        return False, "container_path_budget"
    for selector in path:
        jit_type = _unwrap_optional(jit_type)
        kind = jit_type.kind()
        if type(selector) is not int or selector < 0:
            return False, "nonordinal_provider_container_path"
        if kind == "ListType":
            jit_type = jit_type.getElementType()
        elif kind == "TupleType":
            elements = jit_type.elements()
            if selector >= len(elements):
                return False, "tuple_coordinate_outside_formal"
            jit_type = elements[selector]
        else:
            return False, "provider_path_not_supported_by_formal_type"
    return ((True, None) if _unwrap_optional(jit_type).kind() == "TensorType"
            else (False, "formal_leaf_is_not_declared_tensor"))


def _argument(argument, index, direction):
    alias = argument.alias_info
    kind = _unwrap_optional(argument.type).kind()
    nested = alias is not None and kind != "TensorType"
    aliases = None if alias is None else {
        "is_write": bool(alias.is_write), "before": sorted(alias.before_set),
        "after": sorted(alias.after_set), "contained_aliases_exposed": False,
        "contained_aliases_unresolved": nested}
    has_default = bool(argument.has_default_value())
    return {"ordinal": index, "direction": direction, "name": argument.name,
        "type": str(argument.type), "real_type": str(argument.real_type),
        "kwarg_only": bool(argument.kwarg_only), "is_out": bool(argument.is_out),
        "has_default": has_default,
        "default": _default(argument.default_value) if has_default else None,
        "declared_may_write": bool(argument.is_write), "alias": aliases,
        "gaps": ["contained_alias_annotations_not_exposed"] if nested else []}


def _may_overlap(left, right):
    if left is None or right is None:
        return False
    first, second = set(left["after"]), set(right["after"])
    return bool(first & second or ("*" in first and second) or ("*" in second and first))


def recover_schema_contracts(native_result, *, provider_revision=PROVIDER_REVISION):
    """Mutate native_result's existing slots/effects and return its bridge report.

    The installed parser revision must match the imported provider exactly.
    Each qualified actual Tensor slot points to a real ValueSlot in the same
    SemanticGraph. Unqualified observations remain present with an explicit gap.
    No external artifact paths are opened and no target computation is run.
    """
    if "native_schema" in native_result.report:
        raise ValueError("native schema contracts are already recovered")
    import torch
    if (provider_revision != PROVIDER_REVISION
            or native_result.report.get("provider_revision") != provider_revision
            or torch.version.git_version != provider_revision):
        raise ValueError("native schema parser/imported provider revision mismatch")
    parse_schema = torch._C.parse_schema
    graph, evidence = native_result.bundle.semantic, native_result.bundle.evidence
    scope = native_result.report["scope"] + ":schema-contracts"
    source_by_definition = {}
    for instance in evidence.instances.values():
        if instance.metadata.get("provider") == "ETO":
            source_by_definition.setdefault(instance.definition, instance.metadata.get("raw_reference"))
    parsed, failures, contracts = {}, {}, {}
    slots, effects, edges, definitions = [], [], [], []
    contract_gaps = Counter()
    for definition in graph.definitions.values():
        raw = definition.metadata.get("op_schema")
        if definition.metadata.get("provider") != "eto" or type(raw) is not str or not raw:
            continue
        if definition.input_slots or definition.output_slots or definition.effect_summary is not None:
            raise ValueError("native schema bridge cannot overwrite an existing formal/effect interface")
        if raw in failures:
            continue
        if raw not in parsed:
            try:
                schema = parse_schema(raw)
                arguments = [_argument(arg, index, "input") for index, arg in enumerate(schema.arguments)]
                returns = [_argument(arg, index, "output") for index, arg in enumerate(schema.returns)]
            except Exception as error:
                failures[raw] = {"schema_sha256": sha256(raw.encode()).hexdigest(),
                                 "raw_schema": raw, "error_type": type(error).__name__}
                continue
            parsed[raw] = (schema, arguments, returns)
        schema, arguments, returns = parsed[raw]
        schema_hash = sha256(raw.encode()).hexdigest()
        contract = {"provider_revision": provider_revision, "schema_sha256": schema_hash,
            "raw_schema": raw, "schema_name": schema.name, "overload_name": schema.overload_name,
            "declared_is_mutable": bool(schema.is_mutable),
            "alias_symbols_scope": "this schema contract only; symbols are not global storage identities",
            "source_reference": source_by_definition.get(definition.id),
            "input_slots": [], "output_slots": [], "possible_aliases": [],
            "alias_pair_inventory_complete": False,
            "gaps": ["schema_does_not_close_rng_external_ordering_exception_or_lifetime_effects",
                     "registered_alias_analysis_kind_not_recovered_from_schema_text",
                     "unlisted_alias_pairs_are_not_proven_disjoint"]}
        if "..." in raw:
            contract["gaps"].append("variadic_schema_not_qualified")
        owned = []
        for records, field in ((arguments, "input_slots"), (returns, "output_slots")):
            for record in records:
                slot_id = ValueSlotID(definition.id.value + ":schema:" + field + ":" + str(record["ordinal"]))
                metadata = {"native_schema": {**record, "schema_sha256": schema_hash,
                                             "source_reference": contract["source_reference"]}}
                slot = ValueSlot(slot_id, record["name"] or "return_" + str(record["ordinal"]),
                    record["direction"], record["real_type"], definition.id,
                    True if record["declared_may_write"] else None, metadata)
                slots.append(slot); owned.append((slot, record))
                contract[field].append(slot_id.as_dict())
                contract["gaps"].extend(record["gaps"])
        claim = EvidenceClaim(EvidenceKind.DECLARED,
            (contract["source_reference"],) if contract["source_reference"] is not None else (),
            scope=scope, assumptions=("installed parser matches the imported provider revision",
                "annotations are provider-declared may effects, not complete runtime behavior",
                "alias symbols are scoped to this one operator schema"))
        for left_index, (left, left_record) in enumerate(owned):
            for right, right_record in owned[left_index + 1:]:
                if _may_overlap(left_record["alias"], right_record["alias"]):
                    contract["possible_aliases"].append({"left": left.slot_id.as_dict(),
                        "right": right.slot_id.as_dict(), "relation": "may_alias"})
        effect_id = EffectSummaryID(definition.id.value + ":provider-schema-effects")
        writes = tuple(EffectTarget(EffectTargetKind.VALUE_SLOT, slot.slot_id.wire)
            for slot, record in owned if record["direction"] == "input" and record["declared_may_write"])
        aliases = tuple(EffectTarget(EffectTargetKind.VALUE_SLOT, slot.slot_id.wire)
            for slot, record in owned if record["alias"] is not None)
        effects.append(EffectSummary(effect_id,
            writes=EffectSet(writes, Completeness.PARTIAL),
            aliases=EffectSet(aliases, Completeness.PARTIAL), evidence=(claim,)))
        source = SemanticEndpoint(SemanticNodeKind.OPERATION, definition.id)
        for slot, record in owned:
            relation = SemanticRelation.CONSUMES if record["direction"] == "input" else SemanticRelation.PRODUCES
            edges.append(SemanticEdge(slot.slot_id.value + ":port", relation, source,
                                     SemanticEndpoint(SemanticNodeKind.VALUE_SLOT, slot.slot_id), claim))
            if record["direction"] == "input" and record["declared_may_write"]:
                edges.append(SemanticEdge(slot.slot_id.value + ":may-write", SemanticRelation.WRITES_SLOT,
                    source, SemanticEndpoint(SemanticNodeKind.VALUE_SLOT, slot.slot_id), claim))
        edges.append(SemanticEdge(effect_id.value + ":contract", SemanticRelation.HAS_EFFECT,
            source, SemanticEndpoint(SemanticNodeKind.EFFECT, effect_id), claim))
        contract["gaps"] = sorted(set(contract["gaps"]))
        contract_gaps.update(contract["gaps"])
        contracts[definition.id] = (contract, schema)
        definitions.append((definition, tuple(slot.slot_id for slot, rec in owned if rec["direction"] == "input"),
                            tuple(slot.slot_id for slot, rec in owned if rec["direction"] == "output"), effect_id))
    bindings, binding_gaps, annotations, unqualified_instances = [], Counter(), [], []
    instance_counts, qualified_instances = Counter(), set()
    for instance in evidence.instances.values():
        if instance.metadata.get("provider") != "ETO":
            continue
        pair = contracts.get(instance.definition)
        if pair is None:
            actual_slots = instance.metadata.get("tensor_slots", ())
            if actual_slots:
                instance_counts["UNQUALIFIED"] += len(actual_slots)
                unqualified_instances.append({"instance": instance.id.as_dict(),
                    "definition": instance.definition.as_dict(), "actual_tensor_slots": len(actual_slots),
                    "reason": "actual_tensor_slots_have_no_qualified_schema"})
            for actual in actual_slots:
                gap = "actual_tensor_slots_have_no_qualified_schema"
                binding_gaps[gap] += 1
                annotations.append((actual, {"formal_slot": None, "status": "UNQUALIFIED", "gap": gap,
                                             "schema_sha256": None}))
            continue
        contract, schema = pair
        for ordinal, actual in enumerate(instance.metadata.get("tensor_slots", ())):
            role, path = actual.get("role"), actual.get("ordered_path")
            gap, formal_id = None, None
            if "variadic_schema_not_qualified" in contract["gaps"]:
                gap = "variadic_schema_not_qualified"
            elif role not in ("inputs", "outputs") or type(path) is not list or not path:
                gap = "actual_slot_has_no_supported_formal_coordinate"
            else:
                formals = schema.arguments if role == "inputs" else schema.returns
                ids = contract["input_slots" if role == "inputs" else "output_slots"]
                if type(path[0]) is not int or not 0 <= path[0] < len(formals):
                    gap = "formal_ordinal_outside_schema"
                else:
                    formal_id = ids[path[0]]
                    try:
                        qualified, gap = _tensor_path(formals[path[0]].type, path[1:])
                    except Exception:
                        qualified, gap = False, "formal_container_type_not_exposed"
                    if not qualified:
                        formal_id = None
            if actual.get("provider_reference") not in evidence.provider_references:
                raise ValueError("actual native schema slot refers to an absent provider reference")
            status = "QUALIFIED" if gap is None else "UNQUALIFIED"
            binding = {"instance": instance.id.as_dict(), "definition": instance.definition.as_dict(),
                "actual_tensor_slot_index": ordinal, "role": role, "ordered_path": path,
                "formal_slot": formal_id, "provider_reference": actual["provider_reference"],
                "raw_reference": actual["raw_reference"], "schema_sha256": contract["schema_sha256"],
                "status": status, "gap": gap,
                "basis": "ETO schema-ordered boxed arguments/returns; exact provider leaf coordinate"}
            bindings.append(binding)
            annotations.append((actual, {"formal_slot": formal_id, "status": status,
                "gap": gap, "schema_sha256": contract["schema_sha256"]}))
            instance_counts[status] += 1
            if gap is not None:
                binding_gaps[gap] += 1
            else:
                qualified_instances.add(instance.id)
    # Attach only after all contracts and actual coordinates have been checked.
    for slot in slots:
        graph.add_slot(slot)
    for effect in effects:
        graph.add_effect(effect)
    for definition, inputs, outputs, effect_id in definitions:
        definition.input_slots, definition.output_slots = inputs, outputs
        definition.effect_summary = effect_id
        definition.metadata["native_schema_contract"] = contracts[definition.id][0]
    for edge in edges:
        graph.add_edge(edge)
    for actual, annotation in annotations:
        actual["native_schema_binding"] = annotation
    native_result.bundle.assert_valid()
    report = {"schema": "scar.native-schema-bridge", "schema_version": 1,
        "provider_revision": provider_revision, "parser_torch_version": torch.__version__,
        "scope": scope, "unique_schemas_parsed": len(parsed), "parse_failures": list(failures.values()),
        "definitions_with_ports": len(definitions), "formal_slots": len(slots), "effect_summaries": len(effects),
        "instances_with_qualified_tensor_slots": len(qualified_instances),
        "actual_tensor_slot_counts": dict(instance_counts), "bindings": bindings,
        "unqualified_without_schema": unqualified_instances,
        "contract_gaps": dict(contract_gaps), "binding_gaps": dict(binding_gaps),
        "conditions": ["schema-ordered boxed ETO slots follow the pinned provider serializer contract",
            "formal schema effects are declarations and remain partial",
            "Tensor/container metadata paths are preserved; scalar arguments are not re-read"],
        "actual_mutation_proven": False, "alias_lifetimes_established": False,
        "canonical_state_accesses_established": False, "logical_versions_established": False,
        "physical_copy_established": False, "resource_readiness_established": False,
        "whole_model_established": False, "transformation_authorized": False}
    native_result.report["native_schema"] = report
    return report


__all__ = ["recover_schema_contracts", "PROVIDER_REVISION"]
