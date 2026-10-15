"""v6 witnessed roots follow the entry closure; historical discovery is fixed."""
from dataclasses import replace
import ast
import hashlib
from pathlib import Path
import sys
import tokenize
from types import CodeType, FunctionType

import pytest

from scar.analysis import source_discovery as discovery
from scar.analysis.call_seeds import CallSourceSeedReport, read_call_source_seeds
from scar.ir.frontend_v2 import source_reference
from scar.ir.program.call_edges import CallLinkStatus, CodeSourceLink
from scar.ir.program.discovery import DiscoveryGapKind
from scar.ir.semantics_v2 import SourceSnapshot
from scar.ir.v2.ids import OperationDefinitionID
from scar.trace.call_edges import CallEdgeRecorder
from scar.trace.code_snapshot import describe_code


def _write(root, name, text):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _observed_report(root, *paths):
    """Capture real entries without executing their module/import statements."""
    functions = []
    for path in paths:
        with tokenize.open(path) as stream:
            text = stream.read()
        module_code = compile(text, str(path), "exec", dont_inherit=True)
        code = next(code for code in module_code.co_consts
                    if isinstance(code, CodeType) and code.co_name == "seed")
        functions.append(FunctionType(code, {}))
    output = root / "call-trace"
    recorder = CallEdgeRecorder(output, root)
    previous = sys.getprofile()
    sys.setprofile(recorder.profile)
    try:
        for function in functions:
            assert function(object()) is not None
    finally:
        sys.setprofile(previous)
        recorder.close()
    document = read_call_source_seeds(output, root).to_dict()
    return CallSourceSeedReport.from_dict(document)


def _observed_sources(root, *paths):
    report = _observed_report(root, *paths)
    links = report.eligible_code_links()
    assert {link.snapshot.path for link in links} == {str(path) for path in paths}
    return links


def _protocol_witness(root, path):
    """Typed discovery input fixture, not a successful D0 source match.

    The current full frontend rejects non-.py selected sources. This fixture
    tests only discovery's complete typed-witness/hash admission protocol;
    its definition ID deliberately makes no automatic inventory claim.
    """
    with tokenize.open(path) as stream:
        text = stream.read()
    tree = ast.parse(text, filename=str(path))
    fingerprint = "sha256:" + hashlib.sha256(text.encode()).hexdigest()
    compiled = compile(text, str(path), "exec", dont_inherit=True)
    code = next(code for code in compiled.co_consts if isinstance(code, CodeType))
    return CodeSourceLink(
        describe_code(code)["key"], CallLinkStatus.VERIFIED,
        SourceSnapshot(str(path), fingerprint), OperationDefinitionID("protocol-fixture"),
        source_reference(path, root, fingerprint, 0, tree.body[0]), (0,),
    )


def _reads(monkeypatch):
    reads = []
    original = discovery._read_source

    def read(path, remaining):
        reads.append(path)
        return original(path, remaining)

    monkeypatch.setattr(discovery, "_read_source", read)
    return reads


def _paths(result):
    return {Path(file.snapshot.path) for file in result.files}


def test_entry_dependency_uses_small_budget_before_alphabetically_earlier_observation(tmp_path, monkeypatch):
    entry = _write(tmp_path, "entry.py", "import z_helper\n")
    helper = _write(tmp_path, "z_helper.py", "VALUE = 1\n")
    unrelated = _write(tmp_path, "a_unrelated.py", "def seed(value):\n    return value\n")
    witnesses = _observed_sources(tmp_path, unrelated)
    reads = _reads(monkeypatch)
    result = discovery._discover_sources_from_call_sources(
        entry, project_root=tmp_path, source_witnesses=witnesses, max_files=2)
    assert reads == [entry, helper]
    assert _paths(result) == {entry, helper}
    gap, = (gap for gap in result.gaps if gap.path == str(unrelated))
    assert gap.kind is DiscoveryGapKind.FILE_BUDGET and gap.source is None
    dependency, = result.imports
    assert dependency.source.path == str(entry)


def test_entry_transitive_cycle_frontier_is_exhausted_before_any_observed_root(tmp_path, monkeypatch):
    entry = _write(tmp_path, "entry.py", "import z_helper\n")
    helper = _write(tmp_path, "z_helper.py", "import z_child\n")
    child = _write(tmp_path, "z_child.py", "import z_helper\n")
    unrelated = _write(tmp_path, "a_unrelated.py", "def seed(value):\n    return value\n")
    witnesses = _observed_sources(tmp_path, unrelated)
    reads = _reads(monkeypatch)
    result = discovery._discover_sources_from_call_sources(
        entry, project_root=tmp_path, source_witnesses=witnesses)
    assert reads == [entry, helper, child, unrelated]
    assert len(_paths(result)) == 4


