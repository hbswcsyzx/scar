"""Persist the existing, source-replayed per-file graph triple without bodies."""
import gzip
import hashlib
import json

import pytest

from scar.analysis.source_layers import load_source_layers, reconstruct_source_layers
from scar.ir.control_flow_v2 import EdgeKind, SourceControlFlowGraph
from scar.ir.semantics_v2 import BoundaryKind, Opcode, SourceSemanticsGraph


def _canonical(document):
    return json.dumps(document, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _inventory(tmp_path, source, *, helper=None):
    from scar.analysis.program_inventory import inventory_program

    entry = tmp_path / "entry.py"
    entry.write_text(source, encoding="utf-8")
    if helper is not None:
        (tmp_path / "helper.py").write_text(helper, encoding="utf-8")
    result = inventory_program(
        entry,
        project_root=tmp_path,
        source_roots=(tmp_path,),
        max_files=8,
        max_bytes=200_000,
        max_lowered_bodies=2,
        max_operations=100,
    )
    document = result.to_dict()
    path = tmp_path / "inventory.json.gz"
    raw = _canonical(document)
    path.write_bytes(gzip.compress(raw, mtime=0))
    return path, document, entry


def test_reconstruct_roundtrip_keeps_ordered_operands_and_loop_control(tmp_path):
    marker = tmp_path / "should-not-exist"
    inventory_path, original, source_path = _inventory(tmp_path, f'''
open({str(marker)!r}, "w").write("executed")

def work(items):
    token = ()
    total = 1 + 2
    for item in items:
        total = total + item
    if total:
        return token
    return ()
''')
    original_bytes = inventory_path.read_bytes()
    source_bytes = source_path.read_bytes()

    output = tmp_path / "source-layers"
    manifest = reconstruct_source_layers(inventory_path, output)

    assert manifest["complete"] is True
    assert manifest["files_total"] == len(original["files"]) == 1
    assert manifest["whole_program_graph_established"] is False
    assert manifest["fine_state_effects_established"] is False
    assert manifest["transformation_authorized"] is False
    assert manifest["input"]["raw_sha256"] == hashlib.sha256(original_bytes).hexdigest()
    assert manifest["input"]["decoded_bytes"] == len(_canonical(original))
    assert inventory_path.read_bytes() == original_bytes
    assert source_path.read_bytes() == source_bytes
    assert not marker.exists()

    view = load_source_layers(output, source_path)
    assert view.snapshot.path == str(source_path.resolve())
    assert isinstance(view.semantics, SourceSemanticsGraph)
    assert isinstance(view.control, SourceControlFlowGraph)
    assert any(operation.opcode is Opcode.ADD and operation.result is not None
               and [operand.role for operand in operation.operands] == ["left", "right"]
               for operation in view.semantics.operations.values())
    assert any(edge.kind is EdgeKind.LOOP_BACKEDGE for edge in view.control.edges.values())
    assert any(boundary.kind is BoundaryKind.CONTROL
               and "Loop-carried bindings and zero-trip behavior" in boundary.reason
               for boundary in view.semantics.boundaries)
    assert view.metadata["whole_program_graph_established"] is False
    assert view.metadata["source_replay_on_load"] is False
    with pytest.raises(ValueError, match="record byte budget"):
        load_source_layers(output, source_path, max_record_bytes=1)

    # The reader serves the archived source context. It deliberately does not
    # inspect current source bytes or claim a fresh source replay.
    source_path.write_text("def changed():\n    return 99\n", encoding="utf-8")
    assert load_source_layers(output, source_path).snapshot == view.snapshot


def test_source_drift_and_context_mismatch_keep_file_denominator_as_gaps(tmp_path):
    inventory_path, original, entry = _inventory(
        tmp_path,
        "from helper import VALUE\ndef work():\n    return VALUE + 1\n",
        helper="VALUE = 3\n",
    )
    helper = tmp_path / "helper.py"
    helper.write_text("VALUE = 4\n", encoding="utf-8")
    output = tmp_path / "partial"
    manifest = reconstruct_source_layers(inventory_path, output)

    assert manifest["files_total"] == len(original["files"])
    assert manifest["files_total"] == 2
    assert manifest["files_stored"] + manifest["files_gapped"] == manifest["files_total"]
    assert manifest["complete"] is False
    helper_row = next(row for row in manifest["files"] if row["source_path"] == str(helper.resolve()))
    assert helper_row["status"] == "GAP"
    assert helper_row["gap"]["code"] == "SOURCE_REPLAY_FAILED"
    assert load_source_layers(output, entry).snapshot.path == str(entry.resolve())


def test_malformed_context_digest_is_rejected_before_output_creation(tmp_path):
    inventory_path, document, _ = _inventory(
        tmp_path, "def work():\n    return 1\n")
    document["files"][0]["context"]["control_sha256"] = "not-a-digest"
    inventory_path.write_bytes(gzip.compress(_canonical(document), mtime=0))
    output = tmp_path / "must-not-exist"

    with pytest.raises(ValueError, match="control_sha256"):
        reconstruct_source_layers(inventory_path, output)
    assert not output.exists()


@pytest.mark.parametrize("mutation", ("digest", "namespace"))
def test_replay_digest_or_namespace_mismatch_is_retained_as_gap(tmp_path, mutation):
    inventory_path, document, source_path = _inventory(
        tmp_path, "def work():\n    return 1\n")
    context = document["files"][0]["context"]
    if mutation == "digest":
        context["semantics_sha256"] = "0" * 64
    else:
        context["namespace_root"] = str(tmp_path / "different-root")
    inventory_path.write_bytes(gzip.compress(_canonical(document), mtime=0))
    output = tmp_path / f"mismatch-{mutation}"

    manifest = reconstruct_source_layers(inventory_path, output)
    assert manifest["files_total"] == 1
    assert manifest["files_stored"] == 0
    assert manifest["files_gapped"] == 1
    assert manifest["files"][0]["source_path"] == str(source_path.resolve())
    assert manifest["files"][0]["gap"]["code"] == "SOURCE_REPLAY_FAILED"


def test_reader_rejects_tampered_archive_and_path_escape(tmp_path):
    inventory_path, _, source_path = _inventory(tmp_path, "def work():\n    return 4\n")
    output = tmp_path / "source-layers"
    reconstruct_source_layers(inventory_path, output)
    index_path = output / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    archive_path = output / index["files"][0]["archive"]
    original_archive = archive_path.read_bytes()

    archive_path.write_bytes(original_archive[:-1] + bytes([original_archive[-1] ^ 1]))
    with pytest.raises(ValueError, match="gzip|hash"):
        load_source_layers(output, source_path)
    archive_path.write_bytes(original_archive)

    index["files"][0]["archive"] = "../outside.json.gz"
    index_path.write_bytes(_canonical(index))
    with pytest.raises(ValueError, match="archive path"):
        load_source_layers(output, source_path)


def test_input_record_total_and_boolean_budgets_are_enforced(tmp_path):
    inventory_path, _, _ = _inventory(tmp_path, "def work():\n    return 1\n")

    too_small_input = tmp_path / "small-input"
    with pytest.raises(ValueError, match="raw-byte budget|decoded-byte budget"):
        reconstruct_source_layers(inventory_path, too_small_input, max_input_bytes=32)
    assert not too_small_input.exists()

    multi_root = tmp_path / "multi"
    multi_root.mkdir()
    multi_inventory, _, _ = _inventory(
        multi_root,
        "from helper import VALUE\ndef work():\n    return VALUE\n",
        helper="VALUE = 4\n",
    )
    too_many_files = tmp_path / "too-many-files"
    with pytest.raises(ValueError, match="file count"):
        reconstruct_source_layers(multi_inventory, too_many_files, max_files=1)
    assert not too_many_files.exists()

    with pytest.raises(ValueError, match="max_record_bytes"):
        reconstruct_source_layers(tmp_path / "inventory.json.gz", tmp_path / "bool-budget",
                                  max_record_bytes=True)
    assert not (tmp_path / "bool-budget").exists()

    limited = tmp_path / "record-limited"
    manifest = reconstruct_source_layers(inventory_path, limited, max_record_bytes=1)
    assert manifest["files_total"] == 1
    assert manifest["files_gapped"] == 1
    assert manifest["files"][0]["gap"]["code"] == "RECORD_BYTE_BUDGET"

    too_small_total = tmp_path / "small-total"
    with pytest.raises(ValueError, match="manifest alone exceeds total-byte budget"):
        reconstruct_source_layers(inventory_path, too_small_total, max_total_bytes=1)
    assert not too_small_total.exists()

    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(ValueError, match="fresh and absent"):
        reconstruct_source_layers(inventory_path, existing)
    assert list(existing.iterdir()) == []


def test_missing_source_context_stays_in_file_denominator(tmp_path):
    inventory_path, document, _ = _inventory(tmp_path, "def work():\n    return 1\n")
    document["files"][0]["context"] = None
    inventory_path.write_bytes(gzip.compress(_canonical(document), mtime=0))
    output = tmp_path / "missing-context"

    manifest = reconstruct_source_layers(inventory_path, output)

    assert manifest["files_total"] == 1
    assert manifest["files_stored"] == 0
    assert manifest["files_gapped"] == 1
    assert manifest["files"][0]["gap"]["code"] == "MISSING_CONTEXT"
    assert manifest["complete"] is False

