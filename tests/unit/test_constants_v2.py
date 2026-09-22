from copy import deepcopy
from dataclasses import replace
import json
import struct

import pytest

from scar.analysis.constants_v2 import (
    ConstantReport, ConstantStatus, ConstantRuntimeRequirement, ContractAcceptance,
    EvaluationBudget, RuntimeValidation, SourceValidation, evaluate_constants,
)
from scar.ir import semantics_v2 as sm
from scar.ir.v2 import OperationDefinitionID, SourceAtomID, SourceReference, ValueSlotID


class Model:
    """Manual typed models deliberately carry no source-replay attestation."""
    def __init__(self):
        self.graph = sm.SourceSemanticsGraph()
        self.path, self.fingerprint = "manual.py", "sha256:" + "0" * 64
        self.graph.sources[self.path] = sm.SourceSnapshot(self.path, self.fingerprint)
        self.scope = OperationDefinitionID("scope")
        self.count = 0

    def operation(self, name, opcode, *inputs, literal=None, **kwargs):
        self.count += 1
        operation, value = OperationDefinitionID(name), sm.StaticValueID(name)
        source = SourceReference(SourceAtomID(name), self.path, self.fingerprint, self.count, self.count)
        operands = tuple(sm.OperandUse("item", index, item) for index, item in enumerate(inputs))
        self.graph.operations[operation] = sm.OperationSemantics(
            operation, self.scope, "body", self.count, opcode, operands, value, source,
            literal=literal, **kwargs)
        self.graph.values[value] = sm.StaticValue(value, operation, self.scope, source)
        return value

    def literal(self, name, value):
        return self.operation(name, sm.Opcode.LITERAL, literal=sm.PythonLiteral.from_python(value))

    def bind(self, name, value, epoch):
        result = self.operation(f"bind-{name}-{epoch}", sm.Opcode.ALIAS, value)
        operation = self.graph.operations[self.graph.values[result].producer]
        binding = sm.StaticBinding(sm.StaticBindingID(f"{name}-{epoch}"), ValueSlotID(name),
            operation.operation, result, self.scope, "body", operation.position, epoch, operation.source)
        self.graph.bindings[binding.id] = binding
        return binding.id

    def read(self, name, binding, *, exact=True):
        use_id = sm.BindingUseID(name)
        result = self.operation(name, sm.Opcode.READ, binding_use=use_id)
        operation = self.graph.operations[self.graph.values[result].producer]
        slot = self.graph.bindings[binding].slot
        use = sm.BindingUse(use_id, operation.operation, slot, self.scope, "body", operation.position,
                            (binding,) if exact else (), sm.BindingStatus.EXACT if exact else sm.BindingStatus.UNRESOLVED,
                            operation.source)
        self.graph.uses[use_id] = use
        if not exact:
            self.graph.gaps += (sm.SemanticGap("opaque mutation boundary", operation.operation, use_id,
                                              operation.source, "reaching definition after opaque call"),)
        return result


def test_ordered_noncommutative_operands_and_duplicate_uses_have_distinct_proof_premises():
    model = Model()
    a, b = model.literal("a", 10), model.literal("b", 3)
    forward = model.operation("forward", sm.Opcode.SUB, a, b)
    reverse = model.operation("reverse", sm.Opcode.SUB, b, a)
    duplicate = model.operation("duplicate", sm.Opcode.ADD, a, a)
    report = evaluate_constants(model.graph)
    assert report.facts[forward].literal.to_python() == 7
    assert report.facts[reverse].literal.to_python() == -7
    proof = report.proofs[report.facts[duplicate].proof_id]
    assert proof.premises == (report.facts[a].proof_id, report.facts[a].proof_id)
    assert report.facts[duplicate].literal.to_python() == 20
    assert report.assert_valid()["valid"]


def test_name_rebinding_uses_latest_definition_at_each_read():
    model = Model()
    first = model.bind("x", model.literal("one", 1), 0)
    before = model.read("before", first)
    second = model.bind("x", model.literal("two", 2), 1)
    after = model.read("after", second)
    report = evaluate_constants(model.graph)
    assert report.facts[before].literal.to_python() == 1
    assert report.facts[after].literal.to_python() == 2
    assert report.proofs[report.facts[before].proof_id].binding_uses == (sm.BindingUseID("before"),)


