"""Project real FD outputs for existing R1 handles, without replaying Work.

This is a new provider of bounded evidence, not an alternative mutable IR.
The selected FD view is supplied through its public typed reader and exact
published manifest; callers never supply an authoritative handle dictionary.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, fields, replace
import gzip
import hashlib
import io
import os
from pathlib import Path, PurePosixPath
import re
import secrets

from scar.ir.execution.common import Unresolved
from scar.ir.execution.ids import HandleBindingID, NativeHandleLifetimeID
from scar.ir.execution.resources import HandleBinding, HandleNamespace, ProviderHandle, ProviderRecordSelector, RunRealm
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.record_codec import decode, encode, loads as strict_loads
from scar.store.bundle_partitions import BundleBudgets, BundlePartitions, _Chunk, _line
from scar.trace import os_resources as parser
from scar.trace.os_fd_table_contexts import OSFDTableContexts
from scar.trace.os_resource_refinement import OSResourceBase, OSResourceRefinement


SCHEMA = "scar.os-fd-source-projection"
VERSION = 1
_TABLES = ("fd_ports", "birth_facts", "frontiers")
_RAW = "strace.syscalls.text.v1"


@dataclass(frozen=True)
class FDSourceInputs:
    capture_root: str | Path
    selected_manifest: str | Path
    archive: str | Path
    coordinates: str | Path
    projection_files: str | Path
    context_events: str | Path
    context_evidence: str | Path


@dataclass(frozen=True)
class FDSourceBudgets:
    max_raw_bytes: int = 128_000_000
    max_raw_lines: int = 2_000_000
    max_line_bytes: int = 16_384
    max_compressed_file_bytes: int = 32_000_000
    max_handles: int = 20_000
    max_artifacts: int = 512
    max_metadata_bytes: int = 4_000_000
    max_chunk_decoded_bytes: int = 16_000_000
    max_record_bytes: int = 1_000_000
    max_projection_decoded_bytes: int = 128_000_000
    max_projection_stored_bytes: int = 64_000_000
    max_manifest_bytes: int = 4_000_000

    def __post_init__(self):
        _need(all(type(value) is int and value > 0 for value in vars(self).values()), "budgets must be positive integers")
        _need(self.max_record_bytes <= self.max_chunk_decoded_bytes, "one record must fit in a chunk")


def _need(value, message):
    if not value:
        raise ValueError("OS FD source projection: " + message)


def _storage(limits):
    return BundleBudgets(max_record_bytes=limits.max_record_bytes,
        max_chunk_decoded_bytes=limits.max_chunk_decoded_bytes,
        max_total_decoded_bytes=limits.max_projection_decoded_bytes,
        max_total_stored_bytes=limits.max_projection_stored_bytes,
        max_manifest_bytes=limits.max_manifest_bytes)


def _canonical(value):
    return _line(value, BundleBudgets())


def _record_sha(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _document(path, maximum):
    path = Path(path).absolute()
    _need(path.is_file() and not path.is_symlink(), "explicit input file absent or symlinked")
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    _need(len(raw) <= maximum, "metadata budget exceeded")
    doc = strict_loads(raw.decode("utf-8"))
    declared = doc.get("schema") if type(doc) is dict else None
    schema = declared if type(declared) is str and declared else "application/json"
    return doc, ProviderArtifact(str(path), hashlib.sha256(raw).hexdigest(), len(raw), schema)


def _line_number(source):
    match = re.fullmatch(r"#/lines/([1-9][0-9]*)", source["locator"])
    _need(match is not None, "source is not an exact original physical line")
    return int(match[1])


def _raw_source(entry, line):
    return {"artifact": {"uri": entry["logical_path"], "sha256": entry["raw_sha256"],
        "size_bytes": entry["raw_bytes"], "schema": _RAW}, "locator": "#/lines/" + str(line)}


def _native_tid(entry):
    match = re.fullmatch(r"syscalls\.([1-9][0-9]*)", PurePosixPath(entry["logical_path"]).name)
    _need(match is not None, "unsupported per-native-TID source selector")
    return int(match[1])


def _selected(base, view, path, maximum):
    _need(type(base) is OSResourceBase and type(view) is OSFDTableContexts
          and view.base.artifact == base.artifact, "public original base and verified selected view required")
    _need(getattr(view,'capture_coverage_verified',False) is True and view.document.get('schema_version')==2,
          "historical context continuity is not capture-coverage-qualified; use explicit FD-values-only R2 mode")
    doc, artifact = _document(path, maximum)
    _need(doc == view.document and doc.get("status") == "PUBLISHED"
          and doc["base"] == encode(base.artifact) and doc["run"] == encode(base.run),
          "selected view does not match its exact published manifest")
    expected = {decode(HandleBinding, row["replacement"]).id: decode(HandleBinding, row["replacement"])
                for row in doc["handle_refinements"]}
    _need(expected == view.handles, "selected typed handle registry changed after public validation")
    return artifact


def _load_inputs(base, view, inputs, limits):
    _need(type(inputs) is FDSourceInputs, "explicit FDSourceInputs required")
    selected_artifact = _selected(base, view, inputs.selected_manifest, limits.max_metadata_bytes)
    base_doc, base_artifact = _document(base.reader.manifest_receipt["path"], limits.max_metadata_bytes)
    _need(base_doc == base.manifest and base_artifact == base.artifact, "original base manifest changed")
    docs, receipts = {}, {"selected_manifest": selected_artifact}
    aliases = {"archive": "archive", "coordinates": "coordinates", "projection_files": "projection_files",
               "context_events": "projection_events", "context_evidence": "context_evidence"}
    for name, old_name in aliases.items():
        docs[name], receipts[name] = _document(getattr(inputs, name), limits.max_metadata_bytes)
        _need(encode(receipts[name]) == view.document["inputs"][old_name], "input differs from verified selected view: " + name)
    coords = docs["coordinates"]
    _need(coords["run"] == encode(base.run) and coords["seed"]["archive_sha256"] == receipts["archive"].sha256,
          "input Run/archive receipt differs")
    root = Path(inputs.capture_root).resolve()
    _need(not Path(inputs.capture_root).is_symlink() and root == Path(coords["local_root"]).resolve(),
          "implicit capture relocation is unsupported")
    original = PurePosixPath(coords["original_root"])
    logical, actual = {}, {}
    for entry in docs["archive"]["files"]:
        first, second = PurePosixPath(entry["logical_path"]), PurePosixPath(entry["actual_path"])
        _need(first.is_absolute() and second.is_absolute() and ".." not in first.parts and ".." not in second.parts
              and first.is_relative_to(original) and second.is_relative_to(original), "archive path escapes original namespace")
        _need(entry["logical_path"] not in logical and entry["actual_path"] not in actual, "ambiguous exact retention mapping")
        logical[entry["logical_path"]] = entry; actual[entry["actual_path"]] = entry
    artifacts = []
    for envelope in base.reader.iter_records("artifacts"):
        _need(len(artifacts) < limits.max_artifacts, "artifact budget exceeded")
        artifact = decode(ProviderArtifact, envelope["record"])
        _need(artifact.uri in actual, "original source is outside exact retained mapping")
        entry = actual[artifact.uri]
        _need((artifact.sha256, artifact.size_bytes, artifact.schema) ==
              (entry["raw_sha256"], entry["raw_bytes"], _RAW), "original raw source identity differs")
        artifacts.append(artifact)
    _need(len(artifacts) == base.manifest["tables"]["artifacts"]["records"] == coords["counts"]["os_artifacts"],
          "artifact source scope incomplete")
    expected_lines = {}
    for row in docs["projection_files"]:
        entry = row["entry"]
        _need(entry == logical[entry["logical_path"]] and entry["logical_path"] not in expected_lines
              and type(row["lines"]) is int and row["lines"] >= 0, "original non-main line receipt differs")
        expected_lines[entry["logical_path"]] = row["lines"]
    main_uri = coords["seed"]["target_exec"]["artifact"]["uri"]
    _need(main_uri not in expected_lines and len(expected_lines) + 1 == len(artifacts), "original complement scope differs")
    expected_lines[main_uri] = base.manifest["summary"]["physical_lines"] - sum(expected_lines.values())
    _need(expected_lines[main_uri] >= 0, "main line count cannot be derived")
    return docs, receipts, root, original, logical, actual, artifacts, expected_lines


def _reference(base, ordinal, wire):
    return {"selector": encode(base.selector("handles", ordinal)), "id": wire["id"],
            "canonical_record_sha256": _record_sha(wire)}


def _check_reference(base, reference, ordinal, wire):
    _need(reference == _reference(base, ordinal, wire), "original handle canonical preimage differs")


def _known_births(docs, artifacts, actual):
    known = {}
    for event in docs["context_events"]:
        if event["syscall"] in parser._CLONE and type(event["result"]) is int and event["result"] > 0 and event["clone_flags"] is not None:
            key = event["source"]["artifact"]["uri"], _line_number(event["source"])
            known[key] = {"source": event["source"], "child_native_tid": event["result"], "flags": event["clone_flags"]}
    evidence = docs["context_evidence"]
    row = evidence["child_birth_r1"]["record"]
    flags = parser._clone_flags({"name": row["syscall"], "args": [str(value) for value in row["arguments"]]})
    _need(row["argument_rendering_complete"] and flags is not None, "verified child flags are unavailable")
    entry = actual[artifacts[row["source"]["artifact"]].uri]
    source = _raw_source(entry, row["source"]["line"])
    known[(entry["logical_path"], row["source"]["line"])] = {
        "source": source, "child_native_tid": row["result"], "flags": flags}
    return known


class _Sink:
    """Small fixed table sink using SCAR's existing bounded chunk writer."""
    def __init__(self, out, table, totals, limits):
        self.out, self.table, self.totals, self.limits = out, table, totals, limits
        self.active, self.count, self.chunks = None, 0, []

    def write(self, record):
        data = _line({"ordinal": self.count, "record": record}, self.limits)
        _need(self.totals["decoded_bytes"] + len(data) <= self.limits.max_total_decoded_bytes, "projection decoded budget exceeded")
        if self.active is not None and self.active.decoded_bytes + len(data) > self.limits.max_chunk_decoded_bytes:
            self.chunks.append(self.active.close()); self.active = None
        if self.active is None:
            self.active = _Chunk(self.out, "fd_sources", self.table, len(self.chunks), self.count, self.totals, self.limits)
        ordinal = self.count
        self.active.write(data); self.count += 1
        return ordinal

    def finish(self):
        if self.active is not None:
            self.chunks.append(self.active.close()); self.active = None
        return {"records": self.count, "chunks": self.chunks}


