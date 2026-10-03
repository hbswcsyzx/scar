"""Static-value substitution bridges into OIR with typed, source-bound joins."""
from copy import deepcopy
from dataclasses import replace
import hashlib

import pytest

import scar.ir.v2 as ir
from scar.ir.literals import LiteralKind, PythonLiteral
from scar.ir.semantics_v2 import (
    BindingUseID,
    Opcode,
    OperationSemantics,
    SourceSemanticsGraph,
    SourceSnapshot,
    StaticBinding,
    StaticBindingID,
    StaticValue,
    StaticValueID,
)
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import OperationDefinitionID, SourceAtomID, ValueSlotID
from scar.ir.v2.semantic import OperationDefinition, OperationKind, SourceAtom, ValueSlot


def _fixture():
    semantic = ir.SemanticGraph()
    scope = OperationDefinitionID("module")
    semantic.definitions[scope] = OperationDefinition(scope, OperationKind.MODULE, "module")
    path = "/fixture/static.py"
    fingerprint = "sha256:" + hashlib.sha256(b"x = 3\ny = x\n").hexdigest()
    graph = SourceSemanticsGraph(sources={path: SourceSnapshot(path, fingerprint)})

    def add(name, position, opcode, operands=(), literal=None):
        operation = OperationDefinitionID(name)
        reference = SourceReference(SourceAtomID(name), path, fingerprint,
                                    position + 1, position + 1)
        semantic.source_atoms[reference.atom_id] = SourceAtom(
            reference.atom_id, reference, "expression")
        semantic.definitions[operation] = OperationDefinition(
            operation, OperationKind.OPERATOR, name, source_file=path,
            parent_id=scope, source_atoms=(reference.atom_id,))
        value = StaticValueID(name)
        graph.values[value] = StaticValue(value, operation, scope, reference)
        graph.operations[operation] = OperationSemantics(
            operation, scope, "entry", position, opcode, operands, value,
            reference, literal=literal)
        return operation, value, reference

    literal_op, literal_value, _ = add(
        "literal", 0, Opcode.LITERAL, literal=PythonLiteral.from_python(3))
    alias_op, alias_value, alias_source = add(
        "alias", 1, Opcode.ALIAS,
        (ir_source_operand("value", 0, literal_value),))
    slot = ValueSlotID("x")
    semantic.slots[slot] = ValueSlot(slot, "x", "state", owner=scope)
    binding_id = StaticBindingID("x0")
    graph.bindings[binding_id] = StaticBinding(
        binding_id, slot, alias_op, alias_value, scope, "entry", 1, 0,
        alias_source)
    graph.assert_valid(semantic)

    evidence, values = ir.EvidenceGraph(), ir.ValueGraph()
    return graph, semantic, evidence, values, alias_op, alias_value, alias_source, binding_id


def ir_source_operand(role, index, value):
    from scar.ir.semantics_v2 import OperandUse

    return OperandUse(role, index, value)


def _graph(static, semantic, evidence, values, operation, value, source,
           binding=None, *, region_operation=None, region_source=None):
    graph = ir.OptimizationGraph(
        ir.optimization_context(semantic, evidence, values, static))
    region_id = ir.OptimizationRegionID("region")
    graph.add_region(ir.OptimizationRegion(
        region_id, ir.RegionGranularity.REGION, "target",
        definitions=(region_operation or operation,),
        source_atoms=((region_source or source).atom_id,)))
    original_id = ir.PlanAlternativeID("original")
    graph.add_alternative(ir.PlanAlternative(
        original_id, region_id, "original", ir.TransformKind.NO_OP, original=True))
    substitution = ir.StaticValueSubstitution(
        value, operation, source, PythonLiteral.from_python((None, b"\x00", float("nan"))),
        binding)
    graph.add_alternative(ir.PlanAlternative(
        ir.PlanAlternativeID("static-rewrite"), region_id, "static rewrite",
        ir.TransformKind.SUBSTITUTE,
        delta=ir.TransformDelta(static_substitutions=(substitution,)),
        fallback=original_id))
    return graph, substitution


def _bundle(*, binding=None):
    static, semantic, evidence, values, operation, value, source, binding_id = _fixture()
    graph, substitution = _graph(static, semantic, evidence, values, operation,
                                value, source, binding if binding is not None else binding_id)
    return (ir.IRBundle(semantic, evidence, values, optimization=graph,
                        source_semantics=static), static, semantic, evidence,
            values, operation, value, source, binding_id, graph, substitution)


