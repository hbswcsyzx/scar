from __future__ import annotations

from pathlib import Path

import pytest

from scar.analysis import source_discovery as discovery
from scar.ir.program.discovery import DiscoveryGapKind, SourceDiscovery


def _write(root: Path, relative: str, text: str = "VALUE = 1\n") -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _paths(result):
    return {Path(item.snapshot.path) for item in result.files}


def _gaps(result, kind):
    return [gap for gap in result.gaps if gap.kind is kind]


def _record_reads(monkeypatch):
    reads = []
    original = discovery._read_source

    def read(path, remaining_bytes):
        reads.append(path)
        return original(path, remaining_bytes)

    monkeypatch.setattr(discovery, "_read_source", read)
    return reads


@pytest.mark.parametrize("limits", [
    {}, {"max_files": 1}, {"max_bytes": 4}, {"max_directories": 1},
])
def test_empty_extra_entries_preserve_public_v1_output(tmp_path, limits):
    entry = _write(tmp_path, "main.py", "import pkg.child\n")
    _write(tmp_path, "pkg/__init__.py", "from . import child\n")
    _write(tmp_path, "pkg/child.py", "import unknown\n")

    expected = discovery.discover_sources(entry, project_root=tmp_path, **limits)
    result = discovery._discover_sources_from_entries(
        entry, additional_entries=(), project_root=tmp_path, **limits,
    )

    assert result.to_dict() == expected.to_dict()
    assert result.to_json() == expected.to_json()
    assert result.to_dict()["schema_version"] == 1
    assert SourceDiscovery.from_dict(result.to_dict()) == result


def test_public_api_does_not_expose_manual_additional_entries(tmp_path):
    entry = _write(tmp_path, "entry.py")
    with pytest.raises(TypeError, match="additional_entries"):
        discovery.discover_sources(entry, additional_entries=())


def test_entry_precedes_sorted_deduplicated_seeds_and_import_closure(tmp_path, monkeypatch):
    entry = _write(tmp_path, "z_entry.py", "import a_static\n")
    a_seed = _write(tmp_path, "a_seed.py", "import child\n")
    z_seed = _write(tmp_path, "z_seed.py")
    static = _write(tmp_path, "a_static.py")
    child = _write(tmp_path, "child.py")
    reads = _record_reads(monkeypatch)
    result = discovery._discover_sources_from_entries(
        entry, project_root=tmp_path,
        additional_entries=(str(z_seed), str(a_seed), str(a_seed), str(entry)),
        max_files=3,
    )

    assert reads == [entry, a_seed, z_seed]
    assert _paths(result) == {entry, a_seed, z_seed}
    assert {Path(gap.path) for gap in _gaps(result, DiscoveryGapKind.FILE_BUDGET)} == {
        static, child,
    }


def test_max_files_one_always_admits_entry_and_keeps_seed_gap_without_source(tmp_path):
    entry = _write(tmp_path, "z_entry.py", "import b_static\n")
    seed = _write(tmp_path, "a_seed.py")
    static = _write(tmp_path, "b_static.py")
    result = discovery._discover_sources_from_entries(
        entry, project_root=tmp_path, additional_entries=(str(seed),), max_files=1,
    )

    assert _paths(result) == {entry}
    by_path = {gap.path: gap for gap in _gaps(result, DiscoveryGapKind.FILE_BUDGET)}
    assert by_path[str(seed)].source is None
    assert by_path[str(static)].source.path == str(entry)


