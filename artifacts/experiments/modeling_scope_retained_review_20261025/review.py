"""Read-only terminal delivery audit; bounded public queries, no producer scan."""
from collections import Counter
import gzip
import hashlib
import io
import json
from pathlib import Path
import resource
import time
import traceback

from scar.ir.modeling_scope import (
    CoverageSubject, Domain, Encoding, RecordLocator, RetainedArtifact,
    SubjectKind, obligation_id, scope_revision_id,
)
from scar.ir.modeling_scope_codec import from_dict
from scar.ir.program.providers import ProviderArtifact
from scar.ir.record_codec import encode
from scar.store.scope_partitions import ScopeBudgets, ScopePartitions


BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[2]
GATE = ROOT / "artifacts/experiments/modeling_scope_retained_gate_20261025"
START = time.monotonic()
READS = Counter()
QUERY_CHUNKS = []
REPORT = {
    "status": "IN_PROGRESS", "scope": "retained membership terminal delivery only",
    "raw_reads": 0, "invocation_stream_reads": 0, "target_executions": 0,
    "producer_runs": 0, "full_ledger_decoded": False,
}


def require(ok, message):
    if not ok:
        raise ValueError(message)
    require_wall()


def require_wall():
    if time.monotonic() - START > 180:
        raise ValueError("independent review 180 second budget exceeded")


def read(path, category="small_metadata", max_bytes=4_000_000):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), "non-regular/symlink input")
    require(path.stat().st_size <= max_bytes, "independent review input bound exceeded")
    raw = path.read_bytes()
    READS[category] += len(raw)
    return raw


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def doc(path):
    return json.loads(read(path))


def retained(desc, root, category):
    path = Path(desc["uri"]) if desc["external"] else root / desc["uri"]
    raw = read(path, category, max_bytes=32_000_000)
    require((len(raw), sha(raw)) == (desc["physical_bytes"], desc["physical_sha256"]),
            "source metadata stored receipt mismatch")
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
        decoded = stream.read(32_000_001)
    require((len(decoded), sha(decoded)) == (desc["decoded_bytes"], desc["decoded_sha256"]),
            "source metadata decoded receipt mismatch")
    READS[category + "_decoded"] += len(decoded)
    return path.absolute(), json.loads(decoded)


class MeteredPartitions(ScopePartitions):
    def _chunk(self, descriptor):
        QUERY_CHUNKS.append({"uri": descriptor["uri"], "stored_bytes": descriptor["stored_bytes"],
                             "decoded_bytes": descriptor["decoded_bytes"]})
        return super()._chunk(descriptor)


def query(reader, identity, role, expected_subject=None):
    before = len(QUERY_CHUNKS)
    row = reader.query(identity, scope_revision=reader.scope.revision)
    require(row is not None, "sample missing from public query")
    require(reader.last_query["index_chunks_read"] == reader.last_query["data_chunks_read"] == 1
            and reader.last_query["raw_replayed"] is False, "query escaped one index/one data bound")
    require(row.obligation.id == obligation_id(row.obligation.subject, row.obligation.rule_key)
            and row.obligation.scope_revision == reader.scope.revision
            and row.obligation.subject.scope_id == reader.scope.id,
            "sample exact subject/scope/obligation mismatch")
    require(row.assessment.scope_revision == reader.scope.revision
            and row.assessment.obligation == identity, "sample assessment scope mismatch")
    if expected_subject is not None:
        require(row.obligation.subject == expected_subject, "sample original subject differs")
    require(all(result.status.value == ("SATISFIED" if axis.axis.value == "STRUCTURAL_ATTRIBUTION"
                and row.member is not None else "OPEN")
                for axis in row.assessment.axes for result in axis.results),
            "membership-only query silently closes semantic axes")
    return row, {"role": role, "obligation": identity, "subject": encode(row.obligation.subject),
                 "scope_revision": row.obligation.scope_revision,
                 "retained_gaps": encode(row.assessment.retained_gaps),
                 "query": dict(reader.last_query), "chunks": QUERY_CHUNKS[before:]}


