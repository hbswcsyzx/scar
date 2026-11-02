"""Private C++ source parser. Point positions are derived from raw bytes only."""
from __future__ import annotations

import resource
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

import base64
import bisect
import csv
import hashlib
import importlib.abc
import importlib.machinery
import importlib.util
import io
import json
from pathlib import Path
import re
import sys
import sysconfig


def need(value, detail):
    if not value:
        raise ValueError(detail)


def receipt(path, raw):
    digest = hashlib.sha256(raw).hexdigest()
    return {'path': str(path), 'sha256': digest, 'size_bytes': len(raw), 'byte_start': 0,
        'byte_end': len(raw), 'start_line': 1, 'end_line': max(1, len(raw.splitlines())), 'selection_sha256': digest}


def main():
    need(sys.flags.isolated and sys.flags.no_site, 'analyzer requires -I -S')
    request_raw = sys.stdin.buffer.read(256_001)
    need(len(request_raw) <= 256_000, 'request byte budget')
    request = json.loads(request_raw); budget = request['budget']
    source = Path(request['source']['path']); raw = source.read_bytes()
    need(len(raw) <= budget['max_source_bytes'] and receipt(source, raw) == request['source'], 'source receipt/byte budget differs')
    tool_site = Path(sysconfig.get_path('purelib')).resolve()
    need(tool_site.is_relative_to(Path(sys.prefix)), 'private analyzer site is outside venv')
    approved, tools, versions = {}, [], []
    tool_bytes = 0
    for package in ('tree_sitter', 'tree_sitter_cpp'):
        directories = list(tool_site.glob(package + '-*.dist-info'))
        need(len(directories) == 1, 'MISSING_ANALYZER_TOOL: ' + package)
        directory = directories[0]
        metadata = (directory / 'METADATA').read_bytes()
        version = next(line.partition(': ')[2] for line in metadata.decode().splitlines() if line.startswith('Version: '))
        versions.append((package, version)); tools.append(receipt(directory / 'METADATA', metadata))
        record = (directory / 'RECORD').read_bytes(); tools.append(receipt(directory / 'RECORD', record))
        for relative, digest, size in csv.reader(io.StringIO(record.decode())):
            if relative.startswith(package + '/') and relative.endswith(('.py', '.so')):
                path = tool_site / relative
                need(path.resolve() == path and path.is_relative_to(tool_site), 'noncanonical analyzer tool')
                payload = path.read_bytes(); tool_bytes += len(payload)
                need(tool_bytes <= budget['max_tool_bytes'], 'analyzer tool byte budget')
                actual = 'sha256=' + base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).decode().rstrip('=')
                need((digest, size) == (actual, str(len(payload))), 'analyzer RECORD receipt differs')
                approved[str(path)] = payload
                tools.append(receipt(path, payload))

    class VerifiedSource(importlib.abc.Loader):
        def __init__(self, path):self.path = path
        def create_module(self, spec):return None
        def exec_module(self, module):
            exec(compile(approved[self.path], self.path, 'exec', dont_inherit=True), module.__dict__)

    class Guard(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            root = fullname.partition('.')[0]
            if root in ('tree_sitter', 'tree_sitter_cpp'):
                spec = importlib.machinery.PathFinder.find_spec(fullname, path)
                need(spec is not None and spec.origin in approved, 'unreceipted analyzer module: ' + fullname)
                if spec.origin.endswith('.py'):
                    return importlib.util.spec_from_file_location(fullname, spec.origin, loader=VerifiedSource(spec.origin),
                        submodule_search_locations=list(spec.submodule_search_locations) if spec.submodule_search_locations is not None else None)
                return spec
            if root not in sys.stdlib_module_names:
                raise ImportError('target/non-analyzer import forbidden: ' + fullname)
            return None

    sys.path.insert(0, str(tool_site)); sys.meta_path.insert(0, Guard())
    from tree_sitter import Language, Parser
    import tree_sitter_cpp
    tree = Parser(Language(tree_sitter_cpp.language())).parse(raw)
    offsets = [0] + [i + 1 for i, byte in enumerate(raw) if byte == 10]
    nodes = []; pending = [tree.root_node]
    while pending:
        node = pending.pop(); nodes.append(node)
        need(len(nodes) <= budget['max_nodes'], 'CST node budget')
        pending.extend(reversed(node.named_children))

    occurrences, selected_nodes, edges = {}, {}, {}
    def text(node):return raw[node.start_byte:node.end_byte].decode('utf-8')
    def key(node):return node.type, node.start_byte, node.end_byte
    def occurrence(kind, start, end, role, *, error=False, missing=False):
        coordinate = kind, start, end
        identity = 'cpp:' + hashlib.sha256(json.dumps((request['source']['sha256'], *coordinate), separators=(',', ':')).encode()).hexdigest()
        if identity not in occurrences:
            need(len(occurrences) < budget['max_occurrences'], 'source occurrence budget')
            row = bisect.bisect_right(offsets, start) - 1
            end_row = bisect.bisect_right(offsets, end) - 1
            occurrences[identity] = {'id': identity, 'kind': kind, 'start': start, 'end': end,
                'start_line': row + 1, 'end_line': end_row + 1, 'start_column': start - offsets[row],
                'end_column': end - offsets[end_row], 'roles': set(), 'has_error': error, 'missing': missing}
        occurrences[identity]['roles'].add(role)
        return identity
    def select(node, role):
        if node is None:return None
        identity = occurrence(node.type, node.start_byte, node.end_byte, role, error=node.has_error, missing=node.is_missing)
        selected_nodes[key(node)] = (identity, node)
        return identity
    def relation(source_id, target_id, role, position=None, kind='STRUCTURE'):
        if source_id is None or target_id is None:return
        coordinate = source_id, target_id, kind, role, position
        if coordinate not in edges:
            need(len(edges) < budget['max_relations'], 'source relation budget')
            edges[coordinate] = dict(source=source_id, target=target_id, kind=kind, role=role, position=position)
    def expression(node, role):
        if node is None:return None
        result = select(node, role); todo = [node]
        while todo:
            parent = todo.pop(); parent_id = select(parent, 'expression-structure')
            for position, child in enumerate(parent.named_children):
                child_id = select(child, 'expression-structure')
                relation(parent_id, child_id, 'expression-child', position)
                todo.append(child)
        return result
    def namespace(node):
        result = []; parent = node.parent
        while parent is not None:
            if parent.type == 'namespace_definition':
                name = parent.child_by_field_name('name')
                result.append(text(name) if name is not None else '<anonymous>')
            parent = parent.parent
        return tuple(reversed(result))
    def ancestors(node, predicate):
        result = []; parent = node.parent
        while parent is not None:
            if predicate(parent):result.append(parent)
            parent = parent.parent
        return tuple(reversed(result))
    def preprocessor(node):
        return [select(n, 'preprocessor-context') for n in ancestors(node, lambda n:n.type.startswith('preproc_'))]
    def declarator_name(node):
        seen = set()
        while node is not None and key(node) not in seen:
            seen.add(key(node))
            if node.type in ('identifier', 'field_identifier', 'qualified_identifier', 'operator_name', 'destructor_name'):
                return node
            node = node.child_by_field_name('declarator')
        return None

    unit = select(tree.root_node, 'source-unit')
    holes = []
    if request['pattern'] is not None:
        source_text = raw.decode('utf-8')
        for match in re.finditer(request['pattern'], source_text, re.MULTILINE):
            start = len(source_text[:match.start()].encode()); end = len(source_text[:match.end()].encode())
            holes.append(occurrence('template_hole', start, end, 'unexpanded-template-substitution'))
    errors = [select(n, 'parse-error' if n.type == 'ERROR' else 'missing-syntax') for n in nodes if n.type == 'ERROR' or n.is_missing]
    functions = []; functions_by_key = {}; functions_by_symbol = {}
    for node in nodes:
        if node.type != 'function_definition':continue
        identity = select(node, 'function-definition')
        declarator = node.child_by_field_name('declarator'); body = node.child_by_field_name('body')
        need(declarator is not None and body is not None, 'function syntax lacks its original declarator/body')
        decl = expression(declarator, 'function-declarator'); body_id = select(body, 'function-body')
        name = declarator_name(declarator); name_id = select(name, 'function-name')
        relation(identity, decl, 'declarator'); relation(identity, body_id, 'body'); relation(decl, name_id, 'declared-name')
        fields = ['CPP_TYPE_AND_OVERLOAD_RESOLUTION', 'SOURCE_TO_BINARY_CORRESPONDENCE']
        if node.has_error:fields.append('PARSE_ERROR_IN_FUNCTION')
        item = dict(id=identity, declarator=decl, body=body_id, name=name_id,
            symbol=text(name) if name is not None else None, namespaces=namespace(node),
            preprocessor=preprocessor(node), open_fields=fields)
        functions.append(item); functions_by_key[key(node)] = item
        if item['symbol'] is not None:
            functions_by_symbol.setdefault((item['symbol'], tuple(item['namespaces'])), []).append(identity)

    def references(node):
        result = []; todo = [node] if node is not None else []
        while todo:
            current = todo.pop()
            if current.type in ('identifier', 'field_identifier', 'type_identifier', 'qualified_identifier'):
                identity = select(current, 'symbol-reference'); spelling = text(current)
                # This is a same-file, lexical-namespace spelling candidate,
                # never C++ lookup, overload selection or wrapper identity.
                candidates = functions_by_symbol.get((spelling, namespace(current)), ())
                for candidate in candidates:relation(identity, candidate, 'local-function-definition-candidate', kind='SOURCE')
                result.append(dict(id=identity, spelling=spelling, candidates=candidates,
                    status='LOCAL_DEFINITION_CANDIDATES' if candidates else 'BODY_NOT_SUPPLIED_IN_THIS_FILE'))
                if current.type == 'qualified_identifier':continue
            todo.extend(reversed(current.named_children))
        return result

    tables, entries = [], []
    for node in nodes:
        if node.type != 'declaration':continue
        type_node = node.child_by_field_name('type')
        if type_node is None or text(type_node) != 'PyMethodDef':continue
        for declarator in node.named_children:
            if declarator.type != 'init_declarator':continue
            value = declarator.child_by_field_name('value')
            if value is None or value.type != 'initializer_list':continue
            table_id = select(declarator, 'method-table'); table_name = declarator_name(declarator.child_by_field_name('declarator'))
            name_id = select(table_name, 'method-table-name'); relation(table_id, name_id, 'table-name')
            table_entries, terminators, unclassified = [], [], []
            for position, row in enumerate(value.named_children):
                if row.type == 'comment':continue
                if row.type != 'initializer_list':
                    unclassified.append(select(row, 'unclassified-table-syntax')); continue
                items = [n for n in row.named_children if n.type != 'comment']
                row_id = select(row, 'method-table-entry')
                if len(items) == 1 and text(items[0]) in ('nullptr', 'NULL', '0'):
                    terminators.append(select(row, 'method-table-terminator')); relation(table_id, row_id, 'terminator', position); continue
                table_entries.append(row_id); relation(table_id, row_id, 'explicit-method-entry', len(table_entries)-1)
                selected = [expression(item, role) for item, role in zip(items, ('method-name', 'callback-expression', 'method-flags', 'method-documentation'))]
                selected += [None] * (4-len(selected)); name, callback, flags, documentation = selected
                for role, child in zip(('name', 'callback', 'flags', 'documentation'), selected):relation(row_id, child, role)
                python_name = None
                if items and items[0].type == 'string_literal':
                    try:python_name = json.loads(text(items[0]))
                    except (ValueError, TypeError):pass
                fields = ['RUNTIME_DESCRIPTOR_AND_RECEIVER_BINDING', 'CALLBACK_WRAPPER_AND_CPP_TYPES', 'SOURCE_TO_BINARY_CORRESPONDENCE']
                if len(items) != 4:
                    fields.append('UNSUPPORTED_METHOD_ENTRY_SHAPE')
                    unclassified.append(row_id)
                if python_name is None:fields.append('NON_LITERAL_METHOD_NAME')
                refs = references(items[1]) if len(items)>1 else []
                if any(not ref['candidates'] for ref in refs):fields.append('CALLBACK_BODY_NOT_SUPPLIED_FOR_SOME_REFERENCES')
                entries.append(dict(id=row_id, name=name, python_name=python_name, callback=callback, flags=flags,
                    documentation=documentation, references=refs, open_fields=fields))
            table_holes = [identity for identity in holes if declarator.start_byte<=occurrences[identity]['start']
                and occurrences[identity]['end']<=declarator.end_byte]
            for hole in table_holes:relation(table_id, hole, 'unexpanded-template-item')
            for item in unclassified:relation(table_id, item, 'unclassified-table-item')
            table_errors = [identity for identity in errors if declarator.start_byte<=occurrences[identity]['start']
                and occurrences[identity]['end']<=declarator.end_byte]
            explicit_enumerated = all(any(occurrences[hole]['start']<=occurrences[item]['start']
                and occurrences[item]['end']<=occurrences[hole]['end'] for hole in table_holes)
                for item in (*unclassified, *table_errors))
            tables.append(dict(id=table_id, name=name_id, entries=table_entries, terminators=terminators,
                holes=table_holes, unclassified=unclassified,
                explicit_entries_enumerated=explicit_enumerated, generated_complete=not(table_holes or unclassified or declarator.has_error)))

    calls = []
    for node in nodes:
        if node.type == 'call_expression':
            identity = select(node, 'call-expression'); callee = expression(node.child_by_field_name('function'), 'callee-expression')
            arguments_node = node.child_by_field_name('arguments')
            arguments = [expression(n, 'call-argument') for n in arguments_node.named_children if n.type != 'comment'] if arguments_node is not None else []
            relation(identity, callee, 'callee')
            for position, argument in enumerate(arguments):relation(identity, argument, 'argument', position)
            owner = next((parent for parent in reversed(ancestors(node, lambda n:n.type=='function_definition'))
                if key(parent) in functions_by_key), None)
            owner_id = functions_by_key[key(owner)]['id'] if owner is not None else None
            if owner_id is not None:relation(functions_by_key[key(owner)]['body'], identity, 'body-call')
            references(node.child_by_field_name('function'))
            calls.append(dict(id=identity, callee=callee, arguments=arguments, owner_function=owner_id,
                preprocessor=preprocessor(node), open_fields=['CPP_CALLEE_TYPES_AND_OVERLOAD', 'MACRO_TEMPLATE_AND_CALL_CONTEXT', 'RUNTIME_EXECUTION_NOT_ESTABLISHED']))
        elif node.type in ('if_statement', 'switch_statement', 'while_statement', 'for_statement', 'return_statement') or node.type.startswith('preproc_'):
            identity = select(node, 'control-source' if not node.type.startswith('preproc_') else 'preprocessor-source')
            for field in ('condition', 'consequence', 'alternative', 'body', 'initializer', 'update'):
                child = node.child_by_field_name(field)
                if child is not None:relation(identity, expression(child, field) if field in ('condition', 'initializer', 'update') else select(child, field), field)
            if node.type.startswith('preproc_'):
                for field in ('name', 'argument', 'path'):
                    child = node.child_by_field_name(field)
                    if child is not None:relation(identity, expression(child, 'preprocessor-'+field), 'preprocessor-'+field)
            if node.type == 'return_statement':
                for position, child in enumerate(n for n in node.named_children if n.type != 'comment'):
                    relation(identity, expression(child, 'return-expression'), 'return-expression', position)

    # Keep only the nearest selected source ancestor, without copying the full
    # CST. Explicit role edges above remain separate original syntax facts.
    for identity, node in tuple(selected_nodes.values()):
        parent = node.parent
        while parent is not None and key(parent) not in selected_nodes:parent = parent.parent
        if parent is not None:relation(selected_nodes[key(parent)][0], identity, 'contains-source-occurrence')
    for hole in holes:
        start, end = occurrences[hole]['start'], occurrences[hole]['end']
        candidates = [r for r in occurrences.values() if r['id']!=hole and r['kind'] not in ('ERROR','template_hole') and r['start']<=start and end<=r['end']]
        owner = min(candidates, key=lambda r:r['end']-r['start'])['id'] if candidates else unit
        relation(owner, hole, 'contains-template-substitution')
    for row in occurrences.values():row['roles'] = sorted(row['roles'])
    need(not any(name.partition('.')[0] == 'torch' for name in sys.modules), 'target import occurred')
    result = dict(occurrences=list(occurrences.values()), relations=list(edges.values()), functions=functions,
        tables=tables, entries=entries, calls=calls, holes=holes, errors=errors, named_nodes=len(nodes),
        open_fields=['CPP_TYPES_OVERLOAD_AND_TEMPLATE_INSTANTIATION', 'PREPROCESSOR_CONFIGURATION',
            'SOURCE_TO_BINARY_CORRESPONDENCE', 'RUNTIME_DESCRIPTOR_BINDING_AND_EXECUTION'],
        tools=dict(python_version=sys.version, versions=versions, files=tools, isolated=bool(sys.flags.isolated),
            no_site=bool(sys.flags.no_site), torch_imported=False, core_limit=resource.getrlimit(resource.RLIMIT_CORE)))
    encoded = json.dumps(result, allow_nan=False).encode()
    need(len(encoded) <= budget['max_output_bytes'], 'C++ source output byte budget')
    sys.stdout.buffer.write(encoded)


if __name__ == '__main__':
    try:main()
    except Exception as error:
        sys.stderr.write(type(error).__name__ + ': ' + str(error)[:1200])
        raise SystemExit(2)
