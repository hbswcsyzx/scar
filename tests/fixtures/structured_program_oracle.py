"""Bounded test-only execution of generated core CFG, never the root function.

Python owns host-operation semantics. Typed source opcodes/protocol records own
which operation is attempted. Opaque/UNKNOWN facts stop this oracle explicitly.
SSA registers retain host references: exact RC/GC/finalizer/traceback timing is
outside this conditional evaluator and must not be inferred from its results.
"""
from __future__ import annotations

import ast
import builtins
from dataclasses import dataclass
import operator
from pathlib import Path
import tokenize
import types

from scar.ir.program import BindingState
from scar.ir.program.model import (
    BlockArgument, CompletionResult, DataValue, ExitKind, LiteralOrigin,
    LocalBindingValue, ReferenceValue, StateVersionValue, TerminatorKind, UseRole,
    ValueKind,
)
from scar.ir.program.structured import PythonProtocolKind
from scar.ir.program.validation import require_valid
from scar.ir.semantics_v2 import Opcode


class OracleUnsupported(Exception):
    """The generated graph asks for semantics this test oracle does not model."""


class OracleBudgetExceeded(Exception):
    pass


class OracleInvariantError(AssertionError):
    pass


@dataclass(frozen=True)
class World:
    sequence: int
    observation: object


@dataclass(frozen=True)
class Binding:
    slot: object
    bound: bool
    payload: object = None


@dataclass(frozen=True)
class Visit:
    index: int
    region: object
    block: object
    operation: object
    uses: tuple


@dataclass(frozen=True)
class Outcome:
    status: str
    value: object = None
    exception: BaseException | None = None
    observation: object = None
    post_world: tuple = ()
    visits: tuple[Visit, ...] = ()
    detail: str = ''
    lifetime_scope: str = 'CONDITIONAL; exact RC/GC/frame retention is not modeled'


def freeze(value):
    """Copy only exact builtin observations; never arbitrary repr/equality."""
    if type(value) in (type(None), bool, int, float, str, bytes):
        return value
    if type(value) in (tuple, list):
        return tuple(freeze(item) for item in value)
    if type(value) is dict:
        if any(type(key) not in (str, int, bool, bytes) for key in value):
            raise OracleUnsupported('observation keys must be exact builtin scalars')
        return tuple((freeze(key), freeze(item)) for key, item in value.items())
    raise OracleUnsupported('observation must explicitly normalize host object identities')


def run_python(source, arguments, *, globals=None, observe=lambda: None,
               entry='f', filename='<independent-python>', optimize=0):
    """The independent reference runner; only this runner executes root source."""
    namespace = dict(globals or {})
    exec(compile(source, filename, 'exec', dont_inherit=True, optimize=optimize), namespace)
    try:
        value = namespace[entry](*arguments)
    except BaseException as error:
        return Outcome('RAISE', exception=error, observation=freeze(observe()))
    return Outcome('RETURN', value=value, observation=freeze(observe()))


_BINARY = {Opcode.ADD: operator.add, Opcode.SUB: operator.sub, Opcode.MUL: operator.mul,
           Opcode.TRUE_DIV: operator.truediv, Opcode.FLOOR_DIV: operator.floordiv,
           Opcode.MOD: operator.mod, Opcode.POW: operator.pow, Opcode.MATMUL: operator.matmul,
           Opcode.LSHIFT: operator.lshift, Opcode.RSHIFT: operator.rshift,
           Opcode.BIT_AND: operator.and_, Opcode.BIT_OR: operator.or_, Opcode.BIT_XOR: operator.xor,
           Opcode.IS: operator.is_, Opcode.IS_NOT: operator.is_not, Opcode.INDEX: operator.getitem}
_UNARY = {Opcode.POS: operator.pos, Opcode.NEG: operator.neg,
          Opcode.INVERT: operator.invert, Opcode.NOT: operator.not_}
_FRAME = frozenset((PythonProtocolKind.FRAME_ENTER, PythonProtocolKind.FRAME_BIND,
                    PythonProtocolKind.FRAME_DISCARD, PythonProtocolKind.FRAME_EXIT,
                    PythonProtocolKind.FRAME_HOLD_TEMPORARY,
                    PythonProtocolKind.FRAME_RELEASE_TEMPORARY))
_NO_RESULT = object()


