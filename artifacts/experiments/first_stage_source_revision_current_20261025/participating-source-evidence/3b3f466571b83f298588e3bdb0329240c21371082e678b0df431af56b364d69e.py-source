"""Qualified references to original source definitions, never new producers.

Inventory file indices are optional views owned by an analysis client. They
are deliberately absent from these identities. Stored bytes, decoded JSON,
source versions and the producer's original namespace remain distinct.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re

from scar.ir.program.inventory import SourceContextDigest
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.semantics_v2 import SourceSnapshot
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import OperationDefinitionID


def _sha(value, name):
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(name + " must be a lowercase SHA256")


def _path(value, name):
    if (type(value) is not str or not value or "\0" in value
            or not Path(value).is_absolute() or os.path.normpath(value) != value):
        raise ValueError(name + " must be a canonical absolute path")


@dataclass(frozen=True, slots=True)
class SourceArtifactLocator:
    """One original JSON record with physical and decoded identities.

    ``declaration`` points to the original manifest's artifact declaration.
    The pointer applies to decoded JSON; the artifact SHA applies to stored
    bytes, including gzip when present. No constructor performs I/O.
    """

    artifact: ProviderArtifact
    decoded_sha256: str
    decoded_bytes: int
    representation: str
    pointer: str = "#"
    declaration: ProviderFactReference | None = None

    def __post_init__(self):
        if type(self.artifact) is not ProviderArtifact:
            raise TypeError("source locator requires an exact ProviderArtifact")
        self.artifact.__post_init__()
        _path(self.artifact.uri, "source artifact URI")
        _sha(self.decoded_sha256, "decoded source artifact hash")
        if type(self.decoded_bytes) is not int or self.decoded_bytes < 1:
            raise ValueError("decoded source artifact size must be positive")
        if self.representation not in ("canonical-json", "gzip-canonical-json"):
            raise ValueError("unsupported source artifact representation")
        if (type(self.pointer) is not str or not (self.pointer == "#" or self.pointer.startswith("#/"))
                or re.search(r"~(?![01])", self.pointer) is not None):
            raise ValueError("source locator requires a JSON fragment pointer")
        if self.representation == "canonical-json" and (
                self.artifact.sha256 != self.decoded_sha256
                or self.artifact.size_bytes != self.decoded_bytes):
            raise ValueError("plain canonical JSON must have identical physical/decoded identities")
        if self.declaration is not None:
            if type(self.declaration) is not ProviderFactReference:
                raise TypeError("source declaration must be a ProviderFactReference")
            self.declaration.__post_init__()


@dataclass(frozen=True, slots=True)
class SourceDefinitionReference:
    """An original definition in its root, artifact and source namespace.

    Root/provider records are evidence references. Ownership metadata does
    not prove effects, package-at-capture identity or a canonical typed body.
    ``graph.pointer`` names the original semantic definition record.
    """

    root: SourceArtifactLocator
    providers: tuple[SourceArtifactLocator, ...]
    graph: SourceArtifactLocator
    snapshot: SourceSnapshot
    context: SourceContextDigest
    definition: OperationDefinitionID
    source: SourceReference
    reference_format: str = "scar.source-definition-reference.v1"

    def __post_init__(self):
        if self.reference_format != "scar.source-definition-reference.v1":
            raise ValueError("unsupported source definition reference format")
        for value in (self.root, self.graph):
            if type(value) is not SourceArtifactLocator:
                raise TypeError("source root/graph require exact artifact locators")
            value.__post_init__()
        if type(self.providers) is not tuple or any(type(item) is not SourceArtifactLocator for item in self.providers):
            raise TypeError("provider evidence requires an exact tuple of source locators")
        for item in self.providers:
            item.__post_init__()
        if type(self.snapshot) is not SourceSnapshot or type(self.context) is not SourceContextDigest:
            raise TypeError("definition requires the original typed snapshot and context digest")
        self.snapshot.__post_init__()
        _path(self.snapshot.path, "definition source path")
        _path(self.context.namespace_root, "definition namespace root")
        if not Path(self.snapshot.path).is_relative_to(self.context.namespace_root):
            raise ValueError("source snapshot lies outside its original namespace")
        for field in ("semantic_sha256", "semantics_sha256", "control_sha256"):
            _sha(getattr(self.context, field), "definition context " + field)
        if type(self.definition) is not OperationDefinitionID or type(self.source) is not SourceReference:
            raise TypeError("definition requires original typed DefinitionID and SourceReference")
        self.definition.__post_init__(); self.source.__post_init__()
        if self.source.path != self.snapshot.path or self.source.fingerprint != self.snapshot.fingerprint:
            raise ValueError("definition source differs from its original snapshot")

    def identity_key(self):
        """Version-qualified identity, independent of inventory indices/gzip bytes."""
        return (self.context.namespace_root, self.context.semantic_sha256,
                self.snapshot, self.definition)


__all__ = ["SourceArtifactLocator", "SourceDefinitionReference"]
