"""Source membership/projection conservation, not native write completeness."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json

import pytest

from scar.ir.execution.inventory import InventoryResolver, artifact_json
from scar.ir.execution.snapshot import ExternalSnapshots
from scar.ir.program.providers import ProviderArtifact, ProviderRunScope
from scar.ir.v2.schemas import canonical_json
from scar.trace.normalize_v2 import normalize_bytes
from tests.fixtures.execution_inventory_sources import inventory_sources


def _doc(catalog, artifact):
    return json.loads(catalog[artifact.sha256])


def _pack(catalog, artifact, document):
    payload = canonical_json(document).encode()
    changed = replace(artifact, sha256=hashlib.sha256(payload).hexdigest(), size_bytes=len(payload))
    catalog[changed.sha256] = payload
    return changed


def _resolve(manifest, index, catalog, **limits):
    return InventoryResolver(ExternalSnapshots(artifact_bytes=catalog), **limits).resolve(manifest, index)


def _codes(result):
    return {gap.code for gap in result.gaps}


def test_default_raw_source_is_replayed_and_component_scopes_are_derived_from_original_bundle():
    manifest, index, catalog = inventory_sources()
    result = _resolve(manifest, index, catalog)
    assert result.format_replayed
    source, = result.sources
    assert source.key == "main" and source.projection_replayed
    assert source.raw_records[0].payload["kind"] == "torch_dispatch"
    assert source.bundle is not None and source.bundle.evidence.edges
    for graph, artifact in ((source.bundle.evidence, source.evidence_artifact),
                            (source.bundle.values, source.values_artifact),
                            (source.bundle.semantic, source.semantic_artifact)):
        payload = canonical_json(graph).encode()
        assert artifact.sha256 == hashlib.sha256(payload).hexdigest()
        assert artifact.size_bytes == len(payload) and artifact.schema == graph.SCHEMA
    assert "inventory_capture_unverified" in _codes(result)
    assert not result.source_runtime_verified and not result.transformation_authorized


def test_binary_lf_only_lines_preserve_blank_invalid_nonobject_and_final_unterminated_line():
    raw = (b'{ "kind" : "python_line", "metadata":{"line":1}}\r\n\n'
           + b'\xff\n[]\n' + br'{"kind":"opaque\u000b\u000c"}')
    manifest, index, catalog = inventory_sources(raw_streams={"physical": raw})
    result = _resolve(manifest, index, catalog)
    source, = result.sources
    assert result.format_replayed
    assert len(source.raw_records) == 5
    assert [row.line for row in source.raw_records] == [1, 2, 3, 4, 5]
    assert all(source.raw_records[i].payload is None for i in (1, 2, 3))
    # Actual VT/FF bytes in an escaped Python byte literal remain within one
    # physical line; JSON invalidity does not invent additional line anchors.
    assert len(normalize_bytes(b'\x0b\x0c').coverage["records"]) == 1
    assert "inventory_invalid_raw" in _codes(result)
    assert source.raw_records[0].sha256 == hashlib.sha256(raw.split(b"\n")[0] + b"\n").hexdigest()


def test_raw_metadata_native_result_is_detached_and_not_replaced_by_normalized_metadata():
    row = {"kind": "torch_dispatch", "metadata": {"process_id": 1, "thread_id": 1,
        "scar_native_result": {"length": 2}}, "inputs": [], "outputs": []}
    raw = (json.dumps(row) + "\n").encode()
    manifest, index, catalog = inventory_sources(raw_streams={"native": raw})
    first = _resolve(manifest, index, catalog)
    first.sources[0].raw_records[0].payload["metadata"]["scar_native_result"]["length"] = 9
    assert _resolve(manifest, index, catalog).sources[0].raw_records[0].payload["metadata"]["scar_native_result"]["length"] == 2


@pytest.mark.parametrize("field", ["schema", "schema_version", "extra"])
def test_closed_index_schema_rejects_bad_or_additional_fields(field):
    manifest, index, catalog = inventory_sources()
    document = _doc(catalog, index)
    document[field] = True if field == "schema_version" else "invalid"
    index = _pack(catalog, index, document)
    with pytest.raises(ValueError):
        _resolve(manifest, index, catalog)


@pytest.mark.parametrize("change", ["remove", "duplicate", "foreign"])
def test_index_cannot_shrink_or_expand_the_independent_manifest_source_set(change):
    manifest, index, catalog = inventory_sources(raw_streams={"one": b"", "two": b""})
    document = _doc(catalog, index)
    if change == "remove":
        document["entries"].pop()
    elif change == "duplicate":
        document["entries"].append(deepcopy(document["entries"][0]))
    else:
        document["entries"][0]["stream"] = "another-source"
    index = _pack(catalog, index, document)
    with pytest.raises(ValueError):
        _resolve(manifest, index, catalog)


@pytest.mark.parametrize("target", ["coverage", "bundle"])
def test_valid_artifact_reencoding_cannot_hide_changed_projection(target):
    manifest, index, catalog = inventory_sources()
    indexed = _doc(catalog, index)
    projection = indexed["entries"][0]["projection"]
    artifact = ProviderArtifact(**projection[target])
    document = _doc(catalog, artifact)
    if target == "coverage":
        document["raw_records"] += 1
    else:
        # Dropping an EEG edge leaves a locally valid bundle but changes the
        # source projection. A mere FK/count-presence check would miss it.
        document["evidence"]["edges"].pop()
    projection[target] = artifact_json(_pack(catalog, artifact, document))
    index = _pack(catalog, index, indexed)
    with pytest.raises(ValueError, match="projection"):
        _resolve(manifest, index, catalog)


@pytest.mark.parametrize("missing", ["raw", "bundle", "coverage", "index"])
def test_missing_bytes_leave_manifest_source_obligations_visible(missing):
    manifest, index, catalog = inventory_sources()
    raw_ref = _doc(catalog, manifest)["streams"][0]["raw"]
    projection = _doc(catalog, index)["entries"][0]["projection"]
    artifact = index if missing == "index" else ProviderArtifact(**(raw_ref if missing == "raw" else projection[missing]))
    del catalog[artifact.sha256]
    result = _resolve(manifest, index, catalog)
    assert [row.key for row in result.sources] == ["main"]
    assert result.sources[0].raw_artifact.sha256 == raw_ref["sha256"]
    assert result.sources[0].bundle is None and not result.format_replayed
    assert "inventory_artifact_missing" in _codes(result)


def test_line_budget_is_shared_across_sources_and_never_drops_pending_source_keys():
    raw = b'{"kind":"opaque"}\n'
    manifest, index, catalog = inventory_sources(raw_streams={"one": raw, "two": raw})
    result = _resolve(manifest, index, catalog, max_lines=1)
    assert [row.key for row in result.sources] == ["one", "two"]
    assert result.sources[0].projection_replayed
    assert result.sources[1].bundle is None
    assert not result.format_replayed and "inventory_budget" in _codes(result)


def test_artifact_budget_and_byte_budget_keep_all_known_manifest_placeholders():
    manifest, index, catalog = inventory_sources(raw_streams={"one": b"", "two": b""})
    for limits in ({"max_artifacts": 2}, {"max_bytes": manifest.size_bytes + index.size_bytes}):
        result = _resolve(manifest, index, catalog, **limits)
        assert [row.key for row in result.sources] == ["one", "two"]
        assert not result.format_replayed and "inventory_budget" in _codes(result)


def test_unsupported_recipe_never_reads_or_executes_recipe_path():
    manifest, index, catalog = inventory_sources()
    document = _doc(catalog, index)
    document["entries"][0]["projection"]["recipe"]["implementation"] = {
        "path": "/must/not/read/or/execute.py", "fingerprint": "sha256:" + "f" * 64}
    result = _resolve(manifest, _pack(catalog, index, document), catalog)
    assert not result.format_replayed
    assert result.sources[0].bundle is None
    assert "inventory_recipe_unsupported" in _codes(result)


def test_declared_unresolved_projection_is_not_an_omitted_source():
    manifest, index, catalog = inventory_sources()
    document = _doc(catalog, index)
    document["entries"][0]["projection"] = {"kind": "unresolved", "reason": "collector profile has no normalization adapter"}
    result = _resolve(manifest, _pack(catalog, index, document), catalog)
    assert len(result.sources) == 1 and not result.format_replayed
    assert "inventory_projection_unresolved" in _codes(result)


def test_collector_loss_and_opaque_capture_gaps_survive_successful_format_replay():
    manifest, index, catalog = inventory_sources(metadata={"main": {
        "ended_ns": 10, "dropped_events": 3, "io_failed": True, "errors": ["missing window"]}})
    result = _resolve(manifest, index, catalog)
    assert result.format_replayed
    assert {"inventory_collection_gap", "inventory_capture_unverified"} <= _codes(result)


@pytest.mark.parametrize("metadata", [{"dropped_events": True},
                                     {"started_ns": 20, "ended_ns": 10},
                                     {"errors": "silently ignored error"}])
def test_known_metadata_type_or_window_contradiction_is_rejected(metadata):
    manifest, index, catalog = inventory_sources(metadata={"main": metadata})
    with pytest.raises(ValueError):
        _resolve(manifest, index, catalog)


def test_known_provider_process_scope_conflict_is_not_hidden_by_partial_capture():
    scope = ProviderRunScope("provider-run", 999, "window", "clock")
    manifest, index, catalog = inventory_sources(scopes={"main": scope})
    with pytest.raises(ValueError, match="process ID"):
        _resolve(manifest, index, catalog)


def test_present_none_or_identity_mismatch_is_not_downgraded_to_missing():
    manifest, index, catalog = inventory_sources()
    catalog[manifest.sha256] = None
    with pytest.raises(ValueError):
        _resolve(manifest, index, catalog)
    manifest, index, catalog = inventory_sources()
    catalog[manifest.sha256] += b" "
    with pytest.raises(ValueError):
        _resolve(manifest, index, catalog)


def test_strict_control_json_rejects_duplicates_and_nonfinite_numbers():
    manifest, index, catalog = inventory_sources()
    for payload in (b'{"schema":1,"schema":2}', b'{"value":NaN}'):
        bad = replace(manifest, sha256=hashlib.sha256(payload).hexdigest(), size_bytes=len(payload))
        catalog[bad.sha256] = payload
        with pytest.raises(ValueError):
            _resolve(bad, index, catalog)


def test_source_input_set_is_sealed_without_accepting_an_execution_writer_list():
    manifest, index, catalog = inventory_sources()
    with pytest.raises(TypeError):
        InventoryResolver(ExternalSnapshots(artifact_bytes=catalog)).resolve(manifest, index, contributions=())
    result = _resolve(manifest, index, catalog)
    assert result.sources[0].bundle.evidence.edges
    assert "inventory_capture_unverified" in _codes(result)


def test_normalize_bytes_rejects_nonexact_or_invalid_limits_without_changing_old_entrypoints():
    for limits in ({"max_lines": True}, {"max_line_bytes": 0}):
        with pytest.raises(ValueError):
            normalize_bytes(b"", **limits)
    with pytest.raises(TypeError):
        normalize_bytes(bytearray())
    with pytest.raises(ValueError, match="budget"):
        normalize_bytes(b'{}\n{}', max_lines=1)
    with pytest.raises(ValueError, match="budget"):
        normalize_bytes(b'{}\n', max_line_bytes=1)