def _parse_selected(text):
    timed = parser._TIME.match(text)
    _need(timed is not None and not timed[1].startswith(("--- ", "+++ "))
          and parser._UNFINISHED.match(timed[1]) is None and parser._RESUMED.match(timed[1]) is None,
          "selected source has a context/unfinished/resumed frontier")
    matched = parser._CALL.match(timed[1])
    _need(matched is not None, "selected complete rendering is unsupported")
    name, arguments, returned, tail = matched.groups()
    return name, parser._arguments(arguments), parser._number(returned)


def _fd_value(name, args, result, request, target):
    _need(type(result) is int and result >= 0, "existing output has no successful FD return")
    if name in parser._OPEN:
        _need(request["source"] == target["source"], "open output is not the original OFD import source")
        return result, "OPEN_RETURN"
    duplication = name in ("dup", "dup2", "dup3") or (
        name in ("fcntl", "fcntl64") and len(args) > 1 and args[1] in ("F_DUPFD", "F_DUPFD_CLOEXEC"))
    _need(duplication, "source does not support a legacy FD output contract")
    _need(args and parser._number(args[0]) is not None, "dup input FD is not rendered")
    if name in ("dup2", "dup3"):
        _need(len(args) > 1 and parser._number(args[1]) == result, "dup destination/return mismatch")
    _need(not (name == "dup2" and parser._number(args[0]) == result), "dup2 no-op cannot introduce an extra binding")
    return result, "DUP_RETURN_EXISTING_TARGET"


