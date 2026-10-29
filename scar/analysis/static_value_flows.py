"""Conditional reference routes through original call/formal/return ports.

These edges are composable at any call depth. A consumer pushes the exact
return context and consumes only the matching formal/actual context; merging
callee code bodies does not merge their callers' references. No route proves
unchanged contents, purity, or an observed invocation.
"""
from __future__ import annotations

import ast
import hashlib
from types import SimpleNamespace

from scar.ir.record_codec import decode
from scar.ir.v2.common import SourceReference
from scar.ir.program.functions import (
    ArgumentKind, BodyEntryInterface, CallArgument, CallBindingStatus, FunctionKind, FunctionSignature,
)
from scar.ir.program.model import (
    CompletionResult, ExitKind, ReferenceValue, TerminatorKind, UseRole, ValueKind,
)
from scar.ir.program.native import ExitPortRef
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.static_calls import (
    StaticArgumentValueFlow, StaticCallContext, StaticCallFrontier, StaticCompletionRoute,
    StaticReturnValueFlow, StaticTerminalPort,
)
from scar.ir.program.structured import ControlEdgeReference
from scar.analysis.function_binding import bind_call
from scar.analysis.function_interfaces import validate_body_interface
from scar.analysis.static_function_environment import validate_static_body_namespace


def _body(body, facts=None):
    if facts is not None:
        return facts.body(body).metadata
    if type(body.index) is not ProgramIndex or body.index.graph is not body.graph:
        raise ValueError('value-flow index belongs to another original body graph')
    return validate_static_body_namespace(body.graph, body.document, body.namespace)


def _sources(body, metadata, facts=None):
    if facts is not None:
        return facts.body(body).sources
    # Mapping/class bodies retain source ports in their explicit overlays;
    # their generic LoweringMetadata intentionally carries only the snapshot.
    if body.document.get('module') is not None:
        from scar.ir.program.module_entries import decode_frame_body
        return decode_frame_body(body.document['module'])
    if body.document.get('class') is not None:
        from scar.ir.program.class_entries import decode_class_entry_overlay
        return decode_class_entry_overlay(body.document['class'])
    return metadata


class _ValueFacts:
    """Typed input snapshots owned by one derive or standalone verification.

    No result is retained between public calls. Strong references prevent ID
    reuse, and graph/index/document/namespace ownership is checked on reuse.
    Flow-specific conditions and endpoints are checked separately each time.
    """
    def __init__(self, caller, callee):
        self.bodies = {}
        self.known = {caller.namespace: caller, callee.namespace: callee}
        self.signatures = {}
        self.texts = {}
        self.bindings = {}
        self.completions = {}

    def body(self, body):
        key = id(body)
        found = self.bodies.get(key)
        if found is not None:
            if (found.original is not body or found.graph is not body.graph
                    or found.index is not body.index or found.document is not body.document
                    or found.namespace != body.namespace or body.index.graph is not body.graph):
                raise ValueError('value-flow input ownership changed within its local verification scope')
            return found
        metadata = _body(body)
        sources = _sources(body, metadata)
        interface = (decode(BodyEntryInterface, body.document['interface'])
                     if body.document.get('interface') is not None else None)
        by_operation, by_use, references = {}, {}, {}
        for row in sources.operation_links:
            by_operation.setdefault(row.operation, []).append(row)
        for row in sources.use_links:
            by_use.setdefault(row.operation, []).append(row)
        for rows in (sources.use_links, sources.operation_links, sources.value_links):
            for row in rows:
                if type(row.source) is SourceReference:
                    references.setdefault(_span(row.source), set()).add(row.source)
        found = SimpleNamespace(original=body, graph=body.graph, index=body.index,
            document=body.document, namespace=body.namespace, metadata=metadata,
            sources=sources, interface=interface, operation_links=by_operation,
            use_links=by_use, references=references,
            blocks={block.id: block for region in body.graph.regions for block in region.blocks})
        self.bodies[key] = found
        return found

    def load(self, namespace, loader):
        body = self.known.get(namespace)
        if body is None:
            if loader is None:
                raise ValueError('context-qualified value flow requires its original body loader')
            body = loader(namespace)
            if body is None or body.namespace != namespace:
                raise ValueError('value-flow context loader changed its original namespace')
            self.known[namespace] = body
        return body