def test_opaque_binding_does_not_erase_independent_constant_call_argument():
    model = Model()
    first = model.bind("x", model.literal("seven", 7), 0)
    argument = model.operation("sum", sm.Opcode.ADD, model.literal("two", 2), model.literal("three", 3))
    call = model.operation("call", sm.Opcode.CALL, argument)
    after = model.read("after", first, exact=False)
    report = evaluate_constants(model.graph, targets=(call, after))
    assert report.facts[argument].literal.to_python() == 5
    assert report.facts[call].status is ConstantStatus.NOT_CONSTANT
    assert report.facts[after].status is ConstantStatus.NOT_CONSTANT


def test_exact_builtin_types_float_bits_and_surrogate_strings_are_preserved():
    model = Model()
    inputs = [None, Ellipsis, True, 1, -0.0, 0.0, b"a\x00", "a\x00", "\ud800", (True, 1)]
    values = [model.literal(str(index), value) for index, value in enumerate(inputs)]
    report = evaluate_constants(model.graph)
    assert report.facts[values[2]].literal.kind is sm.LiteralKind.BOOL
    assert report.facts[values[3]].literal.kind is sm.LiteralKind.INT
    assert report.facts[values[4]].literal.payload == "8000000000000000"
    assert report.facts[values[5]].literal.payload == "0000000000000000"
    assert report.facts[values[6]].literal.kind is sm.LiteralKind.BYTES
    assert report.facts[values[7]].literal.kind is sm.LiteralKind.STR
    assert ConstantReport.from_json(report.to_json(), graph=model.graph).to_dict() == report.to_dict()


@pytest.mark.parametrize("opcode,expected", [(sm.Opcode.BUILD_TUPLE, ConstantStatus.CONSTANT),
                                            (sm.Opcode.BUILD_LIST, ConstantStatus.NOT_CONSTANT),
                                            (sm.Opcode.BUILD_DICT, ConstantStatus.NOT_CONSTANT),
                                            (sm.Opcode.BUILD_SET, ConstantStatus.NOT_CONSTANT)])
def test_mutable_construction_recipe_is_never_shared_immutable_literal(opcode, expected):
    model = Model()
    result = model.operation("container", opcode, model.literal("one", 1), model.literal("two", 2))
    report = evaluate_constants(model.graph, targets=(result,))
    assert report.facts[result].status is expected
    if expected is ConstantStatus.CONSTANT:
        assert report.facts[result].literal.to_python() == (1, 2)
    else:
        assert report.facts[result].literal is None


@pytest.mark.parametrize("opcode,a,b,expected", [
    (sm.Opcode.ADD, 3, 2, 5), (sm.Opcode.SUB, 3, 2, 1), (sm.Opcode.MUL, 3, 2, 6),
    (sm.Opcode.TRUE_DIV, 3, 2, 1.5), (sm.Opcode.FLOOR_DIV, -3, 2, -2),
    (sm.Opcode.MOD, -3, 2, 1), (sm.Opcode.POW, 3, 4, 81),
    (sm.Opcode.LSHIFT, 3, 2, 12), (sm.Opcode.RSHIFT, -9, 2, -3),
    (sm.Opcode.BIT_AND, 3, 2, 2), (sm.Opcode.BIT_OR, 3, 4, 7),
    (sm.Opcode.BIT_XOR, 3, 2, 1), (sm.Opcode.ADD, 0.5, 0.25, 0.75),
    (sm.Opcode.MUL, "é", 3, "ééé"), (sm.Opcode.ADD, b"a", b"b", b"ab"),
    (sm.Opcode.MUL, (1, 2), 2, (1, 2, 1, 2)), (sm.Opcode.INDEX, (1, 2), -1, 2),
    (sm.Opcode.INDEX, b"AB", 0, 65), (sm.Opcode.INDEX, "éa", 0, "é"),
])
def test_fixed_builtin_allowlist(opcode, a, b, expected):
    model = Model()
    result = model.operation("result", opcode, model.literal("a", a), model.literal("b", b))
    report = evaluate_constants(model.graph, targets=(result,))
    assert report.facts[result].status is ConstantStatus.CONSTANT
    actual = report.facts[result].literal.to_python()
    assert type(actual) is type(expected) and actual == expected


