"""Declared literal interfaces on original producers; no runtime recovery."""
from dataclasses import replace
import hashlib

from scar.ir.literals import PythonLiteral, literal_builtin_type
from scar.ir.program.ids import BlockID, LocationID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.literal_sources import CodeConstant, ExactLiteralOrigin, UnlocatedLiteral
from scar.ir.program.model import (
    AccessMode, Behavior, Block, DataValue, ExitKind, ExitPort, LiteralEvaluation,
    LiteralOrigin, Operation, OperationResult, ProgramGraph, ReferenceValue, Region,
    StateAccess, Terminator, TerminatorKind, Use, UseRole, ValueKind, ValueType,
)
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.execution.calls import CallActivation
from scar.ir.execution.content import ObjectIdentity, ObjectRef, ValueDenotation
from scar.ir.execution.common import Unresolved
from scar.ir.execution.ids import CallActivationID, DenotationID
from scar.ir.execution.snapshot import external_artifact, snapshot_for
from scar.ir.v2.evidence import EvidenceEndpoint, EvidenceGraph, EvidenceNodeKind
from scar.ir.v2.ids import ObjectID
from tests.fixtures.execution_call_graphs import _model
from tests.fixtures.execution_paths import declared_path
from tests.fixtures.program_graphs import loop_state_program, shared_body_calls_program


def code_definition(index=0):
    artifact = ProviderArtifact('memory:declared-code-record', hashlib.sha256(b'{}').hexdigest(),
                                2, 'fixture.code-record')
    return CodeConstant(ProviderFactReference(artifact, '/code/root'), index)


def _with_producer(program, block_id, state_id, location, argument, *, kind, contents, definition):
    site = OperationResult(OperationID('literal.make'), 0)
    value = (ReferenceValue(ValueID('literal.object'), program.root if block_id == 'body'
                            else RegionID('callee'), site) if kind == 'reference'
             else DataValue(ValueID('literal.object'), program.root if block_id == 'body'
                            else RegionID('callee'), site, 'builtins.int'))
    make = Operation(site.operation, 'declared literal evaluation',
        (Behavior.MEMORY, Behavior.READ, Behavior.COMPUTE),
        (Use(UseID('literal.left'), ValueID(argument)),
         Use(UseID('literal.right'), ValueID(argument)),
         Use(UseID('literal.world'), ValueID(state_id), UseRole.STATE_CONTENT)),
        (value.id,), (StateAccess(LocationID(location), UseID('literal.world'), AccessMode.READ),),
        effects_complete=False)
    role = UseRole.REFERENCE if kind == 'reference' else UseRole.DATA
    observe = Operation(OperationID('literal.observe'), 'ordered identity/content observation',
        (Behavior.READ, Behavior.COMPUTE),
        (Use(UseID('literal.observe.first'), value.id, role),
         Use(UseID('literal.observe.second'), value.id, role)), effects_complete=False)
    regions = tuple(replace(region, blocks=tuple(replace(block,
        operations=(make.id, observe.id, *block.operations)) if block.id == BlockID(block_id)
        else block for block in region.blocks)) for region in program.regions)
    return replace(program, regions=regions, values=(*program.values, value),
        operations=(*program.operations, make, observe),
        literal_evaluations=(LiteralEvaluation(site, contents, definition),)), site


def literal_loop_execution(*, kind='reference', contents=None, definition=None):
    contents = (PythonLiteral.from_python('same literal', exact=True) if kind == 'reference'
                else PythonLiteral.from_python(42, exact=True)) if contents is None else contents
    program, site = _with_producer(loop_state_program(), 'body', 'body.state', 'counter', 'limit',
        kind=kind, contents=contents, definition=code_definition() if definition is None else definition)
    path = ((BlockID('loop.entry'), 0), (BlockID('header'), 0), (BlockID('body'), 0),
            (BlockID('header'), 0), (BlockID('body'), 0), (BlockID('header'), 1),
            (BlockID('exit'), None))
    return program, declared_path(program, path), site


def literal_calls_execution(*, kind='reference'):
    contents = PythonLiteral.from_python('same literal' if kind == 'reference' else 42, exact=True)
    program, site = _with_producer(shared_body_calls_program(), 'callee.entry', 'body.initial',
        'calls', 'body.input', kind=kind, contents=contents, definition=code_definition())
    model, scopes, source = _model(program, (
        (program.root, ((BlockID('caller.entry'), None),), 'caller'),
        (RegionID('callee'), ((BlockID('callee.entry'), None),), 'child.1'),
        (RegionID('callee'), ((BlockID('callee.entry'), None),), 'child.2')))
    caller_ops = scopes[0][2]
    links = tuple(CallActivation(CallActivationID('literal.call.'+str(n)),
        caller_ops[OperationID('call'+str(n))], scope[0], scope[1][0],
        scope[2][OperationID('callee.done')], source) for n, scope in enumerate(scopes[1:], 1))
    return program, replace(model, call_activations=links), site


