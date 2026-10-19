"""Program23 wire isolation and an independently executed immutable v22 oracle.

The oracle test runs the historical encoder only inside a git archive.  No
current encoder is used to manufacture the expected historical bytes.
"""
from dataclasses import fields, replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import textwrap

import pytest

from scar.ir.program import codec
from scar.ir.program.ids import OperationID, ProtocolScopeID, UseID
from scar.ir.program.model import ProgramGraph
from scar.ir.program.protocol_await_records import (
    AwaitAcquisition, AwaitBodyLink, AwaitIteratorQualification, CoroutineAwaitWrapper,
    has_await_acquisition_capability,
)
from scar.ir.program.protocol_connections import (
    ProtocolOperationRef, PROTOCOL_CONNECTION_RECORD_TAGS,
)
from scar.ir.program.protocols import (
    OperationSiteSubject, ProtocolClause as C, ProtocolOperation, ProtocolProfile as F,
    ProtocolScope, StaticGapReason, StaticProtocolGap,
)
from scar.ir.program.state_addresses import STATE_ADDRESS_RECORD_TAGS, ExistingAccess
from scar.ir.record_codec import encode
from tests.fixtures.program_continuation_graphs import continuation_site_program
from tests.fixtures.program_lookup_fallback_graphs import lookup_fallback_program


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
REPOSITORY = Path(__file__).resolve().parents[2]
ORACLE_REVISION = "0bbc6235992e89e2a5735287e94622cfe0755cf8"
ORACLE_CODEC_SHA256 = "2ca1c589997ca4efdec69a4fcc1bab68d32b8413d7386aa5bee1deab4478bf5d"


def _graph(kind="acquisition", *, attach=True):
    # Reinterpret one original opaque INVOKE as the fixed declared primitive;
    # keep its actual Uses, N/R, state and generic consumers unchanged.  All
    # old language attachments are removed, so there is no second execution.
    graph, details = continuation_site_program(kind="await")
    view = details["lookup"]
    operation = view["operation"]
    expected = details["root_inputs"][0]
    expected_origin = next(value.origin for value in graph.values if value.id == expected)
    profile, clause, cls = {
        "acquisition": (F.AWAIT_ACQUISITION_V1, C.AWAIT_ACQUISITION, AwaitAcquisition),
        "qualification": (F.AWAIT_METHOD_IMPLEMENTATION_V1,
                          C.AWAIT_ITERATOR_QUALIFICATION, AwaitIteratorQualification),
        "wrapper": (F.COROUTINE_WRAPPER_CONSTRUCTION_V1,
                    C.WRAPPER_CONSTRUCTION, CoroutineAwaitWrapper),
    }[kind]
    scope = ProtocolScope(ProtocolScopeID("codec.await." + kind), profile,
        OperationSiteSubject(graph.root, operation.id),
        StaticProtocolGap(StaticGapReason.NATIVE_APPLICABILITY_UNPROVEN))
    rows = []
    for port in view["ports"]:
        args = (view["receiver"], expected_origin, port, view["state_sites"])
        contract = (cls(*args, StaticProtocolGap(StaticGapReason.PORT_UNCAPTURED))
                    if kind == "acquisition" else
                    cls(*args, None, None) if kind == "qualification" else cls(*args))
        rows.append(ProtocolOperation(scope.id, clause, operation.id,
            port.edge.successor_index, contract,
            StaticProtocolGap(StaticGapReason.NATIVE_APPLICABILITY_UNPROVEN)))
    return replace(graph, protocol_scopes=(scope,), protocol_operations=tuple(rows) if attach else (),
                   protocol_call_inputs=(), protocol_result_consumers=(), protocol_bindings=())


@pytest.mark.parametrize("kind", ("acquisition", "qualification", "wrapper"))
def test_v23_roundtrip_keeps_original_input_results_state_and_distinct_completions(kind):
    graph = _graph(kind)
    wire = codec.dumps(graph)
    document = json.loads(wire)
    assert codec.SCHEMA_VERSION == 23 and document["schema_version"] == 23
    assert set(document) == {item.name for item in fields(ProgramGraph)} | {"schema", "schema_version"}
    assert has_await_acquisition_capability(graph)
    recovered = codec.loads(wire)
    assert recovered == graph and codec.dumps(recovered) == wire
    assert recovered.operations == graph.operations and recovered.values == graph.values
    assert {row.slot for row in recovered.protocol_operations} == {0, 1}
    assert all(row.contract.result.edge.successor_index == row.slot
               for row in recovered.protocol_operations)
    assert all(row.contract.expected if kind != "wrapper" else row.contract.expected_body
               for row in recovered.protocol_operations)


