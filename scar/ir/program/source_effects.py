"""Source capabilities and effect requests, never observed resource effects.

Family labels do not establish complete read/write sets, allocation, aliases,
RNG, IO or purity. Resolution names identify the next required rule/context;
they do not grant an operation's runtime preconditions.
"""
from dataclasses import dataclass
from enum import Enum

from scar.ir.effects import ActionLabel


class EffectFamily(str, Enum):
    REGION_CONTROL = 'REGION_CONTROL'
    SUSPENSION = 'SUSPENSION'
    COMPILATION_INPUT = 'COMPILATION_INPUT'
    IDENTITY_BOOLEAN = 'IDENTITY_BOOLEAN'
    LITERAL_REPRESENTATION = 'LITERAL_REPRESENTATION'
    BINDING_NAMESPACE = 'BINDING_NAMESPACE'
    ENVIRONMENT_ENTRY = 'ENVIRONMENT_ENTRY'
    CLASS_ACCESS = 'CLASS_ACCESS'
    CODE_DECLARATION = 'CODE_DECLARATION'
    CALLABLE_CONSTRUCTION = 'CALLABLE_CONSTRUCTION'
    VALUE_TYPE_CONSTRUCTION = 'VALUE_TYPE_CONSTRUCTION'
    TYPE_PARAMETER_UPDATE = 'TYPE_PARAMETER_UPDATE'
    ANNOTATION_STATE = 'ANNOTATION_STATE'
    PYTHON_PROTOCOL = 'PYTHON_PROTOCOL'
    SPECIAL_METHOD_PROTOCOL = 'SPECIAL_METHOD_PROTOCOL'
    IMPORT_PROTOCOL = 'IMPORT_PROTOCOL'
    EXCEPTION_STATE = 'EXCEPTION_STATE'
    EXCEPTION_PROCESSING = 'EXCEPTION_PROCESSING'
    CLASS_BUILDER_LOOKUP = 'CLASS_BUILDER_LOOKUP'
    INTERACTIVE_DISPLAY = 'INTERACTIVE_DISPLAY'


class EffectResolution(str, Enum):
    REGION_COMPOSITION = 'REGION_COMPOSITION'
    COMPILE_INPUT = 'COMPILE_INPUT'
    LOCAL_INTRINSIC = 'LOCAL_INTRINSIC'
    ADDRESS_RULE = 'ADDRESS_RULE'
    DEFERRED_DECLARATION = 'DEFERRED_DECLARATION'
    DYNAMIC_TARGET_OR_PROTOCOL = 'DYNAMIC_TARGET_OR_PROTOCOL'
    INSTANCE_CONDITION = 'INSTANCE_CONDITION'


@dataclass(frozen=True, slots=True)
class FamilyRule:
    """dispatch_fields name original typed fields, without interpreting labels.

    The field values stay in the source instruction. In particular enum,
    binding, environment, ABI and source-selector distinctions are not erased
    into a family-wide purity or runtime-effect assertion.
    """
    instruction: str
    family: EffectFamily
    labels: tuple[ActionLabel, ...]
    resolution: EffectResolution
    dispatch_fields: tuple[str, ...]
