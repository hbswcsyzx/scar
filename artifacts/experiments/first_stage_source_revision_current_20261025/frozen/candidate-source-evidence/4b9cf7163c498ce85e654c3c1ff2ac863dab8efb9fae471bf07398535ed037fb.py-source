"""Closed byte-prefix endpoint profile interpretation.

The profile is a small declaration carried by an exact ProviderFactReference.
It selects one fixed interpretation; it never proves that source/runtime facts
match the declaration.  No artifact URI is opened here.
"""
from __future__ import annotations

import json

from scar.ir.program.providers import ProviderFactReference
from scar.ir.program.model import DataValue
from scar.ir.v2.values import ValueGraph
from .content import ProtocolSelector, StorageContent
from .coverage import RegionRef
from .snapshot import SnapshotError


PROFILE_SCHEMA = "scar.endpoint-byte-profile"
PROFILE_LOCATOR = "#"
PROFILE_NAME = "BYTE_PREFIX_READ_AFTER_COMPLETED_WRITE"
PROFILE_MAX_BYTES = 4096
PROFILE_OPERATIONS = frozenset(("READ", "WRITE_REQUEST", "WRITE_ACTUAL"))

_PROFILE_KEYS = frozenset(("schema", "schema_version", "profile", "operation",
                           "offset_bytes", "length_bytes"))


def _artifact_key(artifact):
    return artifact.sha256, artifact.schema, artifact.size_bytes


def same_fact_reference(left, right):
    """Compare the complete canonical identity of two fact references."""
    return (type(left) is ProviderFactReference and type(right) is ProviderFactReference
            and _artifact_key(left.artifact) == _artifact_key(right.artifact)
            and left.locator == right.locator)


def same_materialization(left, right):
    """Compare exact scoped MatRefs without opening or interpreting a URI."""
    from .work import MaterializationRef
    return (type(left) is MaterializationRef and type(right) is MaterializationRef
            and _artifact_key(left.artifact) == _artifact_key(right.artifact)
            and left.materialization == right.materialization)


def _object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("non-finite JSON number is not permitted")


def _issue(ctx, code, path, message):
    ctx.issue(code, path, message)


def _gap(ctx, code, path, message):
    ctx.gap(code, path, message)


def resolve_endpoint_profile(ctx, reference, path, *, budget=None):
    """Resolve an exact supported profile from already supplied raw bytes.

    ``reference`` is a ProtocolSelector or ProviderFactReference.  The cache
    is local to this validation/query context and therefore cannot conceal a
    caller-catalog mutation in a later public query.
    """
    if type(reference) is ProtocolSelector:
        reference = reference.reference
    if type(reference) is not ProviderFactReference:
        raise TypeError("endpoint profile requires exact ProtocolSelector or ProviderFactReference")
    try:
        reference.__post_init__()
    except (TypeError, ValueError) as error:
        _issue(ctx, "endpoint_profile_reference", path, str(error))
        return None

    if budget is not None and not budget.spend("endpoint_profiles", path=path):
        return None

    artifact = reference.artifact
    if artifact.schema != PROFILE_SCHEMA or reference.locator != PROFILE_LOCATOR:
        _gap(ctx, "endpoint_profile_unsupported", path,
             "only the exact root byte-prefix endpoint profile artifact is interpreted")
        return None

    # The profile itself is capped at 4 KiB. Reject an oversized declared
    # artifact before hashing/copying its payload, in addition to checking the
    # actual supplied bytes below.
    if artifact.size_bytes > PROFILE_MAX_BYTES:
        _issue(ctx, "endpoint_profile_size", path,
               "profile artifact declares more than the fixed 4096-byte limit")
        return None

    cache = getattr(ctx, "_endpoint_profile_cache", None)
    if cache is None:
        cache = {}
        ctx._endpoint_profile_cache = cache
    key = (id(ctx.snapshots), _artifact_key(artifact), reference.locator)
    if key not in cache:
        try:
            payload = ctx.snapshots.payload(artifact)
        except SnapshotError as error:
            # SnapshotError and defensive catalog failures are declared as
            # protocol issues; never invoke a loader or fall back to a URI.
            cache[key] = (None, "issue", "endpoint_profile_artifact",
                          "profile artifact failed exact snapshot validation: " + str(error))
        else:
            if payload is None:
                cache[key] = (None, "gap", "endpoint_profile_missing",
                              "exact endpoint profile bytes were not supplied")
            elif len(payload) > PROFILE_MAX_BYTES:
                cache[key] = (None, "issue", "endpoint_profile_size",
                              "endpoint profile exceeds the fixed 4096-byte limit")
            else:
                try:
                    text = payload.decode("utf-8", errors="strict")
                    document = json.loads(text, object_pairs_hook=_object_pairs,
                                          parse_constant=_reject_constant)
                    if type(document) is not dict:
                        raise ValueError("profile document must be an exact JSON object")
                    if frozenset(document) != _PROFILE_KEYS:
                        raise ValueError("profile document has missing or extra fields")
                    if type(document["schema"]) is not str or document["schema"] != PROFILE_SCHEMA:
                        raise ValueError("profile schema does not match the exact endpoint profile schema")
                    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
                        raise ValueError("unsupported endpoint profile schema version")
                    if type(document["profile"]) is not str or document["profile"] != PROFILE_NAME:
                        raise ValueError("unsupported endpoint byte profile")
                    if type(document["operation"]) is not str or document["operation"] not in PROFILE_OPERATIONS:
                        raise ValueError("unsupported endpoint byte profile operation")
                    if type(document["offset_bytes"]) is not int or document["offset_bytes"] < 0:
                        raise ValueError("offset_bytes must be an exact nonnegative integer")
                    if type(document["length_bytes"]) is not int or document["length_bytes"] < 0:
                        raise ValueError("length_bytes must be an exact nonnegative integer")
                    elif document["operation"] in ("READ", "WRITE_REQUEST") and document["length_bytes"] == 0:
                        raise ValueError("READ and WRITE_REQUEST ranges must be nonempty")
                    elif document["offset_bytes"] != 0:
                        cache[key] = (None, "gap", "endpoint_profile_offset_unsupported",
                                      "only zero-offset endpoint byte ranges are interpreted")
                    else:
                        cache[key] = ({**document, "reference": reference}, None, None, None)
                except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError,
                        RecursionError, OverflowError) as error:
                    cache[key] = (None, "issue", "endpoint_profile_invalid", str(error))
    profile, diagnostic, code, message = cache[key]
    if diagnostic == "issue":
        _issue(ctx, code, path, message)
    elif diagnostic == "gap":
        _gap(ctx, code, path, message)
    return profile


