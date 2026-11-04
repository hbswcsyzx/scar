"""F4-A structural grammar is closed independently of opcode semantics."""
from copy import deepcopy
from dataclasses import fields, is_dataclass, replace
from enum import Enum
from hashlib import sha256
import json
import types
import typing

import pytest

from scar.ir.literals import PythonLiteral
from scar.ir.program.ids import (BlockID, LocationID, OperationID, RegionID,
    ResourceDefinitionID, ResourceRequirementID, UseID, ValueID)
from scar.ir.program.literal_sources import ExactLiteralOrigin, SourceExpression
from scar.ir.program.model import (AccessMode, Behavior, Block, BlockArgument, DataValue,
    ExitKind, ExitPort, LiteralOrigin, Operation, OperationResult, ProgramGraph, ReferenceValue,
    Region, Stability, StateAccess, StateLocation, StateVersionValue, Successor, Terminator,
    TerminatorKind, Use, UseRole, ValueKind, ValueType)
from scar.ir.program.resources import (ExternalResource, ResourceDefinition, ResourceKind,
    ResourceLocation, ResourceRequirement, ResourceRole, ResourceUse)
from scar.ir.program.validation import validate
from scar.ir.record_codec import encode
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import Identifier, SourceAtomID


def _fixture():
    region, entry, yes, no, world = RegionID('r'), BlockID('entry'), BlockID('yes'), BlockID('no'), LocationID('world')
    touch, branch, ret_yes, ret_no = (OperationID(name) for name in ('touch', 'branch', 'ret-yes', 'ret-no'))
    state = StateVersionValue(ValueID('before'), region, BlockArgument(entry, 0), world)
    after = StateVersionValue(ValueID('after'), region, OperationResult(touch, 0), world)
    true_state = StateVersionValue(ValueID('yes-state'), region, BlockArgument(yes, 0), world)
    false_state = StateVersionValue(ValueID('no-state'), region, BlockArgument(no, 0), world)
    condition = DataValue(ValueID('condition'), region, LiteralOrigin(True), 'builtins.bool')
    original = SourceReference(SourceAtomID('literal'), '/source/not-executed.py', 'sha256:'+'0'*64, 1, 1, 0, 8)
    literal = DataValue(ValueID('literal'), region,
        ExactLiteralOrigin(PythonLiteral.from_python((1, b'x', None), exact=True), SourceExpression(original)), 'builtins.tuple')
    reference = ReferenceValue(ValueID('reference'), region, LiteralOrigin(None), targets=())
    reference_use = Use(UseID('touch-ref'), reference.id, UseRole.REFERENCE)
    world_use = Use(UseID('touch-world'), state.id, UseRole.STATE_CONTENT)
    update = Operation(touch, 'opaque frame transition', (Behavior.READ, Behavior.WRITE, Behavior.MEMORY),
        (reference_use, world_use), (after.id,), (StateAccess(world, world_use.id, AccessMode.READ_WRITE, after.id),))
    condition_use = Use(UseID('condition-use'), condition.id, UseRole.DATA)
    true_use = Use(UseID('true-world'), after.id, UseRole.STATE_CONTENT)
    false_use = Use(UseID('false-world'), after.id, UseRole.STATE_CONTENT)
    choose = Operation(branch, 'branch', (Behavior.CONTROL,), (condition_use, true_use, false_use),
        terminator=Terminator(TerminatorKind.BRANCH,
            (Successor(yes, (true_use.id,)), Successor(no, (false_use.id,))), condition_use.id))
    exits = []
    for identity, actual in ((ret_yes, true_state), (ret_no, false_state)):
        payload = Use(UseID(identity.value+'-payload'), literal.id, UseRole.DATA)
        state_use = Use(UseID(identity.value+'-world'), actual.id, UseRole.STATE_CONTENT)
        exits.append(Operation(identity, 'return', (Behavior.CONTROL,), (payload, state_use),
            terminator=Terminator(TerminatorKind.RETURN, exit='normal', values=(payload.id, state_use.id))))
    pool, request = ResourceDefinitionID('pool'), ResourceRequirementID('memory')
    graph = ProgramGraph(region, (Region(region, 'root', entry,
        (Block(entry, (state.id,), (touch, branch)), Block(yes, (true_state.id,), (ret_yes,)),
         Block(no, (false_state.id,), (ret_no,))),
        (ExitPort('normal', ExitKind.NORMAL,
            (ValueType(ValueKind.DATA, data_type='builtins.tuple'), ValueType(ValueKind.STATE, location=world))),)),),
        (update, choose, *exits), (state, after, true_state, false_state, condition, literal, reference),
        locations=(StateLocation(world, 'world', stability=Stability.UNKNOWN),),
        resources=(ResourceDefinition(pool, ResourceKind.MEMORY, ResourceRole.MEMORY_POOL, ExternalResource(region, 'memory')),),
        resource_requirements=(ResourceRequirement(request, touch, ResourceKind.MEMORY, ResourceRole.MEMORY_POOL),),
        resource_uses=(ResourceUse(touch, request, pool),), resource_locations=(ResourceLocation(world, pool),))
    assert validate(graph) == ()
    return graph


