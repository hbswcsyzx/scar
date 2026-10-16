"""P0 provider declaration contracts, without artifact reads or graph proof."""
from dataclasses import FrozenInstanceError, fields, replace

import pytest

from scar.ir.program.providers import (
    ProviderArtifact, ProviderArtifactKind, ProviderBinding, ProviderCaptureMode,
    ProviderCollectionDomain, ProviderCollectionObservation, ProviderCondition,
    ProviderConditionDomain, ProviderCoverage, ProviderCoverageDomain, ProviderElement,
    ProviderElementKind, ProviderEnvelope, ProviderFactReference, ProviderPathIndex,
    ProviderPathKey, ProviderRegion, ProviderRegionRelation, ProviderRunScope, ProviderStage,
)
from scar.ir.program.ids import OperationID, ProviderID, RegionID, UseID, ValueID
from scar.ir.v2.common import Completeness, SourceVersion
from scar.ir.v2.ids import LogicalValueID


def artifact():
    return ProviderArtifact("unopened://provider/graph", "a" * 64, 0, "test.schema.v1")


def fact():
    return ProviderFactReference(artifact(), "/nodes/0")


def run_scope():
    return ProviderRunScope("run-1", 0, "window-1", "provider-clock", thread_id=0)


def envelope():
    return ProviderEnvelope(
        ProviderID("raw-graph"), "test.provider", "1.0", None, artifact(),
        ProviderArtifactKind.DEFINITION_GRAPH, ProviderCaptureMode.SYMBOLIC_CAPTURE, None,
        (SourceVersion("model.py", "sha256:" + "b" * 64),),
        (ProviderStage("raw", fact()),), (),
        tuple(ProviderCoverage(domain, Completeness.UNKNOWN, None, "not yet assessed")
              for domain in ProviderCoverageDomain),
        tuple(ProviderCollectionObservation(domain, None, "not yet measured")
              for domain in ProviderCollectionDomain),
    )


def element(kind=ProviderElementKind.USE):
    path = (ProviderPathKey("args"), ProviderPathIndex(0)) if kind is ProviderElementKind.USE else ()
    return ProviderElement(kind, "node-1", path)


def test_envelope_requires_explicit_domain_reports_without_claiming_authority():
    item = envelope()
    assert {row.domain for row in item.coverage} == set(ProviderCoverageDomain)
    assert {row.domain for row in item.collection} == set(ProviderCollectionDomain)
    assert all(row.completeness is Completeness.UNKNOWN and row.evidence is None for row in item.coverage)
    assert all(row.evidence is None and row.reason for row in item.collection)
    assert not ({"verified", "proven", "complete", "effects_none"} & {f.name for f in fields(item)})
    assert item.artifact.uri == "unopened://provider/graph"  # no read/execute in constructor


@pytest.mark.parametrize("field,value", [
    ("uri", ""), ("schema", ""), ("sha256", "sha256:" + "a" * 64),
    ("sha256", "A" * 64), ("sha256", "a" * 63), ("sha256", "g" * 64),
    ("size_bytes", -1), ("size_bytes", True), ("size_bytes", 0.0),
])
def test_artifact_rejects_invalid_identity_schema_digest_or_byte_count(field, value):
    with pytest.raises((TypeError, ValueError)):
        replace(artifact(), **{field: value})


def test_fact_reference_requires_typed_artifact_and_locator_revalidates_nested_record():
    for invalid in (None, "artifact", {}):
        with pytest.raises(TypeError):
            ProviderFactReference(invalid, "/nodes/0")
    with pytest.raises(ValueError):
        replace(fact(), locator="")
    bad = artifact()
    object.__setattr__(bad, "size_bytes", False)
    with pytest.raises(TypeError):
        ProviderFactReference(bad, "/nodes/0")


def test_run_scope_keeps_explicit_zero_and_optional_thread_without_clock_conversion():
    item = run_scope()
    assert item.process_id == 0 and type(item.process_id) is int
    assert item.thread_id == 0 and replace(item, thread_id=None).thread_id is None
    assert item.clock == "provider-clock"


