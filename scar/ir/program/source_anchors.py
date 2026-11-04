"""Unit-local identity links from original F2 occurrences to legacy atoms.

These records do not change either ID domain or attest execution semantics.
Their authority is conditional on the independently accepted input materials.
"""
from dataclasses import dataclass
from pathlib import PurePosixPath
import re

from scar.ir.v2.ids import SourceAtomID


def _digest(value):
    return type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None


@dataclass(frozen=True, slots=True)
class SourceAnchorInput:
    f0_sha256: str
    f2_sha256: str
    semantic_sha256: str
    path: str
    namespace_root: str
    fingerprint: str

    def __post_init__(self):
        if not all(_digest(value) for value in (self.f0_sha256, self.f2_sha256, self.semantic_sha256)):
            raise ValueError('source anchor inputs require exact document digests')
        for value in (self.path, self.namespace_root):
            if (type(value) is not str or not value or '\0' in value
                    or not PurePosixPath(value).is_absolute()
                    or str(PurePosixPath(value)) != value or '..' in PurePosixPath(value).parts):
                raise ValueError('source anchor paths must be normalized absolute paths')
        if not PurePosixPath(self.path).is_relative_to(PurePosixPath(self.namespace_root)):
            raise ValueError('source anchor path must belong to its original namespace')
        if (type(self.fingerprint) is not str or not self.fingerprint.startswith('sha256:')
                or not _digest(self.fingerprint[len('sha256:'):])):
            raise ValueError('source anchor fingerprint requires the original decoded digest')


@dataclass(frozen=True, slots=True)
class SourceAtomAnchor:
    atom: SourceAtomID
    occurrence: int
    breadth_first_ordinal: int

    def __post_init__(self):
        if type(self.atom) is not SourceAtomID:
            raise TypeError('source atom anchor requires exact SourceAtomID')
        if any(type(n) is not int or n < 0 for n in (self.occurrence, self.breadth_first_ordinal)):
            raise ValueError('source atom anchor ordinals must be nonnegative integers')


@dataclass(frozen=True, slots=True)
class SourceAtomAnchors:
    input: SourceAnchorInput
    frontend_sha256: str
    occurrences: int
    anchors: tuple[SourceAtomAnchor, ...]
    rule_version: str = 'FRONTEND_V2_ATOM_ID_FROM_F2_V1'
    schema: str = 'scar.source-atom-anchors'
    schema_version: int = 1
    authority: str = 'SOURCE_ATOM_IDENTITY_ONLY'

    def __post_init__(self):
        if type(self.input) is not SourceAnchorInput:
            raise TypeError('source atom anchors require original typed inputs')
        self.input.__post_init__()
        if (not _digest(self.frontend_sha256) or type(self.occurrences) is not int or self.occurrences < 1
                or type(self.anchors) is not tuple or any(type(row) is not SourceAtomAnchor for row in self.anchors)):
            raise ValueError('invalid source anchor records or occurrence domain')
        for row in self.anchors:
            row.__post_init__()
            if max(row.occurrence, row.breadth_first_ordinal) >= self.occurrences:
                raise ValueError('source anchor ordinal is outside the original F2 domain')
        if (len({row.atom for row in self.anchors}) != len(self.anchors)
                or len({row.occurrence for row in self.anchors}) != len(self.anchors)
                or len({row.breadth_first_ordinal for row in self.anchors}) != len(self.anchors)
                or tuple(row.breadth_first_ordinal for row in self.anchors)
                   != tuple(sorted(row.breadth_first_ordinal for row in self.anchors))):
            raise ValueError('source anchors must be one-to-one in original BFS order')
        if (self.rule_version != 'FRONTEND_V2_ATOM_ID_FROM_F2_V1'
                or self.schema != 'scar.source-atom-anchors'
                or type(self.schema_version) is not int or self.schema_version != 1
                or self.authority != 'SOURCE_ATOM_IDENTITY_ONLY'):
            raise ValueError('unsupported source anchor profile or authority')


__all__ = ['SourceAnchorInput', 'SourceAtomAnchor', 'SourceAtomAnchors']
