"""v14 encodes session posts/reference release without upgrading old graphs."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from scar.ir.program.codec import SCHEMA_VERSION, dumps, loads
from scar.ir.program.frames import FrameRules
from tests.fixtures.program_no_body_graphs import no_body_program
from tests.fixtures.program_session_release_graphs import session_release_program


FIXTURES = Path(__file__).parents[1] / "fixtures"
SESSION_RELEASE_FIELDS = {"session_updates", "terminal_frame_releases"}


def _old(version):
    document = json.loads((FIXTURES / f"program_graph_v{max(2, version)}_frozen.json").read_text())
    if version == 1:
        document["schema_version"] = 1
        for operation in document["operations"]:
            operation.pop("completions", None)
            operation.pop("invoke_arguments", None)
    return document


@pytest.mark.parametrize("binding", ["AFTER_OPERATION", "NORMAL_COMPLETION"])
@pytest.mark.parametrize("post", ["HOLD", "COMPLETE", "ABANDON"])
def test_session_release_roundtrip_preserves_all_canonical_producers(binding, post):
    graph = session_release_program(binding=binding, post=post, strict_subset=True, extra_domain=True)
    payload = dumps(graph)
    document = json.loads(payload)
    assert SCHEMA_VERSION == 27
    assert document["schema_version"] == 14
    assert document["session_updates"] and document["terminal_frame_releases"]
    assert loads(payload) == graph
    assert dumps(loads(payload)) == payload
    assert {value.id: value.origin for value in loads(payload).values} == {
        value.id: value.origin for value in graph.values}
    assert not {"session_facts", "finished_facts", "release_permissions"} & set(document)


@pytest.mark.parametrize("source", ["raise", "no-body", "suspend"])
def test_source_frontiers_roundtrip_without_treating_suspend_as_finished(source):
    graph = session_release_program(source=source, release=source != "suspend")
    assert loads(dumps(graph)) == graph
    assert bool(graph.terminal_frame_releases) is (source != "suspend")


def test_distinct_real_release_attempts_roundtrip_without_a_consumed_bit():
    graph = session_release_program(repeat_release=True)
    assert len(graph.terminal_frame_releases) == 2
    assert graph.terminal_frame_releases[0].operation != graph.terminal_frame_releases[1].operation
    assert loads(dumps(graph)) == graph


@pytest.mark.parametrize("table", sorted(SESSION_RELEASE_FIELDS))
def test_each_new_table_independently_selects_v14(table):
    graph = session_release_program()
    absent = next(name for name in SESSION_RELEASE_FIELDS if name != table)
    graph = replace(graph, **{absent: ()})
    document = json.loads(dumps(graph))
    assert document["schema_version"] == 14
    assert document[table] and document[absent] == []
    assert loads(dumps(graph)) == graph


@pytest.mark.parametrize("version", range(1, 14))
def test_each_historical_schema_rejects_new_tables_even_when_empty(version):
    document = _old(version)
    for field in SESSION_RELEASE_FIELDS:
        with pytest.raises(ValueError, match="top-level fields"):
            loads(json.dumps({**document, field: []}))


@pytest.mark.parametrize("version", range(2, 14))
def test_historical_wire_bytes_remain_exact_without_new_declarations(version):
    raw = (FIXTURES / f"program_graph_v{version}_frozen.json").read_bytes()
    payload = raw.decode().rstrip("\n")
    graph = loads(payload)
    assert graph.session_updates == graph.terminal_frame_releases == ()
    assert dumps(graph) == payload
    if version == 13:
        proof = json.loads((FIXTURES / "program_graph_v13_frozen.proof.json").read_text())
        assert proof["codec_path_inside_immutable_archive"] is True
        assert proof["codec_schema_version"] == proof["wire_schema_version"] == 13
        assert proof["source_revision"].startswith("817cc0b")
        assert proof["fixture_bytes"] == len(raw)
        assert proof["fixture_sha256"] == hashlib.sha256(raw).hexdigest()
        assert dumps(no_body_program(target="value", extra_domain=True, strict_subset=True)) == payload


def test_v14_requires_actual_capability_and_exact_fields_without_downgrade():
    document = _old(13)
    document.update(schema_version=14, **{name: [] for name in SESSION_RELEASE_FIELDS})
    with pytest.raises(ValueError, match="requires explicit session/release capability"):
        loads(json.dumps(document))
    document = json.loads(dumps(session_release_program()))
    for field in SESSION_RELEASE_FIELDS:
        with pytest.raises(ValueError, match="top-level fields"):
            loads(json.dumps({name: value for name, value in document.items() if name != field}))
    with pytest.raises(ValueError, match="top-level fields"):
        loads(json.dumps({**document, "schema_version": 13}))
    with pytest.raises(ValueError, match="top-level fields"):
        loads(json.dumps({**document, "finished_facts": []}))


def test_wire_cannot_claim_authority_change_fixed_rules_or_coalesce_role_uses():
    payload = dumps(session_release_program())
    document = json.loads(payload)
    document["session_updates"][0]["runtime_verified"] = True
    with pytest.raises((ValueError, TypeError)):
        loads(json.dumps(document))
    document = json.loads(payload)
    document["session_updates"][0]["request"] = document["session_updates"][0]["body"]
    with pytest.raises((ValueError, TypeError)):
        loads(json.dumps(document))
    document = json.loads(payload)
    document["terminal_frame_releases"][0]["rules"]["condition_status"] = "PROVEN"
    with pytest.raises((ValueError, TypeError)):
        loads(json.dumps(document))


def test_encode_revalidates_nested_fixed_rules_and_binding_enum_without_global_poisoning():
    graph = session_release_program()
    release = replace(graph.terminal_frame_releases[0], rules=FrameRules())
    graph = replace(graph, terminal_frame_releases=(release, *graph.terminal_frame_releases[1:]))
    object.__setattr__(release.rules, "release", True)
    with pytest.raises((ValueError, TypeError)):
        dumps(graph)
    graph = session_release_program()
    object.__setattr__(graph.session_updates[0], "binding", "AFTER_OPERATION")
    with pytest.raises((ValueError, TypeError)):
        dumps(graph)