def test_observed_root_dependency_and_parent_initializers_use_shared_frontier(tmp_path, monkeypatch):
    entry = _write(tmp_path, "entry.py", "VALUE = 1\n")
    seed = _write(tmp_path, "pkg/seed.py", "import peer\ndef seed(value):\n    return value\n")
    parent = _write(tmp_path, "pkg/__init__.py", "import bootstrap\n")
    peer = _write(tmp_path, "peer.py", "VALUE = 1\n")
    bootstrap = _write(tmp_path, "bootstrap.py", "VALUE = 1\n")
    witnesses = _observed_sources(tmp_path, seed)
    reads = _reads(monkeypatch)
    result = discovery._discover_sources_from_call_sources(
        entry, project_root=tmp_path, source_witnesses=witnesses)
    assert reads == [entry, seed, peer, parent, bootstrap]
    assert _paths(result) == {entry, seed, parent, peer, bootstrap}
    assert all(edge.source.path != str(entry) for edge in result.imports)


def test_repeated_witnesses_and_imported_witness_charge_source_once(tmp_path, monkeypatch):
    entry = _write(tmp_path, "entry.py", "import seed\n")
    seed = _write(tmp_path, "seed.py", "def seed(value):\n    return value\n")
    witnesses = _observed_sources(tmp_path, seed)
    reads = _reads(monkeypatch)
    result = discovery._discover_sources_from_call_sources(
        entry, project_root=tmp_path, source_witnesses=witnesses * 3,
        max_files=2, max_bytes=entry.stat().st_size + seed.stat().st_size)
    assert reads == [entry, seed]
    assert _paths(result) == {entry, seed} and result.gaps == ()


@pytest.mark.parametrize("name", ["source.json", "source", "source.data"])
def test_nonpy_typed_protocol_admits_hash_checked_source_without_suffix_gate(tmp_path, name):
    entry = _write(tmp_path, "entry.py", "VALUE = 1\n")
    seed = _write(tmp_path, name, "def seed(value):\n    return value\n")
    witness = _protocol_witness(tmp_path, seed)
    result = discovery._discover_sources_from_call_sources(
        entry, project_root=tmp_path, source_witnesses=(witness,))
    source, = (file for file in result.files if file.snapshot.path == str(seed))
    assert source.snapshot.fingerprint == witness.snapshot.fingerprint
    assert _paths(result) == {entry, seed}
    with pytest.raises(ValueError, match="additional entry must be a .py"):
        discovery._discover_sources_from_entries(entry, project_root=tmp_path,
                                                additional_entries=(str(seed),))


def test_real_nonpy_d0_capture_keeps_frontend_boundary_and_cannot_add_a_source_root(tmp_path):
    entry = _write(tmp_path, "entry.py", "VALUE = 1\n")
    seed = _write(tmp_path, "seed.json", "def seed(value):\n    return value\n")
    report = _observed_report(tmp_path, seed)
    assert len(report.model.groups) == 1 and report.eligible_groups() == ()
    link, = report.model.code_links
    assert link.status is CallLinkStatus.INCOMPLETE
    assert any(issue.kind.value == "SOURCE_BOUNDARY"
               and "selected source must be an existing Python file" in issue.detail
               for issue in link.issues)
    result = discovery._discover_sources_from_call_sources(
        entry, project_root=tmp_path, source_witnesses=report.eligible_code_links())
    assert _paths(result) == {entry}


def test_nonpy_typed_protocol_rejects_current_source_hash_drift(tmp_path):
    entry = _write(tmp_path, "entry.py", "VALUE = 1\n")
    seed = _write(tmp_path, "seed.json", "def seed(value):\n    return value\n")
    witness = _protocol_witness(tmp_path, seed)
    seed.write_text("def seed(value):\n    return None\n", encoding="utf-8")
    with pytest.raises(ValueError, match="fingerprint differs from current discovery read"):
        discovery._discover_sources_from_call_sources(
            entry, project_root=tmp_path, source_witnesses=(witness,))


