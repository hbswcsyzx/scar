"""Bounded source-owning ATen reference/core interface bridge.

The importer never executes a workload, compiles source or reconstructs the
complete native bundle. Native callbacks/physical observations remain evidence;
only canonical core graphs own producers, Uses and abstract world state.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import gzip
import json
from pathlib import Path
import resource
import time

from scar.ir.record_codec import decode, encode
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.execution.native_port_protocol import (
    PROFILE, attributes, canonical, need, replay_interfaces, _own_capture, _make_evidence,
)
from scar.trace.capture_coordinates import CaptureCoordinates
from scar.trace.native_schema import PROVIDER_REVISION
from scar.trace.tensor_physical_import import canonical_tensor_layout
from scar.store.bundle_partitions import BundlePartitions


@dataclass(frozen=True)
class NativeProtocolWindow:
    first_sequence: int = 1
    max_sequences: int = 16

    def __post_init__(self):
        need(type(self.first_sequence) is int and self.first_sequence == 1,
             "initial adapter requires an exact prefix starting at sequence 1")
        need(type(self.max_sequences) is int and 1 <= self.max_sequences <= 16,
             "native window exceeds 16 sequences")


@dataclass(frozen=True)
class NativeProtocolBudget:
    max_source_raw_bytes: int = 600_000_000
    max_selected_chunks: int = 16
    max_chunk_decoded_bytes: int = 256_000_000
    max_program_bytes: int = 64_000_000
    max_wall_seconds: int = 300
    max_prefix_bytes: int = 262_144
    max_metadata_bytes: int = 4_000_000

    def __post_init__(self):
        need(all(type(v) is int and v > 0 for v in vars(self).values()), "budgets must be positive exact integers")
        need(self.max_source_raw_bytes <= 600_000_000 and self.max_selected_chunks <= 16
             and self.max_chunk_decoded_bytes <= 256_000_000 and self.max_program_bytes <= 64_000_000
             and self.max_wall_seconds <= 300, "adapter hard bounds may not be increased")


@dataclass(frozen=True)
class NativeProtocolWindowResult:
    directory: Path
    program: object
    execution: object
    values: object
    evidence: object
    native_port_evidence: object
    validation: object
    report: dict


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as f:
        f.write(payload)
    return ProviderArtifact(str(path.resolve()), sha256(payload).hexdigest(), len(payload), "application/json")


def _artifact(path, payload, schema):
    return ProviderArtifact(str(path.resolve()), sha256(payload).hexdigest(), len(payload), schema)


def _metadata(path, maximum):
    need(path.is_file() and not path.is_symlink() and path.stat().st_size <= maximum, "metadata absent/symlinked/over budget")
    payload = path.read_bytes()
    return json.loads(payload), payload


def _members(coordinates, root):
    need(type(coordinates) is CaptureCoordinates, "normal CaptureCoordinates input is required")
    need(coordinates.artifact.sha256 == sha256(coordinates.payload).hexdigest()
         and coordinates.artifact.size_bytes == len(coordinates.payload)
         and json.loads(coordinates.payload) == coordinates.report, "coordinate payload changed")
    schemas = ("pytorch.execution-trace.v1", "scar.dispatch-observation.events.v1",
               "scar.tensor-physical-observation.v1", "scar.execution-evidence-collection",
               "scar.dispatch-observation-trace", "scar.tensor-physical-trace")
    result = {}
    for schema in schemas:
        matches = [r for r in coordinates.report["membership"] if r["artifact"]["schema"] == schema]
        need(len(matches) == 1, "source has no unique exact coordinate membership: " + schema)
        row = matches[0]
        artifact = decode(ProviderArtifact, row["artifact"])
        path = Path(row.get("local_path", artifact.uri))
        need(path.is_absolute() and path.resolve().is_relative_to(root) and path.is_file()
             and not path.is_symlink() and coordinates.process_for(artifact, coordinates.target_process.pid)
                == coordinates.target_process, "source escapes exact capture/process membership")
        result[schema] = (artifact, path.resolve())
    return result


def _stream_source(path, artifact, maximum, prefix_bytes, start, seconds, progress):
    digest, size, lines, prefix, tail = sha256(), 0, 0, bytearray(), b""
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as f:
        while data := f.read(1_048_576):
            size += len(data)
            need(size <= maximum and time.monotonic() - start <= seconds, "raw source byte/wall budget exceeded")
            digest.update(data); lines += data.count(b"\n")
            if len(prefix) < prefix_bytes:
                prefix.extend(data[:prefix_bytes - len(prefix)])
            tail = (tail + data)[-16_384:]
    need(size == artifact.size_bytes and digest.hexdigest() == artifact.sha256, "complete source raw SHA/bytes changed")
    if progress:
        progress({"stage": "raw_source_verified", "schema": artifact.schema, "raw_bytes": size,
                  "stored_bytes": path.stat().st_size})
    return bytes(prefix), tail, {"artifact": encode(artifact), "raw_bytes_read": size,
        "stored_bytes_read": path.stat().st_size, "newlines": lines, "retained_prefix_bytes": len(prefix),
        "complete_raw_sha_verified": True, "complete_semantic_parse_performed": False}


def _prefix_lines(payload, max_sequence, schema, pid, nonce=None):
    result = []
    for raw in payload.splitlines(keepends=True):
        if not raw.endswith(b"\n"):
            break
        row = json.loads(raw)
        need(type(row) is dict and row.get("index") == len(result) + 1
             and row.get("process_id") == pid, "source prefix ordinal/process mismatch")
        if nonce is not None:
            need(row.get("nonce") == nonce and row.get("schema") == schema
                 and row.get("schema_version") == 1, "source prefix nonce/schema mismatch")
        if type(row.get("sequence")) is int and row["sequence"] > max_sequence:
            break
        result.append(row)
    need(any(r.get("sequence") == max_sequence for r in result), "source prefix budget did not reach selected window")
    return result


def _eto_prefix(payload, tail, maximum, pid):
    text, suffix, decoder = payload.decode("utf-8"), tail.decode("utf-8"), json.JSONDecoder()
    at = text.find('"nodes": [')
    need(at >= 0 and f'"pid": {pid}' in text[:at] and '"schema": "1.1.1-chakra.0.0.4"' in text[:at],
         "native header/profile differs")
    cursor, nodes = text.index("[", at) + 1, []
    while True:
        while cursor < len(text) and text[cursor] in " \n\r\t,":
            cursor += 1
        if cursor >= len(text) or text[cursor] == "]":
            break
        try:
            node, end = decoder.raw_decode(text, cursor)
        except json.JSONDecodeError:
            break
        need(type(node) is dict and type(node.get("id")) is int, "invalid original ETO node")
        nodes.append(node); cursor = end
        # Include wrappers/ancestors which serialize after the last selected
        # span; stop only when the next dispatch span has closed.
        if node.get("name", "").endswith(f":{maximum + 1}:span"):
            break
    need(any(n.get("name", "").endswith(f":{maximum}:span") for n in nodes),
         "native prefix budget did not reach selected window")
    # The pinned ETO serializes root sentinel last. Locate its actual final
    # object in retained suffix and check the remaining document closure.
    starts = [i for i in range(len(suffix)) if suffix.startswith('{', i)]
    roots = []
    for i in starts:
        try:
            node, end = decoder.raw_decode(suffix, i)
        except json.JSONDecodeError:
            continue
        if type(node) is dict and node.get("id") == 1 and node.get("ctrl_deps") == 1:
            roots.append((node, suffix[end:]))
    need(len(roots) == 1 and roots[0][1].strip().startswith("]")
         and roots[0][0].get("name") == "[pytorch|profiler|execution_trace|process]"
         and attributes(roots[0][0]).get("rf_id") == 0
         and attributes(roots[0][0]).get("tid") == 0
         and attributes(roots[0][0]).get("scope") == 7, "exact native root sentinel missing at document tail")
    return nodes, roots[0][0]


def _closure_ordinals(source, interfaces, model):
    nodes = {n["id"]: n for n in source["nodes"]}
    ordinal = {n["id"]: i for i, n in enumerate(source["nodes"])}
    need(1 not in nodes, "prefix root must be the separately verified final sentinel")
    nodes[1] = source["root_node"]
    ordinal[1] = model["native"]["inventory"]["eto_nodes"] - 1
    wanted = set()
    for interface in interfaces:
        for selected in (interface["node"], interface["span"], interface["output_marker"]):
            current = selected["id"]
            seen = set()
            while current not in seen:
                seen.add(current); wanted.add(current)
                need(current in nodes, "selected native instance lacks original parent closure")
                parent = nodes[current]["ctrl_deps"]
                if current == parent:
                    break
                current = parent
    # Full original object inventory order follows first qualified held epoch.
    object_ordinals = {}
    for row in source["dispatch"]:
        for ref in row.get("observation", {}).get("tensor_references", []):
            if ref.get("identity_qualified") is True and ref["ref"] not in object_ordinals:
                object_ordinals[ref["ref"]] = len(object_ordinals)
    epochs, region_ordinals = {}, {}
    for row in source["physical"]:
        if row["kind"] == "ALLOCATION" and not row.get("gaps"):
            key = (row["device"]["text"], row["provider_allocation_id"])
            epochs.setdefault(key, len(epochs))
        elif row["kind"] == "MARKER":
            for arg in row["arguments"]:
                meta = arg["metadata"]
                if meta.get("status") == "OBSERVED" and not meta.get("gaps") and type(meta.get("provider_allocation_id")) is int:
                    region_ordinals[row["index"], arg["argument_ordinal"]] = len(region_ordinals)
    needs_objects, needs_regions, needs_epochs = set(), set(), set()
    for interface in interfaces:
        for ports in interface["ports"].values():
            for port in ports:
                if not port["tensor"]:
                    continue
                held = port["held"]
                needs_objects.add(held["weak_token"])
                needs_regions.add((held["physical_line"], held["marker_ordinal"]))
                needs_epochs.add((held["metadata"]["device"]["text"], held["metadata"]["provider_allocation_id"]))
    need(needs_epochs <= set(epochs), "selected physical epoch has no prefix allocation ordinal witness")
    offset = model["native"]["memory"]["counts"]["allocation_epochs"]
    requests = {("evidence", "instances"): tuple(sorted(ordinal[n] for n in wanted)),
        ("values", "objects"): tuple(sorted(object_ordinals[w] for w in needs_objects)),
        ("values", "regions"): tuple(sorted(region_ordinals[k] for k in needs_regions)),
        ("values", "allocations"): tuple(sorted(offset + epochs[k] for k in needs_epochs))}
    return requests, {"node_ordinals": {str(n): ordinal[n] for n in wanted},
        "object_ordinals": {w: object_ordinals[w] for w in needs_objects},
        "region_ordinals": {str(k): region_ordinals[k] for k in needs_regions},
        "allocation_prefix_offset": offset}


def _selected_chunks(partitions, requests, budget):
    chunks = []
    for (graph, table), ordinals in requests.items():
        for chunk in partitions.manifest["graphs"][graph]["tables"][table]["chunks"]:
            if any(chunk["first_ordinal"] <= n <= chunk["last_ordinal"] for n in ordinals):
                chunks.append(chunk)
    need(len(chunks) <= budget.max_selected_chunks
         and sum(c["decoded_bytes"] for c in chunks) <= budget.max_chunk_decoded_bytes,
         "exact selected source closure exceeds independent chunk budget")
    return chunks


def _prepare_projection(source, interfaces, selected, out, budget):
    from scar.ir.v2.codec import values_from_dict, evidence_from_dict
    from scar.ir.v2.values import ValueGraph
    from scar.ir.v2.evidence import EvidenceGraph
    values_doc, evidence_doc = ValueGraph().to_dict(), EvidenceGraph().to_dict()
    values_doc.update(schema_version=ValueGraph.SCHEMA_VERSION, objects=[])
    values_doc.pop("validation", None); evidence_doc.pop("validation", None)
    receipts = []
    instance_by_node = {int(r["record"]["metadata"]["node_id"]): r for r in selected["evidence", "instances"]}
    source_nodes = {n["id"]: n for n in [*source["nodes"], source["root_node"]]}
    for node_id, row in instance_by_node.items():
        record = row["record"]; raw = source_nodes[node_id]
        expected = source["native_scope"] + ":eto:" + str(node_id)
        need(record["id"]["value"] == expected and record["process_id"] == source["pid"]
             and record["metadata"]["provider"] == "ETO" and record["metadata"]["ctrl_deps"] == raw["ctrl_deps"]
             and record["metadata"]["rf_id"] == attributes(raw)["rf_id"]
             and record["metadata"]["raw_reference"] == "sha256:" + source["artifacts"]["eto"]["sha256"] + "#/nodes/" + str(row["ordinal"]),
             "original native instance candidate differs from exact raw node/ordinal")
        if node_id == raw["ctrl_deps"]:
            need(record["parent"] is None, "original root has an unexpected parent")
        else:
            need(record["parent"]["value"] == source["native_scope"] + ":eto:" + str(raw["ctrl_deps"]),
                 "original native parent changed")
    objects = {r["record"]["metadata"]["weak_token"]: r["record"] for r in selected["values", "objects"]}
    source["object_records"] = objects
    regions = {(r["record"]["metadata"]["physical_observation"].split("#line/")[1].split("/")[0],
                r["record"]["metadata"]["argument_ordinal"]): r for r in selected["values", "regions"]}
    allocations = {r["record"]["id"]["value"]: r["record"] for r in selected["values", "allocations"]}
    geometry = []
    for interface in interfaces:
        for direction, ports in interface["ports"].items():
            for position, port in enumerate(ports):
                if not port["tensor"]:
                    continue
                held = port["held"]; meta = held["metadata"]
                need(held["weak_token"] in objects and objects[held["weak_token"]]["metadata"]["process_id"] == source["pid"],
                     "original held ObjectInstance candidate differs")
                original = regions.get((str(held["physical_line"]), held["marker_ordinal"]))
                need(original is not None, "original physical StorageRegion missing")
                region = original["record"]
                raw_ref = "sha256:" + source["artifacts"]["eto"]["sha256"] + "#/nodes/" + str(
                    source["node_ordinals"][str(held["marker_node"])]) + "/inputs/values/" + str(held["marker_ordinal"])
                need(region["metadata"]["physical_observation"] == "sha256:" + source["artifacts"]["physical"]["sha256"]
                        + "#line/" + str(held["physical_line"]) + "/arguments/" + str(held["marker_ordinal"])
                     and region["metadata"]["eto_reference"] == raw_ref
                     and region["metadata"]["marker_instance"] == "opinst:" + source["native_scope"] + ":eto:" + str(held["marker_node"])
                     and region["metadata"]["impl_ptr"] == meta["impl_ptr"]
                     and region["metadata"]["provider_tensor_id"] == meta["provider_tensor_id"]
                     and region["offset"] == port["value"][2] and region["shape"] == port["shape"]
                     and region["strides"] == port["strides"] and region["dtype"] == meta["dtype"]
                     and region["device"] == meta["device"]["text"] and region["layout"] == meta["layout"],
                     "original region fields contradict owned marker geometry")
                allocation = allocations.get(region["allocation"]["value"])
                need(allocation is not None and allocation["device"] == region["device"]
                     and allocation["metadata"]["provider_allocation_id"] == meta["provider_allocation_id"]
                     and allocation["metadata"]["address"] == meta["storage_data_ptr"]
                     and allocation["lifetime_scope"] == source["physical_scope"], "original allocation candidate contradicts provider epoch")
                births = [r for r in source["physical"] if r["kind"] == "ALLOCATION"
                          and r["provider_allocation_id"] == meta["provider_allocation_id"]
                          and r["device"]["text"] == region["device"] and r["alloc_size"] > 0]
                need(len(births) == 1 and allocation["nbytes"] == births[0]["alloc_size"],
                     "allocation extent has no unique selected original birth")
                geometry.append({"sequence": interface["sequence"], "direction": direction, "position": position,
                    "object": objects[held["weak_token"]]["id"], "region": region["id"], "allocation": allocation["id"],
                    "point": region["metadata"]["physical_observation"], "association_persistent": False,
                    "logical_content_known": False, "ready": False})
    for (graph, table), rows in selected.items():
        doc = values_doc if graph == "values" else evidence_doc
        for row in rows:
            record = json.loads(canonical(row["record"]))
            derived = None
            if (graph, table) == ("values", "regions"):
                original_layout = record["layout"]
                record["layout"] = canonical_tensor_layout(original_layout,
                    profile=source["physical_profile"], provider_revision=source["provider_revision"])
                record["metadata"].update(provider_layout=original_layout, layout_normalization_rule="PINNED_TORCH_LAYOUT_V1")
                derived = {"rule": "PINNED_TORCH_LAYOUT_V1", "original_layout": original_layout,
                           "projected_layout": record["layout"]}
            doc[table].append(record)
            receipts.append({"graph": graph, "table": table, "original_record": row["record"],
                "source_locator": row["locator"], "source_verification": row["verification"], "derived": derived})
    values, evidence = values_from_dict(values_doc), evidence_from_dict(evidence_doc)
    vp, ep = canonical(values.to_dict()), canonical(evidence.to_dict())
    va = _artifact(out / "source-values.json", vp, values.SCHEMA)
    ea = _artifact(out / "source-evidence.json", ep, evidence.SCHEMA)
    rp = canonical({"schema": "scar.native-source-window-receipts", "schema_version": 1,
        "values_projection": encode(va), "evidence_projection": encode(ea), "records": receipts,
        "physical_associations": geometry, "whole_source_graph_identity_claimed": False})
    return values, evidence, va, ea, geometry, {
        "source-values.json": vp, "source-evidence.json": ep, "source-projection-receipts.json": rp}


def _project(source, interfaces, selected, out, budget):
    """Preserve prefix publication while batch callers preflight pure bytes."""
    *result, payloads = _prepare_projection(source, interfaces, selected, out, budget)
    for name, payload in payloads.items():
        _write(out / name, payload)
    return tuple(result)


def _build_program(interfaces, source, interface_artifact):
    from scar.ir.program.model import (Behavior, Block, BlockArgument, CompletionResult,
        CompletionSignature, CompletionSuccessor, DataValue, ExitKind, ExitPort, Operation,
        ProgramGraph, ReferenceValue, Region, StateLocation, StateVersionValue,
        Terminator, TerminatorKind, Use, UseRole, value_type)
    from scar.ir.program.ids import (BlockID, LocationID, NativeBoundaryID, OperationID,
        ProviderID, RegionID, UseID, ValueID)
    from scar.ir.program.providers import (ProviderArtifactKind, ProviderBinding, ProviderCaptureMode,
        ProviderCollectionDomain, ProviderCollectionObservation, ProviderCoverage,
        ProviderCoverageDomain, ProviderElement, ProviderElementKind, ProviderEnvelope,
        ProviderPathIndex, ProviderPathKey, ProviderRegion, ProviderRegionRelation,
        ProviderRunScope, ProviderStage)
    from scar.ir.program.native import (NativeBoundary, NativeInputSlot, NativeOutputSlot,
        EntryPortRef, ExitPortRef, CoreInputPort, CoreOutputPort)
    from scar.ir.v2.common import Completeness
    catalog = RegionID("aten-interface:catalog")
    catalog_block, catalog_return = BlockID(catalog.value + ":entry"), OperationID(catalog.value + ":return")
    operations = [Operation(catalog_return, "interface catalog; not a runtime invocation", (Behavior.CONTROL,),
                            terminator=Terminator(TerminatorKind.RETURN, exit="normal"))]
    regions = [Region(catalog, "observed ATen interface definitions", catalog_block,
                      (Block(catalog_block, (), (catalog_return,)),), (ExitPort("normal", ExitKind.NORMAL, ()),))]
    values, locations, bindings, provider_regions, boundaries, layouts = [], [], [], [], [], {}
    definition_provider, execution_provider = ProviderID("aten-schema:" + PROVIDER_REVISION), ProviderID("eto:" + source["native_scope"])
    fact = ProviderFactReference(interface_artifact, "#")

    def envelope(id_, name, artifact, kind, mode, scope):
        return ProviderEnvelope(id_, name, None, PROVIDER_REVISION, artifact, kind, mode, scope,
            (), (ProviderStage("pinned schema/observed protocol interface", fact),), (),
            tuple(ProviderCoverage(d, Completeness.PARTIAL if d in (ProviderCoverageDomain.STRUCTURE,
                ProviderCoverageDomain.DATAFLOW) else Completeness.UNKNOWN,
                fact if d in (ProviderCoverageDomain.STRUCTURE, ProviderCoverageDomain.DATAFLOW) else None,
                "bounded reference interface; contents, effects, aliases and completion readiness remain unproved")
                for d in ProviderCoverageDomain),
            tuple(ProviderCollectionObservation(d, None, "instrumentation impact/cost not established") for d in ProviderCollectionDomain))

    eto_artifact = decode(ProviderArtifact, source["artifacts"]["eto"])
    envelopes = (envelope(definition_provider, "pinned ATen schema interface", interface_artifact,
            ProviderArtifactKind.DEFINITION_GRAPH, ProviderCaptureMode.STATIC_ANALYSIS, None),
        envelope(execution_provider, "PyTorch ETO", eto_artifact, ProviderArtifactKind.EXECUTION_EVIDENCE,
            ProviderCaptureMode.REAL_EXECUTION, ProviderRunScope(source["run"], source["pid"],
                "dispatch prefix sequences 1.." + str(source["max_sequences"]), "ETO collector ordering; no per-node clock")))
    unique = {i["signature_id"]: i for i in interfaces}
    for sig_id, interface in unique.items():
        prefix = "aten-interface:" + sig_id
        region = RegionID(prefix)
        entry, normal, failed = (BlockID(prefix + ":" + s) for s in ("entry", "normal", "raised"))
        invoke, returned, raised = (OperationID(prefix + ":" + s) for s in ("invoke", "return", "raise"))
        location = LocationID(prefix + ":world")
        locations.append(StateLocation(location, "opaque native world; domain/alias set unresolved"))
        before, after, error = [], [], []

        def port_value(block, ordinal, port, label):
            id_ = ValueID(prefix + ":" + label + ":" + str(ordinal))
            origin = BlockArgument(block, ordinal)
            return (ReferenceValue(id_, region, origin) if port["tensor"]
                    else DataValue(id_, region, origin, "native.boxed:" + port["type"]))

        for j, port in enumerate(interface["ports"]["inputs"]):
            before.append(port_value(entry, j, port, "input"))
        before.append(StateVersionValue(ValueID(prefix + ":world.before"), region, BlockArgument(entry, len(before)), location))
        for j, port in enumerate(interface["ports"]["outputs"]):
            after.append(port_value(normal, j, port, "output"))
        after.append(StateVersionValue(ValueID(prefix + ":world.after"), region, BlockArgument(normal, len(after)), location))
        error = [ReferenceValue(ValueID(prefix + ":exception"), region, BlockArgument(failed, 0)),
                 StateVersionValue(ValueID(prefix + ":world.raised"), region, BlockArgument(failed, 1), location)]
        values.extend([*before, *after, *error])

        def uses(op, records):
            return tuple(Use(UseID(op.value + ":use:" + str(j)), value.id,
                UseRole.REFERENCE if type(value) is ReferenceValue else
                UseRole.STATE_CONTENT if type(value) is StateVersionValue else UseRole.DATA)
                for j, value in enumerate(records))

        input_uses, normal_uses, error_uses = uses(invoke, before), uses(returned, after), uses(raised, error)
        normal_types, error_types = tuple(value_type(v) for v in after), tuple(value_type(v) for v in error)
        operations.extend((
            Operation(invoke, interface["signature"]["schema"], (Behavior.COMPUTE, Behavior.CONTROL), input_uses,
                effects_complete=False, terminator=Terminator(TerminatorKind.INVOKE, successors=(
                    CompletionSuccessor(ExitKind.NORMAL, normal, tuple(CompletionResult(j) for j in range(len(after)))),
                    CompletionSuccessor(ExitKind.RAISE, failed, tuple(CompletionResult(j) for j in range(len(error)))))),
                completions=(CompletionSignature(ExitKind.NORMAL, normal_types), CompletionSignature(ExitKind.RAISE, error_types)),
                invoke_arguments=tuple(u.id for u in input_uses)),
            Operation(returned, "normal native completion", (Behavior.CONTROL,), normal_uses,
                terminator=Terminator(TerminatorKind.RETURN, exit="normal", values=tuple(u.id for u in normal_uses))),
            Operation(raised, "possible native exception", (Behavior.CONTROL,), error_uses,
                terminator=Terminator(TerminatorKind.RAISE, exit="raised", values=tuple(u.id for u in error_uses)))))
        regions.append(Region(region, interface["signature"]["schema"], entry,
            (Block(entry, tuple(v.id for v in before), (invoke,)), Block(normal, tuple(v.id for v in after), (returned,)),
             Block(failed, tuple(v.id for v in error), (raised,))),
            (ExitPort("normal", ExitKind.NORMAL, normal_types), ExitPort("raised", ExitKind.RAISE, error_types)), parent=catalog))
        provider_regions.extend((ProviderRegion(definition_provider, sig_id, region, ProviderRegionRelation.DEFINES_REPRESENTATION),
            ProviderRegion(execution_provider, sig_id, region, ProviderRegionRelation.OBSERVATION_SCOPE)))
        bindings.append(ProviderBinding(definition_provider, region, ProviderElement(ProviderElementKind.OPERATION, sig_id), invoke))
        for direction, records, actual_uses in (("inputs", before[:-1], input_uses[:-1]), ("outputs", after[:-1], ())):
            for j, value in enumerate(records):
                path = (ProviderPathKey(direction), ProviderPathIndex(j))
                kind = ProviderElementKind.REFERENCE_VALUE if type(value) is ReferenceValue else ProviderElementKind.DATA_VALUE
                bindings.append(ProviderBinding(definition_provider, region, ProviderElement(kind, sig_id, path), value.id))
                if direction == "inputs":
                    bindings.append(ProviderBinding(definition_provider, region, ProviderElement(ProviderElementKind.USE, sig_id, path), actual_uses[j].id))
        sig_fact = ProviderFactReference(interface_artifact, "#/interfaces/" + sig_id)
        boundary = NativeBoundary(NativeBoundaryID(prefix + ":boundary"), definition_provider, region, sig_fact,
            ProviderFactReference(interface_artifact, "#/interfaces/" + sig_id + "/inputs"),
            ProviderFactReference(interface_artifact, "#/interfaces/" + sig_id + "/outputs"),
            tuple(NativeInputSlot(j, "ordered boxed input", sig_fact, EntryPortRef(region, v.id)) for j, v in enumerate(before[:-1])),
            tuple(NativeOutputSlot(j, "ordered normal output", sig_fact, ExitPortRef(region, "normal", j)) for j, v in enumerate(after[:-1])),
            (CoreInputPort(EntryPortRef(region, before[-1].id), "opaque world, not a schema data slot"),),
            (CoreOutputPort(ExitPortRef(region, "normal", len(after) - 1), "opaque world after; contents unknown"),
             CoreOutputPort(ExitPortRef(region, "raised", 0), "unobserved exception"),
             CoreOutputPort(ExitPortRef(region, "raised", 1), "unobserved world on failure")))
        boundaries.append(boundary)
        layouts[sig_id] = {"region": region, "entry": entry, "normal": normal, "invoke": invoke,
            "return": returned, "before": before, "after": after, "input_uses": input_uses,
            "output_uses": normal_uses, "boundary": boundary}
    graph = ProgramGraph(catalog, tuple(regions), tuple(operations), tuple(values), tuple(locations),
        provider_envelopes=envelopes, provider_regions=tuple(provider_regions), provider_bindings=tuple(bindings),
        native_boundaries=tuple(boundaries))
    from scar.ir.program.validation import require_valid
    require_valid(graph)
    return graph, layouts


def _build_execution(program, layouts, interfaces, source, coordinates, program_artifact, values_artifact, evidence_artifact):
    from scar.ir.program.codec import dumps as program_dumps
    from scar.ir.execution.coordinates import (BlockVisit, ControlTransfer, ExecutionSegment, InitialEntry,
        OperationOccurrence, ProgramSnapshot, RegionActivation, UseOccurrence, ValueOccurrence)
    from scar.ir.execution.common import EvidencePoint
    from scar.ir.execution.ids import (BlockVisitID, DenotationID, ExecutionSegmentID,
        OperationOccurrenceID, RegionActivationID, ValueOccurrenceID)
    from scar.ir.execution.content import NativeInputRef, NativeOutputRef, ObjectIdentity, ObjectRef, ValueDenotation
    from scar.ir.execution.model import ExecutionModel, LegacyOperationRef, OccurrenceEvidenceBinding
    from scar.ir.v2.ids import ObjectID, OperationInstanceID
    activations, segments, visits, operations, values, uses, transfers, denotations, evidence_bindings = ([] for _ in range(9))
    eto_artifact, dispatch_artifact = (decode(ProviderArtifact, source["artifacts"][k]) for k in ("eto", "dispatch"))
    for interface in interfaces:
        prefix = "native-port:" + source["run"] + ":" + str(interface["sequence"])
        static = layouts[interface["signature_id"]]
        entry_fact = ProviderFactReference(dispatch_artifact, "#line/" + str(interface["source_lines"][0]))
        output_fact = ProviderFactReference(dispatch_artifact, "#line/" + str(interface["source_lines"][1]))
        point = EvidencePoint(coordinates.run.id, coordinates.target_process.id, entry_fact)
        activation, segment = RegionActivationID(prefix), ExecutionSegmentID(prefix + ":segment")
        entry, normal = BlockVisitID(prefix + ":entry"), BlockVisitID(prefix + ":normal")
        invoke, returned = OperationOccurrenceID(prefix + ":invoke"), OperationOccurrenceID(prefix + ":return")
        activations.append(RegionActivation(activation, static["region"], coordinates.target_process.id, point))
        # Dispatch native TID is explicit, but thread_for may return unresolved
        # for this source artifact; it is never replaced with ETO tid or PID.
        thread = coordinates.thread_for(dispatch_artifact, source["owner_native_tid"], "linux_native_tid")
        host = thread.id if hasattr(thread, "id") else thread
        segments.append(ExecutionSegment(segment, activation, host, InitialEntry(point)))
        visits.extend((BlockVisit(entry, segment, static["entry"]), BlockVisit(normal, segment, static["normal"])))
        operations.extend((OperationOccurrence(invoke, entry, static["invoke"]), OperationOccurrence(returned, normal, static["return"])))
        transfers.append(ControlTransfer(invoke, 0, normal))
        for direction, definitions, visit, occurrence, static_uses in (
                ("inputs", static["before"], entry, invoke, static["input_uses"]),
                ("outputs", static["after"], normal, returned, static["output_uses"])):
            for j, value in enumerate(definitions):
                actual = ValueOccurrenceID(prefix + ":" + direction + ":" + str(j))
                values.append(ValueOccurrence(actual, value.id, visit))
                uses.append(UseOccurrence(occurrence, static_uses[j].id, actual))
                ports = interface["ports"][direction]
                if j >= len(ports) or not ports[j]["tensor"]:
                    continue
                held = ports[j]["held"]
                original = source["object_records"][held["weak_token"]]
                identity = ObjectIdentity(ObjectRef(values_artifact, ObjectID(original["id"]["value"])))
                basis = (NativeInputRef(static["boundary"].id, entry, j) if direction == "inputs"
                         else NativeOutputRef(static["boundary"].id, returned, j))
                denotations.append(ValueDenotation(DenotationID(prefix + ":" + direction + ":denotation:" + str(j)),
                    actual, identity, basis, entry_fact if direction == "inputs" else output_fact))
        native_id = OperationInstanceID(source["native_scope"] + ":eto:" + str(interface["node"]["id"]))
        native_fact = ProviderFactReference(eto_artifact, "#/nodes/" + str(source["node_ordinals"][str(interface["node"]["id"])]))
        evidence_bindings.append(OccurrenceEvidenceBinding(invoke, LegacyOperationRef(evidence_artifact, native_id), native_fact))
    return ExecutionModel(ProgramSnapshot(program_artifact, json.loads(program_dumps(program))["schema_version"]),
        runs=(coordinates.run,), processes=coordinates.processes, threads=coordinates.threads,
        activations=tuple(activations), segments=tuple(segments), visits=tuple(visits), operations=tuple(operations),
        values=tuple(values), uses=tuple(uses), transfers=tuple(transfers), evidence_bindings=tuple(evidence_bindings),
        denotations=tuple(denotations))


def bind_native_protocol_window(coordinates, capture_directory, partitioned_native_manifest,
                                out_dir, *, expected_manifest_sha256, capture_model_path,
                                expected_capture_model_sha256, window=NativeProtocolWindow(),
                                budget=NativeProtocolBudget(), progress=None):
    """Own raw inputs and construct/validate one bounded actual native window.

    ``coordinates`` must come from normal bind_capture_coordinates. That
    independently measured scope verification is distinct from this function's
    three-source budget. This entry performs another exact three-source pass;
    it makes no unverified saved-result reuse claim.
    """
    from scar.ir.program.codec import dumps as program_dumps
    from scar.ir.execution.codec import dumps as execution_dumps
    from scar.ir.execution.validation import validate
    start = time.monotonic()
    need(type(window) is NativeProtocolWindow and type(budget) is NativeProtocolBudget,
         "exact window/budget records are required")
    window.__post_init__(); budget.__post_init__()
    root, out = Path(capture_directory).resolve(), Path(out_dir).resolve()
    need(root.is_dir() and not out.exists(), "capture root absent or output is not fresh")
    out.mkdir(parents=True)
    inputs = _members(coordinates, root)
    partitions = BundlePartitions(partitioned_native_manifest)
    need(partitions.manifest_receipt["physical_sha256"] == expected_manifest_sha256, "native manifest receipt changed")
    model, model_bytes = _metadata(Path(capture_model_path).resolve(), budget.max_metadata_bytes)
    need(sha256(model_bytes).hexdigest() == expected_capture_model_sha256, "capture-model hint artifact changed")
    native = model["native"]
    need(native["provider_revision"] == PROVIDER_REVISION and native["pid"] == coordinates.target_process.pid,
         "native archive process/provider differs")
    meta = {}
    for schema in ("scar.execution-evidence-collection", "scar.dispatch-observation-trace", "scar.tensor-physical-trace"):
        artifact, path = inputs[schema]
        document, payload = _metadata(path, budget.max_metadata_bytes)
        need(len(payload) == artifact.size_bytes and sha256(payload).hexdigest() == artifact.sha256,
             "participating metadata raw receipt changed")
        meta[schema] = document
    collector = meta["scar.execution-evidence-collection"]
    dispatch_meta, physical_meta = meta["scar.dispatch-observation-trace"], meta["scar.tensor-physical-trace"]
    need(collector.get("status") == "CLOSED" and collector.get("failures") == []
         and collector["provider"]["torch_git_version"] == PROVIDER_REVISION
         and dispatch_meta.get("profile") == "scar.dispatch-marker-collector-v1"
         and dispatch_meta.get("provider_revision") == PROVIDER_REVISION and not dispatch_meta.get("gaps")
         and dispatch_meta.get("errors") == [] and dispatch_meta.get("dropped_events") == 0
         and physical_meta.get("profile") == "scar.tensor-physical-event-tree-v1"
         and physical_meta.get("provider_revision") == PROVIDER_REVISION
         and physical_meta.get("traversal_completed") is True
         and physical_meta.get("marker_ordered_slot_correspondence_established") is True
         and physical_meta.get("allocation_receipt_traversal_complete") is True
         and not physical_meta.get("errors") and not physical_meta.get("gaps") and physical_meta.get("frontier") is None,
         "participating collector/profile is not qualified for this adapter")
    pid, nonce = dispatch_meta["process_id"], dispatch_meta["nonce"]
    need(pid == physical_meta["process_id"] == collector["pid"] == coordinates.target_process.pid
         and nonce == physical_meta["nonce"], "participating metadata process/nonce differs")
    schemas = {"eto": "pytorch.execution-trace.v1", "dispatch": "scar.dispatch-observation.events.v1",
               "physical": "scar.tensor-physical-observation.v1"}
    raw_total = sum(inputs[s][0].size_bytes for s in schemas.values())
    need(raw_total <= budget.max_source_raw_bytes, "three-source declared raw byte preflight exceeded")
    # Meta links are exact original artifacts, never filenames/nearest-time hints.
    for label, artifact in (("native_manifest", inputs["scar.execution-evidence-collection"][0]),
                             ("dispatch_metadata", inputs["scar.dispatch-observation-trace"][0]),
                             ("dispatch_observations", inputs[schemas["dispatch"]][0])):
        declaration = physical_meta["inputs"][label]
        need((declaration["path"], declaration["raw_sha256"], declaration["raw_bytes"])
             == (artifact.uri, artifact.sha256, artifact.size_bytes), "physical source membership link changed")
    declaration = dispatch_meta["native_manifest"]
    artifact = inputs["scar.execution-evidence-collection"][0]
    need((declaration["path"], declaration["raw_sha256"], declaration["raw_bytes"])
         == (artifact.uri, artifact.sha256, artifact.size_bytes), "dispatch native metadata link changed")
    for key, document in (("dispatch", dispatch_meta), ("physical", physical_meta)):
        artifact = inputs[schemas[key]][0]
        declared = document["file"]
        need((declared["path"], declared["raw_sha256"], declared["raw_bytes"])
             == (artifact.uri, artifact.sha256, artifact.size_bytes), "source closed file receipt changed")
    kineto_members = [r["artifact"] for r in coordinates.report["membership"]
                      if r["artifact"]["schema"] == "pytorch.kineto.chrome-trace.v1"]
    need(len(kineto_members) == 1, "native scope has no exact Kineto coordinate member")
    native_scope = "native:" + sha256(canonical({"eto": inputs[schemas["eto"]][0].sha256,
        "kineto": kineto_members[0]["sha256"], "revision": PROVIDER_REVISION, "pid": pid})).hexdigest()
    need(native_scope == native["scope"], "original native scope differs from exact source artifacts")
    physical_scope = "tensor-physical:" + sha256(canonical({"native_scope": native_scope,
        "profile": physical_meta["profile"], "artifact": encode(inputs[schemas["physical"]][0]),
        "metadata": encode(inputs["scar.tensor-physical-trace"][0])})).hexdigest()
    need(physical_scope == native["tensor_physical"]["scope"], "original physical scope differs from exact artifacts")
    if progress:
        progress({"stage": "native_source_preflight", "declared_raw_bytes": raw_total})
    prefixes, tails, io = {}, {}, []
    for key, schema in schemas.items():
        artifact, path = inputs[schema]
        prefix, tail, receipt = _stream_source(path, artifact, budget.max_source_raw_bytes,
            budget.max_prefix_bytes, start, budget.max_wall_seconds, progress)
        prefixes[key], tails[key] = prefix, tail
        io.append(receipt)
    need(sum(r["raw_bytes_read"] for r in io) <= budget.max_source_raw_bytes, "combined source bytes exceeded")
    need(io[1]["newlines"] == dispatch_meta["file"]["lines"]
         and io[2]["newlines"] == physical_meta["file"]["lines"], "closed complete source line counts changed")
    nodes, root_node = _eto_prefix(prefixes["eto"], tails["eto"], window.max_sequences, pid)
    source = {"pid": pid, "nonce": nonce, "provider_revision": PROVIDER_REVISION,
        "run": coordinates.run.id.value, "coordinate_artifact": encode(coordinates.artifact),
        "owner_native_tid": dispatch_meta["owner_native_tid"], "owner_python_ident": dispatch_meta["owner_python_ident"],
        "native_scope": native_scope, "physical_scope": physical_scope, "physical_profile": physical_meta["profile"],
        "first_sequence": window.first_sequence, "max_sequences": window.max_sequences,
        "artifacts": {k: encode(inputs[s][0]) for k, s in schemas.items()}, "nodes": nodes, "root_node": root_node,
        "dispatch": _prefix_lines(prefixes["dispatch"], window.max_sequences, "", pid),
        "physical": _prefix_lines(prefixes["physical"], window.max_sequences, "scar.tensor-physical-observation", pid, nonce)}
    interfaces, frontiers = replay_interfaces(source)
    need(interfaces, "no actual qualified ATen normal-completion interfaces in selected window")
    requests, hints = _closure_ordinals(source, interfaces, model)
    source.update(hints)
    chunks = _selected_chunks(partitions, requests, budget)
    _write(out / "closure-preflight.json", canonical({"raw_reads": io,
        "requests": [{"graph": g, "table": t, "ordinals": list(ns)} for (g, t), ns in requests.items()],
        "chunks": chunks, "decoded_chunk_bytes": sum(c["decoded_bytes"] for c in chunks),
        "stored_chunk_bytes": sum(c["physical_bytes"] for c in chunks), "semantics_validated": False}))
    if progress:
        progress({"stage": "source_closure_preflight", "chunks": len(chunks),
                  "decoded_bytes": sum(c["decoded_bytes"] for c in chunks), "interfaces": len(interfaces)})
    selected = {}
    for (graph, table), ordinals in requests.items():
        need(time.monotonic() - start <= budget.max_wall_seconds, "native window wall budget exceeded")
        selected[graph, table] = partitions.selected_records(graph, table, ordinals)
        if progress:
            progress({"stage": "selected_source_rows_verified", "graph": graph, "table": table, "records": len(ordinals)})
    values, evidence, value_artifact, evidence_artifact, geometry = _project(source, interfaces, selected, out, budget)
    interface_doc = {"schema": "scar.pinned-aten-protocol-interface", "schema_version": 1,
        "profile": PROFILE, "interfaces": {i["signature_id"]: i["signature"] for i in interfaces},
        "effect_contract": "UNKNOWN outside partial provider schema annotations", "content_version_claimed": False}
    payload = canonical(interface_doc)
    interface_artifact = _artifact(out / "native-interface.json", payload, interface_doc["schema"])
    _write(out / "native-interface.json", payload)
    program, layouts = _build_program(interfaces, source, interface_artifact)
    program_bytes = program_dumps(program).encode()
    need(len(program_bytes) <= budget.max_program_bytes, "canonical program byte budget exceeded")
    program_artifact = _artifact(out / "program.json", program_bytes, "scar.program-graph")
    _write(out / "program.json", program_bytes)
    execution = _build_execution(program, layouts, interfaces, source, coordinates, program_artifact, value_artifact, evidence_artifact)
    _write(out / "execution.json", execution_dumps(execution).encode())
    owned = _own_capture(source)
    native_evidence = _make_evidence(owned, program, execution, value_artifact, evidence_artifact)
    catalogs = {"value_graphs": {value_artifact.sha256: values}, "evidence_graphs": {evidence_artifact.sha256: evidence},
        "artifact_bytes": {interface_artifact.sha256: payload}, "native_port_evidence": native_evidence}
    validation = validate(execution, program, **catalogs)
    _write(out / "validation.json", canonical({"valid": validation.valid,
        "issues": [encode(i) for i in validation.issues], "gaps": [encode(i) for i in validation.gaps]}))
    report = {"schema": "scar.native-protocol-window", "schema_version": 1,
        "status": "REFERENCE_PORTS_VERIFIED" if validation.valid else "INVALID", "profile": PROFILE,
        "run": encode(coordinates.run), "process": encode(coordinates.target_process), "window": encode(window),
        "coordinates": encode(coordinates.artifact), "source_manifest": partitions.manifest_receipt,
        "capture_model_hint": encode(_artifact(Path(capture_model_path).resolve(), model_bytes, "scar.capture-model")),
        "raw_reads": io, "raw_bytes_read": sum(r["raw_bytes_read"] for r in io),
        "stored_raw_bytes_read": sum(r["stored_bytes_read"] for r in io),
        "chunks_read": len(chunks), "decoded_chunk_bytes_read": sum(c["decoded_bytes"] for c in chunks),
        "stored_chunk_bytes_read": sum(c["physical_bytes"] for c in chunks),
        "parsed_prefix_records": {"eto": len(nodes) + 1, "dispatch": len(source["dispatch"]), "physical": len(source["physical"])},
        "capture_source_counts": {"dispatch_attempts": dispatch_meta["dispatch_attempts"],
            "native_nodes": native["inventory"]["eto_nodes"], "physical_rows": physical_meta["file"]["lines"],
            "physical_arguments": physical_meta["counts"]["marker_argument_slots"]},
        "unvisited_sequences": dispatch_meta["dispatch_attempts"] - window.max_sequences,
        "qualified_interfaces": len(interfaces), "static_interfaces": len(layouts),
        "frontiers": frontiers, "tensor_reference_denotations": len(execution.denotations),
        "physical_geometry_associations": len(geometry), "projection_counts": values.validate()["counts"],
        "artifacts": {"program": encode(program_artifact), "interface": encode(interface_artifact),
                      "values_projection": encode(value_artifact), "evidence_projection": encode(evidence_artifact)},
        "old_wholegraph_qualified_identity_reused": False, "content_versions_established": False,
        "complete_state_effects_established": False, "alias_completeness_established": False,
        "resource_readiness_established": False, "target_executions": 0, "compile_calls": 0, "prepare_calls": 0,
        "wall_seconds": time.monotonic() - start, "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "whole_model_established": False, "transformation_authorized": False}
    _write(out / "report.json", canonical(report))
    need(report["wall_seconds"] <= budget.max_wall_seconds, "native window wall budget exceeded")
    need(validation.valid, "native core/execution/reference validation failed; original diagnostics retained")
    return NativeProtocolWindowResult(out, program, execution, values, evidence, native_evidence, validation, report)


__all__ = ["NativeProtocolWindow", "NativeProtocolBudget", "NativeProtocolWindowResult", "bind_native_protocol_window"]
