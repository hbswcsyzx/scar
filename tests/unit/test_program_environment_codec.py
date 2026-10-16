"""Declared environment interfaces retain exact old wire and canonical call uses."""
from dataclasses import replace
import json
from pathlib import Path

import pytest

from scar.ir.program import (
    EnvironmentInterfaceID, ExternalResource, OperationID, ResourceDefinition,
    ResourceDefinitionID, ResourceKind, ResourceRole, UseID, dumps, loads,
)
from scar.ir.program.queries import EnvironmentBindingStatus, ProgramIndex
from scar.ir.record_codec import encode
from tests.unit.test_program_environments import _environment_graph


@pytest.mark.parametrize("version", [2, 3, 4])
def test_frozen_original_wire_roundtrips_without_new_environment_fields(version):
    payload = (Path(__file__).parents[1] / f"fixtures/program_graph_v{version}_frozen.json").read_text().rstrip("\n")
    graph = loads(payload)
    assert graph.environments == ()
    assert dumps(graph) == payload


def test_v5_environment_and_resource_interfaces_compose_without_erasing_either():
    graph = _environment_graph()
    graph = replace(graph, resources=(ResourceDefinition(
        ResourceDefinitionID("executor"), ResourceKind.CPU, ResourceRole.EXECUTOR,
        ExternalResource(graph.root, "executor")),))
    document = json.loads(dumps(graph))
    assert document["schema_version"] == 5
    assert loads(json.dumps(document)) == graph
    assert document["environments"] and document["resources"]


@pytest.mark.parametrize("version", [1, 2, 3, 4])
@pytest.mark.parametrize("field", ["environments", "function_entries"])
def test_historical_envelope_cannot_carry_environment_even_when_empty(version, field):
    original_version = max(version, 2)
    payload = (Path(__file__).parents[1] / f"fixtures/program_graph_v{original_version}_frozen.json").read_text()
    document = json.loads(payload)
    document["schema_version"] = version
    if version == 1:
        for operation in document["operations"]:
            del operation["completions"]
            del operation["invoke_arguments"]
    loads(json.dumps(document))  # The historical document is valid before injection.
    document[field] = []
    with pytest.raises(ValueError):
        loads(json.dumps(document))


def test_v5_cannot_relabel_an_old_graph_or_omit_its_environment_table():
    document = json.loads(dumps(_environment_graph()))
    document["environments"] = []
    document["function_entries"] = []
    with pytest.raises(ValueError, match="requires explicit environment"):
        loads(json.dumps(document))
    for field in ("environments", "function_entries"):
        missing = dict(document)
        del missing[field]
        with pytest.raises(ValueError, match="top-level fields"):
            loads(json.dumps(missing))


def test_v5_rejects_a_use_id_forged_as_an_environment_value_reference():
    document = json.loads(dumps(_environment_graph()))
    document["environments"][0]["members"][0]["reference"] = encode(UseID("foreign"))
    with pytest.raises(ValueError):
        loads(json.dumps(document))


def test_v5_rejects_environment_id_namespace_confusion():
    document = json.loads(dumps(_environment_graph()))
    document["environments"][0]["code_definition"] = encode(EnvironmentInterfaceID("code"))
    with pytest.raises(ValueError):
        loads(json.dumps(document))


@pytest.mark.parametrize("invoke", [False, True])
def test_query_follows_each_actual_use_without_deduplicating_aliased_objects(invoke):
    graph = _environment_graph(invoke=invoke, alias_actuals=True)
    index = ProgramIndex(graph)
    call = next(operation for operation in graph.operations if operation.callee is not None)
    binding = index.environment_call(call.id)
    assert binding.status is EnvironmentBindingStatus.DECLARED
    assert binding.interface == graph.environments[0].id
    assert binding.callee == call.callee
    assert tuple(argument.member for argument in binding.arguments) == graph.environments[0].members
    assert len({argument.actual.use.id for argument in binding.arguments}) == 6
    assert len({argument.actual.use.value for argument in binding.arguments}) == 1
    assert all(argument.actual.operation == call.id for argument in binding.arguments)
    canonical_uses = {use.id: use for use in call.uses}
    assert all(argument.actual.use is canonical_uses[argument.actual.use.id]
               for argument in binding.arguments)


def test_query_keeps_updated_state_between_repeated_calls_with_same_environment_ports():
    graph = _environment_graph()
    index = ProgramIndex(graph)
    first = index.environment_call(OperationID("call1"))
    second = index.environment_call(OperationID("call2"))
    assert first.interface == second.interface
    assert [item.member.reference for item in first.arguments] == [item.member.reference for item in second.arguments]
    assert all(item.state_arguments[0].use.value.value == "caller.initial" for item in first.arguments)
    assert all(item.state_arguments[0].use.value.value == "call1.state" for item in second.arguments)
    assert first.arguments[-1].actual.use.id != second.arguments[-1].actual.use.id
    assert len(first.parameters) == len(second.parameters) == 1
    assert first.parameters[0].parameter == graph.function_entries[0].parameters[0]
    assert first.parameters[0].actual.use.id == UseID("call1.input")
    assert second.parameters[0].actual.use.id == UseID("call2.input")
    assert index.function_entry_layout(second.callee) == graph.function_entries[0]


def test_query_missing_declarations_remain_explicit_not_empty_environment_proof():
    graph = _environment_graph()
    index = ProgramIndex(replace(graph, environments=(), function_entries=()))
    assert index.environment_interface(graph.environments[0].region) is None
    call = index.environment_call(OperationID("call1"))
    assert call.status is EnvironmentBindingStatus.NO_DECLARED_ENVIRONMENT
    assert call.callee is not None and call.interface is None and call.arguments == ()
    ordinary = index.environment_call(OperationID("twice"))
    assert ordinary.status is EnvironmentBindingStatus.NO_DECLARED_CALLEE
    assert ordinary.callee is None and ordinary.parameters == ()