def build_os_fd_source_projection(base, selected_view, inputs, fresh_out, *, budgets=None, progress=None):
    """Read required raw files once, project selected lines and refine no Work."""
    limits = budgets or FDSourceBudgets()
    _need(type(limits) is FDSourceBudgets, "explicit FDSourceBudgets required")
    docs, receipts, root, original, logical, actual, artifacts, expected_lines = _load_inputs(base, selected_view, inputs, limits)
    out = Path(fresh_out).absolute(); _need(not out.exists(), "output must be fresh")
    resources = {}
    threads = {row["tid"]:row for row in docs["coordinates"]["threads"]}
    for envelope in base.reader.iter_records("resources"):
        row = envelope["record"]
        _need(len(resources) < limits.max_handles and row["id"]["wire"] not in resources,
              "original resource registry budget/uniqueness failed")
        resources[row["id"]["wire"]] = {"source": row["source"], "kind": row["kind"], "role": row["role"]}
    _need(len(resources) == base.manifest["tables"]["resources"]["records"], "resource ID/source scope incomplete")
    requests, actor_entries, retained = {}, {}, []
    total_handles = 0
    for envelope in base.reader.iter_records("handles"):
        ordinal, row = envelope["ordinal"], envelope["record"]
        total_handles += 1; _need(total_handles <= limits.max_handles, "handle budget exceeded")
        source = row["source"]; artifact = decode(ProviderArtifact, source["artifact"])
        _need(artifact.uri in actual and (artifact.sha256, artifact.size_bytes, artifact.schema) ==
              (actual[artifact.uri]["raw_sha256"], actual[artifact.uri]["raw_bytes"], _RAW), "handle source identity differs")
        entry, line = actual[artifact.uri], _line_number(source)
        actor = threads.get(_native_tid(entry))
        _need(row["start"]["run"] == encode(base.run.id) and row["start"]["source"] == source
              and row["start"]["process"] == (actor["process"] if actor is not None else None),
              "handle original Run/source/process differs from its native membership")
        _need(row["target"]["instance"]["wire"] in resources
              and resources[row["target"]["instance"]["wire"]]["role"] == "OPEN_FILE_DESCRIPTION",
              "original target is not a qualified R1 OFD")
        actor_entries[entry["logical_path"]] = entry
        selected = selected_view.handles.get(decode(HandleBindingID, row["id"]))
        reference = _reference(base, ordinal, row)
        if selected is not None:
            wire = encode(selected)
            _need(selected_view.r2.handles[selected.id][0] == ordinal
                  and {k:v for k,v in row.items() if k != "handle"} == {k:v for k,v in wire.items() if k != "handle"},
                  "retained selected handle does not match the original")
            retained.append({"reference": reference, "selected_record_sha256": _record_sha(wire)})
            continue
        _need(set(row["handle"]) == {"value", "gap"}, "unselected original endpoint is not an unresolved R1 handle")
        key = entry["logical_path"], line
        requests.setdefault(key, []).append({"ordinal": ordinal, "reference": reference,
            "source": source, "run": row["start"]["run"], "target": row["target"],
            "target_fact": resources[row["target"]["instance"]["wire"]]})
    _need(total_handles == base.manifest["tables"]["handles"]["records"] and len(retained) == len(selected_view.handles),
          "handle/retained scope incomplete")
    known = _known_births(docs, artifacts, actual)
    missing_births, actor_frontiers = {}, []
    for uri, entry in actor_entries.items():
        thread = threads.get(_native_tid(entry))
        if thread is None:
            actor_frontiers.append({"reason": "NO_OWN_BIRTH_COORDINATE", "source_artifact": _raw_source(entry, 1)["artifact"]})
            continue
        source = thread["source"]
        _need(source["artifact"]["uri"] in logical and source == _raw_source(logical[source["artifact"]["uri"]], _line_number(source)),
              "actor birth source differs from original retention namespace")
        key = source["artifact"]["uri"], _line_number(source)
        if key in known:
            _need(known[key]["child_native_tid"] == thread["tid"], "known birth child differs")
        else:
            missing_births.setdefault(key, []).append(thread)
    needed_uris = {uri for uri, line in requests} | {uri for uri, line in missing_births}
    file_order = {actual[artifact.uri]["logical_path"]: i for i, artifact in enumerate(artifacts)}
    _need(needed_uris <= set(file_order) and len(needed_uris) <= limits.max_artifacts
          and sum(logical[uri]["raw_bytes"] for uri in needed_uris) <= limits.max_raw_bytes,
          "needed raw source scope/budget differs")
    out.mkdir(mode=0o700, parents=False, exist_ok=False)
    storage = _storage(limits)
    totals = {"records":0, "chunks":0, "decoded_bytes":0, "stored_bytes":0}
    sinks = {table:_Sink(out, table, totals, storage) for table in _TABLES}
    index, file_receipts, raw_bytes, raw_lines, physical_read, parsed_lines, previous_handle = [], [], 0, 0, 0, 0, -1
    try:
        for uri in sorted(needed_uris, key=file_order.__getitem__):
            entry = logical[uri]
            relative = PurePosixPath(entry["actual_path"]).relative_to(original)
            path = root
            for part in relative.parts:
                path = path / part; _need(not path.is_symlink(), "raw path traverses a symlink")
            _need(path.is_file() and path.resolve().is_relative_to(root), "raw member absent or outside capture")
            with path.open("rb") as stream:
                compressed = stream.read(limits.max_compressed_file_bytes + 1)
            physical_read += len(compressed)
            _need(len(compressed) <= limits.max_compressed_file_bytes and len(compressed) == entry["compressed_bytes"]
                  and hashlib.sha256(compressed).hexdigest() == entry["gzip_sha256"], "compressed raw receipt/budget differs")
            wanted = {line for raw_uri, line in requests if raw_uri == uri} | {line for raw_uri, line in missing_births if raw_uri == uri}
            seen, digest, size, count = set(), hashlib.sha256(), 0, 0
            with gzip.GzipFile(fileobj=io.BytesIO(compressed), mode="rb") as stream:
                while raw := stream.readline(limits.max_line_bytes + 1):
                    _need(len(raw) <= limits.max_line_bytes and raw.endswith(b"\n"), "raw line bound/termination failed")
                    count += 1; size += len(raw); digest.update(raw); raw_lines += 1; raw_bytes += len(raw)
                    _need(raw_lines <= limits.max_raw_lines and raw_bytes <= limits.max_raw_bytes, "raw aggregate budget exceeded")
                    if count not in wanted:
                        continue
                    parsed_lines += 1; seen.add(count)
                    source = _raw_source(entry, count)
                    try:
                        name, args, result = _parse_selected(raw.decode("utf-8").rstrip("\r\n"))
                    except (ValueError, UnicodeError) as error:
                        sinks["frontiers"].write({"source":source, "reason":"SELECTED_RENDERING_UNQUALIFIED", "detail":str(error)})
                        continue
                    key = uri, count
                    for thread in missing_births.get(key, ()):
                        flags = parser._clone_flags({"name":name, "args":args}) if name in parser._CLONE else None
                        if result == thread["tid"] and name in parser._CLONE and flags is not None:
                            sinks["birth_facts"].write({"run":encode(base.run.id), "source":source,
                                "parent_native_tid":_native_tid(entry), "child_thread":thread, "syscall":name, "flags":flags})
                        else:
                            sinks["frontiers"].write({"source":source, "reason":"BIRTH_RESULT_OR_FLAGS_UNQUALIFIED", "child_thread":thread})
                    at_source = requests.get(key, ())
                    if len(at_source) > 1:
                        sinks["frontiers"].write({"source":source, "reason":"AMBIGUOUS_LEGACY_HANDLE_OUTPUTS", "references":[r["reference"] for r in at_source]})
                        continue
                    for request in at_source:
                        try:
                            fd, contract = _fd_value(name, args, result, request, request["target_fact"])
                        except ValueError as error:
                            sinks["frontiers"].write({"source":source, "reference":request["reference"], "reason":"FD_CONTRACT_UNQUALIFIED", "detail":str(error)})
                            continue
                        _need(request["ordinal"] > previous_handle, "raw/provider order cannot support the declared ordered merge")
                        previous_handle = request["ordinal"]
                        port_ordinal = sinks["fd_ports"].write({"run":request["run"], "source":request["source"],
                            "raw_source":source, "handle_reference":request["reference"], "target":request["target"],
                            "fd":fd, "syscall":name, "extraction_contract":contract,
                            "new_ir_resource_created":False, "original_target_preserved":True,
                            "effects_coverage":"UNKNOWN", "container_coverage":"INDEPENDENT_PROOF_REQUIRED"})
                        index.append([request["ordinal"], port_ordinal])
            _need((digest.hexdigest(),size,count) == (entry["raw_sha256"],entry["raw_bytes"],expected_lines[uri]),
                  "raw SHA/byte/line receipt differs")
            _need(seen == wanted, "requested physical source lines were not all retained")
            file_receipts.append({"entry":entry, "raw_lines":count, "parsed_source_lines":len(wanted),
                "compressed_bytes_read_once":len(compressed), "raw_sha_verified":True, "stored_sha_verified":True})
            if progress is not None:
                progress({"phase":"RAW_FILE_COMPLETE", "files":len(file_receipts), "raw_bytes":raw_bytes,
                    "raw_lines":raw_lines, "selected_lines_parsed":parsed_lines, "fd_ports":len(index)})
        tables = {table:sinks[table].finish() for table in _TABLES}
        for frontier in actor_frontiers:
            # Actor facts are manifest frontiers; they are not missing FD requests.
            _need(frontier["reason"] == "NO_OWN_BIRTH_COORDINATE", "unknown actor frontier")
        for name in ("archive","coordinates","projection_files","context_evidence","context_events"):
            _, current = _document(getattr(inputs,name),limits.max_metadata_bytes)
            _need(current == receipts[name], "input metadata changed during raw projection")
        _need(_selected(base,selected_view,inputs.selected_manifest,limits.max_metadata_bytes) == receipts["selected_manifest"], "selected view changed")
        document = {"schema":SCHEMA,"schema_version":VERSION,"status":"PUBLISHED",
            "base":encode(base.artifact),"selected_view":encode(receipts["selected_manifest"]),"run":encode(base.run),
            "inputs":{name:encode(receipt) for name,receipt in receipts.items()},"tables":tables,"totals":totals,
            "handle_index":index,"retained_handles":retained,"raw_files":file_receipts,"actor_frontiers":actor_frontiers,
            "counts":{"base_handles":total_handles,"retained_provider_handles":len(retained),
                "requested_legacy_handles":sum(map(len,requests.values())),"projected_fd_ports":len(index),
                "unrefined_legacy_handles":sum(map(len,requests.values()))-len(index),
                "missing_birth_requests":sum(map(len,missing_births.values())),"projected_birth_facts":tables["birth_facts"]["records"],
                "frontier_records":tables["frontiers"]["records"],"raw_files":len(file_receipts),"raw_bytes":raw_bytes,
                "raw_lines":raw_lines,"selected_lines_parsed":parsed_lines,"physical_compressed_bytes_read":physical_read},
            "budgets":{f.name:getattr(limits,f.name) for f in fields(limits)},
            "validation":{"producer_raw_receipts_and_selected_extraction_checked":True,
                "reader_semantics":"bounded bytes/ordinals/source/preimages; no raw re-extraction by default",
                "new_resources_or_work":0,"full_execution_model_semantics":"OPEN"},
            "scope":"R1 existing handles only; unbuilt inherited/stdio/other references remain OPEN",
            "whole_model_established":False,"first_stage_complete":False,"transformation_authorized":False}
        encoding = replace(storage,max_record_bytes=limits.max_manifest_bytes,
            max_chunk_decoded_bytes=max(limits.max_chunk_decoded_bytes,limits.max_manifest_bytes))
        payload = _line(document,encoding)
        temporary = out/(".manifest."+secrets.token_hex(16)+".tmp")
        with temporary.open("xb") as stream:
            stream.write(payload);stream.flush();os.fsync(stream.fileno())
        os.link(temporary,out/"manifest.json");temporary.unlink()
        return {"document":document,"manifest_receipt":{"path":str(out/"manifest.json"),
            "physical_sha256":hashlib.sha256(payload).hexdigest(),"physical_bytes":len(payload)}}
    finally:
        for sink in sinks.values():
            if sink.active is not None:
                sink.active.close()