def _signature(callee, signature=None, facts=None):
    if signature is None:
        signature = getattr(callee, 'signature', None)
    if signature is None and getattr(callee, 'context', None) is not None:
        row = callee.context.definitions.get(callee.namespace.definition)
        signature = row[1] if row is not None else None
    if signature is None:
        return None
    if (type(signature) is not FunctionSignature or signature.definition != callee.namespace.definition
            or signature.source != callee.namespace.source):
        raise ValueError('value-flow signature differs from its original qualified callee')
    key = id(callee), signature
    if facts is not None and key in facts.signatures:
        facts.body(callee)
        return facts.signatures[key]
    if callee.document.get('interface') is None:
        raise ValueError('value-flow callee has no original function entry interface')
    metadata = _body(callee, facts)
    interface = (facts.body(callee).interface if facts is not None
                 else decode(BodyEntryInterface, callee.document['interface']))
    validate_body_interface(SimpleNamespace(graph=callee.graph, metadata=metadata),
                            interface, signature)
    if facts is not None:
        facts.signatures[key] = signature
    return signature


def _validate_call_context(context, *, caller, callee, signature=None, facts):
    """Check qualified static ports, without claiming the target was selected."""
    if type(context) is not StaticCallContext:
        raise TypeError('value-flow reader needs its exact typed call context')
    context.__post_init__()
    caller_metadata, callee_metadata = _body(caller, facts), _body(callee, facts)
    if (caller.namespace != context.caller or callee.namespace != context.callee
            or context.definition.snapshot != callee_metadata.source):
        raise ValueError('value-flow context changed an original qualified body/source')
    operation = caller.index.operations.get(context.operation)
    if operation is None or operation.terminator is None or operation.terminator.kind is not TerminatorKind.INVOKE:
        raise ValueError('value-flow context has no original call INVOKE')
    use = caller.index.use_site(context.callee_use)
    roles = [row for row in facts.body(caller).use_links.get(context.operation, ())
             if row.use == context.callee_use and row.role == 'callee']
    if (use.operation != context.operation or use.use.value != context.callee_value
            or context.callee_use not in operation.invoke_arguments or len(roles) != 1
            or type(caller.index.values[context.callee_value]) is not ReferenceValue):
        raise ValueError('value-flow context changed the original callable Use/reference')
    if signature is not None:
        _signature(callee, signature, facts)
    return True


def validate_call_context(context, *, caller, callee, signature=None):
    """Fresh standalone check of qualified original static call ports."""
    return _validate_call_context(context, caller=caller, callee=callee, signature=signature,
                                  facts=_ValueFacts(caller, callee))


def _requirements(context, requirements, *, caller, callee, load_body, load_signature, facts):
    for required in requirements:
        endpoints = []
        for namespace in (required.caller, required.callee):
            endpoints.append(facts.load(namespace, load_body))
        signature = (load_signature(required.callee) if load_signature is not None
                     else _signature(endpoints[1], facts=facts))
        if signature is None:
            raise ValueError('required call context has no original source signature')
        _validate_call_context(required, caller=endpoints[0], callee=endpoints[1], signature=signature, facts=facts)


def _span(value):
    if isinstance(value, ast.AST):
        return value.lineno, value.end_lineno, value.col_offset, value.end_col_offset
    return value.start_line, value.end_line, value.start_column, value.end_column


def _source_text(caller, supplied, facts=None):
    if supplied is None:
        supplied = getattr(caller, 'source_text', None)
    if supplied is None and getattr(caller, 'context', None) is not None:
        supplied = caller.context.docs['source']['text']
    metadata = _body(caller, facts)
    if facts is not None:
        cached = facts.texts.get(id(caller))
        if cached is not None:
            if supplied != cached.text:
                raise ValueError('value-flow source text changed within its local verification scope')
            return cached.text, metadata
    if (type(supplied) is not str
            or 'sha256:' + hashlib.sha256(supplied.encode()).hexdigest() != metadata.source.fingerprint):
        raise ValueError('value-flow caller text differs from its original source snapshot')
    if facts is not None:
        tree = ast.parse(supplied, filename=metadata.source.path, type_comments=True)
        calls = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                calls.setdefault(_span(node), []).append(node)
        facts.texts[id(caller)] = SimpleNamespace(text=supplied, tree=tree, calls=calls)
    return supplied, metadata


