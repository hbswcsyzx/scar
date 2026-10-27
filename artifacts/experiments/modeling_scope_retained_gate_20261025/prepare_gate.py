"""Prepare fixed small-metadata inputs/freeze only; never open invocation rows."""
import gzip
import hashlib
import io
import json
import sys
from pathlib import Path

from scar.analysis.modeling_scope import InputArtifact, InputCatalog, InputBudgets, InputResolver
from scar.ir.modeling_scope import Encoding
from scar.ir.record_codec import encode
from scar.store.scope_partitions import ScopeBudgets

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[2]
LIMIT = 32_000_000
READS = {}

def receipt(path, raw):
    return {"path": str(path.resolve()), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

def read(path):
    path = Path(path)
    if not path.is_file() or path.is_symlink() or path.stat().st_size > LIMIT:
        raise ValueError("small metadata path/size bound: " + str(path))
    raw = path.read_bytes()
    READS[str(path.resolve())] = receipt(path, raw)
    return raw

def document(path):
    return json.loads(read(path))

def input_artifact(path, encoding=Encoding.JSON):
    raw = read(path)
    return InputArtifact(str(Path(path).resolve()), hashlib.sha256(raw).hexdigest(), len(raw), encoding)

def record_reference(ref, root):
    path = Path(ref["uri"]) if ref["external"] else root / ref["uri"]
    raw = read(path)
    if path.suffix == ".gz":
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
            decoded = stream.read(LIMIT + 1)
    else:
        decoded = raw
    if (len(decoded) > LIMIT or len(raw) != ref["physical_bytes"]
            or hashlib.sha256(raw).hexdigest() != ref["physical_sha256"]
            or len(decoded) != ref["decoded_bytes"]
            or hashlib.sha256(decoded).hexdigest() != ref["decoded_sha256"]):
        raise ValueError("small component receipt mismatch")
    return path, json.loads(decoded)

def write_fresh(name, value):
    with (BASE / name).open("x") as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")

def main():
    source_report = ROOT / "artifacts/experiments/first_stage_source_revision_current_20261025/result/connections/source/report.json"
    report = document(source_report)
    inventory = Path(report["inventory"]["path"])
    inventory_bytes = read(inventory)
    expected = {"path": str(inventory.resolve()), "raw_sha256": hashlib.sha256(inventory_bytes).hexdigest(),
                "raw_bytes": len(inventory_bytes), "decoded_bytes": len(inventory_bytes)}
    if report["inventory"] != expected:
        raise ValueError("source report/current inventory receipt mismatch")
    inventory_doc = json.loads(inventory_bytes)
    header_path, header = record_reference(inventory_doc["components"]["header"], inventory.parent)
    publication_path, _ = record_reference(inventory_doc["components"]["publication"], inventory.parent)
    definitions = header["value"]["summary"]["definitions"]
    coordinates = Path(report["coordinate_binding"]["uri"])
    coordinate_bytes = read(coordinates)
    if (len(coordinate_bytes) != report["coordinate_binding"]["size_bytes"]
            or hashlib.sha256(coordinate_bytes).hexdigest() != report["coordinate_binding"]["sha256"]):
        raise ValueError("coordinate binding mismatch")
    coordinate_doc = json.loads(coordinate_bytes)
    if coordinate_doc["run"] != report["run"]:
        raise ValueError("source/coordinate Run mismatch")
    native = ROOT / "artifacts/experiments/first_stage_joined_physical_20261023/result/native/bundle-partitions/manifest.json"
    native_doc = document(native)
    capture_path = native.parents[2] / "capture-model.json"
    capture = document(capture_path)
    if (capture["run"] != report["run"] or capture["native_bundle_storage"]["manifest"] != str(native)
            or capture["coordinate_binding"]["sha256"] != report["coordinate_binding"]["sha256"]):
        raise ValueError("capture-model/native/current coordinates membership mismatch")
    stored_native = next(r for r in capture["outputs"] if r["path"] == str(native))
    if (stored_native["stored_sha256"], stored_native["stored_bytes"]) != (
            READS[str(native)]["sha256"], READS[str(native)]["bytes"]):
        raise ValueError("capture-model native manifest receipt mismatch")
    # Discover existing OS transport metadata by its public schema and exact
    # Run. No resource record, chunk, provider raw or monolithic OS dump opens.
    matches, candidates = [], []
    paths = sorted((ROOT / "artifacts/experiments").glob("*os*/**/manifest.json"))
    if len(paths) > 128:
        raise ValueError("OS metadata discovery budget exceeded")
    for path in paths:
        if path.stat().st_size > LIMIT:
            continue
        value = document(path)
        candidates.append({"path": str(path), "schema": value.get("schema"), "same_run": value.get("run") == report["run"]})
        if value.get("schema") == "scar.partitioned-os-resource-fragment" and value.get("run") == report["run"]:
            if value.get("schema_version") != 1 or value.get("status") != "PUBLISHED":
                raise ValueError("unsupported OS transport metadata")
            matches.append((path, value))
    if len(matches) != 1:
        raise ValueError("OS schema/Run discovery is absent or ambiguous")
    os_path, os_doc = matches[0]
    contract = ROOT / "docs/FIRST_STAGE_MODEL_CONTRACT.md"
    catalog = InputCatalog(input_artifact(coordinates), input_artifact(inventory), input_artifact(source_report),
        input_artifact(contract, Encoding.TEXT), input_artifact(native), input_artifact(os_path), None)
    declaration = report["invocations"]
    if set(declaration) != {"path", "rows", "raw_sha256", "raw_bytes", "compressed_bytes"}:
        raise ValueError("current public invocation descriptor is not exact five-field profile")
    invocation = source_report.parent / declaration["path"]
    stat = invocation.stat()  # stat only: do not open the19.6MB compressed stream.
    if stat.st_size != declaration["compressed_bytes"] or declaration["rows"] != report["summary"]["invocations"]:
        raise ValueError("invocation declaration/stat mismatch")
    in_limits = InputBudgets(max_seconds=1800)
    out_limits = ScopeBudgets(max_decoded_bytes=8_000_000_000, max_seconds=1800)
    if stat.st_size > in_limits.max_calls_stored_bytes or declaration["raw_bytes"] > in_limits.max_calls_decoded_bytes:
        raise ValueError("invocation declaration exceeds prepared budget")
    # The constructor is a metadata/header/stat-only preflight. rows() is never
    # called here; native/OS chunks and source shards are not visited.
    resolver = InputResolver(catalog, budgets=in_limits)
    scope = resolver.plan_scope()
    if resolver.source_count != definitions:
        raise ValueError("source definition header denominator mismatch")
    catalog_document = {"schema": "scar.modeling-scope-input-catalog", "schema_version": 1, "catalog": encode(catalog)}
    write_fresh("catalog.json", catalog_document)
    write_fresh("metadata-preflight.json", {"schema": "scar.scope-retained-metadata-preflight", "schema_version": 1,
        "status": "PREPARED_NO_MEMBER_SCAN", "run": report["run"], "source_inventory": report["inventory"],
        "coordinate_binding": report["coordinate_binding"], "source_header": str(header_path),
        "source_definition_count": definitions, "source_body_statuses_separate": header["value"]["summary"]["body_statuses"],
        "source_files": inventory_doc["counts"]["source_files"], "calls": declaration,
        "dispatch_attempts": coordinate_doc["dispatch_collector_declaration"]["dispatch_attempts"],
        "native_collection_counts": {"instances": native_doc["graphs"]["evidence"]["tables"]["instances"]["records"],
            **{k: native_doc["graphs"]["values"]["tables"][k]["records"] for k in ("objects", "allocations", "regions")}},
        "os_discovery": candidates, "os_selected": str(os_path), "os_run_matches": os_doc["run"] == report["run"],
        "os_collection_counts": {k: v["records"] for k, v in os_doc["tables"].items()},
        "capture_model": str(capture_path), "small_metadata_reads": list(READS.values()),
        "source_shard_reads": 0, "invocation_row_reads": 0, "large_chunk_reads": 0, "raw_capture_reads": 0,
        "scope_id": scope.id, "scope_revision": scope.revision,
        "note": "Only original retained members will be checked; semantic axes and six other domains remain OPEN"})
    # Freeze actual imported SCAR code. Native implementation paths are not
    # invoked by this gate and are deliberately excluded from its source lock.
    dependencies, excluded = {}, []
    for name, module in tuple(sys.modules.items()):
        file = getattr(module, "__file__", None)
        if not name.startswith("scar") or not file or not file.endswith(".py"):
            continue
        path = Path(file).resolve()
        if path.name.startswith("native") or "scalar" in path.name:
            excluded.append(str(path)); continue
        dependencies[str(path)] = receipt(path, read(path))
    selected_roots = [catalog.coordinates, catalog.source_inventory, catalog.source_invocations,
        catalog.contract, catalog.native_bundle, catalog.os_fragment]
    fixed = {r.path: READS[r.path] for r in selected_roots}
    for path in (header_path, publication_path, capture_path, BASE / "prepare_gate.py", BASE / "run_gate.py",
                 BASE / "catalog.json", BASE / "metadata-preflight.json", Path(sys.executable).resolve(), Path("/usr/bin/time"),
                 ROOT / "artifacts/experiments/modeling_scope_membership_20261025/run_retained.py"):
        fixed[str(path.resolve())] = receipt(path, read(path))
    fixed.update(dependencies)
    write_fresh("freeze.json", {"schema": "scar.scope-retained-gate-freeze", "schema_version": 1,
        "status": "PREPARED_NOT_EXECUTED", "scope_id": scope.id, "scope_revision": scope.revision,
        "files": sorted(fixed.values(), key=lambda x: x["path"]), "native_code_excluded": sorted(set(excluded)),
        "invocations_stat_only": {"path": str(invocation), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns,
            "ctime_ns": stat.st_ctime_ns, "inode": stat.st_ino, "device": stat.st_dev,
            "declared_decoded_sha256": declaration["raw_sha256"], "declared_decoded_bytes": declaration["raw_bytes"],
            "physical_sha256": "NOT_READ_BEFORE_AUTHORIZATION"},
        "input_budgets": in_limits.__dict__, "storage_budgets": out_limits.__dict__,
        "outer_wall_seconds": 2100, "heartbeat_seconds": 20,
        "fixed_attempt_directory": str(BASE / "attempt01"), "fixed_output_directory": str(BASE / "attempt01/ledger"),
        "all_source_definitions_expected_from_header": definitions, "all_source_invocations_expected_from_report": declaration["rows"],
        "producer_scope": "source/call metadata membership only; original graph facts stay authoritative"})
    print(json.dumps({"status": "PREPARED_NOT_RUN", "catalog": str(BASE / "catalog.json"), "freeze": str(BASE / "freeze.json"),
        "definitions": definitions, "calls": declaration["rows"], "os": str(os_path), "native_chunks_read": 0}, sort_keys=True))

if __name__ == "__main__":
    main()
