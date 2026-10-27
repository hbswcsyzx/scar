from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False).encode("utf-8")


class IndexedJsonl:
    """Bounded random record lookup over a prior-receipt-bound monotonic JSONL file."""
    def __init__(self, path, *, expected_bytes, expected_lines, prior_sha256,
                 max_returned_bytes=4_000_000):
        self.path = Path(path).absolute()
        if self.path.is_symlink() or not self.path.is_file():
            raise ValueError("source must be an ordinary retained file")
        self.before = self.path.stat()
        if self.before.st_size != expected_bytes:
            raise ValueError("source stored byte count differs from prior publication receipt")
        self.expected_lines = expected_lines
        self.prior_sha256 = prior_sha256
        self.max_returned_bytes = max_returned_bytes
        self.returned_bytes = 0
        self.read_calls = 0
        self.probes = 0
        self.lines_examined = 0
        self.stream = self.path.open("rb")

    def _readline_after(self, offset):
        self.stream.seek(offset)
        if offset:
            self.stream.seek(offset - 1)
            self.read_calls += 1
            previous = self.stream.read(1)
            self.returned_bytes += len(previous)
            self.stream.seek(offset)
            if previous != b"\n":
                self.read_calls += 1
                discarded = self.stream.readline(2_000_001)
                self.returned_bytes += len(discarded)
                if len(discarded) > 2_000_000:
                    raise ValueError("one JSONL line exceeds targeted reader ceiling")
        start = self.stream.tell()
        self.read_calls += 1
        raw = self.stream.readline(2_000_001)
        self.returned_bytes += len(raw)
        if len(raw) > 2_000_000 or self.returned_bytes > self.max_returned_bytes:
            raise ValueError("bounded issue-reader byte ceiling exceeded")
        if not raw:
            return start, None, self.stream.tell()
        row = json.loads(raw.decode("utf-8"))
        if type(row) is not dict or type(row.get("index")) is not int:
            raise ValueError("record does not expose an exact integer index")
        self.lines_examined += 1
        return start, row, self.stream.tell()

    def locate(self, target):
        low_offset, low_index = 0, 0
        high_offset, high_index = self.before.st_size, self.expected_lines + 1
        for _ in range(40):
            if high_offset <= low_offset:
                break
            if high_index <= low_index:
                raise ValueError("index interval is not strictly increasing")
            fraction = (target - low_index) / (high_index - low_index)
            offset = low_offset + int(fraction * (high_offset - low_offset))
            if offset <= low_offset or offset >= high_offset:
                offset = (low_offset + high_offset) // 2
            self.probes += 1
            start, row, end = self._readline_after(offset)
            if row is None:
                high_offset = start
                continue
            index = row["index"]
            if index == target:
                return start, row, end
            if index < target:
                if index < low_index or (index == low_index and end <= low_offset):
                    raise ValueError("event index does not advance at the sampled offset")
                low_index, low_offset = index, end
            else:
                if index > high_index:
                    raise ValueError("event index does not retreat at the sampled offset")
                # Keep the sampled byte offset inside the upper record. Using
                # its line start can repeatedly rediscover the same row.
                high_index, high_offset = index, offset
        # The interval should now contain at most a small local set of rows.
        offset = low_offset
        while offset < high_offset and offset < self.before.st_size:
            start, row, end = self._readline_after(offset)
            if row is None or start >= high_offset:
                break
            if row["index"] == target:
                return start, row, end
            if row["index"] > target:
                break
            offset = end
        return None

    def consecutive(self, start_offset, *, wanted_attempts, max_index_gap):
        self.stream.seek(start_offset)
        attempts, handshakes = {}, {}
        last_index = None
        stop_index = max(wanted_attempts) + max_index_gap
        while True:
            self.read_calls += 1
            raw = self.stream.readline(2_000_001)
            self.returned_bytes += len(raw)
            if len(raw) > 2_000_000 or self.returned_bytes > self.max_returned_bytes:
                raise ValueError("bounded issue-reader byte ceiling exceeded")
            if not raw:
                break
            row = json.loads(raw.decode("utf-8"))
            if type(row) is not dict or type(row.get("index")) is not int:
                raise ValueError("record does not expose an exact integer index")
            self.lines_examined += 1
            if last_index is not None and row["index"] != last_index + 1:
                raise ValueError("retained event indices are not consecutive in the local issue range")
            last_index = row["index"]
            if row["kind"] == "CALL_ATTEMPT" and row["index"] in wanted_attempts:
                attempts[row["index"]] = row
            elif row["kind"] == "ENTRY_HANDSHAKE" and row.get("attempt_index") in wanted_attempts:
                handshakes[row["attempt_index"]] = row
            if len(attempts) == len(wanted_attempts) and len(handshakes) == len(wanted_attempts):
                break
            if row["index"] >= stop_index:
                break
        return attempts, handshakes

    def close_and_check(self):
        self.stream.close()
        after = self.path.stat()
        stable = (self.before.st_dev, self.before.st_ino, self.before.st_size,
            self.before.st_mtime_ns, self.before.st_ctime_ns) == (after.st_dev, after.st_ino,
            after.st_size, after.st_mtime_ns, after.st_ctime_ns)
        if not stable:
            raise ValueError("raw event artifact changed during bounded extraction")
        return {"path": str(self.path), "prior_receipt_sha256": self.prior_sha256,
            "stored_bytes_from_prior_receipt": self.before.st_size,
            "expected_lines": self.expected_lines, "bounded_returned_bytes": self.returned_bytes,
            "read_calls": self.read_calls, "index_probes": self.probes,
            "lines_examined": self.lines_examined, "whole_file_sha_rehashed": False,
            "stat_stable_before_after": True}


