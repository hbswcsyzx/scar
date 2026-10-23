"""One real published-inventory index build and necessary source-locator audit."""
from collections import Counter
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import resource
import sys
import time
import traceback

from scar.analysis.inventory_partitions import InventoryPartitions
from scar.store import GraphIndex, IndexBudgets, IndexBuildError, index_inventory

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
MANIFEST = ROOT / "artifacts/experiments/first_stage_full_inventory_restored_20261023/result/manifest.json"
TAG = sys.argv[1] if len(sys.argv) > 1 else "attempt01"
if re.fullmatch(r"attempt[0-9]{2}", TAG) is None:
    raise ValueError("invalid experiment attempt tag")
START = time.perf_counter()


def save(name, value):
    with (OUT / f"{name}.{TAG}.json").open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def pointer(document, path):
    if not path.startswith("#/"):
        raise ValueError("source locator is not an original checkpoint JSON pointer")
    current = document
    for selector in path[2:].split("/"):
        selector = selector.replace("~1", "/").replace("~0", "~")
        current = current[int(selector)] if type(current) is list else current[selector]
    return current


def require(condition, message):
    if not condition:
        raise ValueError(message)


(OUT / f"pid.{TAG}.txt").write_text(str(os.getpid()) + "\n")
module_receipts = {}
for name in ("scar/store/__init__.py", "scar/store/graph_index.py",
             "scar/analysis/inventory_partitions.py", "scar/ir/program/codec.py",
             "scar/ir/program/model.py", "scar/ir/record_codec.py"):
    data = (ROOT / name).read_bytes()
    module_receipts[name] = {"sha256": sha256(data).hexdigest(), "bytes": len(data)}
save("modules", module_receipts)
print(json.dumps({"stage": "START", "pid": os.getpid(), "manifest": str(MANIFEST), "tag": TAG}), flush=True)
progress_stream = (OUT / f"progress.{TAG}.jsonl").open("x", encoding="utf-8", buffering=1)


def progress(row):
    payload = {"elapsed_seconds": time.perf_counter() - START, **row}
    progress_stream.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    if row["phase"] == "FILE_BEGIN" or row.get("bodies", 0) % 25 == 0:
        print(json.dumps(payload, sort_keys=True), flush=True)


