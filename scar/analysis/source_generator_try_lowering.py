"""Connect existing generator creation to a paired-exception parent builder.

The parent creation/GET_ITER calls keep the parent's real exception packet
route. The existing deferred child keeps its independent raw exception/world
and PEP479 ABI. No child activation, driver, traceback value or source slot is
created by this adapter. Old generator producer/rule bytes remain unchanged.
"""
from __future__ import annotations

from scar.analysis.structured_lowering import StructuredBuilder


class _CreationParent:
    """Private construction view, never a graph/evidence owner or wire input.

    _Nested copies the ordinary builder buffers. Dispatch child emissions to
    the unbound structured base over the *real* owner: IDs and operation budget
    remain shared, while FunctionTry.emit cannot assign a child operation to
    its parent's control/cleanup scope. Parent calls stay genuine bound parent
    methods, so failure references are never narrowed to a raw exception.
    """
    def __init__(self, parent):
        self.__dict__.update(parent.__dict__)
        self._parent_builder = parent

    def __getattr__(self, name):
        return getattr(self._parent_builder, name)

    def fresh(self, cls, tag):
        return self._parent_builder.fresh(cls, tag)

    def emit(self, cursor, operation, node, role, old=None):
        parent = self._parent_builder
        if cursor.block in parent.function_blocks:
            return parent.emit(cursor, operation, node, role, old=old)
        return StructuredBuilder.emit(parent, cursor, operation, node, role, old=old)


def lower_paired_creation(builder, node, cursor):
    from scar.analysis.source_function_try_lowering import FunctionTryBuilder
    from scar.analysis.source_generator_lowering import TABLES
    from scar.analysis.source_generator_creation_lowering import lower_creation
    if not isinstance(builder, FunctionTryBuilder) or not builder.has_language('GENEXPR_CREATION_314_V1'):
        raise TypeError('paired generator creation requires the existing genuine parent builder/capability')
    if not hasattr(builder, 'generator_records'):
        builder.generator_records = {name: [] for name in TABLES}
        builder.generator_handles = {}
    return lower_creation(_CreationParent(builder), node, cursor)