def slim_attempt(row):
    dispatch, site = row["dispatch"], row["site"]
    return {"index": row["index"], "kind": row["kind"], "process_id": row["process_id"],
        "thread_id": row["thread_id"], "invocation_id": row["invocation_id"],
        "frame_index": row["frame_index"], "hook_epoch": row["hook_epoch"],
        "site": {"code": site.get("code"), "offset": site.get("offset"),
            "opname": site.get("opname"), "position": site.get("position")},
        "dispatch": {"kind": dispatch.get("kind"), "code": dispatch.get("code"),
            "layout": dispatch.get("layout")}, "arg0_present": row.get("arg0") is not None,
        "arg0_missing": row.get("arg0_missing")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--result", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--expected-manifest-sha256", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    result = json.loads(Path(args.result).read_text())
    manifest_path = Path(args.manifest)
    manifest_raw = manifest_path.read_bytes()
    if hashlib.sha256(manifest_raw).hexdigest() != args.expected_manifest_sha256:
        raise ValueError("retained candidate manifest SHA differs")
    manifest = json.loads(manifest_raw.decode("utf-8"))
    if result.get("manifest_sha256") != args.expected_manifest_sha256:
        raise ValueError("result does not bind the requested candidate manifest")
    if result.get("status") != "ALL_DIRECT_CANDIDATES_EXAMINED_WITH_OPEN":
        raise ValueError("retained full-candidate result is not the expected completed scope")
    issues = [issue for window in manifest["windows"] for issue in window["candidate_issues"]]
    if len(issues) != 11 or len({issue["attempt_index"] for issue in issues}) != 11:
        raise ValueError("expected exact eleven distinct retained issues")
    operand_ref, = [row for row in manifest["shared_inputs"]["trace_file_receipts"]["operand_files"]
        if row["family"] == "operands" and row["process_id"] == 272038]
    frame_ref, = [row for row in manifest["shared_inputs"]["trace_file_receipts"]["frame_files"]
        if row["family"] == "events" and row["process_id"] == 272038]
    issue_indices = sorted(issue["attempt_index"] for issue in issues)
    operand_reader = IndexedJsonl(operand_ref["path"], expected_bytes=operand_ref["raw_bytes"],
        expected_lines=operand_ref["lines"], prior_sha256=operand_ref["raw_sha256"])
    first, = [issue_indices[0]]
    first_record = operand_reader.locate(first)
    if first_record is None:
        raise ValueError("first issue attempt index is absent from retained operands")
    attempts, handshakes = operand_reader.consecutive(first_record[0],
        wanted_attempts=set(issue_indices), max_index_gap=1024)
    if set(attempts) != set(issue_indices) or set(handshakes) != set(issue_indices):
        raise ValueError("bounded local issue range did not include all attempts and handshakes")
    frame_reader = IndexedJsonl(frame_ref["path"], expected_bytes=frame_ref["raw_bytes"],
        expected_lines=frame_ref["lines"], prior_sha256=frame_ref["raw_sha256"])
    frame_entries = {}
    for entry_index in sorted({row["entry_index"] for row in handshakes.values()}):
        found = frame_reader.locate(entry_index)
        if found is None:
            raise ValueError("handshake entry index is absent from retained frame events")
        frame_entries[entry_index] = found[1]
    issue_by_attempt = {issue["attempt_index"]: issue for issue in issues}
    decoded = []
    for issue_index in issue_indices:
        attempt_row, handshake = attempts[issue_index], handshakes[issue_index]
        attempt = slim_attempt(attempt_row)
        entry_row = frame_entries[handshake["entry_index"]]
        if (attempt_row.get("kind") != "CALL_ATTEMPT" or attempt_row.get("index") != issue_index
                or entry_row.get("kind") != "call_enter"
                or entry_row.get("index") != handshake["entry_index"]
                or entry_row.get("invocation_id") != handshake.get("invocation_id")
                or entry_row.get("code") != attempt["dispatch"].get("code")):
            raise ValueError("attempt/handshake/frame/dispatch code association differs")
        issue = issue_by_attempt[issue_index]
        decoded.append({"candidate_ordinal": issue["candidate_ordinal"],
            "issue_category": issue["category"], "issue_detail": issue["detail"],
            "attempt": attempt, "handshake": {"index": handshake["index"],
                "attempt_index": handshake["attempt_index"], "invocation_id": handshake["invocation_id"],
                "entry_index": handshake["entry_index"]},
            "entry": {"index": entry_row["index"], "invocation_id": entry_row["invocation_id"],
                "code": entry_row["code"], "caller_invocation_id": entry_row.get("caller_invocation_id"),
                "path_complete": entry_row.get("path_complete"),
                "path_length": len(entry_row.get("path", ()))}})
    receipts = {"operand": operand_reader.close_and_check(), "frame": frame_reader.close_and_check()}
    payload = {"schema": "scar.retained-source-call-abi11-targeted-evidence",
        "schema_version": 1, "status": "PASS_TARGETED_EVENT_ROWS_ONLY",
        "manifest_sha256": args.expected_manifest_sha256,
        "prior_full_operand_raw_sha256": operand_ref["raw_sha256"],
        "prior_full_frame_raw_sha256": frame_ref["raw_sha256"],
        "issue_count": len(issues), "issues": decoded, "read_receipts": receipts,
        "whole_trace_replay": False, "whole_operand_sha_recomputed": False,
        "whole_frame_sha_recomputed": False, "argument_value_payloads_saved": False,
        "raw_arg0_reference_strings_saved": False}
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(canonical(payload) + b"\n")
    print(json.dumps({"status": payload["status"], "issue_count": len(decoded),
        "operand_returned_bytes": receipts["operand"]["bounded_returned_bytes"],
        "frame_returned_bytes": receipts["frame"]["bounded_returned_bytes"],
        "output": str(out), "output_sha256": hashlib.sha256(out.read_bytes()).hexdigest()},
        sort_keys=True))


if __name__ == "__main__":
    main()
