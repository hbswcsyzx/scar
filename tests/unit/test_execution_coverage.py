"""Finite byte-set coverage, never produced content, lifetime or readiness."""
from dataclasses import FrozenInstanceError, replace
import hashlib

import pytest

from scar.ir.execution.coverage import (
    CoverageGap, CoverageStatus, RegionRef, StorageCoverageResult,
    _ValueCatalog, _storage_coverage, storage_coverage,
)
from scar.ir.execution.snapshot import external_bytes
from scar.ir.program.providers import ProviderArtifact
from scar.ir.v2.ids import StorageAllocationID, StorageRegionID
from scar.ir.v2.values import StorageAllocation, StorageRegion, ValueGraph


def _graph(*specifications, nbytes=1024):
    graph = ValueGraph()
    allocation = StorageAllocationID("allocation")
    graph.add_allocation(StorageAllocation(allocation, "cpu", nbytes))
    for name, offset, shape, strides, *options in specifications:
        dtype = options[0] if options else "uint8"
        layout = options[1] if len(options) > 1 else "strided"
        graph.add_region(StorageRegion(StorageRegionID(name), allocation, offset,
                                       shape, strides, dtype, "cpu", layout))
    return graph


def _artifact(graph, *, uri="memory:coverage"):
    wire = external_bytes(graph)
    return ProviderArtifact(uri, hashlib.sha256(wire).hexdigest(), len(wire), graph.SCHEMA)


def _call(graph, required="required", offered=("offered",), *, budget=4096):
    artifact = _artifact(graph)
    refs = tuple(RegionRef(artifact, StorageRegionID(name)) for name in offered)
    return storage_coverage(RegionRef(artifact, StorageRegionID(required)), refs,
                            value_graphs={artifact.sha256: graph}, budget=budget)


def _codes(result):
    return {gap.code for gap in result.gaps}


def test_union_of_distinct_halves_covers_only_the_requested_bytes():
    graph = _graph(("required", 2, (8,), (1,)),
                   ("left", 0, (6,), (1,)), ("right", 6, (8,), (1,)))
    result = _call(graph, offered=("left", "right"))
    assert result.status is CoverageStatus.COVERED
    assert result.covered_intervals == ((2, 10),)
    assert result.missing_intervals == ()
    assert result.used == result.offered
    assert not result.source_runtime_verified and not result.transformation_authorized


def test_same_bounding_box_with_stride_holes_is_not_coverage_but_union_can_fill_it():
    graph = _graph(("required", 0, (7,), (1,)),
                   ("even", 0, (4,), (2,)), ("odd", 1, (3,), (2,)))
    missing = _call(graph, offered=("even",))
    assert missing.status is CoverageStatus.INCOMPLETE
    assert missing.covered_intervals == ((0, 1), (2, 3), (4, 5), (6, 7))
    assert missing.missing_intervals == ((1, 2), (3, 4), (5, 6))
    complete = _call(graph, offered=("even", "odd"))
    assert complete.status is CoverageStatus.COVERED
    assert complete.covered_intervals == ((0, 7),)


def test_required_holes_are_not_mistaken_for_missing_required_bytes():
    graph = _graph(("required", 0, (4,), (2,)), ("offered", 0, (7,), (1,)))
    result = _call(graph)
    assert result.status is CoverageStatus.COVERED
    assert result.covered_intervals == ((0, 1), (2, 3), (4, 5), (6, 7))


def test_empty_zero_stride_does_not_create_a_phantom_element():
    graph = _graph(("required", 5000, (0,), (0,)), nbytes=0)
    result = _call(graph, offered=())
    assert result.status is CoverageStatus.COVERED
    assert result.covered_intervals == result.missing_intervals == ()
    assert result.used == ()


def test_nonempty_zero_stride_and_overlapping_dense_dimensions_use_union_not_numel():
    graph = _graph(("required", 0, (10**30,), (0,), "float32"),
                   ("offered", 0, (4,), (1,)), nbytes=4)
    result = _call(graph)
    assert result.status is CoverageStatus.COVERED
    assert result.covered_intervals == ((0, 4),)
    overlapping = _graph(("required", 0, (2, 2), (1, 1)),
                         ("offered", 0, (3,), (1,)), nbytes=3)
    assert _call(overlapping).covered_intervals == ((0, 3),)


def test_negative_stride_equivalence_and_invalid_negative_address_are_distinct():
    graph = _graph(("required", 3, (4,), (-1,)),
                   ("offered", 0, (4,), (1,)), nbytes=4)
    result = _call(graph)
    assert result.status is CoverageStatus.COVERED
    assert result.covered_intervals == ((0, 4),)
    graph.regions[StorageRegionID("required")].offset = 2
    with pytest.raises(ValueError, match="before its allocation"):
        _call(graph)


def test_element_offsets_and_strides_use_each_dtype_width_before_byte_comparison():
    graph = _graph(("required", 1, (1,), (1,), "float32"),
                   ("offered", 1, (4,), (1,), "uint8"), nbytes=8)
    result = _call(graph)
    assert result.status is CoverageStatus.INCOMPLETE
    assert result.covered_intervals == ((4, 5),)
    assert result.missing_intervals == ((5, 8),)


