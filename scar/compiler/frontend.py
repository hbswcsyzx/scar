"""Compile-only discovery of the guarded CPU array-region profile.

This is a derived optimization view over source, not a whole-program closure
claim. Every formal parameter requires the runtime's exact 2D float64 ndarray
guard. Discovery never imports or executes the source being inspected.
"""
from __future__ import annotations

import ast
from hashlib import sha256
import math
from pathlib import Path
from types import CodeType

from scar.compiler.model import ArrayRegion, Expr, SourceRef
from scar.trace.code_snapshot import code_key


_BINARY = {ast.Add: 'add', ast.Sub: 'sub', ast.Mult: 'mul', ast.Div: 'div'}
_ARITHMETIC = frozenset((*_BINARY.values(), 'neg'))


def _span(node):
    return dict(line=getattr(node, 'lineno', 1), column=getattr(node, 'col_offset', 0),
        end_line=getattr(node, 'end_lineno', None), end_column=getattr(node, 'end_col_offset', None))


def _location(node):
    span = _span(node)
    return (type(node).__name__, span['line'], span['column'], span['end_line'], span['end_column'])


class _Rejected(ValueError):
    def __init__(self, code, detail, node):
        self.code, self.detail, self.node = code, detail, node
        super().__init__(detail)


def _reject(code, detail, node):
    raise _Rejected(code, detail, node)


def _code_objects(module):
    """Index unmodified compile-only constants, including nested functions."""
    result, pending = {}, [module]
    while pending:
        code = pending.pop()
        result.setdefault((code.co_name, code.co_firstlineno), []).append(code)
        pending.extend(value for value in code.co_consts if type(value) is CodeType)
    return result


def _functions(tree):
    """Visit every lexical function, including functions in unsupported bodies."""
    result = []

    def visit(node, prefix=''):
        child_prefix = prefix
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            qualname = prefix + node.name
            result.append((node, qualname))
            child_prefix = qualname + '.<locals>.'
        elif isinstance(node, ast.ClassDef):
            child_prefix = prefix + node.name + '.'
        for child in ast.iter_child_nodes(node):
            visit(child, child_prefix)

    visit(tree)
    return sorted(result, key=lambda pair: (pair[0].lineno, pair[0].col_offset))


def _catalog_references(catalog, path, digest):
    """Read only matching units' retained F2; keep their original ordinals."""
    from scar.analysis.source_declared_catalog import read_source_catalog
    from scar.analysis.source_store import read_source_prerequisites
    from scar.analysis.source_syntax import read_source_syntax_material
    from scar.analysis.static_query import _Fragments

    selected = read_source_catalog(catalog)
    facts = selected.fact_store
    units = selected.units_for_source(str(path))
    if not units:
        raise ValueError('source path has no original units in the supplied catalog')
    references = {}
    for identity in sorted(units):
        unit = facts.model_units[identity]
        reader = _Fragments(Path(facts.model_for(identity)))
        # These are the original admitted limits, not a request to rebuild any
        # source templates, fact tables or compiled contexts.
        f1 = reader.read(unit['artifacts']['source_tokens'])
        f2 = reader.read(unit['artifacts']['source_syntax'])
        f0, f1, f2 = read_source_prerequisites(reader, unit, f2['max_nodes'], f1['max_tokens'])
        syntax = read_source_syntax_material(f2, f0, f1)
        if (syntax.status != 'PARSED' or syntax.mode != 'exec'
                or syntax.input.path != str(path) or syntax.input.raw_sha256 != digest):
            raise ValueError('catalog F2 source path, version or parser status differs')
        schemas = {row.name: row for row in syntax.profile.ast_schema}
        for occurrence, row in enumerate(syntax.nodes):
            attributes = dict(zip(schemas[row.constructor].attributes, row.attributes))
            names = ('lineno', 'col_offset', 'end_lineno', 'end_col_offset')
            if any(name not in attributes or attributes[name].kind != 'SCALAR' for name in names):
                continue
            values = tuple(attributes[name].scalar.to_python() for name in names)
            if any(type(value) is not int for value in values):
                continue
            key = (row.constructor, *values)
            references.setdefault(key, []).append(dict(kind='original_f2_occurrence', unit=identity,
                occurrence=occurrence, f2_sha256=unit['artifacts']['source_syntax']['decoded_sha256'],
                constructor=row.constructor,
                span=dict(zip(('line', 'column', 'end_line', 'end_column'), values))))
    return references


