"""Independent source-inventory checks; no manually supplied program graphs."""

import ast
from collections import Counter
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from textwrap import dedent

import pytest

from scar.analysis.program_inventory import ProgramInventory, inventory_program
from scar.analysis.program_lowering import prepare_source
from scar.ir.program import LiteralOrigin, TerminatorKind
from scar.ir.program.inventory import BodyStatus, CandidateCondition, ExecutionPhase


def _write(path, source):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(source).lstrip(), encoding="utf-8")
    return path


def _entry(tmp_path, source, **kwargs):
    path = _write(tmp_path / "entry.py", source)
    result = inventory_program(path, project_root=tmp_path, **kwargs)
    file = next(file for file in result.files if file.snapshot.path == str(path))
    assert file.context is not None, file.gaps
    return result, file, path


def _definition(file, qualname):
    return next(definition for definition in file.definitions if definition.qualname == qualname)


def _call(file, path, expression):
    source = path.read_text()
    nodes = [node for node in ast.walk(ast.parse(source))
             if isinstance(node, ast.Call) and ast.get_source_segment(source, node) == expression]
    assert len(nodes) == 1
    node = nodes[0]
    return next(call for call in file.calls if (
        call.source.start_line, call.source.start_column, call.source.end_line,
        call.source.end_column) == (node.lineno, node.col_offset, node.end_lineno, node.end_col_offset))


def test_all_prepared_source_atoms_have_exactly_one_inventory_owner_and_phase(tmp_path):
    _, file, path = _entry(tmp_path, """
        @decorate(factory())
        def outer(x: annotation() = default(), *, y=keyword_default()):
            def inner(z):
                return consume(z)
            try:
                items = [transform(v) for v in source() if allowed(v)]
            except Exception as error:
                return error
            return inner(x)
        class C(base(), metaclass=meta()):
            value: field_type() = build()
            method = lambda value=method_default(): value
    """)
    context = prepare_source(path, project_root=tmp_path)
    expected = set(context.semantic.source_atoms)
    actual = [entry.source.atom_id for entry in file.coverage]
    assert len(actual) == len(set(actual))
    assert set(actual) == expected
    assert all(entry.reason for entry in file.coverage)


@pytest.mark.parametrize("nested", (False, True))
def test_function_annotation_calls_belong_to_the_enclosing_definition_execution(tmp_path, nested):
    source = ("""
        def outer():
            def inner(x: parameter_type()) -> return_type():
                return x
            return inner
    """ if nested else """
        before()
        def inner(x: parameter_type()) -> return_type():
            return x
    """)
    _, file, path = _entry(tmp_path, source)
    function = _definition(file, "outer.inner" if nested else "inner")
    owner = (_definition(file, "outer").id if nested else
             _call(file, path, "before()").execution_owner)
    for expression in ("parameter_type()", "return_type()"):
        call = _call(file, path, expression)
        assert call.phase is ExecutionPhase.ANNOTATION
        assert call.execution_owner == owner
        assert call.execution_owner != function.id
    assert any("annotation" in issue.detail for issue in file.gaps)


def test_comprehension_outer_iterator_and_inner_work_have_distinct_owners(tmp_path):
    _, file, path = _entry(tmp_path, """
        def outer():
            return [produce(y) for x in first() for y in later(x) if keep(y)]
    """)
    outer = _definition(file, "outer")
    comprehension = next(definition for definition in file.definitions
                         if definition.kind.name == "COMPREHENSION")
    first = _call(file, path, "first()")
    assert first.execution_owner == outer.id
    assert first.phase is ExecutionPhase.FUNCTION_BODY
    for expression in ("later(x)", "keep(y)", "produce(y)"):
        call = _call(file, path, expression)
        assert call.execution_owner == comprehension.id
        assert call.phase is ExecutionPhase.COMPREHENSION_BODY


def test_duplicate_qualnames_lower_the_selected_positions_and_not_the_last_body(tmp_path):
    _, file, path = _entry(tmp_path, """
        def same(x):
            return 11
        saved = same
        def same(x):
            return 22
    """)
    definitions = sorted(file.definitions, key=lambda item: item.source.start_line)
    assert [definition.qualname for definition in definitions] == ["same", "same"]
    bodies = {body.definition: body for body in file.bodies}
    for definition, number in zip(definitions, (11, 22)):
        body = bodies[definition.id]
        assert body.graph is not None, body.reason
        constants = [value.origin.value for value in body.graph.values
                     if isinstance(value.origin, LiteralOrigin)]
        assert constants == [number]
    context = prepare_source(path, project_root=tmp_path)
    with pytest.raises(ValueError, match="ambiguous"):
        context.lower("same")
    stale = replace(definitions[0].source, fingerprint="0" * 64)
    with pytest.raises(ValueError, match="snapshot"):
        context.lower("same", source=stale)


