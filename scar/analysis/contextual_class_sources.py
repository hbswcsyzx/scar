"""Fresh source/compiler checks for original class-statement CALL sources.

Only existing construction and graph records are consumed. Retained source is
compiled for code-layout evidence, never imported, executed or lowered again.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import sys
from types import SimpleNamespace

from scar.analysis.source_class_construction_validation import validate_class_constructions
from scar.analysis.static_compilation import StaticCodeEvidence
from scar.analysis.static_function_origins import _replay_compilation
from scar.ir.program.class_call_sources import ContextualClassStatementSource
from scar.ir.program.dependencies import (
    DependencyCondition as Condition, DependencyEvidence as Evidence,
    DependencyPoint as Point,
)
from scar.ir.program.ids import OperationID, ValueID
from scar.ir.program.model import ExitKind
from scar.ir.program.source_language import decode_language_overlay
from scar.ir.program.structured import PythonProtocol
from scar.ir.record_codec import decode, encode
from scar.trace.code_snapshot import code_key


def _need(ok, detail):
    if not ok:
        raise ValueError('contextual class source: ' + detail)


@dataclass(frozen=True, slots=True)
class _ClassInputs:
    graph: object
    document: dict
    records: tuple
    by_result: dict
    protocols: dict
    language: object
    table: str


class ClassStatementSourceExtractor:
    """One shared-reader batch index; successful verification is not cached."""

    def __init__(self, resolver):
        self.resolver = resolver

    def _inputs(self, body):
        # Class suites currently have no nested ClassConstruction table. Their
        # method factories and classcell/None completions are not class sources.
        if body.document.get('class') is not None:
            return None
        if body.module is not None:
            records = tuple(getattr(body.module, 'class_constructions', ()))
            if not records:
                return None
        else:
            language = body.document.get('language')
            if not language or not language.get('class_constructions'):
                return None
        session = self.resolver.session
        key = ('contextual-class-source-inputs', body.namespace)
        saved = session._get(key)
        if saved is not None and saved.graph is body.graph and saved.document is body.document:
            return saved
        if body.module is not None:
            language = None
            protocols = {row.operation: row for row in body.module.protocols}
            _need(len(protocols) == len(body.module.protocols), 'duplicate original mapping protocol')
            table = 'module'
        else:
            language = decode_language_overlay(body.document['language'])
            records = language.class_constructions
            structured = body.document.get('structured')
            _need(type(structured) is dict, 'function construction lost its original structured protocols')
            markers = tuple(decode(PythonProtocol, row) for row in structured['protocols'])
            protocols = {row.operation: row for row in markers}
            _need(len(protocols) == len(markers), 'duplicate original construction protocol')
            table = 'language'
        by_result = {}
        for number, record in enumerate(records):
            _need(record.result not in by_result, 'multiple class records claim one final result')
            by_result[record.result] = number
        saved = _ClassInputs(body.graph, body.document, records, by_result, protocols, language, table)
        # The index retains these original input objects, so charge their full
        # decoded body size to the existing owner's metered LRU.
        return session._put(key, saved, body.namespace.graph.decoded_bytes +
            256 * (len(records) + len(protocols)))

    def _compiler(self, body):
        context = body.context
        text = context.docs['source']['text']
        _need(type(text) is str and 'sha256:' + hashlib.sha256(text.encode()).hexdigest()
            == body.metadata.source.fingerprint, 'retained source fingerprint differs')
        root = getattr(context, 'compiled_module_for_namespace', None)
        if root is None:
            root = compile(text, body.metadata.source.path, 'exec', flags=0,
                dont_inherit=True, optimize=0)
            context.compiled_module_for_namespace = root
            context.compiled_module_layout_for_namespace = code_key(root)
        inputs = SimpleNamespace(document=body.document, metadata=body.metadata,
            sources=body.module if body.module is not None else body.metadata, namespace=body.namespace)
        namespace_root = context.unit['namespace_root']
        path, code = _replay_compilation(inputs, root, namespace_root)
        source = body.module.declaration.unit if body.module is not None else body.namespace.source
        return StaticCodeEvidence(body.metadata.source, namespace_root, body.namespace.definition,
            source, path, code, code_key(code), sys.implementation.name, tuple(sys.version_info[:3]),
            sys.version, sys.implementation.cache_tag, root_code_layout_key=code_key(root))

    def _verify(self, body, inputs):
        self.resolver.owner._check()
        evidence = self._compiler(body)
        if inputs.language is not None:
            # The independently replayed original artifact profile also owns
            # this language table; no later manifest plan may replace it.
            _need(encode(inputs.language.code_evidence) == encode(body.document['static_compilation']),
                'language compiler receipt differs from the independently replayed original body')
        validate_class_constructions(graph=body.graph, metadata=body.metadata,
            records=inputs.records, protocols=inputs.protocols,
            code_evidence=evidence, source_tree=body.context.tree,
            semantic=body.context.semantic, interface=body.interface,
            module_overlay=body.module, constants=inputs.language.constants
                if inputs.language is not None else (), structural_only=False)
        self.resolver.owner._check()

    def source_at(self, call, callable, source, path):
        if type(source.node) is not ValueID or source.namespace.source_body is None:
            return None
        body = self.resolver._body(source.namespace)
        inputs = self._inputs(body)
        if inputs is None or source.node not in inputs.by_result:
            return None
        self._verify(body, inputs)
        number = inputs.by_result[source.node]
        construction = inputs.records[number]
        locator = replace(source.namespace.graph,
            pointer='#/' + inputs.table + '/class_constructions/' + str(number))
        conditions = dict.fromkeys(condition for edge in path for condition in edge.conditions)
        anchors = [source, callable, call]
        for ports in (construction.builder_call, *(row.call for row in construction.decorators)):
            operation = body.index.operations[ports.operation]
            normals = [(index, edge) for index, edge in enumerate(operation.terminator.successors)
                       if edge.kind is ExitKind.NORMAL]
            _need(len(normals) == 1 and normals[0][1].block == ports.normal,
                'class source stage lost its actual NORMAL completion')
            point = Point(source.namespace, operation.id, source.context)
            conditions[Condition('canonical', 'SUCCESSOR_SELECTED', point, normals[0][0])] = None
            anchors.extend((point, Point(source.namespace, ports.result, source.context),
                Point(source.namespace, ports.normal_world, source.context)))
        compiler_locator = replace(source.namespace.graph,
            pointer='#/module/declaration/compilation' if body.module is not None else '#/static_compilation')
        evidence = tuple(dict.fromkeys((*(item for edge in path for item in edge.evidence),
            Evidence('SOURCE_CLASS_STATEMENT_FINAL_PRODUCT_V1',
                (locator, compiler_locator, source.namespace.graph), tuple(dict.fromkeys(anchors))))))
        return ContextualClassStatementSource(call, callable, source, construction, locator,
            tuple(path), evidence, tuple(conditions))


def validate_class_statement_source(resolver, source):
    """Replay original construction fields and every shared-graph path edge."""
    if type(source) is not ContextualClassStatementSource:
        raise TypeError('expected ContextualClassStatementSource')
    source.__post_init__()
    body = resolver._body(source.call.namespace)
    _need(type(source.call.node) is OperationID and source.call.node in resolver._calls(body),
        'source selection is not an actual original CALL')
    callee = [row.use for row in body.uses_by_op.get(source.call.node, ()) if row.role == 'callee']
    _need(callee == [source.callable.node], 'source substituted the original callable operand')
    for edge in source.path:
        resolver.owner._check()
        _need(resolver._transport(edge), 'source path is not a legal original reference route')
        neighborhood = resolver.session.graph().incoming(edge.target, kinds=(edge.kind,))
        _need(edge in neighborhood.edges, 'source path differs from fresh original graph evidence')
    extractor = getattr(resolver, '_class_source_extractor', None)
    if extractor is None:
        extractor = ClassStatementSourceExtractor(resolver)
    expected = extractor.source_at(source.call, source.callable, source.source, source.path)
    _need(expected == source, 'class statement source fields, guards or source/compiler evidence differ')
    return True


__all__ = ['ClassStatementSourceExtractor', 'validate_class_statement_source']
