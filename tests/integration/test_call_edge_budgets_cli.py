"""Public call-link budgets are independent ceilings and leave no partial report."""
import gzip
import json
import sys

from tests.integration.test_call_edges_cli import cli, linked, read


def invalid(result, text):
    assert result.returncode == 2, result.stdout + result.stderr
    document = json.loads(result.stdout)
    assert document["status"] == "INVALID" and document["transformation_authorized"] is False
    assert any(text in error for error in document["errors"]), document


def run_identity(document):
    model = document["analysis"]["model"]
    names = {item["code"]["key"]: item["code"]["qualname"] for item in model["codes"]}
    run, = [edge for edge in model["edges"] if names[edge["entry"]["code"]] == "run"]
    identity = run["entry"]["invocation"]
    return ["--process", identity["process_id"], "--thread", identity["thread_id"],
            "--invocation", identity["invocation_id"]]


def test_explicit_independent_budgets_roundtrip_without_authorizing_transformations(linked, tmp_path):
    project, _, inventory, trace, _ = linked
    expected = {"max_raw_bytes": 16_000_000, "max_lines": 100_000, "max_line_bytes": 100_000,
                "max_processes": 2, "max_codes": 4096, "max_events": 50_000,
                "max_source_files": 32, "max_source_bytes": 4_000_000,
                "max_references": 250_000, "max_path": 64}
    options = ["--max-call-trace-bytes", expected["max_raw_bytes"],
               "--max-call-trace-lines", expected["max_lines"],
               "--max-call-line-bytes", expected["max_line_bytes"],
               "--max-call-processes", expected["max_processes"],
               "--max-call-trace-codes", expected["max_codes"],
               "--max-call-trace-events", expected["max_events"],
               "--max-call-source-files", expected["max_source_files"],
               "--max-call-source-bytes", expected["max_source_bytes"],
               "--max-call-references", expected["max_references"],
               "--max-call-path", expected["max_path"], "--max-call-report-bytes", 16_000_000]
    output = tmp_path / "explicit.json.gz"
    linked_result = cli("link-calls", trace, "--project-root", project, "--inventory", inventory,
                        "--out", output, *options)
    assert linked_result.returncode == 0, linked_result.stdout + linked_result.stderr
    assert json.loads(linked_result.stdout)["transformation_authorized"] is False
    document = read(output)
    assert document["analysis"]["model"]["budget"] == expected
    checked = cli("check-call-links", output, *options)
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert json.loads(checked.stdout)["status"] == "REPLAYED"
    queried = cli("query-call-refs", output, *run_identity(document), *options)
    assert queried.returncode == 0, queried.stdout + queried.stderr
    query = json.loads(queried.stdout)
    assert query["transformation_authorized"] is False
    assert query["query"]["identity_only"] is True
    assert query["query"]["content_or_effect_equivalence_established"] is False
    # A report cannot lift a verifier's independently selected ceiling, even
    # when this trace's actual number of references is far below either value.
    rejected = cli("check-call-links", output, *options, "--max-call-references", 249_999)
    invalid(rejected, "independent verifier budget: max_references")


def test_low_trace_reference_and_path_caps_reject_without_output(linked, tmp_path):
    project, _, inventory, trace, _ = linked
    for flag in ("--max-call-trace-bytes", "--max-call-trace-lines", "--max-call-line-bytes",
                 "--max-call-trace-events", "--max-call-trace-codes", "--max-call-references",
                 "--max-call-path"):
        output = tmp_path / (flag.removeprefix("--") + ".json.gz")
        rejected = cli("link-calls", trace, "--project-root", project, "--inventory", inventory,
                       "--out", output, flag, 1)
        invalid(rejected, "budget")
        assert not output.exists()
    assert not list(tmp_path.glob(".scar-call-*"))


