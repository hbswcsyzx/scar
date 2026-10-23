"""Logical-version invariance helpers."""
from __future__ import annotations


def same_logical_version(values: list[dict]) -> bool:
    versions = {v.get("logical_version") for v in values}
    return len(versions) == 1 and None not in versions

