"""Independent new-artifact/count/reference audit; no SCAR import or compile."""
import base64
from collections import Counter, defaultdict
import gzip
import hashlib
from io import BytesIO, TextIOWrapper
import json
from pathlib import Path
import tokenize


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode()


def parse(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            assert key not in result, "duplicate JSON key"
            result[key] = value
        return result
    def nonfinite(value):
        raise ValueError(value)
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)


root = Path(__file__).resolve().parent
out = root / "result"
report_raw = (out / "continuation.json").read_bytes()
report = parse(report_raw)
assert canonical(report) == report_raw
assert report["schema"] == "scar.dependency-source-continuation" and report["schema_version"] == 1
assert report["continuation_attempt_complete"] is True and report["first_stage_complete"] is False
assert report["whole_program_graph_established"] is False and report["transformation_authorized"] is False
parent_dir = Path(report["parent"]["directory"])
parent_raw = (parent_dir / report["parent"]["path"]).read_bytes()
assert sha(parent_raw) == report["parent"]["raw_sha256"]
assert len(parent_raw) == report["parent"]["raw_bytes"]
parent = parse(parent_raw)
assert report["program_root"] == parent["program_root"]
assert report["source_roots"] == parent["source_roots"]
assert report["trace_files"] == parent["trace_files"]
assert report["collection_metadata"] == parent["collection_metadata"]
assert report["compilation_profile"] == parent["compilation_profile"]
assert len(report_raw) <= report["budget"]["max_report_bytes"]
for line in (root / "module.sha256.txt").read_text().splitlines():
    digest, filename = line.split(maxsplit=1)
    snapshot = root / (Path(filename).stem + ".snapshot.py")
    assert sha(snapshot.read_bytes()) == digest

old_files = {row["path"]: row for row in parent["source_files"]}
files = {row["path"]: row for row in report["source_files"]}
assert len(files) == len(report["source_files"]) and set(files) == set(old_files)
old_rows = {(row["process_id"], row["code"]): row for row in parent["admissions"]}
rows = {(row["process_id"], row["code"]): row for row in report["admissions"]}
assert len(rows) == len(report["admissions"]) and set(rows) == set(old_rows)
local_targets = defaultdict(list)
for row in rows.values():
    filename = row["source_file"]
    link = row["code_source_link"]
    locator = files[filename]["source_graph_artifact"] if filename in files else None
    if link is not None and locator is not None and locator["origin"] == "CONTINUATION":
        local_targets[locator["artifact"]["path"]].append(link)

headers, documents, checked_bytes = {}, {}, 0
for family in ("sources", "graphs"):
    for path in sorted((out / family).iterdir()):
        assert path.is_file() and not path.is_symlink()
        payload = gzip.decompress(path.read_bytes())
        digest = sha(payload)
        assert path.name == digest + ".json.gz"
        doc = parse(payload)
        assert canonical(doc) == payload
        relative = str(path.relative_to(out))
        header = {"schema": doc["schema"], "schema_version": doc["schema_version"],
                  "path": relative, "canonical_sha256": digest,
                  "canonical_bytes": len(payload), "compressed_bytes": path.stat().st_size}
        checked_bytes += len(payload)
        if family == "sources":
            assert doc["schema"] == "scar.dependency-source-snapshot"
            raw = base64.b64decode(doc["raw_base64"], validate=True)
            assert len(raw) == doc["raw_bytes"] and sha(raw) == doc["raw_sha256"]
            encoding, _ = tokenize.detect_encoding(BytesIO(raw).readline)
            with TextIOWrapper(BytesIO(raw), encoding=encoding, newline=None) as stream:
                text = stream.read()
            assert text == doc["decoded_text"]
            assert "sha256:" + sha(text.encode()) == doc["fingerprint"]
            documents[relative] = {key: doc[key] for key in (
                "source_root", "namespace_root", "original_uri", "raw_sha256", "raw_bytes", "fingerprint")}
        else:
            assert doc["schema"] == "scar.dependency-continuation-source-graphs"
            assert doc["independent_source_replay_established"] is False
            assert doc["first_stage_complete"] is False
            for field, layer in (("semantic_sha256", "semantic"),
                                 ("semantics_sha256", "semantics"), ("control_sha256", "control")):
                assert sha(canonical(doc[layer])) == doc["context"][field]
            assert doc["namespace_root"] == doc["context"]["namespace_root"]
            old = old_files[doc["snapshot"]["path"]]
            assert old["source_graph_artifact"] is None
            assert old["fingerprint"] == doc["snapshot"]["fingerprint"]
            assert doc["source_root"] == old["source_root"]
            if old["context"] is not None:
                assert doc["context"] == old["context"] and doc["parent_context_digest_matched"] is True
            definitions = {item["id"]["wire"]: item for item in doc["semantic"]["definitions"]}
            atoms = {item["id"]["wire"]: item["reference"] for item in doc["semantic"]["source_atoms"]}
            for link in local_targets.get(relative, ()):
                assert link["snapshot"] == doc["snapshot"]
                if link["definition"] is not None:
                    definition = definitions[link["definition"]["wire"]]
                    reference = link["source"]
                    assert reference["atom_id"]["wire"] in {item["wire"] for item in definition["source_atoms"]}
                    assert atoms[reference["atom_id"]["wire"]] == reference
            documents[relative] = {"source_root": doc["source_root"], "context": doc["context"],
                                    "snapshot": doc["snapshot"],
                                    "source_snapshot_locator": doc["source_snapshot_locator"]}
        headers[relative] = header
        del doc, payload