@pytest.mark.parametrize("dtype,layout,code", [
    ("unregistered_dtype", "strided", "dtype_width_unresolved"),
    ("uint8", "opaque", "layout_unresolved"),
])
def test_unknown_geometry_does_not_gain_coverage_from_exact_ref_identity(dtype, layout, code):
    graph = _graph(("required", 0, (4,), (1,), dtype, layout))
    result = _call(graph, offered=("required",))
    assert result.status is CoverageStatus.UNRESOLVED
    assert result.covered_intervals is result.missing_intervals is None
    assert code in _codes(result)


def test_exact_supported_region_ref_covers_huge_strided_selector_without_enumeration(monkeypatch):
    graph = _graph(("required", 0, (10**100,), (2,)), nbytes=2 * 10**100)
    monkeypatch.setattr("scar.ir.execution.coverage._byte_intervals",
                        lambda *args, **kwargs: pytest.fail("identity must not enumerate"))
    result = _call(graph, offered=("required",), budget=128)
    assert result.status is CoverageStatus.COVERED
    assert result.covered_intervals is None
    assert result.missing_intervals == ()
    assert result.used == result.offered


def test_large_dense_selector_has_exact_single_interval_shortcut():
    graph = _graph(("required", 0, (10**30,), (1,)),
                   ("offered", 0, (10**30,), (1,)), nbytes=10**30)
    result = _call(graph, budget=128)
    assert result.status is CoverageStatus.COVERED
    assert result.covered_intervals == ((0, 10**30),)


def test_giant_nondense_range_becomes_unresolved_before_legacy_len_range_overflows(monkeypatch):
    graph = _graph(("required", 0, (10**100,), (2,)),
                   ("offered", 0, (1,), (1,)), nbytes=2 * 10**100)
    monkeypatch.setattr("scar.ir.execution.coverage._byte_intervals",
                        lambda *args, **kwargs: pytest.fail("oversized range must be guarded"))
    result = _call(graph, budget=128)
    assert result.status is CoverageStatus.UNRESOLVED
    assert "geometry_budget_exhausted" in _codes(result)
    assert result.budget_used <= 128


def test_budget_is_shared_across_regions_not_reset_for_each_writer():
    graph = _graph(("required", 0, (30,), (1,)),
                   *((f"p{n}", n, (1,), (1,)) for n in range(30)))
    result = _call(graph, offered=tuple(f"p{n}" for n in range(30)), budget=100)
    assert result.status is CoverageStatus.UNRESOLVED
    assert "geometry_budget_exhausted" in _codes(result)
    assert result.budget_used <= 100
    assert result.missing_intervals is None


def test_missing_extra_offer_cannot_prevent_sufficient_known_subset_but_can_prevent_negative():
    graph = _graph(("required", 0, (4,), (1,)), ("offered", 0, (4,), (1,)))
    artifact = _artifact(graph)
    unknown = RegionRef(replace(artifact, sha256="f" * 64), StorageRegionID("extra"))
    required = RegionRef(artifact, StorageRegionID("required"))
    known = RegionRef(artifact, StorageRegionID("offered"))
    result = storage_coverage(required, (unknown, known), value_graphs={artifact.sha256: graph})
    assert result.status is CoverageStatus.COVERED
    assert "external_graph_unavailable" in _codes(result)
    assert result.used == (known,)
    result = storage_coverage(required, (unknown,), value_graphs={artifact.sha256: graph})
    assert result.status is CoverageStatus.UNRESOLVED
    assert result.missing_intervals is None


def test_same_bare_allocation_id_in_distinct_artifacts_has_no_byte_correspondence():
    left = _graph(("required", 0, (4,), (1,)))
    right = _graph(("offered", 0, (4,), (1,)))
    a, b = _artifact(left), _artifact(right)
    result = storage_coverage(RegionRef(a, StorageRegionID("required")),
                              (RegionRef(b, StorageRegionID("offered")),),
                              value_graphs={a.sha256: left, b.sha256: right})
    assert result.status is CoverageStatus.UNRESOLVED
    assert "allocation_correspondence_unresolved" in _codes(result)


def test_uri_is_not_identity_and_each_artifact_is_hashed_once_per_query(monkeypatch):
    graph = _graph(("required", 0, (4,), (1,)), ("offered", 0, (4,), (1,)))
    artifact = _artifact(graph)
    required = RegionRef(artifact, StorageRegionID("required"))
    offered = RegionRef(replace(artifact, uri="file:///must-not-open"), StorageRegionID("offered"))
    import scar.ir.execution.snapshot as module
    original, calls = module.external_bytes, []

    def counted(value):
        calls.append(value)
        return original(value)

    monkeypatch.setattr(module, "external_bytes", counted)
    monkeypatch.setattr("builtins.open", lambda *a, **k: pytest.fail("URI must not be opened"))
    resolver = _ValueCatalog({artifact.sha256: graph})
    snapshot = resolver.graph(artifact)
    assert snapshot is not graph
    result = _storage_coverage(required, (offered,), catalog=resolver)
    assert result.status is CoverageStatus.COVERED
    assert calls == [graph]
    snapshot.regions[StorageRegionID("offered")].offset = 1
    assert graph.regions[StorageRegionID("offered")].offset == 0