@pytest.mark.parametrize("opcode,value,expected", [(sm.Opcode.POS, 3, 3), (sm.Opcode.NEG, 3, -3),
    (sm.Opcode.INVERT, 3, -4), (sm.Opcode.NOT, (), True), (sm.Opcode.NEG, 0.0, -0.0)])
def test_safe_unary_builtins(opcode, value, expected):
    model = Model()
    result = model.operation("result", opcode, model.literal("input", value))
    actual = evaluate_constants(model.graph).facts[result].literal.to_python()
    assert type(actual) is type(expected) and actual == expected
    if type(expected) is float:
        assert struct.pack(">d", actual) == struct.pack(">d", expected)


@pytest.mark.parametrize("opcode,a,b,exception", [
    (sm.Opcode.FLOOR_DIV, 1, 0, "ZeroDivisionError"),
    (sm.Opcode.INDEX, (1,), 3, "IndexError"),
    (sm.Opcode.LSHIFT, 1, -1, "ValueError"),
])
def test_builtin_exception_is_reported_without_literal_or_deletion_claim(opcode, a, b, exception):
    model = Model()
    result = model.operation("result", opcode, model.literal("a", a), model.literal("b", b))
    report = evaluate_constants(model.graph)
    fact = report.facts[result]
    assert fact.status is ConstantStatus.KNOWN_EXCEPTION and fact.exception == exception
    assert fact.literal is None and fact.proof_id is None


@pytest.mark.parametrize("opcode,a,b", [(sm.Opcode.POW, 2, 1000000),
    (sm.Opcode.LSHIFT, 1, 1000000), (sm.Opcode.MUL, "x", 10000000),
    (sm.Opcode.MUL, (1, 2), 10000000)])
def test_oversized_results_rejected_before_builtin_invocation(monkeypatch, opcode, a, b):
    import scar.analysis.constants_v2 as constants
    model = Model()
    result = model.operation("result", opcode, model.literal("a", a), model.literal("b", b))
    def forbidden(*_args):
        pytest.fail("oversized builtin ran before its budget guard")
    monkeypatch.setitem(constants._BINARY, opcode.name, forbidden)
    assert evaluate_constants(model.graph, targets=(result,)).facts[result].status is ConstantStatus.BUDGET_EXCEEDED


def test_cumulative_output_budget_and_work_budget_are_enforced_before_builtin(monkeypatch):
    import scar.analysis.constants_v2 as constants
    model = Model()
    result = model.operation("result", sm.Opcode.ADD, model.literal("a", "abc"), model.literal("b", "def"))
    def forbidden(*_args):
        pytest.fail("builtin ran after cumulative or work budget exhaustion")
    monkeypatch.setitem(constants._BINARY, "ADD", forbidden)
    for budget in (EvaluationBudget(max_total_output_bytes=8), EvaluationBudget(max_work=7)):
        report = evaluate_constants(model.graph, targets=(result,), budget=budget)
        assert report.facts[result].status is ConstantStatus.BUDGET_EXCEEDED
        assert report.usage.output_bytes <= budget.max_total_output_bytes
        assert report.usage.work <= budget.max_work


def test_node_step_container_depth_and_integer_input_limits():
    model = Model()
    result = model.operation("sum", sm.Opcode.ADD, model.literal("a", 1), model.literal("b", 2))
    for budget in (EvaluationBudget(max_nodes=2), EvaluationBudget(max_steps=1)):
        report = evaluate_constants(model.graph, targets=(result,), budget=budget)
        assert report.facts[result].status is ConstantStatus.BUDGET_EXCEEDED
        assert report.usage.nodes <= budget.max_nodes and report.usage.steps <= budget.max_steps
    tuple_value = model.literal("nested", ((1,),))
    assert evaluate_constants(model.graph, targets=(tuple_value,), budget=EvaluationBudget(max_literal_depth=2)).facts[tuple_value].status is ConstantStatus.BUDGET_EXCEEDED
    int_value = model.literal("large-int", 100)
    assert evaluate_constants(model.graph, targets=(int_value,), budget=EvaluationBudget(max_int_bits=2)).facts[int_value].status is ConstantStatus.BUDGET_EXCEEDED


