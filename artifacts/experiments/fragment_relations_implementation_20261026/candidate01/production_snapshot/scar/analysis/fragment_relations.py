"""Fixed retained-artifact producer for qualified cross-fragment relations.

The disposable SQLite locator index does not own facts.  Static code/source
versions, execution occurrences and physical work remain separate endpoints.
No raw collector, target, compiler or source lowerer is called here.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, fields, replace
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import zlib

from scar.ir.execution.fragment_relations import (
    Encoding, EvidenceEdgeRef, EvidenceInstanceRef, FragmentLocator, HostRelationKind,
    InvocationRef, InvocationStaticBinding, NativeSourceContextRelation, QualifiedOccurrenceRef,
    RelationGap, RuntimeScope, StaticEntityRef, WorkActivityProjectionLink, WorkHostRelation,
    WorkRelations, WorkTicketRef, canonical, exact, need, stable_key,
)
from scar.ir.execution.content import WorkEvidenceBinding
from scar.ir.execution.coordinates import ExecutionRun
from scar.ir.execution.ids import ProcessInstanceID, RunID, WorkTicketID
from scar.ir.execution.model import LegacyOperationRef
from scar.ir.execution.work import ExternalWorkSource, WorkQuiescence, WorkSubmission
from scar.ir.program.call_edges import CallLinkStatus, CapturedCode, CodeCapture, CodeSourceLink, InvocationKey
from scar.ir.program.ids import RegionID
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.program.source_references import SourceArtifactLocator, SourceDefinitionReference
from scar.ir.record_codec import decode, encode, loads as strict_loads
from scar.ir.v2.evidence import OperationInstance
from scar.ir.v2.ids import OperationInstanceID
from scar.store.bundle_partitions import BundlePartitions
from scar.store.fragment_relations import read_payload


@dataclass(frozen=True, slots=True)
class FragmentInputs:
    work_manifest: ProviderArtifact
    original_eeg_manifest: ProviderArtifact
    native_batch_report: ProviderArtifact
    source_report: ProviderArtifact
    dispatch_report: ProviderArtifact
    coordinates: ProviderArtifact

    def __post_init__(self):
        for f in fields(self):
            exact(getattr(self, f.name), ProviderArtifact, f.name)
        need(self.coordinates.schema == "scar.capture-coordinates", "coordinates schema")


def _source_files():
    root = Path(__file__).resolve().parents[2]
    return tuple(root / name for name in ("scar/ir/execution/fragment_relations.py",
        "scar/ir/execution/fragment_relations_codec.py", "scar/store/fragment_relations.py",
        "scar/analysis/fragment_relations.py", "scar/analysis/source_native_composition.py"))


def _code_receipts():
    return [{"path": str(p), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            for p in _source_files() for raw in (p.read_bytes(),)]


def _pointer(document, pointer):
    need(pointer == "#" or pointer.startswith("#/"), "JSON pointer required")
    value = document
    for part in pointer[2:].split("/") if pointer != "#" else ():
        part = part.replace("~1", "/").replace("~0", "~")
        value = value[int(part)] if type(value) is list else value[part]
    return value


def _document(artifact, meter, cache):
    key = (artifact.uri, artifact.sha256, artifact.size_bytes, artifact.schema)
    if key not in cache:
        cache[key] = strict_loads(read_payload(artifact, meter).decode())
    return cache[key]


def _locator(artifact, desc, declaration, *, line=None, pointer="#", compressed=None):
    compressed = desc.get("compression") == "gzip" if compressed is None else compressed
    encoding = (Encoding.GZIP_JSONL if compressed else Encoding.JSONL) if line is not None else (
        Encoding.GZIP_JSON if compressed else Encoding.JSON)
    return FragmentLocator(artifact, desc.get("decoded_sha256", artifact.sha256),
        desc.get("decoded_bytes", artifact.size_bytes), encoding, line, pointer, declaration)


def _artifact(desc, schema):
    return ProviderArtifact(desc["uri"], desc["stored_sha256"], desc["stored_bytes"], schema)


def _source_locator_value(locator, meter, cache):
    if type(locator) is FragmentLocator:
        return _read_locator(locator, meter, cache, code_source=True)
    exact(locator, SourceArtifactLocator, "original static source locator")
    key = (locator.artifact.uri, locator.artifact.sha256, locator.decoded_sha256)
    if key not in cache:
        payload = read_payload(locator.artifact, meter, decoded_bytes=locator.decoded_bytes,
            decoded_sha256=locator.decoded_sha256, compressed=locator.representation == "gzip-canonical-json",
            maximum=meter.budget.max_metadata_bytes, code_source=True)
        cache[key] = strict_loads(payload.decode())
    return _pointer(cache[key], locator.pointer)


def _read_locator(locator, meter, cache, *, code_source=False):
    exact(locator, FragmentLocator, "fragment locator")
    key = stable_key((locator.artifact, locator.decoded_sha256, locator.encoding))
    if key not in cache:
        cache[key] = read_payload(locator.artifact, meter, decoded_bytes=locator.decoded_bytes,
            decoded_sha256=locator.decoded_sha256,
            compressed=locator.encoding in (Encoding.GZIP_JSON, Encoding.GZIP_JSONL),
            maximum=max(meter.budget.max_metadata_bytes, meter.budget.max_input_chunk_bytes), code_source=code_source)
    raw = cache[key]
    if locator.line is not None:
        lines = raw.splitlines(keepends=True)
        need(locator.line <= len(lines), "locator line absent")
        raw = lines[locator.line - 1]
        need(raw.endswith(b"\n") and len(raw) <= meter.budget.max_record_bytes, "locator record bound")
    return _pointer(strict_loads(raw.decode()), locator.pointer)


def _static_locator(value, declaration):
    """Two existing producer contracts, not guessed interchangeable fields."""
    need(type(value) is dict, "static locator object")
    if set(value) == {"artifact", "decoded_sha256", "decoded_bytes", "representation", "pointer", "declaration"}:
        return decode(SourceArtifactLocator, value)
    need(set(value) in ({"artifact", "pointer"}, {"artifact", "pointer", "namespace"}), "unsupported original inventory locator")
    a = value["artifact"]
    need(set(a) == {"uri", "physical_sha256", "physical_bytes", "decoded_sha256", "decoded_bytes", "representation"}, "inventory artifact fields")
    need(a["representation"] in ("scar.inventory-component/1", "scar.source-program/5", "scar.body-construction-checkpoint/1", "scar.body-construction-checkpoint/2")
         and a["uri"].endswith(".json.gz"), "unsupported inventory artifact representation")
    artifact = ProviderArtifact(a["uri"], a["physical_sha256"], a["physical_bytes"], a["representation"])
    return FragmentLocator(artifact, a["decoded_sha256"], a["decoded_bytes"], Encoding.GZIP_JSON, None, value["pointer"], declaration)


class _Index:
    def __init__(self, path):
        self.path = path
        self.db = sqlite3.connect(path)
        self.db.executescript("""
        PRAGMA cache_size=-2048;
        PRAGMA temp_store=FILE;
        PRAGMA journal_mode=OFF;
        CREATE TABLE nodes(id TEXT PRIMARY KEY, ordinal INTEGER UNIQUE, digest TEXT,
          process TEXT, thread TEXT, parent TEXT, rawref TEXT, category TEXT, correlation TEXT, external_id TEXT);
        CREATE TABLE edges(id TEXT PRIMARY KEY, ordinal INTEGER UNIQUE, relation TEXT,
          source TEXT,target TEXT,digest TEXT);
        CREATE INDEX edge_target ON edges(target,relation);
        CREATE TABLE native(instance TEXT, sequence INTEGER, ref TEXT, PRIMARY KEY(instance,sequence));
        CREATE TABLE source(sequence INTEGER, phase TEXT, line INTEGER UNIQUE, payload BLOB,
          PRIMARY KEY(sequence,phase));
        """)

    def close(self):
        self.db.commit(); self.db.close()


class FragmentRelationProducer:
    """One construction, exact catalog and frozen producer policy."""
    def __init__(self, inputs):
        exact(inputs, FragmentInputs, "fixed input catalog")
        self.inputs, self._initial_code = inputs, _code_receipts()
        self._stats = {}
        self._finished = self._started = False
        self._cache = {}

    def catalog_document(self):
        return encode(self.inputs)

    def producer_receipts(self):
        need(_code_receipts() == self._initial_code, "producer source changed during construction")
        return self._initial_code

    def _watch(self, path):
        p = Path(path); s = p.stat()
        need(not p.is_symlink(), "symlink input")
        before = (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        need(str(p) not in self._stats or self._stats[str(p)] == before, "input changed between reads")
        self._stats[str(p)] = before

    def finish(self):
        need(self._finished, "producer did not finish its full work denominator")
        for p in tuple(self._stats):
            self._watch(p)
        self.producer_receipts()

    def _roots(self, meter):
        roots = {}
        for f in fields(self.inputs):
            a = getattr(self.inputs, f.name); self._watch(a.uri)
            roots[f.name] = _document(a, meter, self._cache)
        w, e, n, s, d, c = (roots[f.name] for f in fields(self.inputs))
        need(w.get("schema") == "scar.native-activity-work-report" and w.get("schema_version") in (1, 2), "unsupported native activity work contract")
        need(e.get("schema") == "scar.partitioned-ir-bundle" and e.get("schema_version") == 1, "original EEG storage contract")
        need(n.get("schema") == "scar.native-capture-batch" and n.get("schema_version") == 2
             and n.get("unvisited_actual_groups") == 0, "completed native batch required")
        need(s.get("schema") == "scar.source-invocations" and s.get("schema_version") == 3
             and d.get("schema") == "scar.dispatch-source-associations" and d.get("schema_version") == 3, "current source/dispatch v3 required")
        run = decode(ExecutionRun, s["run"])
        need(d["run"] == s["run"] == c["run"] and w["run"] == encode(run.id)
             and n["run"] == run.id.value, "input roots cross Runs")
        process = decode(ProcessInstanceID, w["process"])
        need(c["target_process"] == w["process"] and s["coordinate_binding"] == d["coordinate_binding"] == encode(self.inputs.coordinates), "input process/coordinate roots differ")
        need(d["source_report"] == encode(self.inputs.source_report) and d["source_inputs"] == s["source_inputs"], "source snapshot composition differs")
        need(w["original_eeg_manifest"] == {"path": self.inputs.original_eeg_manifest.uri,
            "physical_bytes": self.inputs.original_eeg_manifest.size_bytes,
            "physical_sha256": self.inputs.original_eeg_manifest.sha256}, "work original EEG namespace differs")
        need(w["coordinates"]["sha256"] == self.inputs.coordinates.sha256
             and w["coordinates"]["size_bytes"] == self.inputs.coordinates.size_bytes, "work coordinate payload differs")
        need(w["qualified_single_activities"] + sum(w["frontier_counts"].values()) == w["all_gpu_candidates"], "independent physical-work/frontier denominator differs")
        self.scope = RuntimeScope(run.id, process, self.inputs.coordinates)
        self.roots = roots
        self.pid = next(row["pid"] for row in c["processes"] if row["id"] == w["process"])
        need(type(self.pid) is int and self.pid > 0, "target process PID")
        return roots

    def _bundle_index(self, index, meter):
        producer = self
        class Counted(BundlePartitions):
            def _chunk(self, descriptor):
                p = self.root / descriptor["uri"]; producer._watch(p)
                a = ProviderArtifact(str(p), descriptor["physical_sha256"], descriptor["physical_bytes"], "scar.original-eeg-chunk")
                return read_payload(a, meter, decoded_bytes=descriptor["decoded_bytes"], decoded_sha256=descriptor["decoded_sha256"],
                    compressed=True, maximum=meter.budget.max_input_chunk_bytes)
        meter.charge(stored=self.inputs.original_eeg_manifest.size_bytes, decoded=self.inputs.original_eeg_manifest.size_bytes)
        bundle = Counted(self.inputs.original_eeg_manifest.uri)
        self.bundle = bundle
        counts = Counter()
        for item in bundle.iter_records("evidence", "instances"):
            row = item["record"]; instance = decode(OperationInstance, row)
            metadata = row["metadata"]
            index.db.execute("INSERT INTO nodes VALUES(?,?,?,?,?,?,?,?,?,?)", (
                instance.id.wire, item["ordinal"], hashlib.sha256(canonical(row)).hexdigest(),
                json.dumps(instance.process_id), json.dumps(metadata.get("eto_tid", metadata.get("raw_tid"))), None if instance.parent is None else instance.parent.wire,
                metadata.get("raw_reference"), metadata.get("category"), json.dumps(metadata.get("correlation")), json.dumps(metadata.get("external_id"))))
            counts["instances_visited"] += 1
        for item in bundle.iter_records("evidence", "edges"):
            row = item["record"]; counts["edges_visited"] += 1
            if row["relation"] not in ("submits_work", "provider_scope_association"):
                continue
            need(set(row) == {"edge_id", "relation", "source", "target", "evidence"}
                 and row["source"]["kind"] == row["target"]["kind"] == "operation_instance", "provider edge endpoints differ")
            source = decode(OperationInstanceID, row["source"]["reference"])
            target = decode(OperationInstanceID, row["target"]["reference"])
            from scar.ir.v2.common import EvidenceClaim
            decode(EvidenceClaim, row["evidence"])
            index.db.execute("INSERT INTO edges VALUES(?,?,?,?,?,?)", (row["edge_id"], item["ordinal"], row["relation"], source.wire, target.wire, hashlib.sha256(canonical(row)).hexdigest()))
            counts["provider_edges_indexed"] += 1
        need(index.db.execute("SELECT 1 FROM edges e LEFT JOIN nodes a ON a.id=e.source LEFT JOIN nodes b ON b.id=e.target WHERE a.id IS NULL OR b.id IS NULL LIMIT 1").fetchone() is None, "provider edge has missing original endpoint")
        index.db.commit()
        return dict(counts)

    def _original_locator(self, table, ordinal):
        chunks = self.bundle.manifest["graphs"]["evidence"]["tables"][table]["chunks"]
        for number, d in enumerate(chunks):
            if d["first_ordinal"] <= ordinal <= d["last_ordinal"]:
                artifact = ProviderArtifact(str(self.bundle.root / d["uri"]), d["physical_sha256"], d["physical_bytes"], "scar.original-eeg-" + table + ".jsonl")
                desc = {"decoded_bytes": d["decoded_bytes"], "decoded_sha256": d["decoded_sha256"], "compression": "gzip"}
                return _locator(artifact, desc, ProviderFactReference(self.inputs.original_eeg_manifest,
                    "#/graphs/evidence/tables/" + table + "/chunks/" + str(number)), line=ordinal - d["first_ordinal"] + 1, pointer="#/record")
        raise ValueError("original EEG ordinal absent")

    def _node(self, index, identifier):
        row = index.db.execute("SELECT ordinal FROM nodes WHERE id=?", (identifier,)).fetchone()
        need(row is not None, "original EEG identity missing")
        value = identifier.removeprefix("opinst:")
        return EvidenceInstanceRef(self._original_locator("instances", row[0]), OperationInstanceID(value))

    def _edge(self, row):
        identity, ordinal, relation, source, target, _ = row
        return EvidenceEdgeRef(self._original_locator("edges", ordinal), identity, relation,
            OperationInstanceID(source.removeprefix("opinst:")), OperationInstanceID(target.removeprefix("opinst:")))

    def _native_index(self, index, meter):
        from scar.ir.execution.codec import loads as execution_loads
        from scar.ir.program.codec import loads as program_loads
        from scar.ir.program.model import TerminatorKind
        n = self.roots["native_batch_report"]
        shared = decode(ProviderArtifact, n["shared_program"])
        self._watch(shared.uri)
        program = program_loads(read_payload(shared, meter).decode())
        ops = {op.id: op for op in program.operations}
        regions = {r.id: r for r in program.regions}
        counts = Counter()
        for shard in n["shards"]:
            meter.check()
            artifact = decode(ProviderArtifact, shard["execution"]); self._watch(artifact.uri)
            execution = execution_loads(read_payload(artifact, meter, maximum=meter.budget.max_input_chunk_bytes).decode())
            need(execution.snapshot.artifact == shared and encode(execution.snapshot) == shard["program_snapshot"], "native snapshot differs")
            need(any(r.id == self.scope.run for r in execution.runs)
                 and any(p.id == self.scope.process and p.run == self.scope.run and p.pid == self.pid for p in execution.processes), "native Run/process differs")
            projection = decode(ProviderArtifact, shard["evidence_projection"]); self._watch(projection.uri)
            projected = _document(projection, meter, self._cache)
            projected_ids = {r["id"]["wire"]: r for r in projected["instances"]}
            sequence = {"native-port:" + self.scope.run.value + ":" + str(s): s for s in shard["sequences"]}
            activations = {a.id: a for a in execution.activations}; segments = {s.id: s for s in execution.segments}
            visits = {v.id: v for v in execution.visits}; bindings = {b.operation: b for b in execution.evidence_bindings}
            for occurrence in execution.operations:
                op = ops[occurrence.operation]
                if op.terminator is None or op.terminator.kind is not TerminatorKind.INVOKE:
                    continue
                activation = activations[segments[visits[occurrence.visit].segment].activation]
                need(activation.process == self.scope.process and activation.id.value in sequence, "native activation sequence/process differs")
                region = regions[activation.region]
                need(visits[occurrence.visit].block == region.entry
                     and any(b.id == region.entry and op.id in b.operations for b in region.blocks), "native occurrence is not its canonical entry INVOKE")
                binding = bindings[occurrence.id]
                need(binding.legacy.artifact == projection, "native original projection differs")
                instance = projected_ids[binding.legacy.instance.wire]
                original = index.db.execute("SELECT digest FROM nodes WHERE id=?", (binding.legacy.instance.wire,)).fetchone()
                need(original is not None and original[0] == hashlib.sha256(canonical(instance)).hexdigest(), "native projection changes original EEG producer")
                need(type(binding.source) is ProviderFactReference and binding.source.artifact.schema == "pytorch.execution-trace.v1"
                     and instance["metadata"]["raw_reference"] == "sha256:" + binding.source.artifact.sha256 + binding.source.locator, "native source fact changes original ETO point")
                ref = QualifiedOccurrenceRef(artifact, occurrence.id, binding)
                index.db.execute("INSERT INTO native VALUES(?,?,?)", (binding.legacy.instance.wire, sequence[activation.id.value], canonical(encode(ref)).decode()))
                counts["invokes_indexed"] += 1
            counts["shards_visited"] += 1
            # Projections are immutable inputs, but no entire model collection is retained in RAM.
            self._cache.pop((projection.uri, projection.sha256, projection.size_bytes, projection.schema), None)
        index.db.commit()
        need(counts["shards_visited"] == len(n["shards"])
             and counts["invokes_indexed"] == n["enumerated_dispatch_groups"], "native occurrence denominator differs")
        return dict(counts)

    def _source_index(self, index, writer, meter):
        d = self.roots["dispatch_report"]; desc = d["observations"]
        path = Path(self.inputs.dispatch_report.uri).parent / desc["path"]
        need(path.name == desc["path"], "unsafe source association path")
        self._watch(path)
        # Writer v3 declares decoded identity, not compressed SHA. Measure the
        # physical representation in this one owned pass; never guess ISIZE.
        stat = path.stat()
        need(stat.st_size <= meter.budget.max_metadata_bytes, "compressed association transport bound before open")
        meter.charge(stored=stat.st_size)
        stored = path.read_bytes(); physical_sha = hashlib.sha256(stored).hexdigest()
        need(len(stored) == stat.st_size, "association physical stat differs")
        sha = hashlib.sha256(); count = size = 0
        with gzip.GzipFile(fileobj=io.BytesIO(stored), mode="rb") as stream:
            while True:
                raw = stream.readline(meter.budget.max_record_bytes + 1)
                if not raw:
                    break
                need(len(raw) <= meter.budget.max_record_bytes and raw.endswith(b"\n"), "source association record bound")
                meter.charge(decoded=len(raw)); sha.update(raw); count += 1; size += len(raw)
                row = strict_loads(raw.decode()); _check_source_row(row, self.inputs, self.roots, self.scope, self.pid)
                index.db.execute("INSERT INTO source VALUES(?,?,?,?)", (row["sequence"], row["phase"], count, zlib.compress(raw, 1)))
        need((size, sha.hexdigest(), count) == (desc["raw_bytes"], desc["raw_sha256"], desc["rows"]), "full source association EOF denominator differs")
        artifact = ProviderArtifact(str(path), physical_sha, len(stored), "scar.dispatch-source-associations.rows")
        declared = ProviderFactReference(self.inputs.dispatch_report, "#/observations")
        self.source_desc = {"decoded_bytes": size, "decoded_sha256": sha.hexdigest(), "compression": "gzip"}
        self.source_artifact, self.source_declaration = artifact, declared
        for line, raw in index.db.execute("SELECT line,payload FROM source ORDER BY line"):
            writer.source_row(_locator(artifact, self.source_desc, declared, line=line), strict_loads(zlib.decompress(raw).decode()))
        index.db.commit()
        source = self.roots["source_report"]; binding = source["bindings"]
        self.bindings_artifact = ProviderArtifact(str(Path(self.inputs.source_report.uri).parent / binding["path"]),
            binding["raw_sha256"], binding["raw_bytes"], "scar.source-invocation-bindings")
        self._watch(self.bindings_artifact.uri)
        doc = _document(self.bindings_artifact, meter, self._cache)
        self.bindings = doc["bindings"]
        need(len(self.bindings) == source["summary"]["entered_code_groups"], "source binding denominator differs")
        return {"rows_visited": count, "stored_sha256": physical_sha, "stored_bytes": len(stored),
                "decoded_sha256": sha.hexdigest(), "decoded_bytes": size, "binding_rows": len(self.bindings)}

    def _static_binding(self, invocation, definition, fact, meter):
        number = int(fact.locator.removeprefix("#/bindings/")); row = self.bindings[number]
        need(fact.artifact == self.bindings_artifact and row["binding_index"] == number
             and row["process_id"] == invocation.invocation.process_id and row["definition"] == encode(definition), "retained source binding differs")
        capture = decode(CodeCapture, row["code_capture"])
        need(capture.process_id == invocation.invocation.process_id and capture.code.key == row["code"], "captured code version differs")
        attachment = row.get("attachment_witness")
        descriptor = row.get("descriptor_witness_locator")
        link = row.get("code_source_witness_locator")
        if attachment is not None:
            attachment = attachment.get("static_witness", attachment)
            descriptor = attachment.get("descriptor_locator", descriptor)
            link = attachment.get("code_source_locator", link)
        if descriptor is None or link is None:
            return None
        descriptor = _static_locator(descriptor, ProviderFactReference(self.bindings_artifact, fact.locator + "/descriptor_witness_locator"))
        link = _static_locator(link, ProviderFactReference(self.bindings_artifact, fact.locator + "/code_source_witness_locator"))
        self._watch(descriptor.artifact.uri); self._watch(link.artifact.uri)
        observed_descriptor = decode(CapturedCode, _source_locator_value(descriptor, meter, self._cache))
        actual = decode(CodeSourceLink, _source_locator_value(link, meter, self._cache))
        need(observed_descriptor == capture.code and actual.code == capture.code.key
             and actual.status is CallLinkStatus.VERIFIED and actual.snapshot == definition.snapshot
             and actual.definition == definition.definition and actual.source == definition.source, "independent code/source version witness contradicts binding")
        body = None
        raw_body = row.get("body")
        if raw_body is not None and "canonical_locator" in raw_body and "identity" in raw_body.get("reference", {}):
            reference = raw_body["reference"]
            if "definition" in reference:
                need(reference["definition"] == encode(definition), "qualified static body definition differs")
            namespace = raw_body["namespace"]
            need(namespace["body"]["definition"] == encode(definition.definition)
                 and namespace["body"]["source"] == encode(definition.source), "static body original namespace/source differs")
            body = StaticEntityRef(_static_locator(raw_body["canonical_locator"], ProviderFactReference(self.bindings_artifact, fact.locator + "/body/canonical_locator")),
                decode(RegionID, reference["identity"]), definition, ProviderFactReference(self.bindings_artifact, fact.locator + "/body/namespace"))
        return InvocationStaticBinding(invocation, capture.code, definition,
            ProviderFactReference(self.bindings_artifact, fact.locator + "/code_capture"), link, (descriptor,), body)

    def _contexts(self, index, hosts, gaps, source, meter):
        contexts, static = {}, {}
        for host in hosts:
            if host.native is None:
                continue
            records = index.db.execute("SELECT sequence FROM native WHERE instance=? AND ref=?", (host.host.instance.wire, canonical(encode(host.native)).decode())).fetchall()
            need(len(records) == 1, "native host sequence ambiguous")
            found = index.db.execute("SELECT line,payload FROM source WHERE sequence=? ORDER BY phase", (records[0][0],)).fetchall()
            by_phase = {strict_loads(zlib.decompress(raw).decode())["phase"]: strict_loads(zlib.decompress(raw).decode())
                        for _, raw in found}
            span = by_phase.get("span")
            native_parent = index.db.execute("SELECT parent FROM nodes WHERE id=?", (host.host.instance.wire,)).fetchone()
            if span is None or native_parent is None or native_parent[0] != span["marker_instance"]:
                gaps.append(RelationGap("SOURCE_NATIVE_PARENT_UNRESOLVED", source,
                    "Current source span is not the exact original ETO parent of this native host", len(found)))
                continue
            marker = index.db.execute("SELECT process,thread FROM nodes WHERE id=?", (span["marker_instance"],)).fetchone()
            child = index.db.execute("SELECT process,thread FROM nodes WHERE id=?", (host.host.instance.wire,)).fetchone()
            need(marker is not None and marker == child, "source span/native host original process/thread differs")
            for line, raw in found:
                row = strict_loads(zlib.decompress(raw).decode())
                if row["phase"] == "output":
                    parent = index.db.execute("SELECT parent,process,thread FROM nodes WHERE id=?", (row["marker_instance"],)).fetchone()
                    need(parent is not None and parent == (span["marker_instance"], *child), "source output phase original parent/thread differs")
                if row.get("invocation") is None:
                    continue
                invocation = InvocationRef(self.scope, decode(InvocationKey, row["invocation"]), decode(ProviderFactReference, row["source_invocation_reference"]))
                definition = None if row.get("definition") is None else decode(SourceDefinitionReference, row["definition"])
                binding_fact = decode(ProviderFactReference, row["source_binding_reference"])
                relation = NativeSourceContextRelation(host.native, invocation,
                    _locator(self.source_artifact, self.source_desc, self.source_declaration, line=line), binding_fact, definition)
                contexts[stable_key(relation)] = relation
                if definition is not None:
                    typed = self._static_binding(invocation, definition, binding_fact, meter)
                    if typed is not None:
                        static[stable_key(typed)] = typed
        if not contexts:
            gaps.append(RelationGap("SOURCE_CONTEXT_UNRESOLVED", source, "No retained current source invocation is linked by this native host", 0))
        if contexts and not static:
            gaps.append(RelationGap("CODE_SOURCE_WITNESS_UNRESOLVED", source, "Retained source context has no independently readable exact code/source witness", None))
        if any(s.body is None for s in static.values()):
            gaps.append(RelationGap("STATIC_BODY_MEMBER_UNREVIEWED", source,
                "Code/source version is bound, while this binding has no supported exact canonical Region locator", None))
        return tuple(contexts.values()), tuple(static.values())

    def _relations(self, index, projection, source, meter):
        target = projection.original.instance.wire
        direct = index.db.execute("SELECT * FROM edges WHERE target=? ORDER BY relation,id", (target,)).fetchall()
        paths = [(row,) for row in direct]
        for row in direct:
            if row[2] == "submits_work":
                paths.extend((parent, row) for parent in index.db.execute("SELECT * FROM edges WHERE target=? AND relation='provider_scope_association' ORDER BY id", (row[3],)))
        hosts, gaps = {}, []
        for path in paths:
            kind = HostRelationKind.SUBMITTED_BY_RUNTIME if path[0][2] == "submits_work" else HostRelationKind.PROVIDER_SCOPE_CONTEXT
            original_host = self._node(index, path[0][3])
            native = index.db.execute("SELECT ref FROM native WHERE instance=? ORDER BY sequence", (original_host.instance.wire,)).fetchall()
            if not native:
                native = [(None,)]
            for row in native:
                endpoint = None if row[0] is None else decode(QualifiedOccurrenceRef, strict_loads(row[0]))
                host = WorkHostRelation(projection.work, kind, original_host, projection.original, tuple(self._edge(edge) for edge in path), endpoint)
                hosts[stable_key(host)] = host
        if not hosts:
            gaps.append(RelationGap("HOST_RELATION_UNRESOLVED", source, "No exact original provider submission/scope edge path", 0))
        if not any(h.native is not None for h in hosts.values()):
            gaps.append(RelationGap("NATIVE_OCCURRENCE_UNRESOLVED", source, "Original host evidence has no exact canonical native INVOKE association", len(hosts)))
        contexts, static = self._contexts(index, tuple(hosts.values()), gaps, source, meter)
        gaps.append(RelationGap("STATE_CONTENT_READY_UNPROVED", source, "These relationships do not establish actual/formal, world/state, logical contents, readiness or runtime child closure", None))
        return WorkRelations(projection, tuple(hosts.values()), contexts, static, tuple(gaps))

    def produce(self, writer, meter):
        need(not self._started, "producer is single-use")
        self._started = True; self._meter = meter; self.phase = "ROOTS"; self._roots(meter)
        index = _Index(writer.root / "locator.sqlite")
        counts, gaps, kinds = Counter(), Counter(), Counter()
        representative = static_representative = None
        try:
            self.phase = "ORIGINAL_EEG_LOCATOR_INDEX"; original = self._bundle_index(index, meter)
            self.phase = "NATIVE_OCCURRENCE_INDEX"; native = self._native_index(index, meter)
            self.phase = "CURRENT_SOURCE_ASSOCIATIONS"; retained = self._source_index(index, writer, meter)
            self.phase = "FULL_WORK_RELATIONS"
            work = self.roots["work_manifest"]
            declared = work["qualified_single_activities"]
            need(type(declared) is int and declared == sum(s["records"] for s in work["shards"]), "work shard denominator differs")
            seen = set()
            for shard in work["shards"]:
                payloads = {}
                for family, schema in (("work_records", "scar.native-activity-work.rows"), ("source_receipts", "scar.native-activity-work.receipts"), ("evidence", "scar.ir.v2.evidence")):
                    desc = shard[family]; a = _artifact(desc, schema); self._watch(a.uri)
                    payloads[family] = read_payload(a, meter, decoded_bytes=desc["decoded_bytes"], decoded_sha256=desc["decoded_sha256"],
                        compressed=desc["compression"] == "gzip", maximum=meter.budget.max_input_chunk_bytes)
                rows = payloads["work_records"].splitlines(keepends=True)
                receipts = payloads["source_receipts"].splitlines(keepends=True)
                evidence = strict_loads(payloads["evidence"].decode()); instances = evidence["instances"]
                need(len(rows) == len(receipts) == len(instances) == shard["records"], "work/projection/receipt member denominator differs")
                for number, (raw, raw_receipt, instance) in enumerate(zip(rows, receipts, instances)):
                    need(raw.endswith(b"\n") and raw_receipt.endswith(b"\n") and len(raw) <= meter.budget.max_record_bytes, "work record framing/budget")
                    row = strict_loads(raw.decode()); receipt = strict_loads(raw_receipt.decode())
                    need(set(row) == {"submission", "binding", "quiescence"}, "closed native work row required")
                    submission = decode(WorkSubmission, row["submission"]); binding = decode(WorkEvidenceBinding, row["binding"])
                    quiet = decode(WorkQuiescence, row["quiescence"])
                    need(submission.id not in seen, "duplicate work ticket")
                    seen.add(submission.id)
                    projection = _work_projection(self.inputs, self.scope, shard, number, receipt, submission, binding, quiet, instance, self._original_locator)
                    source = ProviderFactReference(projection.work.locator.artifact, "#/lines/" + str(number + 1) + "/submission")
                    original_row = index.db.execute("SELECT digest FROM nodes WHERE id=?", (binding.instance.wire,)).fetchone()
                    need(original_row is not None and original_row[0] == hashlib.sha256(canonical(instance)).hexdigest(), "GPU projection differs from original instance")
                    relation = self._relations(index, projection, source, meter)
                    writer.work_row(relation)
                    counts["visited_work_count"] += 1
                    counts["work_with_host_relation"] += bool(relation.hosts)
                    counts["work_with_native_occurrence"] += any(h.native is not None for h in relation.hosts)
                    endpoints = {stable_key(h.native) for h in relation.hosts if h.native is not None}
                    counts["work_with_unique_native_occurrence"] += len(endpoints) == 1
                    counts["work_with_multiple_native_occurrences"] += len(endpoints) > 1
                    counts["work_with_source_context"] += bool(relation.source_contexts)
                    counts["work_with_static_code_source"] += bool(relation.static_bindings)
                    gaps.update(g.code for g in relation.gaps)
                    kinds.update(h.kind.value for h in relation.hosts)
                    if representative is None and len(endpoints) == 1 and relation.source_contexts and relation.static_bindings:
                        representative = {"scope": encode(self.scope), "work": encode(projection.work)}
                    if static_representative is None and len(endpoints) == 1 and any(
                            s.body is not None and s.body.graph.decoded_bytes <= meter.budget.max_metadata_bytes for s in relation.static_bindings):
                        static_representative = {"scope": encode(self.scope), "work": encode(projection.work)}
            need(counts["visited_work_count"] == declared, "work enumeration incomplete")
            self._finished = True
            return {**dict(counts), "declared_work_count": declared,
                "all_gpu_candidates": work["all_gpu_candidates"], "provider_frontier_counts": work["frontier_counts"],
                "missing_relations": dict(gaps), "original_eeg_index": original,
                "host_relation_kinds": dict(kinds), "first_unique_connected_work": representative,
                "first_static_body_work": static_representative,
                "native_index": native, "source_retention": retained,
                "static_inventory": self.roots["source_report"]["inventory"],
                "source_runtime_summary": self.roots["source_report"]["summary"],
                "relationship_is_direct_call": False, "whole_program_complete": False}
        finally:
            index.close()
            size = index.path.stat().st_size
            meter.charge(output=size)


def _check_source_row(row, inputs, roots, scope, pid):
    d = roots["dispatch_report"]
    need(type(row) is dict and type(row.get("sequence")) is int and row["sequence"] > 0
         and row.get("phase") in ("span", "output") and row.get("relationship") == "RETAINED_ANCESTOR_CONTEXT"
         and row.get("direct_callsite_established") is False, "source retained context contract differs")
    marker = decode(ProviderFactReference, row["marker_reference"])
    eto = [m["artifact"] for m in roots["coordinates"]["membership"]
           if m["artifact"]["schema"] == "pytorch.execution-trace.v1"]
    need(marker.artifact.schema == "pytorch.execution-trace.v1"
         and encode(marker.artifact) in eto
         and marker.locator.startswith("#/nodes/")
         and type(row.get("marker_instance")) is str and row["marker_instance"].startswith("opinst:"), "source marker original identity differs")
    if row.get("invocation") is not None:
        invocation = decode(InvocationKey, row["invocation"])
        need(invocation.process_id == pid, "source invocation process differs")
        for key, original in (("source_invocation_reference", "source_invocations"), ("source_binding_reference", "source_bindings")):
            need(row[key]["artifact"] == d[original], "retained source endpoint original artifact differs")
        need(row["source_binding_reference"]["locator"].startswith("#/bindings/")
             and row["source_invocation_reference"]["locator"].startswith("#/lines/"), "source endpoint coordinates differ")
    if row.get("definition") is not None:
        decode(SourceDefinitionReference, row["definition"])


def _work_projection(inputs, scope, shard, number, receipt, work, binding, quiet, instance, original_locator):
    for item in (work, binding, quiet):
        item.__post_init__()
    need(receipt["projection_index"] == number and receipt["ticket"] == encode(work.id)
         and binding.ticket == quiet.ticket == work.id and binding.instance == decode(OperationInstanceID, instance["id"]), "work ticket/producer/receipt differs")
    projection = _artifact(shard["evidence"], "scar.ir.v2.evidence")
    need(binding.artifact == projection and binding.source == ProviderFactReference(projection, "#/instances/" + str(number)), "work evidence binding original source differs")
    start = ProviderFactReference(projection, "#/instances/" + str(number) + "/start_ns")
    end = ProviderFactReference(projection, "#/instances/" + str(number) + "/end_ns")
    need(type(work.origin) is ExternalWorkSource and work.origin.point.run == scope.run
         and work.origin.point.process == scope.process and quiet.observed_at.run == scope.run
         and quiet.observed_at.process == scope.process and work.origin.source == work.origin.point.source == start
         and quiet.source == quiet.observed_at.source == end and work.source == work.protocol == binding.source
         and binding.id.value == quiet.id.value == work.id.value, "work Run/process/source endpoints differ")
    from scar.ir.v2.common import Completeness
    need(work.dependencies_coverage is work.effects_coverage is work.materializations_coverage is Completeness.UNKNOWN,
         "single-activity input promoted dependency/effect/materialization coverage")
    need(instance["metadata"]["raw_reference"] == receipt["raw_reference"], "GPU original raw fact differs")
    descriptor = shard["work_records"]; artifact = _artifact(descriptor, "scar.native-activity-work.rows")
    declaration = ProviderFactReference(inputs.work_manifest, "#/shards/" + str(shard["index"]) + "/work_records")
    locator = _locator(artifact, descriptor, declaration, line=number + 1, pointer="#/submission")
    original = original_locator("instances", receipt["original_eeg_ordinal"])
    need(original.line == receipt["original_locator"]["line"]
         and original.artifact.sha256 == receipt["original_locator"]["artifact"]["physical_sha256"]
         and receipt["original_locator"]["manifest_receipt"] == {"path": inputs.original_eeg_manifest.uri,
             "physical_sha256": inputs.original_eeg_manifest.sha256, "physical_bytes": inputs.original_eeg_manifest.size_bytes}, "GPU original archive locator differs")
    receipt_desc = shard["source_receipts"]
    receipt_loc = _locator(_artifact(receipt_desc, "scar.native-activity-work.receipts"), receipt_desc,
        ProviderFactReference(inputs.work_manifest, "#/shards/" + str(shard["index"]) + "/source_receipts"), line=number + 1)
    return WorkActivityProjectionLink(scope, WorkTicketRef(locator, work.id), replace(locator, pointer="#/binding"),
        LegacyOperationRef(projection, binding.instance), EvidenceInstanceRef(original, binding.instance), receipt_loc)


def _declared_locator(locator, inputs, roots):
    """Reject a changed namespace/declaration before opening its payload."""
    declaration = locator.declaration
    if declaration.artifact == inputs.original_eeg_manifest:
        d = _pointer(roots["original_eeg_manifest"], declaration.locator)
        path = str(Path(inputs.original_eeg_manifest.uri).parent / d["uri"])
        need((locator.artifact.uri, locator.artifact.sha256, locator.artifact.size_bytes,
              locator.decoded_sha256, locator.decoded_bytes)
             == (path, d["physical_sha256"], d["physical_bytes"], d["decoded_sha256"], d["decoded_bytes"])
             and locator.line is not None and locator.line <= d["lines"], "original EEG descriptor/namespace differs")
    elif declaration.artifact == inputs.work_manifest:
        d = _pointer(roots["work_manifest"], declaration.locator)
        need((locator.artifact.uri, locator.artifact.sha256, locator.artifact.size_bytes,
              locator.decoded_sha256, locator.decoded_bytes)
             == (d["uri"], d["stored_sha256"], d["stored_bytes"], d["decoded_sha256"], d["decoded_bytes"]), "work descriptor/namespace differs")
    elif declaration.artifact == inputs.dispatch_report and declaration.locator == "#/observations":
        d = roots["dispatch_report"]["observations"]
        need(locator.artifact.uri == str(Path(inputs.dispatch_report.uri).parent / d["path"])
             and (locator.decoded_sha256, locator.decoded_bytes) == (d["raw_sha256"], d["raw_bytes"])
             and locator.line is not None and locator.line <= d["rows"], "source retained collection/namespace differs")
    else:
        raise ValueError("fragment locator is outside the fixed root catalog")


def validate_retained_relation(row, catalog_document, producer_receipts, *, meter, retention):
    """Recheck selected original endpoints, without a new capture or whole scan."""
    exact(row, WorkRelations, "retained work relation")
    from scar.store.fragment_relations import RelationPartitions
    exact(retention, RelationPartitions, "fixed retained relation reader")
    inputs = decode(FragmentInputs, catalog_document)
    need(producer_receipts == _code_receipts(), "relation producer/policy version differs")
    cache = {}
    roots = {f.name: _document(getattr(inputs, f.name), meter, cache) for f in fields(inputs)}
    need(roots["work_manifest"]["run"] == encode(row.projection.scope.run)
         and roots["work_manifest"]["process"] == encode(row.projection.scope.process), "retained work scope differs")
    projection = row.projection
    for locator in (projection.work.locator, projection.binding, projection.receipt, projection.original.locator):
        _declared_locator(locator, inputs, roots)
    work = decode(WorkSubmission, _read_locator(projection.work.locator, meter, cache))
    binding = decode(WorkEvidenceBinding, _read_locator(projection.binding, meter, cache))
    receipt = _read_locator(projection.receipt, meter, cache)
    original = _read_locator(projection.original.locator, meter, cache)
    projected = _pointer(_document(projection.projection.artifact, meter, cache), "#/instances/" + str(receipt["projection_index"]))
    need(work.id == projection.work.ticket and binding.ticket == work.id
         and binding.artifact == projection.projection.artifact and binding.instance == projection.original.instance
         and original == projected and original["id"] == encode(binding.instance), "work/projection/original producer mismatch")
    need(receipt["ticket"] == encode(work.id)
         and receipt["original_locator"]["line"] == projection.original.locator.line
         and receipt["original_locator"]["artifact"]["physical_sha256"] == projection.original.locator.artifact.sha256
         and type(work.origin) is ExternalWorkSource and work.origin.point.run == projection.scope.run
         and work.origin.point.process == projection.scope.process, "work receipt/Run origin differs")
    native_cache = {}
    for host in row.hosts:
        _declared_locator(host.host.locator, inputs, roots)
        instance = _read_locator(host.host.locator, meter, cache)
        need(instance["id"] == encode(host.host.instance), "host original entity differs")
        for edge in host.evidence_path:
            _declared_locator(edge.locator, inputs, roots)
            value = _read_locator(edge.locator, meter, cache)
            need(value["edge_id"] == edge.edge_id and value["relation"] == edge.relation
                 and value["source"]["reference"] == encode(edge.source)
                 and value["target"]["reference"] == encode(edge.target), "provider relation/path direction differs")
        if host.native is not None:
            from scar.ir.execution.codec import loads as execution_loads
            ref = host.native
            shards = [s for s in roots["native_batch_report"]["shards"] if s["execution"] == encode(ref.execution)]
            need(len(shards) == 1, "native occurrence is outside catalog shard namespace")
            if ref.execution not in native_cache:
                native_cache[ref.execution] = execution_loads(read_payload(ref.execution, meter, maximum=meter.budget.max_input_chunk_bytes).decode())
            execution = native_cache[ref.execution]
            need(ref.binding in execution.evidence_bindings and any(o.id == ref.occurrence for o in execution.operations)
                 and any(p.id == projection.scope.process and p.run == projection.scope.run for p in execution.processes), "native occurrence/binding/Run differs")
            need(ref.binding.legacy.artifact == decode(ProviderArtifact, shards[0]["evidence_projection"])
                 and execution.snapshot.artifact == decode(ProviderArtifact, roots["native_batch_report"]["shared_program"]), "native static/projection roots differ")
            native_projection = _document(ref.binding.legacy.artifact, meter, cache)
            matched = [r for r in native_projection["instances"] if r["id"] == encode(ref.binding.legacy.instance)]
            need(matched == [instance], "native projected evidence changes original host record")
            from scar.ir.program.codec import loads as program_loads
            from scar.ir.program.model import TerminatorKind
            shared = execution.snapshot.artifact
            program_key = ("PROGRAM", shared)
            if program_key not in cache:
                cache[program_key] = program_loads(read_payload(shared, meter).decode())
            program = cache[program_key]
            occurrence = next(o for o in execution.operations if o.id == ref.occurrence)
            op = next(o for o in program.operations if o.id == occurrence.operation)
            visit = next(v for v in execution.visits if v.id == occurrence.visit)
            segment = next(s for s in execution.segments if s.id == visit.segment)
            activation = next(a for a in execution.activations if a.id == segment.activation)
            region = next(r for r in program.regions if r.id == activation.region)
            need(op.terminator is not None and op.terminator.kind is TerminatorKind.INVOKE
                 and activation.process == projection.scope.process and visit.block == region.entry
                 and any(b.id == visit.block and op.id in b.operations for b in region.blocks), "native occurrence/static CFG ownership differs")
    for context in row.source_contexts:
        _declared_locator(context.association, inputs, roots)
        source_row = retention.source_record(context.association, meter=meter)
        need(source_row["invocation"] == encode(context.invocation.invocation)
             and source_row["source_invocation_reference"] == encode(context.invocation.fact)
             and source_row.get("definition") == (None if context.definition is None else encode(context.definition)), "retained source context changed")
        _check_source_row(source_row, inputs, roots, context.invocation.scope, context.invocation.invocation.process_id)
        need(context.source_binding is not None and source_row["source_binding_reference"] == encode(context.source_binding), "retained source binding fact differs")
    for static in row.static_bindings:
        link = decode(CodeSourceLink, _source_locator_value(static.code_source_link, meter, cache))
        descriptor = decode(CapturedCode, _source_locator_value(static.witness[0], meter, cache))
        need(descriptor == static.captured_code and link.code == descriptor.key and link.status is CallLinkStatus.VERIFIED
             and link.snapshot == static.definition.snapshot and link.source == static.definition.source
             and link.definition == static.definition.definition, "static CodeVersion/source differs")
        binding_root = roots["source_report"]["bindings"]
        binding_artifact = ProviderArtifact(str(Path(inputs.source_report.uri).parent / binding_root["path"]),
            binding_root["raw_sha256"], binding_root["raw_bytes"], "scar.source-invocation-bindings")
        need(static.code_capture.artifact == binding_artifact, "static binding capture outside current source root")
        captured = decode(CodeCapture, _pointer(_document(binding_artifact, meter, cache), static.code_capture.locator))
        need(captured.code == descriptor and captured.process_id == static.invocation.invocation.process_id,
             "current invocation captured another code version")
    return {"scope": "SELECTED_CURRENT_RETAINED_RELATIONS", "original_endpoint_checks": "PASSED",
            "direct_call_established": False, "state_content_ready_established": False,
            "whole_program_complete": False, "gaps": encode(row.gaps)}


def static_member(reference, *, budgets=None, meter=None):
    """Read original static CFG/def-use/state members, including unvisited code.

    This is static membership only. It never manufactures a Run, occurrence,
    alias, effect proof or dynamic execution for an unexecuted branch.
    """
    from scar.store.fragment_relations import Meter, RelationBudgets
    from scar.ir.program.codec import from_dict as program_from_dict
    from scar.ir.program.ids import LocationID, OperationID, UseID
    exact(reference, StaticEntityRef, "qualified static member")
    if meter is None:
        meter = Meter(budgets if budgets is not None else RelationBudgets(max_input_bytes=256_000_000, max_seconds=30))
    exact(meter, Meter, "shared input budget")
    cache = {}
    graph = program_from_dict(_source_locator_value(reference.graph, meter, cache))
    if type(reference.identity) is RegionID:
        found = next((r for r in graph.regions if r.id == reference.identity), None)
    elif type(reference.identity) is OperationID:
        found = next((r for r in graph.operations if r.id == reference.identity), None)
    elif type(reference.identity) is UseID:
        found = next((u for op in graph.operations for u in op.uses if u.id == reference.identity), None)
    elif type(reference.identity) is LocationID:
        found = next((r for r in graph.locations if r.id == reference.identity), None)
    else:
        raise ValueError("unsupported static member")
    need(found is not None, "static entity is absent from its original graph version")
    return {"reference": reference, "member": found, "qualification": "ORIGINAL_STATIC_MEMBERSHIP",
            "runtime_occurrence_implied": False, "effects_or_optimization_authorized": False,
            "costs": meter.receipt()}