def test_public_calls_revalidate_mutable_graph_instead_of_caching_its_previous_digest():
    graph = _graph(("required", 0, (4,), (1,)), ("offered", 0, (4,), (1,)))
    artifact = _artifact(graph)
    required = RegionRef(artifact, StorageRegionID("required"))
    offered = (RegionRef(artifact, StorageRegionID("offered")),)
    catalog = {artifact.sha256: graph}
    assert storage_coverage(required, offered, value_graphs=catalog).status is CoverageStatus.COVERED
    graph.regions[StorageRegionID("offered")].offset = 1
    with pytest.raises(ValueError, match="bytes/schema/hash"):
        storage_coverage(required, offered, value_graphs=catalog)


@pytest.mark.parametrize("change", ["hash", "schema", "size", "family", "region", "shape"])
def test_supplied_invalid_snapshot_or_foreign_key_is_an_error_not_missing_evidence(change):
    graph = _graph(("required", 0, (4,), (1,)))
    artifact = _artifact(graph)
    region = StorageRegionID("required")
    if change == "hash":
        artifact = replace(artifact, sha256="a" * 64)
    elif change == "schema":
        artifact = replace(artifact, schema="other-schema")
    elif change == "size":
        artifact = replace(artifact, size_bytes=artifact.size_bytes + 1)
    elif change == "region":
        region = StorageRegionID("missing")
    elif change == "shape":
        graph.allocations = []
    catalog = {artifact.sha256: object() if change == "family" else graph}
    with pytest.raises(ValueError):
        storage_coverage(RegionRef(artifact, region), (), value_graphs=catalog)


def test_missing_required_graph_is_an_explicit_gap_not_empty_geometry():
    graph = _graph(("required", 0, (4,), (1,)))
    result = storage_coverage(RegionRef(_artifact(graph), StorageRegionID("required")), (),
                              value_graphs={})
    assert result.status is CoverageStatus.UNRESOLVED
    assert result.used == ()
    assert result.covered_intervals is result.missing_intervals is None
    assert _codes(result) == {"external_graph_unavailable"}


@pytest.mark.parametrize("malformed", ["integer-key", "str-subclass-key", "provided-none"])
def test_catalog_keys_are_exact_strings_and_present_none_is_not_missing(malformed):
    graph = _graph(("required", 0, (1,), (1,)))
    artifact = _artifact(graph)
    ref = RegionRef(artifact, StorageRegionID("required"))
    class StringSubclass(str):
        pass
    catalog = ({1: graph} if malformed == "integer-key" else
               {StringSubclass(artifact.sha256): graph} if malformed == "str-subclass-key" else
               {artifact.sha256: None})
    with pytest.raises(TypeError if malformed != "provided-none" else ValueError):
        storage_coverage(ref, (), value_graphs=catalog)


def test_records_are_exact_frozen_and_recheck_nested_private_mutation():
    graph = _graph(("required", 0, (1,), (1,)))
    ref = RegionRef(_artifact(graph), StorageRegionID("required"))
    with pytest.raises(FrozenInstanceError):
        ref.region = StorageRegionID("changed")
    assert not hasattr(ref, "__dict__")
    class DerivedRegionID(StorageRegionID):
        pass
    with pytest.raises(TypeError):
        RegionRef(ref.artifact, DerivedRegionID("required"))
    with pytest.raises(TypeError):
        storage_coverage(ref, [ref], value_graphs={})
    with pytest.raises(TypeError):
        storage_coverage(ref, (), value_graphs={}, budget=True)
    with pytest.raises(ValueError):
        storage_coverage(ref, (), value_graphs={}, budget=0)
    with pytest.raises(TypeError):
        StorageCoverageResult(CoverageStatus.COVERED, ref, (), (), ((False, 1),), (), 1, ())
    object.__setattr__(ref.artifact, "size_bytes", True)
    with pytest.raises(TypeError):
        CoverageGap("nested", ref, "must recheck nested artifact")


def test_invalid_interval_shape_and_fake_authority_are_not_constructor_capabilities():
    graph = _graph(("required", 0, (1,), (1,)))
    ref = RegionRef(_artifact(graph), StorageRegionID("required"))
    with pytest.raises(ValueError, match="sorted, disjoint"):
        StorageCoverageResult(CoverageStatus.INCOMPLETE, ref, (), (), ((0, 1), (1, 2)), (), 1, ())
    with pytest.raises(TypeError):
        StorageCoverageResult(CoverageStatus.COVERED, ref, (), (), (), (), 0, (),
                              transformation_authorized=True)
