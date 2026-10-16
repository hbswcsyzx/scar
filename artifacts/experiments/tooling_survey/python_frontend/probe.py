"""Compiler-owned syntax/scope/code evidence; never executes the specimen module."""
import ast
import dis
import hashlib
import importlib.metadata
import json
import pathlib
import shutil
import symtable
import sys
import time
import types

ROOT = pathlib.Path(__file__).resolve().parent
SOURCE = '''import definitely_nonexistent_scar_probe_module
sentinel = open("SCAR_MUST_NOT_CREATE_THIS_FILE", "w")
def outer(x):
    def inner(y=1):
        try:
            return x + y
        finally:
            cleanup()
    return inner
def stream(items):
    for item in items:
        yield item
async def consume(source):
    async for item in source:
        await sink(item)
type Pair[T] = tuple[T, T]
template = t"value={sentinel}"
'''


def code_rows(code):
    rows = [{
        "qualname": code.co_qualname,
        "flags": code.co_flags,
        "freevars": list(code.co_freevars),
        "cellvars": list(code.co_cellvars),
        "instructions": [{"offset": op.offset, "name": op.opname,
                          "line": op.positions.lineno,
                          "column": op.positions.col_offset}
                         for op in dis.get_instructions(code)],
        "exception_table": [dict(entry._asdict())
                            for entry in dis.Bytecode(code).exception_entries],
    }]
    for constant in code.co_consts:
        if isinstance(constant, types.CodeType):
            rows.extend(code_rows(constant))
    return rows


def scope_row(table):
    return {
        "name": table.get_name(), "type": table.get_type().name,
        "line": table.get_lineno(),
        "symbols": [{"name": symbol.get_name(),
                     **{flag[3:]: getattr(symbol, flag)()
                        for flag in ("is_local", "is_free", "is_global",
                                     "is_parameter", "is_imported")}}
                    for symbol in table.get_symbols()],
        "children": [scope_row(child) for child in table.get_children()],
    }


def main():
    start = time.monotonic()
    tree = ast.parse(SOURCE, filename="<scar-frontend-probe>")
    symbols = symtable.symtable(SOURCE, "<scar-frontend-probe>", "exec")
    compiled = compile(SOURCE, "<scar-frontend-probe>", "exec", dont_inherit=True)
    codes = code_rows(compiled)
    packages = {}
    for name in ("torch", "networkx", "libcst", "astroid", "xdsl", "bytecode"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    result = {
        "python": sys.version, "executable": sys.executable,
        "probe_sha256": hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
        "specimen_sha256": hashlib.sha256(SOURCE.encode()).hexdigest(),
        "packages": packages,
        "commands": {name: shutil.which(name) for name in ("nsys", "dot", "codeql", "mlir-opt")},
        "source_types": sorted({type(node).__name__ for node in ast.walk(tree)}),
        "symbols": scope_row(symbols), "codes": codes,
        "checks": {
            "nonexistent_import_not_executed": "definitely_nonexistent_scar_probe_module" not in sys.modules,
            "specimen_file_not_created": not pathlib.Path("SCAR_MUST_NOT_CREATE_THIS_FILE").exists(),
            "closure_cell_from_compiler": any(c["qualname"] == "outer" and "x" in c["cellvars"] for c in codes),
            "inner_freevar_from_compiler": any(c["qualname"] == "outer.<locals>.inner" and "x" in c["freevars"] for c in codes),
            "finally_exception_entries_available": any(c["qualname"] == "outer.<locals>.inner" and c["exception_table"] for c in codes),
            "new_syntax_represented": {"TypeAlias", "TemplateStr", "Interpolation"}.issubset({type(n).__name__ for n in ast.walk(tree)}),
        },
        "elapsed_seconds": time.monotonic() - start,
        "scope": "stdlib syntax/symbol/code capabilities, not an imported SCAR graph or semantic completeness proof",
    }
    (ROOT / "specimen.py.txt").write_text(SOURCE)
    (ROOT / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"checks": result["checks"], "packages": packages,
                      "commands": result["commands"], "elapsed_seconds": result["elapsed_seconds"]}))
    assert all(result["checks"].values())


if __name__ == "__main__":
    main()