class _Lowerer:
    def __init__(self, function):
        self.function = function
        self.nodes = []
        self.environment = {}
        self.arrays = {}
        self.fresh = {}
        self.locations = []
        self.node_locations = {}

    def remember(self, node):
        self.locations.append(node)

    def emit(self, op, node, inputs=(), attrs=None, *, array=False, fresh=False):
        identity = 'n' + str(len(self.nodes))
        self.nodes.append(Expr(identity, op, tuple(inputs), {} if attrs is None else attrs))
        self.arrays[identity], self.fresh[identity] = array, fresh
        self.node_locations[identity] = node
        self.remember(node)
        return identity

    def numeric(self, node):
        """Signed literal scalars retain Python's sign and exact numeric type."""
        sign, value_node = 1, node
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            sign = -1 if isinstance(node.op, ast.USub) else 1
            value_node = node.operand
        if not isinstance(value_node, ast.Constant) or type(value_node.value) not in (int, float):
            return None
        value = -value_node.value if sign == -1 else value_node.value
        if ((type(value) is int and abs(value) > 2**53)
                or (type(value) is float and not math.isfinite(value))):
            _reject('UNSUPPORTED_CONSTANT', 'numeric literals must be finite; integers must fit exactly in float64', node)
        return value

    def expression(self, node):
        self.remember(node)
        if isinstance(node, ast.Name):
            if not isinstance(node.ctx, ast.Load) or node.id not in self.environment:
                _reject('UNBOUND_NAME', 'expression name is not a parameter or preceding local alias', node)
            return self.environment[node.id]
        number = self.numeric(node)
        if number is not None:
            return self.emit('const', node, attrs={'value': number})
        if isinstance(node, ast.BinOp):
            op = _BINARY.get(type(node.op))
            if op is None:
                _reject('UNSUPPORTED_OPERATOR', 'only add, subtract, multiply and divide are admitted', node)
            left, right = self.expression(node.left), self.expression(node.right)
            if not (self.arrays[left] or self.arrays[right]):
                _reject('SCALAR_ARITHMETIC', 'computed scalar arithmetic is outside this array profile', node)
            return self.emit(op, node, (left, right), array=True, fresh=True)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            value = self.expression(node.operand)
            if not self.arrays[value]:
                _reject('SCALAR_ARITHMETIC', 'computed scalar arithmetic is outside this array profile', node)
            return self.emit('neg', node, (value,), array=True, fresh=True)
        if isinstance(node, ast.Subscript):
            value = self.expression(node.value)
            if not self.arrays[value] or self.fresh[value]:
                _reject('UNSUPPORTED_SLICE_BASE', 'slicing requires an input array or an input-array slice', node)
            if not isinstance(node.slice, ast.Tuple) or len(node.slice.elts) != 2:
                _reject('UNSUPPORTED_SLICE', 'exactly two slice axes are required', node)
            bounds = []
            for axis in node.slice.elts:
                if not isinstance(axis, ast.Slice):
                    _reject('UNSUPPORTED_SLICE', 'array indexing requires two constant-bound slices', axis)
                step = self.bound(axis.step)
                if step not in (None, 1):
                    _reject('UNSUPPORTED_SLICE_STEP', 'slice step must be omitted, None or one', axis)
                bounds.append([self.bound(axis.lower), self.bound(axis.upper)])
                self.remember(axis)
            return self.emit('slice', node, (value,), {'bounds': bounds}, array=True)
        if isinstance(node, ast.Call):
            _reject('UNSUPPORTED_CALL', 'calls, including random-number generation, are outside this profile', node)
        if isinstance(node, ast.Attribute):
            _reject('UNSUPPORTED_STATE_READ', 'attribute and external state reads are outside this profile', node)
        _reject('UNSUPPORTED_EXPRESSION', type(node).__name__ + ' is outside this array profile', node)

    def bound(self, node):
        if node is None:
            return None
        self.remember(node)
        if isinstance(node, ast.Constant) and node.value is None:
            return None
        sign, literal = 1, node
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            sign = -1 if isinstance(node.op, ast.USub) else 1
            literal = node.operand
        if isinstance(literal, ast.Constant) and type(literal.value) is int:
            value = sign * literal.value
            if abs(value) > 2**63 - 1:
                _reject('UNSUPPORTED_SLICE_BOUND', 'slice bounds must fit the signed 64-bit backend ABI', node)
            return value
        _reject('NONCONSTANT_SLICE_BOUND', 'slice bounds must be integer literals or None', node)

    def lower(self):
        function = self.function
        self.remember(function)
        if isinstance(function, ast.AsyncFunctionDef):
            _reject('ASYNC_FUNCTION', 'async functions require a different execution profile', function)
        if any(not isinstance(decorator, ast.Name) or decorator.id != 'staticmethod'
                for decorator in function.decorator_list):
            _reject('UNSUPPORTED_DECORATOR', 'only bare staticmethod is admitted', function)
        args = function.args
        if args.vararg is not None or args.kwarg is not None:
            _reject('VARIADIC_SIGNATURE', 'variadic arguments are outside this fixed-array profile', function)
        parameters = (*args.posonlyargs, *args.args, *args.kwonlyargs)
        for index, parameter in enumerate(parameters):
            self.environment[parameter.arg] = self.emit('input', parameter,
                attrs={'name': parameter.arg, 'index': index}, array=True)
        output = None
        for index, statement in enumerate(function.body):
            self.remember(statement)
            if (index == 0 and isinstance(statement, ast.Expr)
                    and isinstance(statement.value, ast.Constant) and type(statement.value.value) is str):
                continue
            if isinstance(statement, ast.Assign):
                if any(not isinstance(target, ast.Name) for target in statement.targets):
                    _reject('UNSUPPORTED_WRITE', 'only local name assignments are admitted; array/state writes are excluded', statement)
                value = self.expression(statement.value)
                for target in statement.targets:
                    self.remember(target)
                    self.environment[target.id] = value
            elif isinstance(statement, ast.Return):
                if index != len(function.body) - 1:
                    _reject('NONFINAL_RETURN', 'the sole return must be the final statement', statement)
                if statement.value is None:
                    _reject('SCALAR_OUTPUT', 'an array-valued expression is required', statement)
                output = self.expression(statement.value)
            elif isinstance(statement, ast.AugAssign):
                _reject('UNSUPPORTED_WRITE', 'augmented assignment may mutate an input', statement)
            else:
                _reject('UNSUPPORTED_STATEMENT', type(statement).__name__ + ' is outside the pure straight-line profile', statement)
        if output is None:
            _reject('MISSING_RETURN', 'a final array-valued return is required', function)
        if not self.arrays[output]:
            _reject('SCALAR_OUTPUT', 'return expression must depend on an input array', function)
        if not self.fresh[output]:
            _reject('ALIASED_OUTPUT', 'returning an input or its slice would violate fresh-output semantics', function)
        needed, pending = set(), [output]
        by_id = {node.id: node for node in self.nodes}
        while pending:
            identity = pending.pop()
            if identity not in needed:
                needed.add(identity)
                pending.extend(by_id[identity].inputs)
        for node in self.nodes:
            if node.op in _ARITHMETIC and node.id not in needed:
                _reject('UNUSED_ARITHMETIC', 'discarded array arithmetic may still raise NumPy exceptions', self.node_locations[node.id])
            if node.op == 'slice' and node.id not in needed:
                _reject('UNUSED_SLICE', 'discarded input slices are outside this output region', self.node_locations[node.id])
        return tuple(parameter.arg for parameter in parameters), tuple(self.nodes), output


