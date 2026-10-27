"""Small A contract check: synthetic declarations, never source/runtime proof."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path

from scar.ir.program import codec
from scar.ir.program.call_edges import CapturedCode
from scar.ir.program.control import ControlScopeKind
from scar.ir.program.environments import EnvironmentInterface, EnvironmentMember, EnvironmentRole, FunctionEntryLayout
from scar.ir.program.ids import EnvironmentInterfaceID, ValueID
from scar.ir.program.model import BlockArgument, LiteralOrigin, ReferenceValue
from scar.ir.program.module_entries import ModuleUnitSource as ReexportedModuleUnitSource, MODULE_RECORD_TAGS
from scar.ir.program.source_subjects import FrameKind, FrameRoot, FunctionFrameABI, MappingFramePorts, ModuleUnitSource
from scar.ir.program.validation import require_valid, validate
from scar.ir.record_codec import decode, encode
from scar.ir.semantics_v2 import SourceSnapshot
from scar.ir.v2.ids import OperationDefinitionID
from tests.fixtures.program_control_graphs import shared_pending_graph

ROOT = Path(__file__).resolve().parents[3]
DECLARED = CapturedCode('pycode-v2:' + '0' * 64, '/synthetic/module.py', '<module>', 1, 0, ())
UNIT = ModuleUnitSource(SourceSnapshot(DECLARED.filename, 'sha256:' + '1' * 64),
                        '/synthetic', OperationDefinitionID('synthetic.module'))


def mapping_graph():
    graph = shared_pending_graph()
    region = graph.regions[0]
    entry = next(block for block in region.blocks if block.id == region.entry)
    arguments = entry.arguments[1:]  # Only a synthetic condition becomes a literal.
    rewritten = []
    for value in graph.values:
        if value.id == entry.arguments[0]:
            value = replace(value, origin=LiteralOrigin(True))
        elif isinstance(value.origin, BlockArgument) and value.origin.block == entry.id:
            value = replace(value, origin=replace(value.origin, index=value.origin.index - 1))
        rewritten.append(value)
    region = replace(region, blocks=tuple(replace(block, arguments=arguments)
        if block.id == entry.id else block for block in region.blocks))
    original_root = next(scope for scope in graph.control_scopes if scope.parent is None)
    root_scope = replace(original_root, kind=ControlScopeKind.FRAME, source=UNIT)
    abi = MappingFramePorts(*arguments[:3], (), arguments[3])
    return replace(graph, regions=(region,), values=tuple(rewritten),
        control_scopes=tuple(root_scope if scope.id == root_scope.id else scope
                             for scope in graph.control_scopes),
        frame_roots=(FrameRoot(root_scope.id, FrameKind.MODULE, DECLARED, abi),))


def with_extra_reference(graph, identity):
    region = graph.regions[0]
    entry = next(block for block in region.blocks if block.id == region.entry)
    world = graph.frame_roots[0].entry.world
    index = entry.arguments.index(world)
    port = ReferenceValue(ValueID(identity), region.id, BlockArgument(entry.id, index))
    arguments = (*entry.arguments[:index], port.id, *entry.arguments[index:])
    values = tuple(replace(value, origin=replace(value.origin, index=value.origin.index + 1))
        if isinstance(value.origin, BlockArgument) and value.origin.block == entry.id
        and value.origin.index >= index else value for value in graph.values)
    return replace(graph, values=(*values, port), regions=(replace(region, blocks=tuple(
        replace(block, arguments=arguments) if block.id == entry.id else block
        for block in region.blocks)),)), port.id


def run_checks():
    passed, measurements = [], []

    def check(name, predicate):
        if not predicate:
            raise AssertionError(name)
        passed.append(name)

    def invalid(name, graph, code):
        check(name, code in {issue.code for issue in validate(graph)})

    def rejects(name, document, text):
        try:
            codec.loads(json.dumps(document))
        except (ValueError, TypeError) as error:
            check(name, text in str(error))
        else:
            raise AssertionError(name + ': accepted malformed wire')

    check('ModuleUnitSource is the identical reexported class', ReexportedModuleUnitSource is ModuleUnitSource)
    unit_wire = encode(UNIT, record_tags=MODULE_RECORD_TAGS)
    check('old ModuleUnitSource wire unchanged', unit_wire == {
        'snapshot': encode(UNIT.snapshot), 'namespace_root': '/synthetic',
        'initializer': encode(UNIT.initializer), 'source_kind': 'MODULE_UNIT'})
    check('old ModuleUnitSource tagged decode identity', decode(ModuleUnitSource, unit_wire,
        record_tags=MODULE_RECORD_TAGS) == UNIT)
    graph = mapping_graph()
    require_valid(graph)
    wire = codec.dumps(graph)
    document = json.loads(wire)
    check('module FRAME ordinary core29 roundtrip', document['schema_version'] == 29
          and codec.loads(wire) == graph and codec.dumps(codec.loads(wire)) == wire)
    check('original C0 packet/pending/cleanup-scope retained',
          graph.exception_packets == shared_pending_graph().exception_packets
          and graph.pending_completions == shared_pending_graph().pending_completions
          and graph.control_scopes[1:] == shared_pending_graph().control_scopes[1:])
    measurements.append({'label': 'SYNTHETIC_MODULE_C0', 'bytes': len(wire.encode()),
                         'sha256': hashlib.sha256(wire.encode()).hexdigest(),
                         'operations': len(graph.operations), 'regions': len(graph.regions)})
    invalid('missing root entry authority rejected', replace(graph, frame_roots=()), 'frame_root_missing')
    root = graph.frame_roots[0]
    invalid('missing mapping port rejected', replace(graph, frame_roots=(replace(root,
        entry=replace(root.entry, world=ValueID('synthetic.absent-world'))),)), 'frame_root_port')
    invalid('logical code path mismatch rejected', replace(graph, frame_roots=(replace(root,
        code=replace(root.code, filename='/different/module.py')),)), 'frame_root_code')
    wrong_subject = shared_pending_graph().control_scopes[0].source
    invalid('module frame with a SourceAtom subject rejected', replace(graph,
        control_scopes=(replace(graph.control_scopes[0], source=wrong_subject), *graph.control_scopes[1:])),
        'frame_root_subject')
    for version in (6, 28):
        downgraded = dict(document, schema_version=version)
        downgraded.pop('frame_roots')
        fields = codec._V6_GRAPH_FIELDS if version == 6 else codec._V28_GRAPH_FIELDS
        downgraded = {key: value for key, value in downgraded.items()
                      if key in fields or key in ('schema', 'schema_version')}
        rejects('old core' + str(version) + ' rejects FRAME capability', downgraded, 'historical schema')
    legacy = json.loads(codec.dumps(shared_pending_graph()))
    legacy['control_scopes'][0]['source'] = encode(UNIT)  # Untagged union smuggling also fails.
    rejects('old source union cannot smuggle ModuleUnitSource', legacy, 'historical schema')
    malformed = json.loads(wire)
    malformed['frame_roots'][0]['entry']['entry_kind'] = 'UNRECOGNIZED_ABI'
    rejects('closed ABI discriminator rejects unknown', malformed, 'typed record')

    # CLASS has the mapping shape, but no module implicit-None/empty-cell rule.
    class_graph, cell = with_extra_reference(graph, 'synthetic.class-cell')
    class_root = replace(root, kind=FrameKind.CLASS,
                         code=replace(root.code, filename=wrong_subject.path, qualname='SyntheticClass'),
                         entry=replace(root.entry, closure_cells=(cell,)))
    class_graph = replace(class_graph,
        control_scopes=(replace(class_graph.control_scopes[0], source=wrong_subject), *class_graph.control_scopes[1:]),
        frame_roots=(class_root,))
    check('class declaration retains cell ports and arbitrary normal payload',
          codec.loads(codec.dumps(class_graph)) == class_graph)

    # FUNCTION references the existing environment/formal ABI, never copies it.
    function_graph, default = with_extra_reference(graph, 'synthetic.defaults')
    function_graph, kwdefault = with_extra_reference(function_graph, 'synthetic.kwdefaults')
    environment_id = EnvironmentInterfaceID('synthetic.function-environment')
    refs = (root.entry.locals_namespace, root.entry.globals_namespace, root.entry.builtins_namespace,
            default, kwdefault)
    roles = (EnvironmentRole.FUNCTION_OBJECT, EnvironmentRole.GLOBALS_NAMESPACE,
             EnvironmentRole.BUILTINS_NAMESPACE, EnvironmentRole.DEFAULTS, EnvironmentRole.KEYWORD_DEFAULTS)
    environment = EnvironmentInterface(environment_id, graph.root, OperationDefinitionID('synthetic.function'),
                                       tuple(EnvironmentMember(role, port) for role, port in zip(roles, refs)))
    function_root = replace(root, kind=FrameKind.FUNCTION,
        code=replace(root.code, filename=wrong_subject.path, qualname='synthetic_function'),
        entry=FunctionFrameABI(environment_id))
    function_graph = replace(function_graph, environments=(environment,),
        function_entries=(FunctionEntryLayout(environment_id, ()),), frame_roots=(function_root,),
        control_scopes=(replace(function_graph.control_scopes[0], source=wrong_subject), *function_graph.control_scopes[1:]))
    check('function frame references the existing ENV partition', codec.loads(codec.dumps(function_graph)) == function_graph)
    invalid('dangling function ENV reference rejected', replace(function_graph,
        frame_roots=(replace(function_root, entry=FunctionFrameABI(EnvironmentInterfaceID('absent'))),)),
        'frame_root_environment')

    for version in (2, 6, 9):
        path = ROOT / ('tests/fixtures/program_graph_v' + str(version) + '_frozen.json')
        original = path.read_bytes()
        decoded = codec.loads(original.decode())
        canonical = codec.dumps(decoded).encode()
        check('frozen legacy core' + str(version) + ' exact bytes', canonical == original)
        check('frozen legacy core' + str(version) + ' has no frame_roots field',
              'frame_roots' not in json.loads(original))
        measurements.append({'label': 'OLD_CORE_' + str(version), 'path': str(path),
                             'bytes': len(original), 'sha256': hashlib.sha256(original).hexdigest()})
    return {'status': 'TYPED_A_CONTRACT_CHECK_PASS', 'checks': passed, 'measurements': measurements,
            'scope': 'SYNTHETIC_DECLARATIONS_AND_RETAINED_CORE_WIRE_ONLY',
            'source_correspondence': 'NOT_EVALUATED', 'code_witness': 'NOT_EVALUATED',
            'runtime_activation': 'NOT_EVALUATED', 'namespace_contents_or_alias': 'NOT_EVALUATED',
            'module_body_expansion': 'NOT_ATTEMPTED', 'try_source_producer': 'NOT_IMPLEMENTED'}


if __name__ == '__main__':
    import sys
    output = Path(sys.argv[1])
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(output)
    result = run_checks()
    output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'status': result['status'], 'checks': len(result['checks']), 'output': str(output)}))
