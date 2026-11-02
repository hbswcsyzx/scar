"""Receipt-bound ATen declarations, without importing the analyzed program.

These records are provider materials, not another program graph. Schema alias
sets are scoped may-alias declarations; dispatch entries are build declarations,
not observations of a selected kernel, copy, allocation or physical resource.
"""
from __future__ import annotations

import ast
import base64
import csv
from dataclasses import asdict, dataclass
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys


class NativeMaterialError(ValueError):
    """Required original material or the supported parser contract is absent."""


@dataclass(frozen=True, slots=True)
class NativeMaterialBudget:
    max_file_bytes: int = 4_000_000
    max_total_bytes: int = 16_000_000
    max_selectors: int = 32
    max_schema_bytes: int = 32_000
    max_yaml_nodes: int = 200_000
    max_output_bytes: int = 2_000_000
    max_seconds: int = 30

    def __post_init__(self):
        if any(type(value) is not int or value < 1 for value in asdict(self).values()):
            raise ValueError('native material budgets must be positive integers')


@dataclass(frozen=True, slots=True)
class MaterialSpan:
    path: str
    sha256: str
    size_bytes: int
    byte_start: int
    byte_end: int
    start_line: int
    end_line: int
    selection_sha256: str


@dataclass(frozen=True, slots=True)
class NativeType:
    text: str
    kind: str
    name: str | None = None
    element: NativeType | None = None
    size: int | None = None


@dataclass(frozen=True, slots=True)
class NativeAliasDeclaration:
    before: tuple[str, ...]
    may_write: bool
    after: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NativeSchemaPort:
    position: int
    name: str | None
    kind: str
    type: NativeType
    default: str | None
    alias: NativeAliasDeclaration | None


@dataclass(frozen=True, slots=True)
class NativeDispatchDeclaration:
    keys: tuple[str, ...]
    symbol: str
    source: MaterialSpan


@dataclass(frozen=True, slots=True)
class NativeDeclaredField:
    name: str
    value_json: str
    source: MaterialSpan


@dataclass(frozen=True, slots=True)
class StaticNativeDeclaration:
    selector: str
    namespace: str
    operator: str
    overload: str
    schema: str
    cpp_signature: str
    header_source: MaterialSpan
    yaml_source: MaterialSpan
    schema_source: MaterialSpan
    inputs: tuple[NativeSchemaPort, ...]
    outputs: tuple[NativeSchemaPort, ...]
    declared_mutable: bool
    dispatch_declared: bool
    dispatch: tuple[NativeDispatchDeclaration, ...]
    fields: tuple[NativeDeclaredField, ...]
    open_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NativeParserReceipt:
    executable: str
    python_version: str
    worker: MaterialSpan
    tools: tuple[MaterialSpan, ...]
    isolated: bool
    no_site: bool
    torch_imported: bool
    imported_tools: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StaticNativeMaterials:
    package_version: str
    cuda_build: str | None
    source_revision: str
    package_sources: tuple[MaterialSpan, ...]
    parser: NativeParserReceipt
    declarations: tuple[StaticNativeDeclaration, ...]


_SELECTOR = re.compile(r'aten::([A-Za-z_][A-Za-z_0-9]*)(?:\.([A-Za-z_][A-Za-z_0-9]*))?\Z')


def _span(path, raw):
    return MaterialSpan(str(path), hashlib.sha256(raw).hexdigest(), len(raw), 0,
        len(raw), 1, max(1, len(raw.splitlines())), hashlib.sha256(raw).hexdigest())


def _dist(site, prefix, name, read):
    matches = []
    for candidate in site.glob(prefix + '-*.dist-info'):
        metadata = read(candidate / 'METADATA').decode('utf-8')
        fields = {}
        for line in metadata.split('\n\n', 1)[0].splitlines():
            if line.startswith(('Name: ', 'Version: ')):
                key, value = line.split(': ', 1)
                if key in fields:
                    raise NativeMaterialError('duplicate distribution metadata header')
                fields[key] = value
        if fields.get('Name', '').lower().replace('-', '_') == name:
            matches.append((candidate, fields['Version']))
    if len(matches) != 1:
        raise NativeMaterialError('one installed distribution is required: ' + name)
    directory, version = matches[0]
    raw = read(directory / 'RECORD')
    records = {}
    for row in csv.reader(io.StringIO(raw.decode('utf-8'))):
        if len(row) != 3 or row[0] in records:
            raise NativeMaterialError('invalid/duplicate installed RECORD entry')
        records[row[0]] = (row[1], row[2])
    return directory, version, records