def test_static_ids_and_literals_keep_their_existing_public_identity():
    import scar.ir.semantics_v2 as static_api

    assert static_api.StaticValueID is StaticValueID is ir.StaticValueID
    assert static_api.StaticBindingID is StaticBindingID is ir.StaticBindingID
    assert static_api.BindingUseID is BindingUseID is ir.BindingUseID
    assert static_api.PythonLiteral is PythonLiteral is ir.PythonLiteral
    assert static_api.LiteralKind is LiteralKind is ir.LiteralKind
    assert StaticValueID("x").wire == "static_value:x"
    assert StaticBindingID("x").wire == "static_binding:x"


def test_static_substitution_roundtrips_with_real_value_operation_span_and_binding():
    bundle, static, *_rest, graph, substitution = _bundle()
    assert not graph.alternatives[next(
        key for key in graph.alternatives if key.value == "static-rewrite")].delta.is_empty
    assert bundle.validate()["valid"]

    encoded = ir.canonical_json(bundle)
    document = bundle.to_dict()
    assert document["schema_version"] == 2
    assert document["optimization"]["schema_version"] == 3
    restored = ir.IRBundle.from_json(encoded)
    actual = restored.optimization.alternatives[ir.PlanAlternativeID("static-rewrite")]
    restored_substitution = actual.delta.static_substitutions[0]
    assert restored_substitution == substitution
    assert restored_substitution.literal.as_dict() == substitution.literal.as_dict()
    assert restored.source_semantics.to_dict() == static.to_dict()
    assert ir.canonical_json(restored) == encoded


def test_static_substitution_decoder_rejects_a_dynamic_or_wrong_namespace_id():
    bundle, *_ = _bundle()
    document = bundle.to_dict()
    alt = next(item for item in document["optimization"]["alternatives"]
               if item["id"]["value"] == "static-rewrite")
    alt["delta"]["static_substitutions"][0]["static_value"] = ir.ValueSlotID("forged").as_dict()
    with pytest.raises(ValueError):
        ir.IRBundle.from_dict(document)


def test_static_substitution_never_uses_dynamic_value_version_namespace():
    bundle, _, _, _, _, _, _, _, _, graph, _ = _bundle()
    substitution = graph.alternatives[ir.PlanAlternativeID("static-rewrite")].delta.static_substitutions[0]
    assert type(substitution.static_value) is StaticValueID
    assert not isinstance(substitution.static_value, ir.ValueVersionID)
    assert substitution.static_value.wire.startswith("static_value:")
    assert bundle.validate()["valid"]


@pytest.mark.parametrize("corruption", ("unknown_value", "wrong_operation", "wrong_source", "external"))
def test_static_value_source_join_rejects_forged_or_external_records(corruption):
    bundle, static, _, _, _, operation, value, source, binding_id, graph, sub = _bundle()
    if corruption == "unknown_value":
        graph.alternatives[ir.PlanAlternativeID("static-rewrite")].delta = ir.TransformDelta(
            static_substitutions=(replace(sub, static_value=StaticValueID("missing")),))
    elif corruption == "wrong_operation":
        wrong = OperationDefinitionID("literal")
        graph.alternatives[ir.PlanAlternativeID("static-rewrite")].delta = ir.TransformDelta(
            static_substitutions=(replace(sub, operation=wrong),))
    elif corruption == "wrong_source":
        forged = replace(source, end_column=100)
        graph.alternatives[ir.PlanAlternativeID("static-rewrite")].delta = ir.TransformDelta(
            static_substitutions=(replace(sub, source=forged),))
    else:
        static.values[value] = replace(static.values[value], producer=None, external=True)
        graph.context = ir.optimization_context(bundle.semantic, bundle.evidence,
                                                bundle.values, static)

    report = bundle.validate()
    assert not report["valid"]
    assert any("static" in error or "producer" in error or "external" in error
               for error in report["errors"])


