"""Small exact-byte fixtures for the closed endpoint profile parser."""
from __future__ import annotations

from hashlib import sha256
import json

from scar.ir.execution.endpoint_protocol import PROFILE_NAME, PROFILE_SCHEMA
from scar.ir.execution.snapshot import ExternalSnapshots
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference


def profile_bytes(operation="READ", *, offset=0, length=8, extra=None):
    document = {
        "schema": PROFILE_SCHEMA,
        "schema_version": 1,
        "profile": PROFILE_NAME,
        "operation": operation,
        "offset_bytes": offset,
        "length_bytes": length,
    }
    if extra:
        document.update(extra)
    return json.dumps(document, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def profile_reference(payload, *, declared_size=None, name="profile"):
    if type(payload) is not bytes:
        raise TypeError("profile payload must be exact bytes")
    size = len(payload) if declared_size is None else declared_size
    artifact = ProviderArtifact(
        f"memory:endpoint-profile:{name}", sha256(payload).hexdigest(), size,
        PROFILE_SCHEMA,
    )
    return ProviderFactReference(artifact, "#")


class ProfileParserContext:
    """Only the parser dependencies; this fixture does not emulate validation."""

    def __init__(self, reference, payload):
        self.snapshots = ExternalSnapshots(artifact_bytes={reference.artifact.sha256: payload})
        self.issues = []
        self.gaps = []

    def issue(self, code, path, message):
        self.issues.append((code, path, message))

    def gap(self, code, path, message):
        self.gaps.append((code, path, message))


def parser_context(payload, *, declared_size=None, name="profile"):
    reference = profile_reference(payload, declared_size=declared_size, name=name)
    return ProfileParserContext(reference, payload), reference


__all__ = ["ProfileParserContext", "parser_context", "profile_bytes", "profile_reference"]
