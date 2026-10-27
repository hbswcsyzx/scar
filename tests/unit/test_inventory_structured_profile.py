"""Public source inventories retain the existing structured core, never execute it."""
from copy import deepcopy
import sys

import pytest

from scar.analysis import program_inventory as inventory_module
from scar.analysis.program_inventory import ProgramInventory, inventory_program
from scar.ir.program.functions import BodyLoweringProfile
from scar.ir.program.ids import RegionID
from scar.ir.program.inventory import BodyStatus, CoverageStatus
from scar.ir.record_codec import encode


@pytest.fixture(scope="module")
def modeled(tmp_path_factory):
    root = tmp_path_factory.mktemp("structured-inventory")
    entry = root / "entry.py"
    entry.write_text(
        "def leaf(left, right):\n    return left\n"
        "def walk(items, shared):\n"
        "    chosen = shared\n"
        "    for item in items:\n"
        "        chosen = leaf(shared, shared)\n"
        "        if item:\n            continue\n"
        "        else:\n            break\n"
        "    else:\n        chosen = leaf(shared, shared)\n"
        "    while chosen:\n"
        "        chosen = leaf(shared, shared)\n        break\n"
        "    else:\n        chosen = shared\n"
        "    return chosen\n"
        "def unsupported(value):\n"
        "    try:\n        return leaf(value, value)\n"
        "    except Exception:\n        return value\n",
        encoding="utf-8",
    )
    return entry, inventory_program(entry, project_root=root,
                                   body_profile=BodyLoweringProfile.STRUCTURED_BODY)


def test_structured_inventory_joins_loops_calls_interfaces_and_precise_source_atoms(modeled):
    _, result = modeled
    document = result.to_dict()
    assert document["schema_version"] == 7
    assert document["profile"] == "STRUCTURED_BODY_V1"
    assert "frames" not in document and result.frames == ()
    assert document["call_sources"] is document["call_source_scope"] is None
    assert result.summary()["structured"]["loops"] == 2
    assert result.summary()["whole_program_graph_established"] is False
    file, = result.files
    definitions = {definition.name: definition.id for definition in file.definitions}
    bodies = {body.definition: body for body in file.bodies}
    assert bodies[definitions["walk"]].status is BodyStatus.LOWERED_WITH_GAPS
    assert bodies[definitions["unsupported"]].status is BodyStatus.UNSUPPORTED
    assert {model.definition for model in result.structured} == {definitions["leaf"], definitions["walk"]}
    linked = {link.source.atom_id for body in file.bodies if body.graph is not None
              for link in (*body.metadata.operation_links, *body.metadata.value_links, *body.metadata.use_links)}
    control_entries = [entry for entry in file.coverage
                       if entry.ast_kind in {"For", "While", "Break", "Continue"}]
    assert control_entries and all(entry.status is CoverageStatus.CONNECTED for entry in control_entries)
    assert all(entry.source.atom_id in linked for entry in file.coverage
               if entry.status is CoverageStatus.CONNECTED)
    assert any(entry.ast_kind == "Try" and entry.status is CoverageStatus.UNSUPPORTED
               for entry in file.coverage)
    calls = [link for link in bodies[definitions["walk"]].metadata.operation_links
             if link.opcode is not None and link.opcode.value == "call"]
    assert len(calls) == 3
    assert ProgramInventory.from_dict(document).to_dict() == document


def test_same_source_default_frame_preserves_v5_and_its_unsupported_body(modeled):
    entry, result = modeled
    old = inventory_program(entry, project_root=entry.parent).to_dict()
    assert old["schema_version"] == 5 and old["profile"] == "BOUND_FRAME_V1"
    assert "frames" in old and "structured" not in old
    assert "call_sources" not in old and "call_source_scope" not in old
    assert old["summary"]["body_statuses"]["UNSUPPORTED"] == 2
    assert ProgramInventory.from_dict(old).to_dict() == old
    old["structured"] = result.to_dict()["structured"]
    with pytest.raises(ValueError, match="fields mismatch"):
        ProgramInventory.from_dict(old)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "root", "profile", "frames", "type", "authority"])
def test_structured_header_and_overlay_ownership_rejected_before_source_io(modeled, monkeypatch, mutation):
    document = deepcopy(modeled[1].to_dict())
    if mutation == "missing":
        document["structured"].pop()
    elif mutation == "duplicate":
        document["structured"].append(deepcopy(document["structured"][0]))
    elif mutation == "root":
        document["structured"][0]["region"] = encode(RegionID("different-root"))
    elif mutation == "profile":
        document["profile"] = "BOUND_FRAME_V1"
    elif mutation == "frames":
        document["frames"] = []
    elif mutation == "type":
        document["structured"] = {}
    else:
        document["transformation_authorized"] = True
    def source_io_forbidden(*args, **kwargs):
        raise AssertionError("invalid declarations reached source replay")
    monkeypatch.setattr(inventory_module, "_inventory_from_inputs", source_io_forbidden)
    with pytest.raises((ValueError, TypeError)):
        ProgramInventory.from_dict(document)


def test_structured_source_replay_rejects_removed_protocol_and_independent_budget(modeled, monkeypatch):
    document = deepcopy(modeled[1].to_dict())
    document["structured"][0]["protocols"] = []
    with pytest.raises(ValueError, match="differs from current"):
        ProgramInventory.from_dict(document)
    def source_io_forbidden(*args, **kwargs):
        raise AssertionError("budget violation reached source replay")
    monkeypatch.setattr(inventory_module, "_inventory_from_inputs", source_io_forbidden)
    with pytest.raises(ValueError, match="independent verifier budget"):
        ProgramInventory.from_dict(modeled[1].to_dict(), max_operations=1)


def test_legacy_runtime_evidence_can_select_structured_without_call_source_records(tmp_path, monkeypatch):
    from scar.trace.session import TraceSession

    entry = tmp_path / "runtime_entry.py"
    entry.write_text("def f(items):\n    result = None\n    for item in items:\n        result = item\n    return result\n")
    namespace = {}
    exec(compile(entry.read_text(), str(entry), "exec", dont_inherit=True), namespace)
    monkeypatch.setenv("SCAR_RESOURCE_SAMPLER", "0")
    trace = tmp_path / "runtime"
    session = TraceSession(trace)
    previous = sys.getprofile()
    def profile(frame, event, argument):
        if frame.f_code.co_filename != str(entry):
            return
        if event == "call":
            session.python_call(frame)
        elif event == "return":
            session.python_return(frame, argument)
    sys.setprofile(profile)
    try:
        assert namespace["f"]([1, 2]) == 2
    finally:
        sys.setprofile(previous)
        session.close(0)
    result = inventory_program(entry, project_root=tmp_path, runtime_trace=trace / "events.jsonl",
                               body_profile=BodyLoweringProfile.STRUCTURED_BODY)
    document = result.to_dict()
    assert document["schema_version"] == 7 and document["runtime_scope"] is not None
    assert document["call_sources"] is document["call_source_scope"] is None
    assert len(result.structured) == 1 and result.summary()["structured"]["loops"] == 1
    assert ProgramInventory.from_dict(document).to_dict() == document
