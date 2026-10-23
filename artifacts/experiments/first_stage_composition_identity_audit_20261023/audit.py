"""Read-only original namespace audit; no flattening or new program snapshot."""
import gzip
import hashlib
import json
from pathlib import Path
import resource
import sqlite3
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
DATABASE = HERE.parent / "first_stage_graph_index_20261023/graph.attempt01.sqlite"
CHECKPOINTS = HERE.parent / "first_stage_full_inventory_plain_20261023/checkpoints"
EXPECTED_DB = "5e9a7461b68268a630cf926d59ecfb1e7e498549d8500534f7d309fa81a32fbe"
QUERY = """WITH repeated AS (
 SELECT kind,local_id,COUNT(*) AS n FROM entities
 GROUP BY kind,local_id HAVING COUNT(*)>1)
SELECT kind,COUNT(*) AS id_groups,SUM(n) AS occurrences,MAX(n) AS max_namespaces
FROM repeated GROUP BY kind"""
start = time.perf_counter()
hasher = hashlib.sha256()
before = DATABASE.stat()
with DATABASE.open("rb") as stream:
    for block in iter(lambda: stream.read(1_048_576), b""):
        hasher.update(block)
assert hasher.hexdigest() == EXPECTED_DB
db = sqlite3.connect(DATABASE.as_uri() + "?mode=ro")
db.row_factory = sqlite3.Row
db.execute("PRAGMA query_only=ON")
db.execute("BEGIN")
counts = {"entities": db.execute("SELECT COUNT(*) FROM entities").fetchone()[0],
          "namespaces": db.execute("SELECT COUNT(*) FROM namespaces").fetchone()[0]}
assert counts == {"entities": 437228, "namespaces": 840}
repeated = [dict(row) for row in db.execute(QUERY)]
example = db.execute("SELECT kind,local_id,COUNT(*) n FROM entities GROUP BY kind,local_id "
                     "HAVING COUNT(*)>1 ORDER BY n DESC LIMIT 1").fetchone()
assert example is not None
rows = list(db.execute("SELECT e.*,n.identity,n.file_index,n.body_index FROM entities e "
    "JOIN namespaces n ON n.id=e.namespace_id WHERE e.kind=? AND e.local_id=? LIMIT 2",
    (example["kind"], example["local_id"])))
assert len(rows) == 2 and rows[0]["namespace_id"] != rows[1]["namespace_id"]
samples = []
for row in rows:
    namespace = json.loads(row["identity"])
    path = Path(namespace["artifact"]["uri"])
    assert path.is_relative_to(CHECKPOINTS) and path.is_file() and not path.is_symlink()
    assert path.stat().st_size <= 128_000_000
    physical = path.read_bytes()
    with gzip.GzipFile(fileobj=__import__("io").BytesIO(physical)) as stream:
        raw = stream.read(128_000_001)
    assert len(raw) <= 128_000_000
    assert hashlib.sha256(raw).hexdigest() == namespace["artifact"]["decoded_sha256"]
    checkpoint = json.loads(raw)
    selected = checkpoint
    for token in row["pointer"].removeprefix("#").split("/")[1:]:
        selected = selected[int(token)] if type(selected) is list else selected[token]
    assert selected["id"] == json.loads(row["local_id"])
    samples.append({"namespace": namespace, "pointer": row["pointer"],
        "file_index": row["file_index"], "body_index": row["body_index"],
        "original_record": selected, "original_root": checkpoint["graph"]["root"],
        "original_checkpoint": {"path": str(path), "stored_bytes": len(physical),
            "stored_sha256": hashlib.sha256(physical).hexdigest(), "decoded_bytes": len(raw),
            "decoded_sha256": hashlib.sha256(raw).hexdigest()}})
db.close()
after = DATABASE.stat()
assert (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) == (
    after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
result = {"schema": "scar.composition-identity-audit", "schema_version": 1,
    "status": "QUALIFIED_IDENTITY_REQUIREMENT_CONFIRMED", "database": {
        "path": str(DATABASE), "sha256": EXPECTED_DB, "bytes": after.st_size},
    "counts": counts, "sql": QUERY, "repeated_local_ids": repeated, "examples": samples,
    "same_local_id_does_not_authorize_cross_body_or_run_state_equivalence": True,
    "source_program_replayed": False, "new_program_snapshot_created": False,
    "scar_imported": False, "target_executed": False, "whole_model_established": False,
    "transformation_authorized": False, "elapsed_s": time.perf_counter() - start,
    "maxrss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    "producer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
with (HERE / "result.json").open("x") as stream:
    json.dump(result, stream, ensure_ascii=False, sort_keys=True, indent=2)
    stream.write("\n")
print(json.dumps({key: value for key, value in result.items() if key not in ("examples", "sql")}, sort_keys=True))