try:
    build_started = time.perf_counter()
    report = index_inventory(MANIFEST, OUT / f"graph.{TAG}.sqlite", IndexBudgets(), progress=progress)
    build_seconds = time.perf_counter() - build_started
    save("build-report", {**report, "build_wall_seconds": build_seconds})
    print(json.dumps({"stage": "INDEX_PUBLISHED", "seconds": build_seconds,
                      "database": report["database"], "counts": report["counts"]}), flush=True)
    source = InventoryPartitions(MANIFEST, cache_entries=2)
    with GraphIndex(OUT / f"graph.{TAG}.sqlite") as index:
        integrity = [row[0] for row in index.db.execute("PRAGMA integrity_check")]
        foreign_keys = [dict(row) for row in index.db.execute("PRAGMA foreign_key_check")]
        require(integrity == ["ok"] and not foreign_keys, "SQLite integrity/FK audit failed")
        status_counts, source_bodies, source_checkpoints = Counter(), 0, 0
        for raw_file in source.iter_files():
            source_bodies += len(raw_file["bodies"])
            for body in raw_file["bodies"]:
                status_counts[body["status"]] += 1
                source_checkpoints += body["checkpoint"] is not None
        db_status = {row["status"]: row["number"] for row in index.db.execute(
            "SELECT status,COUNT(*) AS number FROM bodies GROUP BY status")}
        db_bodies = dict(index.db.execute(
            "SELECT COUNT(*) AS bodies,SUM(graph_present) AS graph_bodies,SUM(public_graph_validated) AS validated FROM bodies").fetchone())
        require(dict(status_counts) == db_status, "original source body statuses changed")
        require(source_bodies == db_bodies["bodies"] == report["counts"]["bodies"], "body denominator changed")
        require(source_checkpoints == source.manifest["counts"]["checkpoint_returns"], "checkpoint denominator changed")
        require(db_bodies["graph_bodies"] == db_bodies["validated"] == source.manifest["counts"]["graph_bodies"],
                "original graph/public-validation denominator changed")
        require(len(source.manifest["files"]) == report["counts"]["source_files"], "source denominator changed")

        def selected(entity_id):
            row = index.db.execute("SELECT e.*,n.file_index,n.body_index FROM entities e JOIN namespaces n ON n.id=e.namespace_id WHERE e.id=?",
                                   (entity_id,)).fetchone()
            partition = source.file(row["file_index"])["bodies"][row["body_index"]]
            document = source.checkpoint(partition["checkpoint"])
            qref = source.qualified_reference(row["file_index"], row["body_index"],
                kind=row["kind"], local_id=json.loads(row["local_id"]))
            return qref, document, partition["checkpoint"]

        def check_entity(answer, document, receipt):
            require(answer["artifact_receipt"] == receipt, "query artifact receipt changed")
            raw = pointer(document, answer["pointer"])
            require(raw["id"] == answer["qualified_reference"]["local_id"], "query entity pointer does not locate original ID")
            return raw

        containment_row = index.db.execute("SELECT source FROM relations WHERE kind='REGION_BLOCK' ORDER BY id LIMIT 1").fetchone()
        require(containment_row is not None, "real graph has no containment relation")
        region_ref, cp, receipt = selected(containment_row["source"])
        contained = index.region_children(region_ref, limit=1)
        edge = contained["items"][0]
        check_entity(edge["source"], cp, receipt)
        check_entity(edge["target"], cp, receipt)
        require(pointer(cp, edge["pointer"])["id"] == edge["target"]["qualified_reference"]["local_id"],
                "containment field locator mismatch")
        containment_proof = {"query": "region_children", "result": contained, "exact_original_locator_verified": True}

        repeated = index.db.execute("SELECT u.source AS value_id,COUNT(*) AS uses FROM relations u JOIN relations p ON p.target=u.source AND p.kind='VALUE_OPERATION_ORIGIN' WHERE u.kind='VALUE_USE' GROUP BY u.source HAVING COUNT(*)>1 LIMIT 1").fetchone()
        require(repeated is not None, "no real operation-produced Value with repeated Use found")
        value_ref, cp, receipt = selected(repeated["value_id"])
        producer = index.producer(value_ref)
        value = check_entity(producer["value"], cp, receipt)
        require(pointer(cp, producer["origin_pointer"]) == value["origin"], "producer origin locator mismatch")
        for relation in producer["producer"]["items"]:
            check_entity(relation["source"], cp, receipt)
            require(pointer(cp, relation["pointer"]) == relation["source"]["qualified_reference"]["local_id"],
                    "operation producer field locator mismatch")
        uses = index.ordered_uses(value_ref, limit=2)
        require(len(uses["items"]) == 2, "repeated original Uses were deduplicated")
        use_ids = []
        for use in uses["items"]:
            check_entity(use["target"], cp, receipt)
            check_entity(use["use_operation"], cp, receipt)
            require(pointer(cp, use["pointer"]) == value_ref["local_id"], "Use.value original field mismatch")
            require(use["use_value"]["qualified_reference"] == value_ref, "ordered Use lost original Value")
            use_ids.append(use["target"]["qualified_reference"]["local_id"]["wire"])
        require(len(set(use_ids)) == 2, "distinct original Use identities collapsed")
        producer_proof = {"query": "producer + ordered_uses", "producer": producer, "uses": uses,
                          "original_total_use_count": repeated["uses"], "exact_original_locators_verified": True}

        state_row = index.db.execute("SELECT source FROM relations WHERE kind='STATE_ACCESS' ORDER BY id LIMIT 1").fetchone()
        require(state_row is not None, "real graph has no StateAccess relation")
        operation_ref, cp, receipt = selected(state_row["source"])
        states = index.outgoing(operation_ref, relation="STATE_ACCESS", limit=1)
        state = states["items"][0]
        check_entity(state["source"], cp, receipt)
        check_entity(state["target"], cp, receipt)
        require(pointer(cp, state["pointer"]) == state["target"]["qualified_reference"]["local_id"],
                "StateAccess location field mismatch")
        raw_access = pointer(cp, state["pointer"].rsplit("/", 1)[0])
        require(raw_access["mode"] == state["qualifiers"]["mode"]
                and raw_access["full_overwrite"] == state["qualifiers"]["full_overwrite"],
                "StateAccess mode/overwrite semantics changed")
        before = index.outgoing(operation_ref, relation="ACCESS_BEFORE_USE", limit=1)
        before_row = before["items"][0]
        check_entity(before_row["target"], cp, receipt)
        require(pointer(cp, before_row["pointer"]) == raw_access["before"], "original before-state Use changed")
        state_proof = {"query": "StateAccess location/mode/before Use", "state": states,
                       "before": before, "exact_original_locators_verified": True}
        queries = {"containment": containment_proof, "producer_repeated_use": producer_proof,
                   "state_access": state_proof}
        save("query-proofs", queries)
        save("coverage", index.coverage())
        summary = {"status": "PASS", "index_storage_status": "PUBLISHED",
            "manifest": str(MANIFEST), "manifest_receipt": source.manifest_receipt,
            "database": report["database"], "build_wall_seconds": build_seconds,
            "total_wall_seconds": time.perf_counter() - START,
            "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "counts": report["counts"], "original_manifest_counts": source.manifest["counts"],
            "body_status_counts": db_status, "sqlite_body_counts": db_bodies,
            "sqlite_integrity": integrity, "foreign_key_violations": foreign_keys,
            "query_proofs": {key: "exact original receipt/pointer/endpoints PASS" for key in queries},
            "whole_program_graph_established": False, "all_relationships_indexed": False,
            "source_replay_performed": False, "target_executed": False,
            "transformation_authorized": False}
        save("summary", summary)
        print(json.dumps(summary, sort_keys=True), flush=True)
except Exception as error:
    failure = {"status": "FAILED", "elapsed_seconds": time.perf_counter() - START,
               "type": type(error).__name__, "message": str(error),
               "traceback": traceback.format_exc(),
               "build_report": error.report if isinstance(error, IndexBuildError) else None,
               "target_executed": False, "whole_program_graph_established": False}
    save("failure", failure)
    print(json.dumps(failure, sort_keys=True), flush=True)
    raise
finally:
    progress_stream.close()