def read_static_native_materials(site_packages, selectors, *, budget=None):
    """Read exact ``aten::operator.overload`` declarations in an isolated tool.

    The caller explicitly supplies the installed tool/material directory. The
    target's import path and current directory are never added to the worker.
    Only FunctionSchema.parse is called; torchgen generators and target defaults
    are never evaluated. Unknown selectors or missing receipts are rejected.
    """
    budget = budget or NativeMaterialBudget()
    if type(budget) is not NativeMaterialBudget:
        raise TypeError('expected NativeMaterialBudget')
    site = Path(site_packages).absolute()
    if not site.is_dir() or site.resolve() != site:
        raise NativeMaterialError('tool site-packages must be an existing canonical directory')
    selectors = tuple(selectors)
    if (not selectors or len(selectors) > budget.max_selectors or len(set(selectors)) != len(selectors)
            or any(type(s) is not str or not _SELECTOR.fullmatch(s) for s in selectors)):
        raise NativeMaterialError('select distinct full aten::operator.overload names')
    payloads, total = {}, 0

    def read(path):
        nonlocal total
        path = Path(path)
        if path.resolve() != path or not path.is_file() or not path.is_relative_to(site):
            raise NativeMaterialError('required installed material is missing/noncanonical: ' + str(path))
        if path not in payloads:
            if path.stat().st_size > budget.max_file_bytes:
                raise NativeMaterialError('installed material exceeds file budget')
            raw = path.read_bytes(); total += len(raw)
            if len(raw) > budget.max_file_bytes or total > budget.max_total_bytes:
                raise NativeMaterialError('installed materials exceed byte budget')
            payloads[path] = raw
        return payloads[path]

    torch_dist, version, torch_records = _dist(site, 'torch', 'torch', read)
    yaml_dist, _, yaml_records = _dist(site, 'pyyaml', 'pyyaml', read)
    typing_dist, _, typing_records = _dist(site, 'typing_extensions', 'typing_extensions', read)

    def receipt(relative, records):
        raw = read(site / relative)
        digest = 'sha256=' + base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).decode().rstrip('=')
        if records.get(relative) != (digest, str(len(raw))):
            raise NativeMaterialError('installed RECORD receipt differs: ' + relative)
        return {'sha256': hashlib.sha256(raw).hexdigest(), 'size_bytes': len(raw)}

    tool_files = ('torchgen/__init__.py', 'torchgen/model.py', 'torchgen/utils.py', 'torchgen/code_template.py')
    tools = {name: receipt(name, torch_records) for name in tool_files}
    tools['typing_extensions.py'] = receipt('typing_extensions.py', typing_records)
    for name in yaml_records:
        if name.startswith('yaml/') and name.endswith('.py') and name != 'yaml/cyaml.py':
            tools[name] = receipt(name, yaml_records)
    if 'yaml/__init__.py' not in tools:
        raise NativeMaterialError('pure Python PyYAML tool is unavailable')
    material_names = {'torchgen/packaged/ATen/native/native_functions.yaml', 'torch/version.py'}
    material_files = {name: receipt(name, torch_records) for name in sorted(material_names)}
    record_name = str((torch_dist / 'RECORD').relative_to(site))
    record_raw = read(torch_dist / 'RECORD')
    material_files[record_name] = {'sha256': hashlib.sha256(record_raw).hexdigest(), 'size_bytes': len(record_raw)}
    constants = {}
    for node in ast.parse(read(site / 'torch/version.py'), filename=str(site / 'torch/version.py')).body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
            for target in targets:
                if isinstance(target, ast.Name) and target.id in ('__version__', 'git_version', 'cuda'):
                    if target.id in constants or not isinstance(node.value, ast.Constant):
                        raise NativeMaterialError('package version must be one literal declaration')
                    constants[target.id] = node.value.value
    if (constants.get('__version__') != version or type(constants.get('git_version')) is not str
            or re.fullmatch(r'[a-f0-9]{40}', constants['git_version']) is None
            or constants.get('cuda') is not None and type(constants.get('cuda')) is not str):
        raise NativeMaterialError('installed version/git declaration is inconsistent')
    worker_path = Path(__file__).with_name('_static_native_parser_worker.py').resolve()
    worker_raw = worker_path.read_bytes()
    request = {'site': str(site), 'selectors': selectors, 'tools': tools,
        'materials': material_files, 'torch_record': record_name, 'budget': asdict(budget)}
    try:
        completed = subprocess.run([sys.executable, '-I', '-S', '-B', str(worker_path)],
            input=json.dumps(request).encode(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=budget.max_seconds, cwd=worker_path.parent, check=False)
    except (subprocess.TimeoutExpired, OSError) as error:
        raise NativeMaterialError('isolated native parser failed: ' + type(error).__name__) from error
    if completed.returncode or len(completed.stdout) > budget.max_output_bytes:
        detail = completed.stderr[:1500].decode('utf-8', errors='replace')
        raise NativeMaterialError('isolated native parser rejected material: ' + detail)
    try:
        report = json.loads(completed.stdout)
        worker = report['worker']
        if (worker['isolated'] is not True or worker['no_site'] is not True
                or worker['torch_imported'] is not False):
            raise NativeMaterialError('native parser isolation differs')
        used = []
        for row in worker['tools']:
            relative = str(Path(row['path']).relative_to(site))
            if tools.get(relative) != {'sha256': row['sha256'], 'size_bytes': row['size_bytes']}:
                raise NativeMaterialError('native parser tool provenance differs')
            used.append(MaterialSpan(**row))

        def native_type(row):
            return NativeType(row['text'], row['kind'], row.get('name'),
                native_type(row['element']) if row.get('element') else None, row.get('size'))

        def port(row):
            alias = row['alias']
            return NativeSchemaPort(row['position'], row['name'], row['kind'], native_type(row['type']),
                row['default'], NativeAliasDeclaration(tuple(alias['before']), alias['may_write'],
                    tuple(alias['after'])) if alias is not None else None)

        declarations = tuple(StaticNativeDeclaration(row['selector'], row['namespace'], row['operator'],
            row['overload'], row['schema'], row['cpp_signature'], MaterialSpan(**row['header_source']),
            MaterialSpan(**row['yaml_source']), MaterialSpan(**row['schema_source']),
            tuple(port(p) for p in row['inputs']), tuple(port(p) for p in row['outputs']),
            row['declared_mutable'], row['dispatch_declared'],
            tuple(NativeDispatchDeclaration(tuple(d['keys']), d['symbol'], MaterialSpan(**d['source'])) for d in row['dispatch']),
            tuple(NativeDeclaredField(f['name'], f['value_json'], MaterialSpan(**f['source'])) for f in row['fields']),
            tuple(row['open_fields'])) for row in report['declarations'])
        if tuple(row.selector for row in declarations) != selectors:
            raise NativeMaterialError('native parser changed selected operator scope')
        for row in declarations:
            for source in (row.header_source, row.yaml_source, row.schema_source,
                    *(d.source for d in row.dispatch), *(f.source for f in row.fields)):
                raw = read(Path(source.path))
                if (source.size_bytes != len(raw) or source.sha256 != hashlib.sha256(raw).hexdigest()
                        or not 0 <= source.byte_start < source.byte_end <= len(raw)
                        or source.selection_sha256 != hashlib.sha256(raw[source.byte_start:source.byte_end]).hexdigest()):
                    raise NativeMaterialError('native parser material span receipt differs')
        sources = tuple(_span(path, read(path)) for directory in (torch_dist, yaml_dist, typing_dist)
            for path in (directory / 'METADATA', directory / 'RECORD')) + (_span(site / 'torch/version.py', read(site / 'torch/version.py')),)
        return StaticNativeMaterials(version, constants.get('cuda'), constants['git_version'], sources,
            NativeParserReceipt(worker['executable'], worker['python_version'], _span(worker_path, worker_raw),
                tuple(used), True, True, False, tuple(worker['imported_tools'])), declarations)
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, NativeMaterialError):
            raise
        raise NativeMaterialError('invalid isolated native parser result: ' + str(error)) from error


__all__ = ['NativeMaterialError', 'NativeMaterialBudget', 'MaterialSpan', 'NativeType',
    'NativeAliasDeclaration', 'NativeSchemaPort', 'NativeDispatchDeclaration',
    'NativeDeclaredField', 'StaticNativeDeclaration', 'NativeParserReceipt',
    'StaticNativeMaterials', 'read_static_native_materials']