def object_denotations(program, model, *, same=False):
    """Existing scoped object declarations, never payload-derived identities."""
    graph = EvidenceGraph()
    values = tuple(row for row in model.values if row.value == ValueID('literal.object'))
    objects = tuple(ObjectID('same' if same else 'object.'+str(i)) for i in range(len(values)))
    for object_id in set(objects):
        graph.register_external(EvidenceEndpoint(EvidenceNodeKind.OBJECT, object_id))
    artifact = external_artifact(graph, 'memory:literal-object-declarations')
    point = model.activations[0].entry
    denotations = tuple(ValueDenotation(DenotationID('literal.'+str(i)), value.id,
        ObjectIdentity(ObjectRef(artifact, object_id)),
        Unresolved('declared object association; no native capture proof', point), model.runs[0].source)
        for i, (value, object_id) in enumerate(zip(values, objects, strict=True)))
    return replace(model, denotations=denotations), {artifact.sha256: graph}


def exact_data_execution(value):
    """Reuse the original path builder, then refine abstract content only."""
    root, block, done = RegionID('exact'), BlockID('exact.entry'), OperationID('exact.return')
    constant = DataValue(ValueID('content'), root, LiteralOrigin(3), 'builtins.int')
    operation = Operation(done, 'return abstract content', (Behavior.CONTROL,),
        (Use(UseID('return.content'), constant.id),),
        terminator=Terminator(TerminatorKind.RETURN, exit='normal', values=(UseID('return.content'),)))
    region = Region(root, 'abstract content', block, (Block(block, (), (done,)),),
        (ExitPort('normal', ExitKind.NORMAL, (ValueType(ValueKind.DATA, 'builtins.int'),)),))
    base = ProgramGraph(root, (region,), (operation,), (constant,), ())
    model = declared_path(base, ((block, None),))
    literal = PythonLiteral.from_python(value, exact=True)
    kind = literal_builtin_type(literal)
    data_type = kind.__module__+'.'+kind.__qualname__
    exact = replace(constant, origin=ExactLiteralOrigin(literal, UnlocatedLiteral()), data_type=data_type)
    region = replace(region, exits=(ExitPort('normal', ExitKind.NORMAL,
        (ValueType(ValueKind.DATA, data_type),)),))
    program = replace(base, regions=(region,), values=(exact,))
    return program, replace(model, snapshot=snapshot_for(program))


def literal_resume_execution(edge=0):
    """Only original saved ports carry a produced reference across a cut."""
    from tests.fixtures.program_resumption_graphs import resumption_program
    program = resumption_program()
    site = OperationResult(OperationID('literal.before.cut'), 0)
    content = DataValue(ValueID('literal.cut.content'), program.root, LiteralOrigin(3), 'builtins.int')
    reference = ReferenceValue(ValueID('literal.cut.object'), program.root, site)
    make = Operation(site.operation, 'object evaluation before suspension', (Behavior.MEMORY, Behavior.COMPUTE),
        (Use(UseID('literal.cut.input'), ValueID('resume.x'), UseRole.REFERENCE),
         Use(UseID('literal.cut.content.use'), content.id)), (reference.id,), effects_complete=False)
    observe = Operation(OperationID('literal.after.cut'), 'observe original saved reference and abstract content',
        (Behavior.READ, Behavior.COMPUTE),
        (Use(UseID('literal.cut.saved'), ValueID('resume.value.x' if edge == 0 else 'resume.packet.x'), UseRole.REFERENCE),
         Use(UseID('literal.cut.abstract'), content.id)), effects_complete=False)
    operations = tuple(replace(op, uses=tuple(replace(use, value=reference.id)
        if use.id in (UseID('resume.suspend.export'), UseID('resume.suspend.x')) else use
        for use in op.uses)) if op.id == OperationID('resume.suspend') else op
        for op in program.operations)
    landing = BlockID('resume.value' if edge == 0 else 'resume.packet')
    regions = tuple(replace(region, blocks=tuple(replace(block,
        operations=(*block.operations[:2], make.id, *block.operations[2:])) if block.id == BlockID('resume.entry')
        else replace(block, operations=(block.operations[0], observe.id, *block.operations[1:])) if block.id == landing else block
        for block in region.blocks)) for region in program.regions)
    program = replace(program, values=(*program.values, content, reference), regions=regions,
        operations=(*operations, make, observe), literal_evaluations=(LiteralEvaluation(site,
            PythonLiteral.from_python('saved reference', exact=True), code_definition()),))
    model = declared_path(program, ((BlockID('resume.entry'), edge), (landing, None)))
    exact = replace(content, origin=ExactLiteralOrigin(PythonLiteral.from_python(3, exact=True)))
    program = replace(program, values=tuple(exact if value.id == content.id else value for value in program.values))
    return program, replace(model, snapshot=snapshot_for(program)), site


