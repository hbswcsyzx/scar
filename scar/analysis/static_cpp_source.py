"""Receipt-bound C++ source occurrences, not canonical execution values.

The input layer retains syntax and source-reference candidates. It neither
resolves C++ types/overloads nor claims that templates describe a live binary.
"""
from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import asdict, dataclass, fields, is_dataclass
from enum import Enum
import hashlib
import json
from pathlib import Path
import re
import subprocess
from types import UnionType
from typing import Union, get_args, get_origin, get_type_hints

from scar.analysis.static_native_materials import MaterialSpan
from scar.ir.record_codec import decode, encode
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import SourceAtomID


class CppSourceError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CppSourceBudget:
    max_source_bytes: int = 1_000_000
    max_nodes: int = 200_000
    max_occurrences: int = 30_000
    max_relations: int = 100_000
    max_output_bytes: int = 16_000_000
    max_tool_bytes: int = 64_000_000
    max_seconds: int = 30

    def __post_init__(self):
        if any(type(n) is not int or n < 1 for n in asdict(self).values()):
            raise ValueError('C++ source budgets must be positive integers')


class CppRelationKind(str, Enum):
    SOURCE = 'SOURCE'
    STRUCTURE = 'STRUCTURE'


@dataclass(frozen=True, slots=True)
class CppSourceOccurrence:
    id: SourceAtomID
    source: SourceReference
    kind: str
    byte_start: int
    byte_end: int
    roles: tuple[str, ...]
    has_parse_error: bool
    missing: bool


@dataclass(frozen=True, slots=True)
class CppSourceRelation:
    source: SourceAtomID
    target: SourceAtomID
    kind: CppRelationKind
    role: str
    position: int | None = None


@dataclass(frozen=True, slots=True)
class CppFunctionSource:
    occurrence: SourceAtomID
    declarator: SourceAtomID
    body: SourceAtomID
    name: SourceAtomID | None
    symbol: str | None
    namespaces: tuple[str, ...]
    preprocessor: tuple[SourceAtomID, ...]
    open_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CppSymbolReference:
    occurrence: SourceAtomID
    spelling: str
    candidates: tuple[SourceAtomID, ...]
    lookup_status: str


@dataclass(frozen=True, slots=True)
class CppMethodEntry:
    occurrence: SourceAtomID
    name: SourceAtomID | None
    python_name: str | None
    callback: SourceAtomID | None
    flags: SourceAtomID | None
    documentation: SourceAtomID | None
    references: tuple[CppSymbolReference, ...]
    open_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CppMethodTable:
    occurrence: SourceAtomID
    name: SourceAtomID | None
    entries: tuple[SourceAtomID, ...]
    terminators: tuple[SourceAtomID, ...]
    holes: tuple[SourceAtomID, ...]
    unclassified: tuple[SourceAtomID, ...]
    explicit_entries_enumerated: bool
    generated_complete: bool


@dataclass(frozen=True, slots=True)
class CppCallSource:
    occurrence: SourceAtomID
    callee: SourceAtomID | None
    arguments: tuple[SourceAtomID, ...]
    owner_function: SourceAtomID | None
    preprocessor: tuple[SourceAtomID, ...]
    open_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CppSourceToolReceipt:
    executable: str
    python_version: str
    worker: MaterialSpan
    versions: tuple[tuple[str, str], ...]
    files: tuple[MaterialSpan, ...]
    isolated: bool
    no_site: bool
    torch_imported: bool
    core_limit: tuple[int, int]


@dataclass(frozen=True, slots=True)
class CppSourceModel:
    source: MaterialSpan
    template_grammar: MaterialSpan | None
    tools: CppSourceToolReceipt
    occurrences: tuple[CppSourceOccurrence, ...]
    relations: tuple[CppSourceRelation, ...]
    functions: tuple[CppFunctionSource, ...]
    tables: tuple[CppMethodTable, ...]
    entries: tuple[CppMethodEntry, ...]
    calls: tuple[CppCallSource, ...]
    holes: tuple[SourceAtomID, ...]
    errors: tuple[SourceAtomID, ...]
    named_nodes_visited: int
    open_fields: tuple[str, ...]

    def index(self):
        return CppSourceIndex(self)


