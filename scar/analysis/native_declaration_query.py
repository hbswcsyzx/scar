"""A connected, read-only view of original native interfaces and input facts."""
from __future__ import annotations

from pathlib import Path
import json
import time

from scar.ir.execution.fragment_relations import stable_key, need
from scar.ir.record_codec import encode


def native_declaration_graph(view, *, source_ordinal, metadata_ports=()):
    """Follow exact references without adding a second operation/value graph.

    The caller supplies a normally read declaration view. Observed source
    ports, static completion interfaces and input metadata remain distinct.
    """
    from scar.ir.program.model import StateVersionValue

    need(type(source_ordinal) is int and source_ordinal >= 0, 'original source ordinal required')
    selected = [item for item in view.occurrences
                if item.completion.point.source.locator == f'#/nodes/{source_ordinal}']
    need(len(selected) == 1, 'source ordinal does not select one original occurrence in this fragment')
    original = selected[0]
    boundaries = {b.id: b for b in view.program.native_boundaries}
    operations = {o.id: o for o in view.program.operations}
    values = {v.id: v for v in view.program.values}
    invocation = next(o for o in view.execution.operations if o.id == original.invocation)
    operation, boundary = operations[invocation.operation], boundaries[original.boundary]
    denotations = {d.basis: d for d in view.execution.denotations}
    uses = [u for u in view.execution.uses if u.operation == original.invocation]
    nodes, edges = {}, []

    def node(kind, reference):
        key = kind + ':' + stable_key(reference)
        payload = {'kind': kind, 'reference': encode(reference)}
        need(key not in nodes or nodes[key] == payload, 'native graph reference key collision')
        nodes[key] = payload
        return key

    def actual(kind, reference):
        return node(kind, {'artifact': original.execution, 'id': reference})

    def static(kind, reference):
        return node(kind, {'snapshot': original.snapshot, 'reference': reference})

    def edge(kind, source, target, qualification, origin):
        edges.append({'kind': kind, 'source': source, 'target': target,
                      'qualification': qualification, 'origin': encode(origin)})

    call = actual('OPERATION_OCCURRENCE', original.invocation)
    source = node('SOURCE_FACT', original.completion.point.source)
    native = node('NATIVE_INSTANCE', original.native)
    definition = node('NATIVE_DEFINITION', original.definition)
    core = static('STATIC_OPERATION', operation.id)
    signature = static('NATIVE_BOUNDARY', boundary.id)
    region = static('PROGRAM_REGION', boundary.region)
    edge('SOURCE_OBSERVATION', source, native, 'ORIGINAL_PROVIDER_SOURCE', original.native)
    edge('CANONICAL_OCCURRENCE', native, call, 'ORIGINAL_ORDERED_PORT_INTERFACE', original.ports)
    edge('INSTANCE_DEFINITION', native, definition, 'ORIGINAL_NATIVE_DEFINITION', original.definition)
    edge('INSTANCE_OF', call, core, 'CANONICAL_PROGRAM_OPERATION', original.snapshot)
    edge('USES_INTERFACE', call, signature, 'CANONICAL_NATIVE_BOUNDARY', original.snapshot)
    edge('REGION_OPERATION', region, core, 'STATIC_MEMBERSHIP', original.snapshot)
    edge('BOUNDARY_REGION', signature, region, 'STATIC_INTERFACE', original.snapshot)
    for use in uses:
        value = actual('VALUE_OCCURRENCE', use.value)
        current = actual('USE', {'operation': use.operation, 'use': use.use})
        edge('VALUE_USED_AT', value, current, 'ORIGINAL_CANONICAL_INPUT', original.execution)
        edge('OPERATION_ARGUMENT', current, call, 'ORIGINAL_CANONICAL_INPUT', original.execution)
        formal_use = next(u for u in operation.uses if u.id == use.use)
        nodes[current]['role'] = formal_use.role.value
        formal_value = values[formal_use.value]
        if type(formal_value) is StateVersionValue:
            edge('STATE_INPUT_LOCATION', static('STATE_LOCATION', formal_value.location), value,
                 'ABSTRACT_STATE_INPUT_NOT_CONTENT_SNAPSHOT', original.snapshot)
    port_nodes = {}
    for port in original.inputs:
        denotation = denotations[port]
        current = actual('NATIVE_INPUT', port)
        port_nodes[port] = current
        value = actual('VALUE_OCCURRENCE', denotation.value)
        formal = static('ENTRY_PORT', boundary.inputs[port.position].port)
        fact = node('SOURCE_FACT', denotation.source)
        edge('NATIVE_PORT_VALUE', current, value, 'ORIGINAL_CANONICAL_INPUT', denotation.source)
        edge('ACTUAL_FORMAL_PORT', current, formal, 'ORIGINAL_ORDERED_INTERFACE', original.snapshot)
        edge('INPUT_SOURCE_OBSERVATION', fact, current, 'ORIGINAL_PROVIDER_SOURCE', denotation.source)
    for slot, fact in zip(boundary.outputs, original.output_sources, strict=True):
        output = static('EXIT_PORT', slot.port)
        edge('DECLARED_OUTPUT', call, output, 'COMPLETION_UNSELECTED', original.snapshot)
        edge('OUTPUT_SOURCE_MAPPING', node('SOURCE_FACT', fact), output,
             'OBSERVED_PORT_TO_STATIC_INTERFACE_ONLY', fact)
    for slot in boundary.core_outputs:
        edge('DECLARED_STATE_SUCCESSOR', call, static('EXIT_PORT', slot.port),
             'COMPLETION_UNSELECTED_NOT_OBSERVED_STATE_WRITE', original.snapshot)
    joined, gaps = [], []
    for port in metadata_ports:
        if port.invocation != original.invocation:
            continue
        need(port.input in port_nodes and denotations[port.input].value == port.value,
             'metadata join selects another original input occurrence')
        joined.append(encode(port))
        if port.metadata_leaf is None:
            gaps.append({'input': encode(port.input), 'native_path': list(port.native_path),
                         'reason': port.status})
            continue
        metadata = node('METADATA_OBSERVATION', port.metadata_leaf)
        edge('SAME_NATIVE_INPUT_METADATA', port_nodes[port.input], metadata,
             'EXACT_ETO_SOURCE_AND_BOXED_PATH', port.original_input)
        if port.provider_epoch is not None:
            edge('PROVIDER_EPOCH_REFERENCE', metadata, node('SOURCE_FACT', port.provider_epoch),
                 'ORIGINAL_PROVIDER_EPOCH_REFERENCE_NOT_LIFETIME_OR_CONTENT_PROOF', port.metadata_leaf)
    return {'schema': 'scar.program-query', 'schema_version': 1, 'query': 'NATIVE_INTERFACE',
        'source_ordinal': source_ordinal, 'snapshot': encode(original.snapshot),
        'execution': encode(original.execution), 'nodes': nodes, 'edges': edges,
        'metadata_ports': joined, 'metadata_gaps': gaps,
        'metadata_join_requested': bool(metadata_ports),
        'completion': encode(original.completion), 'effects_complete': operation.effects_complete,
        'node_keys': 'QUERY_LOCAL_ONLY; original typed references own identity',
        'actual_normal_completion_established': False, 'content_equality_established': False,
        'resource_ready_established': False, 'whole_program_complete': False,
        'transformation_authorized': False}


