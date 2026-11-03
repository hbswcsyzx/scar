"""Replay source/compiler proofs for call-independent factory entry origins.

Inputs are already receipt-checked original bodies supplied by their owner.
This module performs no file lookup, import, execution, discovery or publication.
Compiling retained text creates compiler evidence only, never a target object.
"""
from __future__ import annotations

import ast
from dataclasses import replace
import hashlib
import sys
from types import CodeType

from scar.analysis.static_compilation import StaticCodeEvidence, _scope_nodes
from scar.analysis.static_function_environment import _EnvironmentFacts, _factory, _roles
from scar.ir.program.environments import EnvironmentRole
from scar.ir.program.function_origins import StaticFactoryEntryOrigin
from scar.ir.program.model import ReferenceValue
from scar.ir.program.source_language import decode_language_overlay
from scar.ir.program.source_subjects import SourceCompilationCodeRef
from scar.ir.program.static_calls import StaticFunctionCreationRoute
from scar.ir.record_codec import encode
from scar.trace.code_snapshot import code_key


def _span(source):
    return source.start_line, source.end_line, source.start_column, source.end_column


def _select_code(root, path):
    code = root
    for position in path:
        if (type(position) is not int or position < 0 or position >= len(code.co_consts)
                or type(code.co_consts[position]) is not CodeType):
            raise ValueError("factory origin compiler path does not select an original code constant")
        code = code.co_consts[position]
    return code


def _replay_compilation(inputs, root, namespace_root):
    """Validate either original frame CodeRef or function CodeEvidence."""
    document, sources = inputs.document, inputs.sources
    if document.get("module") is not None:
        reference = sources.declaration.compilation
    elif document.get("class") is not None:
        from scar.ir.program.class_entries import decode_class_entry_overlay
        reference = decode_class_entry_overlay(document["class"]).compilation
    else:
        reference = None
    if reference is not None:
        if type(reference) is not SourceCompilationCodeRef:
            raise TypeError("factory origin frame needs its exact source compilation CodeRef")
        reference.__post_init__()
        if (reference.definition != inputs.namespace.definition
                or reference.compiler_implementation != sys.implementation.name
                or reference.compiler_version != tuple(sys.version_info[:3])
                or reference.compiler_python != sys.version
                or reference.compiler_cache_tag != sys.implementation.cache_tag):
            raise ValueError("factory origin frame compiler/definition differs")
        code = _select_code(root, reference.code_path)
        if inputs.namespace.source is None and reference.source.namespace_root != namespace_root:
            raise ValueError("factory origin module namespace root differs from its qualified definition")
        replay = StaticCodeEvidence(inputs.metadata.source, namespace_root,
            inputs.namespace.definition, reference.source, reference.code_path, code, code_key(code),
            reference.compiler_implementation, reference.compiler_version, reference.compiler_python,
            reference.compiler_cache_tag, reference.compile_mode, reference.compile_flags,
            reference.dont_inherit, reference.optimize, code_key(root))
        # namespace_root is absent from the class CodeRef itself.  Its source
        # and exact compiler path/layout are compared through to_reference().
        if replay.to_reference() != reference:
            raise ValueError("factory origin frame CodeRef differs from independent source compilation")
        return reference.code_path, code
    wire = document.get("static_compilation")
    if type(wire) is not dict:
        raise ValueError("factory origin body lacks original compiler evidence")
    compiler = wire.get("compiler", {})
    if (wire.get("namespace_root") != namespace_root
            or compiler.get("implementation") != sys.implementation.name
            or compiler.get("version") != list(sys.version_info[:3])
            or compiler.get("python") != sys.version
            or compiler.get("cache_tag") != sys.implementation.cache_tag
            or compiler.get("mode") != "exec" or compiler.get("flags") != 0
            or compiler.get("dont_inherit") is not True or compiler.get("optimize") != 0):
        raise ValueError("factory origin source compiler profile differs")
    path = wire.get("code_path")
    if type(path) is not list:
        raise ValueError("factory origin needs an exact original compiler path")
    code = _select_code(root, path)
    evidence = StaticCodeEvidence(inputs.metadata.source, wire["namespace_root"], inputs.namespace.definition,
        inputs.namespace.source, tuple(path), code, code_key(code), sys.implementation.name,
        tuple(sys.version_info[:3]), compiler["python"], sys.implementation.cache_tag,
        root_code_layout_key=code_key(root))
    expected = evidence.to_dict()
    if "layout" not in wire:
        expected.pop("layout")
    if encode(expected) != wire:
        raise ValueError("factory origin body compiler evidence differs from independent retained-source replay")
    return tuple(path), code


