from __future__ import annotations

import ast
from pathlib import Path

import pytest

from scar.analysis.source_discovery import discover_sources
from scar.ir.program.discovery import (
    CandidateRole, DiscoveryGapKind, DiscoveryRootMode, DiscoveryStatus,
    SourceDiscovery, DiscoveryControlKind,
)
from scar.ir.semantics_v2 import ImportForm
from scar.ir.v2.common import SourceReference


def _write(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _gap(result, kind):
    return [item for item in result.gaps if item.kind is kind]


def test_import_execution_control_arms_remain_explicit_and_reset_at_function_body(tmp_path):
    entry = _write(tmp_path, "entry.py", """\
if condition:
    import yes
    def later():
        import called
else:
    import no
for item in values:
    import loop
else:
    import finished
try:
    import attempt
except Exception:
    import handled
else:
    import normal
finally:
    import cleanup
with context:
    import entered
match item:
    case 1:
        import matched
""")
    result = discover_sources(entry)
    by_name = {edge.requested:edge for edge in result.imports}
    expected = {"yes":"IF_TRUE", "no":"IF_FALSE", "loop":"LOOP_BODY", "finished":"LOOP_ELSE",
                "attempt":"TRY_BODY", "handled":"HANDLER", "normal":"TRY_ELSE", "cleanup":"FINALLY",
                "entered":"WITH_BODY", "matched":"MATCH_CASE"}
    for name, arm in expected.items():
        assert len(by_name[name].control_context) == 1
        guard = by_name[name].control_context[0]
        assert isinstance(guard.kind, DiscoveryControlKind)
        assert guard.kind.name == arm
        assert guard.source.path == str(entry)
    assert by_name["called"].deferred
    assert not by_name["called"].control_context


def test_recursive_imports_keep_parent_init_reexports_cycles_and_deferred_owner(tmp_path):
    entry = _write(tmp_path, "main.py", """\
import pkg.sub
from pkg import public

def outer():
    def inner():
        from pkg import public as exported

class Holder:
    from pkg import public as class_export
""")
    _write(tmp_path, "pkg/__init__.py", "from . import public\n")
    _write(tmp_path, "pkg/sub.py", "from . import public\n")
    _write(tmp_path, "pkg/public.py", "from . import sub\n")

    result = discover_sources(entry, project_root=tmp_path)

    files = {Path(item.snapshot.path).relative_to(tmp_path).as_posix() for item in result.files}
    assert files == {"main.py", "pkg/__init__.py", "pkg/public.py", "pkg/sub.py"}
    assert result.root_mode is DiscoveryRootMode.INFERRED
    assert str(tmp_path) in result.source_roots
    assert any(item.owner_qualname == "outer.<locals>.inner" and item.deferred
               and item.symbol == "public" for item in result.imports)
    assert any(item.owner_qualname == "Holder" and not item.deferred
               and item.bound_name == "class_export" for item in result.imports)
    assert any(item.source.path.endswith("pkg/sub.py") and item.resolved_module == "pkg"
               for item in result.imports)
    cycle_edges = [item for item in result.imports
                   if item.source.path.endswith(("pkg/sub.py", "pkg/public.py"))]
    assert len(cycle_edges) >= 2

    sub_import = next(item for item in result.imports
                      if item.source.path == str(entry) and item.requested == "pkg.sub")
    assert any(candidate.name == "pkg.sub" and candidate.path.endswith("pkg/sub.py")
               for candidate in sub_import.candidates)
    assert any(Path(parent).relative_to(tmp_path).as_posix() == "pkg/__init__.py"
               for candidate in sub_import.candidates
               for parent in candidate.parent_initializers)
    from_import = next(item for item in result.imports
                       if item.source.path == str(entry) and item.symbol == "public")
    assert {candidate.name for candidate in from_import.candidates
            if candidate.role is not CandidateRole.PARENT_NAMESPACE} == {"pkg", "pkg.public"}
    assert from_import.status is DiscoveryStatus.AMBIGUOUS


def test_explicit_roots_preserve_same_name_physical_candidates(tmp_path):
    entry = _write(tmp_path, "main.py", "import shared.mod\n")
    root_a = tmp_path / "one"
    root_b = tmp_path / "two"
    _write(tmp_path, "one/shared/mod.py", "VALUE = 1\n")
    _write(tmp_path, "two/shared/mod.py", "VALUE = 2\n")

    result = discover_sources(entry, project_root=tmp_path,
                             source_roots=(root_b, root_a))
    dependency = result.imports[0]
    assert result.root_mode is DiscoveryRootMode.DECLARED
    assert result.source_roots == tuple(sorted((str(root_a), str(root_b))))
    matches = [item for item in dependency.candidates
               if item.name == "shared.mod" and item.role is CandidateRole.REQUESTED_MODULE]
    assert {item.path for item in matches} == {
        str(root_a / "shared/mod.py"), str(root_b / "shared/mod.py")}
    assert dependency.status is DiscoveryStatus.AMBIGUOUS
    assert any(item.kind is DiscoveryGapKind.AMBIGUOUS for item in result.gaps)


def test_relative_overflow_star_dynamic_and_external_boundaries_are_explicit(tmp_path):
    entry = _write(tmp_path, "entry.py", """\
from . import local
from os import path as os_path
from unknown_pkg import *
import importlib as il

def later():
    il.import_module('plugins.' + 'x')
    __import__('other')
""")
    _write(tmp_path, "local.py", "VALUE = 1\n")

    result = discover_sources(entry, project_root=tmp_path)
    assert any(item.status is DiscoveryStatus.RELATIVE_IMPORT_OVERFLOW
               for item in result.imports)
    assert any(item.status is DiscoveryStatus.STAR_IMPORT for item in result.imports)
    assert any(item.status is DiscoveryStatus.EXTERNAL_OR_UNAVAILABLE
               for item in result.imports if item.symbol == "path")
    assert len(_gap(result, DiscoveryGapKind.DYNAMIC_IMPORT)) == 2
    assert any(item.kind is DiscoveryGapKind.STAR_IMPORT for item in result.gaps)
    assert any(item.kind is DiscoveryGapKind.EXTERNAL_OR_UNAVAILABLE for item in result.gaps)


def test_namespace_package_candidate_and_inferred_src_root(tmp_path):
    entry = _write(tmp_path, "main.py", "import ns.sub\n")
    _write(tmp_path, "src/ns/sub.py", "VALUE = 1\n")
    # No __init__.py: the namespace directory is a real candidate context.

    result = discover_sources(entry, project_root=tmp_path)
    assert str(tmp_path / "src") in result.source_roots
    dependency = next(item for item in result.imports if item.requested == "ns.sub")
    assert any(item.name == "ns.sub" and item.source_root == str(tmp_path / "src")
               and item.path == str(tmp_path / "src/ns/sub.py") for item in dependency.candidates)
    assert any(item.name == "ns" and item.namespace
               and item.role is CandidateRole.PARENT_NAMESPACE
               for item in dependency.candidates)
    assert any(Path(item.snapshot.path) == tmp_path / "src/ns/sub.py" for item in result.files)


def test_budgets_keep_unread_frontier_and_invalid_sources_as_gaps(tmp_path):
    entry = _write(tmp_path, "main.py", "import dep\n")
    dep = _write(tmp_path, "dep.py", "VALUE = 7\n")
    limited_files = discover_sources(entry, project_root=tmp_path, max_files=1)
    assert len(limited_files.files) == 1
    assert any(item.kind is DiscoveryGapKind.FILE_BUDGET and item.path == str(dep)
               for item in limited_files.gaps)

    limited_bytes = discover_sources(entry, project_root=tmp_path, max_bytes=1)
    assert not limited_bytes.files
    assert any(item.kind is DiscoveryGapKind.BYTE_BUDGET and item.path == str(entry)
               for item in limited_bytes.gaps)

    _write(tmp_path, "broken.py", "if True print('bad')\n")
    _write(tmp_path, "nested/deep.py", "VALUE = 1\n")
    bad_entry = _write(tmp_path, "bad_entry.py", "import broken\n")
    invalid = discover_sources(bad_entry, project_root=tmp_path)
    assert any(item.kind is DiscoveryGapKind.SYNTAX_ERROR
               and item.path == str(tmp_path / "broken.py") for item in invalid.gaps)

    directory_limited = discover_sources(entry, project_root=tmp_path, max_directories=1)
    assert any(item.kind is DiscoveryGapKind.DIRECTORY_BUDGET
               for item in directory_limited.gaps)


def test_discovery_never_executes_source_and_round_trips_strict_records(tmp_path):
    marker = tmp_path / "executed"
    entry = _write(tmp_path, "main.py", "import dependency\n")
    _write(tmp_path, "dependency.py", f"open({str(marker)!r}, 'w').write('ran')\n")
    _write(tmp_path, "setup.py", f"open({str(marker)!r}, 'w').write('setup ran')\n")

    result = discover_sources(entry, project_root=tmp_path)
    assert not marker.exists()
    assert SourceDiscovery.from_json(result.to_json()) == result
    with pytest.raises(ValueError, match="incorrect fields"):
        bad = result.to_dict()
        bad["unrecognized"] = True
        SourceDiscovery.from_dict(bad)


def test_source_reference_matches_frontend_atom_identity(tmp_path):
    entry = _write(tmp_path, "main.py", "import dep as alias\n")
    _write(tmp_path, "dep.py", "VALUE = 1\n")
    result = discover_sources(entry, project_root=tmp_path)
    dependency = result.imports[0]
    text = entry.read_text(encoding="utf-8")
    statement = ast.parse(text).body[0]
    alias = statement.names[0]
    assert dependency.source.path == str(entry)
    assert dependency.source.start_line == statement.lineno
    assert dependency.source.start_column == statement.col_offset
    assert dependency.alias_source.start_line == alias.lineno
    assert dependency.alias_source.start_column == alias.col_offset
    assert dependency.source.atom_id.value.startswith("atom:")
    assert isinstance(dependency.source, SourceReference)
    assert dependency.form is ImportForm.MODULE
    assert dependency.bound_name == "alias"


def test_symlink_candidates_are_reported_without_reading_targets(tmp_path):
    entry = _write(tmp_path, "main.py", "import linked\nimport linked_pkg.child\n")
    outside = tmp_path.parent / (tmp_path.name + "-outside")
    outside.mkdir(exist_ok=True)
    target = _write(outside, "module.py", "open('should-not-run', 'w').write('x')\n")
    link_file = tmp_path / "linked.py"
    link_dir = tmp_path / "linked_pkg"
    try:
        link_file.symlink_to(target)
        link_dir.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symbolic links unavailable: {exc}")

    result = discover_sources(entry, project_root=tmp_path)
    assert {Path(item.snapshot.path) for item in result.files} == {entry}
    symlink_gaps = [item for item in result.gaps if item.kind is DiscoveryGapKind.SYMLINK]
    assert any(item.path == str(link_file) for item in symlink_gaps)
    assert any(item.path and str(link_dir) in item.path for item in symlink_gaps)
    assert target.read_text(encoding="utf-8").startswith("open(")


def test_explicit_source_root_must_be_a_collection_and_outside_roots_are_not_read(tmp_path):
    project = tmp_path / "project"
    entry = _write(project, "main.py", "import local\n")
    outside = _write(tmp_path, "outside/local.py", "VALUE = 1\n")
    with pytest.raises(ValueError, match="iterable of paths"):
        discover_sources(entry, project_root=project, source_roots=project / "outside")

    result = discover_sources(entry, project_root=project, source_roots=(outside.parent,))
    assert result.source_roots == ()
    assert all(Path(item.snapshot.path) != outside for item in result.files)
    assert any(item.kind is DiscoveryGapKind.SOURCE_ROOT_INVALID for item in result.gaps)