def linear_byte_region(ctx, artifact, region_id, path, *, budget=None):
    """Return a checked linear uint8 region extent, or None with a gap/issue."""
    if budget is not None and not budget.spend("endpoint_geometry", path=path):
        return None
    graph = ctx.external_values(artifact, path)
    if graph is None:
        return None
    region = graph.regions.get(region_id)
    if region is None:
        _issue(ctx, "endpoint_region", path, "byte selector region is absent from its exact ValueGraph")
        return None
    if (region.dtype != "uint8" or region.layout != "strided" or len(region.shape) != 1
            or region.strides != (1,)):
        _gap(ctx, "endpoint_byte_geometry_unsupported", path,
             "the fixed endpoint profile only interprets rank-one contiguous uint8 regions")
        return None
    count = region.shape[0]
    if type(count) is not int or count < 0:
        _issue(ctx, "endpoint_byte_geometry", path, "byte-region extent is not a canonical nonnegative integer")
        return None
    return {"artifact": artifact, "graph": graph, "region": region,
            "allocation": region.allocation, "offset_bytes": region.offset,
            "length_bytes": count}


def endpoint_extent(ctx, target, profile, path, *, expected_operation=None,
                    materialization=None):
    """Build an internal endpoint interval descriptor from a parsed profile."""
    from .resources import InstanceTarget
    if profile is None:
        return None
    if type(target) is not InstanceTarget:
        _gap(ctx, "endpoint_target_unsupported", path,
             "the fixed byte endpoint profile requires an exact ResourceInstance target")
        return None
    if expected_operation is not None and profile["operation"] != expected_operation:
        _issue(ctx, "endpoint_profile_role", path,
               "endpoint profile operation does not match the original read/write role")
        return None
    return {"kind": "endpoint-byte-range", "target": target,
            "materialization": materialization,
            "profile": profile["profile"], "operation": profile["operation"],
            "offset_bytes": profile["offset_bytes"], "length_bytes": profile["length_bytes"],
            "reference": profile["reference"]}


