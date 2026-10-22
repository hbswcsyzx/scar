"""Bind native allocator claims to exact caller-supplied profile/raw snapshots.

This adapter opens no URI and creates no program occurrence.  A matched claim
remains scoped to profiler allocator receipts, not physical memory or readiness.
"""
from __future__ import annotations

import json
import math
from pathlib import PurePosixPath

from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.record_codec import decode
from .common import EvidencePoint
from .native_memory_protocol import NativeMemoryResolver
from .resources import AllocationTarget
from .snapshot import SnapshotError
from .validity import TargetLifetimeEvent


PROFILE_SCHEMA = "scar.native-memory-profile"
_CONTRACT_FIELDS = {"kineto", "scope", "pid", "provider_revision",
                    "adjust_timestamps", "capture_manifest"}


class _Unavailable(ValueError):
    pass


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key: " + key)
        result[key] = value
    return result


def _constant(value):
    raise ValueError("nonfinite JSON constant: " + value)


def _float(value):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("nonfinite JSON number")
    return value


def _document(ctx, artifact):
    payload = ctx.snapshots.payload(artifact)
    if payload is None:
        raise _Unavailable("exact " + artifact.schema + " payload was not supplied")
    document = json.loads(payload, object_pairs_hook=_pairs, parse_constant=_constant,
                          parse_float=_float)
    if type(document) is not dict:
        raise ValueError(artifact.schema + " must be a JSON object")
    return document


def _shape(document, fields, name):
    if type(document) is not dict or set(document) != fields:
        raise ValueError(name + " has missing or unknown fields")


def _capture(ctx, artifact, contract, kineto):
    if artifact.schema != "scar.execution-evidence-collection":
        raise ValueError("capture artifact has unsupported schema")
    document = _document(ctx, artifact)
    if (document.get("schema") != artifact.schema
            or type(document.get("schema_version")) is not int or document["schema_version"] != 1
            or type(document.get("pid")) is not int or document["pid"] != contract["pid"]):
        raise ValueError("capture schema/version/process does not match native contract")
    configuration, provider = document.get("configuration"), document.get("provider")
    if (type(configuration) is not dict or configuration.get("profile_memory") is not True
            or type(provider) is not dict
            or provider.get("torch_git_version") != contract["provider_revision"]):
        raise ValueError("capture memory setting/provider revision does not match native contract")
    experimental = configuration.get("experimental_config")
    observed = experimental.get("adjust_timestamps") if type(experimental) is dict else None
    observed = observed if type(observed) is bool else None
    declared = contract["adjust_timestamps"]
    if type(declared) is not type(observed) or declared != observed:
        raise ValueError("declared timestamp adjustment does not match capture configuration")
    artifacts = document.get("artifacts")
    captured = artifacts.get("kineto") if type(artifacts) is dict else None
    if (type(captured) is not dict or type(captured.get("path")) is not str
            or not captured["path"] or type(captured.get("size_bytes")) is not int
            or captured["size_bytes"] != kineto.size_bytes):
        raise ValueError("capture Kineto artifact has no matching decompressed size/path")
    current = PurePosixPath(kineto.uri).name
    current = current[:-3] if current.endswith(".gz") else current
    if PurePosixPath(captured["path"]).name != current:
        raise ValueError("capture Kineto basename does not match retained raw artifact")


def _binding(ctx, reference):
    document = _document(ctx, reference.artifact)
    _shape(document, {"schema", "schema_version", "contract"}, "native memory profile")
    if (document["schema"] != PROFILE_SCHEMA or type(document["schema_version"]) is not int
            or document["schema_version"] != 1):
        raise ValueError("unsupported native memory profile schema/version")
    contract = document["contract"]
    _shape(contract, _CONTRACT_FIELDS, "native memory contract")
    if (type(contract["scope"]) is not str or not contract["scope"]
            or type(contract["pid"]) is not int or contract["pid"] <= 0
            or type(contract["provider_revision"]) is not str or not contract["provider_revision"]
            or (contract["adjust_timestamps"] is not None
                and type(contract["adjust_timestamps"]) is not bool)):
        raise ValueError("native memory contract has invalid scope/process/provider/ordering fields")
    kineto = decode(ProviderArtifact, contract["kineto"])
    if kineto.schema != "pytorch.kineto.chrome-trace.v1":
        raise ValueError("native memory contract requires the exact Kineto artifact schema")
    capture = contract["capture_manifest"]
    if capture is not None:
        _capture(ctx, decode(ProviderArtifact, capture), contract, kineto)
    elif contract["adjust_timestamps"] is not None:
        raise ValueError("timestamp adjustment cannot be declared without a capture manifest")
    resolver = NativeMemoryResolver(_document(ctx, kineto), kineto, contract["scope"], contract["pid"],
        provider_revision=contract["provider_revision"], adjust_timestamps=contract["adjust_timestamps"],
        protocol_reference=reference)
    return resolver, contract


