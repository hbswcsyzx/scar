"""Root-owned one-attempt retained membership gate; --execute is never automatic."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import threading
import time
import traceback

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[2]

def raw(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False) + "\n").encode()

def read_small(path):
    path = Path(path)
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 32_000_000:
        raise ValueError("frozen small file path/size bound: " + str(path))
    return path.read_bytes()

def verify_freeze(expected):
    payload = read_small(BASE / "freeze.json")
    if hashlib.sha256(payload).hexdigest() != expected:
        raise ValueError("root-approved freeze SHA mismatch")
    freeze = json.loads(payload)
    for row in freeze["files"]:
        data = read_small(row["path"])
        if len(data) != row["bytes"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise ValueError("frozen source/root changed: " + row["path"])
    row = freeze["invocations_stat_only"]
    stat = Path(row["path"]).stat()  # No invocation bytes before worker scan.
    if (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino, stat.st_dev) != (
            row["size"], row["mtime_ns"], row["ctime_ns"], row["inode"], row["device"]):
        raise ValueError("retained invocation file changed since metadata preflight")
    return freeze

def worker(expected, attempt):
    started = time.monotonic()
    lock, stopped = threading.Lock(), threading.Event()
    state = {"phase": "FREEZE_REVIEW", "source_members": 0, "call_members": 0}
    log = (attempt / "progress.jsonl").open("x")
    resolver = None
    def event(kind, **extra):
        with lock:
            current = dict(state)
            current.update(extra)
            current.update(event=kind, elapsed_s=time.monotonic() - started,
                self_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
            log.write(raw(current).decode()); log.flush()
            print(json.dumps(current, sort_keys=True), flush=True)
    def heartbeat():
        while not stopped.wait(20):
            event("HEARTBEAT", progress_is_not_semantic_coverage=True)
    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    def terminated(signum, _frame):
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, terminated)
    signal.signal(signal.SIGINT, terminated)
    try:
        freeze = verify_freeze(expected)
        event("STAGE_BEGIN")
        from scar.analysis.modeling_scope import InputCatalog, InputBudgets, InputResolver
        from scar.ir.modeling_scope import LedgerEntry, SubjectKind
        from scar.ir.record_codec import decode, loads
        from scar.store.scope_partitions import ScopeBudgets, ScopePartitions, publish_scope_ledger
        document = loads(read_small(BASE / "catalog.json").decode())
        if set(document) != {"schema", "schema_version", "catalog"} or document["schema"] != "scar.modeling-scope-input-catalog" or document["schema_version"] != 1:
            raise ValueError("fixed input catalog envelope differs")
        catalog = decode(InputCatalog, document["catalog"])
        state["phase"] = "ROOT_METADATA_AND_HEADER"
        event("STAGE_BEGIN")
        resolver = InputResolver(catalog, budgets=InputBudgets(**freeze["input_budgets"]))
        scope = resolver.plan_scope()
        if (scope.id, scope.revision) != (freeze["scope_id"], freeze["scope_revision"]):
            raise ValueError("current typed scope differs from approved preflight")
        samples, previous_phase = {}, None
        def rows():
            nonlocal previous_phase
            for row in resolver.rows(scope):
                review = resolver.review_receipt()
                state.update(source_members=review["source_members"], call_members=review["invocation_members"],
                    accounted_input_bytes=review["accounted_stored_plus_decoded_bytes"])
                if type(row) is LedgerEntry:
                    kind = row.obligation.subject.kind
                    phase = "SOURCE_DEFINITIONS" if kind is SubjectKind.SOURCE_DEFINITION else "SOURCE_INVOCATIONS" if kind is SubjectKind.INVOCATION else "SIX_OTHER_DOMAIN_DEBTS"
                    state["phase"] = phase
                    if phase != previous_phase:
                        previous_phase = phase; event("STAGE_BEGIN")
                    identity = row.obligation.id
                    if kind is SubjectKind.SOURCE_DEFINITION:
                        samples.setdefault("first_definition", identity); samples["last_definition"] = identity
                    elif kind is SubjectKind.INVOCATION:
                        samples.setdefault("first_call", identity); samples["last_call"] = identity
                    else:
                        samples["collection_" + row.obligation.rule_key] = identity
                    if review["members_seen"] and review["members_seen"] % 1000 == 0:
                        event("MEMBER_PROGRESS")
                yield row  # Unchanged fixed-InputResolver owned handoff.
            state["phase"] = "INDEX_AND_PUBLICATION"
            event("STAGE_BEGIN")
        limits = ScopeBudgets(**freeze["storage_budgets"])
        result = publish_scope_ledger(scope, rows(), str(attempt / "ledger"), resolver=resolver, budgets=limits)
        state["phase"] = "BOUNDED_READONLY_QUERY"
        event("STAGE_BEGIN")
        reader = ScopePartitions(result["manifest"]["path"], expected_sha256=result["manifest"]["sha256"], budgets=limits)
        queries = []
        for role, identity in samples.items():
            row = reader.query(identity, scope_revision=scope.revision)
            if row is None or reader.last_query.get("data_chunks_read") != 1 or reader.last_query.get("raw_replayed") is not False:
                raise ValueError("bounded original-member query failed")
            queries.append({"role": role, "obligation": identity, "subject_kind": row.obligation.subject.kind.value,
                "scope_revision": row.obligation.scope_revision, "query": dict(reader.last_query)})
        verify_freeze(expected)
        review = resolver.review_receipt()
        if (review["source_members"], review["invocation_members"]) != (
                freeze["all_source_definitions_expected_from_header"], freeze["all_source_invocations_expected_from_report"]):
            raise ValueError("actual member counts differ from original independent denominators")
        footer = {"schema": "scar.scope-retained-membership-gate-result", "schema_version": 1,
            "status": "PUBLISHED_MEMBERSHIP_ONLY", "whole_program_model": "OPEN", "receipt": result,
            "input_review": review, "sample_queries": queries, "queries_are_samples": True,
            "all_member_lookup_index_created": result["counts"]["members"], "self_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "wall_seconds": time.monotonic() - started, "raw_capture_reads": 0, "target_executions": 0,
            "claim": "all retained source definitions and source-invocation members indexed; semantic axes and six other domains remain OPEN"}
        with (attempt / "result.json").open("x") as output: output.write(raw(footer).decode())
        state["phase"] = "FINISHED_OPEN"
        event("STAGE_END", counts=result["counts"], aggregate="OPEN")
        return 0
    except BaseException as error:
        state["phase"] = "FAILED_RETAINED"
        failure = {"status": "FAILED_RETAINED", "exception": type(error).__name__, "message": str(error),
            "wall_seconds": time.monotonic() - started, "self_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "input_review": resolver.review_receipt() if resolver is not None else None,
            "manifest_exists": (attempt / "ledger/manifest.json").is_file(), "automatic_retry": False}
        with (attempt / "failure.json").open("x") as output: output.write(raw(failure).decode())
        event("FAILED", **failure)
        traceback.print_exc()
        return 1
    finally:
        stopped.set(); thread.join(timeout=1); log.close()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="only after root approves exact freeze and budget")
    parser.add_argument("--freeze-sha256")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--attempt", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        return worker(args.freeze_sha256, Path(args.attempt))
    if not args.execute:
        print(json.dumps({"status": "PREPARED_NOT_RUN", "catalog": str(BASE / "catalog.json"),
            "freeze": str(BASE / "freeze.json"), "attempt": str(BASE / "attempt01"),
            "requires_root_approval": True, "input_streams_opened": False}, sort_keys=True))
        return 0
    if not args.freeze_sha256:
        raise ValueError("root-approved --freeze-sha256 is required")
    freeze = verify_freeze(args.freeze_sha256)
    attempt = Path(freeze["fixed_attempt_directory"])
    if attempt != BASE / "attempt01":
        raise ValueError("attempt directory is not the fixed fresh gate")
    attempt.mkdir(exist_ok=False)
    (attempt / "BUILDING.json").write_bytes(raw({"status": "BUILDING", "freeze_sha256": args.freeze_sha256}))
    command = ["/usr/bin/time", "-v", "-o", str(attempt / "gnu-time.txt"), sys.executable, "-B",
        str(Path(__file__).resolve()), "--worker", "--attempt", str(attempt), "--freeze-sha256", args.freeze_sha256]
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1")
    started = time.monotonic()
    with (attempt / "stdout.log").open("x") as stdout, (attempt / "stderr.log").open("x") as stderr:
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=stdout, stderr=stderr, start_new_session=True)
        try:
            code = process.wait(timeout=freeze["outer_wall_seconds"])
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try: code = process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL); code = process.wait()
    footer = {"status": "EXIT0_MEMBERSHIP_OPEN" if code == 0 else "FAILED_RETAINED", "exit_code": code,
        "wall_seconds": time.monotonic() - started, "command": command, "automatic_retry": False,
        "gnu_time_scope": "GNU time -v covers worker command; worker also reports SELF peak RSS",
        "attempt": str(attempt), "progress": str(attempt / "progress.jsonl")}
    (attempt / "launch-result.json").write_bytes(raw(footer))
    print(json.dumps(footer, sort_keys=True))
    return 0 if code == 0 else 1

if __name__ == "__main__":
    raise SystemExit(main())
