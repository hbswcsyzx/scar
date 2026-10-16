"""Compilation-policy report versions replay real captures and archived v1 output."""
import __future__
from copy import deepcopy
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest

import scar.analysis.call_seeds as seeds
from scar.analysis.call_seeds import CallSourceSeedReport, read_call_source_seeds
from scar.ir.program.call_edges import CallEdgeBudget, CallLinkStatus
from scar.ir.program.compilation import CallCompilationProfile
from scar.trace.call_edges import CallEdgeRecorder


LEGACY = CallCompilationProfile.LEGACY_ZERO_FLAGS
RECORDED = CallCompilationProfile.RECORDED_FUTURE_FLAGS


def _capture(root, contexts):
    """Execute only this tiny fixture; the resolver never executes its source."""
    root.mkdir()
    path = root / "library.py"
    source = (
        "def outer(value: object):\n"
        "    def inner(argument: object):\n"
        "        return argument\n"
        "    return inner(value)\n"
    )
    path.write_text(source, encoding="utf-8")
    functions = []
    for inherited in contexts:
        namespace = {}
        if inherited:
            loader = {"source": source, "filename": str(path)}
            # compile() really inherits its caller's future flags; the target
            # source itself has no future statement or resolver-side rewrite.
            exec(compile(
                "from __future__ import annotations\n"
                "module_code = compile(source, filename, 'exec')\n",
                "<fixture-loader>", "exec", dont_inherit=True,
            ), loader)
            code = loader["module_code"]
        else:
            code = compile(source, str(path), "exec", dont_inherit=True)
        exec(code, namespace)
        function = namespace["outer"]
        assert bool(function.__code__.co_flags & __future__.annotations.compiler_flag) is inherited
        functions.append(function)
    output = root / "trace"
    recorder = CallEdgeRecorder(output, root)
    previous = sys.getprofile()
    sys.setprofile(recorder.profile)
    try:
        for function in functions:
            value = object()
            assert function(value) is value
    finally:
        sys.setprofile(previous)
        recorder.close()
    return root, output


@pytest.fixture(scope="module")
def inherited_capture(tmp_path_factory):
    return _capture(tmp_path_factory.mktemp("seed-profiles") / "project", (True,))


@pytest.fixture(scope="module")
def reports(inherited_capture):
    root, output = inherited_capture
    return {
        profile: read_call_source_seeds(output, root, compilation_profile=profile)
        for profile in (LEGACY, RECORDED)
    }


def test_default_recorded_profile_recovers_real_inherited_future_and_nested_code(inherited_capture, reports):
    root, output = inherited_capture
    current = read_call_source_seeds(output, root)
    assert current.compilation_profile is RECORDED
    assert current.to_dict() == reports[RECORDED].to_dict()
    assert current.to_dict()["schema_version"] == 2
    assert current.to_dict()["compilation_profile"] == "RECORDED_FUTURE_FLAGS_V1"
    names = {capture.code.key: capture.code.qualname for capture in current.model.codes}
    assert {names[group.code] for group in current.eligible_groups()} == {
        "outer", "outer.<locals>.inner",
    }
    assert all(link.status is CallLinkStatus.VERIFIED for link in current.model.code_links)
    assert all(link.snapshot and link.definition and link.source for link in current.eligible_code_links())
    assert not any(current.model.authority_flags().values())
    assert current.to_dict()["target_executed_by_resolver"] is False
    legacy = reports[LEGACY]
    assert legacy.eligible_groups() == ()
    assert all(link.status is CallLinkStatus.MISMATCH for link in legacy.model.code_links)


@pytest.mark.parametrize("profile", [LEGACY, RECORDED])
def test_both_report_versions_replay_their_original_compilation_policy(reports, profile):
    report = reports[profile]
    document = report.to_dict()
    assert CallSourceSeedReport._compilation_profile(document) is profile
    decoded = CallSourceSeedReport._decode_replay_input(document, verification_budget=CallEdgeBudget())
    assert decoded.to_dict() == report.model.to_dict()
    restored = CallSourceSeedReport.from_dict(document)
    assert restored.compilation_profile is profile
    assert restored.to_dict() == document
    assert restored.eligible_groups() == report.eligible_groups()


