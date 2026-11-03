"""Source class calls reach a conditional native protocol without execution."""
from dataclasses import replace
from pathlib import Path
import subprocess
import sys

import pytest


def test_class_sources_constructor_protocol_and_shared_implementation_graph(tmp_path):
    from scar.analysis.static_program import link_static_program
    from scar.analysis.static_calls import StaticCallSession, StaticCallBudget
    from scar.analysis.program_dependency_session import ProgramDependencySession
    from scar.analysis.contextual_class_sources import validate_class_statement_source
    from scar.analysis.contextual_type_calls import validate_type_call_alternative
    from scar.analysis.static_type_call import validate_type_call_provider
    from scar.ir.program.dependencies import DependencyKind as K, DependencyMeaning as M, DependencyPoint as P, context_push
    from scar.ir.program.model import DataValue, ReferenceValue, StateVersionValue, TerminatorKind
    from scar.ir.program.type_calls import TypeCallProvider, TypeCallStageKind as S
    from scar.ir.record_codec import decode, encode

    source = tmp_path / 'source'
    source.mkdir()
    text = (Path(__file__).resolve().parents[2] / 'examples/python_class_calls/program.py').read_text()
    (source / 'program.py').write_text(text)
    model = tmp_path / 'model'
    built = subprocess.run([sys.executable, '-B', '-m', 'scar.cli', 'static', str(source),
        '--out', str(model), '--jobs', '1', '--phase', 'bodies'], capture_output=True, text=True)
    assert built.returncode == 0, built.stdout + built.stderr
    link_static_program(model)
    with StaticCallSession(model, out=tmp_path / 'query', budget=StaticCallBudget(max_seconds=180)) as owner:
        context = owner._unit(0)
        position, row = next((i, row) for i, row in enumerate(owner.units[0]['bodies']) if row['kind'] == 'MODULE')
        body = owner._body(context, position, row)
        resolver = owner.contextual_resolver()
        selected = {link.source.start_line: operation for operation, link in resolver._calls(body).items()}
        alternatives = []
        for statement in ('first = Alias(3, flag=True)', 'second = Alias(4, flag=False)', 'other = Wrapped(9)'):
            operation = selected[text.splitlines().index(statement) + 1]
            resolution, = tuple(owner.resolve_contextual_calls(body, operations=(operation,), context=None))
            origin, = resolver.class_sources(resolution.call)
            assert validate_class_statement_source(resolver, origin)
            alternative, = resolver.class_invocations(resolution.call)
            assert validate_type_call_alternative(resolver, alternative)
            assert alternative.source == origin and alternative.original_invocation_retained
            assert not alternative.runtime_class_verified and not alternative.python_callbacks_connected
            assert not alternative.physical_abi_mapping_complete
            assert any(f.kind == 'TYPE_CALL_PHYSICAL_ABI_AND_CALLBACKS_OPEN' for f in resolution.frontiers)
            native = resolver.session.load(alternative.provider)
            assert native.namespace.source_body is None
            metadata = dict(native.document['provider'])
            metadata['graph'] = encode(native.graph)
            provider = decode(TypeCallProvider, metadata)
            validate_type_call_provider(provider)
            with pytest.raises(ValueError):
                validate_type_call_provider(replace(provider, new_object=provider.inputs[0]))
            assert type(native.index.values[provider.argument_view]) is DataValue
            assert native.index.values[provider.argument_view].data_type == 'scar.logical-call-arguments'
            new, = (stage for stage in provider.stages if stage.kind is S.INVOKE_TP_NEW)
            init, = (stage for stage in provider.stages if stage.kind is S.INVOKE_TP_INIT)
            assert new.normal.payloads == (provider.new_object,)
            assert type(native.index.values[provider.new_object]) is ReferenceValue
            assert init.normal.payloads == ()
            assert init.normal.world != new.normal.world
            assert type(native.index.values[init.normal.world]) is StateVersionValue
            returns = [stage for stage in provider.stages if stage.kind is S.RETURN_OBJECT]
            assert len(returns) == 3
            for stage in returns:
                returned = native.index.operations[stage.operation]
                assert returned.terminator.kind is TerminatorKind.RETURN
                assert native.index.use_site(returned.terminator.values[0]).use.value == provider.new_object
            assert len(provider.cleanup_operations) == 1
            assert provider.exception_arity == len(new.raised.payloads) == len(init.raised.payloads)
            assert all(edge.conditions and edge.evidence for edge in alternative.edges)
            graph = resolver.session.graph()
            assert any(edge.target.namespace == alternative.provider
                for edge in graph.outgoing(resolution.call, kinds=(K.IMPLEMENTATION,)).edges)
            child = context_push(resolution.call.context, alternative.frame)
            for formal in provider.inputs:
                incoming = graph.incoming(P(alternative.provider, formal, child), kinds=(K.ARGUMENT,))
                assert incoming.edges and all(edge.meaning in (M.REFERENCE, M.VALUE) for edge in incoming.edges)
            if not alternatives:
                with ProgramDependencySession(model) as registry:
                    registered = registry.register_implementation_graph(alternative.provider.graph,
                        alternative.provider.representation, native.graph)
                    assert registry.index(registered).graph == native.graph
                    registry.graph().incoming(P(registered, provider.inputs[0], None), kinds=(K.ARGUMENT,))
            alternatives.append(alternative)
        # Different argument values reuse one typed implementation definition.
        assert alternatives[0].provider == alternatives[1].provider
        decorated = alternatives[2].source
        assert decorated.construction.decorators
        assert decorated.source.node == decorated.construction.result
        assert decorated.source.node != decorated.construction.builder_call.result
        assert not decorated.runtime_class_verified
        outer_operation = selected[text.splitlines().index('forwarded = construct(Maker, 7)') + 1]
        outer, = tuple(owner.resolve_contextual_calls(body, operations=(outer_operation,), context=None))
        target, = outer.targets
        child_body = owner._load_body_namespace(target.interface.body)
        child, = tuple(owner.resolve_contextual_calls(child_body, context=target.callee_context))
        forwarded, = resolver.class_invocations(child.call)
        metadata = resolver.session.load(forwarded.provider).document['provider']
        assert metadata['exception_arity'] == 1
        assert any(edge.kind is K.ARGUMENT for edge in forwarded.source.path)