def test_import_attribute_user_dispatch_and_bool_arithmetic_require_more_than_literals(tmp_path):
    model = Model()
    imported = model.operation("import", sm.Opcode.IMPORT, import_spec=sm.ImportSpec("arbitrary_package"))
    attr = model.operation("attribute", sm.Opcode.ATTRIBUTE, imported, attribute="value")
    custom = model.operation("custom", sm.Opcode.ADD, model.literal("a", 1), model.literal("b", 2),
                             dispatch=sm.DispatchKind.USER_DEFINED)
    boolean = model.operation("bool-add", sm.Opcode.ADD, model.literal("true", True), model.literal("one", 1))
    marker = tmp_path / "executed"
    text = model.literal("code-string", f"__import__('pathlib').Path({str(marker)!r}).write_text('bad')")
    report = evaluate_constants(model.graph)
    assert report.facts[imported].status is ConstantStatus.NEEDS_CONTRACT
    assert report.facts[attr].status is ConstantStatus.NEEDS_CONTRACT
    assert report.facts[custom].status is ConstantStatus.NOT_CONSTANT
    assert report.facts[boolean].status is ConstantStatus.NOT_CONSTANT
    assert report.facts[text].status is ConstantStatus.CONSTANT and not marker.exists()
    assert report.source_validation is SourceValidation.NOT_CHECKED


def test_deterministic_proof_dag_and_strict_report_roundtrip():
    model = Model()
    result = model.operation("result", sm.Opcode.ADD, model.literal("a", 2), model.literal("b", 3))
    first = evaluate_constants(model.graph)
    model.graph.operations = dict(reversed(list(model.graph.operations.items())))
    model.graph.values = dict(reversed(list(model.graph.values.items())))
    second = evaluate_constants(model.graph)
    assert first.to_dict() == second.to_dict()
    assert all(premise in first.proofs for proof in first.proofs.values() for premise in proof.premises)
    assert ConstantReport.from_json(first.to_json(), graph=model.graph).to_dict() == first.to_dict()
    assert first.facts[result].literal.to_python() == 5


@pytest.mark.parametrize("tamper", ["literal", "status", "premises", "proof_cycle", "digest", "runtime", "source_status", "duplicate", "budget_bool"])
def test_report_cannot_assert_its_own_proof_status(tamper):
    model = Model()
    model.operation("sum", sm.Opcode.ADD, model.literal("a", 2), model.literal("b", 3))
    report = evaluate_constants(model.graph)
    wire = deepcopy(report.to_dict())
    if tamper == "literal":
        wire["facts"][0]["literal"]["payload"] = "999"
    elif tamper == "status":
        wire["facts"][0]["status"] = "KNOWN_EXCEPTION"
    elif tamper == "premises":
        next(item for item in wire["proofs"] if item["premises"])["premises"] = []
    elif tamper == "proof_cycle":
        wire["proofs"][0]["premises"] = [wire["proofs"][0]["id"]]
    elif tamper == "digest":
        wire["model_digest"] = "0" * 64
    elif tamper == "runtime":
        wire["runtime"]["implementation"] = "unverified-runtime"
    elif tamper == "source_status":
        wire["source_validation"] = "VERIFIED"
    elif tamper == "duplicate":
        wire["facts"].append(deepcopy(wire["facts"][0]))
    else:
        wire["budget"]["max_steps"] = True
    with pytest.raises(ValueError):
        ConstantReport.from_dict(wire, graph=model.graph)


def test_later_model_or_source_snapshot_mutation_invalidates_old_report():
    model = Model()
    result = model.operation("sum", sm.Opcode.ADD, model.literal("a", 2), model.literal("b", 3))
    report = evaluate_constants(model.graph)
    op = model.graph.values[result].producer
    model.graph.operations[op] = replace(model.graph.operations[op], opcode=sm.Opcode.SUB)
    assert not report.validate()["valid"]
    newer = evaluate_constants(model.graph)
    assert newer.facts[result].literal.to_python() == -1
    assert newer.source_validation is SourceValidation.NOT_CHECKED
    # Model validity alone cannot attest that a changed opcode matches source.
    wire = newer.to_dict()
    model.graph.sources[model.path] = replace(model.graph.sources[model.path], fingerprint="sha256:" + "1" * 64)
    with pytest.raises(ValueError):
        ConstantReport.from_dict(wire, graph=model.graph)