@pytest.mark.parametrize("field,value", [
    ("process_id", False), ("process_id", -1), ("thread_id", True),
    ("thread_id", -1), ("run", ""), ("window", ""), ("clock", ""),
])
def test_run_scope_rejects_missing_scope_text_and_boolean_or_negative_ids(field, value):
    with pytest.raises((TypeError, ValueError)):
        replace(run_scope(), **{field: value})


def test_stage_and_condition_need_real_fact_references_not_boolean_claims():
    stage = ProviderStage("functionalize", fact())
    condition = ProviderCondition(ProviderConditionDomain.SHAPE, fact())
    assert stage.evidence == condition.evidence
    for item in (stage, condition):
        for invalid in (None, True, "/conditions/shape"):
            with pytest.raises(TypeError):
                replace(item, evidence=invalid)
    with pytest.raises(TypeError):
        replace(condition, domain="SHAPE")


@pytest.mark.parametrize("completeness", [Completeness.COMPLETE, Completeness.PARTIAL])
def test_nonunknown_coverage_requires_evidence_and_remains_provider_declaration(completeness):
    with pytest.raises(ValueError, match="requires evidence"):
        ProviderCoverage(ProviderCoverageDomain.DATAFLOW, completeness, None, "claim")
    item = ProviderCoverage(ProviderCoverageDomain.DATAFLOW, completeness, fact(), "provider-scoped report")
    assert item.completeness is completeness and not hasattr(item, "proven")


def test_unknown_coverage_and_missing_collection_evidence_are_named_gaps_not_none_effects():
    coverage = ProviderCoverage(ProviderCoverageDomain.ALIAS_IDENTITY, Completeness.UNKNOWN,
                                None, "external writes not assessed")
    assert replace(coverage, evidence=fact()).completeness is Completeness.UNKNOWN
    collection = ProviderCollectionObservation(ProviderCollectionDomain.COST, None, "cost not measured")
    for item in (coverage, collection):
        with pytest.raises(ValueError):
            replace(item, reason="")
        with pytest.raises(TypeError):
            replace(item, reason=True)
    with pytest.raises(TypeError):
        replace(coverage, completeness="UNKNOWN")
    assert not hasattr(collection, "zero_cost")


def test_version_or_revision_is_required_and_present_values_must_be_nonempty_text():
    item = envelope()
    assert replace(item, provider_version=None, source_revision="revision-1").source_revision == "revision-1"
    assert replace(item, source_revision="revision-1").provider_version == "1.0"
    for changes in ({"provider_version": None}, {"provider_version": ""},
                    {"source_revision": ""}, {"provider_version": True}):
        with pytest.raises((TypeError, ValueError)):
            replace(item, **changes)


@pytest.mark.parametrize("kind,mode,scope", [
    (ProviderArtifactKind.DEFINITION_GRAPH, ProviderCaptureMode.STATIC_ANALYSIS, None),
    (ProviderArtifactKind.DEFINITION_GRAPH, ProviderCaptureMode.SYMBOLIC_CAPTURE, None),
    (ProviderArtifactKind.DEFINITION_GRAPH, ProviderCaptureMode.SYMBOLIC_CAPTURE, run_scope()),
    (ProviderArtifactKind.DEFINITION_GRAPH, ProviderCaptureMode.REAL_EXECUTION, run_scope()),
    (ProviderArtifactKind.DEFINITION_GRAPH, ProviderCaptureMode.REPLAY, run_scope()),
    (ProviderArtifactKind.EXECUTION_EVIDENCE, ProviderCaptureMode.REAL_EXECUTION, run_scope()),
    (ProviderArtifactKind.EXECUTION_EVIDENCE, ProviderCaptureMode.REPLAY, run_scope()),
])
def test_artifact_kind_and_capture_mode_are_distinct_dimensions(kind, mode, scope):
    item = replace(envelope(), kind=kind, capture_mode=mode, capture_scope=scope)
    assert item.kind is kind and item.capture_mode is mode and item.capture_scope == scope