def _source_proof(creator, body, creation, source_text):
    snapshot = creator.metadata.source
    if (type(source_text) is not str or "sha256:" + hashlib.sha256(source_text.encode()).hexdigest() != snapshot.fingerprint
            or body.metadata.source != snapshot or creation.definition.snapshot != snapshot):
        raise ValueError("factory origin retained text/source versions differ")
    root = compile(source_text, snapshot.path, "exec", flags=0, dont_inherit=True, optimize=0)
    namespace_root = creation.definition.context.namespace_root
    creator_path, parent = _replay_compilation(creator, root, namespace_root)
    body_path, child = _replay_compilation(body, root, namespace_root)
    if (creation.code_layout_key != code_key(parent)
            or body_path != creator_path + creation.constant_path
            or _select_code(parent, creation.constant_path) is not child):
        raise ValueError("factory origin code Use/constant path does not select this body")
    tree = ast.parse(source_text, filename=snapshot.path, type_comments=True)
    scopes, issues = {}, []
    _scope_nodes(tree, root, (), ast.Module, scopes, issues)
    matches = [row for row in scopes.get(_span(creation.definition.source), ())
        if row[0] == body_path and row[1] is child and isinstance(row[2], (ast.FunctionDef, ast.AsyncFunctionDef))]
    if len(matches) != 1:
        raise ValueError("factory origin child is not its exact lexical source/CodeRef occurrence")
    if creator.namespace.source is not None:
        parents = [row for row in scopes.get(_span(creator.namespace.source), ())
            if row[0] == creator_path and row[1] is parent]
        if len(parents) != 1:
            raise ValueError("factory origin creator path does not match its original lexical source")
    if creator.document.get("class") is not None:
        from scar.ir.program.class_entries import decode_class_entry_overlay
        overlay = decode_class_entry_overlay(creator.document["class"])
        constants = overlay.constants
    else:
        constants = getattr(creator.sources, "constants", None)
    if constants is None:
        constants = decode_language_overlay(creator.document["language"]).constants
    selected = [row for row in constants if row.operation == creation.code_constant_operation]
    if len(selected) != 1 or selected[0].constant_path != creation.constant_path:
        raise ValueError("factory origin constant record changed its original code slot/source")
    if creator.document.get("class") is not None:
        code_value = creator.index.use_site(creation.code_use).use.value
        factories = [row for row in overlay.factories if row.operation == creation.factory]
        if (overlay.compilation.code_layout_key != creation.code_layout_key
                or selected[0].reference != code_value or len(factories) != 1
                or factories[0].definition != body.namespace.definition
                or factories[0].source != body.namespace.source
                or factories[0].code_reference != code_value
                or factories[0].reference != creation.normal_value
                or factories[0].constant_path != creation.constant_path):
            raise ValueError("factory class constant/factory record differs from its exact original compiler source")
    elif (selected[0].code_key != creation.code_layout_key
            or selected[0].source != creation.definition.source):
        raise ValueError("factory origin constant record changed its original code slot/source")


def derive_factory_entry_origins(*, creator_graph, creator_document, creator_namespace,
        body_graph, body_document, body_namespace, creation, source_text,
        creator_index=None, body_index=None, _facts=None, _creator_inputs=None, _body_inputs=None):
    """Derive only object/G reference origins, without selecting a caller.

    The supplied definition/namespace locators must already be verified by the
    enclosing reader.  Both source compilation paths are independently replayed;
    a supplied creation record or a common code name is not accepted as proof.
    """
    if type(creation) is not StaticFunctionCreationRoute:
        raise TypeError("factory origin needs its original typed creation record")
    creation.__post_init__()
    if _facts is None and (_creator_inputs is not None or _body_inputs is not None):
        raise ValueError('factory origin owned inputs require their original private owner')
    facts = _EnvironmentFacts() if _facts is None else _facts
    if type(facts) is not _EnvironmentFacts:
        raise TypeError('factory origin input owner must be _EnvironmentFacts')
    creator = facts.body(creator_graph, creator_document, creator_namespace, creator_index,
                         inputs=_creator_inputs)
    body = facts.body(body_graph, body_document, body_namespace, body_index, inputs=_body_inputs)
    if (body_namespace.definition != creation.definition.definition
            or body_namespace.source != creation.definition.source):
        raise ValueError("factory origin target differs from its original qualified definition")
    factory = _factory(creator.index, creator_document, creator.protocols, creation, inputs=creator)
    _source_proof(creator, body, creation, source_text)
    environments = [row for row in body_graph.environments
        if row.region == body_graph.root and row.code_definition == body_namespace.definition]
    if len(environments) != 1:
        raise ValueError("factory origin body lacks its original unique function environment")
    environment = environments[0]
    members = {member.role: member for member in environment.members}
    roles = _roles(creator_document, creator.index, factory, inputs=creator)
    captures = [use for use in factory.uses if roles.get(use.id, (None,))[0] == "function-globals"]
    if len(captures) != 1:
        raise ValueError("factory origin needs its unique original globals capture Use")
    capture = captures[0]
    # Module/nested source roles use a per-role ordinal.  Class-suite source
    # roles use their ordered primitive operand position (code=0, globals=1).
    # They are different existing ABIs, not interchangeable arbitrary indices.
    expected_position = 1 if creator_document.get("class") is not None else 0
    if roles[capture.id] != ("function-globals", expected_position):
        raise ValueError("factory globals role index differs from its original source-lowering ABI")
    if creator_document.get("module") is not None or creator_document.get("class") is not None:
        roots = creator_graph.frame_roots
        if len(roots) != 1:
            raise ValueError("factory origin creator lacks its unique original frame root")
        entry = roots[0].entry
        if creator_document.get("class") is not None:
            from scar.ir.program.source_subjects import ClassFrameABI
            if type(entry) is not ClassFrameABI:
                raise ValueError("factory class origin lacks its original class frame ABI")
            expected_globals = entry.mapping.globals_namespace
        else:
            from scar.ir.program.source_subjects import MappingFramePorts
            if type(entry) is not MappingFramePorts:
                raise ValueError("factory module origin lacks its original mapping frame ABI")
            expected_globals = entry.globals_namespace
    else:
        owners = [environment for environment in creator_graph.environments
            if environment.region == creator_graph.root and environment.code_definition == creator_namespace.definition]
        members_g = [member for environment in owners for member in environment.members
            if member.role is EnvironmentRole.GLOBALS_NAMESPACE]
        if len(owners) != 1 or len(members_g) != 1:
            raise ValueError("nested factory origin lacks its original function globals interface")
        expected_globals = members_g[0].reference
    if capture.value != expected_globals:
        raise ValueError("factory globals capture does not reference the creator authoritative globals port")
    result = []
    for role, use, value in ((EnvironmentRole.FUNCTION_OBJECT, None, creation.normal_value),
            (EnvironmentRole.GLOBALS_NAMESPACE, capture.id, capture.value)):
        member = members.get(role)
        if (member is None or type(creator.index.values[value]) is not ReferenceValue
                or type(body.index.values[member.reference]) is not ReferenceValue):
            raise ValueError("factory origin must connect existing function/reference ports")
        result.append(StaticFactoryEntryOrigin(creator_namespace, creation, body_namespace,
            environment.id, member, use, value))
    return tuple(result)


