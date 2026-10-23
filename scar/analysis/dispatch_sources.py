"""Reference-only production marker -> retained source invocation adapter.

The existing bridge already checked marker/RF correlation and retained context.
This adapter checks its shared capture against complete source-binding artifacts;
it does not reload a native graph, compile source, invent producers or promote
retained ancestry to a direct Python/ATen call.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import gzip
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import tempfile

from scar.ir.execution.common import EvidencePoint
from scar.ir.execution.coordinates import ExecutionRun, HostThreadInstance, RegionActivation
from scar.ir.program.call_edges import CallRecordAnchor, InvocationKey
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.record_codec import decode, encode, loads as strict_loads
from scar.trace.capture_coordinates import CaptureCoordinates
from scar.trace.dispatch_evidence import PRODUCTION_PROFILE


_AUTHORITY = {
    "direct_python_operator_correspondence_established": False,
    "actual_formal_routing_established": False,
    "return_value_routing_established": False,
    "function_environment_established": False,
    "logical_versions_established": False,
    "world_effects_established": False,
    "resource_readiness_established": False,
    "execution_model_established": False,
    "whole_model_established": False,
    "first_stage_complete": False,
    "transformation_authorized": False,
}
_RAW = re.compile(r"sha256:([0-9a-f]{64})(#/nodes/[0-9]+)$")


def _need(condition, detail):
    if not condition:
        raise ValueError("dispatch source association: " + detail)


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _read_document(path, schema, maximum, *, versions=(1,)):
    path = Path(path)
    _need(not path.is_symlink() and path.is_file() and path.stat().st_size <= maximum,
          "document is missing, unsafe or exceeds its byte bound")
    raw = path.read_bytes()
    if path.suffix == ".gz":
        with gzip.GzipFile(fileobj=BytesIO(raw), mode="rb") as source:
            payload = source.read(maximum + 1)
    else:
        payload = raw
    _need(len(payload) <= maximum, "document decoded-byte bound exceeded")
    document = strict_loads(payload.decode("utf-8"))
    _need(type(document) is dict and document.get("schema") == schema
          and type(document.get("schema_version")) is int
          and document["schema_version"] in versions, "unsupported document schema/version")
    return document, ProviderArtifact(str(path.resolve()), hashlib.sha256(payload).hexdigest(),
                                     len(payload), schema)


def _plain_receipt(root, declaration, schema, maximum, *, versions=(1,)):
    _need(type(declaration) is dict and type(declaration.get("path")) is str,
          "source artifact declaration is missing")
    _need(Path(declaration["path"]).name == declaration["path"], "source receipt escapes its directory")
    path = root / declaration["path"]
    document, artifact = _read_document(path, schema, maximum, versions=versions)
    _need((artifact.sha256, artifact.size_bytes) == (declaration["raw_sha256"], declaration["raw_bytes"]),
          "source document differs from its exact byte receipt")
    return document, artifact


def _same_artifact(left, right):
    return left.uri == right.uri and left.sha256 == right.sha256 and left.size_bytes == right.size_bytes


def _member(coordinates, artifact, pid):
    rows = [row for row in coordinates.report["membership"]
            if _same_artifact(decode(ProviderArtifact, row["artifact"]), artifact)]
    _need(len(rows) == 1, "artifact has no unique exact logical URI/bytes capture membership")
    process = coordinates.process_for(artifact, pid)
    _need(process is not None and process.run == coordinates.run.id and encode(process.id) == rows[0]["process"],
          "artifact/process differs from the shared capture coordinates")
    return process


def _inputs(source_directory, bridge_path, coordinates, max_bytes):
    _need(type(coordinates) is CaptureCoordinates, "coordinates must be CaptureCoordinates")
    _need(hashlib.sha256(coordinates.payload).hexdigest() == coordinates.artifact.sha256
          and len(coordinates.payload) == coordinates.artifact.size_bytes
          and _canonical(coordinates.report) == coordinates.payload, "coordinate payload is inconsistent")
    root = Path(source_directory).resolve()
    report, report_artifact = _read_document(root / "report.json", "scar.source-invocations", 16_000_000,
                                           versions=(1, 2))
    _need(report.get("current_capture_raw_scan_verified") is True
          and report.get("old_capture_dynamic_facts_used_for_current_run") is False,
          "source report does not bind a completed current-capture raw scan")
    _need(decode(ExecutionRun, report["run"]) == coordinates.run, "source and marker Run declarations differ")
    _need(report.get("transformation_authorized") is False and report.get("first_stage_complete") is False,
          "source input overstates its authority")
    bindings, binding_artifact = _plain_receipt(root, report["bindings"], "scar.source-invocation-bindings", 32_000_000,
        versions=(report["schema_version"],))
    _need(bindings.get("witness_mode") == report["witness_mode"]
          and bindings.get("transformation_authorized") is False, "source binding header differs from its report")
    bridge, bridge_artifact = _read_document(bridge_path, "scar.dispatch-observation-import", max_bytes)
    _need(bridge.get("profile") == PRODUCTION_PROFILE and bridge.get("production_collector") is True
          and bridge.get("capture_membership_verified") is True
          and bridge.get("direct_python_operator_correspondence_established") is False
          and bridge.get("transformation_authorized") is False, "unsupported production bridge authority/profile")
    artifacts = {key: decode(ProviderArtifact, value) for key, value in bridge["artifacts"].items()}
    current_files = {(file["process_id"], file["family"]): file for file in report["trace_files"]}
    matching = [pid for pid, family in current_files if family == "events"
                and (current_files[pid, family]["raw_sha256"], current_files[pid, family]["raw_bytes"])
                == (artifacts["calls"].sha256, artifacts["calls"].size_bytes)]
    _need(len(matching) == 1, "bridge calls have no unique current source process/raw-byte match")
    pid = matching[0]
    for name, family in (("calls", "events"), ("codes", "codes"), ("call_meta", "meta")):
        file = current_files[pid, family]
        artifact = artifacts[name]
        _need((file["raw_sha256"], file["raw_bytes"]) == (artifact.sha256, artifact.size_bytes),
              "source and marker call-family SHA/bytes differ")
        process = _member(coordinates, artifact, pid)
        memberships = [row for row in coordinates.report["membership"]
                       if _same_artifact(decode(ProviderArtifact, row["artifact"]), artifact)]
        _need(file["path"] == memberships[0]["logical_path"]
              or file["path"] == str(Path(memberships[0].get("local_path", artifact.uri)).with_suffix(""))
                 and Path(memberships[0].get("local_path", artifact.uri)).suffix == ".gz",
              "source call manifest has no exact logical/retained path correspondence")
    for artifact in artifacts.values():
        _need(_member(coordinates, artifact, pid) == process, "bridge artifacts belong to different processes")
    native = {}
    for schema, key in (("pytorch.execution-trace.v1", "eto"), ("pytorch.kineto.chrome-trace.v1", "kineto")):
        matches = [decode(ProviderArtifact, row["artifact"]) for row in coordinates.report["membership"]
                   if row["artifact"]["schema"] == schema]
        _need(len(matches) == 1 and _member(coordinates, matches[0], pid) == process,
              "native artifact is ambiguous or outside this process/capture")
        native[key] = matches[0]
    return root, report, report_artifact, bindings, binding_artifact, bridge, bridge_artifact, artifacts, native, pid, process


class _PartitionedSourceScope:
    """Verify v2 fragments through an explicit original CompositionIndex.

    Cache compact verification results per file/body, not full graphs and not
    per-marker computations. Locator URIs never become arbitrary open paths.
    """
    def __init__(self, composition, report):
        from scar.analysis.program_composition import CompositionIndex
        _need(type(composition) is CompositionIndex and composition.partitioned
              and composition.document["schema_version"] == 2,
              "source schema2 needs an explicit partitioned CompositionIndex")
        _need(report["inventory"] == composition.document["inventory"]
              and report["composition_canonical_sha256"] == hashlib.sha256(_canonical(composition.document)).hexdigest(),
              "source report differs from the exact composition/inventory receipts")
        self.composition = composition
        self.components, self.checked_files, self.checked_bodies = {}, set(), {}
        self.counts = Counter()

    def _witness(self, locator, component, pattern):
        if locator is None:
            return None
        _need(type(locator) is dict and type(locator.get("pointer")) is str
              and re.fullmatch(pattern, locator["pointer"]) is not None,
              "partitioned witness has no supported exact component pointer")
        suffix = locator["pointer"][len("#/value"):]
        expected = self.composition.inventory_component_locator(component, suffix)
        _need(locator == expected, "witness artifact/representation differs from the bound component")
        if component not in self.components:
            self.components[component] = self.composition.inventory_component(component)
        value = self.components[component]
        for part in suffix.lstrip("/").split("/"):
            value = value[int(part)] if type(value) is list else value[part]
        self.counts["witness_locators_verified"] += 1
        return value

    def _file(self, file_index):
        _need(type(file_index) is int and 0 <= file_index < self.composition.inventory_file_count,
              "source element file index is not in the bound inventory")
        raw = self.composition.inventory_file(file_index)
        if file_index not in self.checked_files:
            view = self.composition.source(file_index)
            _need(raw["snapshot"] == encode(view.snapshot) and raw["context"] == encode(view.context),
                  "source shard snapshot/context differs from its original source archive")
            self.checked_files.add(file_index)
        return raw

    def binding(self, binding):
        from scar.ir.program.call_edges import CodeCapture, CodeSourceLink, CallLinkStatus
        from scar.ir.program.call_demand import CallSourceAdmission, CallSourceAdmissionStatus
        from scar.ir.program.ids import RegionID
        from scar.ir.v2.ids import OperationDefinitionID
        _need(type(binding["process_id"]) is int and binding["process_id"] > 0,
              "source schema2 binding process must be an exact positive PID")
        _need(all(binding.get(name) is None for name in ("descriptor_witness_pointer",
                  "code_source_witness_pointer", "admission_pointer"))
              and binding.get("static_body_witness_pointers") == [],
              "schema2 cannot substitute monolithic pointers for partitioned locators")
        for name in ("descriptor_witness_locator", "code_source_witness_locator", "admission_locator",
                     "static_body_witness_locators", "definition_locator"):
            _need(name in binding, "source schema2 binding omitted an explicit locator field")
        capture = decode(CodeCapture, binding["code_capture"]) if binding["code_capture"] is not None else None
        if capture is not None:
            _need(capture.process_id == binding["process_id"] and capture.code.key == binding["code"],
                  "binding capture differs from its actual process/complete code identity")
        descriptor = self._witness(binding["descriptor_witness_locator"], "call_sources",
                                  r"#/value/model/codes/(0|[1-9][0-9]*)/code")
        if binding["complete_descriptor_match"] is True:
            _need(capture is not None and descriptor == encode(capture.code),
                  "complete descriptor match has no identical original descriptor witness")
        else:
            _need(binding["complete_descriptor_match"] is False and descriptor is None,
                  "unmatched descriptor cannot retain a verified descriptor locator")
        link_document = self._witness(binding["code_source_witness_locator"], "call_sources",
                                     r"#/value/model/code_links/(0|[1-9][0-9]*)")
        link = decode(CodeSourceLink, link_document) if link_document is not None else None
        if link is not None:
            _need(link.code == binding["code"], "source witness belongs to a different complete code key")
        if binding["snapshot"] is not None:
            _need(link is not None and link.status is CallLinkStatus.VERIFIED
                  and binding["snapshot"] == encode(link.snapshot),
                  "binding snapshot has no matching original verified code/source witness")
        admission_document = self._witness(binding["admission_locator"], "call_source_scope",
                                         r"#/value/admissions/(0|[1-9][0-9]*)")
        admissions = []
        if admission_document is not None:
            _need(binding["witness_mode"] == "same_capture", "dynamic admission used outside its declared same-capture mode")
            admission = decode(CallSourceAdmission, admission_document)
            _need(admission.origin.process_id == binding["process_id"]
                  and admission.origin.code == binding["code"], "admission belongs to another process/code")
            admissions.append(admission)
        _need(type(binding["static_body_witness_locators"]) is list,
              "static body witness locators must remain an ordered list")
        for locator in binding["static_body_witness_locators"]:
            _need(binding["witness_mode"] == "reused_code", "old static witness used as a current dynamic fact")
            item = decode(CallSourceAdmission, self._witness(locator, "call_source_scope",
                          r"#/value/admissions/(0|[1-9][0-9]*)"))
            _need(item.origin.code == binding["code"], "static body witness has a different complete code identity")
            admissions.append(item)
        definition, body = binding["definition"], binding["body"]
        if definition is None:
            _need(binding["definition_locator"] is None and body is None and binding["source"] is None,
                  "unresolved source definition cannot retain a body/definition locator")
            self.counts["bindings_without_definition"] += 1
            return
        _need(link is not None and link.status is CallLinkStatus.VERIFIED
              and binding["complete_descriptor_match"] is True and capture is not None
              and binding["snapshot"] == encode(link.snapshot) and binding["source"] == encode(link.source),
              "source definition lacks the exact descriptor/source/snapshot witness")
        _need(type(definition) is dict and set(definition) == {"file_index", "identity", "body_index"}
              and definition["body_index"] is None,
              "definition reference is not a source-qualified original element")
        definition_id = decode(OperationDefinitionID, definition["identity"])
        _need(definition_id == link.definition, "definition identity differs from the exact source witness")
        raw_file = self._file(definition["file_index"])
        _need(raw_file["snapshot"] == binding["snapshot"] and capture.code.filename == raw_file["snapshot"]["path"],
              "definition source snapshot differs from its captured code/source archive")
        found = [i for i, item in enumerate(raw_file["definitions"]) if item["id"] == definition["identity"]]
        _need(len(found) == 1 and raw_file["definitions"][found[0]]["source"] == binding["source"],
              "definition ID/source does not identify one original source-shard record")
        _need(binding["definition_locator"] == self.composition.inventory_file_locator(
              definition["file_index"], f"/definitions/{found[0]}"),
              "definition locator is not its exact original shard/record")
        for admission in admissions:
            if admission.status not in (CallSourceAdmissionStatus.UNAVAILABLE, CallSourceAdmissionStatus.MISMATCH):
                _need(encode(admission.snapshot) == binding["snapshot"]
                      and admission.definition == definition_id and encode(admission.source) == binding["source"],
                      "source admission contradicts the source-qualified definition")
        self.counts["definitions_verified"] += 1
        if body is None:
            return
        ref = body["reference"]
        _need(type(ref) is dict and set(ref) == {"file_index", "identity", "body_index"}
              and type(ref["file_index"]) is int
              and ref["file_index"] == definition["file_index"]
              and type(ref["body_index"]) is int and ref["body_index"] >= 0
              and body.get("inventory_pointer") is None,
              "body reference lacks exact source/body qualification")
        region = decode(RegionID, ref["identity"])
        key = ref["file_index"], ref["body_index"]
        if key not in self.checked_bodies:
            raw_body = self.composition.inventory_body(*key)
            graph, metadata = self.composition.typed_body(*key)
            locators = self.composition.inventory_body_locators(*key, raw_body["graph"])
            checkpoint_ref = raw_file["bodies"][ref["body_index"]]["checkpoint"]
            checkpoint = self.composition.inventory.checkpoint(checkpoint_ref)
            namespace = locators["namespace"]
            _need(raw_body["definition"] == definition["identity"] and graph.root == region
                  and encode(metadata.source) == binding["snapshot"]
                  and namespace["body"]["definition"] == definition["identity"]
                  and namespace["body"]["entry"] == metadata.entry
                  and namespace["body"]["source"] == (checkpoint["structured"]["source"]
                      if checkpoint["structured"] is not None else None),
                  "body root/definition/metadata/namespace differs from its original checkpoint")
            expected_fields = {"canonical_locator": locators["graph_locator"],
                "inventory_locator": locators["inventory_locator"], "metadata_locator": locators["metadata_locator"],
                "namespace": namespace, "program_schema_version": raw_body["graph"]["schema_version"],
                "program_canonical_sha256": self.composition.document["files"][key[0]]["bodies"][key[1]]["program_canonical_sha256"],
                "reference": ref}
            self.checked_bodies[key] = {"fields": expected_fields, "definition": definition["identity"]}
        expected = self.checked_bodies[key]
        _need(expected["definition"] == definition["identity"]
              and all(body.get(name) == value for name, value in expected["fields"].items()),
              "body locator/hash/schema/namespace differs from its verified original body")
        _need(any(admission.status is CallSourceAdmissionStatus.CORE_LINKED
                  and admission.core_region == region for admission in admissions),
              "canonical body has no matching exact source admission")
        self.counts["body_bindings_verified"] += 1

    def audit(self):
        return {"partitioned_locators_verified": True, "unique_source_files_verified": len(self.checked_files),
            "unique_bodies_verified": len(self.checked_bodies), **dict(self.counts),
            "source_recompiled": False, "canonical_graphs_copied": False,
            "definition_scope": "exact original snapshot/context + DefinitionID; not path/line matching"}


def _load_invocations(root, report, bindings, artifacts, coordinates, pid, process, wanted, maximum, max_rows):
    declaration = report["invocations"]
    _need(declaration["path"] == "invocations.jsonl.gz", "unsupported invocation artifact path")
    path = root / declaration["path"]
    _need(path.is_file() and not path.is_symlink()
          and path.stat().st_size == declaration["compressed_bytes"], "invocation compressed-byte receipt differs")
    table = bindings["bindings"]
    for index, binding in enumerate(table):
        _need(binding["binding_index"] == index, "source binding table index differs")
    digest, size, count, selected, identities = hashlib.sha256(), 0, 0, {}, set()
    statuses, activation_count = Counter(), 0
    version = report["schema_version"]
    source_artifact = ProviderArtifact(str(path), declaration["raw_sha256"], declaration["raw_bytes"],
                                       "scar.source-invocations.events.v" + str(version))
    with gzip.open(path, "rb") as stream:
        for line, raw in enumerate(stream, 1):
            _need(len(raw) <= 2_000_000, "invocation row exceeds its fixed line bound")
            digest.update(raw); size += len(raw); count += 1
            _need(size <= maximum and count <= max_rows, "source invocation input budget exceeded")
            row = strict_loads(raw.decode("utf-8"))
            _need(type(row) is dict and row.get("kind") == "INVOCATION", "unsupported source invocation row")
            invocation = decode(InvocationKey, row["invocation"])
            _need(invocation not in identities, "duplicate source invocation")
            identities.add(invocation)
            index = row["source_binding_index"]
            _need(type(index) is int and 0 <= index < len(table), "invocation has an invalid source binding index")
            binding = table[index]
            _need(binding["code"] == row["code"] and binding["process_id"] == invocation.process_id
                  and binding["status"] == row["status"], "invocation differs from its source binding")
            _need(invocation.process_id == pid, "source invocation belongs to an unselected marker process")
            point = decode(EvidencePoint, row["point"])
            raw_source = decode(ProviderFactReference, row["raw_source"])
            anchor = decode(CallRecordAnchor, row["anchor"])
            _need(point.run == coordinates.run.id and point.process == process.id
                  and _same_artifact(point.source.artifact, artifacts["calls"])
                  and point.source == raw_source and point.source.locator == "#/lines/" + str(anchor.line_number),
                  "invocation raw source or common execution coordinate differs")
            activation = decode(RegionActivation, row["region_activation"]) if row["region_activation"] is not None else None
            if version == 2:
                namespace = binding["body"]["namespace"] if binding["body"] is not None else None
                _need("region_namespace" in row and row["region_namespace"] == namespace,
                      "invocation region namespace differs from its verified source body")
                host_thread = coordinates.thread_for(artifacts["calls"], invocation.thread_id, "python_ident")
                _need(row["host_thread"] == (encode(host_thread) if host_thread is not None else None),
                      "source invocation Python thread differs from exact call-artifact coordinates")
                _need(type(row["suspended"]) is bool and (activation is not None)
                      == (binding["body"] is not None and not row["suspended"]),
                      "suspended frame or absent body cannot acquire a new region activation")
            if activation is not None:
                _need(binding["body"] is not None and activation.region.as_dict() == binding["body"]["reference"]["identity"]
                      and activation.process == process.id and activation.entry == point,
                      "source region activation differs from its original body/entry")
                if version == 2:
                    expected_id = coordinates.run.id.value + ":source-frame:" + hashlib.sha256(_canonical({
                        "process": encode(point.process), "invocation": encode(invocation),
                        "entry": encode(point.source)})).hexdigest()
                    _need(activation.id.value == expected_id,
                          "region activation identity does not bind this exact original invocation/entry")
                activation_count += 1
            statuses[row["status"]] += 1
            if invocation in wanted:
                selected[invocation] = {"line": line, "line_sha256": hashlib.sha256(raw).hexdigest(),
                    "code": row["code"], "binding_index": index, "activation": activation,
                    "anchor": anchor, "status": row["status"], "frontiers": row["frontiers"],
                    "suspended": row["suspended"]}
                if version == 2:
                    selected[invocation]["region_namespace"] = row["region_namespace"]
    _need((digest.hexdigest(), size, count) == (declaration["raw_sha256"], declaration["raw_bytes"], declaration["rows"]),
          "complete invocation raw SHA/bytes/row receipt differs")
    _need(count == report["summary"]["invocations"] and dict(statuses) == report["summary"]["invocation_statuses"],
          "source invocation summary denominator/statuses differ")
    return selected, source_artifact, {"rows": count, "raw_bytes": size,
        "raw_sha256": digest.hexdigest(), "region_activations": activation_count,
        "invocation_statuses": dict(sorted(statuses.items()))}


def _write_gzip(path, payload):
    with path.open("xb") as stream:
        with gzip.GzipFile(filename="", fileobj=stream, mode="wb", mtime=0) as output:
            output.write(payload)


def bind_dispatch_sources(source_directory, dispatch_bridge, coordinates, out_dir,
                          *, max_input_bytes=1_000_000_000, max_observations=400_000,
                          composition_index=None):
    """Verify compact inputs and reference every original production observation."""
    _need(type(max_input_bytes) is int and max_input_bytes > 0
          and type(max_observations) is int and max_observations > 0, "invalid input budgets")
    output = Path(out_dir).resolve()
    _need(not output.exists(), "output directory already exists")
    (root, source_report, report_artifact, bindings, binding_artifact, bridge, bridge_artifact,
     artifacts, native, pid, process) = _inputs(source_directory, dispatch_bridge, coordinates, max_input_bytes)
    version = source_report["schema_version"]
    source_scope = None
    if version == 2:
        source_scope = _PartitionedSourceScope(composition_index, source_report)
        for index, binding in enumerate(bindings["bindings"]):
            _need(type(binding["binding_index"]) is int and binding["binding_index"] == index,
                  "source schema2 binding table ordinal differs")
            source_scope.binding(binding)
    observations = bridge["observations"]
    _need(type(observations) is list and len(observations) <= max_observations
          and len(observations) == bridge["marker_nodes"], "marker observation denominator/budget differs")
    wanted, markers, phases, marker_phases = set(), set(), set(), {}
    for observation in observations:
        key = observation["sequence"], observation["phase"]
        _need(observation["marker_instance"] not in markers and key not in phases
              and observation["phase"] in ("span", "output"), "duplicate or unsupported marker observation")
        markers.add(observation["marker_instance"]); phases.add(key)
        marker_phases[observation["marker_instance"]] = key
        context = observation["retained_ancestor"]
        if context is not None:
            _need(context.get("kind") == "retained ancestor context, not a proven direct caller",
                  "bridge context lost its retained-only qualification")
            wanted.add(InvocationKey(pid, observation["python_ident"], context["invocation"]))
    selected, invocation_artifact, source_audit = _load_invocations(root, source_report, bindings, artifacts,
        coordinates, pid, process, wanted, max_input_bytes, max_observations * 4)
    slot_indices = defaultdict(list)
    for index, path in enumerate(bridge["paths"]):
        _need(marker_phases.get(path["marker_instance"]) == (path["sequence"], path["phase"]),
              "qualified slot path points outside the original marker observations")
        slot_indices[path["marker_instance"]].append(index)
    _need(sum(map(len, slot_indices.values())) == bridge["slot_associations"], "qualified slot path denominator differs")
    output.parent.mkdir(parents=True, exist_ok=True)
    counts, gaps, source_frontiers, examples, marker_index = Counter(), Counter(), Counter(), {}, {}
    thread_indices = {thread.id: index for index, thread in enumerate(coordinates.threads)}
    with tempfile.TemporaryDirectory(prefix=".dispatch-sources-", dir=output.parent) as temporary:
        stage = Path(temporary)
        digest, raw_bytes = hashlib.sha256(), 0
        with (stage / "associations.jsonl.gz").open("xb") as compressed:
            with gzip.GzipFile(filename="", fileobj=compressed, mode="wb", mtime=0) as stream:
                for index, observation in enumerate(observations):
                    ancestor, missing = observation["retained_ancestor"], []
                    ancestry = observation["actual_provider_ancestry"]
                    _need(ancestry and ancestry[0]["instance"] == observation["marker_instance"],
                          "marker is not the first original provider ancestry item")
                    reference = _RAW.fullmatch(ancestry[0]["raw_reference"])
                    _need(reference is not None and reference[1] == native["eto"].sha256,
                          "marker raw reference belongs to another native source")
                    marker_reference = ProviderFactReference(native["eto"], reference[2])
                    row = {"observation_index": index, "sequence": observation["sequence"],
                           "phase": observation["phase"], "marker_instance": observation["marker_instance"],
                           "marker_reference": encode(marker_reference), "bridge_pointer": "#/observations/" + str(index),
                           "relationship": "RETAINED_ANCESTOR_CONTEXT", "direct_callsite_established": False,
                           "source_invocation_reference": None, "source_binding_reference": None,
                           "invocation": None, "definition": None, "body": None,
                           "region_activation": None, "region_activation_reference": None,
                           "native_tid_verified_by_bridge": observation["native_tid_verified"],
                           "native_thread": None, "native_thread_reference": None,
                           "qualified_slot_path_indices": slot_indices[observation["marker_instance"]],
                           "frontiers": missing, "status": "UNRESOLVED"}
                    if version == 2:
                        row["region_namespace"] = None
                    if observation["native_tid_verified"] is True:
                        thread = coordinates.thread_for(native["kineto"], observation["native_tid"], "linux_native_tid")
                        if type(thread) is HostThreadInstance:
                            _need(thread.process == process.id, "RF-correlated native thread belongs to another process")
                            row["native_thread"] = encode(thread.id)
                            row["native_thread_reference"] = encode(ProviderFactReference(coordinates.artifact,
                                "#/threads/" + str(thread_indices[thread.id])))
                            counts["native_threads_connected"] += 1
                        else:
                            missing.append("RF_NATIVE_THREAD_COORDINATE_UNRESOLVED")
                    else:
                        missing.append("MARKER_RF_NATIVE_TID_UNVERIFIED")
                    if ancestor is None:
                        missing.append("RETAINED_ANCESTOR_MISSING")
                    else:
                        invocation = InvocationKey(pid, observation["python_ident"], ancestor["invocation"])
                        row["invocation"] = encode(invocation)
                        source = selected.get(invocation)
                        if source is None:
                            missing.append("SOURCE_INVOCATION_UNAVAILABLE")
                        else:
                            binding = bindings["bindings"][source["binding_index"]]
                            _need(source["code"] == ancestor["code"]
                                  and binding["code_capture"]["code"]["filename"] == ancestor["source_file"],
                                  "retained context code/source filename differs from its actual invocation")
                            counts["retained_contexts_matched"] += 1
                            row["source_invocation_reference"] = encode(ProviderFactReference(invocation_artifact,
                                "#/lines/" + str(source["line"])))
                            row["source_binding_reference"] = encode(ProviderFactReference(binding_artifact,
                                "#/bindings/" + str(source["binding_index"])))
                            row["source_invocation_line_sha256"] = source["line_sha256"]
                            row["definition"], row["body"] = binding["definition"], binding["body"]
                            if version == 2:
                                row["region_namespace"] = source["region_namespace"]
                            row["status"] = "RETAINED_INVOCATION_LINKED"
                            if binding["definition"] is None:
                                missing.append("SOURCE_DEFINITION_UNAVAILABLE")
                            else:
                                row["status"] = "RETAINED_SOURCE_LINKED"
                                counts["source_definitions_connected"] += 1
                            if binding["body"] is None:
                                missing.append("CANONICAL_BODY_UNAVAILABLE")
                            else:
                                row["status"] = "RETAINED_BODY_LINKED"
                                counts["source_bodies_connected"] += 1
                            if source["activation"] is not None:
                                row["region_activation"] = encode(source["activation"].id)
                                row["region_activation_reference"] = encode(ProviderFactReference(invocation_artifact,
                                    "#/lines/" + str(source["line"]) + "/region_activation"))
                                counts["region_activations_connected"] += 1
                            elif binding["body"] is not None:
                                missing.append("REGION_ACTIVATION_UNAVAILABLE")
                            row["source_frontiers"] = source["frontiers"]
                            row["source_interface_frontiers"] = binding["interface_frontiers"]
                            source_frontiers.update(source["frontiers"])
                    counts[row["status"]] += 1; gaps.update(missing)
                    examples.setdefault(row["status"], row)
                    payload = _canonical(row) + b"\n"
                    stream.write(payload); digest.update(payload); raw_bytes += len(payload)
                    marker_index[row["marker_instance"]] = {"line": index + 1,
                                                            "line_sha256": hashlib.sha256(payload).hexdigest()}
        _need(len(observations) == sum(counts[status] for status in ("UNRESOLVED", "RETAINED_INVOCATION_LINKED",
              "RETAINED_SOURCE_LINKED", "RETAINED_BODY_LINKED")), "association row conservation failed")
        _need(gaps["RETAINED_ANCESTOR_MISSING"] == bridge["gaps"].get("retained_ancestor_missing", 0),
              "missing retained-ancestor count differs from the original bridge")
        index_payload = _canonical({"schema": "scar.dispatch-source-index", "schema_version": 1,
                                    "markers": marker_index})
        _write_gzip(stage / "marker-index.json.gz", index_payload)
        report = {"schema": "scar.dispatch-source-associations", "schema_version": version,
            "scope": "original production marker to retained source invocation references",
            "run": encode(coordinates.run), "process": encode(process),
            "coordinate_binding": encode(coordinates.artifact),
            "source_report": encode(report_artifact), "source_bindings": encode(binding_artifact),
            "source_invocations": encode(invocation_artifact), "dispatch_bridge": encode(bridge_artifact),
            "source_current_rawscan_receipt_verified": True,
            "source_invocation_byte_receipt_verified": True,
            "source_rawscan_repeated_here": False,
            "source_conditions": source_report["conditions"], "source_witness_mode": source_report["witness_mode"],
            "source_audit": source_audit, "summary": dict(sorted(counts.items())),
            "frontiers": dict(sorted(gaps.items())), "source_frontiers": dict(sorted(source_frontiers.items())),
            "upstream_dispatch_gaps": bridge["gaps"],
            "unqualified_payload_slots_reference": encode(ProviderFactReference(bridge_artifact, "#/gaps/unqualified_payload_slots")),
            "observations": {"path": "associations.jsonl.gz", "rows": len(observations),
                "raw_sha256": digest.hexdigest(), "raw_bytes": raw_bytes},
            "index": {"path": "marker-index.json.gz", "raw_sha256": hashlib.sha256(index_payload).hexdigest(),
                      "raw_bytes": len(index_payload)}, "examples": examples,
            "conditions": ["the supplied production bridge producer performed its declared raw marker/RF/context verification",
                "the source producer performed its declared current raw call scan; its exact output bytes and coordinates were checked here",
                "source code/body proof keeps the source report producer conditions",
                "retained ancestry does not establish a direct Python/ATen call or a global Python-ident/native-TID equality",
                "unqualified payload leaves remain upstream gaps; compact bridge does not carry their individual raw descriptions"],
            **_AUTHORITY}
        if source_scope is not None:
            report["partitioned_source_scope_audit"] = source_scope.audit()
        (stage / "report.json").write_bytes(_canonical(report))
        (stage / "capture-coordinates.json").write_bytes(coordinates.payload)
        output.mkdir(exist_ok=False)
        for name in ("capture-coordinates.json", "associations.jsonl.gz", "marker-index.json.gz", "report.json"):
            os.rename(stage / name, output / name)
    return report


def query_dispatch_source(output_directory, marker_instance):
    """Resolve one marker's original references; verify the selected output row."""
    root = Path(output_directory)
    report, _ = _read_document(root / "report.json", "scar.dispatch-source-associations", 16_000_000,
                              versions=(1, 2))
    declaration = report["index"]
    index, artifact = _read_document(root / declaration["path"], "scar.dispatch-source-index", 64_000_000)
    _need((artifact.sha256, artifact.size_bytes) == (declaration["raw_sha256"], declaration["raw_bytes"]),
          "query index differs from its receipt")
    selected = index["markers"].get(marker_instance)
    if selected is None:
        raise KeyError(marker_instance)
    with gzip.open(root / report["observations"]["path"], "rb") as stream:
        for line, raw in enumerate(stream, 1):
            if line == selected["line"]:
                _need(hashlib.sha256(raw).hexdigest() == selected["line_sha256"], "queried row hash differs")
                row = strict_loads(raw.decode("utf-8"))
                _need(row["marker_instance"] == marker_instance, "query marker/index differs")
                return row
    raise ValueError("marker index points beyond the retained associations")


__all__ = ["bind_dispatch_sources", "query_dispatch_source"]