def test_static_binding_is_the_replaced_binding_and_must_match_region_operation_and_span():
    bundle, static, _, _, _, operation, value, source, binding_id, graph, sub = _bundle()
    binding = static.bindings[binding_id]
    graph.context.static_bindings[binding_id] = ir.StaticBindingInfo(
        binding.value, OperationDefinitionID("outside"), binding.source)
    report = graph.validate()
    assert not report["valid"]
    assert any("binding definition" in error for error in report["errors"])

    graph.context = ir.optimization_context(bundle.semantic, bundle.evidence,
                                            bundle.values, static)
    graph.alternatives[ir.PlanAlternativeID("static-rewrite")].delta = ir.TransformDelta(
        static_substitutions=(replace(sub, source=replace(source, end_column=44)),))
    assert any("binding source" in error or "producer span" in error
               for error in graph.validate()["errors"])


def test_context_mappings_are_revalidated_and_bundle_rebuilds_them_from_overlay():
    bundle, static, _, _, _, _, _, _, _, graph, _ = _bundle()
    original = static.values[StaticValueID("alias")]
    extra = StaticValueID("external")
    static.values[extra] = StaticValue(
        extra, None, original.scope, original.source, external=True)
    assert graph.validate()["valid"]
    report = bundle.validate()
    assert not report["valid"]
    assert any("optimization context does not match bundle graphs" in error
               for error in report["errors"])

    graph.context = ir.optimization_context(
        bundle.semantic, bundle.evidence, bundle.values, static)
    value_id = next(iter(graph.context.static_values))
    graph.context.static_values[value_id] = "forged"
    assert not graph.validate()["valid"]
    assert any("static_values" in error for error in graph.validate()["errors"])
    report = bundle.validate()
    assert not report["valid"]


def _legacy_bundle(bundle, optimization_version):
    document = bundle.to_dict()
    document["schema_version"] = 1
    document.pop("source_semantics")
    optimization = document["optimization"]
    optimization["schema_version"] = optimization_version
    for alternative in optimization["alternatives"]:
        alternative["delta"].pop("static_substitutions")
    if optimization_version == 1:
        for port in optimization["ports"]:
            for key in ("slot", "effect", "operation"):
                port.pop(key)
    return document


@pytest.mark.parametrize("optimization_version", (1, 2))
def test_legacy_bundle_and_optimization_schemas_upgrade_without_mutating_input(optimization_version):
    bundle, *_ = _bundle()
    document = _legacy_bundle(bundle, optimization_version)
    before = deepcopy(document)
    restored = ir.IRBundle.from_dict(document)
    assert document == before
    assert restored.source_semantics is None
    assert restored.optimization.to_dict()["schema_version"] == 3
    assert restored.to_dict()["schema_version"] == 2


@pytest.mark.parametrize("version,field", ((1, "source_semantics"), (1, "static_substitutions"),
                                             (2, "static_substitutions")))
def test_legacy_versions_reject_smuggled_new_fields_even_when_empty(version, field):
    bundle, *_ = _bundle()
    document = _legacy_bundle(bundle, version)
    if field == "source_semantics":
        document["source_semantics"] = None
    else:
        document["optimization"]["alternatives"][0]["delta"][field] = []
    with pytest.raises(ValueError, match="unknown fields|fields mismatch"):
        ir.IRBundle.from_dict(document)


def test_legacy_bundle_cannot_wrap_a_newer_optimization_schema():
    bundle, *_ = _bundle()
    document = bundle.to_dict()
    document["schema_version"] = 1
    document.pop("source_semantics")
    with pytest.raises(ValueError, match="cannot contain a newer optimization"):
        ir.IRBundle.from_dict(document)


@pytest.mark.parametrize("field", ("source_semantics", "static_substitutions"))
def test_current_schema_requires_its_new_fields(field):
    bundle, *_ = _bundle()
    document = bundle.to_dict()
    if field == "source_semantics":
        document.pop(field)
    else:
        document["optimization"]["alternatives"][0]["delta"].pop(field)
    with pytest.raises(ValueError, match="missing (required )?field"):
        ir.IRBundle.from_dict(document)


def test_static_substitution_makes_original_noop_delta_nonempty():
    with pytest.raises(ValueError, match="original alternative must be an empty NO_OP"):
        ir.PlanAlternative(
            ir.PlanAlternativeID("bad-original"), ir.OptimizationRegionID("region"),
            "original", ir.TransformKind.NO_OP,
            delta=ir.TransformDelta(static_substitutions=(
                ir.StaticValueSubstitution(
                    StaticValueID("v"), OperationDefinitionID("op"),
                    SourceReference(SourceAtomID("src"), "/x.py", "fp", 1, 1),
                    PythonLiteral.from_python(1)),)),
            original=True)