def _binding(context, caller, signature, source_text, facts=None):
    text, metadata = _source_text(caller, source_text, facts)
    key = id(caller), context, signature
    if facts is not None and key in facts.bindings:
        return facts.bindings[key]
    sources = _sources(caller, metadata, facts)
    links = (facts.body(caller).operation_links.get(context.operation, ()) if facts is not None else
             [row for row in sources.operation_links if row.operation == context.operation])
    if len(links) != 1:
        raise ValueError('value-flow call has no unique original operation/source link')
    link = links[0]
    if link.semantic_operation is None or type(link.source) is not SourceReference:
        return None
    if facts is not None:
        nodes = facts.texts[id(caller)].calls.get(_span(link.source), ())
    else:
        tree = ast.parse(text, filename=metadata.source.path, type_comments=True)
        nodes = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and _span(node) == _span(link.source)]
    if len(nodes) != 1:
        raise ValueError('value-flow call has no exact retained Call AST')
    operation = caller.index.operations[context.operation]
    use_links = (facts.body(caller).use_links.get(context.operation, ()) if facts is not None else
                 [row for row in sources.use_links if row.operation == context.operation])
    node = nodes[0]
    entries = [(argument.value if isinstance(argument, ast.Starred) else argument,
                ArgumentKind.STARRED if isinstance(argument, ast.Starred) else ArgumentKind.POSITIONAL, None)
               for argument in node.args]
    entries.extend((keyword.value, ArgumentKind.KEYWORD if keyword.arg is not None else ArgumentKind.DOUBLE_STARRED,
                    keyword.arg) for keyword in node.keywords)
    actuals = []
    for position, (source, kind, keyword) in enumerate(entries):
        references = {row.source for row in use_links if row.role != 'callee'
                      and type(row.source) is SourceReference and _span(row.source) == _span(source)}
        if not references:
            if facts is not None:
                references = set(facts.body(caller).references.get(_span(source), ()))
            else:
                references = {row.source for rows in (sources.use_links, sources.operation_links, sources.value_links)
                              for row in rows if type(row.source) is SourceReference and _span(row.source) == _span(source)}
        if len(references) != 1:
            return None
        reference = references.pop()
        matches = [row.use for row in use_links if row.source == reference and row.role != 'callee'
                   and row.use in operation.invoke_arguments
                   and caller.index.use_site(row.use).use.role is not UseRole.STATE_CONTENT]
        actuals.append(CallArgument(position, reference, kind, keyword, matches[0] if len(matches) == 1 else None))
    binding = bind_call(signature, call=link.semantic_operation, target=context.definition.definition,
                        source=link.source, arguments=tuple(actuals))
    if facts is not None:
        facts.bindings[key] = binding
    return binding


