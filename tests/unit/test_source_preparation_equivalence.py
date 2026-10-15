"""Generated source layers stay equivalent without trusting caller-owned IR."""

from dataclasses import replace
from hashlib import sha256
from textwrap import dedent

import pytest

from scar.analysis import control_flow_v2 as control_module
from scar.analysis import source_semantics_v2 as semantics_module
from scar.analysis.program_lowering import (
    SourceProgram, lower_source, prepare_source, validate_source_program,
)
from scar.ir.control_flow_v2 import ControlFlowBudget
from scar.ir.frontend_v2 import build_semantic_files
from scar.ir.semantics_v2 import Opcode


def _write(path, source):
    source = dedent(source).lstrip()
    path.write_text(source, encoding="utf-8")
    return source


def _generated(paths, root, sources, *, budget=ControlFlowBudget()):
    return control_module._build_generated_source_layers(
        paths, root, sources=sources, budget=budget)


def _public(paths, root, sources, *, budget=ControlFlowBudget()):
    semantic = build_semantic_files(paths, root, sources=sources).graph
    semantics = semantics_module.extract_source_semantics(semantic, sources=sources)
    control = control_module.build_source_control_flow(
        semantic, semantics, sources=sources, budget=budget)
    return semantic, semantics, control


@pytest.mark.parametrize("source", (
    """
        数 = 9
        def f(value):
            if value:
                return value + 数
            return None
    """,
    """
        @decorate(factory())
        def f(x: annotation() = default()):
            return consume(x)
        class C(base(), metaclass=meta()):
            field = build()
            method = lambda value=initialize(): value
        values = [transform(x) for x in items() if keep(x)]
    """,
    """
        def f(items, manager):
            for item in items:
                if item:
                    continue
                break
            else:
                finish()
            try:
                with manager:
                    work()
            except Exception:
                recover()
            finally:
                cleanup()
    """,
))
def test_generated_layers_have_identical_serialized_sources_semantics_and_control(tmp_path, source):
    path = tmp_path / "program.py"
    sources = {str(path): _write(path, source)}
    generated = _generated((path,), tmp_path, sources)
    public = _public((path,), tmp_path, sources)
    assert [layer.to_dict() for layer in generated] == [layer.to_dict() for layer in public]
    semantic, semantics, control = generated
    assert control_module.validate_source_control_flow(
        control, semantic, semantics, sources=sources)["valid"]


def test_multiple_file_layers_match_the_public_path_without_namespace_mixup(tmp_path):
    entry = tmp_path / "entry.py"
    helper = tmp_path / "helper.py"
    sources = {
        str(entry): _write(entry, "import helper\ndef run(x):\n    return helper.work(x)\n"),
        str(helper): _write(helper, "def work(x):\n    return x - 1\n"),
    }
    generated = _generated((entry, helper), tmp_path, sources)
    public = _public((entry, helper), tmp_path, sources)
    assert [layer.to_dict() for layer in generated] == [layer.to_dict() for layer in public]
    assert set(generated[1].sources) == set(generated[2].sources) == set(sources)


def test_decoded_utf8_bytes_are_checked_even_when_original_file_bytes_fit(tmp_path):
    path = tmp_path / "latin.py"
    text = "# coding: latin-1\nvalue = 'éééééééééé'\n"
    path.write_bytes(text.encode("latin-1"))
    budget = ControlFlowBudget(max_source_bytes=path.stat().st_size)
    assert len(text.encode("latin-1")) <= budget.max_source_bytes < len(text.encode("utf-8"))
    with pytest.raises(ValueError, match="source-byte budget"):
        _generated((path,), tmp_path, {str(path): text}, budget=budget)
    with pytest.raises(ValueError, match="source-byte budget"):
        _public((path,), tmp_path, {str(path): text}, budget=budget)


def test_source_byte_budget_applies_to_the_sum_of_supplied_files(tmp_path):
    first, second = tmp_path / "first.py", tmp_path / "second.py"
    sources = {str(first): _write(first, "x = 1\n"), str(second): _write(second, "y = 2\n")}
    budget = ControlFlowBudget(max_source_bytes=8)
    assert all(len(text.encode("utf-8")) <= budget.max_source_bytes for text in sources.values())
    with pytest.raises(ValueError, match="source-byte budget"):
        _generated((first, second), tmp_path, sources, budget=budget)


@pytest.mark.parametrize("budget", (
    ControlFlowBudget(max_source_bytes=8),
    ControlFlowBudget(max_ast_nodes=2),
    ControlFlowBudget(max_nodes=2),
    ControlFlowBudget(max_edges=2),
    ControlFlowBudget(max_build_work=2),
    ControlFlowBudget(max_nesting=1),
))
def test_generated_path_retains_each_construction_budget(tmp_path, budget):
    path = tmp_path / "program.py"
    source = _write(path, """
        def f(x):
            if x:
                while x:
                    x = x - 1
            return x
    """)
    with pytest.raises(ValueError, match="budget|nesting"):
        _generated((path,), tmp_path, {str(path): source}, budget=budget)