class OSFDSourceProjection:
    """Bounded new-provider reader plus a fixed same-ID handle selection view."""
    @classmethod
    def read(cls, base, selected_view, inputs, manifest, *, budgets=None, cached_chunks=2):
        limits = budgets or FDSourceBudgets()
        _need(type(limits) is FDSourceBudgets and type(cached_chunks) is int and 1<=cached_chunks<=8,"invalid reader budgets/cache")
        loaded = _load_inputs(base,selected_view,inputs,limits)
        docs, receipts, root, original, logical, actual, artifacts, expected_lines = loaded
        selected_artifact = receipts["selected_manifest"]
        doc, artifact = _document(manifest,limits.max_manifest_bytes)
        _need(doc.get("schema")==SCHEMA and type(doc.get("schema_version")) is int and doc["schema_version"]==VERSION
              and doc.get("status")=="PUBLISHED" and set(doc.get("tables",{}))==set(_TABLES),"unsupported/unpublished provider")
        _need(set(doc)=={"schema","schema_version","status","base","selected_view","run","inputs","tables","totals",
              "handle_index","retained_handles","raw_files","actor_frontiers","counts","budgets","validation","scope",
              "whole_model_established","first_stage_complete","transformation_authorized"},"unknown/missing provider fields")
        _need(doc["base"]==encode(base.artifact) and doc["selected_view"]==encode(selected_artifact)
              and doc["run"]==encode(base.run) and all(doc.get(k) is False for k in
                  ("whole_model_established","first_stage_complete","transformation_authorized")),"provider scope/authority differs")
        _need(doc["inputs"]=={name:encode(receipt) for name,receipt in receipts.items()},"provider input receipts differ")
        self=object.__new__(cls)
        self.base,self.selected_view,self.manifest,self.artifact=base,selected_view,doc,artifact
        self.root,self.limits=Path(artifact.uri).parent,_storage(limits)
        self._actual,self._logical=actual,logical
        self.cache,self.cached_chunks=OrderedDict(),cached_chunks
        totals={"records":0,"chunks":0,"decoded_bytes":0,"stored_bytes":0}
        for table in _TABLES:
            ordinal=0
            _need(set(doc["tables"][table])=={"records","chunks"},"unknown/missing provider table fields")
            for number,chunk in enumerate(doc["tables"][table]["chunks"]):
                _need(chunk["uri"]==f"fd_sources/{table}/{number:06d}.jsonl.gz" and chunk["compression"]=="gzip"
                      and type(chunk["lines"]) is int and chunk["lines"]>0
                      and chunk["first_ordinal"]==ordinal and chunk["last_ordinal"]==ordinal+chunk["lines"]-1,
                      "chunk source/range descriptor invalid")
                _need(all(type(chunk[field]) is int and chunk[field]>0 for field in ("physical_bytes","decoded_bytes"))
                      and all(type(chunk[field]) is str and re.fullmatch(r"[0-9a-f]{64}",chunk[field]) is not None
                              for field in ("physical_sha256","decoded_sha256")),"invalid chunk byte/hash receipts")
                _need(chunk["decoded_bytes"]<=self.limits.max_chunk_decoded_bytes
                      and chunk["physical_bytes"]<=self.limits.max_chunk_stored_bytes,"chunk exceeds reader budget")
                ordinal+=chunk["lines"];totals["chunks"]+=1
                totals["decoded_bytes"]+=chunk["decoded_bytes"];totals["stored_bytes"]+=chunk["physical_bytes"]
            _need(ordinal==doc["tables"][table]["records"],"provider table denominator invalid")
            totals["records"]+=ordinal
        _need(totals==doc["totals"] and totals["decoded_bytes"]<=self.limits.max_total_decoded_bytes
              and totals["stored_bytes"]<=self.limits.max_total_stored_bytes,"aggregate provider budget/count differs")
        self.index={}
        previous=-1
        for base_ordinal,port_ordinal in doc["handle_index"]:
            _need(type(base_ordinal) is int and base_ordinal>previous and type(port_ordinal) is int
                  and base_ordinal<base.manifest["tables"]["handles"]["records"]
                  and port_ordinal==len(self.index),"sparse handle index is not one ordered selection")
            self.index[base_ordinal]=port_ordinal;previous=base_ordinal
        _need(len(self.index)==doc["tables"]["fd_ports"]["records"]==doc["counts"]["projected_fd_ports"],"port index denominator differs")
        self.retained={}
        for row in doc["retained_handles"]:
            reference=row["reference"];selector=decode(ProviderRecordSelector,reference["selector"])
            identity=decode(HandleBindingID,reference["id"])
            _need(selector==base.selector("handles",selector.ordinal) and identity in selected_view.handles
                  and selected_view.r2.handles[identity][0]==selector.ordinal
                  and row["selected_record_sha256"]==_record_sha(encode(selected_view.handles[identity]))
                  and selector.ordinal not in self.retained and selector.ordinal not in self.index,
                  "retained selected handle/index differs")
            self.retained[selector.ordinal]=row
        _need(len(self.retained)==len(selected_view.handles)==doc["counts"]["retained_provider_handles"]
              and doc["counts"]["base_handles"]==base.manifest["tables"]["handles"]["records"]
              and doc["counts"]["base_handles"]<=limits.max_handles
              and doc["counts"]["requested_legacy_handles"]+len(self.retained)==doc["counts"]["base_handles"]
              and doc["counts"]["unrefined_legacy_handles"]+len(self.index)==doc["counts"]["requested_legacy_handles"],
              "selected/requested/partial handle denominator differs")
        seen_files=set()
        for row in doc["raw_files"]:
            entry=row["entry"];uri=entry["logical_path"]
            _need(uri not in seen_files and entry==logical[uri] and row["raw_lines"]==expected_lines[uri]
                  and row["compressed_bytes_read_once"]==entry["compressed_bytes"],"provider original raw receipt differs")
            seen_files.add(uri)
        _need(len(seen_files)==doc["counts"]["raw_files"]
              and sum(logical[uri]["raw_bytes"] for uri in seen_files)==doc["counts"]["raw_bytes"]
              and sum(logical[uri]["compressed_bytes"] for uri in seen_files)==doc["counts"]["physical_compressed_bytes_read"],
              "raw IO aggregate receipts differ")
        return self

    def selector(self, table, ordinal, pointer="/record"):
        _need(table in _TABLES and type(ordinal) is int and ordinal>=0,"invalid provider table/ordinal")
        found=[(i,c) for i,c in enumerate(self.manifest["tables"][table]["chunks"]) if c["first_ordinal"]<=ordinal<=c["last_ordinal"]]
        _need(len(found)==1,"provider ordinal has no unique declared chunk")
        number,chunk=found[0]
        return ProviderRecordSelector(ProviderFactReference(self.artifact,f"#/tables/{table}/chunks/{number}"),
            table,ordinal,ordinal-chunk["first_ordinal"]+1,pointer)

    def _chunk(self, table, number):
        key=table,number
        if key not in self.cache:
            self.cache[key]=BundlePartitions._chunk(self,self.manifest["tables"][table]["chunks"][number])
            while len(self.cache)>self.cached_chunks:self.cache.popitem(last=False)
        self.cache.move_to_end(key)
        return self.cache[key]

    def iter_records(self, table):
        _need(table in _TABLES,"unsupported provider table")
        for number,chunk in enumerate(self.manifest["tables"][table]["chunks"]):
            stream=io.BytesIO(self._chunk(table,number))
            for line in range(1,chunk["lines"]+1):
                raw=stream.readline(self.limits.max_record_bytes+1)
                _need(raw.endswith(b"\n") and len(raw)<=self.limits.max_record_bytes,"provider row exceeds bound")
                row=strict_loads(raw.decode("utf-8"));ordinal=chunk["first_ordinal"]+line-1
                _need(type(row) is dict and set(row)=={"ordinal","record"} and row["ordinal"]==ordinal,"provider envelope ordinal differs")
                yield {**row,"selector":encode(self.selector(table,ordinal)),
                    "row_sha256":hashlib.sha256(raw).hexdigest(),"verification":"WHOLE_CHUNK_BYTES_AND_ROW_ORDINAL"}
            _need(not stream.read(1),"unexpected provider trailing bytes")

    def resolve(self, selector):
        _need(type(selector) is ProviderRecordSelector and selector.chunk.artifact==self.artifact
              and selector==self.selector(selector.table,selector.ordinal,selector.pointer_within_line)
              and (selector.pointer_within_line=="/record" or
                   selector.pointer_within_line=="/record/fd" and selector.table=="fd_ports"),
              "selector belongs to another provider/scope")
        number=int(selector.chunk.locator.rsplit("/",1)[1])
        stream=io.BytesIO(self._chunk(selector.table,number))
        for _ in range(selector.line):raw=stream.readline(self.limits.max_record_bytes+1)
        _need(raw.endswith(b"\n") and len(raw)<=self.limits.max_record_bytes,"selected provider row invalid")
        envelope=strict_loads(raw.decode("utf-8"));_need(envelope["ordinal"]==selector.ordinal,"selected ordinal differs")
        record=envelope["record"]
        return {"value":record if selector.pointer_within_line=="/record" else record["fd"],"record":record,
            "ordinal":selector.ordinal,"row_sha256":hashlib.sha256(raw).hexdigest(),
            "verification":"WHOLE_CHUNK_BYTES_AND_EXACT_SELECTOR"}

    def combined_resolve(self, selector):
        if type(selector) is ProviderRecordSelector and selector.chunk.artifact==self.base.artifact:
            return self.base.resolve(selector)
        return self.resolve(selector)

    def _refine(self, ordinal, wire, port, port_ordinal):
        _check_reference(self.base,port["handle_reference"],ordinal,wire)
        _need(port["source"]==wire["source"] and port["run"]==wire["start"]["run"]
              and port["target"]==wire["target"] and type(port["fd"]) is int and port["fd"]>=0,
              "projected original source/Run/target/FD differs")
        entry=self._actual[wire["source"]["artifact"]["uri"]]
        _need(port["raw_source"]==_raw_source(entry,_line_number(wire["source"]))
              and port["extraction_contract"] in ("OPEN_RETURN","DUP_RETURN_EXISTING_TARGET")
              and port["new_ir_resource_created"] is False and port["original_target_preserved"] is True
              and port["effects_coverage"]=="UNKNOWN",
              "projected raw provenance/contract differs")
        _need(port["extraction_contract"]!="OPEN_RETURN" or port["syscall"] in parser._OPEN,
              "open provider contract/syscall differs")
        original=decode(HandleBinding,wire)
        lifetime=NativeHandleLifetimeID("scar.os-fd-source:"+_record_sha({"base":encode(self.base.artifact),
            "reference":port["handle_reference"],"raw_source":port["raw_source"],"fd":port["fd"]}))
        rule=ProviderFactReference(decode(ProviderArtifact,self.base.manifest["protocol_artifact"]),"#/contract/interface_work")
        endpoint=ProviderHandle(HandleNamespace(RunRealm(self.base.run.id),rule),
            Unresolved("FD value observed; container requires independent context/availability proof",original.start),
            self.selector("fd_ports",port_ordinal,"/record/fd"),lifetime,original.source)
        return encode(replace(original,handle=endpoint))

    def iter_handle_records(self):
        """Merge two ordered streams once; no per-handle chunk decompression."""
        ports=iter(self.iter_records("fd_ports"));current=next(ports,None);seen=0
        for envelope in self.base.reader.iter_records("handles"):
            ordinal,wire=envelope["ordinal"],envelope["record"]
            identity=decode(HandleBindingID,wire["id"])
            retained=self.selected_view.handles.get(identity)
            if retained is not None:
                _check_reference(self.base,self.retained[ordinal]["reference"],ordinal,wire)
                result=encode(retained);selection="RETAINED_SELECTED_PROVIDER"
            elif ordinal in self.index:
                _need(current is not None and current["ordinal"]==self.index[ordinal],"ordered port merge differs")
                result=self._refine(ordinal,wire,current["record"],current["ordinal"])
                selection="FD_VALUE_REFINED_CONTAINER_OPEN";seen+=1;current=next(ports,None)
            else:
                result=wire;selection="ORIGINAL_UNRESOLVED_FRONTIER"
            _need({k:v for k,v in result.items() if k!="handle"}=={k:v for k,v in wire.items() if k!="handle"},"nonendpoint field changed")
            yield {"ordinal":ordinal,"record":result,"selection":selection,"base_locator":envelope["locator"]}
        _need(current is None and seen==len(self.index),"port merge source scope incomplete")

    def record(self, table, ordinal):
        if table=="submissions":return self.selected_view.record(table,ordinal)
        _need(table=="handles","only handles are refined; submissions delegate to the selected view")
        wire=self.base.resolve(self.base.selector("handles",ordinal))["record"]
        identity=decode(HandleBindingID,wire["id"]);retained=self.selected_view.handles.get(identity)
        if retained is not None:
            _check_reference(self.base,self.retained[ordinal]["reference"],ordinal,wire)
            return {"record":encode(retained),"selection":"RETAINED_SELECTED_PROVIDER"}
        if ordinal not in self.index:return {"record":wire,"selection":"ORIGINAL_UNRESOLVED_FRONTIER"}
        port_ordinal=self.index[ordinal];port=self.resolve(self.selector("fd_ports",port_ordinal))["record"]
        return {"record":self._refine(ordinal,wire,port,port_ordinal),"selection":"FD_VALUE_REFINED_CONTAINER_OPEN"}