class CppSourceIndex:
    """A derived adjacency index; the source records remain the authority."""
    def __init__(self, model):
        self.model = model
        self.occurrences = {row.id: row for row in model.occurrences}
        self.functions = {row.occurrence: row for row in model.functions}
        self.entries = {row.occurrence: row for row in model.entries}
        self._before, self._after = defaultdict(list), defaultdict(list)
        for edge in model.relations:
            if edge.source not in self.occurrences or edge.target not in self.occurrences:
                raise CppSourceError('source relation endpoint is absent')
            self._before[edge.target].append(edge); self._after[edge.source].append(edge)

    def incoming(self, occurrence):
        return tuple(self._before.get(occurrence, ()))

    def outgoing(self, occurrence):
        return tuple(self._after.get(occurrence, ()))


_DOCUMENT_SCHEMA = 'scar.cpp-source'
_DOCUMENT_VERSION = 1
_REFERENCE_RECORDS = {'relations': CppSourceRelation, 'functions': CppFunctionSource,
    'tables': CppMethodTable, 'entries': CppMethodEntry, 'calls': CppCallSource}


def _validate_cpp_source_model(model):
    """Check unit/occurrence identity and reference integrity, without I/O.

    Original source/parser receipt verification belongs to the reader. A saved
    document does not silently re-open or reparse that external source.
    """
    if type(model) is not CppSourceModel:
        raise CppSourceError('expected CppSourceModel')
    source = model.source
    if (not Path(source.path).is_absolute() or re.fullmatch(r'[a-f0-9]{64}', source.sha256) is None
            or type(source.size_bytes) is not int or source.size_bytes < 0
            or source.byte_start != 0 or source.byte_end != source.size_bytes
            or source.selection_sha256 != source.sha256):
        raise CppSourceError('invalid original C++ source unit receipt')
    ids, coordinates = set(), set()
    for row in model.occurrences:
        reference = row.source
        coordinate = row.kind, row.byte_start, row.byte_end
        identity = 'cpp:' + hashlib.sha256(json.dumps((source.sha256, *coordinate), separators=(',', ':')).encode()).hexdigest()
        if row.id in ids or coordinate in coordinates:
            raise CppSourceError('duplicate C++ source occurrence ID/span')
        if (type(row.id) is not SourceAtomID or row.id.value != identity
                or reference.atom_id != row.id or reference.path != source.path
                or reference.fingerprint != 'sha256:' + source.sha256):
            raise CppSourceError('C++ occurrence differs from its original source unit identity')
        if (not row.kind or any(type(n) is not int for n in (row.byte_start, row.byte_end,
                    reference.start_line, reference.end_line, reference.start_column, reference.end_column))
                or not 0 <= row.byte_start <= row.byte_end <= source.size_bytes
                or not 1 <= reference.start_line <= reference.end_line <= source.end_line + 1
                or not 0 <= reference.start_column <= row.byte_start
                or not 0 <= reference.end_column <= row.byte_end
                or reference.start_line == reference.end_line
                    and reference.end_column - reference.start_column != row.byte_end - row.byte_start
                or len(set(row.roles)) != len(row.roles)):
            raise CppSourceError('invalid C++ occurrence byte/line/role fields')
        ids.add(row.id); coordinates.add(coordinate)
    index = model.index()
    def references(value):
        if type(value) is SourceAtomID:
            if value not in ids:raise CppSourceError('C++ reference is outside its occurrence table')
        elif is_dataclass(value):
            for field in fields(value):references(getattr(value, field.name))
        elif type(value) in (tuple, list):
            for item in value:references(item)
    for name in (*_REFERENCE_RECORDS, 'holes', 'errors'):
        references(getattr(model, name))
    if any(key not in index.entries for row in model.tables for key in row.entries):
        raise CppSourceError('method table references an absent entry record')
    if any(key not in index.functions for row in model.entries for ref in row.references for key in ref.candidates):
        raise CppSourceError('callback reference has no corresponding function definition')
    if any(row.owner_function is not None and row.owner_function not in index.functions for row in model.calls):
        raise CppSourceError('call references an absent function definition')
    if (any(index.occurrences[key].kind != 'template_hole' for key in model.holes)
            or any(index.occurrences[key].kind != 'ERROR' and not index.occurrences[key].missing for key in model.errors)):
        raise CppSourceError('hole/error inventory changed original occurrence roles')


