"""Only declared current-state predicates and no-body finishes require v13."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scar.ir.program.codec import SCHEMA_VERSION, dumps, loads
from tests.fixtures.program_no_body_graphs import no_body_program
from tests.fixtures.program_publication_graphs import publication_program


FIXTURES = Path(__file__).parents[1] / "fixtures"
NO_BODY_FIELDS = {"created_close_tests", "no_body_finishes"}


def _old(version):
    document = json.loads((FIXTURES / f"program_graph_v{max(2, version)}_frozen.json").read_text())
    if version == 1:
        document["schema_version"] = 1
        for operation in document["operations"]:
            operation.pop("completions", None)
            operation.pop("invoke_arguments", None)
    return document


@pytest.mark.parametrize("receiver", ["BODY", "ASYNC_REQUEST"])
@pytest.mark.parametrize("predicate_only", [False, True])
def test_no_body_and_predicate_only_roundtrip_without_publishing_future_d2_tables(receiver, predicate_only):
    graph = no_body_program(receiver=receiver, predicate_only=predicate_only, strict_subset=True, extra_domain=True)
    payload = dumps(graph)
    document = json.loads(payload)
    assert SCHEMA_VERSION == 17
    assert document["schema_version"] == 13
    assert NO_BODY_FIELDS <= set(document)
    assert document["created_close_tests"]
    assert bool(document["no_body_finishes"]) is (not predicate_only)
    assert not {"session_updates", "terminal_frame_releases", "finished_facts"} & set(document)
    assert loads(payload) == graph
    assert dumps(loads(payload)) == payload


def test_explicit_async_association_composes_with_the_same_v13_wire():
    graph = no_body_program(receiver="ASYNC_REQUEST", association=True)
    assert graph.request_association_reads
    assert loads(dumps(graph)) == graph
    assert json.loads(dumps(graph))["schema_version"] == 13


@pytest.mark.parametrize("version", range(1, 13))
def test_each_legacy_schema_rejects_both_no_body_tables_even_empty(version):
    original = _old(version)
    for field in NO_BODY_FIELDS:
        with pytest.raises(ValueError, match="top-level fields"):
            loads(json.dumps({**original, field: []}))


@pytest.mark.parametrize("version", range(2, 13))
def test_all_frozen_legacy_wires_remain_exact_and_carry_no_no_body_declarations(version):
    raw = (FIXTURES / f"program_graph_v{version}_frozen.json").read_bytes()
    payload = raw.decode().rstrip("\n")
    graph = loads(payload)
    assert graph.created_close_tests == graph.no_body_finishes == ()
    assert not NO_BODY_FIELDS & set(json.loads(payload))
    assert dumps(graph) == payload
    if version == 12:
        proof = json.loads((FIXTURES / "program_graph_v12_frozen.proof.json").read_text())
        assert proof["codec_path_inside_immutable_archive"] is True
        assert proof["codec_schema_version"] == proof["wire_schema_version"] == 12
        assert proof["fixture_sha256"] == hashlib.sha256(raw).hexdigest()
        assert proof["fixture_bytes"] == len(raw)
        assert proof["source_revision"].startswith("e86563a")
        assert dumps(publication_program(target="value", extra_domain=True, strict_subset=True)) == payload


def test_v13_requires_real_capability_both_tables_and_rejects_unimplemented_fields():
    document = _old(12)
    document.update(schema_version=13, **{field: [] for field in NO_BODY_FIELDS})
    with pytest.raises(ValueError, match="requires explicit no-body capability"):
        loads(json.dumps(document))
    document = json.loads(dumps(no_body_program()))
    for field in NO_BODY_FIELDS:
        with pytest.raises(ValueError, match="top-level fields"):
            loads(json.dumps({name: value for name, value in document.items() if name != field}))
    document["terminal_frame_releases"] = []
    with pytest.raises(ValueError, match="top-level fields"):
        loads(json.dumps(document))


def test_no_body_cannot_downgrade_omit_scope_invert_true_edge_or_self_assert_proof():
    graph = no_body_program()
    document = json.loads(dumps(graph))
    with pytest.raises(ValueError, match="top-level fields"):
        loads(json.dumps({**document, "schema_version": 12}))
    with pytest.raises(ValueError):
        dumps(replace(graph, driver_lifecycles=()))
    finish = document["no_body_finishes"][0]
    finish["precondition"]["successor_index"] = 1
    with pytest.raises(ValueError):
        loads(json.dumps(document))
    document = json.loads(dumps(graph))
    document["created_close_tests"][0]["guard_verified"] = True
    with pytest.raises((ValueError, TypeError)):
        loads(json.dumps(document))


def test_nested_precondition_mutation_is_rechecked_before_encode():
    graph = no_body_program()
    object.__setattr__(graph.no_body_finishes[0].precondition, "successor_index", True)
    with pytest.raises((ValueError, TypeError)):
        dumps(graph)


@pytest.mark.parametrize("mode", ["publication", "predicate", "finish"])
def test_cli_separates_predicate_structure_finish_count_and_runtime_authority(mode, tmp_path, capsys):
    from scar.cli import _check_program

    graph = publication_program() if mode == "publication" else no_body_program(predicate_only=mode == "predicate")
    source = tmp_path / "graph.json"
    source.write_text(dumps(graph))
    assert _check_program(SimpleNamespace(graph=str(source), out=None)) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["no_body_structure_validated"] is (mode != "publication")
    if mode != "publication":
        assert report["counts"]["created_close_tests"] == len(graph.created_close_tests)
        assert report["counts"]["no_body_finishes"] == (0 if mode == "predicate" else len(graph.no_body_finishes))
    for name in ("driver_lifecycle_verified", "body_driver_verified", "body_runtime_verified",
                 "body_source_verified", "body_exclusivity_verified", "source_recovery",
                 "transformation_authorized"):
        assert report[name] is False


def test_invalid_no_body_cli_never_sets_structure_success(tmp_path, capsys):
    from scar.cli import _check_program

    document = json.loads(dumps(no_body_program()))
    document["no_body_finishes"][0]["precondition"]["successor_index"] = 1
    source = tmp_path / "invalid.json"
    source.write_text(json.dumps(document))
    assert _check_program(SimpleNamespace(graph=str(source), out=None)) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "INVALID"
    assert report["no_body_structure_validated"] is False
    assert report["driver_lifecycle_verified"] is False