class _Machine:
    def __init__(self, program, globals, observe, max_steps):
        self.program, self.graph = program, program.graph
        self.globals, self.observe, self.max_steps = globals, observe, max_steps
        self.regions = {item.id: item for item in self.graph.regions}
        self.blocks = {block.id: block for region in self.graph.regions for block in region.blocks}
        self.operations = {item.id: item for item in self.graph.operations}
        self.values = {item.id: item for item in self.graph.values}
        self.protocols = {item.operation: item for item in program.structured.protocols}
        self.sources = {item.operation: item for item in program.metadata.operation_links}
        self.definitions = {item.value: item for item in self.graph.binding_definitions}
        self.reads = {item.operation: item for item in self.graph.binding_reads}
        self.current, self.visits, self.parsed = {}, [], {}
        self.next_world = 0

    def snapshot(self):
        return freeze(self.observe())

    def world(self, location):
        self.next_world += 1
        value = World(self.next_world, self.snapshot())
        self.current[location] = value
        return value

    def get(self, environment, identity):
        if identity not in environment:
            value = self.values[identity]
            if not isinstance(value.origin, LiteralOrigin):
                raise OracleInvariantError('value unavailable at actual CFG visit: ' + identity.wire)
            environment[identity] = value.origin.value
        return environment[identity]

    def semantics(self, operation):
        source = self.sources.get(operation.id)
        if source is None or source.semantic_operation is None:
            raise OracleUnsupported('operation lacks typed source semantics')
        result = self.program.semantics.operations.get(source.semantic_operation)
        if result is None:
            raise OracleUnsupported('source semantic operation is unavailable')
        return result

    def local_name(self, protocol):
        reference = protocol.source
        if reference.path not in self.parsed:
            with tokenize.open(reference.path) as stream:
                self.parsed[reference.path] = ast.parse(stream.read(), filename=reference.path)
        found = [node.id for node in ast.walk(self.parsed[reference.path])
                 if isinstance(node, ast.Name) and
                 (node.lineno, node.end_lineno, node.col_offset, node.end_col_offset) ==
                 (reference.start_line, reference.end_line, reference.start_column, reference.end_column)]
        if len(found) != 1:
            raise OracleUnsupported('unbound diagnostic source is not one exact Name')
        return found[0]

    def unbound(self, slot):
        record = self.program.semantic.slots.get(slot)
        if record is None:
            raise OracleUnsupported('unbound local has no parsed source slot')
        return UnboundLocalError("cannot access local variable '" + record.name + "' where it is not associated with a value")

    def host(self, operation, operands, operand_ids):
        protocol = self.protocols.get(operation.id)
        if protocol is not None:
            kind = protocol.kind
            if kind in _FRAME:
                return _NO_RESULT
            if kind in (PythonProtocolKind.OPAQUE_EXPRESSION, PythonProtocolKind.OPAQUE_STATEMENT):
                raise OracleUnsupported(kind.value + ' is not executable semantics')
            if kind is PythonProtocolKind.TRUTH:
                return bool(operands[0])
            if kind is PythonProtocolKind.GET_ITERATOR:
                return iter(operands[0])
            if kind is PythonProtocolKind.ADVANCE_ITERATOR:
                return next(operands[0])
            if kind is PythonProtocolKind.MATCH_STOP_ITERATION:
                # isinstance(exc, StopIteration) can consult a spoofed
                # exc.__class__; exception matching uses the real type.
                return issubclass(type(operands[0]), builtins.StopIteration)
            if kind is PythonProtocolKind.MAKE_UNBOUND_LOCAL_ERROR:
                return UnboundLocalError("cannot access local variable '" + self.local_name(protocol)
                                         + "' where it is not associated with a value")
            raise OracleUnsupported('unsupported typed Python protocol')
        read = self.reads.get(operation.id)
        if read is not None:
            binding = operands[operand_ids.index(read.binding)]
            if type(binding) is not Binding:
                raise OracleInvariantError('local read did not consume a binding token')
            if not binding.bound:
                raise self.unbound(binding.slot)
            return binding.payload
        semantics = self.semantics(operation)
        opcode = semantics.opcode
        if opcode is Opcode.OPAQUE:
            raise OracleUnsupported('typed OPAQUE source expression is not modeled')
        if opcode is Opcode.LITERAL:
            return semantics.literal.to_python()
        if opcode is Opcode.READ:
            use = self.program.semantics.uses[semantics.binding_use]
            name = self.program.semantic.slots[use.slot].name
            if name in self.globals:
                return self.globals[name]
            namespace = self.globals.get('__builtins__', vars(builtins))
            namespace = vars(namespace) if type(namespace) is types.ModuleType else namespace
            if name in namespace:
                return namespace[name]
            raise NameError("name '" + name + "' is not defined")
        if opcode in (Opcode.ALIAS, Opcode.RETURN):
            return operands[0]
        if opcode in _BINARY:
            return _BINARY[opcode](*operands)
        if opcode in _UNARY:
            return _UNARY[opcode](*operands)
        if opcode is Opcode.ATTRIBUTE:
            return getattr(operands[0], semantics.attribute)
        if opcode is Opcode.BUILD_TUPLE:
            return tuple(operands)
        if opcode is Opcode.BUILD_LIST:
            return list(operands)
        if opcode is Opcode.BUILD_SET:
            return set(operands)
        if opcode is Opcode.BUILD_DICT:
            roles = [item.role for item in semantics.operands]
            if roles != [role for _ in range(len(roles) // 2) for role in ('key', 'value')]:
                raise OracleUnsupported('dictionary unpacking is not modeled')
            result = {}
            for key, value in zip(operands[::2], operands[1::2]):
                result[key] = value
            return result
        if opcode is Opcode.CALL:
            roles = [item.role for item in semantics.operands]
            if not roles or roles[0] != 'callee' or len(roles) != len(operands):
                raise OracleUnsupported('CALL lacks its exact ordered source operand roles')
            function, *actuals = operands
            if type(function) is types.FunctionType:
                root = self.program.metadata.source
                if (Path(function.__code__.co_filename).resolve() == Path(root.path).resolve()
                        and function.__code__.co_qualname == self.program.metadata.entry):
                    raise OracleUnsupported('calling the original root would bypass core execution')
            positional, keywords = [], {}
            for role, value in zip(roles[1:], actuals):
                if role == 'argument':
                    positional.append(value)
                elif role.startswith('keyword:'):
                    keywords[role.removeprefix('keyword:')] = value
                else:
                    raise OracleUnsupported('CALL packing is not modeled')
            return function(*positional, **keywords)
        raise OracleUnsupported('unsupported typed source opcode: ' + opcode.value)

    def execute(self, region_id, actuals):
        region = self.regions[region_id]
        entry = self.blocks[region.entry]
        if len(actuals) != len(entry.arguments):
            raise OracleInvariantError('region entry arity differs from actual runtime inputs')
        environment = dict(zip(entry.arguments, actuals))
        block_id = entry.id
        while True:
            block = self.blocks[block_id]
            transferred = False
            for identity in block.operations:
                operation = self.operations[identity]
                if len(self.visits) >= self.max_steps:
                    raise OracleBudgetExceeded('dynamic operation budget exhausted')
                self.visits.append(Visit(len(self.visits), region_id, block_id, identity,
                                         tuple(use.id for use in operation.uses)))
                uses = {use.id: self.get(environment, use.value) for use in operation.uses}
                for use in operation.uses:
                    value = self.values[use.value]
                    if isinstance(value, StateVersionValue) and self.current.get(value.location) is not uses[use.id]:
                        raise OracleInvariantError('stale declared runtime world consumed')
                    if isinstance(value, StateVersionValue) and uses[use.id].observation != self.snapshot():
                        raise OracleInvariantError('visible host state changed without a declared post-world')
                term = operation.terminator
                read = self.reads.get(identity)
                if term is not None and term.kind is not TerminatorKind.INVOKE:
                    if read is not None and read.normal_result is None:
                        binding = uses[read.binding]
                        if type(binding) is not Binding or binding.bound:
                            raise OracleInvariantError('unbound-only RAISE reached with a bound token')
                    if term.kind in (TerminatorKind.RETURN, TerminatorKind.RAISE):
                        payloads = tuple(uses[value] for value in term.values)
                        for value in payloads:
                            if isinstance(value, World) and not any(value is world for world in self.current.values()):
                                raise OracleInvariantError('completion carries stale post-world')
                        return (ExitKind.NORMAL if term.kind is TerminatorKind.RETURN else ExitKind.RAISE), payloads
                    if term.kind is TerminatorKind.JUMP:
                        edge = term.successors[0]
                    elif term.kind is TerminatorKind.BRANCH:
                        condition = uses[term.condition]
                        if type(condition) is not bool:
                            raise OracleInvariantError('BRANCH would perform an unmodeled truth conversion')
                        edge = term.successors[0 if condition else 1]
                    else:
                        raise OracleUnsupported('unsupported terminator')
                    incoming = tuple(uses[value] for value in edge.arguments)
                elif term is not None:
                    value_ids = {use.id: use.value for use in operation.uses}
                    operand_ids = tuple(uid for uid in operation.invoke_arguments
                                        if not isinstance(self.values[value_ids[uid]], StateVersionValue))
                    operands = [uses[uid] for uid in operand_ids]
                    try:
                        if operation.callee is not None:
                            kind, payloads = self.execute(operation.callee,
                                tuple(uses[uid] for uid in operation.invoke_arguments))
                            produced = payloads
                        else:
                            value = self.host(operation, operands, operand_ids)
                            kind = ExitKind.NORMAL
                            signature = next(item for item in operation.completions if item.kind is kind)
                            produced = self.produce(signature, value)
                    except (OracleUnsupported, OracleBudgetExceeded, OracleInvariantError):
                        raise
                    except BaseException as error:
                        kind = ExitKind.RAISE
                        signature = next(item for item in operation.completions if item.kind is kind)
                        produced = self.produce(signature, error)
                    edge = next(item for item in term.successors if item.kind is kind)
                    incoming = tuple(produced[value.index] if isinstance(value, CompletionResult) else uses[value]
                                     for value in edge.arguments)
                else:
                    definitions = [self.definitions[value] for value in operation.results if value in self.definitions]
                    for definition in definitions:
                        if definition.state is BindingState.UNKNOWN:
                            raise OracleUnsupported('UNKNOWN local binding cannot be guessed from previous token')
                    if definitions and identity not in self.protocols and read is None:
                        value = _NO_RESULT
                    else:
                        operand_ids = tuple(use.id for use in operation.uses
                                            if not isinstance(self.values[use.value], StateVersionValue))
                        operands = [uses[uid] for uid in operand_ids]
                        value = self.host(operation, operands, operand_ids)
                    for result in operation.results:
                        record = self.values[result]
                        if isinstance(record, StateVersionValue):
                            environment[result] = self.world(record.location)
                        elif isinstance(record, LocalBindingValue):
                            definition = self.definitions[result]
                            environment[result] = Binding(record.slot, definition.state is BindingState.BOUND,
                                uses[definition.payload] if definition.payload is not None else None)
                        else:
                            if value is _NO_RESULT:
                                raise OracleUnsupported('ordinary operation has an unexplained object result')
                            environment[result] = value
                    continue
                target = self.blocks[edge.block]
                if len(incoming) != len(target.arguments):
                    raise OracleInvariantError('dynamic successor arity mismatch')
                # Bind simultaneously, after all sources have been read.
                environment.update(zip(target.arguments, incoming))
                block_id, transferred = target.id, True
                break
            if not transferred:
                raise OracleInvariantError('CFG block did not terminate')

    def produce(self, signature, value):
        nonstate = sum(item.kind is not ValueKind.STATE for item in signature.types)
        if nonstate > 1 or (nonstate == 1 and value is _NO_RESULT):
            raise OracleUnsupported('completion result shape is not modeled')
        return tuple(self.world(item.location) if item.kind is ValueKind.STATE else value for item in signature.types)


def run_core(program, arguments, *, globals=None, observe=lambda: None, max_steps=10000):
    if type(max_steps) is not int or max_steps < 1:
        raise ValueError('oracle step budget must be an exact positive integer')
    if program.graph is None or getattr(program, 'structured', None) is None:
        raise OracleUnsupported('a generated supported structured source program is required')
    require_valid(program.graph)
    machine = _Machine(program, dict(globals or {}), observe, max_steps)
    try:
        actuals = {port.value: value for port, value in zip(program.interface.parameters, arguments)}
        if len(program.interface.parameters) != len(arguments):
            raise OracleInvariantError('test supplied a different Python parameter count')
        entry = machine.blocks[machine.regions[program.graph.root].entry]
        for value in entry.arguments:
            record = machine.values[value]
            if isinstance(record, StateVersionValue):
                actuals[value] = machine.world(record.location)
            elif value not in actuals:
                raise OracleUnsupported('unknown automatically generated environment entry port')
        kind, payloads = machine.execute(program.graph.root, tuple(actuals[value] for value in entry.arguments))
        worlds = tuple(value for value in payloads if isinstance(value, World))
        objects = tuple(value for value in payloads if not isinstance(value, World))
        if len(objects) != 1:
            raise OracleUnsupported('root completion must contain one reference payload')
        if any(world.observation != machine.snapshot() for world in worlds):
            raise OracleInvariantError('declared post-world differs from visible host poststate')
        return Outcome('RETURN' if kind is ExitKind.NORMAL else 'RAISE',
                       value=objects[0] if kind is ExitKind.NORMAL else None,
                       exception=objects[0] if kind is ExitKind.RAISE else None,
                       observation=machine.snapshot(), post_world=worlds, visits=tuple(machine.visits))
    except OracleUnsupported as error:
        return Outcome('UNSUPPORTED', observation=machine.snapshot(), visits=tuple(machine.visits), detail=str(error))
    except OracleBudgetExceeded as error:
        return Outcome('BUDGET_EXHAUSTED', observation=machine.snapshot(), visits=tuple(machine.visits), detail=str(error))


__all__ = ['Outcome', 'Visit', 'World', 'Binding', 'OracleUnsupported', 'OracleInvariantError',
           'freeze', 'run_python', 'run_core']
