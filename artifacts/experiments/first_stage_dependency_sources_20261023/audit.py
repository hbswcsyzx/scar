"""Independent stdlib-only hash/count/reference audit; never prepare/compile."""
import base64
from collections import Counter
import gzip
import hashlib
from io import BytesIO, TextIOWrapper
import json
from pathlib import Path
import tokenize


def sha(payload):
    return hashlib.sha256(payload).hexdigest()


def canonical(document):
    return json.dumps(document, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode()


def pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def read_json(payload):
    def nonfinite(value):
        raise ValueError("nonfinite JSON value: " + value)
    return json.loads(payload, object_pairs_hook=pairs, parse_constant=nonfinite)


root = Path(__file__).resolve().parent
result = root / "result"
report = read_json((result / "admissions.json").read_bytes())
assert report["schema"] == "scar.dependency-source-admissions" and report["schema_version"] == 1
assert report["first_stage_complete"] is False and report["whole_program_graph_established"] is False
expected_module_sha = (root / "module.sha256.txt").read_text().split()[0]
assert sha((root / "dependency_sources.snapshot.py").read_bytes()) == expected_module_sha
artifacts, definitions, atoms, checked_bytes = {}, {}, {}, 0
for directory in ("sources", "graphs", "providers"):
    for path in sorted((result / directory).glob("*.json.gz")):
        with gzip.open(path, "rb") as stream:
            payload = stream.read()
        digest = sha(payload)
        assert path.name == digest + ".json.gz"
        document = read_json(payload)
        assert canonical(document) == payload
        relative = str(path.relative_to(result))
        header = {"schema": document["schema"], "canonical_sha256": digest,
                  "canonical_bytes": len(payload), "compressed_bytes": path.stat().st_size}
        checked_bytes += len(payload)
        if directory in ("sources", "providers"):
            raw = base64.b64decode(document["raw_base64"], validate=True)
            assert sha(raw) == document["raw_sha256"] and len(raw) == document["raw_bytes"]
            header.update(original_uri=document["original_uri"], raw_sha256=sha(raw))
        if directory == "sources":
            encoding, _ = tokenize.detect_encoding(BytesIO(raw).readline)
            with TextIOWrapper(BytesIO(raw), encoding=encoding, newline=None) as stream:
                decoded = stream.read()
            assert decoded == document["decoded_text"]
            assert document["fingerprint"] == "sha256:" + sha(decoded.encode())
            header.update(fingerprint=document["fingerprint"], source_root=document["source_root"],
                          namespace_root=document["namespace_root"])
        if directory == "graphs":
            assert document["independent_source_replay_established"] is False
            assert document["first_stage_complete"] is False
            for field, graph in (("semantic_sha256", "semantic"),
                                 ("semantics_sha256", "semantics"), ("control_sha256", "control")):
                assert document["context"][field] == sha(canonical(document[graph]))
            assert document["context"]["namespace_root"] == document["namespace_root"]
            header.update(snapshot=document["snapshot"], context=document["context"],
                          source_root=document["source_root"],
                          source_snapshot_artifact=document["source_snapshot_artifact"])
            definitions[relative] = {row["id"]["wire"]: row for row in document["semantic"]["definitions"]}
            atoms[relative] = {row["id"]["wire"]: row["reference"] for row in document["semantic"]["source_atoms"]}
        artifacts[relative] = header
        del document, payload


def reference(artifact):
    header = artifacts[artifact["path"]]
    for field in ("schema", "canonical_sha256", "canonical_bytes", "compressed_bytes"):
        assert artifact[field] == header[field], (artifact["path"], field)
    return header


source_files = {row["path"]: row for row in report["source_files"]}
roots = {row["id"]: row for row in report["source_roots"]}
for namespace in roots.values():
    assert Path(namespace["namespace_root"]) != Path("/")
for filename, row in source_files.items():
    if row["snapshot_artifact"] is not None:
        source = reference(row["snapshot_artifact"])
        assert source["original_uri"] == filename and source["fingerprint"] == row["fingerprint"]
        assert source["raw_sha256"] == row["raw_sha256"] and source["source_root"] == row["source_root"]
    if row["source_graph_artifact"] is not None:
        graph = reference(row["source_graph_artifact"])
        reference(graph["source_snapshot_artifact"])
        assert graph["snapshot"]["path"] == filename and graph["snapshot"]["fingerprint"] == row["fingerprint"]
        assert graph["context"] == row["context"] and graph["source_root"] == row["source_root"]
    for provider in row["providers"]:
        if provider["kind"] == "INSTALLED_DISTRIBUTION":
            reference(provider["metadata_artifact"]); reference(provider["record_artifact"])

raw_groups, codes, metadata, raw_entries, raw_exits = Counter(), {}, [], 0, 0
for recorded in report["trace_files"]:
    logical = Path(recorded["path"])
    path = logical if logical.exists() else Path(str(logical) + ".gz")
    opener = gzip.open if path.suffix == ".gz" else open
    digest, size, lines = hashlib.sha256(), 0, 0
    with opener(path, "rb") as stream:
        if recorded["family"] == "meta":
            payload = stream.read()
            digest.update(payload); size = len(payload); lines = len(payload.splitlines())
            row = read_json(payload)
            assert row["project_root"] == report["program_root"]
            metadata.append(row)
        else:
            for line in stream:
                digest.update(line); size += len(line); lines += 1
                row = read_json(line)
                if recorded["family"] == "codes":
                    codes[recorded["process_id"], row["key"]] = row
                elif recorded["family"] == "events":
                    if row["kind"] == "call_enter":
                        raw_entries += 1; raw_groups[row["process_id"], row["code"]] += 1
                    elif row["kind"] == "call_exit":
                        raw_exits += 1
                    else:
                        raise AssertionError("unknown raw event kind")
    assert digest.hexdigest() == recorded["raw_sha256"]
    assert size == recorded["raw_bytes"] and lines == recorded["lines"]
assert metadata == report["collection_metadata"]
admitted = {(row["process_id"], row["code"]): row for row in report["admissions"]}
assert len(admitted) == len(report["admissions"]) == len(raw_groups)
assert set(admitted) == set(raw_groups)
statuses, weighted, code_links, weighted_links = Counter(), Counter(), Counter(), Counter()
for key, count in raw_groups.items():
    row = admitted[key]
    assert row["entered_invocations"] == count
    assert row["captured_code"] == codes.get(key)
    statuses[row["status"]] += 1; weighted[row["status"]] += count
    link = row["code_source_link"]
    if link is None:
        continue
    code_links[link["status"]] += 1; weighted_links[link["status"]] += count
    assert link["code"] == row["code"]
    if link["snapshot"] is not None:
        source = source_files[row["source_file"]]
        if row["status"] == "SOURCE_VERIFIED":
            assert link["snapshot"]["path"] == source["path"]
            assert link["snapshot"]["fingerprint"] == source["fingerprint"]
        if link["definition"] is not None and source["source_graph_artifact"] is not None:
            graph = source["source_graph_artifact"]["path"]
            definition = definitions[graph][link["definition"]["wire"]]
            assert link["source"]["atom_id"]["wire"] in {item["wire"] for item in definition["source_atoms"]}
            assert atoms[graph][link["source"]["atom_id"]["wire"]] == link["source"]
assert dict(statuses) == report["summary"]["statuses"]
assert dict(weighted) == report["summary"]["weighted_statuses"]
assert sum(raw_groups.values()) == raw_entries == report["summary"]["entered_invocations"]
assert raw_entries == sum(meta["invocations"] for meta in metadata)
assert len(codes) == sum(meta["codes"] for meta in metadata)
summary = {"schema": "scar.dependency-source-audit", "schema_version": 1,
           "raw_entries": raw_entries, "raw_exits": raw_exits, "raw_codes": len(codes),
           "entered_code_groups": len(raw_groups), "statuses": dict(statuses),
           "weighted_statuses": dict(weighted), "code_source_link_statuses": dict(code_links),
           "weighted_code_source_link_statuses": dict(weighted_links),
           "artifact_files_checked": len(artifacts), "artifact_canonical_bytes_checked": checked_bytes,
           "all_raw_file_hashes_and_counts_match": True,
           "all_artifact_hashes_and_references_match": True,
           "module_snapshot_sha256": expected_module_sha,
           "compiler_matches_independently_repeated": False,
           "public_source_reprepare_run": False, "target_executed": False,
           "first_stage_complete": False}
(root / "audit.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary, indent=2))