@pytest.mark.parametrize("kind,mode,scope", [
    (ProviderArtifactKind.DEFINITION_GRAPH, ProviderCaptureMode.STATIC_ANALYSIS, run_scope()),
    (ProviderArtifactKind.DEFINITION_GRAPH, ProviderCaptureMode.REAL_EXECUTION, None),
    (ProviderArtifactKind.DEFINITION_GRAPH, ProviderCaptureMode.REPLAY, None),
    (ProviderArtifactKind.EXECUTION_EVIDENCE, ProviderCaptureMode.SYMBOLIC_CAPTURE, run_scope()),
    (ProviderArtifactKind.EXECUTION_EVIDENCE, ProviderCaptureMode.STATIC_ANALYSIS, None),
    (ProviderArtifactKind.EXECUTION_EVIDENCE, ProviderCaptureMode.REAL_EXECUTION, None),
])
def test_execution_and_static_capture_scope_contracts_are_enforced(kind, mode, scope):
    with pytest.raises(ValueError):
        replace(envelope(), kind=kind, capture_mode=mode, capture_scope=scope)


def test_source_versions_are_exact_canonical_nonrepeated_declarations():
    item = envelope()
    assert replace(item, sources=()).sources == ()
    with pytest.raises(ValueError, match="must not repeat"):
        replace(item, sources=(*item.sources, *item.sources))
    bad_source = SourceVersion(True, "sha256:" + "a" * 64)
    with pytest.raises(TypeError):
        replace(item, sources=(bad_source,))
    bad_source = replace(item.sources[0])
    object.__setattr__(bad_source, "fingerprint", "SHA256:" + "a" * 64)
    with pytest.raises(ValueError):
        replace(item, sources=(bad_source,))


def test_envelope_collections_are_exact_tuples_of_expected_record_types():
    item = envelope()
    mutations = [
        {"sources": list(item.sources)}, {"stages": list(item.stages)},
        {"conditions": [ProviderCondition(ProviderConditionDomain.MODE, fact())]},
        {"coverage": list(item.coverage)}, {"collection": list(item.collection)},
        {"sources": ("model.py",)}, {"stages": (fact(),)},
        {"conditions": (ProviderStage("not.condition", fact()),)},
        {"coverage": (True,)}, {"collection": (None,)},
    ]
    for changes in mutations:
        with pytest.raises(TypeError):
            replace(item, **changes)
    with pytest.raises(ValueError, match="nonempty stages"):
        replace(item, stages=())
    # Passes may repeat in a pipeline; neither lexicographic sorting nor
    # invented stage-name uniqueness should change the declared history.
    assert len(replace(item, stages=(*item.stages, *item.stages)).stages) == 2


def test_every_coverage_and_collection_domain_appears_exactly_once_order_independent():
    item = envelope()
    changed = replace(item, coverage=tuple(reversed(item.coverage)), collection=tuple(reversed(item.collection)))
    assert changed.coverage[0].domain is item.coverage[-1].domain
    for field in ("coverage", "collection"):
        rows = getattr(item, field)
        for bad in ((), rows[:-1], (*rows, rows[0]), (rows[0],) * len(rows)):
            with pytest.raises(ValueError, match="exactly one"):
                replace(item, **{field: bad})


def test_envelope_rechecks_nested_observation_invariants_after_tampering():
    item = envelope()
    bad = replace(item.coverage[0])
    object.__setattr__(bad, "completeness", Completeness.COMPLETE)
    with pytest.raises(ValueError, match="requires evidence"):
        replace(item, coverage=(bad, *item.coverage[1:]))


def test_region_declaration_is_typed_but_does_not_resolve_graph_or_source():
    item = ProviderRegion(ProviderID("provider"), "native.subgraph", RegionID("canonical"),
                          ProviderRegionRelation.DEFINES_REPRESENTATION)
    assert replace(item, relation=ProviderRegionRelation.OBSERVATION_SCOPE).region == item.region
    for changes in ({"provider": RegionID("provider")}, {"region": ValueID("canonical")},
                    {"external_region": ""}, {"relation": "OBSERVATION_SCOPE"}):
        with pytest.raises((TypeError, ValueError)):
            replace(item, **changes)