def two_domain_literal_invoke(raised=False):
    """Two state domains plus a leading forwarded reference, no fake result."""
    from scar.ir.program.model import BlockArgument, CompletionResult, StateLocation, StateVersionValue
    from tests.fixtures.program_literals import literal_program
    program, details = literal_program(exact=False)
    location = LocationID('literal.second.world')
    initial = StateVersionValue(ValueID('second.initial'), program.root, BlockArgument(BlockID('entry'), 2), location)
    updated = StateVersionValue(ValueID('second.updated'), program.root, OperationResult(OperationID('direct'), 3), location)
    normal = StateVersionValue(ValueID('second.normal'), program.root, BlockArgument(BlockID('normal'), 4), location)
    failure = StateVersionValue(ValueID('second.failure'), program.root, BlockArgument(BlockID('failure'), 2), location)
    forwarded = ReferenceValue(ValueID('normal.forwarded'), program.root, BlockArgument(BlockID('normal'), 0))
    values = tuple(replace(value, origin=replace(value.origin, index=value.origin.index+1))
        if type(value.origin) is BlockArgument and value.origin.block == BlockID('normal') else value
        for value in program.values)
    state_type = ValueType(ValueKind.STATE, location=location)
    operations = []
    for op in program.operations:
        if op.id == OperationID('direct'):
            before = Use(UseID('second.direct.before'), initial.id, UseRole.STATE_CONTENT)
            op = replace(op, uses=(*op.uses, before), results=(*op.results, updated.id),
                accesses=(*op.accesses, StateAccess(location, before.id, AccessMode.READ_WRITE, updated.id)))
        elif op.id == OperationID('invoke'):
            use = Use(UseID('second.invoke.before'), updated.id, UseRole.STATE_CONTENT)
            forward_use = Use(UseID('invoke.forward'), ValueID('constructed'), UseRole.REFERENCE)
            normal_edge, raise_edge = op.terminator.successors
            normal_edge = replace(normal_edge, arguments=(forward_use.id, *normal_edge.arguments, CompletionResult(3)))
            raise_edge = replace(raise_edge, arguments=(*raise_edge.arguments, CompletionResult(2)))
            op = replace(op, uses=(*op.uses, forward_use, use), invoke_arguments=(*op.invoke_arguments, use.id),
                completions=tuple(replace(signature, types=(*signature.types, state_type)) for signature in op.completions),
                terminator=replace(op.terminator, successors=(normal_edge, raise_edge)))
        elif op.id in (OperationID('return'), OperationID('raise')):
            state = normal if op.id == OperationID('return') else failure
            use = Use(UseID('second.'+op.id.value), state.id, UseRole.STATE_CONTENT)
            op = replace(op, uses=(*op.uses, use), terminator=replace(op.terminator,
                values=(*op.terminator.values, use.id)))
        operations.append(op)
    regions = tuple(replace(region, blocks=tuple(replace(block,
        arguments=(*block.arguments, initial.id)) if block.id == BlockID('entry') else
        replace(block, arguments=(forwarded.id, *block.arguments, normal.id)) if block.id == BlockID('normal') else
        replace(block, arguments=(*block.arguments, failure.id)) for block in region.blocks),
        exits=tuple(replace(exit, types=(*exit.types, state_type)) for exit in region.exits)) for region in program.regions)
    program = replace(program, regions=regions, operations=tuple(operations),
        values=(*values, initial, updated, normal, failure, forwarded),
        locations=(*program.locations, StateLocation(location, 'independent second carrier')))
    model = declared_path(program, ((BlockID('entry'), int(raised)),
        (BlockID('failure' if raised else 'normal'), None)))
    return program, model, details
