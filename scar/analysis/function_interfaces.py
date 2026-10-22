"""Source adapters for function interfaces; no target imports or evaluation."""
import ast

from scar.ir.program.functions import (
    ArgumentKind, BodyEntryInterface, BodyLoweringProfile, CallArgument, FormalParameter,
    FunctionInterfaceIssue, FunctionInterfaces, FunctionKind, FunctionSignature, ParameterKind,
)
from scar.ir.program.model import BlockArgument, ReferenceValue, StateVersionValue
from scar.ir.program.source import SourceRole


def formal_nodes(node):
    args = node.args
    groups = ((args.posonlyargs, ParameterKind.POSITIONAL_ONLY), (args.args, ParameterKind.POSITIONAL),
              ((args.vararg,) if args.vararg else (), ParameterKind.VAR_POSITIONAL),
              (args.kwonlyargs, ParameterKind.KEYWORD_ONLY),
              ((args.kwarg,) if args.kwarg else (), ParameterKind.VAR_KEYWORD))
    return tuple((argument,kind) for values,kind in groups for argument in values)


def _span(node):
    return type(node).__name__, node.lineno, node.end_lineno, node.col_offset, node.end_col_offset


def _sources(context):
    return {(a.kind,a.reference.start_line,a.reference.end_line,a.reference.start_column,a.reference.end_column):a.reference
            for a in context.semantic.source_atoms.values()}


def _body_nodes(nodes):
    for node in nodes:
        if isinstance(node, (ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef,ast.Lambda)):
            continue
        yield node
        yield from _body_nodes(ast.iter_child_nodes(node))


def extract_signature(context, definition, *, node=None, sources=None, slots=None):
    sources = _sources(context) if sources is None else sources
    if node is None:
        matches = [n for n in ast.walk(context.tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.Lambda))
                   and sources.get(_span(n)) == definition.source]
        if len(matches) != 1:
            raise ValueError("signature needs one exact function source")
        node, = matches
    slots = ({(s.owner,s.name):s.slot_id for s in context.semantic.slots.values()} if slots is None else slots)
    positional = node.args.posonlyargs + node.args.args
    defaults = dict(zip((a.arg for a in positional[len(positional)-len(node.args.defaults):]), node.args.defaults))
    defaults.update({a.arg:v for a,v in zip(node.args.kwonlyargs,node.args.kw_defaults) if v is not None})
    parameters = tuple(FormalParameter(a.arg,kind,slots[definition.id,a.arg],sources[_span(a)],
                       sources[_span(defaults[a.arg])] if a.arg in defaults else None)
                       for a,kind in formal_nodes(node))
    body = [node.body] if isinstance(node,ast.Lambda) else node.body
    generator = any(isinstance(n,(ast.Yield,ast.YieldFrom)) for n in _body_nodes(body))
    asynchronous = isinstance(node,ast.AsyncFunctionDef)
    kind = (FunctionKind.ASYNC_GENERATOR if generator and asynchronous else FunctionKind.GENERATOR if generator
            else FunctionKind.ASYNC if asynchronous else FunctionKind.SYNC)
    return FunctionSignature(definition.id,definition.source,parameters,kind,
                             tuple(sources[_span(n)] for n in getattr(node,"decorator_list",())))


def validate_body_interface(body, interface, signature):
    if body.graph is None or interface.definition != signature.definition or interface.region != body.graph.root:
        raise ValueError("body interface differs from its source/root")
    graph = body.graph
    region = next(r for r in graph.regions if r.id == graph.root)
    entry = next(b for b in region.blocks if b.id == region.entry)
    values = {v.id:v for v in graph.values}
    if tuple(p.slot for p in interface.parameters) != tuple(p.slot for p in signature.parameters):
        raise ValueError("body interface does not cover the signature")
    offset = 0
    if interface.profile is BodyLoweringProfile.STRUCTURED_ENV:
        environments = {environment.id: environment for environment in graph.environments}
        layouts = [layout for layout in graph.function_entries
                   if environments[layout.environment].region == interface.region]
        if len(layouts) != 1 or layouts[0].parameters != interface.parameters:
            raise ValueError("environment body needs its exact function entry layout")
        environment = environments[layouts[0].environment]
        prefix = tuple(member.reference for member in environment.members)
        offset = len(prefix)
    else:
        prefix = ()
    if entry.arguments != (*prefix,*tuple(p.value for p in interface.parameters),interface.world):
        raise ValueError("formal/world ports differ from the body entry")
    for index,(parameter,port) in enumerate(zip(signature.parameters,interface.parameters)):
        value = values[port.value]
        if not isinstance(value,ReferenceValue) or value.origin != BlockArgument(entry.id,index + offset):
            raise ValueError("formal port is not an entry reference")
        if not any(link.value == port.value and link.slot == parameter.slot and link.source == parameter.source
                   and link.role is SourceRole.PARAMETER for link in body.metadata.value_links):
            raise ValueError("formal port lacks exact parameter source correspondence")
    world = values[interface.world]
    if not isinstance(world,StateVersionValue) or world.origin != BlockArgument(entry.id,len(interface.parameters) + offset):
        raise ValueError("body world port is not its own entry state")