def validate_factory_entry_origin(origin, **inputs):
    """Freshly replay one derived record; no successful-validation cache."""
    if type(origin) is not StaticFactoryEntryOrigin:
        raise TypeError("expected a typed original factory entry origin")
    origin.__post_init__()
    if origin not in derive_factory_entry_origins(creation=origin.creation, **inputs):
        raise ValueError("factory entry origin changed its original captured/member ports")
    return True


def factory_entry_origin_evidence(origin, *, creator_document, body_document):
    """Original graph/compiler locators, never a fictitious saved origin row."""
    if type(origin) is not StaticFactoryEntryOrigin:
        raise TypeError("expected a typed factory entry origin")
    compiler = ("#/module/declaration/compilation" if creator_document.get("module") is not None else
        "#/class/compilation" if creator_document.get("class") is not None else "#/static_compilation")
    if body_document.get("static_compilation") is None:
        raise ValueError("factory origin evidence lacks original body compilation")
    return (origin.creator.graph, origin.body.graph,
        replace(origin.creator.graph, pointer=compiler), replace(origin.body.graph, pointer="#/static_compilation"))


def factory_entry_origin_ports(*, graph, document, namespace, index=None, _facts=None, _inputs=None):
    """Identify this adapter's original interface scope, not successful origins.

    An empty explicit origin list cannot close a real MAKE normal/capture port.
    Unsupported/unselected factory sources remain interfaces with open origins.
    """
    from scar.analysis.static_namespace import normal_reference
    if _facts is None and _inputs is not None:
        raise ValueError('factory origin ports need the original private input owner')
    owner = _EnvironmentFacts() if _facts is None else _facts
    if type(owner) is not _EnvironmentFacts:
        raise TypeError('factory origin port owner must be _EnvironmentFacts')
    facts = owner.body(graph, document, namespace, index, inputs=_inputs)
    incoming = frozenset(member.reference for environment in graph.environments
        if environment.region == graph.root and environment.code_definition == namespace.definition
        for member in environment.members if member.role in (
            EnvironmentRole.FUNCTION_OBJECT, EnvironmentRole.GLOBALS_NAMESPACE))
    outgoing = set()
    for operation in graph.operations:
        if facts.protocols.get(operation.id) not in ("MAKE_FUNCTION_314", "MAKE_NESTED_FUNCTION"):
            continue
        normal = normal_reference(facts.index, operation.id, blocks=facts.blocks)
        if normal is not None:
            outgoing.add(normal[1])
        roles = _roles(document, facts.index, operation, inputs=facts)
        outgoing.update(use.id for use in operation.uses if roles.get(use.id, (None,))[0] == "function-globals")
    return incoming, frozenset(outgoing)


__all__ = ["derive_factory_entry_origins", "validate_factory_entry_origin", "factory_entry_origin_evidence",
    "factory_entry_origin_ports"]