__all__=["FDSourceInputs","FDSourceBudgets","build_os_fd_source_projection","OSFDSourceProjection"]


# Explicitly different qualification from historical schema1 context-dependent
# views. The immutable schema1 payload is admitted as FD evidence only.
FD_VALUES_VERSION=2
FD_VALUES_MODE='FD_VALUES_ONLY_R2'


@dataclass(frozen=True)
class FDValuesInputs:
    selected_manifest: str | Path  # Public R2, never an old context dictionary.
    original_projection: str | Path
    original_selected_manifest: str | Path  # Receipt/provenance only, no context authority.
    archive: str | Path
    coordinates: str | Path


def _r2_selection(base,view,path,maximum):
    _need(type(base) is OSResourceBase and type(view) is OSResourceRefinement
          and view.base.artifact==base.artifact,'FD-values-only requires the public original R2 selection')
    doc,artifact=_document(path,maximum)
    _need(doc==view.document and doc['base']==encode(base.artifact) and doc['run']==encode(base.run),
          'R2 selected manifest receipt/record differs')
    handles={identity:pair[1] for identity,pair in view.handles.items()}
    _need(all(type(row.handle) is ProviderHandle and type(row.handle.container) is Unresolved for row in handles.values()),
          'FD-values-only must not inherit a known container assertion')
    return artifact,handles