def cpp_source_to_document(model):
    """Normalize this unit's original IDs to local integer references.

    IDs occur once, in the occurrence table. SourceReference atom/path/hash
    are reconstructible from that row and the unit's original source receipt.
    Integer references are storage coordinates, never new program identities.
    """
    _validate_cpp_source_model(model)
    positions = {row.id: index for index, row in enumerate(model.occurrences)}
    def project(value):
        if type(value) is SourceAtomID:return positions[value]
        if isinstance(value, Enum):return value.value
        if is_dataclass(value):return {field.name: project(getattr(value, field.name)) for field in fields(value)}
        if type(value) in (tuple, list):return [project(item) for item in value]
        return value
    result = {'schema': _DOCUMENT_SCHEMA, 'schema_version': _DOCUMENT_VERSION,
        'source': encode(model.source), 'template_grammar': encode(model.template_grammar),
        'tools': encode(model.tools), 'occurrences': [],
        'named_nodes_visited': model.named_nodes_visited, 'open_fields': list(model.open_fields)}
    for row in model.occurrences:
        result['occurrences'].append({'id': row.id.value, 'kind': row.kind,
            'byte_start': row.byte_start, 'byte_end': row.byte_end, 'roles': list(row.roles),
            'has_parse_error': row.has_parse_error, 'missing': row.missing,
            'start_line': row.source.start_line, 'end_line': row.source.end_line,
            'start_column': row.source.start_column, 'end_column': row.source.end_column})
    for name in (*_REFERENCE_RECORDS, 'holes', 'errors'):
        result[name] = project(getattr(model, name))
    return result


def cpp_source_from_document(document):
    """Strictly reconstruct the same typed model from one normalized unit."""
    expected_fields = {'schema', 'schema_version', *(field.name for field in fields(CppSourceModel))}
    try:
        if (type(document) is not dict or set(document) != expected_fields
                or document['schema'] != _DOCUMENT_SCHEMA or type(document['schema_version']) is not int
                or document['schema_version'] != _DOCUMENT_VERSION):
            raise CppSourceError('unsupported normalized C++ source schema/fields')
        source = decode(MaterialSpan, document['source'])
        rows = document['occurrences']
        if type(rows) is not list:
            raise CppSourceError('C++ occurrences must be a document array')
        occurrence_fields = {'id', 'kind', 'byte_start', 'byte_end', 'roles', 'has_parse_error', 'missing',
            'start_line', 'end_line', 'start_column', 'end_column'}
        occurrences, ids, seen = [], [], set()
        for row in rows:
            if type(row) is not dict or set(row) != occurrence_fields or type(row['id']) is not str:
                raise CppSourceError('invalid normalized C++ occurrence fields')
            identity = SourceAtomID(row['id'])
            if identity in seen:raise CppSourceError('duplicate C++ source occurrence ID')
            seen.add(identity); ids.append(identity)
            value = {name: row[name] for name in ('kind', 'byte_start', 'byte_end', 'roles', 'has_parse_error', 'missing')}
            value['id'] = encode(identity)
            value['source'] = {'atom_id': encode(identity), 'path': source.path,
                'fingerprint': 'sha256:' + source.sha256,
                **{name: row[name] for name in ('start_line', 'end_line', 'start_column', 'end_column')}}
            occurrences.append(decode(CppSourceOccurrence, value))
        def inflate(expected, value):
            if expected is SourceAtomID:
                if type(value) is not int or not 0 <= value < len(ids):
                    raise CppSourceError('C++ occurrence index is outside this unit')
                return encode(ids[value])
            origin, arguments = get_origin(expected), get_args(expected)
            if origin in (Union, UnionType):
                if value is None and type(None) in arguments:return None
                if SourceAtomID in arguments:return inflate(SourceAtomID, value)
                return value
            if origin in (tuple, list):
                if type(value) is not list:raise CppSourceError('C++ reference sequence must be an array')
                if origin is tuple and not (len(arguments) == 2 and arguments[1] is Ellipsis):
                    if len(arguments) != len(value):raise CppSourceError('incorrect C++ fixed tuple length')
                    return [inflate(kind, item) for kind, item in zip(arguments, value)]
                return [inflate(arguments[0], item) for item in value]
            if is_dataclass(expected):
                members = fields(expected); hints = get_type_hints(expected)
                if type(value) is not dict or set(value) != {field.name for field in members}:
                    raise CppSourceError('C++ reference record fields differ')
                return {field.name: inflate(hints[field.name], value[field.name]) for field in members}
            return value
        typed = {name: document[name] for name in ('source', 'template_grammar', 'tools', 'named_nodes_visited', 'open_fields')}
        typed['occurrences'] = [encode(row) for row in occurrences]
        for name, record_type in _REFERENCE_RECORDS.items():
            typed[name] = inflate(tuple[record_type, ...], document[name])
        for name in ('holes', 'errors'):
            typed[name] = inflate(tuple[SourceAtomID, ...], document[name])
        model = decode(CppSourceModel, typed)
        _validate_cpp_source_model(model)
        return model
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, CppSourceError):raise
        raise CppSourceError('invalid normalized C++ source document: ' + str(error)) from error


