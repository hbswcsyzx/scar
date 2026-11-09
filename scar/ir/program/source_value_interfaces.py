"""May-value dependencies joined to original source argument interfaces."""
from dataclasses import dataclass

from .reference_consumers import ReferenceArgumentUse, SourceConsumerBinding, ConsumerFrontier


@dataclass(frozen=True, slots=True)
class SourceValueInterfaceUse:
    reach: int
    input: int
    use: ReferenceArgumentUse


@dataclass(frozen=True, slots=True)
class SourceValueInterfaceGraph:
    """Binding.use indexes uses; use.node/frontier.node index parent reaches.

    The root formal's may-dependency on an actual is supplied by the parent
    value-flow graph. Only the original actual-to-formal route is retained as
    reference transport; this graph grants no root/actual identity or dispatch.
    """
    uses: tuple[SourceValueInterfaceUse, ...]
    bindings: tuple[SourceConsumerBinding, ...]
    frontiers: tuple[ConsumerFrontier, ...]
    semantics: str = 'MAY_VALUE_DEPENDENCY_TO_SOURCE_INTERFACES_NOT_ROOT_ALIAS_OR_RUNTIME_DISPATCH'