def _completion(caller, callee, context, facts=None):
    key = id(caller), id(callee), context
    if facts is not None and key in facts.completions:
        facts.body(caller); facts.body(callee)
        return facts.completions[key]
    operation = caller.index.operations[context.operation]
    normals = [(position, edge) for position, edge in enumerate(operation.terminator.successors)
               if edge.kind is ExitKind.NORMAL]
    root = callee.index.regions[callee.namespace.region]
    exits = [port for port in root.exits if port.kind is ExitKind.NORMAL]
    signatures = [signature for signature in operation.completions if signature.kind is ExitKind.NORMAL]
    if len(normals) != 1 or len(exits) != 1 or len(signatures) != 1:
        return None
    edge_index, edge = normals[0]
    exit_port, signature = exits[0], signatures[0]
    if (not signature.types or len(signature.types) != len(exit_port.types)
            or signature.types[0].kind is not ValueKind.REFERENCE or exit_port.types[0].kind is not ValueKind.REFERENCE):
        return None
    positions = [number for number, actual in enumerate(edge.arguments)
                 if type(actual) is CompletionResult and actual.index == 0]
    caller_blocks = (facts.body(caller).blocks if facts is not None else
                     {block.id: block for region in caller.graph.regions for block in region.blocks})
    if len(positions) != 1:
        return None
    landing = caller_blocks[edge.block].arguments[positions[0]]
    if type(caller.index.values[landing]) is not ReferenceValue:
        raise ValueError('normal value-flow landing is not its original reference formal')
    port = ExitPortRef(root.id, exit_port.name, 0)
    terminals = []
    for block in root.blocks:
        for identity in block.operations:
            terminal = callee.index.operations[identity].terminator
            if terminal is None or terminal.kind is not TerminatorKind.RETURN or terminal.exit != exit_port.name:
                continue
            if not terminal.values:
                raise ValueError('normal value-flow terminal lacks its declared reference payload')
            use = callee.index.use_site(terminal.values[0])
            if use.operation != identity or type(callee.index.values[use.use.value]) is not ReferenceValue:
                raise ValueError('normal value-flow terminal changed its original returned reference Use')
            terminals.append(StaticTerminalPort(port, block.id, identity, use.use.id, use.use.value))
    completion = (StaticCompletionRoute(ExitKind.NORMAL, ValueKind.REFERENCE,
        ControlEdgeReference(context.operation, edge_index), 0, edge.block, landing, port, tuple(terminals))
        if terminals else None)
    if facts is not None:
        facts.completions[key] = completion
    return completion


def _scope(flow, *, caller, callee, signature, load_body, load_signature, target, facts):
    flow.__post_init__()
    signature = _signature(callee, signature, facts)
    if signature is None or signature.kind is not FunctionKind.SYNC:
        raise ValueError('suspended or unavailable source body cannot supply a synchronous value flow')
    _validate_call_context(flow.context, caller=caller, callee=callee, signature=signature, facts=facts)
    _requirements(flow.context, flow.requirements, caller=caller, callee=callee,
                  load_body=load_body, load_signature=load_signature, facts=facts)
    if target is not None and (target.definition != flow.context.definition or target.body != flow.context.callee
                               or flow.requirements not in target.requirement_paths):
        raise ValueError('value-flow caller requirements differ from its original selected target alternatives')
    return signature


def _validate_argument_value_flow(flow, *, caller, callee, signature=None, caller_source_text=None,
                                  load_body=None, load_signature=None, target=None, facts):
    if type(flow) is not StaticArgumentValueFlow:
        raise TypeError('argument value-flow reader requires its typed original relation')
    signature = _scope(flow, caller=caller, callee=callee, signature=signature,
        load_body=load_body, load_signature=load_signature, target=target, facts=facts)
    binding = _binding(flow.context, caller, signature, caller_source_text, facts)
    if binding is None or binding != flow.binding or binding.status is not CallBindingStatus.CONDITIONAL:
        raise ValueError('argument value flow differs from the original source/signature binding')
    port = flow.argument
    actual = caller.index.use_site(port.actual_use)
    interface = facts.body(callee).interface
    parameters = {parameter.slot: parameter for parameter in signature.parameters}
    formals = {formal.slot: formal.value for formal in interface.parameters}
    if (actual.operation != flow.context.operation or actual.use.value != port.actual_value
            or port.actual_use not in caller.index.operations[flow.context.operation].invoke_arguments
            or type(caller.index.values[port.actual_value]) is not ReferenceValue
            or formals.get(port.formal_slot) != port.formal_value
            or parameters[port.formal_slot].name != port.formal_name):
        raise ValueError('argument value flow changed its original actual/formal reference endpoint')
    if target is not None and (target.binding != binding or port not in target.arguments):
        raise ValueError('argument value flow is not an existing original target argument port')
    return True


