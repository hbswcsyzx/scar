"""Fixed unpack fields are projections of original normal payload slots."""
import subprocess
import sys


def test_unpack_projection_slots_values_and_contexts_are_not_container_identity(tmp_path):
    from scar.analysis.static_program import link_static_program
    from scar.analysis.program_dependency_session import ProgramDependencySession, ProgramDependencyBudget
    from scar.analysis.program_value_analysis import ProgramValueAnalysis, ValueAnalysisBudget
    from scar.ir.literals import PythonLiteral
    from scar.ir.program.dependencies import (DependencyPoint as P, GraphNamespace,
        DependencyKind as K, DependencyMeaning as M, DependencyCondition)
    from scar.ir.program.ids import OperationID
    from scar.ir.program.model import CompletionResult, ExitKind, ReferenceValue, StateVersionValue, ValueKind
    from scar.ir.record_codec import decode

    source = tmp_path / 'source'
    source.mkdir()
    model = tmp_path / 'model'
    text = '''def pieces(values):
    first, second = values
    return (first, second)
def relay(values):
    return pieces(values)
def mixed(value):
    first, second = (value, 17)
    return (first, second)
def unknown(items):
    first, second = items
    return (first, second)
one = relay((3, (5, 8)))
two = relay((11, (13, 21)))
mixed_result = mixed(opaque())
unknown_result = unknown(opaque())
'''
    # This file is parsed/compiled by SCAR only. In particular opaque() is
    # never called, and no target function/module is imported or executed.
    (source / 'program.py').write_text(text)
    built = subprocess.run([sys.executable, '-B', '-m', 'scar.cli', 'static',
        str(source), '--out', str(model), '--jobs', '1', '--phase', 'bodies'],
        capture_output=True, text=True)
    assert built.returncode == 0, built.stdout + built.stderr
    link_static_program(model)

    with ProgramDependencySession(model,
            budget=ProgramDependencyBudget(max_graphs=16, max_seconds=120)) as session:
        bodies = {}
        interfaces = {}
        view = session.graph()
        for name in ('pieces', 'mixed', 'unknown'):
            namespace, = session.select_bodies(file='program.py', entry='<module>.' + name)
            body = session.load_body(namespace)
            ns = GraphNamespace.from_source(namespace)
            declared = [row for owner in ('module', 'structured', 'class')
                for row in (body.document.get(owner) or {}).get('protocols', ())
                if row['kind'] == 'UNPACK_FIXED']
            protocol, = declared
            operation = body.index.operations[decode(OperationID, protocol['operation'])]
            normal, = [edge for edge in operation.terminator.successors if edge.kind is ExitKind.NORMAL]
            landing = body.index._block_records[normal.block]
            outputs = {}
            for value, actual in zip(landing.arguments, normal.arguments):
                assert type(actual) is CompletionResult
                if type(body.index.values[value]) is ReferenceValue:
                    outputs[actual.index] = value
            assert set(outputs) == {0, 1}
            first_projection = session.unpack_projection(P(ns, outputs[0], None))
            assert first_projection is not None and first_projection.index == 0
            interface = first_projection.interface
            assert interface.operation == operation.id
            assert interface.body == namespace
            assert interface.outputs == (outputs[0], outputs[1])
            expected_guard = DependencyCondition('canonical', 'SUCCESSOR_SELECTED',
                P(ns, operation.id, None), interface.normal.successor_index)
            for index, value in outputs.items():
                point = P(ns, value, None)
                projection = session.unpack_projection(point)
                assert projection is not None and projection.interface == interface and projection.index == index
                neighborhood = view.incoming(point, kinds=(K.PROJECTION,))
                edge, = neighborhood.edges
                assert edge.kind is K.PROJECTION and edge.meaning is M.DEPENDENCE
                assert edge.source == P(ns, interface.rhs, None) and edge.target == point
                assert expected_guard in edge.conditions and edge.evidence
                # Slot is the original typed projection/CompletionResult
                # ordinal, never a runtime condition or a synthetic getitem.
                assert not any(c.name == 'COMPLETION_SLOT' for c in edge.conditions)
            pre_world = body.index.use_site(interface.world).use.value
            assert all(type(body.index.values[value]) is StateVersionValue
                for value in (pre_world, interface.normal_world, interface.raised_world))
            assert len({pre_world, interface.normal_world, interface.raised_world}) == 3
            for value in (*interface.raised_payloads, interface.normal_world, interface.raised_world):
                point = P(ns, value, None)
                assert session.unpack_projection(point) is None
                assert not view.incoming(point, kinds=(K.PROJECTION,)).edges
            bodies[name] = (ns, body)
            interfaces[name] = interface

        module_namespace, = session.select_bodies(file='program.py', entry='<module>')
        calls = [call for shard, _ in session.relation_shards(module_namespace) for call in shard.calls]
        roots = []
        for statement in ('one = relay((3, (5, 8)))', 'two = relay((11, (13, 21)))',
                'mixed_result = mixed(opaque())', 'unknown_result = unknown(opaque())'):
            line = text.splitlines().index(statement) + 1
            # Only select the outer original call; the opaque operand call
            # shares its source line but has no selected source target.
            selected = [call for call in calls if call.source.start_line == line
                and any(target.body is not None for target in call.targets)]
            call, = selected
            target, = call.targets
            completion, = [route for route in target.completions
                if route.kind is ExitKind.NORMAL and route.value_kind is ValueKind.REFERENCE
                and route.completion_index == 0]
            roots.append(P(GraphNamespace.from_source(module_namespace), completion.landing_value))
        analysis = ProgramValueAnalysis(session,
            budget=ValueAnalysisBudget(max_points=768, max_edges=2048, max_steps=8192))
        report = analysis.analyze(roots)
        assert report.worklist_stable, report.usage
        for point, expected in zip(roots[:2], ((3, (5, 8)), (11, (13, 21)))):
            field = report.for_point(point).immutable_tuple
            assert {a.value for a in field.alternatives} == {PythonLiteral.from_python(expected, exact=True)}
            assert all(a.conditions and a.evidence for a in field.alternatives)
        assert any(edge.kind is K.ARGUMENT for edge in report.edges)
        assert any(edge.kind is K.COMPLETION for edge in report.edges)
        assert any(edge.kind is K.BINDING_PAYLOAD for edge in report.edges)
        assert any(edge.kind is K.BINDING_READ for edge in report.edges)
        assert any(edge.kind is K.PROJECTION for edge in report.edges)

        # The two contexts of the same original unpack retain distinct slot
        # values. A normal slot1 is a nested tuple, not a copy of slot0.
        pieces_ns, _ = bodies['pieces']
        pieces = interfaces['pieces']
        contextual = {}
        for fact in report.facts:
            if fact.point.namespace == pieces_ns and fact.point.node in pieces.outputs:
                contextual.setdefault(fact.point.context, {})[pieces.outputs.index(fact.point.node)] = fact
        observed = set()
        for context, slots in contextual.items():
            if set(slots) != {0, 1} or not slots[0].scalar_constant.alternatives:
                continue
            scalars = {a.value for a in slots[0].scalar_constant.alternatives}
            tuples = {a.value for a in slots[1].immutable_tuple.alternatives}
            assert len(scalars) == len(tuples) == 1
            assert not slots[0].immutable_tuple.alternatives and not slots[1].scalar_constant.alternatives
            observed.add((next(iter(scalars)), next(iter(tuples))))
        assert observed == {
            (PythonLiteral.from_python(3), PythonLiteral.from_python((5, 8), exact=True)),
            (PythonLiteral.from_python(11), PythonLiteral.from_python((13, 21), exact=True)),
        }

        # A constructed tuple has its own known definition even when one
        # element is open. That container definition is not either element.
        mixed_ns, _ = bodies['mixed']
        mixed = interfaces['mixed']
        mixed_outputs = [fact for fact in report.facts
            if fact.point.namespace == mixed_ns and fact.point.node == mixed.outputs[0]]
        assert mixed_outputs
        for fact in mixed_outputs:
            rhs = report.for_point(P(mixed_ns, mixed.rhs, fact.point.context))
            container_sources = {a.value for a in rhs.reference_sources.alternatives}
            assert container_sources
            assert not container_sources & {a.value for a in fact.reference_sources.alternatives}
            assert not fact.scalar_constant.alternatives and not fact.immutable_tuple.alternatives
            assert fact.scalar_constant.unknown_paths or fact.immutable_tuple.unknown_paths
            assert fact.feasible is not False
            second = report.for_point(P(mixed_ns, mixed.outputs[1], fact.point.context))
            assert second is not None
            assert {a.value for a in second.scalar_constant.alternatives} == {PythonLiteral.from_python(17)}
        for point in roots[2:]:
            fact = report.for_point(point)
            assert not fact.scalar_constant.alternatives and not fact.immutable_tuple.alternatives
            assert fact.scalar_constant.unknown_paths or fact.immutable_tuple.unknown_paths
            assert fact.feasible is not False