def _fd_values_inputs(base,r2,inputs,limits):
    _need(type(inputs) is FDValuesInputs,'explicit FDValuesInputs required')
    selected,handles=_r2_selection(base,r2,inputs.selected_manifest,limits.max_metadata_bytes)
    base_doc,base_artifact=_document(base.reader.manifest_receipt['path'],limits.max_metadata_bytes)
    _need(base_doc==base.manifest and base_artifact==base.artifact,'original base changed during FD qualification')
    docs,receipts={}, {'selected_manifest':selected}
    for name in ('original_projection','original_selected_manifest','archive','coordinates'):
        docs[name],receipts[name]=_document(getattr(inputs,name),limits.max_metadata_bytes)
    old=docs['original_projection'];former=docs['original_selected_manifest'];coords=docs['coordinates']
    _need(old.get('schema')==SCHEMA and old.get('schema_version')==1 and old.get('status')=='PUBLISHED',
          'only an explicit original schema1 FD evidence payload can be requalified')
    _need(old['base']==encode(base.artifact) and old['run']==encode(base.run)
          and old['selected_view']==encode(receipts['original_selected_manifest'])
          and former['base']==encode(base.artifact) and former['run']==encode(base.run),
          'original FD payload/capture/R2 provenance differs')
    _need(former.get('schema')=='scar.os-fd-table-context-refinement'
          and former.get('schema_version')==1 and former.get('status')=='PUBLISHED',
          'original context provenance is not the explicit historical schema1 publication')
    _need(old['inputs']['archive']==encode(receipts['archive']) and old['inputs']['coordinates']==encode(receipts['coordinates'])
          and coords['run']==encode(base.run) and coords['seed']['archive_sha256']==receipts['archive'].sha256,
          'original raw/coordinate receipts differ')
    bound=base.manifest['protocol_document']['contract']['coordinate_binding']
    _need(bound==encode(receipts['coordinates']),'base binds another coordinate artifact')
    actual={entry['actual_path']:entry for entry in docs['archive']['files']}
    _need(len(actual)==len(docs['archive']['files']),'retention actual URI mapping is ambiguous')
    return docs,receipts,handles,actual


def _open_payload_only(path,limits,version):
    """Storage verification only; never instantiate a context-qualified view."""
    doc,artifact=_document(path,limits.max_manifest_bytes)
    _need(doc.get('schema')==SCHEMA and doc.get('schema_version')==version and doc.get('status')=='PUBLISHED'
          and set(doc.get('tables',{}))==set(_TABLES),'unsupported explicit FD payload representation')
    if version==FD_VALUES_VERSION:
        _need(doc.get('mode')==FD_VALUES_MODE,'schema2 is not FD_VALUES_ONLY_R2')
    self=object.__new__(OSFDValuesProjection)
    self.root,self.manifest,self.artifact=Path(artifact.uri).parent,doc,artifact
    self.limits,self.cache,self.cached_chunks=_storage(limits),OrderedDict(),2
    totals={'records':0,'chunks':0,'decoded_bytes':0,'stored_bytes':0}
    for table in _TABLES:
        ordinal=0
        _need(set(doc['tables'][table])=={'records','chunks'}
              and type(doc['tables'][table]['records']) is int
              and doc['tables'][table]['records']>=0,'invalid payload table descriptor')
        for number,chunk in enumerate(doc['tables'][table]['chunks']):
            _need(chunk['uri']==f'fd_sources/{table}/{number:06d}.jsonl.gz' and chunk['compression']=='gzip'
                  and type(chunk['lines']) is int and chunk['lines']>0
                  and chunk['first_ordinal']==ordinal and chunk['last_ordinal']==ordinal+chunk['lines']-1,
                  'payload chunk/range descriptor differs')
            _need(all(type(chunk[field]) is int and chunk[field]>0 for field in ('physical_bytes','decoded_bytes'))
                  and all(type(chunk[field]) is str and re.fullmatch(r'[0-9a-f]{64}',chunk[field]) is not None
                          for field in ('physical_sha256','decoded_sha256')),'invalid payload byte/hash receipts')
            _need(chunk['decoded_bytes']<=self.limits.max_chunk_decoded_bytes
                  and chunk['physical_bytes']<=self.limits.max_chunk_stored_bytes,'payload chunk exceeds reader budget')
            ordinal+=chunk['lines'];totals['chunks']+=1
            totals['decoded_bytes']+=chunk['decoded_bytes'];totals['stored_bytes']+=chunk['physical_bytes']
        _need(ordinal==doc['tables'][table]['records'],'payload table denominator differs')
        totals['records']+=ordinal
    _need(totals==doc['totals'] and totals['decoded_bytes']<=self.limits.max_total_decoded_bytes
          and totals['stored_bytes']<=self.limits.max_total_stored_bytes,'payload aggregate receipts differ')
    return self


