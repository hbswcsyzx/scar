"""Detect repeated physical materialization and host materialization patterns."""
from __future__ import annotations

from collections import defaultdict

from scar.ir import ExecutionGraph, Opportunity, ProofStatus, proof


def _residency_legality_proofs(support: list[int]):
    return [
        proof(
            "no_logical_invalidation", "legality",
            "the logical version is not invalidated while the resident copy is reused",
            ProofStatus.UNKNOWN, evidence="UNKNOWN",
            reason="the observed transfers do not prove all foreign and alias writes",
            supporting_events=support,
        ),
        proof(
            "residency_lifetime_safe", "legality",
            "destination storage lifetime, stream ordering, consumers and escapes permit retention",
            ProofStatus.UNKNOWN, evidence="UNKNOWN",
            reason="lifetime, ordering and escape evidence is incomplete",
            supporting_events=support,
        ),
    ]


_DTYPE_BYTES = {
    "float32": 4, "float16": 2, "bfloat16": 2, "float64": 8,
    "int64": 8, "int32": 4, "int16": 2, "int8": 1,
    "uint8": 1, "bool": 1,
}

# Runtime serializers may report a dtype as ``torch.float32``, ``float32``
# or a NumPy spelling.  These are representations of the same contract, so
# normalise the spelling before estimating residency cost.
_DTYPE_ALIASES = {
    "float": "float32", "float32": "float32", "torch.float": "float32",
    "torch.float32": "float32", "float16": "float16", "torch.float16": "float16",
    "bfloat16": "bfloat16", "torch.bfloat16": "bfloat16",
    "float64": "float64", "torch.float64": "float64",
    "int64": "int64", "torch.int64": "int64", "long": "int64",
    "int32": "int32", "torch.int32": "int32", "int16": "int16",
    "torch.int16": "int16", "int8": "int8", "torch.int8": "int8",
    "uint8": "uint8", "torch.uint8": "uint8", "bool": "bool", "torch.bool": "bool",
}


def _bytes(value: dict) -> int | None:
    try:
        if "shape" not in value:
            return None
        size = 1
        for dimension in value.get("shape", []):
            size *= int(dimension)
        dtype = str(value.get("dtype")).lower()
        dtype = _DTYPE_ALIASES.get(dtype, dtype)
        itemsize = _DTYPE_BYTES.get(dtype)
        return size * itemsize if itemsize is not None else None
    except (TypeError, ValueError):
        return None


def materialization_candidates(graph: ExecutionGraph) -> list[Opportunity]:
    transfers = defaultdict(list)
    for idx, event in enumerate(graph.events):
        if event.kind != "transfer" or not event.inputs or not event.outputs:
            continue
        inp, out = event.inputs[0], event.outputs[0]
        if event.metadata.get("physical") is True:
            transfers[(inp.get("logical_version"), out.get("device"))].append((idx, event))
    result = []
    for (version, device), values in transfers.items():
        if version and len(values) > 1:
            sizes = [_bytes(event.outputs[0]) for _, event in values]
            support = [i for i, _ in values]
            result.append(Opportunity(
                kind="ResidencyCandidate", code_id=None, evidence="Observed",
                applicability="same_logical_version_repeated_transfer",
                guard="no intervening invalidation and destination storage remains live",
                reason=f"logical version {version} materialized {len(values)} times on {device}",
                supporting_events=support, decision="rejected",
                backend="persistent_residency",
                rejection_reason="residency lifetime and invalidation guard is incomplete",
                estimated_memory_bytes=max(sizes) if all(size is not None for size in sizes) else None,
                proof_obligations=[
                    proof(
                        "repeated_physical_materialization", "applicability",
                        "one logical version is physically materialized on the same destination more than once",
                        ProofStatus.PROVEN, evidence="Observed",
                        reason=f"observed {len(values)} physical transfer events",
                        supporting_events=support,
                    ),
                ] + _residency_legality_proofs(support),
            ))

    # Physical Kineto activities are the authoritative copy observations. A
    # logical version is eligible for this family only after the trace
    # finalizer attached a unique (possibly Inferred) host-transfer mapping.
    # Ambiguous and UNKNOWN activities are intentionally excluded.
    physical = defaultdict(list)
    for idx, event in enumerate(graph.events):
        if event.kind != "cuda_memcpy":
            continue
        logical = event.metadata.get("logical_version")
        confidence = event.metadata.get("mapping_confidence")
        if not logical or confidence not in {"Observed", "Inferred"}:
            continue
        destination = event.resource.get("device", "unknown")
        direction = event.resource.get("direction", "unknown")
        physical[(logical, direction, destination)].append((idx, event))
    for (logical, direction, destination), values in physical.items():
        if len(values) < 2:
            continue
        sizes = [event.resource.get("bytes") for _, event in values]
        support = [idx for idx, _ in values]
        mapping_status = (ProofStatus.PROVEN
                          if all(event.metadata.get("mapping_confidence") == "Observed"
                                 for _, event in values) else ProofStatus.UNKNOWN)
        result.append(Opportunity(
            kind="ResidencyCandidate", code_id=None,
            evidence="Inferred" if any(event.metadata.get("mapping_confidence") == "Inferred"
                                       for _, event in values) else "Observed",
            applicability="same_logical_version_repeated_physical_materialization",
            guard=("logical-version invalidation, storage lifetime, stream ordering, "
                   "consumer/escape behavior and residency memory budget must be proven"),
            reason=(f"physical {direction} materialization observed {len(values)} times for "
                    f"logical version {logical} on resource {destination}"),
            supporting_events=support,
            expected_savings_ns=sum(event.duration_ns or 0 for _, event in values[1:]),
            estimated_memory_bytes=max(sizes) if all(isinstance(size, int) for size in sizes) else None,
            decision="rejected", backend="persistent_residency",
            rejection_reason="residency lifetime and invalidation guard is incomplete",
            proof_obligations=[
                proof(
                    "repeated_physical_materialization", "applicability",
                    "the same logical version has repeated physical copy activities",
                    ProofStatus.PROVEN, evidence="Observed",
                    reason=f"Kineto observed {len(values)} {direction} copies",
                    supporting_events=support,
                ),
                proof(
                    "physical_to_logical_mapping", "applicability",
                    "each physical copy is uniquely correlated to the stated logical version",
                    mapping_status,
                    evidence="Observed" if mapping_status == ProofStatus.PROVEN else "Inferred",
                    reason=("runtime correlation is observed" if mapping_status == ProofStatus.PROVEN
                            else "signature join is inferred and needs a runtime correlation ID"),
                    supporting_events=support,
                ),
            ] + _residency_legality_proofs(support),
        ))
    return result
