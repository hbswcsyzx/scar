"""Open retained trace artifacts as streams, including lossless gzip archives."""
from __future__ import annotations

import gzip
from pathlib import Path


def resolve(path: str | Path, *, default_name: str | None = None) -> Path:
    path = Path(path)
    if path.is_dir() and default_name is not None:
        path = path / default_name
    if not path.exists() and path.suffix != ".gz":
        archive = Path(str(path) + ".gz")
        if archive.is_file():
            return archive
    return path


def open_binary(path: str | Path):
    path = resolve(path)
    return gzip.open(path, "rb") if path.suffix == ".gz" else path.open("rb")


def open_text(path: str | Path):
    path = resolve(path)
    return (gzip.open(path, "rt", encoding="utf-8") if path.suffix == ".gz"
            else path.open("r", encoding="utf-8"))