def _unmatched(reason, status="UNRESOLVED"):
    return {"status": status, "matched": False, "profile_supported": False,
            "birth_verified": False, "free_verified": False, "ordering_qualified": False,
            "reasons": [reason], "conditions": [], "physical_allocation_established": False,
            "resource_ready": False, "transformation_authorized": False}


def resolve_native_memory_claim(ctx, row, path):
    """Resolve only the fixed native profile; generic protocols return None.

    ctx supplies snapshots, external_values(), runs/processes, and issue()/gap().
    Missing exact snapshots remain gaps; malformed declarations are issues.
    Cached bindings live only inside this context and never open artifact URIs.
    """
    reference = getattr(row, "protocol", None)
    if type(reference) is not ProviderFactReference or reference.artifact.schema != PROFILE_SCHEMA:
        return None
    try:
        reference.__post_init__()
        if reference.locator != "#/contract":
            raise ValueError("native memory profile must select #/contract")
        if (type(row) is not TargetLifetimeEvent or type(row.target) is not AllocationTarget
                or type(row.at) is not EvidencePoint or row.at.process is None):
            raise ValueError("native memory claim needs an allocation target and process EvidencePoint")
        key = (reference.artifact.sha256, reference.artifact.schema,
               reference.artifact.size_bytes, reference.locator)
        cache = getattr(ctx, "_native_memory_binding_cache", None)
        if cache is None:
            cache = ctx._native_memory_binding_cache = {}
        if key not in cache:
            try:
                cache[key] = (_binding(ctx, reference), None, None)
            except _Unavailable as error:
                cache[key] = (None, "gap", str(error))
            except (SnapshotError, ValueError, TypeError, UnicodeError, RecursionError, OverflowError) as error:
                cache[key] = (None, "issue", str(error))
        binding, diagnostic, message = cache[key]
        if diagnostic:
            getattr(ctx, diagnostic)("native_memory_binding", path, message)
            return _unmatched(message, "MISMATCH" if diagnostic == "issue" else "UNRESOLVED")
        resolver, contract = binding
        process = ctx.processes.get(row.at.process)
        if (process is None or type(process.pid) is not int or process.pid != contract["pid"]
                or process.run != row.at.run or row.at.run not in ctx.runs):
            raise ValueError("native memory EvidencePoint process/run does not match contract pid")
        values = ctx.external_values(row.target.artifact, path)
        if values is None:
            return _unmatched("exact final allocation ValueGraph was not supplied or is invalid")
        result = resolver.resolve(row, values)
        if result["status"] == "MISMATCH":
            ctx.issue("native_memory_claim", path, "; ".join(result["reasons"]))
        elif not result["matched"]:
            ctx.gap("native_memory_claim", path, "; ".join(result["reasons"]))
        if result["matched"]:
            result["conditions"] = [item for item in result["conditions"]
                if item not in ("caller_bound_exact_raw_and_final_value_graph",
                                "caller_bound_evidence_process_to_profile_pid")]
            if contract["capture_manifest"] is not None:
                result["conditions"].append("capture_association_uses_basename_and_decompressed_size")
        return result
    except (SnapshotError, ValueError, TypeError, UnicodeError, RecursionError, OverflowError) as error:
        ctx.issue("native_memory_binding", path, str(error))
        return _unmatched(str(error), "MISMATCH")


__all__ = ["resolve_native_memory_claim"]