def source_byte_input(ctx, write_row, resolved_write, path, *, budget=None):
    """Derive a unique original byte input for an endpoint writer.

    This only joins original Use/ContentRead/denotation/materialization rows.
    It does not establish that native code consumed or wrote the bytes.
    """
    from .content import DataIdentity, EndpointContent, HostConsumer, ResourceConsumer
    from .coordinates import UseRef
    from .production import WorkWrite, HostWrite
    from .work import WithinOperation

    if budget is not None and not budget.spend("endpoint_source_reads", path=path):
        return None
    writer = resolved_write.get("writer")
    ticket = write_row.writer.ticket if type(write_row.writer) is WorkWrite else None
    if type(write_row.writer) is HostWrite:
        operation = write_row.writer.operation
    elif (type(write_row.writer) is WorkWrite and writer is not None
          and type(writer.origin) is WithinOperation):
        operation = writer.origin.operation
    else:
        _gap(ctx, "endpoint_write_source_unresolved", path,
             "writer has no exact within-operation source input scope")
        return None
    if type(write_row.placement) is not EndpointContent:
        _gap(ctx, "endpoint_write_source_unresolved", path,
             "writer placement is not an interpreted endpoint content association")
        return None

    candidates = []
    for read_id, resolved in ctx.resolved_content_reads.items():
        if budget is not None and not budget.spend("endpoint_source_reads", path=path):
            return None
        row = resolved["read"]
        consumer = row.consumer
        if type(consumer) is HostConsumer:
            subject = consumer.subject
        elif type(consumer) is ResourceConsumer:
            if ticket is None or consumer.read.ticket != ticket:
                continue
            subject = consumer.subject
        else:
            continue
        if type(subject) is not UseRef or subject.operation != operation:
            continue
        if type(row.placement) is not StorageContent:
            continue
        if resolved.get("actual") is None:
            continue
        candidates.append((read_id, resolved))

    if not candidates:
        _gap(ctx, "endpoint_write_source_unresolved", path,
             "no original ContentRead for a writer-owned Data Use was found")
        return None
    if len(candidates) != 1:
        _gap(ctx, "endpoint_write_source_ambiguous", path,
             "multiple original writer-owned ContentReads remain; no source Use is selected")
        return None

    read_id, resolved = candidates[0]
    read = resolved["read"]
    actual = resolved["actual"]
    definition = ctx.core_values.get(actual.value)
    if type(definition) is not DataValue:
        _gap(ctx, "endpoint_write_source_nondata", path,
             "source ContentRead does not denote a canonical DataValue")
        return None
    denotation = resolved.get("denotation")
    if denotation is None or type(denotation["denotation"].identity) is not DataIdentity:
        _gap(ctx, "endpoint_write_source_version_unresolved", path,
             "source DataValue has no exact scoped logical version denotation")
        return None
    placement = resolved.get("placement")
    if placement is None or placement[0] is None or type(read.placement) is not StorageContent:
        _gap(ctx, "endpoint_write_source_materialization_unresolved", path,
             "source read has no resolved original storage materialization")
        return None
    source_mat = read.placement.materialization
    destination_mat = write_row.placement.materialization
    if _artifact_key(source_mat.artifact) != _artifact_key(destination_mat.artifact):
        _gap(ctx, "endpoint_write_source_materialization_unresolved", path,
             "source and endpoint materializations belong to different ValueGraph artifacts")
        return None
    materialization, selector = placement
    identity = denotation["denotation"].identity
    destination_graph = ctx.external_values(destination_mat.artifact, path)
    destination = (None if destination_graph is None else
                   destination_graph.materializations.get(destination_mat.materialization))
    if destination is None:
        _issue(ctx, "endpoint_write_destination_materialization", path,
               "endpoint materialization is absent from its exact ValueGraph")
        return None
    if (_artifact_key(identity.version.artifact) != _artifact_key(source_mat.artifact)
            or identity.version.version != materialization.value_version
            or destination.value_version != materialization.value_version):
        _issue(ctx, "endpoint_write_source_version", path,
               "source denotation, source materialization and endpoint materialization do not share one scoped logical version")
        return None
    source_region = selector if type(selector) is RegionRef else (
        RegionRef(source_mat.artifact, materialization.region)
        if materialization.region is not None else None)
    if source_region is None:
        _gap(ctx, "endpoint_write_source_geometry_unresolved", path,
             "source materialization has no storage region for requested byte geometry")
        return None
    extent = linear_byte_region(ctx, source_region.artifact, source_region.region, path, budget=budget)
    if extent is None:
        return None
    return {"read_id": read_id, "read": read, "resolved_read": resolved,
            "subject": read.consumer.subject, "value": actual, "denotation": denotation,
            "materialization": materialization, "materialization_ref": source_mat,
            "selector": source_region, "extent": extent,
            "conditions": ("original Use/read/version mapping is conditional; native byte consumption remains unverified",)}


__all__ = [
    "PROFILE_LOCATOR", "PROFILE_MAX_BYTES", "PROFILE_NAME", "PROFILE_OPERATIONS",
    "PROFILE_SCHEMA", "endpoint_extent", "linear_byte_region", "resolve_endpoint_profile",
    "same_fact_reference", "same_materialization", "source_byte_input",
]