@pytest.mark.parametrize("kind", ("acquisition", "qualification", "wrapper"))
def test_deleted_local_rows_keep_new_scope_capability_and_do_not_rewrite_old_ports(kind):
    graph = _graph(kind, attach=False)
    wire = codec.dumps(graph)
    assert json.loads(wire)["schema_version"] == 23
    recovered = codec.loads(wire)
    assert recovered == graph and not recovered.protocol_operations


@pytest.mark.parametrize("version", (19, 20, 21, 22))
def test_new_profile_and_contract_cannot_be_downgraded(version):
    document = json.loads(codec.dumps(_graph()))
    document["schema_version"] = version
    if version < 21:
        del document["exception_matches"]
    with pytest.raises((TypeError, ValueError)):
        codec.loads(json.dumps(document))


def test_untagged_new_contract_under_old_enums_still_cannot_enter_v22():
    document = json.loads(codec.dumps(_graph()))
    document["schema_version"] = 22
    document["protocol_scopes"][0]["profile"] = F.AWAIT_SITE_V1.value
    for row in document["protocol_operations"]:
        row["clause"] = C.AWAIT_CALL.value
        del row["contract"]["kind"]
    with pytest.raises(ValueError, match="historical schema cannot contain await acquisition capability"):
        codec.loads(json.dumps(document))


def test_untagged_new_binding_with_only_old_reference_enums_cannot_enter_v22():
    graph, _ = lookup_fallback_program(kind="close")
    document = json.loads(codec.dumps(graph))
    source = ProtocolOperationRef(ProtocolScopeID("old.scope"), C.AWAIT_CALL,
                                  OperationID("old.source"), 0)
    link = AwaitBodyLink(source, replace(source, operation=OperationID("advance")),
                         OperationID("drive"), None, None)
    # Excluding the Program23 registry deliberately removes the new top tag.
    document["protocol_bindings"].append(encode(link, record_tags=PROTOCOL_CONNECTION_RECORD_TAGS))
    with pytest.raises(ValueError, match="historical schema cannot contain await acquisition capability"):
        codec.loads(json.dumps(document))


@pytest.mark.parametrize("change", (
    "missing_expected", "extra_authority", "unknown_tag", "bool_slot",
    "wrong_id_namespace", "unknown_operand_fk", "unknown_expected_fk", "bool_state_index",
))
def test_v23_rejects_invalid_sources_fields_and_nested_ports(change):
    document = json.loads(codec.dumps(_graph()))
    row = document["protocol_operations"][0]
    contract = row["contract"]
    if change == "missing_expected":
        del contract["expected"]
    elif change == "extra_authority":
        contract["native_verified"] = False
    elif change == "unknown_tag":
        contract["kind"] = "OPEN_AWAIT_PROTOCOL"
    elif change == "bool_slot":
        row["slot"] = True
    elif change == "wrong_id_namespace":
        contract["operand_use"] = row["operation"]
    elif change == "unknown_operand_fk":
        contract["operand_use"] = encode(UseID("absent.operand"))
    elif change == "unknown_expected_fk":
        contract["expected"]["block"]["value"] = "absent.block"
        contract["expected"]["block"]["wire"] = "program_block:absent.block"
    else:
        contract["state_sites"][0] = {
            "kind": STATE_ADDRESS_RECORD_TAGS[ExistingAccess][1],
            "operation": row["operation"], "index": True,
        }
    with pytest.raises((TypeError, ValueError)):
        codec.loads(json.dumps(document))


def test_v23_cannot_upgrade_an_old_document_with_no_new_capability():
    graph, _ = lookup_fallback_program(kind="close")
    document = json.loads(codec.dumps(graph))
    assert document["schema_version"] == 22
    document["schema_version"] = 23
    with pytest.raises(ValueError, match="requires explicit await acquisition capability"):
        codec.loads(json.dumps(document))


