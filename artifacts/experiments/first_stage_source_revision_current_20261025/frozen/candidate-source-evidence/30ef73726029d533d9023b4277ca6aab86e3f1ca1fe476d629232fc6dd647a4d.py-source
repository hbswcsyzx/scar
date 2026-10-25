"""Retain profiler allocation receipts in the existing value/evidence graphs.

Addresses are scoped allocator slots, not Tensor identities.  Each positive
receipt creates a distinct allocation epoch.  Free pairing uses only a unique
provider event index on one host thread; timestamps and JSON order never decide
lifetimes.  Conflicting slots retain their receipts without a free association.
These are profiler allocator observations, not physical CUDA allocation/free,
content equivalence, synchronization, or proof that open epochs are leaks.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import math

from scar.ir.v2 import (
    EvidenceEndpoint, EvidenceNodeKind, EvidenceRelation, OperationInstance,
    OperationInstanceID, OperationKind, StorageAllocation, StorageAllocationID,
)


_PROFILE = "TORCH_KINETO_ALLOCATOR_V1"


@dataclass(slots=True)
class NativeMemoryRecords:
    rows: tuple[dict, ...]
    report: dict
    source_document: dict | None = None


def _integer(value, *, minimum=None):
    return type(value) is int and (minimum is None or value >= minimum)


def _device(device_type, device_id):
    if device_type == 0 and device_id == -1:
        return "cpu", True
    if device_type == 1 and device_id >= 0:
        return "cuda:" + str(device_id), True
    return "provider-device:" + str(device_type) + ":" + str(device_id), False


def _timestamp(value):
    if type(value) not in (int, float) or value < 0:
        return None
    try:
        scaled = value * 1000
        return round(scaled) if math.isfinite(scaled) else None
    except (OverflowError, ValueError):
        return None


def append_memory_events(importer):
    """Append receipts once to an already loaded, capture-scoped importer.

    ``rows`` contains one typed allocation ID per positive receipt, with raw
    event indices and immutable capture-local selectors for a later independent
    resolver.  ``report.records`` retains every memory record's raw locator,
    including invalid and zero-size diagnostics.  The original document is
    retained by reference, not copied or re-read; no value-graph hash is taken.
    """
    chrome = importer.chrome
    records, valid, slots = [], [], defaultdict(list)
    counts, event_indices = Counter(), Counter()
    if chrome is None:
        return NativeMemoryRecords((), {
            "profile": _PROFILE, "records": [], "counts": {},
            "allocation_lifetimes_complete": False, "physical_cuda_allocation_established": False,
            "logical_content_established": False, "open_epochs_are_leaks": False,
        }, None)
    events = chrome["traceEvents"]
    for index, event in enumerate(events):
        if type(event) is not dict or event.get("name") != "[memory]":
            continue
        counts["memory_records"] += 1
        reference = importer.pointer("kineto", "#/traceEvents/" + str(index))
        args = event.get("args")
        record = {"index": index, "reference": reference, "disposition": "INVALID"}
        records.append(record)
        if type(args) is not dict:
            importer.gap("native_memory_args_invalid", reference,
                         "memory receipt has no object of provider arguments; raw record retained")
            counts["invalid_records"] += 1
            continue
        ev_idx = args.get("Ev Idx")
        if _integer(ev_idx, minimum=0):
            event_indices[ev_idx] += 1
        if event.get("ph") != "i" or event.get("cat") != "cpu_instant_event":
            importer.gap("native_memory_receipt_shape_unsupported", reference,
                         "memory name is not the pinned provider's CPU instant-event receipt; raw record retained")
            counts["invalid_records"] += 1
            continue
        size = args.get("Bytes")
        if type(size) is int and size == 0:
            record["disposition"] = "ZERO_SIZE_DIAGNOSTIC"
            counts["zero_records"] += 1
            importer.gap("native_memory_zero_size", reference,
                         "zero-Bytes record does not establish an allocation or free")
            continue
        process, thread = event.get("pid"), event.get("tid")
        address, device_type, device_id = args.get("Addr"), args.get("Device Type"), args.get("Device Id")
        if not (type(size) is int and size != 0
                and _integer(process, minimum=1) and _integer(thread, minimum=1)
                and _integer(address, minimum=1) and _integer(device_type, minimum=0)
                and _integer(device_id)):
            importer.gap("native_memory_selector_invalid", reference,
                "memory receipt needs exact signed Bytes, positive process/thread/address and integer device selectors")
            counts["invalid_records"] += 1
            continue
        entry = {"index": index, "ev_idx": ev_idx if _integer(ev_idx, minimum=0) else None,
                 "bytes": size, "address": address, "process": process, "thread": thread,
                 "device_type": device_type, "device_id": device_id, "reference": reference,
                 "event": event, "record": record}
        valid.append(entry)
        slots[process, device_type, device_id, address].append(entry)
        counts["positive_receipts" if size > 0 else "negative_receipts"] += 1

    allocation_rows = []
    for slot_entries in slots.values():
        reasons = set()
        threads = {entry["thread"] for entry in slot_entries}
        if len(threads) != 1:
            reasons.add("multiple_host_threads")
        if any(entry["ev_idx"] is None for entry in slot_entries):
            reasons.add("missing_or_invalid_event_index")
        if any(entry["ev_idx"] is not None and event_indices[entry["ev_idx"]] != 1 for entry in slot_entries):
            reasons.add("nonunique_event_index")
        # A conflicted ordering is never repaired by sorting JSON positions or
        # nearby timestamps.  Positive observations still have distinct IDs.
        ordered = (sorted(slot_entries, key=lambda entry: entry["ev_idx"])
                   if not reasons else slot_entries)
        local_pairs, opened, previously_closed = {}, None, False
        if not reasons:
            for entry in ordered:
                if entry["bytes"] > 0:
                    if opened is not None:
                        reasons.add("overlapping_positive_receipts")
                    opened = entry
                elif opened is not None:
                    if -entry["bytes"] != opened["bytes"]:
                        reasons.add("free_size_mismatch")
                    else:
                        local_pairs[opened["index"]] = entry
                        opened = None
                        previously_closed = True
                elif previously_closed:
                    reasons.add("duplicate_or_unobserved_free")
                else:
                    # A free for an allocation born before capture is not a
                    # later generation's free and does not poison its birth.
                    entry["record"]["disposition"] = "UNMATCHED_PREHISTORY_FREE"
        if reasons:
            counts["ambiguous_slots"] += 1
            for reason in sorted(reasons):
                importer.gap("native_memory_" + reason, slot_entries[0]["reference"],
                    "allocator slot cannot establish free pairing: " + reason + "; all receipts retained")
            local_pairs.clear()
        generation = 0
        for entry in ordered:
            if entry["bytes"] <= 0:
                continue
            free = local_pairs.get(entry["index"])
            allocation = StorageAllocationID(importer.scope + ":allocation:kineto:" + str(entry["index"]))
            row = {
                "allocation": allocation, "profile": _PROFILE,
                "birth_index": entry["index"], "birth_ev_idx": entry["ev_idx"],
                "free_index": free["index"] if free is not None else None,
                "free_ev_idx": free["ev_idx"] if free is not None else None,
                "address": entry["address"], "process": entry["process"], "thread": entry["thread"],
                "device_type": entry["device_type"], "device_id": entry["device_id"],
                "generation": entry["index"] if reasons else generation,
                "birth_reference": entry["reference"], "free_reference": free["reference"] if free is not None else None,
                "ordering_status": "UNRESOLVED" if reasons else "PROVIDER_THREAD_ORDER",
                "lifetime_status": ("UNRESOLVED" if reasons else "MATCHED_PROFILER_FREE" if free is not None
                                    else "OPEN_AT_CAPTURE_END"),
            }
            generation += 1
            entry["allocation_row"] = row
            if free is not None:
                free["allocation_row"] = row
            allocation_rows.append(row)

    # Provider serialization need not follow allocation order.  Clean pairs
    # have unique Ev Idx and their births are therefore inserted before frees.
    # Unordered receipts do not have any allocation/free association to apply.
    valid.sort(key=lambda entry: (entry["ev_idx"] is None,
                                  entry["ev_idx"] if entry["ev_idx"] is not None else entry["index"]))
    for entry in valid:
        reference = entry["reference"]
        birth = entry["bytes"] > 0
        row = entry.get("allocation_row")
        domain = "kineto_memory_allocation" if birth else "kineto_memory_free"
        name = "profiler allocation receipt" if birth else "profiler free receipt"
        definition_id = importer.definition(domain, name)
        definition = importer.bundle.semantic.definitions[definition_id]
        definition.kind = OperationKind.ALLOCATION if birth else OperationKind.OPAQUE
        definition.metadata.update(action_tags=["MEM"], provider_memory_contract=_PROFILE,
            physical_cuda_allocation_established=False, tensor_identity_established=False)
        instance_id = OperationInstanceID(importer.scope + ":kineto-memory:" + str(entry["index"]))
        timestamp = _timestamp(entry["event"].get("ts"))
        instance = OperationInstance(instance_id, definition_id, entry["process"], entry["thread"],
            start_ns=timestamp, end_ns=timestamp, metadata={
                "provider": "Kineto", "raw_reference": reference, "category": "cpu_instant_event",
                "raw_category": entry["event"].get("cat"), "raw_phase": entry["event"].get("ph"),
                "clock_domain": "kineto; timestamp is not allocation ordering",
                "thread_namespace": "Kineto host thread", "native_memory": {
                    "profile": _PROFILE, "index": entry["index"], "ev_idx": entry["ev_idx"],
                    "bytes": entry["bytes"], "address": entry["address"],
                    "device_type": entry["device_type"], "device_id": entry["device_id"],
                    "role": "ALLOCATION_RECEIPT" if birth else "FREE_RECEIPT",
                }})
        importer.bundle.evidence.add_instance(instance)
        entry["record"].update(instance=instance_id.wire, bytes=entry["bytes"], ev_idx=entry["ev_idx"])
        if birth:
            metadata = {key: value for key, value in row.items() if key != "allocation"}
            device, supported_device = _device(entry["device_type"], entry["device_id"])
            importer.bundle.values.add_allocation(StorageAllocation(row["allocation"], device,
                nbytes=entry["bytes"], allocator_token="kineto-addr:" + str(entry["address"]),
                lifetime_scope=importer.scope, metadata={"native_memory": metadata,
                    "birth_reference": reference, "allocation_event": True,
                    "identity_basis": "capture-scoped positive profiler memory receipt",
                    "physical_cuda_allocation_established": False, "tensor_identity_established": False}))
            importer.bundle.evidence.register_external(EvidenceEndpoint(EvidenceNodeKind.ALLOCATION, row["allocation"]))
            importer.edge(EvidenceRelation.PRODUCES, instance_id, row["allocation"], importer.claim(reference,
                assumptions=("profiler allocation receipt, not physical device allocator completion",)),
                kind=EvidenceNodeKind.ALLOCATION)
            entry["record"].update(disposition="ALLOCATION_EPOCH", allocation=row["allocation"].wire,
                                    lifetime_status=row["lifetime_status"])
            counts["allocation_epochs"] += 1
            if row["lifetime_status"] == "OPEN_AT_CAPTURE_END":
                counts["open_at_capture_end"] += 1
            if not supported_device:
                importer.gap("native_memory_device_unsupported", reference,
                    "provider device selector retained generically; CPU/CUDA physical identity is not established")
        elif row is not None:
            importer.edge(EvidenceRelation.USES_STORAGE, instance_id, row["allocation"],
                importer.claim(row["birth_reference"], reference, assumptions=(
                    "same capture/process/device/address with unique provider Ev Idx on one host thread",
                    "size-matched free receipt; not physical CUDA free, readiness or Tensor identity")),
                kind=EvidenceNodeKind.ALLOCATION)
            entry["record"].update(disposition="MATCHED_PROFILER_FREE", allocation=row["allocation"].wire)
            counts["matched_frees"] += 1
        else:
            entry["record"]["disposition"] = ("UNMATCHED_PREHISTORY_FREE"
                if entry["record"]["disposition"] == "UNMATCHED_PREHISTORY_FREE" else "UNRESOLVED_FREE")
            counts["unmatched_frees"] += 1
            importer.gap("native_memory_free_unmatched", reference,
                "free receipt has no admissible unique observed birth; no allocation association invented")
    allocation_rows.sort(key=lambda row: row["birth_index"])
    report = {
        "profile": _PROFILE, "counts": dict(sorted(counts.items())), "records": records,
        "ordering_basis": "unique integer provider Ev Idx within one host thread per allocator slot",
        "slot_conflict_policy": "reject every free association in a conflicting slot",
        "source_artifact": dict(importer.artifacts["kineto"]),
        "allocation_lifetimes_complete": False, "physical_cuda_allocation_established": False,
        "logical_content_established": False, "tensor_storage_association_established": False,
        "open_epochs_are_leaks": False,
    }
    return NativeMemoryRecords(tuple(allocation_rows), report, chrome)


__all__ = ["NativeMemoryRecords", "append_memory_events"]
