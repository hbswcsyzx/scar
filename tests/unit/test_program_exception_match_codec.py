"""Program21 matcher capability, strict nested tags, and old wire isolation."""
from dataclasses import fields, replace
import hashlib
import json
from pathlib import Path

import pytest

from scar.ir.program import codec
from scar.ir.program.exception_matches import ExceptionHandlerOperand, FixedBuiltinHandler
from scar.ir.program.model import ProgramGraph
from scar.ir.program.validation import require_valid
from tests.fixtures.program_exception_match_graphs import exception_match_program
from tests.fixtures.program_method_lookup_graphs import method_lookup_program


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
ORACLE_REVISION = "8f08bda1d192f7f9b778c06bb51d6509e17fc8ca"


def _document(*, mode="ordinary", input_kind="reference"):
    graph, _ = exception_match_program(mode=mode, input_kind=input_kind)
    require_valid(graph)
    return graph, json.loads(codec.dumps(graph))


@pytest.mark.parametrize("mode", ("ordinary", "invoke", "raise-only"))
@pytest.mark.parametrize("input_kind", ("reference", "packet"))
def test_matchers_select_program21_without_a_fake_protocol_scope(mode, input_kind):
    graph, document = _document(mode=mode, input_kind=input_kind)
    assert codec.SCHEMA_VERSION == 25
    assert not graph.protocol_scopes and not graph.protocol_operations
    assert document["schema_version"] == 21
    assert set(document) == ({field.name for field in fields(ProgramGraph)} - {"call_effect_expansions"}) | {"schema", "schema_version"}
    row, = document["exception_matches"]
    assert row["kind"] == "EXCEPTION_MATCHER"
    assert row["handler"]["kind"] == ("FIXED_BUILTIN_EXCEPTION_HANDLER" if mode == "ordinary"
                                       else "EXCEPTION_HANDLER_OPERAND")
    if mode == "raise-only":
        assert row["normal_result"] is row["branch"] is None
        assert row["raise_result"]["kind"] == "INVOKE_LITERAL_RESULT"
    elif mode == "invoke":
        assert row["normal_result"]["kind"] == row["raise_result"]["kind"] == "INVOKE_LITERAL_RESULT"
        assert row["handler"]["interpretation"]["kind"] == "FIXED_BUILTIN_EXCEPTION_HANDLER"
    else:
        assert row["raise_result"] is None
    wire = codec.dumps(graph)
    recovered = codec.loads(wire)
    assert recovered == graph
    assert codec.dumps(recovered) == wire
    assert type(recovered.exception_matches[0].handler) is (
        FixedBuiltinHandler if mode == "ordinary" else ExceptionHandlerOperand)


def test_removing_matcher_attachment_does_not_add_empty_fields_to_older_wire():
    graph, _ = exception_match_program()
    original = replace(graph, exception_matches=())
    require_valid(original)
    wire = codec.dumps(original)
    document = json.loads(wire)
    assert document["schema_version"] < 21
    assert "exception_matches" not in document
    recovered = codec.loads(wire)
    assert recovered == original and recovered.exception_matches == ()
    assert codec.dumps(recovered) == wire


def test_independent_program20_oracle_keeps_the_old_encoder_bytes():
    wire = (FIXTURES / "program_graph_v20_frozen.json").read_bytes()
    proof = json.loads((FIXTURES / "program_graph_v20_frozen.proof.json").read_text())
    assert proof["source_revision"] == ORACLE_REVISION
    assert proof["schema_version"] == 20
    assert proof["fixture_profile"] == "method_lookup_program(request='send')"
    assert len(wire) == proof["fixture_bytes"]
    assert hashlib.sha256(wire).hexdigest() == proof["fixture_sha256"]
    document = json.loads(wire)
    assert document["schema_version"] == 20
    assert "exception_matches" not in document
    old = codec.loads(wire.decode("ascii"))
    assert old.exception_matches == ()
    assert codec.dumps(old).encode("ascii") == wire
    current, _ = method_lookup_program(request="send")
    assert codec.dumps(current).encode("ascii") == wire


@pytest.mark.parametrize("version", range(2, 21))
def test_legacy_wire_profiles_stay_byte_exact_and_reject_even_empty_matcher_field(version):
    # Some original fixture files include a terminating line separator. It is
    # not a codec output byte and the historical files themselves stay intact.
    wire = (FIXTURES / f"program_graph_v{version}_frozen.json").read_bytes().rstrip(b"\n")
    old = codec.loads(wire.decode("utf8"))
    assert old.exception_matches == ()
    assert codec.dumps(old).encode("utf8") == wire
    document = json.loads(wire)
    document["exception_matches"] = []
    with pytest.raises(ValueError, match="incorrect top-level fields"):
        codec.loads(json.dumps(document))


def test_program21_requires_a_nonempty_matcher_capability_and_exact_top_level_fields():
    _, document = _document()
    document["exception_matches"] = []
    with pytest.raises(ValueError, match="requires explicit exception matcher capability"):
        codec.loads(json.dumps(document))
    del document["exception_matches"]
    with pytest.raises(ValueError, match="incorrect top-level fields"):
        codec.loads(json.dumps(document))


def test_program20_cannot_load_a_program21_matcher_table():
    _, document = _document()
    document["schema_version"] = 20
    with pytest.raises(ValueError, match="incorrect top-level fields"):
        codec.loads(json.dumps(document))


@pytest.mark.parametrize("change", ("unknown_kind", "missing_field", "extra_authority", "boolean_slot",
                                   "wrong_handler_kind", "unknown_category", "formal_as_result"))
def test_program21_rechecks_exact_nested_tags_fields_and_original_port_types(change):
    _, document = _document()
    row, = document["exception_matches"]
    if change == "unknown_kind":
        row["kind"] = "UNREGISTERED_EXCEPTION_MATCHER"
    elif change == "missing_field":
        del row["state_sites"]
    elif change == "extra_authority":
        row["verified"] = False
    elif change == "boolean_slot":
        row["normal_result"]["index"] = True
    elif change == "wrong_handler_kind":
        row["handler"]["kind"] = "EXCEPTION_HANDLER_OPERAND"
    elif change == "unknown_category":
        row["handler"]["category"] = "ARBITRARY_CLASS_NAME"
    else:
        row["normal_result"] = row["source"]
    with pytest.raises((TypeError, ValueError)):
        codec.loads(json.dumps(document))


def test_matcher_natural_key_cannot_be_duplicated_on_the_wire():
    _, document = _document()
    document["exception_matches"].append(document["exception_matches"][0])
    with pytest.raises((TypeError, ValueError)):
        codec.loads(json.dumps(document))


def test_new_handler_record_cannot_hide_inside_an_old_program20_source_union():
    _, matcher_document = _document()
    document = json.loads((FIXTURES / "program_graph_v20_frozen.json").read_text())
    document["protocol_call_inputs"][0]["cases"][0]["receiver"] = matcher_document["exception_matches"][0]["handler"]
    with pytest.raises((TypeError, ValueError)):
        codec.loads(json.dumps(document))


@pytest.mark.parametrize("version", (26, True))
def test_future_and_boolean_schema_versions_remain_rejected(version):
    _, document = _document()
    document["schema_version"] = version
    with pytest.raises(ValueError, match="unsupported program graph schema version"):
        codec.loads(json.dumps(document))