def test_generated_path_rechecks_the_budget_record(tmp_path):
    path = tmp_path / "program.py"
    sources = {str(path): _write(path, "x = 1\n")}
    with pytest.raises(TypeError, match="budget"):
        _generated((path,), tmp_path, sources, budget=object())
    malformed = ControlFlowBudget()
    object.__setattr__(malformed, "max_nodes", True)
    with pytest.raises(ValueError, match="max_nodes"):
        _generated((path,), tmp_path, sources, budget=malformed)


@pytest.mark.parametrize("defect", ("missing", "extra"))
def test_generated_source_mapping_must_exactly_match_selected_files(tmp_path, defect):
    path = tmp_path / "program.py"
    source = _write(path, "x = 1\n")
    sources = {} if defect == "missing" else {
        str(path): source, str(tmp_path / "unselected.py"): "y = 2\n",
    }
    with pytest.raises(ValueError, match="sources|snapshot"):
        _generated((path,), tmp_path, sources)


def test_layers_share_the_supplied_snapshot_and_public_replay_detects_disk_drift(tmp_path):
    path = tmp_path / "program.py"
    original = _write(path, "def f(x):\n    return x - 1\n")
    path.write_text("def f(x):\n    return x + 1\n", encoding="utf-8")
    semantic, semantics, control = _generated((path,), tmp_path, {str(path): original})
    expected = "sha256:" + sha256(original.encode("utf-8")).hexdigest()
    assert semantics.sources[str(path)].fingerprint == control.sources[str(path)].fingerprint == expected
    assert {op.opcode for op in semantics.operations.values()} >= {Opcode.SUB}
    checked = control_module.validate_source_control_flow(control, semantic, semantics)
    assert not checked["valid"]
    assert any("fingerprint" in error for error in checked["errors"])


def test_public_builder_and_validator_reject_opcode_tampering_even_with_matching_digest(tmp_path):
    path = tmp_path / "program.py"
    sources = {str(path): _write(path, "x = 9 - 2\n")}
    semantic, semantics, control = _generated((path,), tmp_path, sources)
    subtraction, = [op for op in semantics.operations.values() if op.opcode is Opcode.SUB]
    semantics.operations[subtraction.operation] = replace(subtraction, opcode=Opcode.ADD)
    assert semantics.assert_valid(semantic)["valid"]  # The forgery is shape-valid.
    control.source_semantics_digest = control_module._digest(semantics.to_dict())
    assert control.assert_valid(semantic, semantics)["valid"]
    with pytest.raises(ValueError, match="replay"):
        control_module.build_source_control_flow(semantic, semantics, sources=sources)
    checked = control_module.validate_source_control_flow(control, semantic, semantics, sources=sources)
    assert not checked["valid"]
    assert any("replay" in error for error in checked["errors"])


def test_prepare_and_multiple_bodies_extract_semantics_only_once(tmp_path, monkeypatch):
    path = tmp_path / "program.py"
    _write(path, "def first(x):\n    return x\ndef second(x):\n    return x + x\n")
    extractions = []
    original = semantics_module._Extractor.run

    def counted(self):
        extractions.append(self)
        return original(self)

    monkeypatch.setattr(semantics_module._Extractor, "run", counted)
    prepared = prepare_source(path)
    assert prepared.lower("first").graph is not None
    assert prepared.lower("second").graph is not None
    assert len(extractions) == 1


def test_prepare_keeps_encoding_cookie_handling(tmp_path):
    path = tmp_path / "latin.py"
    text = "# coding: latin-1\ndef f():\n    return 'é'\n"
    path.write_bytes(text.encode("latin-1"))
    prepared = prepare_source(path)
    assert prepared.text == text
    assert prepared.lower("f").graph is not None
    expected = "sha256:" + sha256(text.encode("utf-8")).hexdigest()
    assert prepared.semantics.sources[str(path)].fingerprint == expected


def test_prepared_report_replay_still_rejects_later_source_changes(tmp_path):
    path = tmp_path / "program.py"
    _write(path, "def f(x):\n    return x - 1\n")
    result = lower_source(path, "f")
    document = result.to_dict()
    assert validate_source_program(result)["valid"]
    path.write_text("def f(x):\n    return x + 1\n", encoding="utf-8")
    assert not validate_source_program(result)["valid"]
    with pytest.raises(ValueError):
        SourceProgram.from_dict(document)


def test_generated_builder_preserves_recursion_error_boundary(tmp_path, monkeypatch):
    path = tmp_path / "program.py"
    sources = {str(path): _write(path, "x = 1\n")}

    def too_deep(self):
        raise RecursionError("simulated construction recursion")

    monkeypatch.setattr(control_module._Builder, "build", too_deep)
    with pytest.raises(ValueError, match="nesting.*limit"):
        _generated((path,), tmp_path, sources)
