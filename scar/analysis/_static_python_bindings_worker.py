"""Derive installed torchgen Python binding declarations in a -I -S tool process.

JSON stdin: {"site": "/canonical/site-packages", "names": ["torch.cat"]}.
Omit names for the complete generated catalog; bare names select every scope.
This executes build tooling only. It never imports torch or the analyzed program,
and generated declarations do not establish the wheel's runtime export table.
"""
from __future__ import annotations

import ast
import base64
import csv
import hashlib
import importlib.abc
import importlib.util
import inspect
import io
import json
from pathlib import Path
import re
import sys


def need(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    need(sys.flags.isolated and sys.flags.no_site, 'worker requires -I -S')
    sys.dont_write_bytecode = True
    worker_path = Path(__file__).resolve()
    worker_raw = worker_path.read_bytes()
    raw_request = sys.stdin.buffer.read(256_001)
    need(len(raw_request) <= 256_000, 'binding request byte budget')
    request = json.loads(raw_request)
    site = Path(request['site'])
    need(site.is_absolute() and site.resolve() == site and site.is_dir(),
         'tool site-packages must be an existing canonical directory')
    names = request.get('names')
    need(names is None or (isinstance(names, list) and len(names) <= 4096
         and all(isinstance(name, str) and re.fullmatch(r'[A-Za-z_][A-Za-z_0-9.]*', name)
                 for name in names) and len(set(names)) == len(names)),
         'names must be distinct Python export names')
    snapshots, tools, materials, imported_tools = {}, {}, {}, {}
    records_by_root = {}

    def read(path):
        path = Path(path)
        need(path.resolve() == path and path.is_relative_to(site) and path.is_file(),
             'noncanonical installed file: ' + str(path))
        if path not in snapshots:
            need(path.stat().st_size <= 8_000_000, 'installed file byte budget')
            snapshots[path] = path.read_bytes()
            need(sum(map(len, snapshots.values())) <= 64_000_000,
                 'installed materials byte budget')
        return snapshots[path]

    def receipt(path):
        path = Path(path)
        raw = read(path)
        return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(),
                'size_bytes': len(raw)}

    def source(path, first=1, last=None):
        path = Path(path)
        raw = read(path)
        lines = raw.splitlines(keepends=True)
        last = len(lines) if last is None else last
        start, end = sum(map(len, lines[:first - 1])), sum(map(len, lines[:last]))
        return {**receipt(path), 'start_line': first, 'end_line': last,
                'byte_start': start, 'byte_end': end,
                'selection_sha256': hashlib.sha256(raw[start:end]).hexdigest()}

    def distribution(prefix, expected_name):
        matches = []
        for directory in sorted(site.glob(prefix + '-*.dist-info')):
            metadata_path = directory / 'METADATA'
            metadata = read(metadata_path).decode('utf-8')
            fields = {}
            for line in metadata.split('\n\n', 1)[0].splitlines():
                if line.startswith(('Name: ', 'Version: ')):
                    key, value = line.split(': ', 1)
                    need(key not in fields, 'duplicate installed metadata header')
                    fields[key] = value
            if fields.get('Name', '').lower().replace('-', '_') == expected_name:
                matches.append((directory, fields['Version']))
        need(len(matches) == 1, 'one installed distribution required: ' + expected_name)
        directory, version = matches[0]
        record_path = directory / 'RECORD'
        records = {}
        for row in csv.reader(io.StringIO(read(record_path).decode('utf-8'))):
            need(len(row) == 3 and row[0] not in records, 'invalid installed RECORD')
            records[row[0]] = tuple(row[1:])
        for path in (directory / 'METADATA', record_path):
            materials[str(path)] = receipt(path)
        return version, records

    package_version, torch_records = distribution('torch', 'torch')
    _, yaml_records = distribution('pyyaml', 'pyyaml')
    _, typing_records = distribution('typing_extensions', 'typing_extensions')
    records_by_root.update(torchgen=torch_records, yaml=yaml_records,
                           typing_extensions=typing_records)

    def verified(relative, records, collection):
        path = site / relative
        raw = read(path)
        digest = 'sha256=' + base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).decode().rstrip('=')
        need(records.get(relative) == (digest, str(len(raw))),
             'installed RECORD receipt differs: ' + relative)
        collection[str(path)] = receipt(path)
        return path, raw

    class ToolLoader(importlib.abc.Loader):
        def __init__(self, relative, root):
            self.relative, self.root = relative, root

        def create_module(self, spec):
            return None

        def exec_module(self, module):
            path, raw = verified(self.relative, records_by_root[self.root], tools)
            imported_tools[module.__name__] = str(path)
            exec(compile(raw, str(path), 'exec', dont_inherit=True), module.__dict__)

    class ImportGuard(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            root = fullname.partition('.')[0]
            if root == 'torch':
                raise ImportError('torch import is forbidden in static binding tooling')
            if root in records_by_root:
                # Keep the YAML dependency on its audited pure Python path.
                if fullname == 'yaml.cyaml':
                    raise ImportError('pure Python YAML only')
                base = fullname.replace('.', '/')
                relative = next((name for name in (base + '.py', base + '/__init__.py')
                                 if name in records_by_root[root]), None)
                if relative is None:
                    directory = site / base
                    if (directory.is_dir() and directory.resolve() == directory
                            and any(name.startswith(base + '/') and name.endswith('.py')
                                    for name in records_by_root[root])):
                        spec = importlib.util.spec_from_loader(fullname, loader=None, is_package=True)
                        spec.submodule_search_locations = [str(directory)]
                        return spec
                    # from-package optional attribute probes must keep normal
                    # ImportError semantics (e.g. yaml.CSafeLoader fallback).
                    raise ImportError('unrecorded tool module: ' + fullname)
                return importlib.util.spec_from_file_location(
                    fullname, site / relative, loader=ToolLoader(relative, root),
                    submodule_search_locations=([str((site / relative).parent)]
                                                if relative.endswith('/__init__.py') else None))
            if root not in sys.stdlib_module_names:
                raise ImportError('target/non-tool import forbidden: ' + fullname)
            return None

    # Never add site-packages or the target directory to sys.path. Only these
    # RECORD-verified pure Python tools can be resolved by this finder.
    sys.meta_path.insert(0, ImportGuard())
    import yaml
    from torchgen.gen import parse_native_yaml
    from torchgen.context import native_function_manager
    from torchgen.api import python as python_api
    from torchgen.model import Argument, SelfArgument, TensorOptionsArguments, Variant
    from torchgen.packaged.autograd import gen_python_functions as generator

    def material(relative):
        return verified(relative, torch_records, materials)

    version_path, version_raw = material('torch/version.py')
    constants = {}
    for node in ast.parse(version_raw, filename=str(version_path)).body:
        targets = node.targets if isinstance(node, ast.Assign) else (
            (node.target,) if isinstance(node, ast.AnnAssign) else ())
        for target in targets:
            if isinstance(target, ast.Name) and target.id in ('__version__', 'git_version', 'cuda'):
                need(target.id not in constants and isinstance(node.value, ast.Constant),
                     'package version must be literal')
                constants[target.id] = node.value.value
    need(constants.get('__version__') == package_version
         and isinstance(constants.get('git_version'), str)
         and re.fullmatch(r'[a-f0-9]{40}', constants['git_version']),
         'package metadata/version/source revision disagree')

    native_path, native_raw = material('torchgen/packaged/ATen/native/native_functions.yaml')
    tags_path, _ = material('torchgen/packaged/ATen/native/tags.yaml')
    deprecated_path, deprecated_raw = material('torchgen/packaged/autograd/deprecated.yaml')

    # Exact YAML record spans also cover generated NativeFunctions whose loc
    # refers back to the original record; derived schemas are marked below.
    native_nodes = yaml.compose(native_raw.decode('utf-8'), Loader=yaml.SafeLoader)
    native_sources = {}
    for node in native_nodes.value:
        fields = {key.value: value for key, value in node.value}
        first = node.start_mark.line + 1
        native_sources[first] = (source(native_path, first, node.end_mark.line + 1),
                                 fields['func'].value)
    deprecated_nodes = yaml.compose(deprecated_raw.decode('utf-8'), Loader=yaml.SafeLoader)
    deprecated_sources = {}
    for node in deprecated_nodes.value:
        fields = {key.value: value for key, value in node.value}
        deprecated_sources[fields['name'].value] = source(
            deprecated_path, node.start_mark.line + 1, node.end_mark.line + 1)

    native_functions = parse_native_yaml(str(native_path), str(tags_path)).native_functions
    native_functions = list(filter(generator.should_generate_py_binding, native_functions))
    pairs_by_method = {
        method: generator.load_signatures(native_functions, str(deprecated_path), method=method)
        for method in (False, True)
    }
    # These are the table scopes of the official generator/templates. The
    # module argument controls __torch_function__ metadata, not Python re-exports.
    scopes = [
        ('torch', 'torch', False, 'is_py_torch_function', 'python_torch_functions.cpp'),
        ('torch.Tensor', None, True, 'is_py_variable_method', 'python_variable_methods.cpp'),
        *[('torch._C._' + name, 'torch.' + name, False, 'is_py_' + name + '_function',
           'python_' + name + '_functions.cpp')
          for name in ('nn', 'fft', 'linalg', 'nested', 'sparse', 'special')],
    ]

    api_objects = {
        'parse_native_yaml': parse_native_yaml,
        'should_generate_py_binding': generator.should_generate_py_binding,
        'load_signatures': generator.load_signatures,
        'group_filter_overloads': generator.group_filter_overloads,
        'group_overloads': generator.group_overloads,
        'method_def': generator.method_def,
        'method_impl': generator.method_impl,
        'emit_single_dispatch': generator.emit_single_dispatch,
        'signature_str': python_api.PythonSignature.signature_str,
        'argument_str': python_api.PythonArgument.argument_str,
        'signature_from_schema': python_api.signature_from_schema,
        'cpp_signature': python_api.CppSignatureGroup.from_native_function,
        'cpp_arguments': python_api.cpp.arguments,
        **{name: getattr(python_api, name) for name in (
            'arg_parser_output_exprs', 'dispatch_lambda_args', 'dispatch_lambda_exprs',
            'dispatch_lambda_return_str', 'cpp_dispatch_target', 'cpp_dispatch_exprs')},
        **{scope[3]: getattr(generator, scope[3]) for scope in scopes},
    }
    api_sources = {}
    for name, obj in api_objects.items():
        obj = inspect.unwrap(obj)
        lines, first = inspect.getsourcelines(obj)
        api_sources[name] = source(inspect.getsourcefile(obj), first, first + len(lines) - 1)

    def schema_arguments(argument):
        if isinstance(argument, Argument):
            return [argument.name]
        if isinstance(argument, SelfArgument):
            return [argument.argument.name]
        if isinstance(argument, TensorOptionsArguments):
            return [item.name for item in argument.all()]
        raise ValueError('unsupported official C++ argument: ' + type(argument).__name__)

    bindings, wrappers, selected_names = [], {}, set()
    for namespace, module, method, predicate, template_name in scopes:
        template_path, _ = material('torchgen/packaged/autograd/templates/' + template_name)
        grouped = generator.group_filter_overloads(pairs_by_method[method], getattr(generator, predicate))
        for name in sorted(grouped, key=str):
            export_name = str(name)
            qualified = namespace + '.' + export_name
            selected = {item for item in names or () if item in (qualified, export_name)}
            if names is not None and not selected:
                continue
            selected_names.update(selected)
            pairs = grouped[name]
            _, structseq_typenames = generator.emit_structseq_call(pairs)
            table_entry = generator.method_def(name, module, pairs, method=method)
            groups = generator.group_overloads(pairs, symint=True)
            wrapper_text = generator.method_impl(name, module, pairs, method=method, symint=True)
            registration_container = ('torch._C._VariableFunctions' if namespace == 'torch' else
                                      'torch._C.TensorBase' if method else namespace)
            registration_source = source(template_path)
            registration_sources = [registration_source]
            if method:
                tensor_path, _ = material('torch/_tensor.py')
                registration_sources.append(source(tensor_path, 102, 102))
            wrappers[qualified] = {
                'text': wrapper_text, 'sha256': hashlib.sha256(wrapper_text.encode()).hexdigest(),
                'generated_method_def': table_entry,
                'parser_signatures': [group.signature.signature_str(symint=True) for group in groups],
                'registration_container': registration_container,
                'registration_sources': registration_sources,
                'family_complete': True,
                'sources': [api_sources['method_impl'], api_sources['method_def'], source(template_path)],
            }
            for parser_index, group in enumerate(groups):
                ps = group.signature
                arguments = []
                for index, argument in enumerate(ps.arguments()):
                    formal = argument.argument_str(method=method, symint=True)
                    parser_name = formal.split(' ', 1)[1].split('=', 1)[0]
                    arguments.append({
                        'name': parser_name, 'schema_name': argument.name,
                        'type': str(argument.type),
                        'parser_type': python_api.argument_type_str(argument.type, symint=True),
                        'default': formal.partition('=')[2] if argument.default is not None else None,
                        'generator_default': argument.default, 'default_init': argument.default_init,
                        'parser_formal': formal,
                        'keyword_only': index >= len(ps.input_args),
                        'kind': 'keyword_only' if index >= len(ps.input_args) else 'positional_or_keyword',
                        'parser_index': index,
                        'position': index if index < len(ps.input_args) else None,
                        'output': argument is ps.output_args,
                        'tensor_option': argument in ps.tensor_options_args,
                    })
                branches = [('base', group.base)]
                if group.outplace is not None:
                    branches.append(('out', group.outplace))
                for branch, function in branches:
                    with native_function_manager(function):
                        parser_outputs = python_api.arg_parser_output_exprs(ps, function, symint=True)
                        lambda_args = python_api.dispatch_lambda_args(ps, function, symint=True)
                        lambda_exprs = python_api.dispatch_lambda_exprs(ps, function, symint=True)
                        target = python_api.cpp_dispatch_target(function)
                        cpp_args = python_api.cpp_dispatch_exprs(function, python_signature=ps)
                        generated_dispatch = generator.emit_single_dispatch(ps, function, structseq_typenames, symint=True)
                        lambda_return = python_api.dispatch_lambda_return_str(function)
                        # Binding.argument links a C++ formal explicitly to one
                        # or several schema arguments; Python/native port order
                        # is never used as a schema correspondence heuristic.
                        cpp_signatures = python_api.CppSignatureGroup.from_native_function(
                            function, method=False)
                        # cpp_dispatch_target uses has_symint() to choose the
                        # target spelling; retain that overload's formal types.
                        cpp_bindings = (cpp_signatures.symint_signature or
                                        cpp_signatures.signature).arguments()
                        if Variant.method in function.variants:
                            cpp_bindings = [item for item in cpp_bindings if item.name != 'self']
                        need(len(cpp_bindings) == len(cpp_args), 'official C++ binding/expression arity differs')
                        expr_schema_args = {}
                        for formal_binding, expression in zip(cpp_bindings, cpp_args):
                            expr_schema_args.setdefault(expression, []).extend(schema_arguments(formal_binding.argument))
                        if Variant.method in function.variants:
                            expr_schema_args['self'] = ['self']
                    native_source, original_schema = native_sources[function.loc.line]
                    sources = [native_source, source(template_path), api_sources['should_generate_py_binding'],
                               api_sources[predicate], api_sources['load_signatures'],
                               api_sources['group_overloads'], api_sources['emit_single_dispatch']]
                    if ps.deprecated:
                        sources.append(deprecated_sources[str(ps.deprecated_schema)])

                    def parser_schema_arguments(output):
                        result = list(expr_schema_args.get(output.name, []))
                        # signature_from_schema explicitly scatters these
                        # TensorOptions fields and packs multi-output formals.
                        options = function.func.arguments.tensor_options
                        if options is not None:
                            result.extend(item.name for item in options.all() if item.name == output.name)
                        if isinstance(output.argument, python_api.PythonOutArgument):
                            for item in output.argument.outputs:
                                result.extend(expr_schema_args.get(item.name, []))
                        return sorted(set(result))

                    conversions = [
                        {'stage': 'python_arg_parser', 'argument': output.name,
                         'parser_index': output.index, 'expression': output.expr,
                         'schema_arguments': parser_schema_arguments(output)}
                        for output in parser_outputs.values()
                    ] + [
                        {'stage': 'dispatch_lambda', 'argument': arg.name, 'type': arg.type_str,
                         'output': arg.is_out_arg, 'expression': expression,
                         'schema_arguments': sorted(set(expr_schema_args.get(arg.name, [])))}
                        for arg, expression in zip(lambda_args, lambda_exprs.exprs)
                    ]
                    bindings.append({
                        'export_namespace': namespace, 'export_name': export_name,
                        'kind': 'method' if method else 'function',
                        'native_selector': function.namespace + '::' + str(function.func.name),
                        'native_schema': str(function.func),
                        'parser_signature': ps.signature_str(symint=True),
                        'parser_index': parser_index, 'group_id': qualified + '#' + str(parser_index),
                        'arguments': arguments, 'conversions': conversions,
                        'dispatch_expression': target + '(' + ', '.join(cpp_args) + ')',
                        'dispatch_target': target, 'dispatch_arguments': list(cpp_args),
                        'dispatch_lambda_initializers': list(lambda_exprs.inits),
                        'dispatch_lambda_return': lambda_return,
                        'generated_dispatch': generated_dispatch,
                        'generated_method_def': table_entry, 'generator_module': module,
                        'wrapper_id': qualified, 'family_complete': True,
                        'registration_container': registration_container,
                        'registration_source': registration_source,
                        'registration_sources': registration_sources,
                        'registration_status': 'GENERATOR_DECLARATION_NOT_RUNTIME_EXPORT_OBSERVATION',
                        'cpp_argument_bindings': [
                            {'name': formal_binding.name, 'type': formal_binding.type,
                             'expression': expression,
                             'schema_arguments': schema_arguments(formal_binding.argument)}
                            for formal_binding, expression in zip(cpp_bindings, cpp_args)
                        ],
                        'branch': branch,
                        'branch_condition': (None if group.outplace is None else
                            ('' if branch == 'base' else '!') + '_r.isNone(' + str(ps.output_idx()) + ')'),
                        'implicit_receiver': 'self' if method else None,
                        'deprecated': ps.deprecated,
                        'deprecated_schema': str(ps.deprecated_schema) if ps.deprecated else None,
                        'native_generated': 'generated' in function.tags,
                        'native_source_schema': original_schema,
                        'sources': sources,
                    })

    # Detect unexpected file changes across official tool reads too.
    need(all(path.read_bytes() == raw for path, raw in snapshots.items()),
         'installed tooling/material changed during derivation')
    need(worker_path.read_bytes() == worker_raw, 'worker changed during derivation')
    torch_imported = any(name.partition('.')[0] == 'torch' for name in sys.modules)
    need(not torch_imported, 'torch import is forbidden')
    report = {
        'protocol_version': 1, 'package_version': package_version,
        'catalog_scope': 'TORCHGEN_GENERATED_NATIVE_PYTHON_BINDINGS',
        'manual_bindings_included': False, 'python_reexports_resolved': False,
        'source_revision': constants['git_version'], 'cuda_build': constants.get('cuda'),
        'bindings': bindings, 'wrappers': wrappers, 'tools': [tools[key] for key in sorted(tools)],
        'materials': [materials[key] for key in sorted(materials)], 'api_sources': api_sources,
        'unmatched_names': [] if names is None else sorted(set(names) - selected_names),
        'torch_imported': torch_imported,
        'worker': {'isolated': bool(sys.flags.isolated), 'no_site': bool(sys.flags.no_site),
                   'torch_imported': torch_imported, 'executable': sys.executable,
                   'python_version': sys.version, 'imported_tools': imported_tools,
                   'path': str(worker_path), 'size_bytes': len(worker_raw),
                   'sha256': hashlib.sha256(worker_raw).hexdigest()},
        'open_conditions': [
            'WHEEL_RUNTIME_EXPORT_TABLE_AND_PYTHON_REEXPORTS',
            'RUNTIME_ARGUMENT_ACCEPTANCE_AND_SELECTED_OVERLOAD',
            'RUNTIME_DISPATCH_AND_SELECTED_KERNEL',
            'REFERENCE_ALIAS_IDENTITY_AND_STORAGE',
            'STATE_RNG_EXTERNAL_EFFECTS_AND_EXCEPTION_COMPLETENESS',
        ],
    }
    encoded = json.dumps(report, ensure_ascii=False, allow_nan=False).encode()
    need(len(encoded) <= 64_000_000, 'binding output byte budget')
    sys.stdout.buffer.write(encoded)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        sys.stderr.write(type(error).__name__ + ': ' + str(error)[:1500] + '\n')
        raise SystemExit(2)
