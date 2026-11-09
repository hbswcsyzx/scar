"""Source body references shared across caller contexts and compilation forms."""
from dataclasses import dataclass

from .normal_targets import GlobalPort
from .providers import ProviderFactReference
from .reference_consumers import ConsumerBodyEntry
from .source_value_flow import SourceBodyValueFlow, SourceDataReach


@dataclass(frozen=True, slots=True)
class SharedBodyReference:
    source_function: GlobalPort
    body: ProviderFactReference


@dataclass(frozen=True, slots=True)
class BodyExpansionFrontier:
    binding: int
    reason: str


@dataclass(frozen=True, slots=True)
class SourceBodyExpansion:
    """entries/reaches.body index references, not the new-bodies table.

    references may select original parent value-flow bodies. Only additional
    bodies are stored locally; bindings index the original interface parent.
    """
    bodies: tuple[SourceBodyValueFlow, ...]
    references: tuple[SharedBodyReference, ...]
    entries: tuple[ConsumerBodyEntry, ...]
    reaches: tuple[SourceDataReach, ...]
    frontiers: tuple[BodyExpansionFrontier, ...]