def _fd_values_index(document,base):
    index={};previous=-1
    for base_ordinal,port_ordinal in document['handle_index']:
        _need(type(base_ordinal) is int and previous<base_ordinal<base.manifest['tables']['handles']['records']
              and type(port_ordinal) is int and port_ordinal==len(index),'FD-only ordered sparse index differs')
        index[base_ordinal]=port_ordinal;previous=base_ordinal
    _need(len(index)==document['tables']['fd_ports']['records'],'FD-only index denominator differs')
    return index


def requalify_os_fd_values(base,r2_view,inputs,fresh_out,*,budgets=None,progress=None):
    """Publish explicit schema2/R2 qualification, hard-linking exact old chunks.

    No raw scan and no unsafe OSFDTableContexts.read. Context identity is not
    inherited. Original OFD/ends remain baseline declarations, not proven truth.
    """
    limits=budgets or FDSourceBudgets()
    docs,receipts,retained,actual=_fd_values_inputs(base,r2_view,inputs,limits)
    payload=_open_payload_only(inputs.original_projection,limits,1)
    out=Path(fresh_out).absolute();_need(not out.exists(),'output must be fresh')
    old=payload.manifest
    former={row['replacement']['id']['wire']:row['replacement'] for row in docs['original_selected_manifest']['handle_refinements']}
    ports=iter(payload.iter_records('fd_ports'));current=next(ports,None)
    old_retained={decode(ProviderRecordSelector,row['reference']['selector']).ordinal:row for row in old['retained_handles']}
    old_index=_fd_values_index(old,base)
    new_retained=[];checked=0;values=0;seen_retained=set()
    for envelope in base.reader.iter_records('handles'):
        ordinal,wire=envelope['ordinal'],envelope['record'];checked+=1
        _need(checked<=limits.max_handles,'handle qualification budget exceeded')
        identity=decode(HandleBindingID,wire['id'])
        if identity in retained:
            original=retained[identity];new=encode(original)
            _need(r2_view.handles[identity][0]==ordinal and identity.value==wire['id']['value'],'R2 original handle identity differs')
            reference=old_retained[ordinal]['reference'];_check_reference(base,reference,ordinal,wire)
            previous=former[identity.wire]
            _need(_record_sha(previous)==old_retained[ordinal]['selected_record_sha256']
                  and {k:v for k,v in previous.items() if k!='handle'}=={k:v for k,v in new.items() if k!='handle'}
                  and {k:v for k,v in previous['handle'].items() if k!='container'}==
                      {k:v for k,v in new['handle'].items() if k!='container'},
                  'R2 retained FD value/lifetime/selector/source changed beyond removing container assertion')
            new_retained.append({'reference':reference,'selected_record_sha256':_record_sha(new)})
            seen_retained.add(identity);continue
        if ordinal not in old_index:
            continue
        _need(current is not None,'original FD evidence is missing an indexed port')
        port=current['record'];reference=port['handle_reference'];_check_reference(base,reference,ordinal,wire)
        _need(current['ordinal']==old_index[ordinal] and port['source']==wire['source']
              and port['run']==wire['start']['run']==encode(base.run.id) and port['target']==wire['target']
              and type(port['fd']) is int and port['fd']>=0,'original FD evidence/preimage differs')
        entry=actual[wire['source']['artifact']['uri']]
        _need(port['raw_source']==_raw_source(entry,_line_number(wire['source']))
              and port['extraction_contract'] in ('OPEN_RETURN','DUP_RETURN_EXISTING_TARGET')
              and port['new_ir_resource_created'] is False and port['original_target_preserved'] is True,
              'FD scalar raw provenance/contract differs')
        values+=1;current=next(ports,None)
        if progress is not None and values%2000==0:progress({'phase':'FD_VALUES_REQUALIFIED','ports':values})
    _need(current is None and values==old['tables']['fd_ports']['records'] and seen_retained==set(retained)
          and checked==base.manifest['tables']['handles']['records'],'FD values qualification scope incomplete')
    _need(checked==values+len(retained)+old['counts']['unrefined_legacy_handles'],
          'original partial FD evidence denominator differs')
    # Verify every other payload chunk before making any new logical publication.
    for table in ('birth_facts','frontiers'):
        for _ in payload.iter_records(table):pass
    for name in ('original_projection','original_selected_manifest','archive','coordinates'):
        _,current_receipt=_document(getattr(inputs,name),limits.max_metadata_bytes)
        _need(current_receipt==receipts[name],'FD qualification input changed')
    _need(_r2_selection(base,r2_view,inputs.selected_manifest,limits.max_metadata_bytes)[0]==receipts['selected_manifest'],
          'R2 selected input changed')
    out.mkdir(mode=0o700,parents=False,exist_ok=False)
    links=[]
    for table in _TABLES:
        for chunk in old['tables'][table]['chunks']:
            relative=Path(chunk['uri']);_need(not relative.is_absolute() and '..' not in relative.parts,'unsafe payload URI')
            source=payload.root/relative
            _need(source.is_file() and not source.is_symlink(),'payload hardlink source absent or symlinked')
            destination=out/relative;destination.parent.mkdir(parents=True,exist_ok=True)
            os.link(source,destination)
            links.append({'original_provider':encode(payload.artifact),'original_uri':chunk['uri'],'new_uri':chunk['uri'],
                'stored_sha256':chunk['physical_sha256'],'stored_bytes':chunk['physical_bytes'],'retention':'HARDLINK_SAME_VERIFIED_BYTES'})
    document={'schema':SCHEMA,'schema_version':FD_VALUES_VERSION,'mode':FD_VALUES_MODE,'status':'PUBLISHED',
        'base':encode(base.artifact),'selected_view':encode(receipts['selected_manifest']),'run':encode(base.run),
        'inputs':{name:encode(value) for name,value in receipts.items()},'tables':old['tables'],'totals':old['totals'],
        'handle_index':old['handle_index'],'retained_handles':new_retained,'actor_frontiers':old['actor_frontiers'],
        'original_extraction':{'artifact':encode(payload.artifact),'counts':old['counts'],'raw_files':old['raw_files']},
        'payload_retention':links,'counts':{'base_handles':checked,'retained_provider_handles':len(new_retained),
            'projected_fd_ports':values,'unrefined_legacy_handles':old['counts']['unrefined_legacy_handles'],
            'raw_bytes_read_during_requalification':0,'new_container_bindings':0},
        'invalidated_context_assertions':{'artifact':encode(receipts['original_selected_manifest']),
            'reason':'CAPTURE_FILTER_COVERAGE_NOT_ESTABLISHED','imported_context_resources':0},
        'validation':{'fd_values':'RECEIPT_BOUND_PRIOR_RAW_EXTRACTION_AND_EXACT_BASE_PREIMAGES',
            'ofd_target_and_end_semantics':'PRESERVED_BASELINE_DECLARATIONS_NOT_REPROVED',
            'container_continuity':'UNQUALIFIED_NOT_IMPORTED','new_resources_or_work':0,'full_execution_model_semantics':'OPEN'},
        'scope':'existing R1 FD scalar evidence only; FD table/OFD coidentity and unobserved producers remain OPEN',
        'whole_model_established':False,'first_stage_complete':False,'transformation_authorized':False}
    encoding=replace(_storage(limits),max_record_bytes=limits.max_manifest_bytes,
        max_chunk_decoded_bytes=max(limits.max_chunk_decoded_bytes,limits.max_manifest_bytes))
    raw=_line(document,encoding);temporary=out/('.manifest.'+secrets.token_hex(16)+'.tmp')
    with temporary.open('xb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
    os.link(temporary,out/'manifest.json');temporary.unlink()
    return {'document':document,'manifest_receipt':{'path':str(out/'manifest.json'),
        'physical_sha256':hashlib.sha256(raw).hexdigest(),'physical_bytes':len(raw)}}


class OSFDValuesProjection(OSFDSourceProjection):
    """Explicit schema2 FD-only view over public R2; no table-context authority."""
    @classmethod
    def read(cls,base,r2_view,inputs,manifest,*,budgets=None):
        limits=budgets or FDSourceBudgets()
        docs,receipts,retained,actual=_fd_values_inputs(base,r2_view,inputs,limits)
        self=_open_payload_only(manifest,limits,FD_VALUES_VERSION)
        _need(set(self.manifest)=={'schema','schema_version','mode','status','base','selected_view','run','inputs',
              'tables','totals','handle_index','retained_handles','actor_frontiers','original_extraction',
              'payload_retention','counts','invalidated_context_assertions','validation','scope',
              'whole_model_established','first_stage_complete','transformation_authorized'},
              'unknown/missing FD-only publication fields')
        _need(self.manifest['mode']==FD_VALUES_MODE and self.manifest['base']==encode(base.artifact)
              and self.manifest['selected_view']==encode(receipts['selected_manifest'])
              and self.manifest['inputs']=={name:encode(value) for name,value in receipts.items()}
              and self.manifest['run']==encode(base.run),'FD-values-only published scope differs')
        original=docs['original_projection']
        _need(all(self.manifest[field]==original[field] for field in ('tables','totals','handle_index','actor_frontiers'))
              and self.manifest['original_extraction']=={'artifact':encode(receipts['original_projection']),
                  'counts':original['counts'],'raw_files':original['raw_files']},
              'FD-only payload differs from the exact original evidence')
        _need(self.manifest['validation']['container_continuity']=='UNQUALIFIED_NOT_IMPORTED'
              and self.manifest['invalidated_context_assertions']=={
                  'artifact':encode(receipts['original_selected_manifest']),
                  'reason':'CAPTURE_FILTER_COVERAGE_NOT_ESTABLISHED','imported_context_resources':0}
              and all(self.manifest.get(field) is False for field in
                  ('whole_model_established','first_stage_complete','transformation_authorized')),
              'FD-values-only header imports container authority')
        links=[{'original_provider':encode(receipts['original_projection']),'original_uri':chunk['uri'],
                'new_uri':chunk['uri'],'stored_sha256':chunk['physical_sha256'],
                'stored_bytes':chunk['physical_bytes'],'retention':'HARDLINK_SAME_VERIFIED_BYTES'}
               for table in _TABLES for chunk in original['tables'][table]['chunks']]
        _need(self.manifest['payload_retention']==links,'FD-only exact payload retention differs')
        self.base,self.selected_view,self._retained,self._actual=base,r2_view,retained,actual
        self.index=_fd_values_index(self.manifest,base);self.retained={}
        for row in self.manifest['retained_handles']:
            selector=decode(ProviderRecordSelector,row['reference']['selector'])
            identity=decode(HandleBindingID,row['reference']['id'])
            _need(identity in retained and selector==base.selector('handles',selector.ordinal)
                  and r2_view.handles[identity][0]==selector.ordinal
                  and row['selected_record_sha256']==_record_sha(encode(retained[identity]))
                  and selector.ordinal not in self.retained and selector.ordinal not in self.index,
                  'FD-only retained selection differs')
            self.retained[selector.ordinal]=row
        _need(len(self.retained)==len(retained),'FD-only retained scope incomplete')
        _need(self.manifest['counts']=={'base_handles':base.manifest['tables']['handles']['records'],
              'retained_provider_handles':len(retained),'projected_fd_ports':len(self.index),
              'unrefined_legacy_handles':original['counts']['unrefined_legacy_handles'],
              'raw_bytes_read_during_requalification':0,'new_container_bindings':0},
              'FD-only count scope differs')
        return self

    def iter_handle_records(self):
        ports=iter(self.iter_records('fd_ports'));current=next(ports,None);seen=0
        for envelope in self.base.reader.iter_records('handles'):
            ordinal,wire=envelope['ordinal'],envelope['record'];identity=decode(HandleBindingID,wire['id'])
            if identity in self._retained:
                _check_reference(self.base,self.retained[ordinal]['reference'],ordinal,wire)
                result=encode(self._retained[identity]);selection='RETAINED_R2_FD_CONTAINER_UNRESOLVED'
            elif ordinal in self.index:
                _need(current is not None and current['ordinal']==self.index[ordinal],'FD-only ordered port merge differs')
                result=self._refine(ordinal,wire,current['record'],current['ordinal']);seen+=1;current=next(ports,None)
                selection='FD_VALUE_REFINED_CONTAINER_UNRESOLVED'
            else:result=wire;selection='ORIGINAL_UNRESOLVED_FRONTIER'
            _need({k:v for k,v in result.items() if k!='handle'}=={k:v for k,v in wire.items() if k!='handle'},'FD-only nonendpoint changed')
            yield {'ordinal':ordinal,'record':result,'selection':selection,'base_locator':envelope['locator']}
        _need(current is None and seen==len(self.index),'FD-only merged source scope incomplete')

    def record(self,table,ordinal):
        if table=='submissions':return self.selected_view.record(table,ordinal)
        _need(table=='handles','only handles are refined')
        wire=self.base.resolve(self.base.selector('handles',ordinal))['record'];identity=decode(HandleBindingID,wire['id'])
        if identity in self._retained:
            _check_reference(self.base,self.retained[ordinal]['reference'],ordinal,wire)
            return {'record':encode(self._retained[identity]),'selection':'RETAINED_R2_FD_CONTAINER_UNRESOLVED'}
        if ordinal not in self.index:return {'record':wire,'selection':'ORIGINAL_UNRESOLVED_FRONTIER'}
        port_ordinal=self.index[ordinal];port=self.resolve(self.selector('fd_ports',port_ordinal))['record']
        return {'record':self._refine(ordinal,wire,port,port_ordinal),'selection':'FD_VALUE_REFINED_CONTAINER_UNRESOLVED'}


__all__ += ['FDValuesInputs','FD_VALUES_MODE','FD_VALUES_VERSION','requalify_os_fd_values','OSFDValuesProjection']