def _receipt(path, raw):
    digest = hashlib.sha256(raw).hexdigest()
    return MaterialSpan(str(path), digest, len(raw), 0, len(raw), 1,
        max(1, len(raw.splitlines())), digest)


def _template_pattern(path, budget):
    if path is None:
        return None, None
    path = Path(path).absolute()
    if not path.is_file() or path.stat().st_size > budget.max_source_bytes:
        raise CppSourceError('MISSING_TEMPLATE_GRAMMAR: original CodeTemplate source is unavailable')
    raw = path.read_bytes(); tree = ast.parse(raw, filename=str(path))
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'CodeTemplate']
    if len(classes) != 1:
        raise CppSourceError('UNSUPPORTED_TEMPLATE_GRAMMAR: expected original CodeTemplate declaration')
    pattern = []
    compiled = []
    for node in classes[0].body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        if node.targets[0].id == 'substitution_str' and isinstance(node.value, ast.Constant) and type(node.value.value) is str:
            pattern.append(node.value.value)
        if node.targets[0].id == 'substitution':
            call = node.value
            if (isinstance(call, ast.Call) and ast.unparse(call.func) == 're.compile'
                    and [ast.unparse(a) for a in call.args] == ['substitution_str', 're.MULTILINE'] and not call.keywords):
                compiled.append(True)
    if len(pattern) != 1 or len(compiled) != 1:
        raise CppSourceError('UNSUPPORTED_TEMPLATE_GRAMMAR: original public pattern/flags differ')
    return pattern[0], _receipt(path, raw)


