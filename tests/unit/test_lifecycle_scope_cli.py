"""Machine reports preserve declared conditional scope without native authority."""
import json
from types import SimpleNamespace

import pytest

from scar.cli import _check_program
from scar.ir.program.codec import dumps
from scar.ir.record_codec import encode
from tests.fixtures.program_driver_graphs import driver_program
from tests.fixtures.program_no_body_graphs import no_body_program
from tests.fixtures.program_publication_graphs import publication_program
from tests.fixtures.program_session_release_graphs import session_release_program


@pytest.mark.parametrize("version", (11, 12, 13, 14))
def test_cli_original_scope_rule_fact_and_capabilities_are_machine_readable(version, tmp_path, capsys):
    graph = {11: driver_program, 12: publication_program, 13: no_body_program,
             14: session_release_program}[version]()
    path = tmp_path / "graph.json"
    payload = dumps(graph)
    path.write_text(payload)
    assert _check_program(SimpleNamespace(graph=str(path), out=None)) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["conditional_lifecycle_facts_derived"] is (version >= 12)
    assert report["session_release_structure_validated"] is (version == 14)
    if version == 11:
        assert report["conditional_lifecycle_scopes"] == []
    else:
        scope, = report["conditional_lifecycle_scopes"]
        interface = graph.driver_interfaces[0]
        assert scope["region"] == interface.region.wire
        assert scope["rule_profile"] == interface.rule.profile.value
        assert scope["implementation"] == encode(interface.rule.implementation)
        assert scope["applicability"] == "UNKNOWN"
        assert scope["conditional_facts_derived"] is True
        for name, count in scope["declared_capabilities"].items():
            assert count == len(getattr(graph, name))
        if version < 14:
            assert scope["declared_capabilities"]["session_updates"] == 0
            assert scope["declared_capabilities"]["terminal_frame_releases"] == 0
        # The existing implementation fact is retained even without a provider
        # envelope; no artifact contents or provenance relationship is invented.
        assert graph.provider_envelopes == ()
    for name in ("driver_lifecycle_verified", "body_source_verified", "body_runtime_verified",
                 "source_recovery", "transformation_authorized"):
        assert report[name] is False
    assert path.read_text() == payload


def test_predicate_only_reports_conditional_analysis_without_fabricating_finish(tmp_path, capsys):
    graph = no_body_program(predicate_only=True)
    path = tmp_path / "predicate.json"
    path.write_text(dumps(graph))
    assert _check_program(SimpleNamespace(graph=str(path), out=None)) == 0
    report = json.loads(capsys.readouterr().out)
    scope, = report["conditional_lifecycle_scopes"]
    assert scope["declared_capabilities"]["no_body_finishes"] == 0
    assert scope["applicability"] == "UNKNOWN"
    assert report["session_release_structure_validated"] is False


@pytest.mark.parametrize("failure", ("invalid-record", "same-output"))
def test_cli_failures_never_keep_scope_or_conditional_derivation(failure, tmp_path, capsys):
    graph = session_release_program()
    path = tmp_path / "graph.json"
    document = json.loads(dumps(graph))
    if failure == "invalid-record":
        document["session_updates"][0]["runtime_verified"] = True
    path.write_text(json.dumps(document))
    assert _check_program(SimpleNamespace(graph=str(path), out=str(path) if failure == "same-output" else None)) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["conditional_lifecycle_scopes"] == []
    assert report["conditional_lifecycle_facts_derived"] is False
    assert report["driver_lifecycle_verified"] is False
    assert report["transformation_authorized"] is False
