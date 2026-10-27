"""Stream one capture into bounded, unattached existing work-record fragments.

All provider GPU candidates remain in the source inventory.  Only the fixed
kernel/copy/memset end contract qualifies quiescence, never success or value ready.
No ProgramGraph, ExecutionModel, queue lifetime, or logical value is invented.
"""
from __future__ import annotations

import builtins
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
import gzip
from hashlib import sha256
import io
import json
from pathlib import Path
import resource
import time

from scar.ir.execution.native_work_protocol import _make_evidence, activity_actor, make_records
from scar.ir.program.providers import ProviderArtifact
from scar.ir.record_codec import decode, encode, loads as strict_loads
from scar.ir.v2.codec import evidence_from_dict
from scar.ir.v2.evidence import EvidenceGraph
from scar.store.bundle_partitions import BundlePartitions
from scar.trace.capture_coordinates import bind_capture_coordinates
from scar.trace.native_capture_batch import _JSONStream
from scar.trace.native_import import _REVISION, _canonical_hash, _ns


def _need(test, message):
    if not test:
        raise ValueError(message)


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


@dataclass(frozen=True)
class NativeWorkBudget:
    max_input_bytes: int = 4_000_000_000  # stored + decoded, including repeats
    max_os_lines: int = 2_000_000
    max_output_io_bytes: int = 512_000_000  # write + readback stored/decoded
    max_wall_seconds: int = 600
    max_rss_kib: int = 2 * 1024 * 1024
    max_record_bytes: int = 4_000_000
    max_shard_rows: int = 256
    max_shard_decoded_bytes: int = 16_000_000

    def __post_init__(self):
        _need(all(type(v) is int and v > 0 for v in vars(self).values()), "invalid work budgets")
        _need(self.max_input_bytes <= 8_000_000_000
              and self.max_output_io_bytes <= 512_000_000
              and self.max_shard_rows <= 1000
              and self.max_shard_decoded_bytes <= 16_000_000,
              "work acquisition hard budget exceeded")


