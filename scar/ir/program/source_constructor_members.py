"""Declared contexts point into one shared source-body reference registry."""
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ContextBodyReference:
    context: int
    body: int