def query_native_declaration(fragment, *, source_ordinal, metadata_navigation=None,
        max_input_bytes=256_000_000, max_seconds=180):
    from scar.analysis.native_declaration_interfaces import NativeDeclarationBudget, read_native_declaration_fragment

    started = time.monotonic()
    view = read_native_declaration_fragment(fragment, budget=NativeDeclarationBudget(
        max_input_bytes=max_input_bytes, max_seconds=max_seconds))
    ports, metadata_costs = (), None
    if metadata_navigation is not None:
        from scar.analysis.native_declaration_inputs import NativeDeclarationInputBudget, NativeDeclarationInputSession
        remaining = max_seconds - (time.monotonic() - started)
        need(remaining >= 1, 'native interface query wall budget exhausted')
        with NativeDeclarationInputSession(metadata_navigation,
                budget=NativeDeclarationInputBudget(max_seconds=int(remaining))) as session:
            ports = session.join_fragment(view)
            metadata_costs = dict(session.measurements)
    result = native_declaration_graph(view, source_ordinal=source_ordinal, metadata_ports=ports)
    result['metadata_join_requested'] = metadata_navigation is not None
    result['costs'] = {'native_fragment': view.measurements, 'input_metadata': metadata_costs,
                       'total_elapsed_seconds': time.monotonic() - started}
    return result


def query_native_interface_cli(args):
    from scar.ir.program.providers import ProviderArtifact

    def artifact(path, digest, schema):
        path = Path(path).absolute()
        return ProviderArtifact(str(path), digest, path.stat().st_size, schema)

    need((args.metadata_navigation is None) == (args.metadata_sha256 is None),
         'metadata navigation and SHA must be supplied together')
    navigation = None if args.metadata_navigation is None else artifact(
        args.metadata_navigation, args.metadata_sha256, 'scar.native-input-port-navigation')
    result = query_native_declaration(artifact(args.fragment, args.sha256, 'scar.native-declaration-fragment'),
        source_ordinal=args.source_ordinal, metadata_navigation=navigation,
        max_input_bytes=args.max_input_bytes, max_seconds=args.max_seconds)
    payload = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    if args.out:
        with Path(args.out).open('x', encoding='utf-8') as stream:
            stream.write(payload)
    else:
        print(payload, end='')
    return 0


def register_native_declaration_query(sub):
    parser = sub.add_parser('query-native-interface',
        help='follow one canonical native operation, its ordered ports/state and optional original input metadata')
    for name in ('fragment', 'sha256'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--source-ordinal', type=int, required=True, help='original ETO node ordinal, not a node ID')
    parser.add_argument('--metadata-navigation', help='existing input navigation manifest; joins use one metadata-row pass')
    parser.add_argument('--metadata-sha256')
    parser.add_argument('--max-input-bytes', type=int, default=256_000_000, help='canonical fragment input budget')
    parser.add_argument('--max-seconds', type=int, default=180, help='combined native/metadata wall ceiling')
    parser.add_argument('--out', help='fresh JSON graph view; otherwise stdout')
    parser.set_defaults(func=query_native_interface_cli)