@pytest.mark.parametrize("imported", [False, True])
def test_witness_source_drift_is_rejected_also_when_reached_by_entry_import(tmp_path, imported):
    entry = _write(tmp_path, "entry.py", "import seed\n" if imported else "VALUE = 1\n")
    seed = _write(tmp_path, "seed.py", "def seed(value):\n    return value\n")
    witnesses = _observed_sources(tmp_path, seed)
    seed.write_text("def seed(value):\n    return None\n", encoding="utf-8")
    with pytest.raises(ValueError, match="fingerprint differs from current discovery read"):
        discovery._discover_sources_from_call_sources(
            entry, project_root=tmp_path, source_witnesses=witnesses)


def test_hash_check_uses_exact_discovery_read_instead_of_a_preflight_read(tmp_path, monkeypatch):
    entry = _write(tmp_path, "entry.py", "VALUE = 1\n")
    seed = _write(tmp_path, "seed.py", "def seed(value):\n    return value\n")
    witnesses = _observed_sources(tmp_path, seed)
    original = discovery._read_source
    reads = []

    def change_at_read(path, remaining):
        reads.append(path)
        if path == seed:
            path.write_text("def seed(value):\n    return None\n", encoding="utf-8")
        return original(path, remaining)

    monkeypatch.setattr(discovery, "_read_source", change_at_read)
    with pytest.raises(ValueError, match="fingerprint differs"):
        discovery._discover_sources_from_call_sources(
            entry, project_root=tmp_path, source_witnesses=witnesses)
    assert reads == [entry, seed]


@pytest.mark.parametrize("budget", ["files", "bytes"])
def test_unadmitted_observation_does_not_spend_extra_source_reads_for_hash(tmp_path, monkeypatch, budget):
    entry = _write(tmp_path, "entry.py", "import z_helper\n")
    helper = _write(tmp_path, "z_helper.py", "VALUE = 1\n")
    seed = _write(tmp_path, "a_seed.py", "def seed(value):\n    return value\n")
    witnesses = _observed_sources(tmp_path, seed)
    seed.write_text("changed after replay\n", encoding="utf-8")
    reads = _reads(monkeypatch)
    limits = ({"max_files": 2} if budget == "files" else
              {"max_bytes": entry.stat().st_size + helper.stat().st_size})
    result = discovery._discover_sources_from_call_sources(
        entry, project_root=tmp_path, source_witnesses=witnesses, **limits)
    assert reads == [entry, helper] and _paths(result) == {entry, helper}
    kind = DiscoveryGapKind.FILE_BUDGET if budget == "files" else DiscoveryGapKind.BYTE_BUDGET
    assert any(gap.path == str(seed) and gap.kind is kind for gap in result.gaps)


def test_conflicting_witness_hashes_are_rejected_before_any_source_read(tmp_path, monkeypatch):
    entry = _write(tmp_path, "entry.py", "VALUE = 1\n")
    seed = _write(tmp_path, "seed.py", "def seed(value):\n    return value\n")
    witness, = _observed_sources(tmp_path, seed)
    fingerprint = "sha256:" + "0" * 64
    conflict = replace(witness, snapshot=replace(witness.snapshot, fingerprint=fingerprint),
                       source=replace(witness.source, fingerprint=fingerprint))
    reads = _reads(monkeypatch)
    with pytest.raises(ValueError, match="conflicting fingerprints"):
        discovery._discover_sources_from_call_sources(
            entry, project_root=tmp_path, source_witnesses=(witness, conflict))
    assert reads == []


def test_encoded_snapshot_compares_decoded_utf8_hash_not_all_snapshot_metadata(tmp_path):
    entry = _write(tmp_path, "entry.py", "VALUE = 1\n")
    seed = tmp_path / "seed.py"
    seed.write_bytes("# coding: latin-1\nLABEL = 'é'\ndef seed(value):\n    return value\n".encode("latin-1"))
    witness, = _observed_sources(tmp_path, seed)
    result = discovery._discover_sources_from_call_sources(
        entry, project_root=tmp_path, source_witnesses=(witness,))
    snapshot, = (file.snapshot for file in result.files if file.snapshot.path == str(seed))
    assert snapshot.fingerprint == witness.snapshot.fingerprint
    assert snapshot.encoding == "iso-8859-1" and witness.snapshot.encoding == "utf-8"
    assert snapshot.python_version is None and witness.snapshot.python_version is not None


