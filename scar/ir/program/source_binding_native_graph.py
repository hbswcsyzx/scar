"""Conditional source normalization into independent native schema graphs."""
from dataclasses import dataclass

from .binding_returns import NativeReturnSlot, ValueShape
from .ids import NativeBoundaryID
from .native import EntryPortRef, ExitPortRef, NativeOutputSlot
from .normal_targets import GlobalPort
from .providers import ProviderFactReference
from .python_bindings import NativeSchemaReference, PythonBindingID
from .software_resources import OperandSource


@dataclass(frozen=True, slots=True)
class BindingSchemaLink:
    binding: PythonBindingID
    declaration: ProviderFactReference
    native: NativeSchemaReference


@dataclass(frozen=True, slots=True)
class SourceOperandNormalization:
    match: ProviderFactReference
    dependency: OperandSource
    aggregation: str | None = None


@dataclass(frozen=True, slots=True)
class SourceOutputNormalization:
    """Retain both return declarations without a one-to-one data mapping.

    world -> native_world and native_normal_world -> result_world are explicit
    conditional state dependencies. Wrapper pre/post effects remain open;
    these pairs do not establish equality of logical state versions.
    """
    match: ProviderFactReference
    binding: PythonBindingID
    declaration: ProviderFactReference
    boundary: NativeBoundaryID
    result: GlobalPort
    world: GlobalPort
    result_world: GlobalPort
    native_world: EntryPortRef
    native_normal_world: ExitPortRef
    native_outputs: tuple[NativeOutputSlot, ...]
    python_return: ValueShape | None
    native_returns: tuple[NativeReturnSlot, ...]
    conditions: tuple[str, ...]
    frontier: str | None = None
    semantics: str = 'DECLARED_WRAPPING_DEPENDENCY_NOT_NATIVE_PYTHON_OBJECT_OR_STORAGE_IDENTITY'


@dataclass(frozen=True, slots=True)
class SourceNormalizationUnit:
    unit: str
    inputs: tuple[SourceOperandNormalization, ...]
    outputs: tuple[SourceOutputNormalization, ...]
