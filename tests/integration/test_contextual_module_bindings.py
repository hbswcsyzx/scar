"""Original module fields remain conditional across real contextual CALL ports."""
import hashlib
import json
import subprocess
import sys


def test_module_argument_fields_follow_relative_reexports_without_receiver_callee_identity(tmp_path):
    from scar.analysis.contextual_module_bindings import ContextualModuleBindingProvider
    from scar.analysis.static_calls import StaticCallBudget, StaticCallSession
    from scar.ir.program.dependencies import (
        DependencyKind as K, DependencyMeaning as M, DependencyPoint as P,
        DependencyStrength as Strength, GraphNamespace, OpenDependencyContext, context_frames,
    )
    from scar.ir.program.ids import UseID
    from scar.ir.program.model import LiteralOrigin
    from scar.ir.program.static_calls import StaticImportFromRead

    source = tmp_path / 'source'
    source.mkdir()
    package = source / 'pkg'
    package.mkdir()
    initializer = package / '__init__.py'
    initializer.write_text('from .worker import Item, work\n')
    worker = package / 'worker.py'
    worker.write_text('class Item:\n    def __init__(self, value):\n        self.value = value\n'
        '\ndef work():\n    return 17\n')
    application = source / 'app.py'
    text = ('import pkg\ndef build(mod):\n    return mod.Item(3)\n'
        'def dispatch(mod):\n    return mod.work()\n'
        'created = build(pkg)\ncalled = dispatch(pkg)\n')
    application.write_text(text)
    originals = {path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (initializer, worker, application)}
    model = tmp_path / 'model'
    # This subprocess executes SCAR only. No sample import, class constructor,
    # initializer, descriptor, package hook or work() is executed.
    built = subprocess.run([sys.executable, '-B', '-m', 'scar.cli', 'static', str(source),
        '--out', str(model), '--jobs', '1', '--phase', 'bodies'], capture_output=True, text=True)
    assert built.returncode == 0, built.stdout + built.stderr
    assert not json.loads((model / 'manifest.json').read_bytes()).get('static_calls')

    relative_projections = {}
    with StaticCallSession(model, out=tmp_path / 'query',
            budget=StaticCallBudget(max_seconds=180)) as owner:
        number = next(i for i, unit in enumerate(owner.units) if unit['path'] == str(application))
        context = owner._unit(number)
        position, row = next((i, row) for i, row in enumerate(owner.units[number]['bodies'])
            if row['kind'] == 'MODULE')
        module = owner._body(context, position, row)
        resolver = owner.contextual_resolver()
        provider = ContextualModuleBindingProvider(resolver)
        selected = {link.source.start_line: operation for operation, link in resolver._calls(module).items()}
        lines = text.splitlines()
        inner_calls = {}
        for statement, function, field in (('created = build(pkg)', 'build', 'Item'),
                                           ('called = dispatch(pkg)', 'dispatch', 'work')):
            outer_operation = selected[lines.index(statement) + 1]
            outer, = tuple(owner.resolve_contextual_calls(module,
                operations=(outer_operation,), context=None))
            target, = outer.targets
            assert outer.call.context is None
            assert type(target.callee_context) is OpenDependencyContext
            assert context_frames(target.callee_context) == (target.frame,)
            assert target.interface.body.source.path == str(application)
            inner_body = owner._load_body_namespace(target.interface.body)
            inner, = tuple(owner.resolve_contextual_calls(inner_body, context=target.callee_context))
            inner_calls[function] = inner.call
            receivers = resolver.receiver_evidence(inner.call)
            classes = resolver.class_sources(inner.call)
            invocations = resolver.class_invocations(inner.call)
            assert receivers is not None
            evidence, = receivers
            assert evidence.lookup.field == field
            receiver = P(GraphNamespace.from_source(inner_body.namespace),
                evidence.lookup.receiver, inner.call.context)
            assert evidence.walk.roots == (receiver,)
            argument_edges = [edge for edge in evidence.walk.edges if edge.kind is K.ARGUMENT]
            assert argument_edges and all(edge.conditions and edge.evidence for edge in argument_edges)
            assert any(edge.target.context == target.callee_context and edge.source.context is None
                for edge in argument_edges)
            assert any(frontier.kind == 'RECEIVER_IMPORT_MODULE_SOURCE'
                for frontier in evidence.walk.frontiers)

            if field == 'Item':
                origin, = classes
                alternative, = invocations
                assert alternative.source == origin and alternative.original_invocation_retained
                assert not alternative.runtime_class_verified
                assert not alternative.python_callbacks_connected
                assert not alternative.physical_abi_mapping_complete
                assert origin.source.namespace.source_body.source is None
                assert origin.construction.source.path == str(worker)
                assert origin.source.context is None
                assert not inner.targets
                path = origin.path
                conditions, proofs = origin.conditions, origin.evidence
                callable_point = origin.callable
            else:
                assert classes == () and invocations == ()
                candidate, = inner.targets
                assert candidate.interface.definition.source.path == str(worker)
                assert candidate.source.creation.creation.definition.source.start_line == 5
                assert candidate.source.factory.context is None
                path = candidate.source.path
                conditions, proofs = candidate.source.conditions, candidate.source.evidence
                callable_point = candidate.callee

            assert not inner.enumerated
            assert path and path[-1].target == callable_point
            assert all(condition in conditions for edge in path for condition in edge.conditions)
            assert all(proof in proofs for edge in path for proof in edge.evidence)
            # The module is an operand of the lookup. It is never promoted to
            # the class/function factory or equated to lookup.result.
            lookup_result = P(receiver.namespace, evidence.lookup.result, receiver.context)
            assert not any(edge.source == receiver and edge.target == lookup_result
                and edge.meaning is M.REFERENCE for edge in path)
            field_projections = []
            for read_result in dict.fromkeys(edge.target for edge in path if edge.kind is K.STATE_VALUE):
                projections = tuple(projection for projection in provider.projections_for(read_result)
                    if projection.dependency_edge() in path)
                for projection in projections:
                    field_projections.append(projection)
                    assert provider.validate_projection(projection)
                    edge = projection.dependency_edge()
                    assert edge in path
                    assert edge.kind is K.STATE_VALUE and edge.meaning is M.REFERENCE
                    assert edge.strength is Strength.MAY and edge.conditions and edge.evidence
                    assert type(projection.source.node) is UseID and projection.source.context is None
                    assert projection.source.node == projection.namespace_binding.write.payload
                    assert projection.namespace_binding.key == projection.read.field
                    assert projection.target == read_result
                    assert projection.target.node == projection.read.result
                    assert projection.receiver_path
                    assert projection.receiver_path[-1].target.node == projection.read.receiver
                    names = {condition.name for condition in projection.conditions
                        if condition.domain == 'scar.contextual-module-binding'}
                    required = {'STANDARD_IMPORT_INITIALIZER_USES_MODULE_DICT',
                        'SOURCE_MODULE_INITIALIZER_COMPLETED_NORMALLY',
                        'SOURCE_SNAPSHOT_BINDING_PRESERVED_AT_CURRENT_READ'}
                    required.update({'IMPORT_FROM_LOOKUP_USES_NAMESPACE_BINDING',
                        'IMPORT_FROM_FALLBACKS_NOT_SELECTED'} if type(projection.read) is StaticImportFromRead
                        else {'MODULE_LOOKUP_USES_SOURCE_MODULE_DICT', 'MODULE_LOOKUP_HOOKS_NOT_SELECTED'})
                    assert required <= names
                    imported = projection.import_source
                    assert imported.module_context is None
                    if imported.relative_level == 1:
                        assert type(projection.read) is StaticImportFromRead
                        relative_projections[projection.read.field] = projection
            assert any(projection.target == lookup_result for projection in field_projections)
            neighborhood = resolver.session.graph().incoming(lookup_result, kinds=(K.STATE_VALUE,))
            assert any(frontier.kind == 'CONTEXTUAL_MODULE_BINDING_SCOPE_OPEN'
                for frontier in neighborhood.frontiers)

        assert set(relative_projections) == {'Item', 'work'}
        for field, projection in relative_projections.items():
            imported, read = projection.import_source, projection.read
            assert imported.requested_spelling == 'worker'
            assert imported.relative_level == 1 and imported.package_context == 'pkg'
            assert imported.resolved_module == 'pkg.worker'
            assert read.member_index == ('Item', 'work').index(field)
            request = imported.request
            assert request is not None and request.fromlist_constant.source == imported.source
            original_body = resolver._body(imported.origin.namespace)
            requested = original_body.index.values[original_body.index.use_site(request.requested_use).use.value]
            level = original_body.index.values[original_body.index.use_site(request.level_use).use.value]
            assert type(requested.origin) is LiteralOrigin and requested.origin.value == 'worker'
            assert type(level.origin) is LiteralOrigin and type(level.origin.value) is int and level.origin.value == 1
            fromlist = original_body.index.use_site(request.fromlist_use).use.value
            assert original_body.index.operations[request.fromlist_constant.operation].results == (fromlist,)
            guards = [condition for condition in projection.conditions
                if condition.name == 'CURRENT_IMPORT_PACKAGE_CONTEXT_MATCHES_DECLARED_CANDIDATE']
            assert guards and all(condition.operands and condition.index is not None for condition in guards)
            assert all(condition in projection.conditions for condition in imported.conditions)

        # Unknown caller scope cannot borrow the previously selected actual
        # module argument or turn an open suffix into a closed activation.
        bound = inner_calls['build']
        unbound = resolver.resolve(P(bound.namespace, bound.node, None))
        assert not unbound.targets and not unbound.enumerated
        assert resolver.class_sources(unbound.call) == ()
        assert resolver.class_invocations(unbound.call) == ()
        unbound_evidence, = resolver.receiver_evidence(unbound.call)
        assert unbound_evidence.walk.roots[0].context is None
        assert any(frontier.kind == 'RECEIVER_ENTRY_FORMAL_UNBOUND'
            for frontier in unbound_evidence.walk.frontiers)
        assert not any(edge.kind is K.ARGUMENT for edge in unbound_evidence.walk.edges)
    assert all(hashlib.sha256(path.read_bytes()).hexdigest() == digest
        for path, digest in originals.items())
