"""Join owned marker arguments to provider physical epochs in the original IR.

The event-tree epoch is its own provider namespace. It is never equated with
Kineto Ev Idx, an ETO storage token, TensorID or a logical content version.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from hashlib import sha256
import json

from scar.ir.record_codec import encode
from scar.ir.v2.common import EvidenceClaim, EvidenceKind
from scar.ir.v2.evidence import EvidenceEdge, EvidenceEndpoint, EvidenceNodeKind as N, EvidenceRelation
from scar.ir.v2.ids import StorageAllocationID, StorageRegionID
from scar.ir.v2.values import StorageAllocation, StorageRegion
from scar.trace.dispatch_import import _retained_artifact
from scar.trace.files import open_binary, resolve
from scar.trace.native_import import _canonical_hash, _pairs, _constant
from scar.trace.tensor_physical import PROFILE, PROVIDER_REVISION


def _need(condition, message):
    if not condition:
        raise ValueError("physical Tensor bridge: " + message)


def _json(payload):
    return json.loads(payload, object_pairs_hook=_pairs, parse_constant=_constant)


def _integer(value, minimum=0):
    return type(value) is int and value >= minimum


def canonical_tensor_layout(source_layout, *, profile, provider_revision):
    """Translate the pinned provider's layout spelling, not tensor contents.

    Unknown provider layouts remain opaque. This conversion alone establishes
    neither capture membership, allocation bounds, aliasing nor readiness.
    """
    _need(profile == PROFILE and provider_revision == PROVIDER_REVISION,
          "layout conversion requires the exact physical provider profile/revision")
    _need(type(source_layout) is str and source_layout and source_layout != "strided",
          "layout must retain its original provider spelling")
    return "strided" if source_layout == "torch.strided" else source_layout


def import_tensor_physical(result, observations_path, metadata_path, *, coordinates=None,
                           max_bytes=1_000_000_000, max_rows=1_000_000, max_line_bytes=2_000_000):
    """Augment the supplied, validated native bundle without inventing content.

    Import is atomic with respect to source/geometry validation: pending model
    records are constructed first, then installed. Partial sidecars are retained
    as OPEN reports without granting physical associations. Caller paths are
    explicit; metadata URIs are only compared and never followed for reads.
    """
    _need(all(_integer(x, 1) for x in (max_bytes, max_rows, max_line_bytes)), "invalid independent budgets")
    _need(result.report.get("provider_revision") == PROVIDER_REVISION, "unsupported provider")
    _need("tensor_physical" not in result.report, "bridge already imported")
    bridge = result.report.get("dispatch_bridge")
    _need(type(bridge) is dict and bridge.get("production_collector") is True,
          "the original production dispatch bridge is required")
    meta_path, events_path = resolve(metadata_path).resolve(), resolve(observations_path).resolve()
    with open_binary(meta_path) as stream:
        payload = stream.read(min(max_bytes, 2_000_000) + 1)
    _need(len(payload) <= min(max_bytes, 2_000_000), "metadata byte ceiling exceeded")
    meta = _json(payload)
    meta_artifact = _retained_artifact(coordinates, meta_path, sha256(payload).hexdigest(), len(payload),
                                      "scar.tensor-physical-trace")
    _need(meta.get("schema") == "scar.tensor-physical-trace" and meta.get("schema_version") == 1
          and meta.get("profile") == PROFILE and meta.get("provider_revision") == PROVIDER_REVISION,
          "unsupported sidecar schema/profile/provider")
    pid, nonce = meta.get("process_id"), meta.get("nonce")
    _need(_integer(pid, 1) and pid == result.report["pid"] and type(nonce) is str,
          "sidecar process differs from native graph")
    # These are the original raw artifacts already verified by dispatch_import.
    for source_key, bridge_key in (("dispatch_metadata", "metadata"),
                                   ("dispatch_observations", "observations"),
                                   ("native_manifest", "native_meta")):
        declared, original = meta["inputs"][source_key], bridge["artifacts"][bridge_key]
        _need((declared.get("path"), declared.get("raw_sha256"), declared.get("raw_bytes"))
              == (original["uri"], original["sha256"], original["size_bytes"]),
              "sidecar does not bind the original " + source_key)
    declarations = meta.get("file")
    _need(type(declarations) is dict, "sidecar lacks a closed event-file receipt")
    raw_size, digest, rows = 0, sha256(), []
    with open_binary(events_path) as stream:
        while True:
            line = stream.readline(max_line_bytes + 1)
            if not line:
                break
            raw_size += len(line)
            _need(len(line) <= max_line_bytes and line.endswith(b"\n")
                  and raw_size + len(payload) <= max_bytes and len(rows) < max_rows,
                  "event source exceeds independent complete-line/row/byte ceilings")
            digest.update(line)
            row = _json(line)
            _need(type(row) is dict and row.get("index") == len(rows) + 1
                  and row.get("schema") == "scar.tensor-physical-observation"
                  and row.get("schema_version") == 1 and row.get("process_id") == pid
                  and row.get("nonce") == nonce, "event ordinal/schema/process/nonce mismatch")
            _need(row.get("kind") in ("MARKER", "ALLOCATION"), "unsupported physical record kind")
            rows.append(row)
    _need((declarations.get("raw_bytes"), declarations.get("raw_sha256"), declarations.get("lines"))
          == (raw_size, digest.hexdigest(), len(rows)), "closed physical raw-byte receipt differs")
    artifact = _retained_artifact(coordinates, events_path, digest.hexdigest(), raw_size,
                                  "scar.tensor-physical-observation.v1")
    _need(declarations.get("path") == artifact.uri, "physical logical event URI differs")
    if coordinates is not None:
        _need(all(coordinates.process_for(item, pid) == coordinates.target_process
                  for item in (artifact, meta_artifact)), "physical artifact has no verified process membership")
    report = {"schema": "scar.tensor-physical-import", "schema_version": 1, "profile": PROFILE,
        "artifacts": {"observations": encode(artifact), "metadata": encode(meta_artifact)},
        "capture_membership_verified": coordinates is not None, "rows": len(rows),
        "source_status": meta.get("status"), "source_gaps": meta.get("gaps"),
        "source_frontier": meta.get("frontier"), "associations": [], "epochs": [],
        "legacy_kineto_allocation_correspondence_established": False,
        "layout_normalization_rule": "PINNED_TORCH_LAYOUT_V1",
        "logical_versions_established": False, "materializations_established": False,
        "state_effects_established": False, "resource_readiness_established": False,
        "whole_model_established": False, "transformation_authorized": False}
    complete = (meta.get("traversal_completed") is True
        and meta.get("marker_ordered_slot_correspondence_established") is True
        and meta.get("allocation_receipt_traversal_complete") is True
        and not meta.get("errors") and not meta.get("gaps") and meta.get("frontier") is None)
    if not complete:
        report.update(status="OPEN", gaps={"PHYSICAL_COLLECTOR_PARTIAL": 1})
        result.report["tensor_physical"] = report
        return report
    scope = "tensor-physical:" + _canonical_hash({"native_scope": result.report["scope"],
        "profile": PROFILE, "artifact": encode(artifact), "metadata": encode(meta_artifact)})
    report["scope"] = scope
    evidence, values = result.bundle.evidence, result.bundle.values
    native_markers = {}
    for instance in evidence.instances.values():
        if instance.metadata.get("provider") != "ETO":
            continue
        label = result.bundle.semantic.definitions[instance.definition].label
        if label.startswith(f"scar-dispatch:{nonce}:{pid}:"):
            _need(label not in native_markers, "duplicate native marker")
            native_markers[label] = instance
    paths = {(p["marker_instance"], p["provider_argument_ordinal"]): p for p in bridge["paths"]}
    contexts = {item["marker_instance"]: item for item in bridge["observations"]}
    old_edges = evidence.edges
    epochs, markers, gaps = defaultdict(list), {}, Counter()

    def reference(row, suffix=""):
        return "sha256:" + artifact.sha256 + "#line/" + str(row["index"]) + suffix

    def key(item):
        device, epoch, ptr = item.get("device"), item.get("provider_allocation_id"), item.get("storage_data_ptr", item.get("ptr"))
        if not (type(device) is dict and type(device.get("text")) is str
                and _integer(epoch, 1) and _integer(ptr, 1)):
            return None
        return device["text"], epoch

    for row in rows:
        if row["kind"] == "ALLOCATION":
            epoch = key(row)
            if epoch is None or type(row.get("alloc_size")) is not int or row.get("gaps"):
                gaps["ALLOCATION_RECEIPT_UNQUALIFIED"] += 1
            else:
                epochs[epoch].append(row)
        else:
            name = row.get("marker")
            _need(type(name) is str and name not in markers, "duplicate/invalid physical marker")
            markers[name] = row
    _need(set(markers) == set(native_markers), "owned tree/ETO marker sets differ")
    _need(len(markers) == meta.get("confirmed_marker_count"), "closed marker count differs")
    pending, pending_regions, pending_edges = {}, [], []

    def allocation(epoch, tensor=None):
        if epoch in pending:
            return pending[epoch]
        records = epochs.get(epoch, [])
        addresses = {row["ptr"] for row in records}
        _need(len(addresses) <= 1, "one provider epoch has conflicting storage pointers")
        births = [r for r in records if r["alloc_size"] > 0]
        frees = [r for r in records if r["alloc_size"] < 0]
        _need(len(births) <= 1 and len(frees) <= 1, "one provider epoch has duplicate birth/free receipts")
        _need(not births or not frees or births[0]["alloc_size"] == -frees[0]["alloc_size"],
              "one provider epoch has conflicting birth/free extents")
        if tensor is not None and addresses:
            _need(tensor["storage_data_ptr"] in addresses, "Tensor pointer differs from its provider allocation epoch")
        identifier = StorageAllocationID(scope + ":epoch:" + _canonical_hash(epoch))
        extent = births[0]["alloc_size"] if births else None
        record = StorageAllocation(identifier, epoch[0], nbytes=extent,
            allocator_token="provider-allocation-id:" + str(epoch[1]), lifetime_scope=scope,
            metadata={"identity_basis": "same profiler result calculateUniqueTensorIDs allocation_id",
                "provider_allocation_id": epoch[1], "address": next(iter(addresses),
                    tensor["storage_data_ptr"] if tensor is not None else None),
                "allocation_receipts": [reference(row) for row in records],
                "birth_reference": reference(births[0]) if births else None,
                "free_reference": reference(frees[0]) if frees else None,
                "lifetime_status": "OBSERVED_BIRTH_AND_FREE" if births and frees else
                    "OBSERVED_BIRTH_OPEN_AT_CAPTURE_END" if births else "BIRTH_NOT_OBSERVED",
                "legacy_kineto_allocation_correspondence_established": False,
                "physical_cuda_allocation_established": False, "resource_ready_established": False})
        pending[epoch] = record
        return record

    for epoch in epochs:
        allocation(epoch)
    total_slots, layout_counts = 0, Counter()
    for name, row in markers.items():
        marker = native_markers[name]
        context = contexts.get(marker.id.wire)
        _need(context is not None and _integer(context.get("source_line"), 1)
              and row.get("dispatch_source_line") == context["source_line"]
              and row.get("sequence") == context["sequence"] and row.get("phase") == context["phase"]
              and row.get("dispatch_native_tid") == context["native_tid"]
              and row.get("dispatch_python_ident") == context["python_ident"],
              "physical marker differs from the original dispatch source line/context")
        _need(not row.get("gaps") and row.get("binding_status") == "PROVISIONAL_REQUIRES_FINAL_METADATA",
              "physical marker row is unqualified")
        slots = [s for s in marker.metadata.get("tensor_slots", ()) if s["role"] == "inputs"]
        arguments = row.get("arguments")
        _need(type(arguments) is list and len(arguments) == len(slots) == row.get("expected_argument_count"),
              "physical/ETO marker argument count differs")
        for ordinal, (argument, slot) in enumerate(zip(arguments, slots, strict=True)):
            total_slots += 1
            _need(argument.get("argument_ordinal") == argument.get("dispatch_reference_ordinal") == ordinal
                  and slot["ordered_path"] == [ordinal], "physical/ETO ordered argument path differs")
            tensor = argument.get("metadata")
            _need(type(tensor) is dict, "missing Tensor physical metadata")
            epoch = key(tensor)
            if epoch is None or tensor.get("status") != "OBSERVED" or tensor.get("gaps"):
                gaps["TENSOR_PHYSICAL_REFERENCE_UNQUALIFIED"] += 1
                continue
            provider = evidence.provider_references[slot["provider_reference"]]
            descriptors = [d for d in provider.metadata["descriptors"] if d["descriptor_id"] == slot["descriptor_id"]]
            _need(len(descriptors) == 1, "native argument has no unique original descriptor")
            descriptor = descriptors[0]
            raw = descriptor["tensor_tuple"]
            _need(descriptor["shape"] == tensor["sizes"] and descriptor["strides"] == tensor["strides"]
                  and type(raw) is list and len(raw) == 6 and raw[5] == epoch[0]
                  and _integer(raw[2]), "same marker slot has contradictory geometry/device/offset")
            record = allocation(epoch, tensor)
            # Check pointers even when the epoch was introduced by a receipt.
            _need(record.metadata["address"] == tensor["storage_data_ptr"],
                  "marker Tensor pointer contradicts provider epoch")
            region_id = StorageRegionID(scope + f":region:{row['index']}:{ordinal}")
            loc = reference(row, "/arguments/" + str(ordinal))
            layout = canonical_tensor_layout(tensor["layout"], profile=meta["profile"],
                                             provider_revision=meta["provider_revision"])
            layout_counts[layout] += 1
            region = StorageRegion(region_id, record.id, raw[2], tuple(tensor["sizes"]),
                tuple(tensor["strides"]), tensor["dtype"], epoch[0], layout=layout,
                metadata={"physical_observation": loc, "eto_reference": slot["raw_reference"],
                    "provider_layout": tensor["layout"], "layout_normalization_rule": "PINNED_TORCH_LAYOUT_V1",
                    "marker_instance": marker.id.wire, "argument_ordinal": ordinal,
                    "impl_ptr": tensor["impl_ptr"], "provider_tensor_id": tensor["provider_tensor_id"],
                    "offset_basis": "same held Tensor, exact ETO marker argument storage_offset",
                    "association_persistent": False, "logical_version": None})
            pending_regions.append(region)
            claim = EvidenceClaim(EvidenceKind.INFERRED, (loc, slot["raw_reference"],
                "sha256:" + meta_artifact.sha256 + "#"), scope=scope,
                assumptions=("fixed owned collector passed the same held Tensor to this exact marker slot",
                    "provider allocation_id is capture-local physical identity, not logical content",
                    "association applies only at this marker observation; no permanent object/storage binding",
                    "capture membership verified" if coordinates is not None else "caller supplied these raw artifacts together"))
            pending_edges.append(EvidenceEdge(scope + f":use:{row['index']}:{ordinal}",
                EvidenceRelation.USES_STORAGE, EvidenceEndpoint(N.OPERATION_INSTANCE, marker.id),
                EvidenceEndpoint(N.STORAGE_REGION, region_id), claim))
            original_path = paths.get((marker.id.wire, ordinal))
            object_id = None
            if original_path is not None:
                edge = old_edges[original_path["edge_id"]]
                _need(edge.relation is EvidenceRelation.OBJECT_REFERENCE_ASSOCIATION
                      and edge.target.reference == slot["provider_reference"], "original object slot association differs")
                object_id = edge.source.reference
                pending_edges.append(EvidenceEdge(scope + f":object:{row['index']}:{ordinal}",
                    EvidenceRelation.USES_STORAGE, EvidenceEndpoint(N.OBJECT, object_id),
                    EvidenceEndpoint(N.STORAGE_REGION, region_id), claim))
            else:
                gaps["PYTHON_OBJECT_SLOT_UNQUALIFIED"] += 1
            report["associations"].append({"marker_instance": marker.id.wire,
                "argument_ordinal": ordinal, "physical_reference": loc,
                "provider_reference": slot["provider_reference"], "storage_region": region_id.wire,
                "allocation": record.id.wire, "object": object_id.wire if object_id is not None else None})
    _need(total_slots == meta.get("counts", {}).get("marker_argument_slots"), "closed physical slot count differs")
    _need(sum(len(r) for r in epochs.values()) + gaps["ALLOCATION_RECEIPT_UNQUALIFIED"]
          == meta.get("counts", {}).get("allocation_nodes"), "closed allocation count differs")
    from scar.ir.v2._validation import record_errors
    for record in pending.values():
        _need(not record_errors(record, StorageAllocation, "physical allocation"),
              "invalid typed physical allocation")
    for region in pending_regions:
        _need(not record_errors(region, StorageRegion, "physical storage region"),
              "invalid typed storage geometry")
    for edge in pending_edges:
        _need(not record_errors(edge, EvidenceEdge, "physical evidence edge"),
              "invalid typed physical edge")
    for record in pending.values():
        values.add_allocation(record)
        evidence.register_external(EvidenceEndpoint(N.ALLOCATION, record.id))
        report["epochs"].append({"allocation": record.id.wire, "provider_allocation_id": record.metadata["provider_allocation_id"],
            "device": record.device, "nbytes": record.nbytes, **record.metadata})
    for region in pending_regions:
        values.add_region(region)
        evidence.register_external(EvidenceEndpoint(N.STORAGE_REGION, region.id))
    for edge in pending_edges:
        evidence.add_edge(edge)
    result.bundle.assert_valid()
    report.update(status="IMPORTED_WITH_OPEN_OBLIGATIONS", marker_nodes=len(markers),
        argument_slots=total_slots, physical_slot_associations=len(pending_regions),
        allocation_epochs=len(pending), evidence_edges=len(pending_edges), gaps=dict(gaps),
        source_allocation_receipts=meta["counts"]["allocation_nodes"],
        canonical_region_layout_counts=dict(layout_counts),
        interface_only_claim="observation-scoped object/argument geometry and provider physical epochs")
    result.report["tensor_physical"] = report
    return report


__all__ = ["import_tensor_physical", "canonical_tensor_layout"]