def locator(value, source_root):
    assert value["source_root"] == source_root
    artifact = value["artifact"]
    if value["origin"] == "CONTINUATION":
        assert artifact == headers[artifact["path"]]
    else:
        assert value["origin"] == "PARENT"
        assert value["parent_report_raw_sha256"] == report["parent"]["raw_sha256"]
        assert value["parent_directory"] == str(parent_dir)
    return artifact


inherited_graphs = inherited_snapshots = 0
provider_refs_checked = set()
for filename, row in files.items():
    old = old_files[filename]
    for field in ("snapshot_artifact", "source_graph_artifact"):
        value = row[field]
        if old[field] is not None:
            assert value["origin"] == "PARENT"
            assert locator(value, row["source_root"]) == old[field]
            if field == "snapshot_artifact": inherited_snapshots += 1
            else: inherited_graphs += 1
        elif value is not None:
            artifact = locator(value, row["source_root"])
            document = documents[artifact["path"]]
            if field == "snapshot_artifact":
                assert document["original_uri"] == filename
                assert all(document[key] == old[key] for key in ("raw_sha256", "raw_bytes", "fingerprint"))
            else:
                assert document["context"] == row["context"]
                assert document["source_snapshot_locator"] == row["snapshot_artifact"]
    for provider in row["providers"]:
        if provider["kind"] != "INSTALLED_DISTRIBUTION": continue
        for field in ("metadata_artifact", "record_artifact"):
            reference = locator(provider[field], row["source_root"])
            if reference["path"] in provider_refs_checked:
                continue
            path = parent_dir / reference["path"]
            raw = gzip.decompress(path.read_bytes())
            assert sha(raw) == reference["canonical_sha256"] and len(raw) == reference["canonical_bytes"]
            provider_refs_checked.add(reference["path"])

guards = {row["path"]: row for row in report["source_guards"]}
assert len(guards) == len(report["source_guards"]) and set(guards) == set(files)
for filename, guard in guards.items():
    assert guard["expected_raw_sha256"] == old_files[filename]["raw_sha256"]
    assert guard["expected_raw_bytes"] == old_files[filename]["raw_bytes"]
    assert guard["expected_fingerprint"] == old_files[filename]["fingerprint"]
    if guard["matches"]:
        assert guard["current_raw_sha256"] == guard["expected_raw_sha256"]
        assert guard["current_raw_bytes"] == guard["expected_raw_bytes"]
        assert guard["current_fingerprint"] == guard["expected_fingerprint"]

raw_groups, raw_codes, entries, exits = Counter(), {}, 0, 0
for recorded in report["trace_files"]:
    path = Path(recorded["path"])
    if not path.exists(): path = Path(str(path) + ".gz")
    opener = gzip.open if path.suffix == ".gz" else open
    digest, size, lines = hashlib.sha256(), 0, 0
    with opener(path, "rb") as stream:
        if recorded["family"] == "meta":
            payload = stream.read(); digest.update(payload); size = len(payload); lines = len(payload.splitlines())
            assert parse(payload) in report["collection_metadata"]
        else:
            for line in stream:
                digest.update(line); size += len(line); lines += 1
                row = parse(line)
                if recorded["family"] == "codes": raw_codes[recorded["process_id"], row["key"]] = row
                elif row["kind"] == "call_enter":
                    entries += 1; raw_groups[row["process_id"], row["code"]] += 1
                elif row["kind"] == "call_exit": exits += 1
                else: raise AssertionError("unknown event kind")
    assert digest.hexdigest() == recorded["raw_sha256"] and size == recorded["raw_bytes"] and lines == recorded["lines"]