def test_low_source_caps_produce_explicit_boundaries_within_verification_scope(linked, tmp_path):
    project, _, inventory, trace, _ = linked
    for flag, field, detail in (("--max-call-source-files", "max_source_files", "source file budget exceeded"),
                                ("--max-call-source-bytes", "max_source_bytes", "source byte budget exceeded")):
        output = tmp_path / (field + ".json.gz")
        result = cli("link-calls", trace, "--project-root", project, "--inventory", inventory,
                     "--out", output, flag, 1)
        assert result.returncode == 0, result.stdout + result.stderr
        document = read(output)
        analysis, model = document["analysis"], document["analysis"]["model"]
        assert model["budget"][field] == 1
        bounded = [link for link in model["code_links"]
                   if any(issue["kind"] == "SOURCE_BOUNDARY" and issue["detail"] == detail
                          for issue in link["issues"])]
        assert bounded
        assert all(link["status"] == "INCOMPLETE" and link["definition"] is None
                   and link["source"] is None for link in bounded)
        snapshots = {link["snapshot"]["path"] for link in model["code_links"] if link["snapshot"] is not None}
        if field == "max_source_files":
            assert len(snapshots) <= 1
        else:
            assert not snapshots
            assert analysis["summary"]["verified_source_call_sites"] == 0
            assert analysis["summary"]["target_body_observations"] == 0
        assert analysis["transformation_authorized"] is False
        assert analysis["function_environment_established"] is False
        assert analysis["contents_or_effects_established"] is False
        checked = cli("check-call-links", output)
        assert checked.returncode == 0, checked.stdout + checked.stderr


def test_process_count_ceiling_rejects_two_real_capture_processes(linked, tmp_path):
    project, entry, inventory, first_trace, _ = linked
    second_trace = tmp_path / "second-trace"
    captured = cli("trace", "--calls-only", "--project-root", project, "--out", second_trace,
                   "--", sys.executable, entry, cwd=project)
    assert captured.returncode == 0, captured.stdout + captured.stderr
    combined = tmp_path / "combined-trace"
    combined.mkdir()
    for directory in (first_trace, second_trace):
        for path in directory.glob("call-*"):
            destination = combined / path.name
            assert not destination.exists()
            destination.write_bytes(path.read_bytes())
    assert len(list(combined.glob("call-meta.*.json"))) == 2
    output = tmp_path / "too-many-processes.json"
    rejected = cli("link-calls", combined, "--project-root", project, "--inventory", inventory,
                   "--out", output, "--max-call-processes", 1)
    invalid(rejected, "process budget exceeded")
    assert not output.exists() and not list(tmp_path.glob(".scar-call-*"))


def test_public_report_read_ceiling_is_decompressed_and_exact_for_check_and_query(linked, tmp_path):
    *_, compressed = linked
    document = read(compressed)
    plain = tmp_path / "plain.json"
    plain.write_text(json.dumps(document, ensure_ascii=False) + "\n", encoding="utf-8")
    for path in (plain, compressed):
        raw = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
        if path.suffix == ".gz":
            assert path.stat().st_size < len(raw) - 1
        checked = cli("check-call-links", path, "--max-call-report-bytes", len(raw))
        assert checked.returncode == 0, checked.stdout + checked.stderr
        invalid(cli("check-call-links", path, "--max-call-report-bytes", len(raw) - 1),
                "independent read byte ceiling")
        invalid(cli("query-call-refs", path, *run_identity(document),
                    "--max-call-report-bytes", len(raw) - 1), "independent read byte ceiling")


def test_public_output_ceiling_preserves_old_reports_and_removes_new_partial_files(linked, tmp_path):
    project, _, inventory, trace, _ = linked
    for suffix in (".json", ".json.gz"):
        for existing in (False, True):
            output = tmp_path / (f"limited-{existing}" + suffix)
            old_raw = b'{"schema":"scar.call-links-envelope","old":true}\n'
            previous = gzip.compress(old_raw) if suffix.endswith(".gz") else old_raw
            if existing:
                output.write_bytes(previous)
            result = cli("link-calls", trace, "--project-root", project, "--inventory", inventory,
                         "--out", output, "--max-call-report-bytes", 128)
            invalid(result, "independent write byte ceiling")
            assert output.exists() is existing
            if existing:
                assert output.read_bytes() == previous
            assert not list(tmp_path.glob(".scar-call-*"))


def test_public_nonpositive_ceilings_are_invalid(linked, tmp_path):
    project, _, inventory, trace, report = linked
    for ceiling in (0, -1):
        invalid(cli("check-call-links", report, "--max-call-report-bytes", ceiling),
                "positive exact integer")
        output = tmp_path / f"invalid-{ceiling}.json"
        invalid(cli("link-calls", trace, "--project-root", project, "--inventory", inventory,
                    "--out", output, "--max-call-processes", ceiling), "exact integer")
        assert not output.exists()
    assert not list(tmp_path.glob(".scar-call-*"))
