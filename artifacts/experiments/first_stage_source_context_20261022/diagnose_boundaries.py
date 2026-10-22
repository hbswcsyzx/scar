"""Locate exact independent boundary-check disagreements; not an acceptance."""
import ast
import gzip
import json
from pathlib import Path
import tokenize

root = Path(__file__).resolve().parent
current_path, positions = None, {}
found = 0
with gzip.open(root / "result/contexts.jsonl.gz", "rt") as stream:
    for line in stream:
        row = json.loads(line)
        if current_path != row["source_path"]:
            current_path = row["source_path"]
            with tokenize.open(current_path) as source:
                tree = ast.parse(source.read(), filename=current_path, type_comments=True)
            positions = {(type(node).__name__, node.lineno, node.end_lineno,
                          node.col_offset, node.end_col_offset): node
                         for node in ast.walk(tree)
                         if hasattr(node, "lineno") and hasattr(node, "end_lineno")}
        for context in row["contexts"]:
            ref = context["statement_source"]
            if ref is None:
                continue
            matches = [node for key, node in positions.items()
                       if key[1:] == (ref["start_line"], ref["end_line"],
                                     ref["start_column"], ref["end_column"])
                       and isinstance(node, ast.stmt)]
            assert len(matches) == 1
            cursor, parents = matches[0], []
            missing = []
            for step in context["field_path"]:
                parents.append({"kind": type(cursor).__name__, **step})
                if isinstance(cursor, ast.BoolOp) and "BOOLEAN_SHORT_CIRCUIT" not in context["boundaries"]:
                    missing.append(type(cursor).__name__)
                cursor = getattr(cursor, step["field"])
                if step["index"] is not None:
                    cursor = cursor[step["index"]]
            if missing:
                print(json.dumps({"row": row, "ast_path": parents, "missing": missing}))
                found += 1
                if found == 5:
                    raise SystemExit(0)
