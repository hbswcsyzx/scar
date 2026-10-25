"""Read-only, preimage-qualified OS resource refinements over a published R1.

No ProgramSnapshot, complete ExecutionModel, arbitrary patch, source operation,
FD-table epoch, or new work is manufactured. Only two fixed field refinements
are supported. Provider selectors address real chunks/JSONL lines, not arrays.
"""
from collections import OrderedDict
from dataclasses import replace
import hashlib
import io
import json
import os
from pathlib import Path
import re
import secrets

from scar.ir.execution.common import EvidencePoint, Unresolved
from scar.ir.execution.coordinates import ExecutionRun, HostThreadInstance
from scar.ir.execution.ids import (HandleBindingID, NativeHandleLifetimeID,
    ProviderResourceAccessID, WorkTicketID)
from scar.ir.execution.resources import (ExplicitHandle, HandleBinding, HandleNamespace,
    ImplicitBinding, ImportedAt, ProviderAccessPurpose, ProviderHandle, ProviderRecordSelector,
    ProviderResourceAccess, ResourceInstance, RunRealm, ThreadTarget, UnresolvedHandle)
from scar.ir.execution.work import DirectExecution, ExternalWorkSource, WorkSubmission
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.program.resources import ResourceKind, ResourceRole
from scar.ir.record_codec import decode, encode, loads as strict_loads
from scar.trace.os_resources import OSInterfacePartitions
from scar.store.bundle_partitions import BundlePartitions, BundleBudgets, _line


SCHEMA = "scar.os-resource-refinement"
VERSION = 1


def _need(value, message):
    if not value:
        raise ValueError("OS resource refinement: " + message)


