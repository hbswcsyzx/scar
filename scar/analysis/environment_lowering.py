"""Construct explicit function environments in the existing source/core model.

This profile describes source-selected function bodies.  Entry references are
ports, never observations of actual Python objects.  Cells and namespaces keep
the ordinary coarse-world state chain: address refinements identify relevant
owners without claiming disjointness or complete effects.
"""
from __future__ import annotations

import ast
from dataclasses import replace

from scar.analysis.program_lowering import _Unsupported, _key, _REF
from scar.analysis.structured_lowering import StructuredBuilder
from scar.ir.program.environments import (
    EnvironmentInterface, EnvironmentMember, EnvironmentRole, FunctionEntryLayout,
)
from scar.ir.program.functions import BodyEntryInterface, BodyLoweringProfile, FormalPort
from scar.ir.program.ids import EnvironmentInterfaceID, RegionID, ValueID
from scar.ir.program.model import (
    AccessMode, Behavior, Block, BlockArgument, ExitKind, ExitPort, ReferenceValue,
    Region, StateVersionValue, TerminatorKind,
)
from scar.ir.program.source import GapKind, SourceRole
from scar.ir.program.state_addresses import (
    AddressCoverage, AddressEffect, CellContent, InvokeStateOperand, NamespaceKey,
    ReferenceOwner, StateAddressRefinement,
)
from scar.ir.program.structured import PythonProtocolKind
from scar.ir.v2.ids import ValueSlotID


_PREFIX = (
    EnvironmentRole.FUNCTION_OBJECT,
    EnvironmentRole.GLOBALS_NAMESPACE,
    EnvironmentRole.BUILTINS_NAMESPACE,
    EnvironmentRole.DEFAULTS,
    EnvironmentRole.KEYWORD_DEFAULTS,
)


def captured_cell_slot(definition, name):
    """This body's free-variable interface slot, distinct from its origin slot."""
    return ValueSlotID(_key("captured-cell-interface", definition.wire, name))


