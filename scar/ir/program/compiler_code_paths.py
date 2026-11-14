"""Compiler construction paths; source scopes and runtime values stay distinct."""
from dataclasses import dataclass
from enum import StrEnum


class CompilerCodeRole(StrEnum):
    ROOT = 'ROOT'
    FUNCTION_BODY = 'FUNCTION_BODY'
    LAMBDA_BODY = 'LAMBDA_BODY'
    CLASS_BODY = 'CLASS_BODY'
    TYPE_PARAMETERS = 'TYPE_PARAMETERS'
    HEADER_ANNOTATIONS = 'HEADER_ANNOTATIONS'
    VARIABLE_ANNOTATIONS = 'VARIABLE_ANNOTATIONS'
    TYPE_PARAMETER_BOUND = 'TYPE_PARAMETER_BOUND'
    TYPE_PARAMETER_DEFAULT = 'TYPE_PARAMETER_DEFAULT'
    TYPE_ALIAS = 'TYPE_ALIAS'
    COMPREHENSION = 'COMPREHENSION'
    GENERATOR_EXPRESSION = 'GENERATOR_EXPRESSION'


@dataclass(frozen=True, slots=True)
class CompilerCodePath:
    block: int
    source_scope: int
    role: CompilerCodeRole
    constant_path: tuple[int, ...]
    load_offset: int | None
    position: tuple[int | None, ...] | None

    def __post_init__(self):
        if (type(self.block) is not int or self.block < 0
                or type(self.source_scope) is not int or self.source_scope < 0
                or type(self.role) is not CompilerCodeRole
                or any(type(i) is not int or i < 0 for i in self.constant_path)
                or (self.role is CompilerCodeRole.ROOT) != (not self.constant_path)
                or (self.load_offset is None) != (not self.constant_path)):
            raise ValueError('compiler correspondence needs an original scope and constant path')
