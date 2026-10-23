"""Classify actual call attempts, without replaying SCAR or executing a target.

This is an evidence audit, not a callable resolution or argument-binding proof.
OTHER deliberately remains OTHER: it includes several Python/native protocols.
"""
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import time


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
EXPERIMENTS = HERE.parent
STARTED = time.perf_counter()
MAX_BYTES = 300_000_000


def pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def parse(raw):
    def invalid(value):
        raise ValueError("non-finite JSON value")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def receipt(path):
    payload = path.read_bytes()
    return {"path": str(path), "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest()}


def inspect(capture):
    manifests = list((capture / "trace").glob("execution-evidence.*.json"))
    assert len(manifests) == 1
    native = parse(manifests[0].read_bytes())
    assert native["status"] == "CLOSED" and native["failures"] == []
    pid = native["pid"]
    index_path = capture / "archive-index.json"
    archive = parse(index_path.read_bytes()) if index_path.exists() else None
    if archive is not None:
        assert archive["verified_roundtrip"] is True
    inputs = [receipt(manifests[0])]
    if archive is not None:
        inputs.append(receipt(index_path))

    def rows(family):
        suffix = ".json" if family == "operand-meta" else ".jsonl"
        logical = capture / "trace" / ("call-" + family + "." + str(pid) + suffix)
        entry = None
        local = logical
        if archive is not None:
            matches = [row for row in archive["files"] if row["logical_path"] == str(logical)]
            assert len(matches) == 1
            entry = matches[0]
            local = Path(entry["actual_path"])
            assert local.is_relative_to(capture) and not local.is_symlink()
            actual = receipt(local)
            assert actual["sha256"] == entry["gzip_sha256"]
            assert actual["bytes"] == entry["compressed_bytes"]
        assert local.is_file() and not local.is_symlink()
        opener = gzip.open if entry is not None else open
        digest, size, count = hashlib.sha256(), 0, 0
        with opener(local, "rb") as stream:
            if family == "operand-meta":
                raw = stream.read(2_000_001)
                assert len(raw) <= 2_000_000
                digest.update(raw)
                size, count = len(raw), 1
                yield parse(raw)
            else:
                for raw in stream:
                    size += len(raw)
                    count += 1
                    assert size <= MAX_BYTES and count <= 2_000_000 and len(raw) <= 2_000_000
                    assert raw.endswith(b"\n")
                    digest.update(raw)
                    yield parse(raw)
        raw_receipt = {"logical_path": str(logical), "local_path": str(local),
                       "raw_sha256": digest.hexdigest(), "raw_bytes": size, "lines_or_documents": count}
        if entry is not None:
            assert digest.hexdigest() == entry["raw_sha256"] and size == entry["raw_bytes"]
            raw_receipt["archive_entry"] = entry
        inputs.append(raw_receipt)

    metadata, = rows("operand-meta")
    assert metadata["process_id"] == pid and metadata["dropped_events"] == 0
    assert metadata["errors"] == [] and metadata["io_failed"] is False
    codes = {}
    for code in rows("codes"):
        assert code["key"] not in codes
        codes[code["key"]] = code
    declared_codes, = [row for row in metadata["base_manifest"] if row["family"] == "codes"]
    assert inputs[-1]["raw_sha256"] == declared_codes["raw_sha256"]
    assert inputs[-1]["raw_bytes"] == declared_codes["raw_bytes"]
    project_root = Path(metadata["project_root"])
    attempts, handshake_counts = {}, Counter()
    event_counts, gaps = Counter(), Counter()
    dispatch_counts, opcodes = Counter(), Counter()
    last_index = 0
    for row in rows("operands"):
        assert row["process_id"] == pid and row["index"] == last_index + 1
        last_index = row["index"]
        event_counts[row["kind"]] += 1
        if row["kind"] == "CALL_ATTEMPT":
            kind = row["dispatch"]["kind"]
            assert kind in ("EXACT_FUNCTION", "EXACT_METHOD", "OTHER", "UNAVAILABLE")
            descriptor = codes.get(row["dispatch"]["code"])
            if kind != "EXACT_FUNCTION":
                scope = "NO_CODE_IN_THIS_CALLABLE_VARIANT"
            elif descriptor is None:
                scope = "NO_RETAINED_DESCRIPTOR"
            else:
                filename = descriptor["filename"]
                scope = ("PROJECT_PATH" if Path(filename).is_absolute() and Path(filename).is_relative_to(project_root)
                         else "NON_PROJECT_PATH")
            attempts[row["index"]] = {"kind": kind, "scope": scope,
                "caller_code": row["site"]["code"], "callee_code": row["dispatch"]["code"],
                "anchor": {"index": row["index"], "invocation_id": row["invocation_id"],
                           "thread_id": row["thread_id"], "site": row["site"]}}
            dispatch_counts[kind] += 1
            opcodes[row["site"]["opname"]] += 1
        elif row["kind"] == "ENTRY_HANDSHAKE":
            assert row["attempt_index"] in attempts
            handshake_counts[row["attempt_index"]] += 1
        elif row["kind"] == "GAP":
            gaps[row.get("reason", row.get("detail", "MISSING_REASON"))] += 1
    assert last_index == metadata["events"] == metadata["event_attempts"]
    assert inputs[-1]["raw_bytes"] == metadata["bytes"]
    for kind, key in (("INSTRUCTION", "instructions"), ("CALL_ATTEMPT", "call_attempts"),
                      ("ENTRY_HANDSHAKE", "handshakes"), ("GAP", "gaps")):
        assert event_counts[kind] == metadata[key]
    counts, examples = Counter(), {}
    for index, row in attempts.items():
        number = handshake_counts[index]
        status = "UNIQUE" if number == 1 else "ABSENT" if number == 0 else "MULTIPLE"
        key = (row["kind"], row["scope"], status)
        counts[key] += 1
        examples.setdefault(key, [])
        if len(examples[key]) < 2:
            examples[key].append(row)
    return {"capture": str(capture), "pid": pid, "inputs": inputs,
        "codes": len(codes), "metadata_python": metadata["python"], "rule": metadata["rule"],
        "event_counts": dict(event_counts), "dispatch_counts": dict(dispatch_counts),
        "attempt_opcodes": dict(opcodes), "gap_reasons": dict(gaps),
        "partitions": [{"kind": key[0], "retained_code_scope": key[1], "entry_handshake": key[2],
                        "attempts": counts[key], "examples": examples[key]} for key in sorted(counts)],
        "absent_handshake_attempts": sum(number for key, number in counts.items() if key[2] == "ABSENT"),
        "all_attempts_classified": sum(counts.values()) == len(attempts),
        "callable_implementation_or_completion_established": False,
        "argument_routes_established": False, "native_calls_inferred_from_OTHER": False}


result = {"schema": "scar.call-protocol-frontier-audit", "schema_version": 1,
    "status": "RAW_PARTITION_AUDIT_PASS", "producer": receipt(Path(__file__).resolve()),
    "revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
    "captures": [inspect(EXPERIMENTS / name) for name in (
        "first_stage_lewm_dispatch_20261023", "first_stage_lewm_physical_20261023")],
    "elapsed_s": time.perf_counter() - STARTED,
    "maxrss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    "scar_imported": False, "target_executed": False, "source_prepared": False,
    "whole_model_established": False, "first_stage_complete": False,
    "transformation_authorized": False}
with (HERE / "result.json").open("x") as out:
    json.dump(result, out, ensure_ascii=False, indent=2, sort_keys=True)
    out.write("\n")
print(json.dumps({"status": result["status"], "elapsed_s": result["elapsed_s"],
    "captures": [{"pid": row["pid"], "dispatch_counts": row["dispatch_counts"],
                  "absent_handshake_attempts": row["absent_handshake_attempts"],
                  "partitions": [{key: value for key, value in part.items() if key != "examples"}
                                 for part in row["partitions"]]} for row in result["captures"]]}, sort_keys=True))