def discover_regions(path, *, catalog=None) -> tuple[list[ArrayRegion], list[dict]]:
    """Discover source-grounded regions and explicit rejection records.

    Compilation uses unmodified file bytes, its canonical filename, no inherited
    future flags and optimization level zero. Runtime installation must verify
    the resulting code key and source digest, then enforce the ndarray guards.
    If supplied, a catalog must contain matching retained F2 source material;
    its original unit identities and occurrence ordinals survive in origins.
    """
    path = Path(path).resolve()
    raw = path.read_bytes()
    digest = sha256(raw).hexdigest()
    regions, rejections = [], []

    def rejected(code, detail, node=None, qualname='<module>'):
        rejections.append(dict(path=str(path), sha256=digest, qualname=qualname,
            **_span(node), code=code, reason=code, detail=detail))

    try:
        tree = compile(raw, str(path), 'exec', flags=ast.PyCF_ONLY_AST | ast.PyCF_TYPE_COMMENTS,
            dont_inherit=True, optimize=0)
        compiled = compile(raw, str(path), 'exec', dont_inherit=True, optimize=0)
    except (SyntaxError, ValueError, OverflowError, RecursionError) as error:
        rejected('SOURCE_COMPILATION_FAILED', type(error).__name__ + ': ' + str(error))
        return regions, rejections
    try:
        references = {} if catalog is None else _catalog_references(catalog, path, digest)
    except (ValueError, KeyError, OSError, TypeError) as error:
        rejected('CATALOG_SOURCE_MISMATCH', str(error))
        return regions, rejections
    codes = _code_objects(compiled)
    for function, lexical_qualname in _functions(tree):
        first_line = min([function.lineno, *(node.lineno for node in function.decorator_list)])
        candidates = codes.get((function.name, first_line), ())
        if len(candidates) != 1:
            rejected('CODE_IDENTITY_UNAVAILABLE', 'source definition has no unique original code constant', function, lexical_qualname)
            continue
        code = candidates[0]
        lowerer = _Lowerer(function)
        try:
            parameters, nodes, output = lowerer.lower()
            key = code_key(code)
        except _Rejected as error:
            rejected(error.code, error.detail, error.node, code.co_qualname)
            continue
        except (ValueError, RecursionError) as error:
            rejected('CODE_IDENTITY_UNAVAILABLE', str(error), function, code.co_qualname)
            continue
        origins = [dict(kind='source_span', constructor=type(function).__name__, span=_span(function))]
        seen = set()
        if catalog is not None:
            for node in lowerer.locations:
                location = _location(node)
                if location not in seen:
                    seen.add(location)
                    origins.extend(references.get(location, ()))
            if not references.get(_location(function)):
                rejected('CATALOG_OCCURRENCE_MISSING', 'source function has no retained original F2 occurrence', function, code.co_qualname)
                continue
        source = SourceRef(str(path), digest, code.co_qualname, function.lineno,
            function.col_offset, key, tuple(origins))
        identity = 'array-region:' + sha256((str(path) + '\0' + digest + '\0' + key).encode()).hexdigest()[:24]
        regions.append(ArrayRegion(identity, source, parameters, nodes, output))
    return regions, rejections


__all__ = ['discover_regions']