class _Budget:
    def __init__(self, limits):
        self.limits, self.started = limits, time.monotonic()
        self.input = Counter(); self.output = Counter(); self.reserved = 0

    def check(self):
        _need(time.monotonic() - self.started <= self.limits.max_wall_seconds,
              "native work whole wall budget exceeded")
        _need(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss <= self.limits.max_rss_kib,
              "native work RSS budget exceeded")

    def read(self, family, size):
        self.input[family] += size
        _need(sum(self.input.values()) + self.reserved <= self.limits.max_input_bytes,
              "native work combined stored/decoded input budget exceeded")
        self.check()

    def out(self, family, size):
        self.output[family] += size
        _need(sum(self.output.values()) <= self.limits.max_output_io_bytes,
              "native work output/readback budget exceeded")
        self.check()

    def report(self):
        return {"actual_input_reader_returned_bytes": dict(self.input),
                "actual_combined_input_bytes": sum(self.input.values()),
                "outstanding_input_reservations": self.reserved,
                "actual_output_io_bytes": dict(self.output),
                "actual_combined_output_io_bytes": sum(self.output.values()),
                "whole_elapsed_s": time.monotonic() - self.started,
                "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}


class _Counted:
    def __init__(self, stream, counter):
        self.stream, self.counter = stream, counter

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def _count(self, data):
        self.counter(len(data.encode("utf-8")) if type(data) is str else len(data))
        return data

    def read(self, *args):
        return self._count(self.stream.read(*args))

    def readline(self, *args):
        return self._count(self.stream.readline(*args))

    def readinto(self, buffer):
        n = self.stream.readinto(buffer)
        if n:
            self.counter(n)
        return n

    def __iter__(self):
        return self

    def __next__(self):
        data = self.readline()
        if not data:
            raise StopIteration
        return data

    def __enter__(self):
        self.stream.__enter__()
        return self

    def __exit__(self, *args):
        return self.stream.__exit__(*args)


@contextmanager
def _count_input_reads(budget, roots):
    """Count the real ordinary reader calls, without replacing their results.

    Public binder/partition checks are unchanged.  Capture plain bytes count as
    both stored and decoded views; gzip counts its real compressed reads and
    returned decoded bytes separately.  Scope is one synchronous acquisition.
    """
    old_builtin, old_io, old_gzip = builtins.open, io.open, gzip.open

    def selected(path):
        if not isinstance(path, (str, bytes, Path)):
            return False
        resolved = Path(path).resolve()
        return any(resolved.is_relative_to(root) for root in roots)

    def wrap_open(original):
        def opened(file, mode="r", *args, **kwargs):
            stream = original(file, mode, *args, **kwargs)
            if selected(file) and not any(char in mode for char in "wax+"):
                compressed = str(file).endswith(".gz")
                def count(n):
                    budget.read("stored", n)
                    if not compressed:
                        budget.read("decoded_plain", n)
                return _Counted(stream, count)
            return stream
        return opened

    def gz_opened(filename, mode="rb", *args, **kwargs):
        stream = old_gzip(filename, mode, *args, **kwargs)
        if selected(filename) and not any(char in mode for char in "wax+"):
            return _Counted(stream, lambda n: budget.read("decoded_gzip", n))
        return stream

    builtins.open, io.open, gzip.open = wrap_open(old_builtin), wrap_open(old_io), gz_opened
    try:
        yield
    finally:
        builtins.open, io.open, gzip.open = old_builtin, old_io, old_gzip


class _Partitions(BundlePartitions):
    def __init__(self, manifest, budget):
        self._budget = budget
        super().__init__(manifest)

    def _chunk(self, descriptor):
        # Reserve before decompressing; completed bytes are charged only after
        # the original reader has verified the whole chunk SHA/bytes/EOF.
        n = descriptor["decoded_bytes"]
        self._budget.reserved += n
        _need(sum(self._budget.input.values()) + self._budget.reserved
              <= self._budget.limits.max_input_bytes, "partition reservation exceeds input budget")
        try:
            decoded = super()._chunk(descriptor)
        except BaseException:
            # Reservation is retained as a reservation on failure, never IO.
            raise
        self._budget.reserved -= n
        self._budget.read("decoded_verified_partition", len(decoded))
        return decoded


class _DigestReader:
    def __init__(self, path, artifact):
        self.stream = gzip.open(path, "rb") if path.suffix == ".gz" else path.open("rb")
        self.artifact, self.digest, self.size = artifact, sha256(), 0

    def read(self, size):
        data = self.stream.read(size)
        self.size += len(data); self.digest.update(data)
        return data

    def finish(self):
        _need(self.read(1) == b"" and self.size == self.artifact.size_bytes
              and self.digest.hexdigest() == self.artifact.sha256,
              "complete Kineto SHA/bytes/EOF differs from ordinary coordinates")


def _gpu(category):
    return category == "kernel" or category.startswith("gpu_") or category in ("cuda_sync", "cuda_event")


def _reason(event):
    category, args = event["cat"], event.get("args", {})
    if category not in ("kernel", "gpu_memcpy", "gpu_memset"):
        return "GPU_CATEGORY_END_CONTRACT_UNSUPPORTED"
    if event.get("ph") != "X":
        return "GPU_NON_DURATION_RECORD"
    start, duration = _ns(event.get("ts")), _ns(event.get("dur"))
    if start is None or duration is None or start <= 0 or duration <= 0:
        return "GPU_VALID_POSITIVE_INTERVAL_UNAVAILABLE"
    if type(args) is not dict:
        raise ValueError("Kineto GPU args must be an object")
    actor = activity_actor(event)
    if actor is None:
        return "GPU_EXECUTION_ACTOR_UNAVAILABLE"
    device, context, stream = actor
    if type(event.get("pid")) is not int or type(event.get("tid")) is not int:
        return "GPU_DEVICE_LANE_UNAVAILABLE"
    _need(event["pid"] == device and event["tid"] == stream,
          "known GPU device/lane conflicts with its native resource fields")
    return None


def _scan_kineto(path, artifact, budget):
    reader = _DigestReader(path, artifact)
    stream = _JSONStream(reader, budget.limits.max_record_bytes)
    facts, categories, phases = {}, Counter(), Counter()
    count, keys = 0, set()
    try:
        stream.take("{")
        if stream.peek() != "}":
            while True:
                key = stream.value()
                _need(type(key) is str and key not in keys, "duplicate/nonstring Kineto root key")
                keys.add(key); stream.take(":")
                if key == "traceEvents":
                    stream.take("[")
                    if stream.peek() != "]":
                        while True:
                            event = stream.value()
                            _need(type(event) is dict and type(event.get("cat", "")) is str,
                                  "invalid Kineto event/category")
                            category = event.get("cat", "")
                            categories[category] += 1; phases[str(event.get("ph"))] += 1
                            if _gpu(category):
                                _need((event.get("ph") != "X" or (type(event.get("name")) is str and event["name"]))
                                      and type(event.get("args", {})) is dict,
                                      "invalid GPU provider event")
                                facts[count] = {"reference": "sha256:" + artifact.sha256 + f"#/traceEvents/{count}",
                                    "raw_ordinal": count, "event": event, "category": category,
                                    "frontier": _reason(event), "eeg_seen": False}
                            count += 1
                            if count % 1000 == 0:
                                budget.check()
                            if stream.peek() != ",":
                                break
                            stream.take(",")
                    stream.take("]")
                else:
                    stream.value()
                if stream.peek() != ",":
                    break
                stream.take(",")
        stream.take("}")
        _need("traceEvents" in keys and stream.peek() == "", "Kineto root/trailing bytes differ")
        reader.finish()
    finally:
        reader.stream.close()
    return facts, {"events": count, "category_counts": dict(categories), "phase_counts": dict(phases),
                   "complete_sha_verified": True, "artifact": encode(artifact)}


def _check_original(record, raw, scope, pid):
    event = raw["event"]; args = event.get("args", {}); category = raw["category"]
    _need(event.get("ph") == "X", "EEG GPU duration record joins a nonduration original")
    reference = raw["reference"]
    _need(record["id"]["value"] == scope + ":kineto:" + str(raw["raw_ordinal"])
          and record["definition"]["value"] == scope + ":symbol:" + _canonical_hash((category, event["name"], "")),
          "EEG GPU namespace/instance/definition differs from the original provider")
    physical = category in ("kernel", "gpu_memcpy", "gpu_memset")
    expected_process = pid if physical else (event.get("pid")
        if type(event.get("pid")) in (int, str) else "kineto-process-unresolved")
    _need(record["id"]["kind"] == "opinst" and record["definition"]["kind"] == "opdef"
          and record["process_id"] == expected_process and record["parent"] is None
          and record["status"] == "Observed", "EEG GPU ownership/status differs")
    start, duration = _ns(event.get("ts")), _ns(event.get("dur"))
    if start is not None and duration is not None:
        _need((record["start_ns"], record["end_ns"]) == (start, start + duration),
              "EEG GPU interval differs from fixed original provider conversion")
    else:
        _need(record["start_ns"] is None and record["end_ns"] is None,
              "EEG invents an unavailable original interval")
    metadata = record["metadata"]
    wanted = {"provider": "Kineto", "raw_reference": reference,
        "category": category, "raw_pid": event.get("pid"), "raw_tid": event.get("tid"),
        "clock_domain": "kineto", "correlation": args.get("correlation"),
        "external_id": args.get("External id"), "thread_namespace": "device lane, not OS TID",
        "raw_resource": {key: args[key] for key in ("device", "context", "stream", "bytes") if key in args}}
    # gpu_user_annotation is deliberately unsupported; the historical importer
    # assigns its native lane differently, so only raw source/category and exact
    # time/instance are checked for that retained frontier.
    if category not in ("kernel", "gpu_memcpy", "gpu_memset"):
        wanted = {key: wanted[key] for key in ("provider", "raw_reference", "category", "raw_pid", "raw_tid")}
    _need(all(metadata.get(key) == value for key, value in wanted.items()),
          "EEG GPU provider metadata differs from original source")
    if category in ("kernel", "gpu_memcpy", "gpu_memset"):
        _need(record["thread_id"] == f"kineto-device-lane:{event.get('pid')}:{event.get('tid')}",
              "EEG GPU lane was rewritten as a host thread")


def _write(path, payload, budget, *, compressed=False):
    _need(len(payload) <= budget.limits.max_shard_decoded_bytes, "work output shard exceeds decoded bound")
    data = gzip.compress(payload, mtime=0) if compressed else payload
    _need(sum(budget.output.values()) + len(data) <= budget.limits.max_output_io_bytes,
          "work output budget would be exceeded before write")
    with path.open("xb") as stream:
        stream.write(data)
    budget.out("written_stored", len(data))
    # Exactly one readback, also used for physical hash and semantic decoding.
    restored = path.read_bytes(); budget.out("readback_stored", len(restored))
    _need(restored == data, "work output bytes changed during readback")
    result = gzip.decompress(restored) if compressed else restored
    if compressed:
        budget.out("readback_decoded", len(result))
    _need(result == payload, "work output decoded bytes changed during readback")
    return {"uri": str(path), "stored_bytes": len(data), "stored_sha256": sha256(data).hexdigest(),
            "decoded_bytes": len(payload), "decoded_sha256": sha256(payload).hexdigest(),
            "compression": "gzip" if compressed else "none"}, result


def _publish(rows, out, number, coordinates, budget, callback):
    # Existing EEG codec chooses its ordinary supported schema; no source row
    # is renamed, and projection order determines the real endpoint pointers.
    ordered = sorted(rows, key=lambda item: item["record"]["id"]["wire"])
    document = {"schema": EvidenceGraph.SCHEMA, "schema_version": 6,
        "instances": [item["record"] for item in ordered], "observations": [],
        "measurements": [], "control_events": [], "external_references": [],
        "edges": [], "provider_references": []}
    graph = evidence_from_dict(document)
    payload = _json(graph.to_dict())
    path = out / "shards" / f"{number:06d}.evidence.json"
    artifact = ProviderArtifact(str(path), sha256(payload).hexdigest(), len(payload), EvidenceGraph.SCHEMA)
    evidence_receipt, readback = _write(path, payload, budget)
    # Preserve the standard EEG graph and its ordinary semantic validity.
    _need(evidence_from_dict(strict_loads(readback.decode())).to_dict() == graph.to_dict(),
          "ordinary EEG projection roundtrip differs")
    by_id = {item["record"]["id"]["value"]: item for item in ordered}
    facts = [by_id[record["id"]["value"]] for record in graph.to_dict()["instances"]]
    triples = [make_records(coordinates.run.id, coordinates.target_process.id,
        artifact, i, fact["record"], fact["raw"]) for i, fact in enumerate(facts)]
    submissions = tuple(row[0] for row in triples)
    bindings = tuple(row[1] for row in triples)
    quiet = tuple(row[2] for row in triples)
    evidence = _make_evidence(coordinates.run.id, coordinates.target_process.id, artifact, payload, facts)
    checked = evidence.check_fragment(submissions, bindings, quiet, payload)
    encoded = b"".join(_json({"submission": encode(a), "binding": encode(b), "quiescence": encode(c)})
                       + b"\n" for a, b, c in triples)
    wire_receipt, wire = _write(out / "shards" / f"{number:06d}.work.jsonl.gz", encoded, budget, compressed=True)
    decoded = [strict_loads(line.decode()) for line in wire.splitlines()]
    _need(len(decoded) == len(triples), "work wire row inventory differs")
    rebuilt = tuple(tuple(decode(type(original), row[name]) for original, name in zip(triple,
        ("submission", "binding", "quiescence"))) for row, triple in zip(decoded, triples))
    _need(len(rebuilt) == len(triples), "work readback inventory differs")
    evidence.check_fragment(tuple(t[0] for t in rebuilt), tuple(t[1] for t in rebuilt),
                            tuple(t[2] for t in rebuilt), readback)
    receipts = b"".join(_json({"projection_index": index, "ticket": encode(triples[index][0].id),
        "original_eeg_ordinal": item["ordinal"], "original_locator": item["locator"],
        "raw_reference": item["raw"]["reference"], "raw_ordinal": item["raw"]["raw_ordinal"]}) + b"\n"
        for index, item in enumerate(facts))
    receipt_receipt, _ = _write(out / "shards" / f"{number:06d}.receipts.jsonl.gz", receipts, budget, compressed=True)
    if callback is not None:
        callback(evidence, submissions, bindings, quiet, payload)
    return {"index": number, "records": len(triples), "evidence": evidence_receipt,
            "work_records": wire_receipt, "source_receipts": receipt_receipt, "check": checked}


def acquire_native_activity_work(capture_root, partition_root, output, *, budgets=None,
                                 on_verified_shard=None):
    """Acquire all GPU candidates once and publish existing typed fragments.

    Genuine coordinates are acquired here, never accepted from a JSON report.
    No caller whitelist reduces the physical kernel/copy domain.
    """
    limits = budgets or NativeWorkBudget(); limits.__post_init__()
    capture_root, partition_root = Path(capture_root).resolve(), Path(partition_root).resolve()
    output = Path(output).resolve()
    _need(not output.exists() and not output.is_relative_to(capture_root)
          and not output.is_relative_to(partition_root), "work output must be a fresh separate directory")
    output.mkdir(parents=True); (output / "shards").mkdir(); (output / "inventory").mkdir()
    budget = _Budget(limits)
    progress = output / "progress.jsonl"

    def emit(value):
        with progress.open("ab") as stream:
            data = _json({**value, "io": budget.report()}) + b"\n"
            _need(sum(budget.output.values()) + len(data) <= limits.max_output_io_bytes,
                  "work progress output budget exceeded")
            stream.write(data); budget.out("written_progress", len(data))

    try:
        with _count_input_reads(budget, (capture_root, partition_root)):
            coordinates = bind_capture_coordinates(capture_root, max_bytes=limits.max_input_bytes,
                                                    max_lines=limits.max_os_lines)
            emit({"stage": "genuine_coordinates_acquired", "run": encode(coordinates.run.id)})
            members = coordinates.report["membership"]
            def member(schema):
                matches = [row for row in members if row["artifact"]["schema"] == schema]
                _need(len(matches) == 1, "capture does not select one exact " + schema)
                row = matches[0]
                return decode(ProviderArtifact, row["artifact"]), Path(row["local_path"])
            kineto, kineto_path = member("pytorch.kineto.chrome-trace.v1")
            eto, _ = member("pytorch.execution-trace.v1")
            native_artifact, native_path = member("scar.execution-evidence-collection")
            native_bytes = native_path.read_bytes()
            _need(len(native_bytes) == native_artifact.size_bytes
                  and sha256(native_bytes).hexdigest() == native_artifact.sha256,
                  "closed native manifest changed after binder")
            native = strict_loads(native_bytes.decode())
            _need(native["provider"]["torch_git_version"] == _REVISION
                  and native["provider"]["torch_version"].endswith("+cu132"),
                  "unsupported fixed GPU provider revision/ABI family")
            pid = coordinates.target_process.pid
            _need(coordinates.process_for(kineto, pid) == coordinates.target_process
                  and coordinates.process_for(eto, pid) == coordinates.target_process,
                  "native artifacts do not select the exact target process")
            scope = "native:" + _canonical_hash({"eto": eto.sha256, "kineto": kineto.sha256,
                                                "revision": _REVISION, "pid": pid})
            raw, provider = _scan_kineto(kineto_path, kineto, budget)
            emit({"stage": "complete_kineto_verified", "gpu_candidate_records": len(raw),
                  "provider_events": provider["events"]})
            archive = _Partitions(partition_root, budget)
            table = archive.manifest["graphs"]["evidence"]["tables"]["instances"]
            chunks = table["chunks"]
            _need(sum(budget.input.values()) + sum(c["decoded_bytes"] + c["physical_bytes"] for c in chunks)
                  <= limits.max_input_bytes, "complete EEG instance table would exceed remaining input budget")
            shards, pending, qualified, visited, eeg_gpu = [], [], 0, 0, 0
            for row in archive.iter_records("evidence", "instances"):
                visited += 1
                record = row["record"]; metadata = record.get("metadata", {})
                category = metadata.get("category", "")
                if type(category) is str and _gpu(category):
                    eeg_gpu += 1
                    reference = metadata.get("raw_reference")
                    prefix = "sha256:" + kineto.sha256 + "#/traceEvents/"
                    _need(type(reference) is str and reference.startswith(prefix)
                          and reference[len(prefix):].isdigit(), "EEG GPU source is outside original Kineto")
                    index = int(reference[len(prefix):]); fact = raw.get(index)
                    _need(fact is not None and not fact["eeg_seen"], "EEG GPU source is missing or duplicated")
                    _check_original(record, fact, scope, pid)
                    fact["eeg_seen"], fact["eeg_ordinal"] = True, row["ordinal"]
                    if fact["frontier"] is None:
                        pending.append({"record": record, "raw": fact.copy(),
                                        "host_pid": pid, "ordinal": row["ordinal"], "locator": row["locator"]})
                        qualified += 1
                        if len(pending) == limits.max_shard_rows:
                            shards.append(_publish(pending, output, len(shards), coordinates, budget, on_verified_shard))
                            pending.clear()
                            emit({"stage": "verified_shard", "shards": len(shards),
                                  "qualified": qualified, "visited_eeg_instances": visited})
                if visited % 10000 == 0:
                    budget.check()
            _need(visited == table["records"], "complete EEG instance denominator differs")
            if pending:
                shards.append(_publish(pending, output, len(shards), coordinates, budget, on_verified_shard))
            inventory_chunks, inventory, frontier_counts = [], [], Counter()
            qualified_after_join = 0
            for index, fact in sorted(raw.items()):
                reason = fact["frontier"]
                if not fact["eeg_seen"] and reason is None:
                    reason = "ORIGINAL_EEG_ACTIVITY_UNAVAILABLE"
                if reason is not None:
                    frontier_counts[reason] += 1
                else:
                    qualified_after_join += 1
                inventory.append({"raw_ordinal": index, "raw_reference": fact["reference"],
                    "category": fact["category"], "phase": fact["event"].get("ph"),
                    "eeg_ordinal": fact.get("eeg_ordinal"),
                    "status": "QUIESCENCE_QUALIFIED" if reason is None else "FRONTIER", "frontier": reason})
                if len(inventory) == 1000:
                    payload = b"".join(_json(item) + b"\n" for item in inventory)
                    receipt, _ = _write(output / "inventory" / f"{len(inventory_chunks):06d}.jsonl.gz",
                                        payload, budget, compressed=True)
                    inventory_chunks.append({**receipt, "rows": len(inventory)}); inventory.clear()
            if inventory:
                receipt, _ = _write(output / "inventory" / f"{len(inventory_chunks):06d}.jsonl.gz",
                    b"".join(_json(item) + b"\n" for item in inventory), budget, compressed=True)
                inventory_chunks.append({**receipt, "rows": len(inventory)})
            _need(qualified == qualified_after_join == sum(item["records"] for item in shards)
                  and qualified + sum(frontier_counts.values()) == len(raw),
                  "complete native activity work/source inventory is not conserved")
            report = {"schema": "scar.native-activity-work-report", "schema_version": 1,
                "status": "SINGLE_ACTIVITY_QUIESCENCE_WITH_OPEN", "run": encode(coordinates.run.id),
                "process": encode(coordinates.target_process.id), "native_namespace": scope,
                "coordinates": encode(coordinates.artifact), "kineto": provider,
                "original_eeg_manifest": archive.manifest_receipt,
                "original_eeg_instances": visited, "original_eeg_gpu_candidates": eeg_gpu,
                "all_gpu_candidates": len(raw), "qualified_single_activities": qualified,
                "frontier_counts": dict(frontier_counts), "shards": shards,
                "inventory_chunks": inventory_chunks, "budgets": vars(limits), "io": budget.report(),
                "io_scope": "before_manifest_publication; gate result includes its write/readback",
                "program_snapshot_attachment": "UNATTACHED_TO_PROGRAM_SNAPSHOT",
                "execution_model_created": False, "outcomes_created": 0,
                "result_success_established": False, "child_completion_established": False,
                "resource_readiness_established": False, "whole_model_established": False,
                "conditions": ["fixed declared Torch/Kineto/CUPTI provider contract",
                    "historical loaded provider binary/source identity is not proved",
                    "single instrumented GPU activity, not host-call or child-work closure",
                    "all dependency/effect/materialization/retention coverage remains unknown"],
                "provider_contract": {"torch_revision": _REVISION,
                    "kineto_revision": "094d3c1d072362d0a919a77299459eee94f97931",
                    "compile_guard_condition": "declared cu132 implies CUDA_VERSION >= 13010; actual historical build witness OPEN",
                    "kernel_struct": "CUpti_ActivityKernel11", "copy_struct": "CUpti_ActivityMemcpy5",
                    "p2p_struct": "CUpti_ActivityMemcpyPtoP4",
                    "memset_struct": "CUpti_ActivityMemset4",
                    "typedef_source": "libkineto/src/DeviceProperties.h:25-42 at pinned Kineto",
                    "memset_quiescence_qualified": True}}
            _write(output / "manifest.json", _json(report), budget)
            # The final accounting includes publication/readback of the manifest.
            final = {**report, "io": budget.report(), "io_scope": "after_manifest_publication"}
            return final
    except BaseException as error:
        failure = {"status": "FAILED", "error_type": type(error).__name__, "error": str(error),
                   "io": budget.report(), "whole_model_established": False}
        path = output / "failure.json"
        if not path.exists():
            with path.open("xb") as stream:
                stream.write(_json(failure))
        raise


__all__ = ["NativeWorkBudget", "acquire_native_activity_work"]