def test_invalid_targets_budget_and_duplicate_json_keys_rejected():
    model = Model()
    model.literal("one", 1)
    with pytest.raises(ValueError):
        evaluate_constants(model.graph, targets=("one",))
    with pytest.raises(ValueError):
        EvaluationBudget(max_nodes=True)
    report = evaluate_constants(model.graph)
    payload = report.to_json()
    payload = payload[:-1] + ',"schema":"forged"}'
    with pytest.raises(ValueError, match="duplicate"):
        ConstantReport.from_json(payload, graph=model.graph)


def test_source_contract_and_transitive_float_runtime_requirements_remain_unaccepted():
    model = Model()
    result = model.operation("float-add", sm.Opcode.ADD, model.literal("a", 0.5), model.literal("b", 0.25))
    binding = model.bind("value", result, 0)
    loaded = model.read("loaded", binding)
    report = evaluate_constants(model.graph, targets=(loaded,))
    assert report.facts[loaded].literal.to_python() == 0.75
    assert report.required_preconditions == model.graph.required_preconditions
    assert report.preconditions_status is ContractAcceptance.REQUIRED_CONTRACT
    assert report.runtime_validation is RuntimeValidation.NOT_CHECKED
    assert report.source_validation is SourceValidation.NOT_CHECKED
    proof = report.proofs[report.facts[loaded].proof_id]
    assert ConstantRuntimeRequirement.FLOATING_ENVIRONMENT_MATCH in proof.runtime_requirements
    assert ConstantRuntimeRequirement.BUILTIN_RUNTIME_MATCH in proof.runtime_requirements
    for field, value in (("required_preconditions", []), ("preconditions_status", "ACCEPTED"),
                         ("runtime_requirements", []), ("runtime_validation", "VERIFIED")):
        document = deepcopy(report.to_dict())
        document[field] = value
        with pytest.raises(ValueError):
            ConstantReport.from_dict(document, graph=model.graph)


@pytest.mark.parametrize("entry", ["from_dict", "from_json", "validate", "to_dict"])
def test_untrusted_report_budget_cannot_authorize_recomputation_allocation(monkeypatch, entry):
    import scar.analysis.constants_v2 as constants
    model = Model()
    result = model.operation("huge", sm.Opcode.MUL, model.literal("text", "a"), model.literal("count", 1000000000))
    report = evaluate_constants(model.graph, targets=(result,))
    assert report.facts[result].status is ConstantStatus.BUDGET_EXCEEDED
    document = report.to_dict()
    for name in ("max_work", "max_int_bits", "max_sequence_items", "max_bytes", "max_total_output_bytes"):
        document["budget"][name] = 10**30
    huge_budget = EvaluationBudget(**document["budget"])
    def forbidden(*_args, **_kwargs):
        pytest.fail("untrusted stored budget reached recomputation")
    # Intercept before any graph traversal, not merely the eventual MUL.
    monkeypatch.setattr(constants, "evaluate_constants", forbidden)
    if entry == "validate":
        report.budget = huge_budget
        validation = report.validate()
        assert not validation["valid"]
        assert "verification ceiling" in validation["errors"][0]
    elif entry == "to_dict":
        report.budget = huge_budget
        with pytest.raises(ValueError, match="verification ceiling"):
            report.to_dict()
    else:
        with pytest.raises(ValueError, match="verification ceiling"):
            if entry == "from_dict":
                ConstantReport.from_dict(document, graph=model.graph)
            else:
                ConstantReport.from_json(json.dumps(document), graph=model.graph)


def test_larger_verification_budget_requires_explicit_trusted_caller_opt_in():
    model = Model()
    model.literal("one", 1)
    budget = EvaluationBudget(max_nodes=20000)
    report = evaluate_constants(model.graph, budget=budget)
    with pytest.raises(ValueError, match="verification ceiling"):
        report.to_dict()
    document = report.to_dict(verification_budget=budget)
    with pytest.raises(ValueError, match="verification ceiling"):
        ConstantReport.from_dict(document, graph=model.graph)
    restored = ConstantReport.from_dict(document, graph=model.graph, verification_budget=budget)
    assert restored.assert_valid(verification_budget=budget)["valid"]