def test_legacy_direct_constructor_preserves_the_complete_v1_wire_shape(reports):
    legacy = reports[LEGACY]
    direct = CallSourceSeedReport(legacy.model)
    assert direct.compilation_profile is LEGACY
    assert direct.to_dict() == legacy.to_dict()
    assert set(direct.to_dict()) == {
        "schema", "schema_version", "model", "summary", "target_executed_by_resolver",
        *legacy.model.authority_flags(),
    }
    assert direct.to_dict()["schema_version"] == 1
    assert "compilation_profile" not in direct.to_dict()


def test_real_archived_v1_report_is_exact_and_replays_without_upgrade(tmp_path, inherited_capture, reports):
    repository = Path(__file__).resolve().parents[2]
    package = tmp_path / "archived-package"
    package.mkdir()
    archive = subprocess.check_output(["git", "archive", "9cb3805", "scar"], cwd=repository)
    with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
        stream.extractall(package, filter="data")
    root, output = inherited_capture
    environment = {key: value for key, value in os.environ.items() if not key.startswith("SCAR_")}
    environment.update(PYTHONPATH=str(package), PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run(
        [sys.executable, "-c",
         "import json, sys\n"
         "from pathlib import Path\n"
         "import scar\n"
         "from scar.analysis.call_seeds import read_call_source_seeds\n"
         "assert Path(scar.__file__).resolve().is_relative_to(Path(sys.argv[3]))\n"
         "print(json.dumps(read_call_source_seeds(sys.argv[1], sys.argv[2]).to_dict()))\n",
         str(output), str(root), str(package)],
        cwd=package, env=environment, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    document = json.loads(result.stdout)
    assert document == reports[LEGACY].to_dict()
    assert document["schema_version"] == 1 and "compilation_profile" not in document
    restored = CallSourceSeedReport.from_dict(document)
    assert restored.compilation_profile is LEGACY
    assert restored.to_dict() == document
    assert restored.eligible_groups() == ()


def test_one_source_recorded_under_both_contexts_does_not_share_wrong_compile_trials(tmp_path):
    root, output = _capture(tmp_path / "project", (False, True))
    report = read_call_source_seeds(output, root)
    assert len(report.model.groups) == len(report.eligible_groups()) == 4
    assert len({link.definition for link in report.eligible_code_links()}) == 2
    assert len({link.snapshot for link in report.eligible_code_links()}) == 1
    assert all(link.status is CallLinkStatus.VERIFIED for link in report.model.code_links)
    assert CallSourceSeedReport.from_dict(report.to_dict()).to_dict() == report.to_dict()
    legacy = read_call_source_seeds(output, root, compilation_profile=LEGACY)
    assert len(legacy.eligible_groups()) == 2
    assert {link.status for link in legacy.model.code_links} == {
        CallLinkStatus.VERIFIED, CallLinkStatus.MISMATCH,
    }
    assert CallSourceSeedReport.from_dict(legacy.to_dict()).to_dict() == legacy.to_dict()


@pytest.mark.parametrize("profile", [LEGACY, RECORDED])
def test_valid_policy_relabel_does_not_reuse_previous_matching_results(reports, profile):
    document = deepcopy(reports[profile].to_dict())
    if profile is LEGACY:
        document["schema_version"] = 2
        document["compilation_profile"] = RECORDED.value
        assert CallSourceSeedReport._compilation_profile(document) is RECORDED
    else:
        document["schema_version"] = 1
        del document["compilation_profile"]
        assert CallSourceSeedReport._compilation_profile(document) is LEGACY
    with pytest.raises(ValueError, match="replay"):
        CallSourceSeedReport.from_dict(document)


@pytest.mark.parametrize("profile,mutation", [
    (LEGACY, {"compilation_profile": LEGACY.value}),
    (LEGACY, {"compilation_profile": RECORDED.value}),
    (LEGACY, {"schema_version": True}),
    (LEGACY, {"schema_version": 0}),
    (LEGACY, {"schema_version": 2}),
    (RECORDED, {"schema_version": 1}),
    (RECORDED, {"schema_version": False}),
    (RECORDED, {"schema_version": 3}),
    (RECORDED, {"schema_version": 2.0}),
    (RECORDED, {"schema_version": "2"}),
    (RECORDED, {"compilation_profile": LEGACY.value}),
    (RECORDED, {"compilation_profile": "RECORDED_FUTURE_FLAGS_V2"}),
    (RECORDED, {"compilation_profile": True}),
    (RECORDED, {"compilation_profile": None}),
    (RECORDED, {"compilation_profile": {"trusted": True}}),
    (RECORDED, {"schema": "scar.call-links"}),
    (RECORDED, {"trusted": True}),
])
def test_invalid_version_profile_pairs_fail_before_io(reports, monkeypatch, profile, mutation):
    document = deepcopy(reports[profile].to_dict())
    document.update(mutation)

    def forbidden(*args, **kwargs):
        pytest.fail("invalid report policy must fail before raw/source work")

    monkeypatch.setattr(seeds, "read_call_source_seeds", forbidden)
    monkeypatch.setattr(seeds, "scan_call_trace", forbidden)
    monkeypatch.setattr(seeds, "_Sources", forbidden)
    with pytest.raises(ValueError):
        CallSourceSeedReport._compilation_profile(document)
    with pytest.raises(ValueError):
        CallSourceSeedReport.from_dict(document)


def test_v2_missing_profile_fails_before_io(reports, monkeypatch):
    document = deepcopy(reports[RECORDED].to_dict())
    del document["compilation_profile"]
    monkeypatch.setattr(seeds, "read_call_source_seeds", lambda *a, **kw: pytest.fail("must not replay"))
    with pytest.raises(ValueError, match="fields"):
        CallSourceSeedReport.from_dict(document)


@pytest.mark.parametrize("profile", [LEGACY, RECORDED])
@pytest.mark.parametrize("mutation", ["budget", "authority", "model_extra"])
def test_existing_model_authority_and_independent_budget_checks_still_precede_io(
    reports, monkeypatch, profile, mutation,
):
    document = deepcopy(reports[profile].to_dict())
    if mutation == "budget":
        document["model"]["budget"]["max_references"] += 1
    elif mutation == "authority":
        document["data_connections_established"] = True
    else:
        document["model"]["trusted"] = True
    monkeypatch.setattr(seeds, "read_call_source_seeds", lambda *a, **kw: pytest.fail("must not replay"))
    with pytest.raises(ValueError):
        CallSourceSeedReport.from_dict(document)


@pytest.mark.parametrize("profile", [LEGACY.value, RECORDED.value, True, None])
def test_public_and_private_readers_require_typed_profile_before_io(monkeypatch, profile):
    monkeypatch.setattr(seeds, "scan_call_trace", lambda *a, **kw: pytest.fail("must not scan"))

    class NoFilesystem:
        def __fspath__(self):
            pytest.fail("profile must be checked before path resolution")

    for reader in (seeds.read_call_source_seeds, seeds._read_call_source_seeds):
        with pytest.raises(ValueError, match="typed compilation profile"):
            reader(NoFilesystem(), NoFilesystem(), budget=CallEdgeBudget(), compilation_profile=profile)


@pytest.mark.parametrize("profile", [LEGACY.value, RECORDED.value, True, None])
def test_report_requires_typed_policy(reports, profile):
    with pytest.raises(ValueError, match="typed compilation profile"):
        replace(reports[RECORDED], compilation_profile=profile)


def test_recorded_profile_does_not_turn_source_drift_into_a_match(tmp_path):
    root, output = _capture(tmp_path / "project", (True,))
    document = read_call_source_seeds(output, root).to_dict()
    source = root / "library.py"
    source.write_text(source.read_text().replace("return argument", "return None"), encoding="utf-8")
    changed = read_call_source_seeds(output, root)
    assert changed.eligible_groups() == ()
    assert all(link.status is CallLinkStatus.MISMATCH for link in changed.model.code_links)
    with pytest.raises(ValueError, match="replay"):
        CallSourceSeedReport.from_dict(document)