def _independent_closure():
    records, enums, identifiers, unions = set(), set(), set(), set()
    pending = [ProgramGraph]
    while pending:
        annotation = pending.pop()
        origin, arguments = typing.get_origin(annotation), typing.get_args(annotation)
        if origin in (typing.Union, types.UnionType):
            if arguments not in unions:
                # Ordered wire alternatives are distinct even when Python
                # considers the two Union objects equal.
                unions.add(arguments); pending.extend(arguments)
        elif origin is tuple:
            pending.extend(arg for arg in arguments if arg is not Ellipsis)
        elif annotation in (type(None), bool, int, float, str, bytes):
            continue
        elif isinstance(annotation, type) and issubclass(annotation, Identifier):
            identifiers.add(annotation)
        elif isinstance(annotation, type) and issubclass(annotation, Enum):
            enums.add(annotation)
        elif isinstance(annotation, type) and is_dataclass(annotation):
            if annotation not in records:
                records.add(annotation)
                hints = typing.get_type_hints(annotation)
                pending.extend(hints[field.name] for field in fields(annotation))
        else:
            raise AssertionError(('unreviewed reachable annotation', annotation))
    return records, enums, identifiers, unions


@pytest.mark.parametrize('family', ('closed_catalog_and_valid_graph', 'exact_variants_and_rejections'))
def test_canonical_program_type_grammar(family, monkeypatch):
    from scar.analysis.program_types import (ProgramTypeError, program_type_catalog,
        read_program_type_catalog, validate_program_shape)
    graph = _fixture()
    if family == 'closed_catalog_and_valid_graph':
        catalog = program_type_catalog()
        records, enums, identifiers, unions = _independent_closure()
        assert (len(records), sum(len(fields(record)) for record in records), len(identifiers), len(enums), len(unions)) == (205, 733, 18, 60, 75)
        assert catalog['counts'] == dict(records=205, fields=733, identifiers=18, enums=60,
            enum_members=sum(len(list(enum)) for enum in enums), unions=75)
        expected_keys = {cls.__module__+'.'+cls.__qualname__ for cls in records | enums | identifiers}
        assert {row['key'] for row in catalog['types']} == expected_keys
        assert len(catalog['types']) == len(expected_keys)
        for cls in records:
            row = next(row for row in catalog['types'] if row['key'] == cls.__module__+'.'+cls.__qualname__)
            assert row['kind'] == 'RECORD'
            assert [field['name'] for field in row['fields']] == [field.name for field in fields(cls)]
        assert catalog['claims'] == dict(structural_signature_closed=True,
            operation_semantics_closed=False, graph_realized=False)
        restored = read_program_type_catalog(deepcopy(catalog))
        assert restored == catalog
        before = encode(graph)
        summary = validate_program_shape(graph)
        assert summary['complete'] and summary['visits'] > 0 and summary['records'] > 0
        assert summary['constructor_invariants_checked'] is True
        assert summary['cross_record_invariants_checked'] is False
        assert summary['operation_semantics_checked'] is False
        assert encode(graph) == before
        return

    class ForeignOperation(Operation):
        pass
    class ForeignData(DataValue):
        pass
    foreign_op = ForeignOperation(**{field.name: getattr(graph.operations[0], field.name) for field in fields(Operation)})
    foreign_value = ForeignData(**{field.name: getattr(graph.values[4], field.name) for field in fields(DataValue)})
    variants = (replace(graph, operations=(foreign_op, *graph.operations[1:])),
                replace(graph, values=(*graph.values[:4], foreign_value, *graph.values[5:])))
    for changed in variants:
        # The historical structural gate uses isinstance for these variants.
        assert validate(changed) == ()
        with pytest.raises(ProgramTypeError) as rejected:
            validate_program_shape(changed)
        assert rejected.value.code and rejected.value.path
    class ForeignInt(int):
        pass
    class ForeignStr(str):
        pass
    forged_behavior = str.__new__(Behavior, 'COMPUTE')
    object.__setattr__(forged_behavior, '_name_', 'COMPUTE')
    object.__setattr__(forged_behavior, '_value_', 'COMPUTE')
    assert type(forged_behavior) is Behavior and forged_behavior == Behavior.COMPUTE
    assert forged_behavior is not Behavior.COMPUTE
    mutations = (
        lambda g: object.__setattr__(g, 'root', ValueID('r')),
        lambda g: object.__setattr__(g.root, 'value', ForeignStr('r')),
        lambda g: object.__setattr__(g.root, 'prefix', 'forged-prefix'),
        lambda g: object.__setattr__(g.operations[0], 'behaviors', (forged_behavior,)),
        lambda g: object.__setattr__(g, 'operations', list(g.operations)),
        lambda g: object.__setattr__(g.values[0].origin, 'index', True),
        lambda g: object.__setattr__(g.values[5].origin.literal, 'items', []),
        lambda g: object.__setattr__(g.values[5].origin.literal, 'items', (g.values[5].origin.literal,)),
        lambda g: object.__setattr__(g.values[4].origin, 'value', ForeignInt(1)),
    )
    for mutate in mutations:
        changed = deepcopy(graph); mutate(changed)
        with pytest.raises(ProgramTypeError):
            validate_program_shape(changed)
    with pytest.raises(ProgramTypeError) as stopped:
        validate_program_shape(graph, max_visits=0)
    assert stopped.value.code and stopped.value.path
    # Count actual tuple pulls, not elapsed time. The budget is exhausted upon
    # entering the first Operation; eager child-list construction would pull
    # all 4096 elements before reporting that same frontier.
    import builtins
    import scar.analysis.program_types as program_types
    wide = replace(graph, regions=(), operations=tuple(
        Operation(OperationID('wide-'+str(index)), 'ordinary', ()) for index in range(4096)))
    pulled = []
    def counted_enumerate(values, *args):
        for item in builtins.enumerate(values, *args):
            if values is wide.operations:
                pulled.append(item[0])
            yield item
    with monkeypatch.context() as patch:
        patch.setattr(program_types, 'enumerate', counted_enumerate, raising=False)
        with pytest.raises(ProgramTypeError) as limited:
            validate_program_shape(wide, max_visits=4)
    assert limited.value.code == 'BUDGET_FRONTIER'
    assert limited.value.path == 'graph.operations[0]' and pulled == [0]
    # The only current fixed tuple is a compiler-version declaration. This
    # extra shape probe makes no claim about its cross-record frame/source links.
    from scar.ir.program.ids import ControlScopeID, EnvironmentInterfaceID
    from scar.ir.program.source_subjects import (FrameKind, FunctionFrameABI,
        SourceCompilationCodeRef, SourceCompilationFrameRoot)
    from scar.ir.v2.ids import OperationDefinitionID
    source = graph.values[5].origin.definition.source
    declaration = SourceCompilationCodeRef(source, OperationDefinitionID('function'), (1,),
        'pycode-v2:'+'1'*64, 'pycode-v2:'+'0'*64, 'cpython', (3, 14, 7),
        '3.14.7', 'cpython-314', 'exec', 0, True, 0)
    frame = SourceCompilationFrameRoot(ControlScopeID('declared-frame'), FrameKind.FUNCTION, declaration,
                                      FunctionFrameABI(EnvironmentInterfaceID('declared-environment')))
    declared = replace(graph, frame_roots=(frame,))
    assert validate_program_shape(declared)['cross_record_invariants_checked'] is False
    changed = deepcopy(declared); object.__setattr__(changed.frame_roots[0].code, 'compiler_version', (3, 14))
    with pytest.raises(ProgramTypeError):
        validate_program_shape(changed)
    catalog = program_type_catalog()
    changed = deepcopy(catalog); changed['extra'] = None
    with pytest.raises((ProgramTypeError, ValueError, TypeError)):
        read_program_type_catalog(changed)

    changed = deepcopy(catalog)
    record = next(row for row in changed['types'] if row['kind'] == 'RECORD' and row['fields'])
    record['fields'].pop()
    changed['counts']['fields'] -= 1
    payload = {key: value for key, value in changed.items() if key != 'content_sha256'}
    changed['content_sha256'] = sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'),
        ensure_ascii=True, allow_nan=False).encode('ascii')).hexdigest()
    with pytest.raises((ProgramTypeError, ValueError, TypeError)):
        read_program_type_catalog(changed)