@pytest.mark.parametrize("bad", ["list", "path", "unverified", "no_definition", "no_optimize", "source_hash"])
def test_only_complete_typed_source_witnesses_are_accepted(tmp_path, bad):
    entry = _write(tmp_path, "entry.py", "VALUE = 1\n")
    seed = _write(tmp_path, "seed.py", "def seed(value):\n    return value\n")
    witness, = _observed_sources(tmp_path, seed)
    if bad == "list":
        value = [witness]
    elif bad == "path":
        value = (str(seed),)
    elif bad == "unverified":
        value = (replace(witness, status=CallLinkStatus.INCOMPLETE, definition=None, source=None),)
    elif bad == "no_definition":
        value = (replace(witness, definition=None, source=None),)
    elif bad == "no_optimize":
        value = (replace(witness, optimize_levels=()),)
    else:
        value = (replace(witness, source=replace(witness.source, fingerprint="sha256:" + "0" * 64)),)
    with pytest.raises(ValueError, match="(source_witnesses|call source witness)"):
        discovery._discover_sources_from_call_sources(
            entry, project_root=tmp_path, source_witnesses=value)


def test_public_api_has_no_manual_witness_or_trust_override_and_root_still_requires_py(tmp_path):
    entry = _write(tmp_path, "entry.json", "VALUE = 1\n")
    with pytest.raises(TypeError, match="source_witnesses"):
        discovery.discover_sources(entry, source_witnesses=())
    with pytest.raises(TypeError, match="trusted"):
        discovery._discover_sources_from_call_sources(entry, source_witnesses=(), trusted=True)
    with pytest.raises(ValueError, match="entry must be a .py"):
        discovery._discover_sources_from_call_sources(entry, source_witnesses=())


def test_zero_witness_v6_preserves_original_entry_closure(tmp_path):
    entry = _write(tmp_path, "entry.py", "import child\nimport unknown\n")
    _write(tmp_path, "child.py", "VALUE = 1\n")
    expected = discovery.discover_sources(entry, project_root=tmp_path)
    actual = discovery._discover_sources_from_call_sources(
        entry, project_root=tmp_path, source_witnesses=())
    assert actual.to_json() == expected.to_json()


# These complete, root-normalized SourceDiscovery JSON hashes were produced
# with source_discovery.py from actual base commit 936fa9c before this change.
@pytest.mark.parametrize("seeded,limits,expected", [
    (False, {}, "7f1c9aadf384016383aa87fa74833e9aaba7c3123b9168ad20c9be33a0ea2694"),
    (False, {"max_files": 2}, "68a49f70c6b856964837880f4d7a364cc687299e00f37b0bbf9174878a4cff76"),
    (False, {"max_bytes": 35}, "0d4046da8efff1ab7e2832a9e22c2c88d64ab5071f82e836fd7d49347f044ff3"),
    (False, {"max_directories": 1}, "7f1c9aadf384016383aa87fa74833e9aaba7c3123b9168ad20c9be33a0ea2694"),
    (True, {}, "3c247f2d244698ffb940e3542b7723236d3c5dfb9ccf0694621fa1e878f11c3f"),
    (True, {"max_files": 2}, "0247849550ba2111ea985b9c09909b6a3834152caeb03c8838fafb009c4c7a2e"),
    (True, {"max_bytes": 35}, "22e7b8804180319305c77711c7f6f00eef769cfb35cb7ebfd8a50ef634a5ec7c"),
    (True, {"max_directories": 1}, "3c247f2d244698ffb940e3542b7723236d3c5dfb9ccf0694621fa1e878f11c3f"),
])
def test_legacy_complete_wire_bytes_match_frozen_base(tmp_path, seeded, limits, expected):
    entry = _write(tmp_path, "z_entry.py", "import z_helper\nimport missing\n")
    _write(tmp_path, "z_helper.py", "import child\n")
    _write(tmp_path, "child.py", "VALUE = 1\n")
    seed = _write(tmp_path, "a_unrelated.py", "import a_leaf\n")
    _write(tmp_path, "a_leaf.py", "VALUE = 2\n")
    if seeded:
        result = discovery._discover_sources_from_entries(
            entry, project_root=tmp_path, additional_entries=(str(seed),), **limits)
    else:
        result = discovery.discover_sources(entry, project_root=tmp_path, **limits)
    normalized = result.to_json().replace(str(tmp_path), "<root>")
    assert hashlib.sha256(normalized.encode()).hexdigest() == expected
