"""Receiver evidence follows actual caller ports without becoming a callee."""
import subprocess
import sys


def test_receiver_walk_follows_matching_formal_and_retains_unbound_context(tmp_path):
    from scar.analysis.static_calls import StaticCallSession, StaticCallBudget
    from scar.analysis.static_program import link_static_program
    from scar.analysis.static_namespace import normal_reference, protocol_kinds
    from scar.ir.program.dependencies import (DependencyPoint as P, GraphNamespace,
        DependencyKind as K, DependencyMeaning as M, context_frames)

    source = tmp_path / 'source'
    source.mkdir()
    helper = source / 'helper.py'
    helper.write_text('def work():\n    return 23\n')
    application = source / 'app.py'
    application.write_text('import helper\ndef apply(receiver):\n    return receiver.work()\nresult = apply(helper)\n')
    model = tmp_path / 'model'
    # Only SCAR runs. Neither input file is imported/executed, and receiver
    # classification never calls a descriptor or assumes an instance class.
    built = subprocess.run([sys.executable, '-B', '-m', 'scar.cli', 'static',
        str(source), '--out', str(model), '--jobs', '1', '--phase', 'bodies'],
        capture_output=True, text=True)
    assert built.returncode == 0, built.stdout + built.stderr
    link_static_program(model)

    with StaticCallSession(model, out=tmp_path / 'contextual',
            budget=StaticCallBudget(max_seconds=120)) as owner:
        number = next(i for i, unit in enumerate(owner.units) if unit['path'] == str(application))
        context = owner._unit(number)
        module_position, module_row = next((i, row) for i, row in enumerate(owner.units[number]['bodies'])
            if row['kind'] == 'MODULE')
        apply_position, apply_row = next((i, row) for i, row in enumerate(owner.units[number]['bodies'])
            if row['name'] == '<module>.apply')
        module = owner._body(context, module_position, module_row)
        applying = owner._body(context, apply_position, apply_row)
        resolver = owner.contextual_resolver()
        outer, = tuple(owner.resolve_contextual_calls(module, context=()))
        target, = outer.targets
        assert target.frame is not None
        assert context_frames(target.callee_context)[-1] == target.frame
        assert target.interface.body == applying.namespace

        module_ns = GraphNamespace.from_source(module.namespace)
        apply_ns = GraphNamespace.from_source(applying.namespace)
        imports = [operation for operation, kind in protocol_kinds(module.document).items()
            if kind in ('IMPORT_NAME_314', 'FUNCTION_IMPORT_NAME')]
        imported_operation, = imports
        blocks = {block.id: block for region in module.graph.regions for block in region.blocks}
        imported = normal_reference(module.index, imported_operation, blocks=blocks)
        assert imported is not None
        imported_point = P(module_ns, imported[1], outer.call.context)

        inner, = tuple(owner.resolve_contextual_calls(applying, context=target.callee_context))
        saved = resolver.receiver_evidence(inner.call)
        assert saved is not None
        evidence, = saved
        assert evidence.lookup.field == 'work'
        receiver = P(apply_ns, evidence.lookup.receiver, inner.call.context)
        assert evidence.walk.roots == (receiver,)
        assert receiver in evidence.walk.points and imported_point in evidence.walk.points
        argument_edges = [edge for edge in evidence.walk.edges if edge.kind is K.ARGUMENT]
        assert argument_edges, evidence.walk.frontiers
        assert any(edge.target.namespace == apply_ns and edge.target.context == target.callee_context
            and edge.source.namespace == module_ns and edge.source.context == outer.call.context
            for edge in argument_edges)
        assert all(edge.meaning is M.REFERENCE and edge.conditions and edge.evidence
            for edge in argument_edges)
        assert any(frontier.kind == 'RECEIVER_IMPORT_MODULE_SOURCE'
            and frontier.point == imported_point for frontier in evidence.walk.frontiers)
        assert any(frontier.kind == 'ATTRIBUTE_DISPATCH_RULE_OPEN' for frontier in inner.frontiers)
        assert not evidence.walk.dependence_closed
        # A module receiver's origin explains the lookup operand. It is not
        # itself a function factory or a reference identity for lookup.result.
        lookup_result = P(apply_ns, evidence.lookup.result, inner.call.context)
        incoming_lookup = resolver.session.graph().incoming(lookup_result,
            kinds=(K.STATE_VALUE, K.ENVIRONMENT, K.ARGUMENT, K.COMPLETION))
        assert not any(edge.source == receiver and edge.meaning is M.REFERENCE
            for edge in incoming_lookup.edges)
        assert all(candidate.source.factory != imported_point for candidate in inner.targets)
        assert all(candidate.source.path != evidence.walk.edges for candidate in inner.targets)

        unbound_call = P(inner.call.namespace, inner.call.node, None)
        unbound = resolver.resolve(unbound_call)
        assert resolver.receiver_evidence(inner.call) is None
        unbound_saved = resolver.receiver_evidence(unbound.call)
        assert unbound_saved is not None
        unbound_evidence, = unbound_saved
        assert unbound_evidence.walk.roots == (P(apply_ns, unbound_evidence.lookup.receiver, None),)
        assert any(frontier.kind == 'RECEIVER_ENTRY_FORMAL_UNBOUND'
            for frontier in unbound_evidence.walk.frontiers)
        assert imported_point not in unbound_evidence.walk.points
        assert not any(edge.kind is K.ARGUMENT for edge in unbound_evidence.walk.edges)
        assert not unbound.targets

        # An accessor for another completed query must report absence of its
        # transient evidence, rather than fabricate a known-empty walk.
        resolver.resolve(outer.call)
        assert resolver.receiver_evidence(unbound.call) is None
