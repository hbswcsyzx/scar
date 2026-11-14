"""Match compiler-created annotation callbacks to existing sealed F4 requests.

Only original CodeType constants, finite creation instructions, F2 slots and
C3 scope roles select a request. Code names and callable/namespace values do
not select it. No target execution, function fact or argument binder is added.
"""
from collections import defaultdict
from dataclasses import dataclass
import dis
from hashlib import sha256
from pathlib import Path
from types import CodeType

from scar.analysis.source_namespace_interfaces import NamespacePlanView
from scar.ir.program import source_productions as P, normal_targets as T
from scar.ir.program.source_observed_codes import ObservedSourceRequestKind as Kind
from scar.ir.program.source_template_links import SourceTemplateKey
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.record_codec import encode
from scar.trace.code_snapshot import describe_code


@dataclass(frozen=True)
class _Function:
    path: tuple
    code: CodeType
    span: tuple
    load: int
    make: int


def _span(syntax, occurrence):
    node = syntax.nodes[occurrence]
    schema = next(s for s in syntax.profile.ast_schema if s.name == node.constructor)
    attrs = dict(zip(schema.attributes, (v.scalar.to_python() if v.kind == 'SCALAR' else None
        for v in node.attributes)))
    return tuple(attrs.get(k) for k in ('lineno', 'end_lineno', 'col_offset', 'end_col_offset'))


def _creations(root):
    """Conservative straight-line provenance; unsupported stack work resets it.

    A function token survives only reviewed function/closure construction and
    SET_FUNCTION_ATTRIBUTE operations. In particular a CALL cannot fabricate
    callback provenance. Fixed publication names below are compiler protocols,
    not comparisons with a callback's co_name/co_qualname.
    """
    pending = [((), root)]; loads = {}; result = []; publications = set()
    while pending:
        path, code = pending.pop(); stack = []
        def pop(count=1):
            if count > len(stack):
                stack.clear(); return [None] * count
            values = stack[-count:] if count else []
            if count: del stack[-count:]
            return values
        for ins in dis.get_instructions(code, adaptive=False, show_caches=False):
            op = ins.opname
            if op == 'LOAD_CONST':
                if type(ins.argval) is CodeType:
                    child = (*path, ins.arg)
                    loads[child] = tuple(ins.positions)
                    pending.append((child, ins.argval))
                    stack.append((child, ins.argval, tuple(ins.positions), ins.offset))
                else: stack.append(None)
            elif op == 'MAKE_FUNCTION':
                value = pop()[0]
                stack.append(_Function(*value, ins.offset) if type(value) is tuple else None)
            elif op == 'SET_FUNCTION_ATTRIBUTE':
                attribute, function = pop(2)
                if ins.arg == 0x10 and type(attribute) is _Function and type(function) is _Function:
                    result.append((Kind.FUNCTION_ANNOTATIONS, attribute, function.span, path, ins.offset))
                stack.append(function if type(function) is _Function else None)
            elif op in ('STORE_NAME', 'STORE_GLOBAL', 'STORE_FAST', 'STORE_DEREF'):
                value = pop()[0]
                publication = ((not path and ins.argval == '__annotate__' and path not in publications)
                    or (bool(path) and ins.argval == '__annotate_func__'))
                if op in ('STORE_NAME', 'STORE_GLOBAL') and publication and type(value) is _Function:
                    result.append((None, value, None, path, ins.offset)); publications.add(path)
            elif op in ('LOAD_FAST', 'LOAD_FAST_BORROW', 'LOAD_DEREF', 'LOAD_CLOSURE', 'LOAD_NAME'):
                stack.append(None)
            elif op == 'LOAD_GLOBAL':
                stack.extend([None] * (1 + bool(ins.arg & 1)))
            elif op in ('BUILD_TUPLE', 'BUILD_LIST', 'BUILD_SET', 'BUILD_MAP', 'BUILD_CONST_KEY_MAP'):
                count = ins.arg * 2 if op == 'BUILD_MAP' else ins.arg + (op == 'BUILD_CONST_KEY_MAP')
                pop(count); stack.append(None)
            elif op == 'COPY' and 0 < ins.arg <= len(stack): stack.append(stack[-ins.arg])
            elif op == 'SWAP' and 0 < ins.arg <= len(stack): stack[-1], stack[-ins.arg] = stack[-ins.arg], stack[-1]
            elif op not in ('NOP', 'RESUME', 'COPY_FREE_VARS', 'EXTENDED_ARG', 'NOT_TAKEN'):
                stack.clear()
    return result, loads