def _validate_return_value_flow(flow, *, caller, callee, signature=None, caller_source_text=None,
                                load_body=None, load_signature=None, target=None, facts):
    if type(flow) is not StaticReturnValueFlow:
        raise TypeError('return value-flow reader requires its typed original relation')
    signature = _scope(flow, caller=caller, callee=callee, signature=signature,
        load_body=load_body, load_signature=load_signature, target=target, facts=facts)
    binding = _binding(flow.context, caller, signature, caller_source_text, facts)
    if binding is None or binding.status is CallBindingStatus.INCOMPATIBLE:
        raise ValueError('normal return value flow has no compatible original entry binding')
    if _completion(caller, callee, flow.context, facts) != flow.completion:
        raise ValueError('return value flow changed original normal landing/terminal ports')
    if target is not None and flow.completion not in target.completions:
        raise ValueError('return value flow is not an existing original target completion port')
    return True


def validate_argument_value_flow(flow, *, caller, callee, signature=None, caller_source_text=None,
                                 load_body=None, load_signature=None, target=None):
    """Fresh standalone verification; no prior check is accepted as authority."""
    return _validate_argument_value_flow(flow, caller=caller, callee=callee, signature=signature,
        caller_source_text=caller_source_text, load_body=load_body, load_signature=load_signature,
        target=target, facts=_ValueFacts(caller, callee))


def validate_return_value_flow(flow, *, caller, callee, signature=None, caller_source_text=None,
                               load_body=None, load_signature=None, target=None):
    """Fresh standalone verification of the original selected return terminal."""
    return _validate_return_value_flow(flow, caller=caller, callee=callee, signature=signature,
        caller_source_text=caller_source_text, load_body=load_body, load_signature=load_signature,
        target=target, facts=_ValueFacts(caller, callee))


def derive_static_value_flows(*, caller, callee, call_operation, callee_use, target,
                              signature=None, requirements=(), caller_source_text=None,
                              load_body=None, load_signature=None):
    """Return argument edges, return edges and precise unconnected frontiers.

    Only existing explicit SourceArgumentPorts and normal reference completion
    routes are projected. Defaults, packing and unknown actuals never invent
    formal aliases. Conditions describe the caller stack for each edge; a
    consumer must not use an empty summary for an exact nonempty requirement.
    """
    if target.body is None or callee_use is None:
        return (), (), (StaticCallFrontier('CALL_VALUE_INTERFACE_UNAVAILABLE',
            'A qualified callee body and original callable Use are required for value routing.'),)
    use = caller.index.use_site(callee_use)
    facts = _ValueFacts(caller, callee)
    context = StaticCallContext(caller.namespace, call_operation, callee_use, use.use.value,
                                target.definition, callee.namespace)
    _validate_call_context(context, caller=caller, callee=callee, facts=facts)
    signature = _signature(callee, signature, facts)
    if signature is None or signature.kind is not FunctionKind.SYNC:
        return (), (), (StaticCallFrontier('SYNCHRONOUS_VALUE_BODY_UNAVAILABLE',
            'No original synchronous source signature/body is available; async/generator creation is not a body return.'),)
    binding = _binding(context, caller, signature, caller_source_text, facts)
    if binding is None or binding.status is CallBindingStatus.INCOMPATIBLE:
        return (), (), (StaticCallFrontier('CALL_VALUE_ENTRY_BINDING_OPEN',
            'Original call/source binding is unavailable or incompatible with entry; no normal reference route is admitted.'),)
    if target.binding is not None and target.binding != binding:
        raise ValueError('target binding differs from independently reconstructed call/source arguments')
    common = dict(caller=caller, callee=callee, signature=signature, caller_source_text=caller_source_text,
                  load_body=load_body, load_signature=load_signature, target=target, facts=facts)
    arguments = []
    if binding.status is CallBindingStatus.CONDITIONAL:
        for port in target.arguments:
            flow = StaticArgumentValueFlow(context, binding, port, requirements=requirements)
            _validate_argument_value_flow(flow, **common)
            arguments.append(flow)
    returns = []
    completion = _completion(caller, callee, context, facts)
    if completion is not None:
        for original in target.completions:
            if original != completion:
                continue
            for terminal in original.terminals:
                flow = StaticReturnValueFlow(context, original, terminal, requirements=requirements)
                _validate_return_value_flow(flow, **common)
                returns.append(flow)
    return tuple(arguments), tuple(returns), ()


__all__ = ['derive_static_value_flows', 'validate_call_context',
           'validate_argument_value_flow', 'validate_return_value_flow']
