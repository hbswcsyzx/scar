"""Effect lattice. Unknown is deliberately distinct from an empty effect."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Knowledge(str, Enum):
    NONE = "NONE"
    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"


class ActionLabel(str, Enum):
    VAL = "VAL"
    REP = "REP"
    MEM = "MEM"
    XFER = "XFER"
    STATE = "STATE"
    CTRL = "CTRL"
    ORDER = "ORDER"
    IO = "IO"
    OPAQUE = "OPAQUE"


@dataclass(slots=True)
class Effect:
    reads: list[str] = field(default_factory=list)
    writes: list[str] = field(default_factory=list)
    allocates: list[str] = field(default_factory=list)
    frees: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    escapes: list[str] = field(default_factory=list)
    rng_effect: Knowledge = Knowledge.UNKNOWN
    may_raise: Knowledge = Knowledge.UNKNOWN
    external_effect: Knowledge = Knowledge.UNKNOWN
    ordering_effect: Knowledge = Knowledge.UNKNOWN
    notes: list[str] = field(default_factory=list)
    # A list holds observed members, not proof that the set is complete.
    # In particular [] must not silently mean that no writes/escapes exist.
    collection_knowledge: dict[str, Knowledge] = field(default_factory=dict)

    def __post_init__(self):
        for name in ("reads", "writes", "allocates", "frees", "aliases", "escapes"):
            try:
                self.collection_knowledge[name] = Knowledge(
                    self.collection_knowledge.get(name, Knowledge.UNKNOWN))
            except ValueError:
                self.collection_knowledge[name] = Knowledge.UNKNOWN

    @property
    def safe_for_exact_reuse(self) -> bool:
        return (
            all(value != Knowledge.UNKNOWN for value in self.collection_knowledge.values())
            and not self.writes
            and not self.allocates
            and not self.frees
            and not self.aliases
            and not self.escapes
            and self.rng_effect == Knowledge.NONE
            and self.may_raise == Knowledge.NONE
            and self.external_effect == Knowledge.NONE
            and self.ordering_effect == Knowledge.NONE
        )

    def as_dict(self) -> dict[str, Any]:
        return {"reads": self.reads, "writes": self.writes, "allocates": self.allocates,
                "frees": self.frees, "aliases": self.aliases, "escapes": self.escapes,
                "rng_effect": self.rng_effect.value, "may_raise": self.may_raise.value,
                "external_effect": self.external_effect.value,
                "ordering_effect": self.ordering_effect.value, "notes": self.notes,
                "collection_knowledge": {name: value.value for name, value in
                                         self.collection_knowledge.items()}}
