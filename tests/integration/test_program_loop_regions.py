"""Source loops select original work and retain their ports, not invariance."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest


def test_source_loop_constructs_keep_nested_exits_and_internal_header_arguments(tmp_path):
    from scar.analysis.program_dependency_session import ProgramDependencyBudget, ProgramDependencySession
    from scar.analysis.program_regions import BoundaryKnowledge
    from scar.ir.program.dependencies import DependencyKind as K, DependencyPoint as P, GraphNamespace
    from scar.ir.program.ids import UseID
    from scar.ir.program.model import BlockArgument, StateVersionValue
    from scar.ir.semantics_v2 import Opcode

    source = tmp_path / 'source'
    source.mkdir()
    program = source / 'program.py'
    text = ('def scan(items, other, x, before, step, after):\n'
        '    outside_before = before(x)\n'
        '    for item in items:\n'
        '        x[0] = item\n'
        '        if item:\n'
        '            continue\n'
        '        for nested in other:\n'
        '            if nested:\n'
        '                break\n'
        '            if x:\n'
        '                return step(x)\n'
        '            step(nested)\n'
        '        step(item)\n'
        '    outside_after = after(x)\n'
        '    return outside_after\n')
    program.write_text(text)
    original_source = hashlib.sha256(program.read_bytes()).hexdigest()
    model = tmp_path / 'model'
    built = subprocess.run([sys.executable, '-B', '-m', 'scar.cli', 'static', str(source),
        '--out', str(model), '--phase', 'bodies', '--jobs', '1'],
        cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True)
    assert built.returncode == 0, built.stdout + built.stderr
    # This subprocess only built SCAR's static model; scan() was never run.
    original_manifest = (model / 'manifest.json').read_bytes()
    assert json.loads(original_manifest)['target_executed'] is False

    with ProgramDependencySession(model, budget=ProgramDependencyBudget(max_seconds=180)) as session:
        namespace, = session.select_bodies(file=str(program), entry='<module>.scan', kind='FUNCTION')
        qualified = GraphNamespace.from_source(namespace)
        body = session.load_body(namespace)
        index = session.index(qualified)
        graph = session.graph()
        constructs = session.loop_constructs(namespace)
        assert len(constructs) == 2
        outer, inner = sorted(constructs, key=lambda view: view.template.loop.source.start_line)
        assert inner.template.lexical_parent == outer.template.loop.source
        assert outer.template.nested_sources == (inner.template.loop.source,)
        assert set(inner.members) <= set(outer.members)
        assert not set(inner.members).intersection(outer.direct_members)

        outside_lines = {text.splitlines().index(statement) + 1 for statement in
            ('    outside_before = before(x)', '    outside_after = after(x)')}
        outside_calls = {link.operation for link in body.metadata.operation_links
            if link.opcode is Opcode.CALL and link.source.start_line in outside_lines}
        assert len(outside_calls) == 2
        assert not outside_calls.intersection(outer.members)
        # Source ownership can split one basic block. Selecting its loop
        # operations must not silently select the unrelated prefix/suffix.
        root = index.regions[qualified.root]
        mixed_blocks = [block for block in root.blocks
            if set(block.operations).intersection(outer.members)
            and set(block.operations).difference(outer.members)]
        assert mixed_blocks

        for construct in (outer, inner):
            template = construct.template
            members = set(construct.members)
            assert construct.kind == 'SOURCE_LOOP_CONSTRUCT'
            assert construct.scope_complete is False
            assert construct.iteration_knowledge == 'TEMPLATE_ONLY'
            assert construct.content_invariance == 'UNPROVED'
            assert template.namespace == qualified and template.loop.region == root.id
            assert template.independent_loop_region is False and template.iterations_unrolled is False
            assert tuple(operation.id for operation in construct.expand(graph)) == construct.members
            assert all(index._blocks[index._operation_blocks[identity]] == root.id for identity in members)
            assert set(construct.direct_members) <= members

            header = index._block_records[template.loop.header]
            assert set(header.arguments) <= set(construct.internal_block_arguments)
            assert any(type(index.values[value]) is StateVersionValue for value in header.arguments)
            assert template.initial_routes and template.backedge_routes
            assert all(tuple(slot.formal for slot in route.slots) == header.arguments
                for route in (*template.initial_routes, *template.backedge_routes))
            assert all(slot.content_invariance == 'UNPROVED'
                for route in (*template.initial_routes, *template.backedge_routes) for slot in route.slots)
            assert any(slot.ssa_relation == 'FORWARDED' and not slot.is_world
                for route in template.backedge_routes for slot in route.slots)

            boundary = session.loop_boundary(namespace, construct)
            assert {point.node for point in boundary.cut.operations} == members
            assert all(P(qualified, value, None) in boundary.cut.members for value in header.arguments)
            assert boundary.inputs
            assert any(edge.source not in boundary.cut.members and edge.target in boundary.cut.members
                for edge in boundary.inputs)
            assert not boundary.transformation_authorized and not boundary.cut.transformation_authorized
            assert boundary.field('aliases').knowledge in (BoundaryKnowledge.PARTIAL, BoundaryKnowledge.UNKNOWN)
            # Both early return and exceptional terminal work belong to this
            # source construct, even though neither path returns to its header.
            assert {'RETURN', 'RAISE'} <= {flow.kind for flow in boundary.control if flow.target is None}
            crossing = (*boundary.cut.inputs, *boundary.cut.outputs, *boundary.cut.interfaces)
            carried = []
            for route in template.backedge_routes:
                assert route.edge.operation in members
                for slot in route.slots:
                    if type(slot.actual) is UseID:
                        source_point, formal_point = P(qualified, slot.actual, None), P(qualified, slot.formal, None)
                        edges = [edge for edge in graph.incoming(formal_point, kinds=(K.BLOCK_ARGUMENT,)).edges
                            if edge.source == source_point]
                        assert edges
                        carried.extend(edges)
            assert carried and all(edge not in crossing for edge in carried)

        # Internal values must name a fully selected original block's ports.
        # An entry argument cannot be smuggled into a partial operation cut.
        entry = index._block_records[root.entry]
        assert len(entry.operations) > 1 and entry.arguments
        argument = entry.arguments[0]
        assert type(index.values[argument].origin) is BlockArgument
        with pytest.raises(ValueError, match='every original block operation'):
            graph.cut((P(qualified, entry.operations[0]),), internal_values=(P(qualified, argument),))

    assert (model / 'manifest.json').read_bytes() == original_manifest
    assert hashlib.sha256(program.read_bytes()).hexdigest() == original_source