class StructuredEnvironmentBuilder(StructuredBuilder):
    """The structured body rules with canonical environment and address ports."""

    def __init__(self, context, entry, *, source=None, max_operations=10000, sealed_source=None,
                 language_options=None):
        super().__init__(context, entry, source=source, max_operations=max_operations,
                         sealed_source=sealed_source, language_options=language_options)
        self.profile = BodyLoweringProfile.STRUCTURED_ENV
        self.prepared_source = context
        self.environment = None
        self.environment_references = {}
        self.cell_references = {}
        self.free_cells = frozenset()
        self.local_cells = frozenset()
        self.address_refinements = []

    def make_graph(self):
        return replace(super().make_graph(),
            environments=(self.environment,),
            function_entries=(FunctionEntryLayout(self.environment.id, self.interface.parameters),),
            state_address_refinements=tuple(self.address_refinements))

    def _addresses(self, operation_id, effects):
        operation = self.operation_records[operation_id]
        # invoke() appends exactly this operation's current coarse-world Use.
        state_use = operation.uses[-1]
        self.address_refinements.append(StateAddressRefinement(
            InvokeStateOperand(operation_id, state_use.id), tuple(effects), AddressCoverage.PARTIAL))

    def _cell_read(self, node, cursor, old):
        cell = self.cell_references[node.id]
        cursor, value, operation_id = self.invoke(cursor, node,
            ((cell, node, "cell-owner", 0, None),), old=old)
        kind = (PythonProtocolKind.READ_FREE_CELL if node.id in self.free_cells
                else PythonProtocolKind.READ_LOCAL_CELL)
        self.protocol(operation_id, kind, node)
        operation = self.operation_records[operation_id]
        self._addresses(operation_id, (AddressEffect(
            ReferenceOwner(operation.uses[0].id), (CellContent(),), AccessMode.READ),))
        return cursor, value

    def _global_read(self, node, cursor, old):
        key = self.literal(node, node.id)
        globals_ref = self.environment_references[EnvironmentRole.GLOBALS_NAMESPACE]
        builtins_ref = self.environment_references[EnvironmentRole.BUILTINS_NAMESPACE]
        cursor, value, operation_id = self.invoke(cursor, node, (
            (globals_ref, node, "globals-owner", 0, None),
            (builtins_ref, node, "builtins-owner", 0, None),
            (key, node, "namespace-key", 0, None),
        ), old=old)
        self.protocol(operation_id, PythonProtocolKind.LOOKUP_GLOBAL, node)
        operation = self.operation_records[operation_id]
        self._addresses(operation_id, tuple(AddressEffect(
            ReferenceOwner(operation.uses[index].id),
            (NamespaceKey(operation.uses[2].id),), AccessMode.READ) for index in (0, 1)))
        self.gap(GapKind.EFFECT_SUMMARY, node,
            "globals lookup precedes saved-builtins fallback; runtime namespace contents and complete effects remain unproved")
        if node.id in self.functions and len(self.function_candidates.get(node.id, ())) == 1:
            self.reference_candidates[value] = node.id
        return cursor, value

    def expr(self, node, cursor):
        if (self.has_language("CALL_KWARGS_314_V1") and isinstance(node, ast.Call)
                and any(keyword.arg is None for keyword in node.keywords)):
            from scar.analysis.source_call_lowering import lower_kwargs_call
            return lower_kwargs_call(self, node, cursor)
        if self.has_language("LEXICAL_LOCALS") and isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            label = ("GENERATOR_EXPRESSION_CREATION_DRIVE_INTERFACE_UNIMPLEMENTED" if isinstance(node, ast.GeneratorExp)
                     else "COMPREHENSION_SCOPE_INTERFACE_UNIMPLEMENTED")
            raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, node, label)
        if self.has_language("SLICE_KEYS") and isinstance(node, (ast.Slice, ast.Subscript)):
            from scar.analysis.source_slice_lowering import lower_slice, lower_subscript
            return lower_slice(self, node, cursor) if isinstance(node, ast.Slice) else lower_subscript(self, node, cursor)
        if isinstance(node, ast.Dict):
            from scar.analysis.source_mapping_lowering import lower_dictionary
            return lower_dictionary(self, node, cursor)
        if isinstance(node, ast.JoinedStr):
            from scar.analysis.source_string_lowering import lower_joined_string
            return lower_joined_string(self, node, cursor)
        if isinstance(node, ast.BoolOp):
            from scar.analysis.source_conditional_lowering import lower_bool_expression
            return lower_bool_expression(self, node, cursor)
        if isinstance(node, ast.IfExp):
            from scar.analysis.source_conditional_lowering import lower_if_expression
            return lower_if_expression(self, node, cursor)
        if isinstance(node, ast.Name):
            return self.read_source_name(node, cursor, self.old_operation(node))
        return super().expr(node, cursor)

    def condition(self, node, cursor):
        if isinstance(node, (ast.BoolOp, ast.IfExp)) or isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            from scar.analysis.source_conditional_lowering import lower_condition_expression
            return lower_condition_expression(self, node, cursor)
        return super().condition(node, cursor)

    def read_source_name(self, node, cursor, old=None):
        """A target child may have SG provenance without a computational overlay."""
        if node.id in self.cell_references:
            return self._cell_read(node, cursor, old)
        if node.id in cursor.env:
            return self.read_local(node, cursor, old)
        if node.id in self.locals:
            raise _Unsupported(GapKind.SOURCE_MAPPING, node,
                "ordinary local binding is missing from the function frame: " + node.id)
        if node.id not in self.global_names:
            raise _Unsupported(GapKind.SOURCE_MAPPING, node,
                "Name has no exact compiler environment classification: " + node.id)
        return self._global_read(node, cursor, old)

    def store(self, target, value, cursor):
        if self.has_language("FIXED_UNPACK") and isinstance(target, (ast.Tuple, ast.List)):
            from scar.analysis.source_unpack_lowering import lower_unpack_target
            return lower_unpack_target(self, target, value, cursor)
        if isinstance(target, (ast.Attribute, ast.Subscript)):
            from scar.analysis.source_heap_lowering import store_heap_target
            return store_heap_target(self, target, value, cursor)
        if isinstance(target, ast.Name) and target.id in self.cell_references:
            cursor, _, operation_id = self.invoke(cursor, target, (
                (self.cell_references[target.id], target, "cell-owner", 0, None),
                (value, target, "assigned-reference", 0, None),
            ), role=SourceRole.LOCAL_BINDING, old=self.old_operation(target), result_type=None)
            self.protocol(operation_id, PythonProtocolKind.STORE_CELL, target)
            operation = self.operation_records[operation_id]
            self._addresses(operation_id, (AddressEffect(
                ReferenceOwner(operation.uses[0].id), (CellContent(),), AccessMode.WRITE),))
            return cursor
        if isinstance(target, ast.Name) and target.id in self.global_names:
            key = self.literal(target, target.id)
            cursor, _, operation_id = self.invoke(cursor, target, (
                (self.environment_references[EnvironmentRole.GLOBALS_NAMESPACE], target, "globals-owner", 0, None),
                (key, target, "namespace-key", 0, None),
                (value, target, "assigned-reference", 0, None),
            ), role=SourceRole.LOCAL_BINDING, old=self.old_operation(target), result_type=None)
            self.protocol(operation_id, PythonProtocolKind.STORE_GLOBAL, target)
            operation = self.operation_records[operation_id]
            self._addresses(operation_id, (AddressEffect(ReferenceOwner(operation.uses[0].id),
                (NamespaceKey(operation.uses[1].id),), AccessMode.WRITE),))
            return cursor
        return super().store(target, value, cursor)

    def statements(self, statements, cursor):
        # These declarations affect compiler binding classification; neither
        # performs a namespace read/write merely by being encountered.
        from scar.analysis.source_statement_lowering import annotated_assignment, assert_statement, raise_statement
        for node in statements:
            if isinstance(node, (ast.Global, ast.Nonlocal)):
                continue
            if cursor is None:
                cursor = super().statements((node,), cursor)
            elif isinstance(node, ast.AnnAssign):
                cursor = annotated_assignment(self, node, cursor)
            elif isinstance(node, ast.Assert):
                self.gap(GapKind.CODE_VERSION, node,
                    "assertion source semantics use compiler optimize=0; live optimized-code correspondence remains unproved")
                cursor = assert_statement(self, node, cursor)
            elif isinstance(node, ast.Raise):
                cursor = raise_statement(self, node, cursor)
            else:
                cursor = super().statements((node,), cursor)
        return cursor

    def _make_cell(self, cursor, node, name, initial=None):
        inputs = () if initial is None else ((initial, node, "initial-cell-content", 0, None),)
        cursor, reference, operation_id = self.invoke(cursor, node, inputs)
        self.protocol(operation_id, PythonProtocolKind.MAKE_CELL, node)
        operation = self.operation_records[operation_id]
        marked = replace(operation, behaviors=operation.behaviors + (Behavior.MEMORY,))
        self.operations[self.operations.index(operation)] = marked
        self.operation_records[operation_id] = marked
        self.cell_references[name] = reference
        # An ordinary call's own cells are per-invocation allocations, not
        # captured-cell entry parameters or immutable local binding tokens.
        self.active_temporaries.append(reference)
        return cursor

    def build_function(self):
        from scar.analysis.function_interfaces import formal_nodes
        from scar.analysis.source_environment_layout import compiler_environment_layout

        node = self.functions[self.entry]
        if isinstance(node, ast.AsyncFunctionDef):
            raise _Unsupported(GapKind.UNSUPPORTED_SIGNATURE, node,
                "async completion/suspension interface is not implemented")

        def body_nodes(nodes):
            for child in nodes:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                    continue
                yield child
                yield from body_nodes(ast.iter_child_nodes(child))

        if any(isinstance(child, (ast.Yield, ast.YieldFrom)) for child in body_nodes(node.body)):
            raise _Unsupported(GapKind.UNSUPPORTED_SIGNATURE, node,
                "generator enter/yield/resume/close interface is not implemented")
        self.function_definition = self.definition(node)
        self.function_context = RegionID(_key("function-body", self.function_definition.id.wire, self.profile.value))
        self.function_blocks = []; self.reference_candidates = {}
        try:
            evidence = self.language_options.code_evidence if self.language_options is not None else None
            if evidence is not None:
                from scar.analysis.source_environment_layout import CompilerEnvironmentLayout
                evidence.require_definition(self.snapshot, self.function_definition.id, self.source(node))
                code = evidence.code
                layout = CompilerEnvironmentLayout(tuple(code.co_freevars), tuple(code.co_cellvars),
                                                   code.co_qualname, code.co_firstlineno)
            else:
                layout = compiler_environment_layout(self.prepared_source, node, self.function_definition)
        except (ValueError, SyntaxError, TypeError, KeyError, RecursionError) as error:
            raise _Unsupported(GapKind.SOURCE_MAPPING, node,
                "compiler environment layout unavailable: " + str(error)) from error
        self.free_cells, self.local_cells = frozenset(layout.freevars), frozenset(layout.cellvars)
        table = self.symbol_tables[(node.name, node.lineno)]
        symbols = tuple(table.get_symbols())
        free_names = {symbol.get_name() for symbol in symbols if symbol.is_free() or symbol.is_nonlocal()}
        if free_names != self.free_cells:
            raise _Unsupported(GapKind.SOURCE_MAPPING, node,
                "source symbol table and compiled free-variable interface differ")
        physical_locals = {symbol.get_name() for symbol in symbols if symbol.is_local()}
        if self.has_language("LEXICAL_LOCALS"):
            from scar.ir.program.source_language import CompilerLocalMapping
            lexical = {name for owner, name in self.slots if owner == self.function_definition.id}
            transient = set()
            def comprehension_in_this_function(owner):
                seen = set()
                while owner in self.semantic.definitions and owner not in seen:
                    if owner == self.function_definition.id:
                        return True
                    seen.add(owner)
                    definition = self.semantic.definitions[owner]
                    if getattr(definition.kind, "value", definition.kind) in ("function", "method", "class"):
                        return False
                    owner = definition.parent_id
                return False
            for symbol in symbols:
                name = symbol.get_name()
                if not symbol.is_local():
                    continue
                comp_iter = bool(getattr(symbol, "is_comp_iter", lambda: False)())
                comp_cell = bool(getattr(symbol, "is_comp_cell", lambda: False)())
                if name in lexical:
                    slots = (self.slots[self.function_definition.id, name],)
                    category = "LEXICAL_FUNCTION"
                elif comp_iter or comp_cell:
                    slots = tuple(slot.slot_id for slot in self.semantic.slots.values()
                                  if slot.name == name and slot.metadata.get("scope_kind") == "comprehension"
                                  and comprehension_in_this_function(slot.owner))
                    if not slots:
                        raise _Unsupported(GapKind.SOURCE_MAPPING, node,
                            "COMPILER_COMPREHENSION_SLOT_UNRECOVERED: " + name)
                    category = "COMPREHENSION_TRANSIENT"
                    transient.add(name)
                else:
                    raise _Unsupported(GapKind.SOURCE_MAPPING, node,
                        "compiler local has no exact lexical or comprehension source slot: " + name)
                self.language_compiler_locals.append(CompilerLocalMapping(name, category, slots, comp_iter, comp_cell))
            self.local_cells = frozenset(set(self.local_cells) - transient)
            physical_locals -= transient
        self.locals = physical_locals - self.local_cells
        self.global_names = {symbol.get_name() for symbol in symbols if symbol.is_global()}
        parameters = [argument for argument, _ in formal_nodes(node)]
        cursor = self.new_block(node)
        state = self.pop_value()
        args, ports, refs, members = [], [], [], []

        def environment_reference(role, name=None, position=None):
            value = ReferenceValue(self.fresh(ValueID, "environment-reference"), self.function_context,
                                   BlockArgument(cursor.block, len(args)))
            self.add_value(value); args.append(value.id)
            self.link_value(value, node, SourceRole.FUNCTION_OBJECT)
            refs.append((value.id, node, "environment-reference"))
            slot = captured_cell_slot(self.function_definition.id, name) if name is not None else None
            members.append(EnvironmentMember(role, value.id, (self.world,), slot, position))
            if name is None:
                self.environment_references[role] = value.id
            else:
                self.cell_references[name] = value.id

        for role in _PREFIX:
            environment_reference(role)
        for position, name in enumerate(layout.freevars):
            environment_reference(EnvironmentRole.CAPTURED_CELL, name, position)
        for parameter in parameters:
            value = ReferenceValue(self.fresh(ValueID, "formal"), self.function_context,
                                   BlockArgument(cursor.block, len(args)))
            slot = self.slots.get((self.function_definition.id, parameter.arg))
            if slot is None:
                raise _Unsupported(GapKind.SOURCE_MAPPING, parameter, "formal has no parsed slot")
            self.add_value(value); args.append(value.id); refs.append((value.id, parameter, "formal-reference"))
            self.link_value(value, parameter, SourceRole.PARAMETER, slot=slot)
            ports.append(FormalPort(slot, value.id))
        state = StateVersionValue(state.id, state.region, BlockArgument(cursor.block, len(args)), state.location)
        self.add_value(state); self.link_value(state, node, SourceRole.STATE)
        cursor.state = state.id; args.append(state.id); self.block_arguments[cursor.block] = tuple(args)
        self.interface = BodyEntryInterface(self.function_definition.id, self.function_context,
            tuple(ports), state.id, self.profile)
        self.environment = EnvironmentInterface(
            EnvironmentInterfaceID(_key("source-function-environment", self.function_definition.id.wire, self.profile.value)),
            self.function_context, self.function_definition.id, tuple(members))
        self.frame_transition(cursor, node, refs, PythonProtocolKind.FRAME_ENTER)
        parameter_values = {parameter.arg: port.value for parameter, port in zip(parameters, ports)}
        for name in layout.cellvars:
            if name not in self.local_cells:
                continue
            parameter_node = next((parameter for parameter in parameters if parameter.arg == name), node)
            cursor = self._make_cell(cursor, parameter_node, name, parameter_values.get(name))
        for name in sorted(self.locals):
            parameter_node = next((parameter for parameter in parameters if parameter.arg == name), node)
            self.define_binding(name, cursor, parameter_node, parameter_values.get(name))
        self.gap(GapKind.FRAME_EFFECT, node,
            "frame interposition, lifetime, finalizers and noncompletion remain explicit unproved conditions")
        self.gap(GapKind.CODE_VERSION, node,
            "source environment ports are declared; live function object, namespaces, cells and definition-time effects remain unproved")
        statements = node.body
        if (statements and isinstance(statements[0], ast.Expr)
                and isinstance(statements[0].value, ast.Constant) and type(statements[0].value.value) is str):
            statements = statements[1:]
        cursor = self.statements(statements, cursor)
        if cursor is not None:
            self.finish_exit(cursor, node, self.literal(node, None), ExitKind.NORMAL)
        blocks = tuple(Block(block, self.block_arguments[block], tuple(self.block_operations[block]))
                       for block in self.function_blocks)
        completed = {operation.terminator.kind for operation in self.operations if operation.terminator is not None}
        exits = tuple(ExitPort(kind.value.lower(), kind, (_REF, self.state_type)) for kind, terminator in
            ((ExitKind.NORMAL, TerminatorKind.RETURN), (ExitKind.RAISE, TerminatorKind.RAISE)) if terminator in completed)
        self.regions.append(Region(self.function_context, self.entry, self.interface_region_entry(), blocks, exits))
        return node


__all__ = ["StructuredEnvironmentBuilder", "captured_cell_slot"]