def test_same_legacy_module_name_in_two_physical_files_does_not_mix_definitions(tmp_path):
    _write(tmp_path / "shared.py", "def value(x):\n    return 11\n")
    _write(tmp_path / "shared" / "__init__.py", "def value(x):\n    return 22\n")
    result, _, _ = _entry(tmp_path, """
        import shared
        def use(x):
            return shared.value(x)
    """, source_roots=(tmp_path,))
    files = {Path(file.snapshot.path).relative_to(tmp_path).as_posix(): file for file in result.files}
    assert {"shared.py", "shared/__init__.py"} <= set(files)
    first, second = files["shared.py"], files["shared/__init__.py"]
    assert {definition.id for definition in first.definitions}.isdisjoint(
        definition.id for definition in second.definitions)
    for file, expected in ((first, 11), (second, 22)):
        body, = file.bodies
        assert body.graph is not None
        assert [value.origin.value for value in body.graph.values
                if isinstance(value.origin, LiteralOrigin)] == [expected]
    assert not result.summary()["runtime_reachability_established"]


def test_each_discovered_file_prepares_legacy_layers_once_for_all_its_bodies(tmp_path, monkeypatch):
    import scar.analysis.program_inventory as module

    original = module.prepare_source
    prepared = []

    def counted(path, **kwargs):
        prepared.append(Path(path))
        return original(path, **kwargs)

    monkeypatch.setattr(module, "prepare_source", counted)
    _write(tmp_path / "helper.py", "def one(x):\n    return x\ndef two(x):\n    return x\n")
    result, _, _ = _entry(tmp_path, """
        import helper
        def first(x):
            return x
        def second(x):
            return x
        def third(x):
            return x
    """, source_roots=(tmp_path,))
    assert Counter(prepared) == Counter({Path(file.snapshot.path): 1 for file in result.files})
    assert sum(len(file.bodies) for file in result.files) == 5


def test_failed_body_construction_consumes_the_shared_operation_budget(tmp_path, monkeypatch):
    from scar.analysis.program_lowering import _Builder

    original = _Builder.emit
    emitted = []

    def counted(self, cursor, operation, *args, **kwargs):
        result = original(self, cursor, operation, *args, **kwargs)
        emitted.append(operation.id)
        return result

    monkeypatch.setattr(_Builder, "emit", counted)
    source = "".join(f"def fail{index}(x):\n    x + x\n    while x:\n        pass\n"
                     for index in range(4))
    result, _, _ = _entry(tmp_path, source, max_operations=3, max_lowered_bodies=4)
    assert result.summary()["core_operations"] == 0
    assert len(emitted) <= 3, "discarding an unsupported graph must not refund construction work"
    assert result.summary()["construction_operations"] == len(emitted)
    assert sum(body.construction_operations for file in result.files for body in file.bodies) == len(emitted)


def test_body_and_retained_operation_budgets_are_shared_between_files(tmp_path):
    _write(tmp_path / "helper.py", "def helper(x):\n    return x\n")
    result, _, _ = _entry(tmp_path, """
        import helper
        def first(x):
            return x
        def second(x):
            return x
    """, source_roots=(tmp_path,), max_lowered_bodies=1, max_operations=4)
    bodies = [body for file in result.files for body in file.bodies]
    assert len([body for body in bodies if body.status is not BodyStatus.NOT_ATTEMPTED]) == 1
    assert sum(len(body.graph.operations) for body in bodies if body.graph is not None) <= 4


@pytest.mark.parametrize("tampering", (
    "coverage", "definition", "context", "summary", "construction_cost", "extra_file_field",
))
def test_persisted_inventory_rejects_correspondence_or_context_tampering(tmp_path, tampering):
    result, _, _ = _entry(tmp_path, "def f(x):\n    return x\n")
    document = deepcopy(result.to_dict())
    if tampering == "coverage":
        document["files"][0]["coverage"].pop()
    elif tampering == "definition":
        document["files"][0]["definitions"][0]["qualname"] = "forged"
    elif tampering == "context":
        document["files"][0]["context"]["semantic_sha256"] = "0" * 64
    elif tampering == "summary":
        document["summary"]["runtime_reachability_established"] = True
    elif tampering == "construction_cost":
        document["files"][0]["bodies"][0]["construction_operations"] = 0
    else:
        document["files"][0]["extra"] = "forged"
    with pytest.raises(ValueError):
        ProgramInventory.from_dict(document)


def test_persisted_inventory_rejects_source_drift_and_new_import_candidate(tmp_path):
    result, _, path = _entry(tmp_path, "import optional\ndef f(x):\n    return x\n",
                             source_roots=(tmp_path,))
    document = result.to_dict()
    assert ProgramInventory.from_dict(document).to_dict() == document
    candidate = _write(tmp_path / "optional.py", "def helper(x):\n    return x\n")
    with pytest.raises(ValueError, match="replay"):
        ProgramInventory.from_dict(document)
    candidate.unlink()
    path.write_text("import optional\ndef f(x):\n    return None\n", encoding="utf-8")
    with pytest.raises(ValueError, match="replay"):
        ProgramInventory.from_dict(document)