def _recipe_reference(material, key, step_index):
    """Retain the real table receipt and its exact record/step coordinates."""
    node = material.interfaces['nodes'][key]; domain = node.origin.domain.value
    report = getattr(material, 'report', {})
    if report.get('schema') == 'scar.observed-compiled-local-material':
        descriptor = report['tables'][domain]; path = material.path / descriptor['path']
        schema = 'scar.sealed-source-recipe-json'; coordinate = 'records'
    elif hasattr(material, 'descriptor'):
        descriptor = material.descriptor['tables'][domain]
        path = material.root / material.descriptor['path'] / descriptor['path']
        schema = 'scar.sealed-source-recipe-jsonl'; coordinate = 'lines'
    else:
        import json
        from scar.analysis.source_template_links import _worker_stores
        report = json.loads(material._template_raw)
        specs = tuple((p['domain'], p['materials'], p['verification'], p['collection_sha256'],
            p['verification_sha256']) for p in report['parents'])
        store = next(s for s in _worker_stores(specs, report['model_manifest_sha256']) if s.domain.value == domain)
        descriptor = store.rows[material.unit]['artifact']; path = store.root / descriptor['path']
        schema = 'scar.sealed-source-recipe-fragment-jsonl'; coordinate = 'lines'
    raw = path.read_bytes()
    if len(raw) != descriptor['bytes'] or sha256(raw).hexdigest() != descriptor['sha256']:
        raise ValueError('request recipe evidence table differs from its sealed receipt')
    locator = '#/' + coordinate + '/' + str(node.origin.line - 1)
    if schema == 'scar.sealed-source-recipe-fragment-jsonl': locator += '/plan'
    locator += '/steps/' + str(step_index)
    return ProviderFactReference(ProviderArtifact(str(path), descriptor['sha256'], descriptor['bytes'], schema), locator)


def request_candidates(material, syntax, topology, root, observed):
    """Yield exact original request declarations and captured compiler children."""
    if topology.status != 'PROJECTED': raise ValueError('request code needs original projected compiler topology')
    spans = defaultdict(list)
    for i, node in enumerate(syntax.nodes):
        if node.constructor in ('FunctionDef', 'AsyncFunctionDef', 'ClassDef'): spans[_span(syntax, i)].append(i)
    scopes = defaultdict(list)
    for block in topology.blocks:
        if block.origin.role in ('HEADER_ANNOTATIONS', 'VARIABLE_ANNOTATIONS') and block.source_scope is not None:
            scopes[block.origin.occurrence, block.origin.role].append(block.source_scope)
    captures = defaultdict(list)
    for capture in observed: captures[capture.code.key].append(capture)
    creations, loads = _creations(root); selected = []
    for kind, function, span, parent, install in creations:
        matched = tuple(c for c in captures.get(describe_code(function.code)['key'], ())
            if encode(c.code) == describe_code(function.code))
        if not matched: continue
        if kind is Kind.FUNCTION_ANNOTATIONS:
            owners = [i for i in spans[span] if syntax.nodes[i].constructor in ('FunctionDef', 'AsyncFunctionDef')]
            role = 'HEADER_ANNOTATIONS'
        else:
            owners = ([syntax.root] if not parent else
                [i for i in spans[loads.get(parent)] if syntax.nodes[i].constructor == 'ClassDef'])
            kind = Kind.MODULE_ANNOTATIONS if not parent else Kind.CLASS_ANNOTATIONS
            role = 'VARIABLE_ANNOTATIONS'
        if len(owners) != 1 or len(scopes[owners[0], role]) != 1: continue
        owner = owners[0]; scope = scopes[owner, role][0]
        if kind is Kind.CLASS_ANNOTATIONS:
            first, _, column, _ = _span(syntax, owner)
            # CPython's implicit class publication uses the class-entry
            # zero-width location, unlike an explicitly defined source method.
            if function.span != (first, first, column, column): continue
        key = SourceTemplateKey(owner, P.ProductionPurpose.ROOT if owner == syntax.root else P.ProductionPurpose.STATEMENT)
        if key in material.interfaces['nodes']: selected.append((kind, function, parent, install, scope, key, matched))
    plans = material.plans(tuple(dict.fromkeys(row[5] for row in selected)))
    declarations = {Kind.FUNCTION_ANNOTATIONS:P.BuildFunctionAnnotations,
        Kind.CLASS_ANNOTATIONS:P.BuildClassAnnotations, Kind.MODULE_ANNOTATIONS:P.BuildScopeAnnotations}
    for kind, function, parent, install, scope, key, matched in selected:
        plan = plans[key]; view = NamespacePlanView(material.unit, plan)
        candidates = [(i, step) for i, step in enumerate(plan.steps)
            if type(step.instruction) is declarations[kind] and step.instruction.annotations.scope == scope]
        if len(candidates) != 1: continue
        index, step = candidates[0]; body = view.regions[step.instruction.body]
        first = view.steps[body.steps[0]]
        if type(first.instruction) is not P.EnterEvaluationRequest:
            raise ValueError('annotation declaration lost its original request activation')
        environment = first.instruction.environment
        if environment.scope != scope or view.owner(body.id).source_scope != scope:
            raise ValueError('compiler/source annotation scope differs from sealed request')
        yield dict(kind=kind, declaration=_recipe_reference(material, key, index),
            declaration_step=step.id, plan_sha256=material.interfaces['nodes'][key].origin.plan_sha256,
            callable=view.result(step), body=T.Body(material.unit, key, body.id), scope=view.owner(body.id),
            environment=environment, captures=matched, constant_path=function.path,
            creator_constant_path=parent, load_offset=function.load, make_offset=function.make,
            installation_offset=install)
    material.validate_parents()
