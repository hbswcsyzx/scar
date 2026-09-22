"""Static identity/codec adversaries, independent of source extractor/evaluator."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import struct

import pytest

from scar.ir.record_codec import decode, encode
from scar.ir.semantics_v2 import (
    BindingStatus, BindingUse, BindingUseID, ImportSpec, LiteralKind, Opcode,
    OperandUse, OperationSemantics, PythonLiteral, SemanticGap, SourceSemanticsGraph,
    SourceSnapshot, StaticBinding, StaticBindingID, StaticValue, StaticValueID,
    SourceExecutionPrecondition,
)
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import OperationDefinitionID, SourceAtomID, ValueSlotID
from scar.ir.v2.semantic import (
    OperationDefinition, OperationKind, SemanticGraph, SourceAtom, ValueSlot,
)


def model_fixture():
    semantic = SemanticGraph()
    scope = OperationDefinitionID("module")
    semantic.definitions[scope] = OperationDefinition(scope, OperationKind.MODULE, "module")
    path = "/fixture/program.py"
    fingerprint = "sha256:" + hashlib.sha256(b"x = 2\ny = x\n").hexdigest()
    graph = SourceSemanticsGraph(sources={path: SourceSnapshot(path, fingerprint)})

    def add(name, opcode, position, operands=(), **kwargs):
        operation = OperationDefinitionID(name)
        reference = SourceReference(SourceAtomID(name), path, fingerprint, position + 1, position + 1)
        semantic.source_atoms[reference.atom_id] = SourceAtom(reference.atom_id, reference, "expression")
        semantic.definitions[operation] = OperationDefinition(
            operation, OperationKind.OPERATOR, name, source_file=path,
            parent_id=scope, source_atoms=(reference.atom_id,))
        value = StaticValueID(name)
        graph.values[value] = StaticValue(value, operation, scope, reference)
        graph.operations[operation] = OperationSemantics(
            operation, scope, "entry", position, opcode, operands, value, reference, **kwargs)
        return operation, value, reference

    literal, value, reference = add("literal", Opcode.LITERAL, 0, literal=PythonLiteral.from_python(2))
    assign, assigned, assign_source = add("assign", Opcode.ALIAS, 1, (OperandUse("value", 0, value),))
    other, other_value, other_source = add("other", Opcode.LITERAL, 2, literal=PythonLiteral.from_python(7))
    slot = ValueSlotID("x")
    semantic.slots[slot] = ValueSlot(slot, "x", "state", owner=scope)
    binding_id = StaticBindingID("x0")
    graph.bindings[binding_id] = StaticBinding(binding_id, slot, assign, assigned,
                                               scope, "entry", 1, 0, assign_source)
    use_id = BindingUseID("read-x")
    read, _, read_source = add("read", Opcode.READ, 3, binding_use=use_id)
    graph.uses[use_id] = BindingUse(use_id, read, slot, scope, "entry", 3,
                                   (binding_id,), BindingStatus.EXACT, read_source)
    graph.assert_valid(semantic)
    return graph, semantic, add


@pytest.mark.parametrize("value", (None, Ellipsis, True, False, 0, -(2**300), "é\x00", b"\x00\xff", (1, True, (None, b"x"))))
def test_exact_literal_preserves_python_type_and_nested_immutable_content(value):
    literal = PythonLiteral.from_python(value)
    result = decode(PythonLiteral, encode(literal)).to_python()
    assert type(result) is type(value)
    assert result == value


@pytest.mark.parametrize("bits", ("0000000000000000", "8000000000000000", "7ff0000000000000", "fff0000000000000", "7ff8000000000001", "7ff8000000000002"))
def test_float_literal_preserves_signed_zero_infinity_and_nan_payload(bits):
    value = struct.unpack(">d", bytes.fromhex(bits))[0]
    literal = PythonLiteral.from_python(value)
    assert literal.kind is LiteralKind.FLOAT64
    assert literal.payload == bits
    encoded = json.dumps(encode(literal), allow_nan=False)
    restored = decode(PythonLiteral, json.loads(encoded)).to_python()
    assert struct.pack(">d", restored).hex() == bits


@pytest.mark.parametrize("value", ([], {}, set(), [1], ([],), 1j, type("IntSubclass", (int,), {})(2)))
def test_mutable_values_and_user_types_are_not_immutable_literals(value):
    with pytest.raises(TypeError):
        PythonLiteral.from_python(value)


@pytest.mark.parametrize("kind,payload", ((LiteralKind.INT, "01"), (LiteralKind.INT, "-0"),
    (LiteralKind.INT, True), (LiteralKind.BOOL, 1), (LiteralKind.FLOAT64, "nan"),
    (LiteralKind.FLOAT64, "7FF8000000000001"), (LiteralKind.BYTES, "f"),
    (LiteralKind.NONE, "none"), (LiteralKind.TUPLE, "[]")))
def test_noncanonical_or_type_erasing_literal_wire_is_rejected(kind, payload):
    with pytest.raises((TypeError, ValueError)):
        PythonLiteral(kind, payload)


def test_static_ids_do_not_alias_dynamic_or_binding_namespaces():
    value, binding, use = StaticValueID("same"), StaticBindingID("same"), BindingUseID("same")
    assert len({value, binding, use, OperationDefinitionID("same")}) == 4
    with pytest.raises(ValueError, match="namespace"):
        decode(StaticValueID, encode(binding))


def test_deterministic_roundtrip_preserves_repeated_operand_order_and_proof_limit():
    graph, semantic, add = model_fixture()
    left, right = StaticValueID("literal"), StaticValueID("other")
    op, _, _ = add("tuple", Opcode.BUILD_TUPLE, 4,
                   (OperandUse("item", 0, right), OperandUse("item", 1, left), OperandUse("item", 2, right)))
    payload = graph.to_json()
    restored = SourceSemanticsGraph.from_json(payload, semantic)
    assert restored.operations[op].operands == graph.operations[op].operands
    graph.operations = dict(reversed(tuple(graph.operations.items())))
    assert graph.to_json() == payload == restored.to_json()
    report = restored.validate(semantic)
    assert report["semantic_references_checked"]
    assert report["source_replay_checked"] is False


@pytest.mark.parametrize("registry", ("sources", "operations", "values", "bindings", "uses"))
def test_duplicate_wire_identity_fails_before_overwriting(registry):
    graph, _, _ = model_fixture()
    document = graph.to_dict()
    document[registry].append(deepcopy(document[registry][0]))
    with pytest.raises(ValueError, match="duplicate"):
        SourceSemanticsGraph.from_dict(document)


@pytest.mark.parametrize("mutation", ("version_bool", "version_new", "extra", "missing", "wrong_id", "unknown_enum"))
def test_schema_and_nested_wire_corruption_rejected(mutation):
    graph, _, _ = model_fixture()
    document = graph.to_dict()
    if mutation == "version_bool":
        document["schema_version"] = True
    elif mutation == "version_new":
        document["schema_version"] = 999
    elif mutation == "extra":
        document["operations"][0]["verified"] = True
    elif mutation == "missing":
        del document["gaps"]
    elif mutation == "wrong_id":
        document["values"][0]["id"] = encode(StaticBindingID("forged"))
    else:
        document["operations"][0]["opcode"] = "trust_me_pure"
    with pytest.raises(ValueError):
        SourceSemanticsGraph.from_dict(document)


def test_duplicate_json_fields_and_nonfinite_numbers_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        SourceSemanticsGraph.from_json('{"schema":1,"schema":2}')
    with pytest.raises(ValueError, match="non-finite"):
        SourceSemanticsGraph.from_json('{"schema":1e999}')


@pytest.mark.parametrize("field,value", (("scope", OperationDefinitionID("elsewhere")), ("block", "other"), ("position", 0)))
def test_exact_binding_cannot_cross_scope_block_or_reach_back_from_future(field, value):
    graph, _, _ = model_fixture()
    use_id = BindingUseID("read-x")
    graph.uses[use_id] = replace(graph.uses[use_id], **{field: value})
    errors = graph.validate()["errors"]
    assert any("same-scope/block nonfuture" in error for error in errors)


def test_intervening_registered_write_invalidates_old_exact_binding():
    graph, _, _ = model_fixture()
    old = graph.bindings[StaticBindingID("x0")]
    other = graph.operations[OperationDefinitionID("other")]
    later = replace(old, id=StaticBindingID("x1"), definition=other.operation,
                    value=other.result, position=other.position, epoch=1, source=other.source)
    graph.bindings[later.id] = later
    assert any("latest preceding" in x for x in graph.validate()["errors"])
    use = graph.uses[BindingUseID("read-x")]
    graph.uses[use.id] = replace(use, reaching=(later.id,))
    assert graph.validate()["valid"]


def test_dangling_slot_and_forged_source_span_fail_semantic_join():
    graph, semantic, _ = model_fixture()
    use = graph.uses[BindingUseID("read-x")]
    del semantic.slots[use.slot]
    assert any("missing semantic slot" in error for error in graph.validate(semantic)["errors"])
    graph, semantic, _ = model_fixture()
    op = graph.operations[OperationDefinitionID("literal")]
    forged = replace(op.source, end_column=999)
    graph.operations[op.operation] = replace(op, source=forged)
    graph.values[op.result] = replace(graph.values[op.result], source=forged)
    assert graph.validate()["valid"]  # Structural coherence alone cannot prove source truth.
    assert any("source reference does not match" in x for x in graph.validate(semantic)["errors"])


def test_snapshot_fingerprint_and_result_producer_are_checked():
    graph, _, _ = model_fixture()
    path = next(iter(graph.sources))
    graph.sources[path] = replace(graph.sources[path], fingerprint="sha256:" + "0" * 64)
    assert any("fingerprint differs" in x for x in graph.validate()["errors"])
    graph, _, _ = model_fixture()
    value = graph.values[StaticValueID("read")]
    graph.values[value.id] = replace(value, producer=OperationDefinitionID("literal"))
    assert any("producer" in x for x in graph.validate()["errors"])


def test_value_dependency_cycle_is_rejected_even_with_consistent_ids():
    graph, _, _ = model_fixture()
    op = graph.operations[OperationDefinitionID("assign")]
    graph.operations[op.operation] = replace(op, operands=(OperandUse("value", 0, StaticValueID("read")),))
    assert "cyclic static value dependency" in graph.validate()["errors"]


def test_unresolved_bindings_and_opaque_operations_require_actionable_gaps():
    graph, semantic, _ = model_fixture()
    use = graph.uses[BindingUseID("read-x")]
    graph.uses[use.id] = replace(use, reaching=(), status=BindingStatus.UNRESOLVED)
    assert not graph.validate()["valid"]
    graph.gaps = (SemanticGap("parameter depends on caller", use=use.id,
                             source=use.source, required_fact="caller binding context"),)
    assert graph.validate(semantic)["valid"]
    op = graph.operations[OperationDefinitionID("other")]
    graph.operations[op.operation] = replace(op, opcode=Opcode.OPAQUE, literal=None)
    assert not graph.validate()["valid"]
    graph.gaps += (SemanticGap("unsupported expression", operation=op.operation,
                              required_fact="typed expression semantics"),)
    assert graph.validate(semantic)["valid"]


def test_unmodeled_source_operation_coverage_is_explicit_and_roundtrips():
    graph, semantic, _ = model_fixture()
    scope = OperationDefinitionID("module")
    graph.unmodeled_operations = (scope,)
    graph.gaps = (SemanticGap("scope wrapper has no expression value", operation=scope,
                             required_fact="module initialization semantics"),)
    assert SourceSemanticsGraph.from_json(graph.to_json(), semantic).unmodeled_operations == (scope,)
    graph.unmodeled_operations += (scope,)
    assert "duplicate unmodeled operation" in graph.validate()["errors"]


@pytest.mark.parametrize("corruption", ("no_gap", "overlap", "missing_sg", "dangling_gap"))
def test_unmodeled_operation_coverage_cannot_silently_drop_or_forge_ids(corruption):
    graph, semantic, _ = model_fixture()
    identifier = OperationDefinitionID("module")
    if corruption == "overlap":
        identifier = OperationDefinitionID("literal")
    elif corruption == "missing_sg":
        identifier = OperationDefinitionID("missing")
    graph.unmodeled_operations = () if corruption == "dangling_gap" else (identifier,)
    if corruption != "no_gap":
        graph.gaps = (SemanticGap("unmodeled", operation=identifier, required_fact="typed semantics"),)
    assert not graph.validate(semantic)["valid"]


def test_mutable_container_recipe_is_distinct_from_immutable_tuple_literal():
    graph, semantic, add = model_fixture()
    op, _, _ = add("list", Opcode.BUILD_LIST, 5, (OperandUse("item", 0, StaticValueID("literal")),))
    assert graph.operations[op].literal is None
    assert graph.validate(semantic)["valid"]
    with pytest.raises(ValueError, match="literal payload"):
        replace(graph.operations[op], literal=PythonLiteral.from_python((2,)))


def test_malformed_in_memory_collections_return_invalid_report_without_crashing():
    graph, _, _ = model_fixture()
    graph.values = None
    report = graph.validate()
    assert not report["valid"]
    assert report["counts"]["values"] is None


def test_relative_import_without_module_name_is_representable_but_not_certified():
    item = ImportSpec("", symbol="CONFIG", relative_level=1)
    assert decode(ImportSpec, encode(item)) == item
    with pytest.raises(ValueError):
        ImportSpec("")


@pytest.mark.parametrize("mutation", ("omit", "drop", "duplicate", "accepted_fact"))
def test_source_execution_contracts_cannot_be_omitted_or_upgraded_in_wire(mutation):
    graph, _, _ = model_fixture()
    document = graph.to_dict()
    if mutation == "omit":
        del document["required_preconditions"]
    elif mutation == "drop":
        document["required_preconditions"].pop()
    elif mutation == "duplicate":
        document["required_preconditions"][1] = document["required_preconditions"][0]
    else:
        document["required_preconditions"][0] = "observed_fresh_namespace"
    with pytest.raises(ValueError):
        SourceSemanticsGraph.from_dict(document)


def test_source_execution_contracts_roundtrip_as_undischarged_preconditions():
    graph, semantic, _ = model_fixture()
    restored = SourceSemanticsGraph.from_json(graph.to_json(), semantic)
    assert set(restored.required_preconditions) == set(SourceExecutionPrecondition)
    assert restored.validate(semantic)["source_replay_checked"] is False
    graph.required_preconditions = ()
    assert not graph.validate()["valid"]


def test_exact_surrogate_string_survives_json_utf8_without_replacement():
    graph, semantic, _ = model_fixture()
    op = graph.operations[OperationDefinitionID("literal")]
    graph.operations[op.operation] = replace(op, literal=PythonLiteral.from_python("\ud800\x00é"))
    payload = graph.to_json().encode("utf-8")
    restored = SourceSemanticsGraph.from_json(payload.decode("utf-8"), semantic)
    assert restored.operations[op.operation].literal.to_python() == "\ud800\x00é"