class FunctionInterfaceBuilder:
    def __init__(self, *, profile=BodyLoweringProfile.BOUND_FORMALS):
        if type(profile) is not BodyLoweringProfile or profile not in (
                BodyLoweringProfile.BOUND_FORMALS, BodyLoweringProfile.BOUND_FRAME,
                BodyLoweringProfile.STRUCTURED_BODY, BodyLoweringProfile.STRUCTURED_ENV):
            raise ValueError("function interfaces require an explicit bound profile")
        self.profile = profile
        self.signatures, self.arguments, self.body_interfaces = {}, {}, {}
        self.issues = []

    def index_file(self, context, file, nodes):
        sources = _sources(context)
        slots = {(s.owner,s.name):s.slot_id for s in context.semantic.slots.values()}
        signatures, actuals, issues = {}, {}, []
        for definition in file.definitions:
            node = nodes[definition.id]
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.Lambda)):
                try:
                    signatures[definition.id] = extract_signature(context,definition,node=node,sources=sources,slots=slots)
                except (ValueError,KeyError) as error:
                    issues.append(FunctionInterfaceIssue(definition.source,"signature interface unavailable: " + str(error)))
        by_source = {sources[_span(n)].atom_id:n for n in ast.walk(context.tree) if isinstance(n,ast.Call)}
        for call in file.calls:
            node = by_source[call.source.atom_id]
            arguments = []
            for argument in node.args:
                kind = ArgumentKind.STARRED if isinstance(argument,ast.Starred) else ArgumentKind.POSITIONAL
                expression = argument.value if isinstance(argument,ast.Starred) else argument
                arguments.append(CallArgument(len(arguments),sources[_span(expression)],kind))
            for keyword in node.keywords:
                kind = ArgumentKind.KEYWORD if keyword.arg is not None else ArgumentKind.DOUBLE_STARRED
                arguments.append(CallArgument(len(arguments),sources[_span(keyword.value)],kind,keyword.arg))
            actuals[call.operation] = tuple(arguments)
        # Publish a complete file snapshot together, never a half-indexed file.
        self.signatures.update(signatures)
        self.arguments.update(actuals)
        self.issues.extend(issues)

    def record_body(self, body, interface):
        from dataclasses import replace
        if body.graph is None:
            if interface is not None:
                raise ValueError("failed body cannot retain entry ports")
            return
        if interface is None:
            raise ValueError("bound body needs explicit entry ports")
        if interface.profile is not self.profile:
            raise ValueError("body interface profile differs from its inventory")
        signature = self.signatures[body.definition]
        validate_body_interface(body,interface,signature)
        operations = {op.id:op for op in body.graph.operations}
        use_sources = {(link.operation,link.use):link.source for link in body.metadata.use_links}
        argument_updates = {}
        for link in body.metadata.operation_links:
            arguments = self.arguments.get(link.semantic_operation)
            if arguments is None:
                continue
            operation = operations[link.operation]
            if len(operation.invoke_arguments) != len(arguments) + 2:
                continue
            updated = []
            for index,argument in enumerate(arguments):
                use = operation.invoke_arguments[index+1]
                if use_sources.get((operation.id,use)) != argument.source:
                    raise ValueError("call argument differs from its exact use source")
                updated.append(replace(argument,use=use))
            argument_updates[link.semantic_operation] = tuple(updated)
        self.arguments.update(argument_updates)
        self.body_interfaces[body.definition] = interface

    def finish(self, files):
        from scar.analysis.function_binding import bind_call
        bindings = []
        for file in files:
            for call in file.calls:
                for target in call.candidates:
                    bindings.append(bind_call(self.signatures.get(target),call=call.operation,target=target,
                                              source=call.source,arguments=self.arguments[call.operation]))
        return FunctionInterfaces(tuple(self.signatures.values()),tuple(self.body_interfaces.values()),
                                  tuple(bindings),tuple(self.issues),self.profile)
