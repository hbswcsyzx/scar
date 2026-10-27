"""Provider records remain scoped declarations over canonical core endpoints."""
from dataclasses import replace
import json

import pytest

from scar.ir.program.ids import OperationID, ProviderID, RegionID, UseID, ValueID
from scar.ir.program.model import ProgramGraph
from scar.ir.program.model import DataValue, LiteralOrigin
from scar.ir.program.providers import (
    ProviderBinding,
    ProviderElement,
    ProviderElementKind,
    ProviderPathIndex,
    ProviderPathKey,
    ProviderRegion,
    ProviderRegionRelation,
)
from scar.ir.program.validation import validate
from scar.ir.program.codec import dumps, loads
from scar.ir.program.queries import ProgramIndex
from scar.cli import main

from tests.fixtures.program_provider_graphs import (
    definition_provider_graph,
    definition_parent_owner_graph,
    execution_multirun_observation_graph,
    execution_observation_graph,
    provider_owner_conflict_graph,
)


def _rejects(graph):
    """Invalid declarations must fail the shared graph gate and public codec."""
    issues = validate(graph)
    assert issues
    assert any(issue.code.startswith("provider_") for issue in issues)
    with pytest.raises(ValueError):
        dumps(graph)


def _binding(graph, kind, key, target, path=()):
    owner = graph.provider_regions[0]
    return ProviderBinding(
        owner.provider,
        owner.region,
        ProviderElement(kind, key, path),
        target,
    )


def test_definition_provider_keeps_ordered_duplicate_value_operands_distinct():
    graph = definition_provider_graph()
    assert validate(graph) == ()

    twice = next(operation for operation in graph.operations if operation.id == OperationID("twice"))
    left, right = twice.uses
    assert (left.id, right.id) == (UseID("twice.left"), UseID("twice.right"))
    assert left.value == right.value == ValueID("body.input")

    use_bindings = tuple(row for row in graph.provider_bindings
                         if row.external.kind is ProviderElementKind.USE)
    assert tuple(row.external.path for row in use_bindings) == (
        (ProviderPathIndex(0),), (ProviderPathIndex(1),),
    )
    assert tuple(row.target for row in use_bindings) == (left.id, right.id)
    assert {row.region for row in graph.provider_bindings} == {RegionID("callee")}

    payload = dumps(graph)
    assert json.loads(payload)["schema_version"] == 7
    assert loads(payload) == graph


def test_execution_evidence_can_scope_observations_but_cannot_define_static_bindings():
    observed = execution_observation_graph()
    assert validate(observed) == ()
    assert {row.relation for row in observed.provider_regions} == {
        ProviderRegionRelation.OBSERVATION_SCOPE,
    }
    assert {row.region for row in observed.provider_regions} == {
        RegionID("caller"), RegionID("callee"),
    }
    assert {row.external_region for row in observed.provider_regions} == {"observed.project"}
    assert observed.provider_bindings == ()

    _rejects(execution_observation_graph(with_static_binding=True))


def test_program_index_returns_declarations_and_exact_use_sites_without_inference():
    graph = definition_provider_graph()
    index = ProgramIndex(graph)
    provider = ProviderID("definition-provider")

    assert index.provider_envelope(provider) == graph.provider_envelopes[0]
    left_binding = index.provider_sources(UseID("twice.left"))
    right_binding = index.provider_sources(UseID("twice.right"))
    assert tuple(item.target for item in left_binding) == (UseID("twice.left"),)
    assert tuple(item.target for item in right_binding) == (UseID("twice.right"),)
    assert index.use_site(UseID("twice.left")).operation == OperationID("twice")
    assert index.use_site(UseID("twice.right")).operation == OperationID("twice")
    assert index.use_site(UseID("twice.left")).use.value == ValueID("body.input")
    assert index.use_site(UseID("twice.right")).use.value == ValueID("body.input")

    # A target without a declaration stays unassociated; this is not a
    # no-source proof or an inferred connection from a same-looking value.
    assert index.provider_sources(ValueID("caller.input")) == ()
    with pytest.raises(KeyError):
        index.provider_envelope(ProviderID("missing-provider"))


def test_observation_scopes_are_multiregion_multirun_and_never_become_bindings():
    graph = execution_multirun_observation_graph()
    assert validate(graph) == ()
    index = ProgramIndex(graph)

    callee_sources = index.provider_region_sources(RegionID("callee"))
    caller_sources = index.provider_region_sources(RegionID("caller"))
    assert len(callee_sources) == len(caller_sources) == 2
    assert {item.association.external_region for item in callee_sources} == {"same.external.scope"}
    assert {item.association.relation for item in callee_sources} == {
        ProviderRegionRelation.OBSERVATION_SCOPE,
    }
    assert {item.envelope.capture_scope.run for item in callee_sources} == {"run-1", "run-2"}
    assert index.provider_sources(OperationID("twice")) == ()