def test_report_budget_cannot_raise_the_verifiers_independent_ceiling(tmp_path):
    result, _, _ = _entry(tmp_path, "def f(x):\n    return x\n", max_operations=11)
    with pytest.raises(ValueError, match="independent verifier budget"):
        ProgramInventory.from_dict(result.to_dict(), max_operations=10)


def test_unknown_python_operations_remain_effectful_and_runtime_targets_unconfirmed(tmp_path):
    result, file, _ = _entry(tmp_path, """
        def helper(x):
            return x
        def f(x):
            return helper(x + x)
    """)
    for body in file.bodies:
        assert body.graph is not None
        invocations = [op for op in body.graph.operations
                       if op.terminator is not None and op.terminator.kind is TerminatorKind.INVOKE]
        assert invocations
        assert all(not op.effects_complete and op.callee is None for op in invocations)
        assert all(target.status.name == "INFERRED" for target in body.metadata.call_targets)
    assert not result.summary()["fine_state_effects_established"]
    assert not result.summary()["transformation_authorized"]


@pytest.mark.parametrize("form", ("from_alias", "module_alias", "reexport", "local_import"))
def test_cross_file_candidates_keep_the_typed_import_chain_and_unaccepted_conditions(tmp_path, form):
    library = _write(tmp_path / "library.py", "def work(x):\n    return x\n")
    if form == "from_alias":
        source = "from library import work as chosen\ndef f(x):\n    return chosen(x)\n"
    elif form == "module_alias":
        source = "import library as chosen\ndef f(x):\n    return chosen.work(x)\n"
    elif form == "reexport":
        _write(tmp_path / "facade.py", "from library import work as public\n")
        source = "from facade import public as chosen\ndef f(x):\n    return chosen(x)\n"
    else:
        source = "def f(x):\n    from library import work as chosen\n    return chosen(x)\n"
    result, file, path = _entry(tmp_path, source, source_roots=(tmp_path,))
    call, = file.calls
    assert call.callee_binding is not None
    assert len(call.import_bindings) == 1
    witness, = call.candidate_witnesses
    target_file = next(item for item in result.files if item.snapshot.path == str(library))
    definition = _definition(target_file, "work")
    assert call.candidates == (definition.id,)
    assert witness.definition == definition.id and witness.target_source == definition.source
    assert witness.through_imports[0].path == str(path)
    assert len(witness.through_imports) == (2 if form == "reexport" else 1)
    assert CandidateCondition.SOURCE_BINDING_REACHES_READ in witness.conditions
    assert CandidateCondition.SOURCE_BODY_MATCHES_LIVE_CALLABLE in witness.conditions
    assert CandidateCondition.LOADER_AND_PACKAGE_CONTEXT in witness.conditions
    assert CandidateCondition.NO_EXTERNAL_NAMESPACE_MUTATION in witness.conditions
    for body in file.bodies:
        if body.graph is not None:
            assert all(op.callee is None for op in body.graph.operations)


@pytest.mark.parametrize("source", (
    "from library import work as chosen\ndef f(chosen, x):\n    return chosen(x)\n",
    "from library import work as chosen\ndef f(x, replacement):\n    chosen = replacement\n    return chosen(x)\n",
    "def f(x, replacement):\n    from library import work as chosen\n    chosen = replacement\n    return chosen(x)\n",
    "def f(x, replacement):\n    from library import work\n    chosen = work\n    chosen = replacement\n    return chosen(x)\n",
))
def test_parameter_shadow_and_definite_local_rebinding_do_not_invent_import_candidates(tmp_path, source):
    _write(tmp_path / "library.py", "def work(x):\n    return x\n")
    _, file, _ = _entry(tmp_path, source, source_roots=(tmp_path,))
    call, = file.calls
    assert call.callee_binding is not None
    assert call.import_bindings == ()
    assert call.candidate_witnesses == ()
    assert call.candidates == ()


@pytest.mark.parametrize("field", ("through_imports", "conditions"))
def test_persisted_cross_file_witness_cannot_drop_binding_steps_or_conditions(tmp_path, field):
    _write(tmp_path / "library.py", "def work(x):\n    return x\n")
    result, _, path = _entry(tmp_path,
        "from library import work as chosen\ndef f(x):\n    return chosen(x)\n",
        source_roots=(tmp_path,))
    document = deepcopy(result.to_dict())
    file = next(item for item in document["files"] if item["snapshot"]["path"] == str(path))
    assert file["calls"][0]["candidate_witnesses"][0][field]
    file["calls"][0]["candidate_witnesses"][0][field] = []
    with pytest.raises(ValueError, match="replay"):
        ProgramInventory.from_dict(document)
