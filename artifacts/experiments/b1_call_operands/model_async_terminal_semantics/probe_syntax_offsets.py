"""Observe pinned CPython parser/compiler offsets without target execution."""
import ast
import hashlib
import json
from pathlib import Path
import sys
from scripts.run_gate import fingerprint

before, sources = fingerprint()
observations = []
for label, phase, text in (
    ('compiler-async-return-utf8', 'compile', 'async def body():\n    café = 1; return None\n    yield 1\n'),
    ('compiler-module-return-utf8', 'compile', 'café = 1; return None\n'),
    ('parser-invalid-expression-utf8', 'parse', 'café = ;\n'),
    ('parser-invalid-return-utf8', 'parse', 'def body():\n    café = 1; return )\n'),
):
    try:
        if phase == 'parse':
            ast.parse(text, filename=label)
        else:
            compile(text, label, 'exec', dont_inherit=True, optimize=0)
    except SyntaxError as error:
        line = text.split('\n')[error.lineno - 1]
        row = {'label': label, 'phase': phase, 'text': text, 'line_text': line,
               'message': error.msg, 'lineno': error.lineno, 'offset': error.offset,
               'end_lineno': error.end_lineno, 'end_offset': error.end_offset,
               'line_characters': len(line), 'line_utf8_bytes': len(line.encode('utf-8'))}
        if phase == 'compile':
            tree = ast.parse(text)
            row['returns'] = [{'line': node.lineno, 'column_utf8_bytes': node.col_offset,
                'end_column_utf8_bytes': node.end_col_offset}
                for node in ast.walk(tree) if isinstance(node, ast.Return)]
        observations.append(row)
    else:
        raise AssertionError(label + ' did not report the expected syntax error')
after, final = fingerprint()
assert before == after and sources == final
result = {'python': sys.version, 'python_executable': sys.executable,
    'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'source_sha256_before': before, 'source_sha256_after': after, 'sources': sources,
    'observations': observations, 'target_bodies_executed': 0, 'tests_started': 0,
    'source_runtime_verified': False, 'transformation_authorized': False}
Path(__file__).with_name('syntax-offset-probe.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({key: value for key, value in result.items() if key != 'sources'}, indent=2))
