"""The calls matcher gets its old source projection without full graph digests."""
from pathlib import Path

import pytest

from scar.analysis.call_edges import _Sources
from scar.analysis.program_inventory import _Inventory
from scar.analysis.program_lowering import prepare_source
from scar.ir.program.call_edges import CallEdgeBudget, CallLinkStatus, CapturedCode
from scar.ir.record_codec import decode
from scar.trace.code_snapshot import describe_code


def _rich_source() -> str:
    return '''from typing import Any

def decorate(function):
    return function

@decorate
def repeated(value: (lambda item: item)) -> int:
    match value:
        case {"payload": payload}:
            def repeated():
                return payload
            return repeated()
    return 0  # type: ignore[return-value]

def repeated():
    return 2
'''


def _old_projection(path: Path):
    context = prepare_source(path, project_root=path.parent)
    return _Inventory(context, 0, 0).index()


def _new_projection(path: Path):
    context = prepare_source(path, project_root=path.parent)
    return _Inventory(context, 0, 0).source_witness_index()


def test_witness_projection_matches_legacy_consumed_fields_for_complex_source(tmp_path):
    path = tmp_path / "complex.py"
    path.write_text(_rich_source(), encoding="utf-8")

    old = _old_projection(path)
    new = _new_projection(path)

    assert new.snapshot == old.snapshot
    assert new.definitions == old.definitions
    assert new.calls == old.calls
    assert new.coverage == old.coverage
    assert not hasattr(new, "context")
    assert not hasattr(new, "gaps")
    assert not hasattr(new, "implicit_invocations")

    annotation_lambdas = [definition for definition in new.definitions
                          if definition.kind.value == "LAMBDA"
                          and definition.source.start_line == 7]
    assert len(annotation_lambdas) == 1
    assert annotation_lambdas[0].id.value.startswith("inventory:")
    nested_match_definition = [definition for definition in new.definitions
                               if definition.name == "repeated"
                               and definition.source.start_line == 10]
    assert len(nested_match_definition) == 1
    assert nested_match_definition[0].id.value.startswith("inventory:")


def test_encoding_cookie_type_ignore_duplicate_definitions_keep_old_projection(tmp_path):
    path = tmp_path / "encoded.py"
    path.write_bytes(
        "# coding: latin-1\n"
        "label = 'café'\n"
        "def same(value):\n"
        "    return value  # type: ignore[arg-type]\n"
        "def same(value):\n"
        "    return 'café'\n".encode("latin-1")
    )

    old = _old_projection(path)
    new = _new_projection(path)

    assert new.snapshot == old.snapshot
    assert new.definitions == old.definitions
    assert new.calls == old.calls
    assert new.coverage == old.coverage
    same_definitions = [definition for definition in new.definitions if definition.name == "same"]
    assert len(same_definitions) == 2
    assert same_definitions[0].id != same_definitions[1].id


def test_witness_publication_does_not_serialize_any_full_layer(tmp_path, monkeypatch):
    path = tmp_path / "no-digests.py"
    path.write_text("def work(value):\n    return value + 1\n", encoding="utf-8")
    context = prepare_source(path, project_root=path.parent)

    def forbidden(self):
        raise AssertionError("source-witness publication serialized a full layer")

    for layer in (context.semantic, context.semantics, context.control):
        monkeypatch.setattr(type(layer), "to_dict", forbidden)

    indexed = _Inventory(context, 0, 0).source_witness_index()
    assert indexed.snapshot.path == str(path.resolve())
    assert indexed.definitions
    assert indexed.coverage


def test_witness_publication_still_rejects_missing_atom_coverage(tmp_path):
    path = tmp_path / "coverage.py"
    path.write_text("def work():\n    return 1\n", encoding="utf-8")
    inventory = _Inventory(prepare_source(path, project_root=path.parent), 0, 0)
    inventory.walk = lambda *args, **kwargs: None

    with pytest.raises(ValueError, match="coverage has missing or duplicate atoms"):
        inventory.source_witness_index()


def test_call_sources_context_uses_thin_record_with_all_consumed_fields(tmp_path):
    path = tmp_path / "entry.py"
    path.write_text("def run(value):\n    return identity(value)\n", encoding="utf-8")
    sources = _Sources(path.parent, CallEdgeBudget(), inventory=None)

    context = sources.context(str(path.resolve()))
    indexed = sources.indexes[str(path.resolve())]

    assert context.snapshot == indexed.snapshot
    assert indexed.definitions and indexed.calls and indexed.coverage
    assert {"snapshot", "definitions", "calls", "coverage"} <= set(indexed.__dataclass_fields__)


def test_changed_source_is_a_code_mismatch_not_a_stale_witness(tmp_path):
    path = tmp_path / "drift.py"
    original = "def worker(value):\n    return value\n"
    path.write_text(original, encoding="utf-8")
    namespace = {}
    exec(compile(original, str(path), "exec", dont_inherit=True), namespace)
    captured = decode(CapturedCode, describe_code(namespace["worker"].__code__))
    path.write_text("def worker(value):\n    return None\n", encoding="utf-8")

    link = _Sources(path.parent, CallEdgeBudget(), inventory=None).code(captured)

    assert link.status is CallLinkStatus.MISMATCH
    assert link.snapshot is not None
    assert link.snapshot.fingerprint != "sha256:" + __import__("hashlib").sha256(original.encode()).hexdigest()


@pytest.mark.parametrize("boundary", ["outside", "byte-budget", "symlink"])
def test_source_boundaries_remain_incomplete(boundary, tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    actual = root / "actual.py"
    actual.write_text("def worker(value):\n    return value\n", encoding="utf-8")

    if boundary == "outside":
        source_path = tmp_path / "outside.py"
        source_path.write_text("def worker(value):\n    return value\n", encoding="utf-8")
        budget = CallEdgeBudget()
    elif boundary == "byte-budget":
        source_path = actual
        budget = CallEdgeBudget(max_source_bytes=1)
    else:
        source_path = root / "alias.py"
        source_path.symlink_to(actual)
        budget = CallEdgeBudget()

    source = source_path.read_text(encoding="utf-8")
    namespace = {}
    exec(compile(source, str(source_path), "exec", dont_inherit=True), namespace)
    captured = decode(CapturedCode, describe_code(namespace["worker"].__code__))
    link = _Sources(root, budget, inventory=None).code(captured)

    assert link.status is CallLinkStatus.INCOMPLETE
    assert link.snapshot is None
    assert link.issues and link.issues[0].kind.value == "SOURCE_BOUNDARY"
