"""Distinguish CPython legality from optional type-comment AST metadata."""
import ast
import hashlib
import json
from pathlib import Path
import sys
from scripts.run_gate import fingerprint

before, sources = fingerprint()
text = 'pass  # type: int\n'
rows = []
for label in ('ordinary_compile', 'ordinary_ast', 'type_comment_ast'):
    try:
        if label == 'ordinary_compile':
            compile(text, 'type-comment', 'exec', dont_inherit=True, optimize=0)
        else:
            ast.parse(text, filename='type-comment', type_comments=label == 'type_comment_ast')
    except SyntaxError as error:
        rows.append({'mode': label, 'accepted': False, 'message': error.msg})
    else:
        rows.append({'mode': label, 'accepted': True})
after, final = fingerprint()
assert before == after and sources == final
result = {'python': sys.version, 'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'sources': sources, 'source_sha256_before': before, 'source_sha256_after': after,
    'text': text, 'observations': rows, 'target_bodies_executed': 0, 'tests_started': 0,
    'transformation_authorized': False}
Path(__file__).with_name('type-comment-probe.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({key: value for key, value in result.items() if key != 'sources'}, indent=2))