def test_path_preserves_nested_order_and_operation_vs_use_shape_constraints():
    path = (ProviderPathKey("kwargs"), ProviderPathKey("batch"), ProviderPathIndex(1), ProviderPathIndex(0))
    item = replace(element(), path=path)
    assert item.path == path
    assert element(ProviderElementKind.OPERATION).path == ()
    with pytest.raises(ValueError, match="must be empty"):
        replace(element(ProviderElementKind.OPERATION), path=path)
    with pytest.raises(ValueError, match="nonempty operand path"):
        replace(item, path=())
    for kind in tuple(ProviderElementKind)[1:-1]:
        assert replace(item, kind=kind, path=()).path == ()


def test_path_parts_reject_boolean_indices_empty_keys_and_untyped_container_entries():
    for value in (True, False, -1, 1.0):
        with pytest.raises((TypeError, ValueError)):
            ProviderPathIndex(value)
    assert ProviderPathIndex(0).index == 0
    with pytest.raises(ValueError):
        ProviderPathKey("")
    for bad in ([ProviderPathIndex(0)], (0,), ("args",), (True,)):
        with pytest.raises(TypeError):
            replace(element(), path=bad)


@pytest.mark.parametrize("kind", tuple(ProviderElementKind))
def test_binding_target_namespace_follows_element_kind_without_inventing_logical_identity(kind):
    expected = {ProviderElementKind.OPERATION: OperationID,
                ProviderElementKind.USE: UseID}.get(kind, ValueID)
    item = ProviderBinding(ProviderID("provider"), RegionID("region"), element(kind), expected("target"))
    assert type(item.target) is expected
    for wrong in (ProviderID("target"), LogicalValueID("target"), "target", True):
        with pytest.raises(TypeError):
            replace(item, target=wrong)


def test_mapping_has_no_second_actual_value_or_writable_verification_field():
    item = ProviderBinding(ProviderID("provider"), RegionID("region"), element(), UseID("operand"))
    assert {field.name for field in fields(item)} == {"provider", "region", "external", "target"}
    assert not hasattr(item, "value") and not hasattr(item, "verified")
    with pytest.raises(TypeError):
        replace(item, target=ValueID("operand"))
    with pytest.raises(TypeError):
        replace(item, provider=RegionID("provider"))


def test_new_contract_uses_exact_types_including_nested_records_and_tuples():
    class DerivedProvider(ProviderID):
        pass

    class DerivedValue(ValueID):
        pass

    class DerivedTuple(tuple):
        pass

    class DerivedElement(ProviderElement):
        pass

    class DerivedSource(SourceVersion):
        pass

    with pytest.raises(TypeError):
        replace(envelope(), id=DerivedProvider("provider"))
    with pytest.raises(TypeError):
        replace(envelope(), coverage=DerivedTuple(envelope().coverage))
    with pytest.raises(TypeError):
        replace(envelope(), sources=(DerivedSource("model.py", "sha256:" + "b" * 64),))
    binding = ProviderBinding(ProviderID("provider"), RegionID("region"),
                              element(ProviderElementKind.REFERENCE_VALUE), ValueID("value"))
    with pytest.raises(TypeError):
        replace(binding, target=DerivedValue("value"))
    with pytest.raises(TypeError):
        replace(binding, external=DerivedElement(ProviderElementKind.REFERENCE_VALUE, "node"))
    with pytest.raises(TypeError):
        replace(element(), path=DerivedTuple(element().path))


def test_all_provider_records_are_frozen_and_slotted():
    items = (
        artifact(), fact(), run_scope(), ProviderStage("raw", fact()),
        ProviderCondition(ProviderConditionDomain.VALUE, fact()), envelope().coverage[0],
        envelope().collection[0], envelope(),
        ProviderRegion(ProviderID("provider"), "subgraph", RegionID("region"),
                       ProviderRegionRelation.OBSERVATION_SCOPE),
        ProviderPathIndex(0), ProviderPathKey("args"), element(),
        ProviderBinding(ProviderID("provider"), RegionID("region"), element(), UseID("operand")),
    )
    for item in items:
        assert not hasattr(item, "__dict__")
        name = fields(item)[0].name
        with pytest.raises(FrozenInstanceError):
            setattr(item, name, getattr(item, name))
