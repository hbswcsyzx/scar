"""Isolated, receipt-bound build-tool parser. Never import target/PyTorch code."""
from __future__ import annotations

import hashlib
import base64
import csv
import importlib.abc
import importlib.util
import json
import io
from pathlib import Path
import re
import sys


def need(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    need(sys.flags.isolated and sys.flags.no_site, 'worker requires -I -S')
    raw_request = sys.stdin.buffer.read(256_001)
    need(len(raw_request) <= 256_000, 'parser request byte budget')
    request = json.loads(raw_request)
    site = Path(request['site']); budget = request['budget']; loaded = {}
    need(site.is_absolute() and site.resolve() == site, 'tool directory must be canonical')

    def read(relative, expected):
        path = site / relative
        need(path.resolve() == path and path.is_relative_to(site) and path.is_file(), 'noncanonical tool/material path')
        need(path.stat().st_size <= budget['max_file_bytes'], 'parser file byte budget')
        raw = path.read_bytes()
        need(expected == {'sha256': hashlib.sha256(raw).hexdigest(), 'size_bytes': len(raw)},
             'tool/material receipt differs: ' + relative)
        return path, raw

    def span(relative, raw, begin=0, end=None):
        end = len(raw) if end is None else end
        return {'path': str(site / relative), 'sha256': hashlib.sha256(raw).hexdigest(),
            'size_bytes': len(raw), 'byte_start': begin, 'byte_end': end,
            'start_line': raw[:begin].count(b'\n') + 1,
            'end_line': max(raw[:begin].count(b'\n') + 1, raw[:end].count(b'\n') + (not raw[:end].endswith(b'\n'))),
            'selection_sha256': hashlib.sha256(raw[begin:end]).hexdigest()}

    class VerifiedLoader(importlib.abc.Loader):
        def __init__(self, relative):
            self.relative = relative
        def create_module(self, spec):
            return None
        def exec_module(self, module):
            path, raw = read(self.relative, request['tools'][self.relative])
            loaded[module.__name__] = span(self.relative, raw)
            exec(compile(raw, str(path), 'exec', dont_inherit=True), module.__dict__)

    class ImportGuard(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            root = fullname.partition('.')[0]
            if root in ('torchgen', 'yaml', 'typing_extensions'):
                # Force SafeLoader's pure Python implementation. No C extension
                # or generator/API submodule is part of the audited tool chain.
                if fullname == 'yaml.cyaml':
                    raise ImportError('pure Python YAML parser only')
                base = fullname.replace('.', '/')
                relative = next((name for name in (base + '.py', base + '/__init__.py')
                    if name in request['tools']), None)
                need(relative is not None, 'unaudited parser submodule: ' + fullname)
                return importlib.util.spec_from_file_location(fullname, site / relative,
                    loader=VerifiedLoader(relative), submodule_search_locations=(
                        [str((site / relative).parent)] if relative.endswith('/__init__.py') else None))
            if root not in sys.stdlib_module_names:
                raise ImportError('target/non-tool import forbidden: ' + fullname)
            return None

    sys.meta_path.insert(0, ImportGuard())
    # No site-packages path is inserted: approved tool modules can only be
    # resolved by the verified loader, never by CWD, .pth or a shadow package.
    import yaml
    from torchgen.model import (BaseType, CustomClassType, DispatchKey, FunctionSchema,
        ListType, OptionalType)
    from torchgen.utils import NamespaceHelper

    record_name = request['torch_record']
    _, record_raw = read(record_name, request['materials'][record_name])
    installed = {}
    for row in csv.reader(io.StringIO(record_raw.decode('utf-8'))):
        need(len(row) == 3 and row[0] not in installed, 'invalid/duplicate installed RECORD')
        installed[row[0]] = row[1:]

    def header_file(relative):
        need(relative in installed, 'generated native header is absent from installed RECORD')
        digest, size = installed[relative]
        need(digest.startswith('sha256=') and size.isdecimal(), 'generated native header has no exact receipt')
        encoded = digest.partition('=')[2]
        expected = {'sha256': base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)).hex(),
            'size_bytes': int(size)}
        return read(relative, expected)

    yaml_relative = 'torchgen/packaged/ATen/native/native_functions.yaml'
    _, yaml_raw = read(yaml_relative, request['materials'][yaml_relative])
    yaml_text = yaml_raw.decode('utf-8')
    loader = yaml.SafeLoader(yaml_text)
    try:
        document = loader.get_single_node()
        need(isinstance(document, yaml.SequenceNode), 'native YAML must be a sequence')
        pending = [document]; seen = set()
        safe_tags = {'tag:yaml.org,2002:' + tag for tag in ('map', 'seq', 'str', 'null', 'bool', 'int', 'float')}
        while pending:
            node = pending.pop()
            need(id(node) not in seen, 'YAML aliases are outside this material profile')
            seen.add(id(node)); need(len(seen) <= budget['max_yaml_nodes'], 'YAML node budget')
            need(node.tag in safe_tags, 'non-data YAML tag')
            if isinstance(node, yaml.MappingNode):
                keys = set()
                for key, value in node.value:
                    need(isinstance(key, yaml.ScalarNode) and key.tag == 'tag:yaml.org,2002:str'
                        and key.value not in keys, 'YAML keys must be distinct strings')
                    keys.add(key.value); pending.extend((key, value))
            elif isinstance(node, yaml.SequenceNode):
                pending.extend(node.value)

        def node_span(node):
            return span(yaml_relative, yaml_raw, len(yaml_text[:node.start_mark.index].encode()),
                len(yaml_text[:node.end_mark.index].encode()))

        selected_records = {}
        for row in document.value:
            need(isinstance(row, yaml.MappingNode), 'native YAML record must be a mapping')
            fields = {key.value: value for key, value in row.value}
            func = fields.get('func')
            need(isinstance(func, yaml.ScalarNode) and func.tag == 'tag:yaml.org,2002:str', 'native schema must be text')
            # Only the name before the first '(' selects a record. Function
            # parameters, aliases and defaults are parsed by torchgen below.
            name = func.value.partition('(')[0]
            canonical = name if '::' in name else 'aten::' + name
            if canonical in request['selectors']:
                need(canonical not in selected_records, 'ambiguous selected native YAML schema')
                selected_records[canonical] = row, fields

        def native_type(value):
            result = {'text': str(value), 'kind': type(value).__name__}
            if type(value) is BaseType:
                result['name'] = value.name.name
            elif type(value) is CustomClassType:
                result['name'] = value.class_name
            elif type(value) is OptionalType:
                result['element'] = native_type(value.elem)
            elif type(value) is ListType:
                result.update(element=native_type(value.elem), size=value.size)
            else:
                raise ValueError('unsupported source schema type: ' + type(value).__name__)
            return result

        def port(value, position, kind):
            annotation = value.annotation
            return {'position': position, 'name': value.name, 'kind': kind,
                'type': native_type(value.type), 'default': getattr(value, 'default', None),
                'alias': None if annotation is None else {'before': annotation.alias_set,
                    'may_write': annotation.is_write, 'after': annotation.alias_set_after}}

        declarations = []
        for selector in request['selectors']:
            need(selector in selected_records, 'unknown exact native schema: ' + selector)
            row, fields = selected_records[selector]
            raw_schema = fields['func'].value
            need(len(raw_schema.encode()) <= budget['max_schema_bytes'], 'schema byte budget')
            namespace = NamespaceHelper.from_namespaced_entity(raw_schema, max_level=1)
            schema_text = namespace.entity_name
            schema = FunctionSchema.parse(schema_text)
            need(str(schema) == schema_text, 'schema grammar did not roundtrip exactly')
            operator_name = str(schema.name.name)
            overload = schema.name.overload_name
            canonical_namespace = namespace.get_cpp_namespace(default='aten')
            need(selector == canonical_namespace + '::' + str(schema.name), 'schema selector changed during parsing')
            # This is the exact torchgen NativeFunction.root_name rule. The
            # parser already distinguishes inplace/dunder/functional spelling.
            relative = 'torch/include/ATen/ops/' + schema.name.name.base + '_ops.h'
            _, header = header_file(relative)
            header_text = header.decode('utf-8')
            matches = []
            for match in re.finditer(r'struct TORCH_API [A-Za-z_0-9]+ \{\n(.*?)\n\};', header_text, re.S):
                body = match.group(1)
                strings = {}
                for key in ('name', 'overload_name', 'schema_str'):
                    found = re.findall(r'static constexpr const char\* ' + key + r' = ("(?:[^"\\]|\\.)*");', body)
                    need(len(found) == 1, 'generated operator header field is ambiguous')
                    strings[key] = json.loads(found[0])
                if strings['name'] == canonical_namespace + '::' + operator_name and strings['overload_name'] == overload:
                    need(strings['schema_str'] == schema_text, 'header/YAML schema contract differs')
                    signatures = re.findall(r'using schema = ([^\n]+);', body)
                    need(len(signatures) == 1, 'generated native signature is ambiguous')
                    matches.append((match, signatures[0]))
            need(len(matches) == 1, 'one exact generated header signature is required')
            match, signature = matches[0]
            dispatch = []
            if 'dispatch' in fields:
                dispatch_node = fields['dispatch']
                need(isinstance(dispatch_node, yaml.MappingNode), 'dispatch declaration must be a mapping')
                for key, value in dispatch_node.value:
                    need(value.tag == 'tag:yaml.org,2002:str', 'native dispatch symbol must be text')
                    keys = tuple(DispatchKey.parse(k.strip()).name for k in key.value.split(','))
                    need(keys and len(set(keys)) == len(keys), 'dispatch declaration repeats keys')
                    dispatch.append({'keys': keys, 'symbol': value.value, 'source': node_span(value)})
            positional = {id(a) for a in schema.arguments.flat_positional}
            out = {id(a) for a in schema.arguments.out}
            declaration_fields = []
            for name in ('variants', 'device_check', 'device_guard', 'tags', 'structured',
                         'structured_delegate', 'autogen', 'manual_kernel_registration'):
                if name in fields:
                    declaration_fields.append({'name': name,
                        'value_json': json.dumps(loader.construct_object(fields[name], deep=True),
                            ensure_ascii=False, allow_nan=False, sort_keys=True),
                        'source': node_span(fields[name])})
            declarations.append({'selector': selector, 'namespace': canonical_namespace,
                'operator': operator_name, 'overload': overload, 'schema': schema_text,
                'cpp_signature': signature,
                'header_source': span(relative, header, len(header_text[:match.start()].encode()),
                    len(header_text[:match.end()].encode())),
                'yaml_source': node_span(row), 'schema_source': node_span(fields['func']),
                'inputs': [port(a, i, 'out' if id(a) in out else 'positional' if id(a) in positional else 'keyword_only')
                    for i, a in enumerate(schema.schema_order_arguments())],
                'outputs': [port(a, i, 'return') for i, a in enumerate(schema.returns)],
                'declared_mutable': schema.is_mutable, 'dispatch_declared': 'dispatch' in fields,
                'dispatch': dispatch, 'fields': declaration_fields,
                'open_fields': ['PYTHON_CALLABLE_AND_OVERLOAD_BINDING', 'RUNTIME_DISPATCH_AND_KERNEL',
                    'ALIAS_IDENTITY_AND_STORAGE', 'STATE_EFFECT_COMPLETENESS', 'RNG_AND_EXTERNAL_EFFECTS',
                    'EXCEPTIONS_AND_LIFETIME', 'PHYSICAL_RESOURCES_TRANSFERS_AND_ORDER']})
    finally:
        loader.dispose()
    torch_imported = any(name.partition('.')[0] == 'torch' for name in sys.modules)
    need(not torch_imported, 'PyTorch import is forbidden')
    report = {'declarations': declarations, 'worker': {'isolated': bool(sys.flags.isolated),
        'no_site': bool(sys.flags.no_site), 'torch_imported': torch_imported,
        'executable': sys.executable, 'python_version': sys.version,
        'tools': [loaded[name] for name in sorted(loaded)], 'imported_tools': sorted(loaded)}}
    encoded = json.dumps(report, ensure_ascii=False, allow_nan=False).encode()
    need(len(encoded) <= budget['max_output_bytes'], 'parser output byte budget')
    sys.stdout.buffer.write(encoded)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        sys.stderr.write(type(error).__name__ + ': ' + str(error)[:1200])
        raise SystemExit(2)