def test_seed_closure_includes_imports_parent_initializers_and_cycles(tmp_path, monkeypatch):
    entry = _write(tmp_path, "entry.py")
    seed = _write(tmp_path, "pkg/nested/seed.py", "from . import peer\n")
    peer = _write(tmp_path, "pkg/nested/peer.py", "from . import seed\n")
    parent = _write(tmp_path, "pkg/__init__.py", "import bootstrap\n")
    nested = _write(tmp_path, "pkg/nested/__init__.py")
    bootstrap = _write(tmp_path, "bootstrap.py")
    reads = _record_reads(monkeypatch)
    result = discovery._discover_sources_from_entries(
        entry, project_root=tmp_path, additional_entries=(str(seed),), max_files=6,
    )

    assert _paths(result) == {entry, seed, peer, parent, nested, bootstrap}
    assert len(reads) == len(set(reads)) == 6
    assert not _gaps(result, DiscoveryGapKind.FILE_BUDGET)
    assert {edge.source.path for edge in result.imports} == {
        str(seed), str(peer), str(parent),
    }
    assert all(edge.source.path != str(entry) for edge in result.imports)


def test_seed_parent_budget_gap_has_no_fabricated_import_source(tmp_path):
    entry = _write(tmp_path, "entry.py")
    seed = _write(tmp_path, "pkg/seed.py")
    parent = _write(tmp_path, "pkg/__init__.py")
    result = discovery._discover_sources_from_entries(
        entry, project_root=tmp_path, additional_entries=(str(seed),), max_files=2,
    )

    assert _paths(result) == {entry, seed}
    assert result.imports == ()
    gaps = _gaps(result, DiscoveryGapKind.FILE_BUDGET)
    assert len(gaps) == 1
    assert gaps[0].path == str(parent)
    assert gaps[0].source is None


def test_seed_is_charged_once_when_also_imported_and_repeated(tmp_path, monkeypatch):
    entry = _write(tmp_path, "entry.py", "import seed\n")
    seed = _write(tmp_path, "seed.py", "import child\n")
    child = _write(tmp_path, "child.py")
    reads = _record_reads(monkeypatch)
    budget = sum(path.stat().st_size for path in (entry, seed, child))
    result = discovery._discover_sources_from_entries(
        entry, project_root=tmp_path,
        additional_entries=(str(seed), str(seed), str(entry)),
        max_files=3, max_bytes=budget,
    )

    assert reads == [entry, seed, child]
    assert _paths(result) == {entry, seed, child}
    assert not _gaps(result, DiscoveryGapKind.BYTE_BUDGET)
    assert not _gaps(result, DiscoveryGapKind.FILE_BUDGET)


def test_byte_budget_is_shared_by_entry_seed_and_imports(tmp_path, monkeypatch):
    entry = _write(tmp_path, "entry.py", "import child\n")
    seed = _write(tmp_path, "seed.py", "NAME = 'é'\n")
    child = _write(tmp_path, "child.py")
    reads = _record_reads(monkeypatch)
    result = discovery._discover_sources_from_entries(
        entry, project_root=tmp_path, additional_entries=(str(seed),),
        max_bytes=entry.stat().st_size + seed.stat().st_size,
    )

    assert reads == [entry, seed]
    assert _paths(result) == {entry, seed}
    gaps = _gaps(result, DiscoveryGapKind.BYTE_BUDGET)
    assert len(gaps) == 1 and gaps[0].path == str(child)


@pytest.mark.parametrize("bad_source", [None, "if invalid syntax\n"])
def test_failed_seed_attempt_does_not_refund_file_budget(tmp_path, bad_source):
    entry = _write(tmp_path, "entry.py")
    broken = tmp_path / "a_broken.py"
    if bad_source is not None:
        broken.write_text(bad_source, encoding="utf-8")
    later = _write(tmp_path, "z_later.py")
    result = discovery._discover_sources_from_entries(
        entry, project_root=tmp_path,
        additional_entries=(str(later), str(broken)), max_files=2,
    )

    assert _paths(result) == {entry}
    kind = (DiscoveryGapKind.FILE_UNAVAILABLE if bad_source is None
            else DiscoveryGapKind.SYNTAX_ERROR)
    assert any(gap.path == str(broken) and gap.source is None for gap in _gaps(result, kind))
    assert any(gap.path == str(later) for gap in _gaps(result, DiscoveryGapKind.FILE_BUDGET))