def read_static_cpp_source(source, *, tool_python=None, template_grammar=None, budget=None):
    """Parse source in SCAR's private analyzer process; never execute C++.

    Pass the receipt-bound ``torchgen/code_template.py`` as template_grammar
    for torchgen template inputs. Its literal public regex is read, not run.
    No Point named-field access is used by the parser worker.
    """
    budget = budget or CppSourceBudget()
    if type(budget) is not CppSourceBudget:
        raise TypeError('expected CppSourceBudget')
    source = Path(source).absolute()
    if not source.is_file() or source.stat().st_size > budget.max_source_bytes:
        raise CppSourceError('MISSING_SOURCE_MATERIAL: source is missing or exceeds its byte budget')
    raw = source.read_bytes()
    if len(raw) > budget.max_source_bytes:
        raise CppSourceError('SOURCE_BYTE_BUDGET')
    source_receipt = _receipt(source, raw)
    pattern, grammar_receipt = _template_pattern(template_grammar, budget)
    project = Path(__file__).resolve().parents[2]
    # Keep the venv executable's path: resolving its symlink loses venv identity.
    executable = Path(tool_python).absolute() if tool_python is not None else project / '.venv/native-source/bin/python'
    cfg = executable.parent.parent / 'pyvenv.cfg'
    if not executable.is_file() or not cfg.is_file() or 'include-system-site-packages = false' not in cfg.read_text().lower():
        raise CppSourceError('MISSING_ANALYZER_TOOL: use the isolated SCAR native-source venv')
    worker_path = Path(__file__).with_name('_static_cpp_source_worker.py').resolve()
    worker_raw = worker_path.read_bytes()
    request = {'source': asdict(source_receipt), 'pattern': pattern, 'budget': asdict(budget)}
    try:
        run = subprocess.run([str(executable), '-I', '-S', '-B', str(worker_path)], input=json.dumps(request).encode(),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=budget.max_seconds, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise CppSourceError('ANALYZER_PROCESS_FAILED: ' + type(error).__name__) from error
    if run.returncode or len(run.stdout) > budget.max_output_bytes:
        raise CppSourceError('ANALYZER_PROCESS_FAILED: exit=' + str(run.returncode) + ' ' + run.stderr[:1000].decode(errors='replace'))
    try:
        result = json.loads(run.stdout)
        tool = result['tools']
        if not (tool['isolated'] and tool['no_site'] and not tool['torch_imported'] and tool['core_limit'] == [0, 0]):
            raise CppSourceError('ANALYZER_ISOLATION_DIFFERS')
        ids = {}
        occurrences = []
        for row in result['occurrences']:
            identity = SourceAtomID(row['id']); ids[row['id']] = identity
            ref = SourceReference(identity, str(source), 'sha256:' + source_receipt.sha256,
                row['start_line'], row['end_line'], row['start_column'], row['end_column'])
            occurrences.append(CppSourceOccurrence(identity, ref, row['kind'], row['start'], row['end'],
                tuple(row['roles']), row['has_error'], row['missing']))
        key = lambda value: ids[value] if value is not None else None
        keys = lambda values: tuple(key(v) for v in values)
        relations = tuple(CppSourceRelation(key(r['source']), key(r['target']), CppRelationKind(r['kind']),
            r['role'], r['position']) for r in result['relations'])
        functions = tuple(CppFunctionSource(key(r['id']), key(r['declarator']), key(r['body']), key(r['name']),
            r['symbol'], tuple(r['namespaces']), keys(r['preprocessor']), tuple(r['open_fields'])) for r in result['functions'])
        entries = tuple(CppMethodEntry(key(r['id']), key(r['name']), r['python_name'], key(r['callback']), key(r['flags']),
            key(r['documentation']), tuple(CppSymbolReference(key(s['id']), s['spelling'], keys(s['candidates']), s['status'])
                for s in r['references']), tuple(r['open_fields'])) for r in result['entries'])
        tables = tuple(CppMethodTable(key(r['id']), key(r['name']), keys(r['entries']), keys(r['terminators']),
            keys(r['holes']), keys(r['unclassified']), r['explicit_entries_enumerated'], r['generated_complete']) for r in result['tables'])
        calls = tuple(CppCallSource(key(r['id']), key(r['callee']), keys(r['arguments']), key(r['owner_function']),
            keys(r['preprocessor']), tuple(r['open_fields'])) for r in result['calls'])
        model = CppSourceModel(source_receipt, grammar_receipt,
            CppSourceToolReceipt(str(executable), tool['python_version'], _receipt(worker_path, worker_raw),
                tuple(tuple(r) for r in tool['versions']), tuple(MaterialSpan(**r) for r in tool['files']),
                True, True, False, (0, 0)), tuple(occurrences), relations, functions, tables, entries, calls,
            keys(result['holes']), keys(result['errors']), result['named_nodes'], tuple(result['open_fields']))
        model.index()  # Enforce all SOURCE/STRUCTURE endpoints over original occurrences.
        if hashlib.sha256(source.read_bytes()).hexdigest() != source_receipt.sha256:
            raise CppSourceError('source changed during analysis')
        return model
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, CppSourceError):
            raise
        raise CppSourceError('INVALID_ANALYZER_RESULT: ' + str(error)) from error


__all__ = ['CppSourceError', 'CppSourceBudget', 'CppRelationKind', 'CppSourceOccurrence',
    'CppSourceRelation', 'CppFunctionSource', 'CppSymbolReference', 'CppMethodEntry',
    'CppMethodTable', 'CppCallSource', 'CppSourceToolReceipt', 'CppSourceModel',
    'CppSourceIndex', 'read_static_cpp_source', 'cpp_source_to_document', 'cpp_source_from_document']
