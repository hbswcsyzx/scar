"""Composed protocols retain canonical links without a new wire schema."""
from pathlib import Path
import hashlib
import json

import pytest

from scar.ir.program.codec import SCHEMA_VERSION, dumps, loads
from scar.ir.program.queries import ProgramIndex
from scar.ir.v2.common import ProofStatus
from tests.fixtures.program_lifecycle_body_composition import body_cleanup_lifecycle_program
from tests.fixtures.program_lifecycle_cleanup_graphs import driver_cleanup_release_program
from tests.fixtures.program_session_release_graphs import session_release_program


FIXTURES = Path(__file__).parents[1] / "fixtures"


def test_immutable_d2_3_v14_wire_is_unchanged_by_query_scope_views():
    raw = (FIXTURES / "program_graph_v14_frozen.json").read_bytes()
    proof = json.loads((FIXTURES / "program_graph_v14_frozen.proof.json").read_text())
    assert proof["source_revision"] == "fdf9d0d37ab043db297f095bfafa685b32b0b058"
    assert proof["codec_schema_version"] == proof["wire_schema_version"] == 14
    assert SCHEMA_VERSION == 15
    assert proof["codec_path_inside_immutable_archive"] is True
    assert proof["fixture_bytes"] == len(raw)
    assert proof["fixture_sha256"] == hashlib.sha256(raw).hexdigest()
    payload = raw.decode()
    graph = loads(payload)
    assert dumps(graph) == payload
    assert dumps(session_release_program(binding="NORMAL_COMPLETION", strict_subset=True, extra_domain=True)) == payload
    index = ProgramIndex(graph)
    scope = index.lifecycle_scope(graph.driver_interfaces[0].region)
    assert scope.applicability is ProofStatus.UNKNOWN
    assert index.session_publication(graph.session_updates[0].operation).point.scope is scope
    assert dumps(graph) == payload
    document = json.loads(payload)
    assert not {"lifecycle_scopes", "lifecycle_points", "lifecycle_facts"} & document.keys()


@pytest.mark.parametrize("factory", (
    lambda: body_cleanup_lifecycle_program(binding="AFTER_OPERATION"),
    lambda: body_cleanup_lifecycle_program(binding="NORMAL_COMPLETION"),
    lambda: driver_cleanup_release_program(helper=False),
    lambda: driver_cleanup_release_program(helper=True),
))
def test_real_cleanup_composition_roundtrip_keeps_sources_context_and_current_state(factory):
    graph = factory()
    payload = dumps(graph)
    decoded = loads(payload)
    assert decoded == graph
    assert dumps(decoded) == payload
    assert json.loads(payload)["schema_version"] == 14
    assert decoded.cleanup_interfaces == graph.cleanup_interfaces
    assert decoded.cleanup_replacements == graph.cleanup_replacements
    assert decoded.body_outcome_commits == graph.body_outcome_commits
    index = ProgramIndex(decoded)
    for release in decoded.terminal_frame_releases:
        view = index.terminal_release_publication(release.operation)
        assert view.release is release
        assert view.point.terminal.is_finished(view.owner.use.value)
        assert view.point.scope.applicability is ProofStatus.UNKNOWN
        assert all(source.commit in decoded.body_outcome_commits for source in view.sources)
        assert all(index.producer(access.after.id) is access.after.origin for access in view.accesses)
