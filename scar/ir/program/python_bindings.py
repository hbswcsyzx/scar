"""Generated Python/native interface declarations and conditional source links.

Parser, C++ and ATen parameter orders are separate. Conversion expressions
describe provider transformations; they are never same-reference/alias edges.
"""
from dataclasses import dataclass
from enum import Enum

from scar.ir.v2.ids import Identifier
from .ids import NativeBoundaryID
from .native import EntryPortRef
from .normal_targets import GlobalPort
from .providers import ProviderFactReference
from .source_references import SourceArtifactLocator
from .binding_returns import ValueShape,NativeReturnSlot,ReceiverMode


class PythonBindingID(Identifier):
    prefix = 'python_binding'


class BindingKind(str, Enum):
    FUNCTION = 'function'
    METHOD = 'method'


class ConversionStage(str, Enum):
    PYTHON_PARSE = 'python_arg_parser'
    DISPATCH_LAMBDA = 'dispatch_lambda'
    CPP_ARGUMENT = 'cpp_argument'


@dataclass(frozen=True, slots=True)
class ParserArgument:
    name: str
    schema_name: str
    type: str
    position: int | None
    parser_index: int
    keyword_only: bool
    default: str | None
    default_init: str | None = None
    parser_type: str = ''
    parser_formal: str = ''
    kind: str = ''
    output: bool = False
    tensor_option: bool = False
    generator_default: str | None = None


@dataclass(frozen=True, slots=True)
class ArgumentConversion:
    stage: ConversionStage
    argument: str
    expression: str
    cpp_type: str | None = None
    parser_index: int | None = None
    schema_arguments: tuple[str, ...] = ()
    output: bool = False


@dataclass(frozen=True, slots=True)
class NativeSchemaReference:
    selector: str
    graph: SourceArtifactLocator
    boundary: NativeBoundaryID


@dataclass(frozen=True, slots=True)
class PythonBinding:
    id: PythonBindingID
    namespace: str
    name: str
    kind: BindingKind
    registration_container: str
    selector: str
    parser_signature: str
    arguments: tuple[ParserArgument, ...]
    conversions: tuple[ArgumentConversion, ...]
    dispatch_expression: str | None
    source: ProviderFactReference
    wrapper: ProviderFactReference | None
    family_complete: bool
    native: NativeSchemaReference | None
    native_status: str
    conditions: tuple[str, ...]
    parser_index: int = 0
    group_id: str = ''
    branch_condition: str | None = None
    implicit_receiver: str | None = None
    deprecated: bool = False
    native_returns: tuple[NativeReturnSlot,...] = ()
    python_return: ValueShape | None = None


@dataclass(frozen=True, slots=True)
class NormalizationLink:
    binding: PythonBindingID
    conversion: int
    native_parameter: str
    native_port: EntryPortRef
    semantics: str = 'DECLARED_TRANSFORMATION_DEPENDENCY'


@dataclass(frozen=True, slots=True)
class NamespaceBindingLink:
    """A generated export can satisfy this open namespace lookup conditionally."""
    lookup: ProviderFactReference
    receiver: GlobalPort
    result: GlobalPort
    binding: PythonBindingID
    conditions: tuple[str, ...]
    runtime_binding_verified: bool = False


@dataclass(frozen=True, slots=True)
class SourceCallSite:
    """Original call ABI, including calls with no inferred target yet."""
    callee: GlobalPort
    positional: tuple[GlobalPort, ...]
    keywords: tuple[tuple[str, GlobalPort], ...]
    result: GlobalPort
    world: GlobalPort
    result_world: GlobalPort
    positional_pack: GlobalPort | None = None
    keyword_pack: GlobalPort | None = None


@dataclass(frozen=True, slots=True)
class NativeCallCandidate:
    site: SourceCallSite
    binding: PythonBindingID
    conditions: tuple[str, ...]
    runtime_binding_verified: bool = False
    receiver: GlobalPort | None = None
    receiver_mode: ReceiverMode = ReceiverMode.FUNCTION
