"""Compiler-only distinctions; never run target module or function bodies."""
import ast
import hashlib
import json
from pathlib import Path
import symtable
import sys

from scripts.run_gate import fingerprint


HERE = Path(__file__).resolve().parent
examples = {
    'bare': 'async def body():\n    yield 1\n    return\n',
    'explicit-none': 'async def body():\n    yield 1\n    return None\n',
    'nested-sync-return': 'async def body():\n    yield 1\n    def nested():\n        return None\n    return\n',
    'yield-only-in-nested': 'async def body():\n    def nested():\n        yield 1\n    return None\n',
    'yield-in-nested-default': 'async def body():\n    def nested(x=(yield 1)):\n        return None\n    return None\n',
}
before, sources = fingerprint()
rows = []
for label, text in examples.items():
    tree = ast.parse(text)
    row = {'label': label, 'text': text,
        'returns': tuple({'line': node.lineno, 'expression_present': node.value is not None}
                         for node in ast.walk(tree) if isinstance(node, ast.Return))}
    try:
        table = symtable.symtable(text, '<scar-return-source-probe>', 'exec')
    except SyntaxError as error:
        row['symbol_table'] = {'accepted': False, 'message': error.msg, 'line': error.lineno}
    else:
        row['symbol_table'] = {'accepted': True, 'children': tuple(
            {'name': child.get_name(), 'type': str(child.get_type()),
             'generator_api': tuple(name for name in dir(child)
                                    if 'generat' in name or 'coroutine' in name)}
            for child in table.get_children())}
    try:
        compile(tree, '<scar-return-source-probe>', 'exec')
    except SyntaxError as error:
        row['compiler'] = {'accepted': False, 'message': error.msg, 'line': error.lineno,
                           'offset': error.offset, 'end_line': error.end_lineno,
                           'end_offset': error.end_offset}
    else:
        row['compiler'] = {'accepted': True}
    rows.append(row)
after, final = fingerprint()
assert before == after and sources == final
record = {'source_sha256_before': before, 'source_sha256_after': after, 'sources': sources,
    'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'python': sys.version,
    'target_bodies_executed': 0, 'tests_started': 0, 'observations': rows}
assert not (HERE / 'return-source-probe.json').exists()
(HERE / 'return-source-probe.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps({'source_sha256': before, 'observations': rows}, indent=2))
