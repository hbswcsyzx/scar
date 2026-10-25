"""Stable identities used by the execution IR."""
from __future__ import annotations

import hashlib
import marshal
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import CodeType


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


@lru_cache(maxsize=4096)
def _describe_code(code: CodeType, filename: str, qualname: str, line: int):
    # Fingerprint the loaded executable, including constants and nested code.
    # Reading the file here could instead fingerprint a later on-disk edit.
    # The explicit location arguments prevent equal code objects from sharing
    # an identity when they originated in different source locations.
    source = filename if filename.startswith("<") else str(Path(filename).resolve())
    version = "pycode-sha256:" + hashlib.sha256(marshal.dumps(code)).hexdigest()
    return source, qualname, line, version


@dataclass(frozen=True, slots=True)
class CodeID:
    source: str
    qualname: str
    line: int | None = None
    column: int | None = None
    version: str = "unknown"

    @classmethod
    def from_frame(cls, frame) -> "CodeID":
        # The current instruction belongs in a call-site/span field, not in
        # the identity of this function. A call and return must name one code.
        return cls.from_code(frame.f_code)

    @classmethod
    def from_code(cls, code: CodeType) -> "CodeID":
        source, qualname, line, version = _describe_code(
            code, code.co_filename, getattr(code, "co_qualname", code.co_name),
            code.co_firstlineno)
        return cls(source, qualname, line, None, version)

    def key(self) -> str:
        return f"{self.source}:{self.qualname}:{self.line}:{self.column}:{self.version}"

    @classmethod
    def parse_key(cls, value: str) -> "CodeID | None":
        """Parse the versioned key while allowing colons in paths/versions."""
        try:
            value = str(value)
            if ":pycode-sha256:" in value:
                head, digest = value.rsplit(":pycode-sha256:", 1)
                source, qualname, line, column = head.rsplit(":", 3)
                version = "pycode-sha256:" + digest
            else:
                source, qualname, line, column, version = value.rsplit(":", 4)
            return cls(source, qualname, int(line),
                       None if column == "None" else int(column), version)
        except (TypeError, ValueError):
            return None


@dataclass(frozen=True, slots=True)
class InvocationID:
    value: int


@dataclass(frozen=True, slots=True)
class ObjectID:
    value: str

    @classmethod
    def of(cls, obj) -> "ObjectID":
        return cls(f"py:{id(obj):x}")


@dataclass(frozen=True, slots=True)
class StorageID:
    value: str
    epoch: int = 0


@dataclass(frozen=True, slots=True)
class LogicalVersion:
    value: str


def logical_version(storage: StorageID, epoch: int) -> LogicalVersion:
    return LogicalVersion(f"{storage.value}@{storage.epoch}:v{epoch}")
