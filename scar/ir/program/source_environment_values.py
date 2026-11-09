"""Retained callback values, distinct from mutable namespace locations."""
from dataclasses import dataclass

from .ids import OperationID, UseID
from .normal_targets import GlobalPort
from .source_productions import ClassBodyInterface


@dataclass(frozen=True, slots=True)
class ClassTypeParameterProjection:
    """The selected callback environment supplies its retained tuple.

    ``interface.type_parameters`` retains the original source selector. This
    is neither a lookup of the later class ``__type_params__`` field nor a
    reference alias between the environment and that tuple. Creation and
    activation still have to select the same environment instance.
    """
    operation: OperationID
    interface: ClassBodyInterface
    environment: GlobalPort
    environment_use: UseID
    result: GlobalPort
    world_in: GlobalPort
    world_out: GlobalPort
