"""Real source/capture checks for shared preparation priority and bounded rereads."""
from collections import Counter
import hashlib
from pathlib import Path
import sys
from types import ModuleType

import pytest

pytestmark = pytest.mark.filterwarnings("error::pytest.PytestUnraisableExceptionWarning")

import scar.analysis.call_demand as composition
from scar.analysis.call_seeds import read_call_source_seeds
from scar.analysis.program_context_store import PreparedContextStore
from scar.analysis.program_inventory import inventory_program
from scar.analysis.program_lowering import prepare_source
from scar.ir.program.call_demand import CallSourceAdmissionStatus
from scar.ir.program.call_edges import CallLinkStatus
from scar.ir.program.expansion import ContextStoreBudget
from scar.trace.call_edges import CallEdgeRecorder


def _write(path, text):
    path.write_text(text, encoding="utf-8")
    return path


def _context_bytes(path, project):
    # Independent fixture calibration, outside the invocation being measured.
    context = prepare_source(path, project_root=project)
    with PreparedContextStore() as store:
        store.put(context)
        return store.compressed_bytes_written


def test_observed_decoy_cannot_consume_entry_and_import_context_allowance(tmp_path, monkeypatch):
    dependency = _write(tmp_path / "workspace_dep.py", "def identity(value):\n    return value\n")
    entry = _write(tmp_path / "entry.py",
        "from workspace_dep import identity\n"
        "def run(value):\n    return identity(value)\n"
        "answer = run(None)\n")
    # One large source constant makes the unrelated context expensive without
    # executing a large workload or constructing a manual program graph.
    padding = "".join(hashlib.sha256(str(index).encode()).hexdigest() for index in range(1536))
    decoy = _write(tmp_path / "aaa_decoy.py",
        "def unrelated(value):\n    return value\n" + "padding = " + repr(padding) + "\n")
    module = ModuleType("aaa_decoy")
    exec(compile(decoy.read_text(), str(decoy), "exec", dont_inherit=True), module.__dict__)
    trace = tmp_path / "trace"
    recorder = CallEdgeRecorder(trace, tmp_path)
    previous = sys.getprofile()
    sys.setprofile(recorder.profile)
    try:
        value = object()
        assert module.unrelated(value) is value
    finally:
        sys.setprofile(previous)
        recorder.close()

    standalone = read_call_source_seeds(trace, tmp_path)
    link, = standalone.eligible_code_links()
    assert link.status is CallLinkStatus.VERIFIED and link.snapshot.path == str(decoy)

    entry_cost = _context_bytes(entry, tmp_path)
    dependency_cost = _context_bytes(dependency, tmp_path)
    decoy_cost = _context_bytes(decoy, tmp_path)
    context_budget = ContextStoreBudget(max_compressed_bytes=entry_cost + dependency_cost + 256)
    assert decoy_cost > context_budget.max_compressed_bytes

    preparations = Counter()
    original = composition.prepare_source

    def count_preparation(path, **kwargs):
        preparations[str(path)] += 1
        return original(path, **kwargs)

    monkeypatch.setattr(composition, "prepare_source", count_preparation)
    result = inventory_program(entry, project_root=tmp_path, calls_trace=trace,
                               context_budget=context_budget, max_lowered_bodies=8, max_operations=1000)
    assert result.to_dict()["schema_version"] == 6
    assert result.call_sources.to_dict() == standalone.to_dict()
    assert preparations == {str(entry): 1, str(dependency): 1, str(decoy): 1}
    assert result.source_analysis_measurements["source_prepare_max_per_path"] == 1
    assert result.source_analysis_measurements["source_discovery_passes"] == 2

    emitted = {(file.snapshot.path, definition.name): body.graph
               for file in result.files for definition in file.definitions
               for body in file.bodies if body.definition == definition.id}
    assert emitted[str(entry), "run"] is not None
    assert emitted[str(dependency), "identity"] is not None
    decoy_file, = [file for file in result.files if file.snapshot.path == str(decoy)]
    assert not any(body.graph is not None for body in decoy_file.bodies)
    outcome, = result.call_source_scope.admissions
    assert outcome.origin.code == link.code
    assert outcome.status in (CallSourceAdmissionStatus.UNAVAILABLE,
                              CallSourceAdmissionStatus.INDEXED_WITHOUT_BODY)
    assert outcome.core_region is None and outcome.reason
    assert any(item.path == str(decoy) and item.reason for item in result.expansion.unavailable_contexts)


@pytest.mark.parametrize("consumer", ("prepare", "source_projection"))
def test_sealed_source_that_exceeds_the_read_cap_is_rejected_before_open(tmp_path, monkeypatch, consumer):
    path = _write(tmp_path / "raw.py", "def f(value):\n    return value\n")
    with composition._SourceWorkspace(tmp_path, ContextStoreBudget()) as workspace:
        workspace.source_projection(path)
        with path.open("ab") as stream:
            stream.truncate(4_000_001)
        original_open = Path.open

        def guarded_open(self, mode="r", *args, **kwargs):
            if self == path and "r" in mode:
                raise AssertionError("oversized source was opened before enforcing its byte limit")
            return original_open(self, mode, *args, **kwargs)

        monkeypatch.setattr(Path, "open", guarded_open)
        with pytest.raises(ValueError, match="4 MB"):
            getattr(workspace, consumer)(path)
        assert workspace.preparations[str(path)] == 1


@pytest.mark.parametrize("consumer", ("prepare", "source_projection"))
def test_source_growth_during_reread_is_bounded_and_detected(tmp_path, monkeypatch, consumer):
    path = _write(tmp_path / "raw.py", "def f(value):\n    return value\n")
    initial_size = path.stat().st_size
    with composition._SourceWorkspace(tmp_path, ContextStoreBudget()) as workspace:
        workspace.source_projection(path)
        original_open = Path.open
        reads = []

        class GrowingReader:
            def __init__(self, stream):
                self.stream = stream

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self.stream.close()

            def read(self, size=-1):
                assert type(size) is int and 0 <= size <= initial_size, "unbounded source reread"
                reads.append(size)
                with original_open(path, "ab") as writer:
                    writer.write(b"# source grew while being read\n")
                return self.stream.read(size)

        def growing_open(self, mode="r", *args, **kwargs):
            stream = original_open(self, mode, *args, **kwargs)
            return GrowingReader(stream) if self == path and mode == "rb" else stream

        monkeypatch.setattr(Path, "open", growing_open)
        with pytest.raises(OSError, match="changed while"):
            getattr(workspace, consumer)(path)
        assert reads == [initial_size]
        assert workspace.preparations[str(path)] == 1