def test_seed_does_not_add_source_roots_or_invent_module_context(tmp_path):
    entry = _write(tmp_path, "entry.py")
    seed = _write(tmp_path, "plugins/seed.py", "from . import peer\nimport dependency\n")
    _write(tmp_path, "plugins/peer.py")
    _write(tmp_path, "plugins/__init__.py")
    dependency = _write(tmp_path, "lib/dependency.py")
    result = discovery._discover_sources_from_entries(
        entry, project_root=tmp_path, source_roots=(tmp_path / "lib",),
        additional_entries=(str(seed),),
    )

    assert result.source_roots == (str(tmp_path / "lib"),)
    assert _paths(result) == {entry, seed, dependency}
    seed_file = next(item for item in result.files if item.snapshot.path == str(seed))
    assert seed_file.module_mappings == ()
    assert seed_file.module_names == ()
    assert _gaps(result, DiscoveryGapKind.RELATIVE_IMPORT_OVERFLOW)


def test_in_root_symlink_seed_is_not_read(tmp_path, monkeypatch):
    entry = _write(tmp_path, "entry.py")
    target = _write(tmp_path, "real.py")
    seed = tmp_path / "linked.py"
    seed.symlink_to(target)
    reads = _record_reads(monkeypatch)
    result = discovery._discover_sources_from_entries(
        entry, project_root=tmp_path, source_roots=(tmp_path,),
        additional_entries=(str(seed),),
    )

    assert reads == [entry]
    assert _paths(result) == {entry}
    assert any(gap.path == str(seed) and gap.source is None
               for gap in _gaps(result, DiscoveryGapKind.SYMLINK))


@pytest.mark.parametrize("via_symlink", [False, True])
def test_outside_seed_is_rejected_before_any_source_read(tmp_path, monkeypatch, via_symlink):
    project = tmp_path / "project"
    entry = _write(project, "entry.py")
    outside = _write(tmp_path, "outside.py")
    seed = outside
    if via_symlink:
        seed = project / "linked.py"
        seed.symlink_to(outside)
    reads = _record_reads(monkeypatch)

    with pytest.raises(ValueError, match="(within|outside) project_root"):
        discovery._discover_sources_from_entries(
            entry, project_root=project, additional_entries=(str(seed),),
        )
    assert reads == []


@pytest.mark.parametrize("bad_input", ["string", "list", "path", "relative", "suffix"])
def test_internal_additional_entries_require_absolute_python_path_tuple(tmp_path, bad_input):
    entry = _write(tmp_path, "entry.py")
    seed = _write(tmp_path, "seed.py")
    value = {
        "string": str(seed), "list": [str(seed)], "path": (seed,),
        "relative": ("seed.py",), "suffix": (str(seed.with_suffix(".pyc")),),
    }[bad_input]

    with pytest.raises(ValueError, match="(absolute path strings|.py source file)"):
        discovery._discover_sources_from_entries(
            entry, project_root=tmp_path, additional_entries=value,
        )


def test_multiple_entries_share_one_directory_scan_and_budget(tmp_path, monkeypatch):
    entry = _write(tmp_path, "entry.py")
    one = _write(tmp_path, "one/seed.py")
    two = _write(tmp_path, "two/seed.py")
    calls = []
    original = discovery._discover_source_roots

    def discover_roots(root, max_directories, gaps):
        calls.append((root, max_directories))
        return original(root, max_directories, gaps)

    monkeypatch.setattr(discovery, "_discover_source_roots", discover_roots)
    result = discovery._discover_sources_from_entries(
        entry, project_root=tmp_path, additional_entries=(str(one), str(two)),
        max_directories=1,
    )

    assert calls == [(tmp_path, 1)]
    assert _paths(result) == {entry, one, two}
    assert {Path(gap.path) for gap in _gaps(result, DiscoveryGapKind.DIRECTORY_BUDGET)} == {
        one.parent, two.parent,
    }
