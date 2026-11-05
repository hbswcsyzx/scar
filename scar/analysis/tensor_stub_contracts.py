"""Read installed Tensor interface declarations without importing torch.

Annotations describe conditional types, not object/storage identity, runtime
member lookup, argument acceptance, native dispatch, or resource placement.
Unknown annotations remain OPEN with their original syntax and source span.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re


_CONDITIONS = (
    'DECLARATION_CONFORMANCE',
    'TENSOR_DESCRIPTOR_LOOKUP_MATCHES_DECLARATION',
    'TORCH_FUNCTION_OVERRIDE_PATH_NOT_SELECTED',
    'TORCH_DISPATCH_OVERRIDE_PATH_NOT_SELECTED',
)
_TENSORS = {
    'torch.Tensor', 'torch._tensor.Tensor', 'torch._C.Tensor',
    'torch._C.TensorBase', 'torch._C._TensorBase',
}
_PRIMITIVES = {
    name: name for name in ('bool', 'int', 'float', 'complex', 'str', 'bytes')
}
_PRIMITIVES.update({'builtins.' + name: name for name in tuple(_PRIMITIVES)})
_PRIMITIVES.update({'torch.types._' + name: name
                    for name in ('bool', 'int', 'float', 'complex', 'str', 'bytes')})
_CONTAINERS = {
    'list': 'LIST', 'builtins.list': 'LIST', 'typing.List': 'LIST',
    'tuple': 'TUPLE', 'builtins.tuple': 'TUPLE', 'typing.Tuple': 'TUPLE',
    'collections.abc.Iterator': 'ITERATOR', 'typing.Iterator': 'ITERATOR',
}


def _name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _name(node.value)
        return None if prefix is None else prefix + '.' + node.attr
    return None


class _Source:
    def __init__(self, path, module, role, index):
        self.path = path.resolve()
        self.raw = self.path.read_bytes()
        self.text = self.raw.decode('utf-8')
        self.tree = ast.parse(self.text, filename=str(self.path), type_comments=True)
        self.module, self.index = module, index
        self.receipt = dict(path=str(self.path), sha256=sha256(self.raw).hexdigest(),
                            size_bytes=len(self.raw), module=module, role=role)
        self.offsets = [0]
        for line in self.raw.splitlines(keepends=True):
            self.offsets.append(self.offsets[-1] + len(line))
        self.aliases = {}
        for node in self.tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.aliases[alias.asname or alias.name.split('.')[0]] = (
                        alias.name if alias.asname else alias.name.split('.')[0])
            elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
                for alias in node.names:
                    if alias.name != '*':
                        self.aliases[alias.asname or alias.name] = node.module + '.' + alias.name
        self.typevars = {}
        for node in self.tree.body:
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
                continue
            if self.resolve(node.value.func) not in ('typing.TypeVar', 'typing_extensions.TypeVar'):
                continue
            bound = next((k.value for k in node.value.keywords if k.arg == 'bound'), None)
            if bound is not None:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self.typevars[target.id] = bound

    def resolve(self, node):
        name = _name(node)
        if name is None:
            return None
        root, dot, tail = name.partition('.')
        return self.aliases.get(root, root) + (dot + tail if dot else '')

    def syntax(self, node):
        return None if node is None else ast.get_source_segment(self.text, node)

    def span(self, node):
        return dict(lineno=node.lineno, col_offset=node.col_offset,
                    end_lineno=node.end_lineno, end_col_offset=node.end_col_offset,
                    byte_start=self.offsets[node.lineno - 1] + node.col_offset,
                    byte_end=self.offsets[node.end_lineno - 1] + node.end_col_offset)

    def identity(self, occurrence):
        return sha256((self.receipt['sha256'] + ':' + occurrence).encode()).hexdigest()


def _annotation(source, node, tensor_names, depth=0):
    """Classify syntax only; never evaluate a forward reference or alias."""
    result = dict(kind='OPEN', annotation=source.syntax(node),
                  ast=None if node is None else ast.dump(node, include_attributes=False))
    if node is None or depth > 32:
        result['reason'] = 'MISSING_ANNOTATION' if node is None else 'ANNOTATION_DEPTH_FRONTIER'
        return result
    child = lambda value: _annotation(source, value, tensor_names, depth + 1)
    if isinstance(node, ast.Constant):
        if node.value is None:
            result['kind'] = 'NONE'
        elif isinstance(node.value, str):
            try:
                parsed = ast.parse(node.value, mode='eval').body
            except (SyntaxError, ValueError):
                result['reason'] = 'UNPARSED_FORWARD_REFERENCE'
            else:
                # Parsed nodes refer to the string, not the installed file.
                forward = _annotation(_ForwardSource(source, node.value), parsed,
                                      tensor_names, depth + 1)
                result.update({k: v for k, v in forward.items() if k not in ('annotation', 'ast')})
                result['forward_reference'] = True
        return result
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        result.update(kind='UNION', items=[child(node.left), child(node.right)])
        return result
    name = source.resolve(node.value if isinstance(node, ast.Subscript) else node)
    if name in tensor_names:
        result.update(kind='TENSOR', declared_type=name)
    elif name in ('typing.Self', 'typing_extensions.Self'):
        result['kind'] = 'SELF'
    elif name in _PRIMITIVES:
        result.update(kind='PRIMITIVE', python_type=_PRIMITIVES[name])
    elif name in ('torch.types.Number', 'numbers.Number'):
        result['kind'] = 'NUMBER'
    elif name in ('numpy.ndarray', 'numpy.typing.NDArray'):
        result['kind'] = 'NDARRAY'
    elif name in _CONTAINERS:
        kind = _CONTAINERS[name]
        result['kind'] = kind
        if isinstance(node, ast.Subscript):
            args = list(node.slice.elts) if isinstance(node.slice, ast.Tuple) else [node.slice]
            if kind == 'TUPLE':
                variadic = (len(args) == 2 and isinstance(args[-1], ast.Constant)
                            and args[-1].value is Ellipsis)
                result['variadic'] = variadic
                if variadic:
                    result['element'] = child(args[0])
                else:
                    result['items'] = [child(arg) for arg in args]
            else:
                if len(args) == 1:
                    result['element'] = child(args[0])
                else:
                    result.update(kind='OPEN', reason='UNSUPPORTED_CONTAINER_ARGUMENTS')
        else:
            result['element'] = child(None)
            if kind == 'TUPLE':
                result['variadic'] = True
    elif isinstance(node, ast.Subscript) and name in ('typing.Union', 'typing.Optional'):
        args = list(node.slice.elts) if isinstance(node.slice, ast.Tuple) else [node.slice]
        result.update(kind='UNION', items=[child(arg) for arg in args])
        if name == 'typing.Optional':
            result['items'].append(dict(kind='NONE', annotation='None', ast='Constant(value=None)'))
    elif isinstance(node, ast.Name) and node.id in source.typevars:
        bound = _annotation(getattr(source, 'typevar_source', source),
                            source.typevars[node.id], tensor_names, depth + 1)
        result.update(kind='TENSOR' if bound['kind'] == 'TENSOR' else 'OPEN',
                      type_variable=node.id, bound=bound)
    else:
        result['reason'] = 'UNRESOLVED_DECLARED_TYPE'
    if name is not None:
        result['reference'] = name
    if isinstance(node, ast.Subscript) and result['kind'] in ('OPEN', 'NDARRAY'):
        args = node.slice.elts if isinstance(node.slice, ast.Tuple) else (node.slice,)
        result['arguments'] = [child(arg) for arg in args]
    return result


class _ForwardSource:
    def __init__(self, source, text):
        self.text, self.aliases, self.typevars = text, source.aliases, source.typevars
        self.typevar_source = getattr(source, 'typevar_source', source)

    resolve = _Source.resolve
    syntax = _Source.syntax


def _member(source, owner, node, occurrence, tensor_names, ordinal):
    decorators = [source.resolve(d) or ast.unparse(d) for d in node.decorator_list]
    short = [d.rsplit('.', 1)[-1] for d in decorators]
    kind = 'METHOD'
    if 'property' in short:
        kind = 'PROPERTY_GETTER'
    elif short and short[-1] in ('setter', 'deleter'):
        kind = 'PROPERTY_' + short[-1].upper()
    binding = ('STATIC' if 'staticmethod' in short else
               'CLASS' if 'classmethod' in short else 'INSTANCE')
    annotation = _annotation(source, node.returns, tensor_names)
    args = ast.unparse(node.args)
    signature = ('async ' if isinstance(node, ast.AsyncFunctionDef) else '')
    signature += 'def ' + node.name + '(' + args + ')'
    if node.returns is not None:
        signature += ' -> ' + ast.unparse(node.returns)
    return dict(id=source.identity(occurrence), owner=owner, name=node.name,
                source=source.index, occurrence=occurrence, span=source.span(node),
                kind=kind, binding=binding, overload='overload' in short,
                declaration_ordinal=ordinal, decorators=decorators, signature=signature,
                signature_ast=dict(kind=type(node).__name__,
                    arguments=ast.dump(node.args, include_attributes=False),
                    returns=annotation['ast'],
                    type_params=[ast.dump(p, include_attributes=False)
                                 for p in getattr(node, 'type_params', ())]),
                return_annotation=annotation['annotation'], returns=annotation,
                return_span=None if node.returns is None else source.span(node.returns),
                conditions=(*_CONDITIONS, 'DECLARED_SIGNATURE_ACCEPTS_ACTUAL_ARGUMENTS',
                            'NORMAL_RETURN_CONFORMS_TO_DECLARATION'),
                native_selector=None, runtime_binding_verified=False)


def collect_tensor_contracts(site: Path) -> dict:
    """Collect receipt-bound Tensor classes, overloads and typed attributes.

    ``methods`` and ``attributes`` are flat rows; classes reference their IDs.
    ``returns`` is a recursive annotation tree. SELF is a declared result type,
    never a same-reference edge. Registration evidence is optional source text,
    never a mapping from a method name to an ATen selector or runtime table.
    """
    site = Path(site).resolve()
    sources = [_Source(site / 'torch/_C/__init__.pyi', 'torch._C', 'tensor_stub', 0)]
    python_source = site / 'torch/_tensor.py'
    if python_source.is_file():
        sources.append(_Source(python_source, 'torch._tensor', 'tensor_python_source', len(sources)))
    tensor_names = set(_TENSORS)
    selected = []
    candidates = [(s, i, n) for s in sources for i, n in enumerate(s.tree.body)
                  if isinstance(n, ast.ClassDef)]
    while True:
        added = []
        for source, index, node in candidates:
            qualified = source.module + '.' + node.name
            if qualified in tensor_names or any(source.resolve(base) in tensor_names for base in node.bases):
                added.append((source, index, node))
                tensor_names.add(qualified)
                # Unqualified references to classes declared in the same file.
                source.aliases[node.name] = qualified
        if not added:
            break
        selected.extend(added)
        identities = {(s.index, i) for s, i, _ in added}
        candidates = [(s, i, n) for s, i, n in candidates if (s.index, i) not in identities]
    if not selected:
        raise ValueError('installed stub has no Tensor class declaration')
    classes, methods, attributes = [], [], []
    for source, index, node in selected:
        owner = source.module + '.' + node.name
        occurrence = '/body/' + str(index)
        row = dict(id=source.identity(occurrence), name=node.name, qualified_name=owner,
                   source=source.index, occurrence=occurrence, span=source.span(node),
                   bases=[source.syntax(base) for base in node.bases], methods=[], attributes=[])
        ordinals = Counter()
        for member_index, member in enumerate(node.body):
            pointer = occurrence + '/body/' + str(member_index)
            if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                item = _member(source, owner, member, pointer, tensor_names, ordinals[member.name])
                ordinals[member.name] += 1
                if item['kind'] == 'PROPERTY_GETTER':
                    attributes.append(item)
                    row['attributes'].append(item['id'])
                else:
                    methods.append(item)
                    row['methods'].append(item['id'])
            elif isinstance(member, ast.AnnAssign) and isinstance(member.target, ast.Name):
                annotation = _annotation(source, member.annotation, tensor_names)
                item = dict(id=source.identity(pointer), owner=owner, name=member.target.id,
                    source=source.index, occurrence=pointer, span=source.span(member),
                    kind='ATTRIBUTE', annotation=annotation['annotation'], returns=annotation,
                    annotation_span=source.span(member.annotation), conditions=_CONDITIONS,
                    runtime_binding_verified=False)
                attributes.append(item)
                row['attributes'].append(item['id'])
        classes.append(row)
    receipts = [source.receipt for source in sources]
    registrations = []
    template = site / 'torchgen/packaged/autograd/templates/python_variable_methods.cpp'
    if template.is_file():
        raw = template.read_bytes()
        receipts.append(dict(path=str(template), sha256=sha256(raw).hexdigest(),
                             size_bytes=len(raw), role='method_registration_template'))
        active = False
        for line_number, line in enumerate(raw.decode('utf-8').splitlines(), 1):
            if re.search(r'PyMethodDef\s+variable_methods\s*\[\s*\]\s*=\s*\{', line):
                active = True
            elif active and re.match(r'\s*};', line):
                break
            elif active:
                match = re.match(r'\s*\{\s*"([A-Za-z_][A-Za-z_0-9]*)"', line)
                if match:
                    registrations.append(dict(name=match.group(1), source=len(receipts) - 1,
                        lineno=line_number, text=line, status='REGISTRATION_SOURCE_DECLARATION'))
    counts = Counter(item['returns']['kind'] for item in methods)
    return dict(schema='scar.tensor-stub-contracts', schema_version=1,
                status='DECLARED_INTERFACES', sources=receipts, classes=classes,
                methods=methods, attributes=attributes, registrations=registrations,
                conditions=_CONDITIONS, summary=dict(classes=len(classes), methods=len(methods),
                    method_names=len({r['name'] for r in methods}), attributes=len(attributes),
                    overloads=sum(r['overload'] for r in methods), return_kinds=dict(counts),
                    registration_names=len({r['name'] for r in registrations})),
                target_executed=False, torch_imported=False, runtime_binding_verified=False,
                native_selectors_inferred=False, same_reference_proven=False,
                storage_aliases_proven=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site-packages', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    document = collect_tensor_contracts(args.site_packages)
    args.out.mkdir(parents=True, exist_ok=False)
    (args.out / 'contracts.json').write_text(json.dumps(document, ensure_ascii=False, sort_keys=True,
                                                       separators=(',', ':')) + '\n')
    (args.out / 'result.json').write_text(json.dumps(document['summary'], indent=2) + '\n')
    print(json.dumps(document['summary'], indent=2))


if __name__ == '__main__':
    main()