def main():
    result = doc(GATE / "attempt01/result.json")
    launch = doc(GATE / "attempt01/launch-result.json")
    freeze = doc(GATE / "freeze.json")
    catalog = doc(GATE / "catalog.json")["catalog"]
    require(launch["exit_code"] == 0 and result["status"] == "PUBLISHED_MEMBERSHIP_ONLY"
            and result["whole_program_model"] == "OPEN" and result["raw_capture_reads"] == 0
            and result["target_executions"] == 0, "terminal status is not membership-only OPEN")
    root_receipt = result["receipt"]["manifest"]
    manifest_path = Path(root_receipt["path"])
    manifest_raw = read(manifest_path)
    require((len(manifest_raw), sha(manifest_raw)) == (root_receipt["bytes"], root_receipt["sha256"]),
            "result exact manifest root receipt mismatch")
    m = json.loads(manifest_raw)
    require(m["schema_version"] == 2 and m["scope"]["schema_version"] == 2,
            "transport/record schema must both be version 2")
    limits = ScopeBudgets(**freeze["storage_budgets"])
    reader = MeteredPartitions(manifest_path, expected_sha256=root_receipt["sha256"], budgets=limits)
    READS["public_reader_manifest"] += len(manifest_raw)
    scope = reader.scope
    require(scope.revision == scope_revision_id(scope) == result["receipt"]["scope_revision"]
            == freeze["scope_revision"], "ScopeRevision full typed digest mismatch")
    require(m["verification"]["aggregate"] == result["receipt"]["aggregate"] == "OPEN"
            and m["verification"]["publication_is_program_completeness"] is False,
            "publication falsely claims whole-program completeness")
    # ScopeRevision recursively includes all six catalog roots and four sources.
    bound = {}
    def collect(value):
        if type(value) is dict:
            if set(("uri", "sha256", "size_bytes")) <= set(value):
                bound[value["uri"]] = value
            for child in value.values(): collect(child)
        elif type(value) is list:
            for child in value: collect(child)
    collect(m["scope"])
    roots = {}
    root_documents = {}
    for name, ref in catalog.items():
        if ref is None:
            continue
        require(ref["path"] in bound and (bound[ref["path"]]["sha256"], bound[ref["path"]]["size_bytes"])
                == (ref["physical_sha256"], ref["physical_bytes"]), "catalog root absent from ScopeRevision")
        raw = read(ref["path"])
        require((len(raw), sha(raw)) == (ref["physical_bytes"], ref["physical_sha256"]),
                "catalog root physical receipt mismatch")
        roots[name] = {"path": ref["path"], "bytes": len(raw), "sha256": sha(raw)}
        if ref["encoding"] == "JSON": root_documents[name] = json.loads(raw)
    require(len(scope.policy_sources) == len(m["producer"]) == 4, "producer source count mismatch")
    for ref, producer in zip(scope.policy_sources, m["producer"]):
        original = ref.artifact.original
        require((original.uri, original.size_bytes, original.sha256) ==
                (producer["path"], producer["bytes"], producer["sha256"]), "producer root/scope mismatch")
        raw = read(producer["path"], "producer_source")
        require((len(raw), sha(raw)) == (producer["bytes"], producer["sha256"]), "producer source changed")
    # Verify every stored chunk without decoding the 4.27 GB ledger.
    descriptors = m["entries"] + m["index"]
    expected_paths = {d["uri"] for d in descriptors}
    actual_paths = {str(p.relative_to(manifest_path.parent)) for family in ("entries", "index")
                    for p in (manifest_path.parent / family).iterdir()}
    require(expected_paths == actual_paths and len(descriptors) == 637, "saved chunk inventory differs")
    verified = hashlib.sha256()
    for d in descriptors:
        raw = read(manifest_path.parent / d["uri"], "all_stored_chunks", max_bytes=8_000_000)
        require((len(raw), sha(raw)) == (d["stored_bytes"], d["stored_sha256"]),
                "saved chunk stored bytes/SHA mismatch: " + d["uri"])
        verified.update((d["uri"] + " " + str(len(raw)) + " " + sha(raw) + "\n").encode())
    require(m["totals"] == result["receipt"]["totals"] and READS["all_stored_chunks"] == m["totals"]["stored_bytes"],
            "stored chunk totals mismatch")
    denoms = [from_dict(d) for d in m["denominators"]]
    denom_by_domain = {d.domain.value: d for d in denoms}
    for name, count in (("SOURCE_DEFINITIONS", 2217), ("OBSERVED_PYTHON_CALLS", 100438)):
        d = denom_by_domain[name]
        require(d.declared_count == d.enumerated_count == count and d.enumeration.value == "ENUMERATED"
                and d.cursor is None and d.membership_sha256 is not None, "enumerated denominator mismatch")
    debts = [d for d in denoms if d.domain.value not in ("SOURCE_DEFINITIONS", "OBSERVED_PYTHON_CALLS")]
    require(len(debts) == 6 and all(d.enumerated_count == 0 and d.enumeration.value == "DECLARED"
            and d.cursor is not None and d.membership_sha256 is None and d.gaps for d in debts)
            and all(d.observation_coverage.value == "UNKNOWN" for d in denoms), "six domain debts were lost")
    require(m["counts"] == result["receipt"]["counts"] and m["counts"]["members"] == 102655
            and m["counts"]["obligations"] == sum(d["rows"] for d in m["entries"])
            == sum(d["rows"] for d in m["index"]) == 102661, "declared ledger count conservation failed")
    inventory = root_documents["source_inventory"]
    inventory_root = Path(catalog["source_inventory"]["path"]).parent
    _, header = retained(inventory["components"]["header"], inventory_root, "source_header")
    source_count = header["value"]["summary"]["definitions"]
    call_report = root_documents["source_invocations"]
    require(source_count == 2217 and call_report["invocations"]["rows"]
            == call_report["summary"]["invocations"] == 100438, "independent retained root denominators differ")
    inv = catalog["source_inventory"]
    require(call_report["inventory"] == {"path": inv["path"], "raw_sha256": inv["physical_sha256"],
            "raw_bytes": inv["physical_bytes"], "decoded_bytes": inv["physical_bytes"]},
            "invocation report binds another source inventory")
    samples = []
    require(len(result["sample_queries"]) == 10, "fixed ten query IDs missing")
    for saved in result["sample_queries"]:
        row, receipt = query(reader, saved["obligation"], saved["role"])
        require(row.obligation.subject.kind.value == saved["subject_kind"]
                and saved["scope_revision"] == scope.revision, "saved query role/type/revision mismatch")
        if saved["role"].startswith("collection_"):
            domain = saved["role"].split(":")[-1]
            require(row.obligation.subject.record == denom_by_domain[domain].collection.record
                    and row.member is None, "collection debt query points to another collection")
        elif saved["role"] in ("first_call", "last_call"):
            require(row.obligation.subject.record.line == (1 if saved["role"] == "first_call" else 100438),
                    "first/last invocation sample ordinal mismatch")
            call_artifact = row.obligation.subject.record.artifact
            require(call_artifact.decoded_sha256 == call_report["invocations"]["raw_sha256"]
                    and call_artifact.decoded_bytes == call_report["invocations"]["raw_bytes"]
                    and call_artifact.original.size_bytes == call_report["invocations"]["compressed_bytes"],
                    "invocation sample original artifact declaration mismatch")
        samples.append(receipt)
    # At most two source shards: first original + first revised local shard.
    # Select by producer.rows' definition/body status branch, never function/op names.
    chosen = list(dict.fromkeys([0] + [i for i, d in enumerate(inventory["files"]) if not d["external"]]))[:2]
    source_shards, candidates = [], {}
    for fi in chosen:
        desc = inventory["files"][fi]
        path, shard = retained(desc, inventory_root, "two_source_shards")
        require(shard["file_index"] == fi and shard["schema_version"] in (1, 2), "source shard ordinal/schema mismatch")
        file = shard["file"]
        key = lambda item: json.dumps(item, sort_keys=True)
        bodies = {key(b["definition"]): (bi, b) for bi, b in enumerate(file["bodies"])}
        statuses = Counter()
        for di, definition in enumerate(file["definitions"]):
            entry = bodies.get(key(definition["id"]))
            if entry is None: continue
            bi, body = entry; status = body["status"]; statuses[status] += 1
            if status in ("LOWERED_WITH_GAPS", "UNSUPPORTED", "NOT_ATTEMPTED"):
                candidates.setdefault(status, (fi, desc, path, di, bi, body))
        source_shards.append({"file_index": fi, "path": str(path), "stored_bytes": desc["physical_bytes"],
                              "decoded_bytes": desc["decoded_bytes"], "body_statuses": dict(statuses)})
    source_checks = []
    targets = ["LOWERED_WITH_GAPS"] + (["UNSUPPORTED"] if "UNSUPPORTED" in candidates else ["NOT_ATTEMPTED"])
    for status in targets:
        if status not in candidates:
            source_checks.append({"requested_status": status, "status": "NOT_VERIFIED_WITHIN_TWO_SHARD_BUDGET"})
            continue
        fi, desc, path, di, bi, body = candidates[status]
        artifact = RetainedArtifact(ProviderArtifact(str(path), desc["physical_sha256"], desc["physical_bytes"],
                                    "scar.partitioned-file-inventory"), desc["decoded_sha256"], desc["decoded_bytes"],
                                    Encoding.GZIP_JSON if path.suffix == ".gz" else Encoding.JSON)
        subject = CoverageSubject(scope.id, SubjectKind.SOURCE_DEFINITION,
                                  RecordLocator(artifact, "#/file/definitions/" + str(di)))
        identity = obligation_id(subject, "SOURCE_CALL_MEMBERSHIP_V2:SOURCE_DEFINITIONS")
        row, receipt = query(reader, identity, "source_status_" + status, subject)
        gaps = row.assessment.retained_gaps
        expected_source = RecordLocator(artifact, "#/file/bodies/" + str(bi))
        reason = str(body.get("reason") or ("Original body status " + status))[:512]
        require(len(gaps) == 1 and gaps[0].code == "ORIGINAL_BODY_" + status
                and gaps[0].requirement_key == "SOURCE_BODY" and gaps[0].source == expected_source
                and gaps[0].reason == reason, "retained body gap differs from exact producer.rows branch")
        source_checks.append({"status": "VERIFIED_SAMPLE", "original_status": status, "file_index": fi,
                              "definition_index": di, "body_index": bi, **receipt})
    REPORT.update(status="REVIEW_PASS_WITH_OPEN_SCOPE", manifest_root=root_receipt,
        record_schema_version=2, transport_schema_version=2,
        scope_revision=scope.revision, scope_all_catalog_roots=roots, producer=m["producer"],
        terminal={"exit_code": launch["exit_code"], "status": result["status"], "aggregate": "OPEN",
                  "whole_program_model": result["whole_program_model"], "raw_capture_reads_reported": result["raw_capture_reads"],
                  "target_executions_reported": result["target_executions"], "worker_wall_seconds": result["wall_seconds"],
                  "worker_peak_rss_kib": result["self_peak_rss_kib"]},
        chunks={"verified_stored_files": len(descriptors), "entries_chunks": len(m["entries"]),
                "index_chunks": len(m["index"]), "verified_stored_bytes": READS["all_stored_chunks"],
                "manifest_declared_decoded_bytes_not_fully_rechecked": m["totals"]["decoded_bytes"],
                "verified_uri_bytes_sha256_lines_digest": verified.hexdigest(), "mismatches": 0},
        denominators=[{"domain": d.domain.value, "declared": d.declared_count, "enumerated": d.enumerated_count,
                       "enumeration": d.enumeration.value, "observation_coverage": d.observation_coverage.value,
                       "gap_codes": [g.code for g in d.gaps]} for d in denoms],
        counts=m["counts"], original_ten_public_queries=samples,
        source_shards=source_shards, source_status_checks=source_checks,
        query_cost={"calls": len(samples) + sum(x["status"] == "VERIFIED_SAMPLE" for x in source_checks),
                    "index_chunks_read": sum(x["uri"].startswith("index/") for x in QUERY_CHUNKS),
                    "data_chunks_read": sum(x["uri"].startswith("entries/") for x in QUERY_CHUNKS),
                    "stored_bytes_including_repeated_reads": sum(x["stored_bytes"] for x in QUERY_CHUNKS),
                    "decoded_bytes_including_repeated_reads": sum(x["decoded_bytes"] for x in QUERY_CHUNKS)},
        limits=["All 637 stored byte/SHA receipts checked; full decoded 4.27 GB and all row semantics not rechecked.",
                "Ten original public queries are samples, plus at most two source body-status samples.",
                "Membership publication is not complete modeling: semantic axes, observability and six other domains remain OPEN.",
                "No original invocation stream/raw capture, native/OS data chunks, source checkpoints, target or producer executed.",
                "Metered costs below cover this validation run; earlier small code/root metadata inspection is excluded."])


try:
    main()
except BaseException as error:
    REPORT.update(status="REVIEW_FAILED", exception=type(error).__name__, message=str(error), traceback=traceback.format_exc())
finally:
    REPORT.update(metered_read_bytes=dict(READS), wall_seconds=time.monotonic() - START,
                  self_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    (BASE / "receipt.json").write_text(json.dumps(REPORT, indent=2, sort_keys=True) + "\n")
print(json.dumps({k: REPORT.get(k) for k in ("status", "message", "chunks", "query_cost", "wall_seconds", "self_peak_rss_kib")}))
raise SystemExit(0 if REPORT["status"] == "REVIEW_PASS_WITH_OPEN_SCOPE" else 1)