def _identity(kind, fields):
    raw = json.dumps(fields, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return kind("provider-r2:" + hashlib.sha256(raw).hexdigest())


class OSResourceBase:
    """Explicit original base plus bounded public selector resolver.

    This first adapter binds the original publication path. A moved copy does
    not silently acquire the old URI from a hash; relocation needs a separate
    future receipt adapter. Selector URIs are never opened.
    """
    def __init__(self, manifest, *, budgets=None, cached_chunks=2):
        _need(type(cached_chunks) is int and 1 <= cached_chunks <= 8, "invalid bounded chunk cache")
        self.reader = OSInterfacePartitions(manifest, budgets=budgets)
        receipt = self.reader.manifest_receipt
        actual = ProviderArtifact(receipt["path"], receipt["physical_sha256"], receipt["physical_bytes"],
                                  self.reader.manifest["schema"])
        self.artifact = actual
        self.manifest = self.reader.manifest
        _need(self.manifest["fragment"] == {"schema": "scar.os-resource-fragment", "schema_version": 2},
              "only the explicit R1 schema2 provider is supported")
        self.run = decode(ExecutionRun, self.manifest["run"])
        self.cache, self.cached_chunks = OrderedDict(), cached_chunks

    def selector(self, table, ordinal, pointer="/record"):
        _need(table in self.manifest["tables"] and type(ordinal) is int and ordinal >= 0, "invalid original table/ordinal")
        chunks = self.manifest["tables"][table]["chunks"]
        found = [(number, chunk) for number, chunk in enumerate(chunks)
                 if chunk["first_ordinal"] <= ordinal <= chunk["last_ordinal"]]
        _need(len(found) == 1, "ordinal has no unique original chunk")
        number, chunk = found[0]
        return ProviderRecordSelector(ProviderFactReference(self.artifact,
            f"#/tables/{table}/chunks/{number}"), table, ordinal,
            ordinal - chunk["first_ordinal"] + 1, pointer)

    def resolve(self, selector):
        """Verify whole bounded chunk, exact ordinal/line, then line-local pointer."""
        _need(type(selector) is ProviderRecordSelector and selector.chunk.artifact == self.artifact,
              "selector belongs to another original manifest namespace/receipt")
        _need(selector == self.selector(selector.table, selector.ordinal, selector.pointer_within_line),
              "selector chunk/line/ordinal differs from its exact declaration")
        number = int(selector.chunk.locator.rsplit("/", 1)[1])
        chunk = self.manifest["tables"][selector.table]["chunks"][number]
        key = selector.table, number
        if key not in self.cache:
            self.cache[key] = BundlePartitions._chunk(self.reader, chunk)
            while len(self.cache) > self.cached_chunks:
                self.cache.popitem(last=False)
        self.cache.move_to_end(key)
        stream = io.BytesIO(self.cache[key])
        for _ in range(selector.line):
            raw = stream.readline(self.reader.limits.max_record_bytes + 1)
            _need(raw.endswith(b"\n") and len(raw) <= self.reader.limits.max_record_bytes, "selected line exceeds its bound")
        envelope = strict_loads(raw.decode("utf-8"))
        _need(type(envelope) is dict and set(envelope) == {"ordinal", "record"}
              and type(envelope["ordinal"]) is int and envelope["ordinal"] == selector.ordinal,
              "selected original envelope/ordinal differs")
        value = envelope
        for token in selector.pointer_within_line.split("/")[1:]:
            token = token.replace("~1", "/").replace("~0", "~")
            if type(value) is list:
                _need(re.fullmatch(r"0|[1-9][0-9]*", token) is not None, "array pointer has no exact index")
                index = int(token)
                _need(index < len(value), "array pointer is out of range")
                value = value[index]
            else:
                _need(type(value) is dict and token in value, "line-local field is absent")
                value = value[token]
        locator = {"artifact": dict(chunk), "line": selector.line,
            "pointer_within_line": selector.pointer_within_line,
            "manifest_receipt": dict(self.reader.manifest_receipt)}
        return {"value": value, "record": envelope["record"], "ordinal": selector.ordinal,
            "row_sha256": hashlib.sha256(raw).hexdigest(), "locator": locator,
            "verification": {"whole_chunk_stored_sha_verified": True, "whole_chunk_decoded_sha_verified": True,
                "line_and_ordinal_verified": True, "resource_identity_or_effects_established": False}}

    def preimage(self, table, ordinal):
        selector = self.selector(table, ordinal)
        resolved = self.resolve(selector)
        _need(type(resolved["record"]) is dict and "id" in resolved["record"], "preimage is not an identified original record")
        return {"selector": encode(selector), "row_sha256": resolved["row_sha256"],
                "id": resolved["record"]["id"]}, resolved["record"]

    def check_preimage(self, preimage, table):
        _need(type(preimage) is dict and set(preimage) == {"selector", "row_sha256", "id"}, "invalid fixed preimage fields")
        selector = decode(ProviderRecordSelector, preimage["selector"])
        _need(selector.table == table and selector.pointer_within_line == "/record", "preimage must address its entire original record")
        resolved = self.resolve(selector)
        _need(resolved["row_sha256"] == preimage["row_sha256"] and resolved["record"]["id"] == preimage["id"],
              "original record preimage changed")
        return selector, resolved["record"]


class OSResourceRefinement:
    """Fixed immutable base/refinement selection; never a complete model."""
    def __init__(self, base, document):
        _need(type(base) is OSResourceBase and type(document) is dict, "explicit original base/document required")
        _need(document.get("schema") == SCHEMA and type(document.get("schema_version")) is int
              and document["schema_version"] == VERSION and document.get("status") == "PUBLISHED",
              "unsupported/unpublished refinement")
        _need(set(document) == {"schema", "schema_version", "status", "base", "run", "base_references",
            "provider_accesses", "handle_refinements", "executor_refinements", "frontiers", "scope", "counts",
            "execution_capability_version", "complete_execution_model", "program_snapshot_created",
            "whole_model_established", "first_stage_complete", "transformation_authorized"}, "unknown/missing fixed refinement fields")
        _need(document["base"] == encode(base.artifact) and document["run"] == encode(base.run), "refinement belongs to another base/run")
        _need(document.get("whole_model_established") is False and document.get("transformation_authorized") is False
              and document.get("first_stage_complete") is False and document.get("complete_execution_model") is False
              and document.get("program_snapshot_created") is False and document.get("execution_capability_version") == 9,
              "refinement overstates its authority")
        self.base, self.document = base, document
        self.handles, self.executors, self.work, self.resources, self.threads = {}, {}, {}, {}, {}
        _need(set(document["base_references"]) == {"submissions", "resources", "threads"}, "unknown qualified base table")
        for table, registry, kind in (("submissions", self.work, WorkSubmission), ("resources", self.resources, ResourceInstance),
                                      ("threads", self.threads, HostThreadInstance)):
            for reference in document["base_references"][table]:
                _, wire = base.check_preimage(reference, table)
                row = decode(kind, wire)
                _need(row.id not in registry, "duplicate qualified base reference")
                registry[row.id] = row
        accesses = tuple(decode(ProviderResourceAccess, wire) for wire in document["provider_accesses"])
        self.accesses = {row.id: row for row in accesses}
        _need(len(self.accesses) == len(accesses), "duplicate provider access identity")
        lifetimes = set()
        for entry in document["handle_refinements"]:
            _need(type(entry) is dict and set(entry) == {"preimage", "replacement"}, "unknown handle refinement fields")
            selector, original = base.check_preimage(entry["preimage"], "handles")
            previous, replacement = decode(HandleBinding, original), decode(HandleBinding, entry["replacement"])
            _need(type(previous.handle) is UnresolvedHandle and type(replacement.handle) is ProviderHandle,
                  "only unresolved-to-provider handle refinement is supported")
            _need({k: v for k, v in original.items() if k != "handle"} ==
                  {k: v for k, v in entry["replacement"].items() if k != "handle"}, "handle refinement changed another field")
            selected = base.resolve(replacement.handle.selector)
            value = selected["value"]
            _need(type(value) is int and value >= 0 and replacement.target.instance in self.resources,
                  "provider handle selector/qualified original target is invalid")
            port_match = re.fullmatch(r"/record/created_handles/(0|[1-9][0-9]*)/fd", replacement.handle.selector.pointer_within_line)
            _need(replacement.handle.selector.table == "observations" and port_match is not None,
                  "provider FD requires an actual declared output port selector")
            ports = selected["record"].get("created_handles", ())
            index = int(port_match[1])
            _need(index < len(ports) and ports[index]["binding"] == previous.id.wire
                  and ports[index]["target"] == previous.target.instance.wire and ports[index]["fd"] == value,
                  "selected FD port does not identify this original handle/target")
            resource = self.resources[previous.target.instance]
            _need(resource.kind is ResourceKind.FILE and resource.role is ResourceRole.OPEN_FILE_DESCRIPTION
                  and resource.source == previous.source and type(resource.origin) is ImportedAt
                  and resource.origin.point == previous.start, "original OFD producer differs from its handle")
            _need(type(replacement.handle.container) is Unresolved and replacement.handle.container.point == previous.start
                  and replacement.handle.source == previous.source
                  and replacement.handle.namespace.realm == RunRealm(base.run.id)
                  and replacement.handle.namespace.protocol == ProviderFactReference(
                      decode(ProviderArtifact, base.manifest["protocol_artifact"]), "#/contract/interface_work"),
                  "R2.1 cannot invent a table epoch, source, or namespace")
            _need(replacement.handle.lifetime not in lifetimes, "distinct created ports cannot share a handle lifetime")
            lifetimes.add(replacement.handle.lifetime)
            _need(previous.id not in self.handles, "conflicting handle refinements")
            self.handles[previous.id] = (selector.ordinal, replacement)
        output_handles = set()
        for access in accesses:
            _need(access.work in self.work and access.point.run == base.run.id, "provider access has no exact qualified work/run")
            source = self.work[access.work].origin
            _need(type(source) is ExternalWorkSource, "OS provider work requires its original external entry")
            _need(access.point.process == source.point.process, "provider access changed its work process/None frontier")
            resolved = base.resolve(access.selector)
            _need(resolved["record"].get("work_ticket") == access.work.value, "provider selector belongs to another actual work")
            if access.purpose is ProviderAccessPurpose.OUTPUT_SELECTOR:
                _need(type(access.handle) is ExplicitHandle and access.handle.binding in self.handles,
                      "output selector has no exact refined base handle")
                handle = self.handles[access.handle.binding][1]
                _need(handle.id not in output_handles, "duplicate output association for one original producer port")
                output_handles.add(handle.id)
                _need(access.target == handle.target and access.point == handle.start and access.source == handle.source,
                      "output association changed its handle target/point/source")
                _need(access.selector == handle.handle.selector, "output and handle selectors differ")
            elif access.purpose is ProviderAccessPurpose.EXECUTOR:
                work = self.work[access.work]
                _need(type(access.target) is ThreadTarget and access.target.thread in self.threads
                      and type(work.scheduling) is DirectExecution and work.scheduling.thread == access.target.thread,
                      "executor has no exact original native-thread scheduling")
                _need(access.selector.table == "observations" and access.selector.pointer_within_line == "/record/tid"
                      and access.point == source.point and access.source == source.source,
                      "executor requires the actual native TID slot and original submission point/source")
                thread = self.threads[access.target.thread]
                _need(type(resolved["value"]) is int and resolved["value"] == thread.tid and thread.process == access.point.process,
                      "executor selector/process does not match its native thread")
            else:
                raise ValueError("R2.1 does not yet recover INPUT_SELECTOR dependencies")
        _need(output_handles == set(self.handles), "a refined handle has no unique output association")
        for entry in document["executor_refinements"]:
            _need(type(entry) is dict and set(entry) == {"preimage", "executor"}, "unknown executor refinement fields")
            selector, original = base.check_preimage(entry["preimage"], "submissions")
            previous = decode(WorkSubmission, original)
            identity = decode(ProviderResourceAccessID, entry["executor"])
            access = self.accesses.get(identity)
            _need(type(previous.executor) is Unresolved and access is not None and access.work == previous.id
                  and access.purpose is ProviderAccessPurpose.EXECUTOR, "invalid fixed executor refinement")
            _need(previous.id not in self.executors, "conflicting executor refinements")
            self.executors[previous.id] = (selector.ordinal, replace(previous, executor=identity))
        _need(document["counts"] == {"observations_scanned": base.manifest["summary"]["syscall_observations"],
            "created_ports": len(self.handles), "handle_refinements": len(self.handles),
            "provider_accesses": len(self.accesses), "executor_refinements": len(self.executors)}
              and len(self.handles) == base.manifest["summary"]["actual_fd_producer_ports"],
              "refinement scope/counters differ from the actual declared producer ports")

    @classmethod
    def read(cls, base, path, *, max_bytes=4_000_000):
        path = Path(path)
        _need(type(max_bytes) is int and max_bytes > 0 and path.is_file() and not path.is_symlink(),
              "refinement must be an explicitly supplied regular file")
        with path.open("rb") as stream:
            payload = stream.read(max_bytes + 1)
        _need(len(payload) <= max_bytes, "refinement document budget exceeded")
        return cls(base, strict_loads(payload.decode("utf-8")))

    def record(self, table, ordinal):
        """Return exactly one selected record, preserving original base identity."""
        _need(table in ("handles", "submissions"), "only two explicitly refined tables are supported")
        selector = self.base.selector(table, ordinal)
        original = self.base.resolve(selector)["record"]
        kind, replacements = (HandleBinding, self.handles) if table == "handles" else (WorkSubmission, self.executors)
        row = decode(kind, original)
        replacement = replacements.get(row.id)
        _need(replacement is None or replacement[0] == ordinal, "refinement ordinal identity conflict")
        return {"record": encode(replacement[1]) if replacement is not None else original,
                "selection": "REFINED" if replacement is not None else "BASE", "base_selector": encode(selector)}


def build_os_resource_refinement(base, fresh_out, *, executor_observation_ordinals=(),
                                 max_observations=2_000_000, max_ports=128, max_executors=8,
                                 max_document_bytes=4_000_000, progress=None):
    """Recover existing declared created_handles ports and selected executors.

    This first scope is explicit: existing open/openat legacy ports and shared
    FD/VM/context recovery are not claimed. No raw workload is executed/read.
    """
    _need(type(base) is OSResourceBase and all(type(x) is int and x > 0 for x in
        (max_observations, max_ports, max_executors, max_document_bytes)), "invalid base/budgets")
    selected_executors = set(executor_observation_ordinals)
    _need(all(type(x) is int and x >= 0 for x in selected_executors) and len(selected_executors) <= max_executors,
          "invalid bounded executor selections")
    rule = ProviderFactReference(decode(ProviderArtifact, base.manifest["protocol_artifact"]), "#/contract/interface_work")
    artifacts = tuple(decode(ProviderArtifact, e["record"]) for e in base.reader.iter_records("artifacts"))
    threads, thread_ordinals = {}, {}
    for envelope in base.reader.iter_records("threads"):
        thread = decode(HostThreadInstance, envelope["record"])
        threads[thread.id], thread_ordinals[thread.id] = thread, envelope["ordinal"]
    ports, executor_rows, scanned, work_ordinal = [], [], 0, 0
    for envelope in base.reader.iter_records("observations"):
        scanned += 1
        _need(scanned <= max_observations, "observation scope budget exceeded")
        row = envelope["record"]
        if row.get("interface_record") is not True:
            continue
        for index, port in enumerate(row.get("created_handles", ())):
            _need(len(ports) < max_ports, "created port budget exceeded")
            ports.append((envelope["ordinal"], work_ordinal, row, index, port))
        if envelope["ordinal"] in selected_executors:
            executor_rows.append((envelope["ordinal"], work_ordinal, row))
        work_ordinal += 1
        if progress is not None and scanned % 100_000 == 0:
            progress({"phase": "OBSERVATIONS", "records": scanned, "created_ports": len(ports)})
    _need(scanned == base.manifest["summary"]["syscall_observations"]
          and work_ordinal == base.manifest["tables"]["submissions"]["records"]
          and len(executor_rows) == len(selected_executors), "original observation/work/executor denominator differs")
    wanted_handles = {port[4]["binding"] for port in ports}
    handle_preimages = {}
    for envelope in base.reader.iter_records("handles"):
        row = envelope["record"]
        if row["id"]["wire"] in wanted_handles:
            handle_preimages[row["id"]["wire"]] = base.preimage("handles", envelope["ordinal"])
    _need(set(handle_preimages) == wanted_handles, "created port handle is absent from the original base")
    references, work_records, additions, handle_changes, executor_changes, frontiers = {}, {}, [], [], [], []
    def work_at(ordinal, observation):
        identity = WorkTicketID(observation["work_ticket"])
        if identity in work_records:
            _need(decode(ProviderRecordSelector, references[identity]["selector"]).ordinal == ordinal,
                  "same work identity appeared at another original ordinal")
            return work_records[identity]
        reference, wire = base.preimage("submissions", ordinal)
        work = decode(WorkSubmission, wire)
        expected = ProviderFactReference(artifacts[observation["entry_source"]["artifact"]],
            "#/lines/" + str(observation["entry_source"]["line"]))
        _need(work.id == WorkTicketID(observation["work_ticket"]) and type(work.origin) is ExternalWorkSource
              and work.origin.point.run == base.run.id and work.origin.point.source == expected
              and (work.origin.point.process.wire if work.origin.point.process is not None else None) == observation["process"],
              "selected actual work does not match the exact original interface source/run/process")
        references[work.id] = reference; work_records[work.id] = work
        return work
    targets = set()
    for observation_ordinal, ordinal, observation, index, port in ports:
        work = work_at(ordinal, observation)
        preimage, wire = handle_preimages[port["binding"]]
        original = decode(HandleBinding, wire)
        _need(type(original.handle) is UnresolvedHandle and original.target.instance.wire == port["target"]
              and type(original.start) is EvidencePoint, "producer port differs from its original handle/target")
        selector = base.selector("observations", observation_ordinal, f"/record/created_handles/{index}/fd")
        _need(base.resolve(selector)["value"] == port["fd"] and type(port["fd"]) is int and port["fd"] >= 0,
              "created FD selector differs from its actual numeric port")
        lifetime = _identity(NativeHandleLifetimeID, {"base": base.artifact.sha256, "preimage": preimage, "port": index})
        endpoint = ProviderHandle(HandleNamespace(RunRealm(base.run.id), rule),
            Unresolved("R1 did not export an exact FD-table incarnation receipt; TID/table_status cannot substitute", original.start),
            selector, lifetime, original.source)
        handle_changes.append({"preimage": preimage, "replacement": encode(replace(original, handle=endpoint))})
        identity = _identity(ProviderResourceAccessID, {"base": base.artifact.sha256, "selector": encode(selector), "purpose": "OUTPUT_SELECTOR"})
        additions.append(ProviderResourceAccess(identity, work.id, ProviderAccessPurpose.OUTPUT_SELECTOR,
            original.target, ExplicitHandle(original.id), original.start, selector, original.source))
        targets.add(original.target.instance)
    used_threads = {}
    for observation_ordinal, ordinal, observation in executor_rows:
        work = work_at(ordinal, observation)
        if type(work.scheduling) is not DirectExecution or type(work.scheduling.thread) is Unresolved:
            frontiers.append({"code": "EXECUTOR_NATIVE_THREAD_UNRESOLVED", "observation_ordinal": observation_ordinal})
            continue
        thread = threads.get(work.scheduling.thread)
        _need(thread is not None and thread.tid == observation["tid"] and thread.process == work.origin.point.process,
              "selected executor has no exact original native-thread/process")
        selector = base.selector("observations", observation_ordinal, "/record/tid")
        identity = _identity(ProviderResourceAccessID, {"base": base.artifact.sha256, "selector": encode(selector), "purpose": "EXECUTOR"})
        additions.append(ProviderResourceAccess(identity, work.id, ProviderAccessPurpose.EXECUTOR,
            ThreadTarget(thread.id), ImplicitBinding(rule, ()), work.origin.point, selector, work.origin.source))
        executor_changes.append({"preimage": references[work.id], "executor": encode(identity)})
        used_threads[thread.id] = base.preimage("threads", thread_ordinals[thread.id])[0]
    resource_refs = []
    for envelope in base.reader.iter_records("resources"):
        row = decode(ResourceInstance, envelope["record"])
        if row.id in targets:
            resource_refs.append(base.preimage("resources", envelope["ordinal"])[0])
    _need(len(resource_refs) == len(targets), "original target resource has no unique base record")
    document = {"schema": SCHEMA, "schema_version": VERSION, "status": "PUBLISHED",
        "base": encode(base.artifact), "run": encode(base.run),
        "base_references": {"submissions": list(references.values()), "resources": resource_refs,
                            "threads": list(used_threads.values())},
        "provider_accesses": encode(tuple(additions)), "handle_refinements": handle_changes,
        "executor_refinements": executor_changes, "frontiers": frontiers,
        "scope": "R1 declared created_handles ports + explicitly selected executor observations; not all descriptors",
        "counts": {"observations_scanned": scanned, "created_ports": len(ports), "handle_refinements": len(handle_changes),
            "provider_accesses": len(additions), "executor_refinements": len(executor_changes)},
        "execution_capability_version": 9, "complete_execution_model": False, "program_snapshot_created": False,
        "whole_model_established": False, "first_stage_complete": False, "transformation_authorized": False}
    OSResourceRefinement(base, document)  # Exact selected preimages/typed endpoints, no fake snapshot.
    limits = BundleBudgets(max_record_bytes=max_document_bytes,
        max_chunk_decoded_bytes=max(16_000_000, max_document_bytes), max_manifest_bytes=max_document_bytes)
    payload = _line(document, limits)
    out = Path(fresh_out).absolute(); out.mkdir(mode=0o700, parents=False, exist_ok=False)
    temporary = out / (".refinement." + secrets.token_hex(16) + ".tmp")
    with temporary.open("xb") as stream:
        stream.write(payload); stream.flush(); os.fsync(stream.fileno())
    os.link(temporary, out / "manifest.json"); temporary.unlink()
    return {"document": document, "manifest_receipt": {"path": str(out / "manifest.json"),
        "physical_sha256": hashlib.sha256(payload).hexdigest(), "physical_bytes": len(payload)}}


__all__ = ["OSResourceBase", "OSResourceRefinement", "build_os_resource_refinement"]
