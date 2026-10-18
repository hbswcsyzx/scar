"""Address declarations use v15 without changing legacy state producers/wire."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from scar.ir.program import AccessMode as PublicAccessMode
from scar.ir.program.codec import SCHEMA_VERSION, dumps, loads
from scar.ir.program.model import AccessMode
from scar.ir.program.state_addresses import (
    AddressCoverage, AddressEffect, CellContent, DomainOwner, ExistingAccess,
    StateAddressRefinement, UnknownOwner, WholeOwner,
)
from scar.ir.program.state_modes import AccessMode as CanonicalAccessMode
from tests.fixtures.program_session_release_graphs import session_release_program
from tests.fixtures.program_state_addresses import state_address_program


FIXTURES = Path(__file__).parents[1] / "fixtures"
ADDRESS_FIELD = "state_address_refinements"


def _old(version):
    document = json.loads((FIXTURES / f"program_graph_v{max(version, 2)}_frozen.json").read_text())
    if version == 1:
        document["schema_version"] = 1
        for operation in document["operations"]:
            operation.pop("completions", None)
            operation.pop("invoke_arguments", None)
    return document


def _aggregate(graph):
    operations = {operation.id: operation for operation in graph.operations}
    return next(row for row in graph.state_address_refinements
                if type(row.site) is ExistingAccess
                and operations[row.site.operation].accesses[row.site.index].reference is None
                and not operations[row.site.operation].accesses[row.site.index].full_overwrite)


def test_v15_roundtrip_keeps_single_access_mode_and_original_producers():
    graph, _ = state_address_program()
    assert AccessMode is CanonicalAccessMode is PublicAccessMode
    document = json.loads(dumps(graph))
    assert SCHEMA_VERSION == 22
    assert document["schema_version"] == 15
    assert document[ADDRESS_FIELD]
    decoded = loads(dumps(graph))
    assert decoded == graph
    assert dumps(decoded) == dumps(graph)
    assert tuple((value.id, value.origin) for value in decoded.values) == tuple(
        (value.id, value.origin) for value in graph.values)
    assert tuple(operation.accesses for operation in decoded.operations) == tuple(
        operation.accesses for operation in graph.operations)
    stripped = replace(graph, state_address_refinements=())
    assert json.loads(dumps(stripped))["schema_version"] < 15
    assert ADDRESS_FIELD not in json.loads(dumps(stripped))
    assert stripped.values is graph.values and stripped.operations is graph.operations


def test_empty_owner_selector_variants_have_distinct_explicit_nested_tags():
    graph, _ = state_address_program()
    row = _aggregate(graph)
    access = next(op for op in graph.operations if op.id == row.site.operation).accesses[row.site.index]
    replacement = StateAddressRefinement(row.site, (
        AddressEffect(DomainOwner(), (WholeOwner(),), access.mode),
        AddressEffect(UnknownOwner("owner remains unknown"), (CellContent(),), access.mode),
    ), AddressCoverage.PARTIAL)
    graph = replace(graph, state_address_refinements=(replacement,))
    document = json.loads(dumps(graph))
    effects = document[ADDRESS_FIELD][0]["effects"]
    assert effects[0]["owner"] == {"kind": "DOMAIN_OWNER"}
    assert effects[0]["path"] == [{"kind": "WHOLE_OWNER"}]
    assert effects[1]["owner"]["kind"] == "UNKNOWN_OWNER"
    assert effects[1]["path"] == [{"kind": "CELL_CONTENT"}]
    assert loads(dumps(graph)) == graph


@pytest.mark.parametrize("version", range(1, 15))
def test_legacy_versions_reject_new_table_even_if_empty(version):
    with pytest.raises(ValueError, match="top-level fields"):
        loads(json.dumps({**_old(version), ADDRESS_FIELD: []}))


@pytest.mark.parametrize("version", range(2, 15))
def test_legacy_bytes_are_unchanged_and_never_gain_precision(version):
    raw = (FIXTURES / f"program_graph_v{version}_frozen.json").read_bytes()
    payload = raw.decode().rstrip("\n")
    graph = loads(payload)
    assert graph.state_address_refinements == ()
    assert dumps(graph) == payload
    if version == 14:
        proof = json.loads((FIXTURES / "program_graph_v14_frozen.proof.json").read_text())
        assert proof["codec_path_inside_immutable_archive"] is True
        assert proof["codec_schema_version"] == proof["wire_schema_version"] == 14
        assert proof["fixture_bytes"] == len(raw)
        assert proof["fixture_sha256"] == hashlib.sha256(raw).hexdigest()
        assert dumps(session_release_program(binding="NORMAL_COMPLETION", strict_subset=True,
                                             extra_domain=True)) == payload


def test_v1_migration_adds_no_address_capability_or_loss_of_ports():
    graph = loads(json.dumps(_old(1)))
    assert graph.state_address_refinements == ()
    assert json.loads(dumps(graph))["schema_version"] == 2
    assert loads(dumps(graph)) == graph


def test_v15_requires_capability_and_exact_fields_without_downgrade():
    graph, _ = state_address_program()
    document = json.loads(dumps(graph))
    with pytest.raises(ValueError, match="top-level fields"):
        loads(json.dumps({**document, "schema_version": 14}))
    with pytest.raises(ValueError, match="top-level fields"):
        loads(json.dumps({key: value for key, value in document.items() if key != ADDRESS_FIELD}))
    with pytest.raises(ValueError, match="requires explicit state-address capability"):
        loads(json.dumps({**document, ADDRESS_FIELD: []}))
    with pytest.raises(ValueError, match="top-level fields"):
        loads(json.dumps({**document, "address_proof": True}))


@pytest.mark.parametrize("mutation", ("missing-site-tag", "wrong-owner-tag", "bool-index", "authority"))
def test_nested_tags_exact_types_and_authority_cannot_be_forged(mutation):
    graph, _ = state_address_program()
    document = json.loads(dumps(graph))
    row = next(item for item in document[ADDRESS_FIELD] if item["site"]["kind"] == "EXISTING_ACCESS")
    if mutation == "missing-site-tag":
        row["site"].pop("kind")
    elif mutation == "wrong-owner-tag":
        row["effects"][0]["owner"]["kind"] = "CELL_CONTENT"
    elif mutation == "bool-index":
        row["site"]["index"] = True
    else:
        row["transformation_authorized"] = True
    with pytest.raises((ValueError, TypeError)):
        loads(json.dumps(document))


def test_new_tags_cannot_hide_inside_old_footprint_but_plain_label_text_is_allowed():
    document = _old(14)
    operation = next(item for item in document["operations"] if item["accesses"])
    operation["accesses"][0]["footprint"]["kind"] = "WHOLE_OWNER"
    with pytest.raises((ValueError, TypeError)):
        loads(json.dumps(document))
    document = _old(14)
    document["operations"][0]["label"] = "WHOLE_OWNER"
    graph = loads(json.dumps(document))
    assert not graph.state_address_refinements
    assert json.loads(dumps(graph))["schema_version"] == 14


def test_graph_table_sites_are_unique_and_nested_mutation_is_rechecked():
    graph, _ = state_address_program()
    row = graph.state_address_refinements[0]
    with pytest.raises(TypeError):
        replace(graph, state_address_refinements=[row])
    with pytest.raises(ValueError, match="sites"):
        replace(graph, state_address_refinements=(row, row))
    effect = replace(row.effects[0])
    row = replace(row, effects=(effect, *row.effects[1:]))
    graph = replace(graph, state_address_refinements=(row,))
    object.__setattr__(effect, "stage", True)
    with pytest.raises((ValueError, TypeError)):
        dumps(graph)