@pytest.mark.parametrize("version", (True, 24))
def test_boolean_or_future_schema_version_is_not_a_capability(version):
    document = json.loads(codec.dumps(_graph()))
    document["schema_version"] = version
    with pytest.raises(ValueError, match="unsupported program graph schema version"):
        codec.loads(json.dumps(document))


def test_independent_v22_archive_encoder_preserves_meaningful_fallback_bytes(tmp_path):
    archive = tmp_path / "immutable-v22"
    archive.mkdir()
    tar_path = tmp_path / "source.tar"
    with tar_path.open("wb") as target:
        subprocess.run(["git", "archive", ORACLE_REVISION, "scar", "tests/fixtures"],
                       cwd=REPOSITORY, stdout=target, check=True)
    with tarfile.open(tar_path) as source:
        source.extractall(archive, filter="data")
    script = textwrap.dedent('''
        import hashlib, json, pathlib, sys, types
        root = pathlib.Path(sys.argv[1]).resolve()
        sys.path.insert(0, str(root))
        # Select the archive's tests namespace even if site-packages has tests.
        namespace = types.ModuleType("tests")
        namespace.__path__ = [str(root / "tests")]
        sys.modules["tests"] = namespace
        from scar.ir.program import codec, model
        from tests.fixtures import program_lookup_fallback_graphs as fixture
        assert codec.SCHEMA_VERSION == 22
        for module in (codec, model, fixture):
            assert pathlib.Path(module.__file__).resolve().is_relative_to(root)
        graph, _ = fixture.lookup_fallback_program(kind="throw", matcher="invoke", throw_arity=3)
        wire = codec.dumps(graph).encode("ascii")
        assert json.loads(wire)["schema_version"] == 22
        (root / "oracle.json").write_bytes(wire)
        proof = {"schema_version":22,
                 "source_codec_sha256":hashlib.sha256(pathlib.Path(codec.__file__).read_bytes()).hexdigest(),
                 "fixture_sha256":hashlib.sha256(wire).hexdigest(),
                 "fixture_bytes":len(wire),
                 "module_paths":[str(pathlib.Path(m.__file__).resolve()) for m in (codec,model,fixture)]}
        (root / "oracle.proof.json").write_text(json.dumps(proof,sort_keys=True))
        print(json.dumps(proof,sort_keys=True))
    ''')
    command = [sys.executable, "-B", "-c", script, str(archive)]
    result = subprocess.run(command, cwd=archive, check=True, capture_output=True, text=True,
                            env={**os.environ, "PYTHONPATH": str(archive),
                                 "PYTHONDONTWRITEBYTECODE": "1"})
    proof = json.loads(result.stdout)
    wire = (archive / "oracle.json").read_bytes()
    assert proof["source_codec_sha256"] == ORACLE_CODEC_SHA256
    assert proof["fixture_bytes"] == len(wire)
    assert proof["fixture_sha256"] == hashlib.sha256(wire).hexdigest()
    proof.update(source_revision=ORACLE_REVISION,
                 fixture_profile="lookup_fallback_program(kind='throw',matcher='invoke',throw_arity=3)",
                 archive_command=["git", "archive", ORACLE_REVISION, "scar", "tests/fixtures"],
                 child_command=command)
    (tmp_path / "v22.proof.json").write_text(json.dumps(proof, sort_keys=True, indent=2))
    print(json.dumps(proof, sort_keys=True))
    recovered = codec.loads(wire.decode("ascii"))
    assert not has_await_acquisition_capability(recovered)
    assert codec.dumps(recovered).encode("ascii") == wire
    current, _ = lookup_fallback_program(kind="throw", matcher="invoke", throw_arity=3)
    assert codec.dumps(current).encode("ascii") == wire


@pytest.mark.parametrize("version", range(2, 22))
def test_existing_historical_golden_bytes_are_not_rewritten(version):
    wire = (FIXTURES / f"program_graph_v{version}_frozen.json").read_bytes().rstrip(b"\n")
    graph = codec.loads(wire.decode("utf8"))
    assert not has_await_acquisition_capability(graph)
    assert codec.dumps(graph).encode("utf8") == wire
