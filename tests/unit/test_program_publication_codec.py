"""D2.1 adds only explicit scope/body-publication wire capability v12."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scar.ir.program.codec import SCHEMA_VERSION, dumps, loads
from scar.ir.program.ids import ValueID
from tests.fixtures.program_driver_graphs import driver_program
from tests.fixtures.program_publication_graphs import publication_program


FIXTURES = Path(__file__).parents[1] / "fixtures"
PUBLICATION_FIELDS = {"driver_lifecycles", "body_outcome_commits"}


def _old(version):
    document = json.loads((FIXTURES / f"program_graph_v{max(version, 2)}_frozen.json").read_text())
    if version == 1:
        document["schema_version"] = 1
        for operation in document["operations"]:
            operation.pop("completions", None)
            operation.pop("invoke_arguments", None)
    return document


@pytest.mark.parametrize("target", ["start", "value", "packet"])
def test_scoped_body_publication_roundtrips_as_v12_without_adding_other_d2_tables(target):
    graph = publication_program(target=target, create=True, extra_domain=True)
    payload = dumps(graph)
    document = json.loads(payload)
    assert SCHEMA_VERSION == 21
    assert document["schema_version"] == 12
    assert PUBLICATION_FIELDS <= set(document)
    assert document["driver_lifecycles"] and document["body_outcome_commits"]
    assert not {"session_updates", "terminal_frame_releases", "no_body_finishes"} & set(document)
    assert loads(payload) == graph
    assert dumps(loads(payload)) == payload


@pytest.mark.parametrize("version", range(1, 12))
def test_all_legacy_schemas_reject_both_new_tables_including_empty_fields(version):
    original = _old(version)
    for field in PUBLICATION_FIELDS:
        with pytest.raises(ValueError, match="top-level fields"):
            loads(json.dumps({**original, field: []}))


@pytest.mark.parametrize("version", range(2, 12))
def test_legacy_golden_wires_remain_byte_exact_and_have_no_publication_scope(version):
    raw = (FIXTURES / f"program_graph_v{version}_frozen.json").read_bytes()
    payload = raw.decode("utf-8").rstrip("\n")
    graph = loads(payload)
    assert graph.driver_lifecycles == graph.body_outcome_commits == ()
    assert not PUBLICATION_FIELDS & set(json.loads(payload))
    assert dumps(graph) == payload
    if version == 11:
        proof = json.loads((FIXTURES / "program_graph_v11_frozen.proof.json").read_text())
        assert proof["codec_path_inside_immutable_archive"] is True
        assert proof["codec_schema_version"] == proof["wire_schema_version"] == 11
        assert proof["fixture_sha256"] == hashlib.sha256(raw).hexdigest()
        assert proof["fixture_bytes"] == len(raw)
        assert proof["source_revision"].startswith("38d2968")


def test_v12_requires_real_capability_exact_tables_and_never_swallows_future_fields():
    document = _old(11)
    document.update(schema_version=12, **{field: [] for field in PUBLICATION_FIELDS})
    with pytest.raises(ValueError, match="requires explicit body-publication capability"):
        loads(json.dumps(document))
    document = json.loads(dumps(publication_program()))
    for field in PUBLICATION_FIELDS:
        missing = {name: value for name, value in document.items() if name != field}
        with pytest.raises(ValueError, match="top-level fields"):
            loads(json.dumps(missing))
    document["session_updates"] = []
    with pytest.raises(ValueError, match="top-level fields"):
        loads(json.dumps(document))


def test_publication_cannot_downgrade_or_omit_scope_and_cannot_self_assert_runtime_proof():
    graph = publication_program()
    document = json.loads(dumps(graph))
    downgraded = {**document, "schema_version": 11}
    with pytest.raises(ValueError, match="top-level fields"):
        loads(json.dumps(downgraded))
    with pytest.raises(ValueError):
        dumps(replace(graph, driver_lifecycles=()))
    without_scope = {**document, "driver_lifecycles": []}
    with pytest.raises(ValueError):
        loads(json.dumps(without_scope))
    document["body_outcome_commits"][0]["outcome"]["runtime_verified"] = True
    with pytest.raises((ValueError, TypeError)):
        loads(json.dumps(document))


def test_nested_record_mutation_is_rechecked_before_encoding():
    graph = publication_program()
    object.__setattr__(graph.body_outcome_commits[0].outcome, "source", ValueID("wrong-id-type"))
    with pytest.raises((ValueError, TypeError)):
        dumps(graph)


@pytest.mark.parametrize("published", [False, True])
def test_program_cli_distinguishes_publication_from_d1_and_full_lifecycle(published, tmp_path, capsys):
    from scar.cli import _check_program

    graph = publication_program() if published else driver_program()
    source = tmp_path / "program.json"
    source.write_text(dumps(graph), encoding="utf-8")
    assert _check_program(SimpleNamespace(graph=str(source), out=None)) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["body_publication_structure_validated"] is published
    if published:
        assert report["counts"]["driver_lifecycles"] == len(graph.driver_lifecycles)
        assert report["counts"]["body_outcome_commits"] == len(graph.body_outcome_commits)
    else:
        assert "body_outcome_commits" not in report["counts"]
    for name in ("driver_lifecycle_verified", "body_driver_verified", "body_runtime_verified",
                 "body_source_verified", "body_exclusivity_verified", "source_recovery",
                 "transformation_authorized"):
        assert report[name] is False


def test_invalid_publication_cli_does_not_publish_a_success_flag(tmp_path, capsys):
    from scar.cli import _check_program

    document = json.loads(dumps(publication_program()))
    document["body_outcome_commits"] = []
    source = tmp_path / "invalid.json"
    source.write_text(json.dumps(document), encoding="utf-8")
    assert _check_program(SimpleNamespace(graph=str(source), out=None)) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "INVALID"
    assert report["body_publication_structure_validated"] is False
    assert report["driver_lifecycle_verified"] is False