def test_definition_owner_is_not_inherited_from_parent_region_to_child():
    graph = definition_parent_owner_graph()
    assert validate(graph) == ()
    index = ProgramIndex(graph)

    parent_sources = index.provider_region_sources(RegionID("caller"))
    child_sources = index.provider_region_sources(RegionID("callee"))
    assert len(parent_sources) == 1
    assert parent_sources[0].association.relation is ProviderRegionRelation.DEFINES_REPRESENTATION
    assert child_sources == ()


def test_two_definition_providers_cannot_own_one_core_region():
    _rejects(provider_owner_conflict_graph())


def test_binding_must_use_the_region_it_is_declared_under():
    graph = definition_provider_graph()
    changed = replace(graph.provider_bindings[0], region=RegionID("caller"))
    _rejects(replace(graph, provider_bindings=(changed, *graph.provider_bindings[1:])))


def test_one_external_use_slot_cannot_be_reused_for_two_core_occurrences():
    graph = definition_provider_graph()
    right = next(row for row in graph.provider_bindings if row.target == UseID("twice.right"))
    changed = replace(right, external=ProviderElement(
        ProviderElementKind.USE, "twice", (ProviderPathIndex(0),)))
    _rejects(replace(graph, provider_bindings=tuple(
        changed if row is right else row for row in graph.provider_bindings)))


def test_use_external_key_must_match_the_operation_that_owns_that_use():
    graph = definition_provider_graph()
    graph = replace(graph, provider_bindings=tuple(
        row for row in graph.provider_bindings if row.target != UseID("twice.left")))
    changed = _binding(graph, ProviderElementKind.USE, "count", UseID("twice.left"),
                       (ProviderPathIndex(0),))
    _rejects(replace(graph, provider_bindings=(*graph.provider_bindings, changed)))


def test_operation_result_value_requires_its_producer_key_and_nonempty_result_path():
    graph = definition_provider_graph()
    without_result = replace(
        graph,
        provider_bindings=tuple(row for row in graph.provider_bindings
                                if row.target != ValueID("body.result")),
    )
    wrong_producer = _binding(
        without_result, ProviderElementKind.DATA_VALUE, "count", ValueID("body.result"),
        (ProviderPathKey("result"),),
    )
    _rejects(replace(without_result,
                     provider_bindings=(*without_result.provider_bindings, wrong_producer)))

    missing_result_path = _binding(
        without_result, ProviderElementKind.DATA_VALUE, "twice", ValueID("body.result"),
    )
    _rejects(replace(without_result,
                     provider_bindings=(*without_result.provider_bindings, missing_result_path)))


def test_external_value_kind_must_match_the_actual_core_value_variant():
    graph = definition_provider_graph()
    unbound_data = DataValue(ValueID("body.unclassified"), RegionID("callee"),
                             LiteralOrigin(7), "builtins.int")
    graph = replace(graph, values=(*graph.values, unbound_data))
    wrong_data_kind = _binding(
        graph, ProviderElementKind.REFERENCE_VALUE, "unclassified-reference",
        unbound_data.id, (ProviderPathKey("value"),),
    )
    _rejects(replace(graph, provider_bindings=(*graph.provider_bindings, wrong_data_kind)))

    base = definition_provider_graph()
    without_state_binding = replace(
        base,
        provider_bindings=tuple(row for row in base.provider_bindings
                                if row.target != ValueID("body.initial")),
    )
    wrong_state_kind = _binding(
        without_state_binding, ProviderElementKind.DATA_VALUE, "state-as-data",
        ValueID("body.initial"), (ProviderPathKey("world"),),
    )
    _rejects(replace(without_state_binding,
                     provider_bindings=(*without_state_binding.provider_bindings, wrong_state_kind)))


def test_one_core_target_cannot_be_collapsed_from_distinct_external_values():
    graph = definition_provider_graph()
    alias = _binding(
        graph, ProviderElementKind.DATA_VALUE, "other-argument", ValueID("body.input"),
        (ProviderPathKey("y"),),
    )
    _rejects(replace(graph, provider_bindings=(*graph.provider_bindings, alias)))


def test_complete_coverage_and_empty_conditions_do_not_create_capture_authority(tmp_path, capsys):
    graph = definition_provider_graph(complete_claims=True)
    assert validate(graph) == ()
    envelope = graph.provider_envelopes[0]
    assert envelope.conditions == ()
    assert {item.completeness.value for item in envelope.coverage} == {"COMPLETE"}
    collection = {item.domain.value: item for item in envelope.collection}
    assert collection["CAPTURE_EFFECTS"].evidence is None
    assert collection["COST"].evidence is None
    assert not hasattr(envelope, "transformation_authorized")
    indexed = ProgramIndex(graph).provider_envelope(envelope.id)
    assert indexed == envelope
    assert not hasattr(indexed, "transformation_authorized")

    source = tmp_path / "provider.json"
    source.write_text(dumps(graph), encoding="utf-8")
    assert main(["check-program", str(source)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "WELL_FORMED"
    assert report["transformation_authorized"] is False
    assert report["provider_artifact_replay_verified"] is False
    assert report["provider_conditions_verified"] is False
    assert report["provider_source_correspondence_verified"] is False
    assert report["cross_representation_equivalence_verified"] is False
    assert report["provider_runtime_correspondence_verified"] is False