assert set(raw_groups) == set(rows)
statuses, weighted, frontier_weights = Counter(), Counter(), Counter()
reused = matched = 0
for key, row in rows.items():
    old = old_rows[key]
    assert row["entered_invocations"] == old["entered_invocations"] == raw_groups[key]
    assert row["captured_code"] == old["captured_code"] == raw_codes.get(key)
    for field in ("first_anchor", "last_anchor", "descriptor_anchor"):
        assert row[field] == old[field]
    if row["source_file"] in guards:
        assert row["current_source_guard_matches"] == guards[row["source_file"]]["matches"]
    if old["code_source_link"] is not None:
        assert row["code_source_link"] == old["code_source_link"]
        assert row["source_compiler_witness_reused"] is True
        assert row["source_compiler_matching_performed"] is False
        assert row["witness_origin"] == "PARENT_SOURCE_COMPILER_WITNESS_NOT_RECOMPILED"
        reused += 1
    if row["source_compiler_matching_performed"]:
        assert old["code_source_link"] is None
        assert old_files[row["source_file"]]["snapshot_artifact"] is None
        matched += 1
    statuses[row["status"]] += 1; weighted[row["status"]] += row["entered_invocations"]
    for code in {gap["code"] for gap in row["frontiers"]}:
        frontier_weights[code] += row["entered_invocations"]
assert report["summary"]["statuses"] == dict(statuses)
assert report["summary"]["weighted_statuses"] == dict(weighted)
assert report["summary"]["weighted_frontiers"] == dict(frontier_weights)
assert report["summary"]["historical_compiler_witnesses_reused"] == reused
assert report["summary"]["new_compiler_matching_groups"] == matched
assert report["raw_audit"]["entered_invocations"] == entries
assert report["raw_audit"]["exited_invocations"] == exits
expected_missing = {path for path, row in old_files.items() if row["source_graph_artifact"] is None}
assert len(report["completed_files"]) == len(set(report["completed_files"]))
assert set(report["completed_files"]) == expected_missing
assert report["measurements"]["source_prepare_attempts"] <= len(expected_missing)
for family, folder in (("snapshot", "sources"), ("graph", "graphs")):
    actual_bytes = sum(value["canonical_bytes"] for path, value in headers.items() if path.startswith(folder + "/"))
    assert actual_bytes == report["measurements"].get(family + "_canonical_bytes_written", 0)
    assert actual_bytes <= report["budget"]["max_" + family + "_bytes"]
    assert all(value["canonical_bytes"] <= report["budget"]["max_" + family + "_record_bytes"]
               for path, value in headers.items() if path.startswith(folder + "/"))
result = {"schema": "scar.dependency-continuation-audit", "schema_version": 1,
          "continuation_report_raw_sha256": sha(report_raw),
          "parent_report_raw_sha256": sha(parent_raw),
          "raw_entries": entries, "raw_exits": exits, "captured_descriptors": len(raw_codes),
          "entered_code_groups": len(raw_groups), "new_artifacts_checked": len(headers),
          "new_canonical_bytes_checked": checked_bytes,
          "inherited_snapshots": inherited_snapshots, "inherited_graphs": inherited_graphs,
          "historical_compiler_witnesses_reused": reused, "new_compiler_matching_groups": matched,
          "source_prepare_attempts": report["measurements"]["source_prepare_attempts"],
          "current_source_guards_true": sum(row["matches"] for row in guards.values()),
          "current_source_guards_false": [row for row in guards.values() if not row["matches"]],
          "statuses": dict(statuses), "weighted_statuses": dict(weighted),
          "all_new_artifact_hashes_and_references_match": True,
          "all_raw_sha_counts_and_descriptors_match": True,
          "all_parent_artifacts_reparsed_by_post_audit": False,
          "compiler_matching_independently_repeated": False,
          "source_reprepare_run": False, "target_executed": False, "first_stage_complete": False}
(root / "audit.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
