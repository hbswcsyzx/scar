"""Opt-in tensor observations for the v2 provenance registry.

Regular observations inspect descriptors only. Weak lifetime witnesses prevent
allocator tokens from becoming logical identities. This adapter does not hook
all writes: its default mutation coverage is UNKNOWN, even for eval/inference.
Explicit checkpoints can observe a change; they do not prove future stability.
"""
from __future__ import annotations

from dataclasses import dataclass
import weakref

from scar.ir.provenance import ExactContract, ProvenanceRegistry, ValueHandle
from scar.ir.v2 import Completeness, EvidenceClaim, EvidenceKind, ObjectID, ProofStatus, StorageAllocationID
from scar.trace.checkpoint import CheckpointStore, ComparisonResult, ComparisonStatus


@dataclass(frozen=True)
class TensorVerification:
    handle: ValueHandle
    comparison: ComparisonResult
    version_advanced: bool


@dataclass
class _ObservedObject:
    reference: weakref.ReferenceType
    identity: ObjectID
    signature: tuple
    handle: ValueHandle


@dataclass
class _AllocationWitness:
    allocation: StorageAllocationID
    owners: list[weakref.ReferenceType]


class TensorObserver:
    """Descriptor capture and explicit exact checkpoints, with no backend.

    Caller must exclude concurrent writes during capture/verification. Shared
    NumPy/ctypes aliases remain open unless a write or exact comparison is
    observed. Sparse, quantized, meta, conjugate and negative-bit tensor
    representations are explicitly unsupported by this first adapter.
    """

    def __init__(self, registry=None, *, namespace=None,
                 checkpoint_bytes=8 * 1024 * 1024, allow_cuda=False):
        self.registry = registry or ProvenanceRegistry(namespace=namespace)
        self.checkpoints = CheckpointStore(max_bytes=checkpoint_bytes,
                                           allow_cuda=allow_cuda)
        self.namespace = namespace or self.registry.namespace
        self._objects = {}
        self._storages = {}
        self._counter = 0
        self._checkpoints = {}

    def _evidence(self, label):
        return EvidenceClaim(EvidenceKind.OBSERVED,
                             references=(str(label),), scope=self.registry.scope)

    @staticmethod
    def _storage_key(tensor):
        return str(tensor.device), tensor.untyped_storage()._cdata

    def _descriptor(self, tensor):
        import torch

        if (type(tensor) not in (torch.Tensor, torch.nn.Parameter) or tensor.layout is not torch.strided
                or tensor.is_quantized or tensor.device.type == "meta"
                or tensor.is_conj() or tensor.is_neg()):
            raise ValueError("unsupported tensor representation for v2 observation")
        key = self._storage_key(tensor)
        witness = self._storages.get(key)
        if witness is not None:
            owners = []
            for reference in witness.owners:
                owner = reference()
                if owner is not None and self._storage_key(owner) == key:
                    owners.append(reference)
            witness.owners = owners
        if witness is None or not witness.owners:
            self._counter += 1
            allocation = self.registry.allocation(
                device=key[0], nbytes=tensor.untyped_storage().nbytes(),
                token=str(key[1]), lifetime=f"{self.namespace}:storage:{self._counter}")
            witness = _AllocationWitness(allocation, [])
            self._storages[key] = witness
        if not any(reference() is tensor for reference in witness.owners):
            witness.owners.append(weakref.ref(tensor))
        signature = (witness.allocation, tensor.storage_offset(), tuple(tensor.shape),
                     tuple(tensor.stride()), str(tensor.dtype))
        return signature

    def observe(self, tensor, *, evidence="tensor capture", fresh=False):
        signature = self._descriptor(tensor)
        previous = self._objects.get(id(tensor))
        if previous is not None and previous.reference() is tensor:
            identity = previous.identity
            if not fresh and previous.signature == signature:
                return previous.handle
            # Descriptor changes are not evidence of a write to old storage.
            self.registry.escape(previous.handle, "descriptor changed or fresh capture",
                                 self._evidence(evidence))
        else:
            self._counter += 1
            identity = ObjectID(f"{self.namespace}:object:{self._counter}")
        region = self.registry.region(signature[0], offset=signature[1],
            shape=signature[2], strides=signature[3], dtype=signature[4])
        handle = self.registry.origin(identity, region, self._evidence(evidence),
                                      coverage=Completeness.UNKNOWN)
        self._objects[id(tensor)] = _ObservedObject(weakref.ref(tensor), identity,
                                                   signature, handle)
        return handle

    def view(self, source, result, *, evidence="observed shared tensor storage"):
        parent = self.observe(source, evidence=evidence)
        child = self.observe(result, evidence=evidence)
        source_record, result_record = self._objects[id(source)], self._objects[id(result)]
        if source_record.signature[0] != result_record.signature[0]:
            raise ValueError("a view requires the same live allocation witness")
        region = self.registry.graph.materializations[child.materialization].region
        handle = self.registry.view(parent, child.object_id, region, self._evidence(evidence))
        result_record.handle = handle
        return handle

    def enroll(self, tensor):
        # Earlier descriptor-only captures could hide foreign writes. Enroll
        # a new capture identity; no retroactive equality to those captures.
        handle = self.observe(tensor, fresh=True)
        checkpoint = self.checkpoints.enroll(tensor)
        self._checkpoints[checkpoint] = (weakref.ref(tensor), handle)
        return checkpoint

    def verify(self, checkpoint, tensor):
        original_ref, original = self._checkpoints[checkpoint]
        if original_ref() is not tensor:
            raise ValueError("a mutation checkpoint belongs to its original live object")
        current = self.observe(tensor)
        comparison = self.checkpoints.compare(checkpoint, tensor)
        advanced = False
        if comparison.status is ComparisonStatus.DIFFERENT and current == original:
            region = self.registry.graph.materializations[current.materialization].region
            current = self.registry.mutate(current, region,
                self._evidence("bitwise checkpoint mismatch observed"))
            self._objects[id(tensor)].handle = current
            advanced = True
        return TensorVerification(current, comparison, advanced)

    def release(self, checkpoint):
        self.checkpoints.release(checkpoint)
        del self._checkpoints[checkpoint]

    def _copy(self, tensor, operation, *, label, mutable):
        """Observe a caller-selected copy with bounded, explicit verification.

        The copy itself is ordinary target work. This opt-in collector checks
        its result and records provenance; it never substitutes cached output.
        """
        checkpoint = self.enroll(tensor)
        source = self.observe(tensor)
        try:
            result = operation(tensor)
            if result is tensor:
                return result, source  # Real no-op: no new materialization.
            comparison = self.checkpoints.compare(checkpoint, result)
            output = self.observe(result, evidence=label)
            evidence = self._evidence(label + ": " + comparison.reason)
            contract = None
            if comparison.status is ComparisonStatus.EXACT:
                contract = ExactContract(
                    reference="observed-copy:bitwise-full", status=ProofStatus.PROVEN,
                    scope=self.registry.scope, evidence=evidence,
                    checked_versions=(source.version,), checked_at=self.registry.current_event)
            region = self.registry.graph.materializations[output.materialization].region
            if mutable:
                handle = self.registry.copy(source, output.object_id, region, evidence,
                                            contract=contract, mutable=True)
            else:
                handle = self.registry.materialize(source, output.object_id, region, evidence,
                                                   contract=contract)
            self._objects[id(result)].handle = handle
            return result, handle
        finally:
            self.release(checkpoint)

    def deepcopy(self, tensor):
        import copy
        return self._copy(tensor, copy.deepcopy, label="observed deepcopy", mutable=True)

    def copy_to(self, tensor, device):
        return self._copy(tensor, lambda value: value.to(device),
                          label="observed Tensor.to(device)", mutable=False)


__all__ = ["TensorObserver", "TensorVerification"]
