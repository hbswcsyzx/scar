"""Lossless physical layout of matched binding tracks, not new graph nodes."""
from dataclasses import dataclass
from .normal_graph import Port,CallSite
from .normal_links import Namespace
from .normal_targets import GlobalPort
from .source_name_definitions import NameDefinition,NameDefinitionTransition,NameDefinitionFrontier


@dataclass(frozen=True,slots=True)
class SharedBindingControl:
    source_function: GlobalPort
    max_states: int
    max_stack: int
    states: tuple[tuple[Port,tuple[CallSite,...]],...]
    transitions: tuple[NameDefinitionTransition,...]
    traversal_complete: bool


@dataclass(frozen=True,slots=True)
class PackedBindingTrack:
    # Unit header + ordinal select a control record. This is not a value ID.
    control: int
    namespace: Namespace
    max_updates: int
    definitions: tuple[NameDefinition,...]
    # Lowercase hexadecimal bitsets of track-local definition ordinals.
    # Equal sets in different tracks do not identify equal program values.
    definition_sets: tuple[str,...]
    states: tuple[tuple[int,int],...]
    reads: tuple[tuple[int,int,tuple[int,...],int],...]
    frontiers: tuple[NameDefinitionFrontier,...]
    dataflow_complete: bool
