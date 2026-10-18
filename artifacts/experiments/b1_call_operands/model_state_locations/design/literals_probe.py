import ast
import dis
import json
import math
import platform
import struct

SOURCES = {
    "none": "x = None",
    "bool": "x = True",
    "int": "x = 12345678901234567890",
    "float": "x = 1.5",
    "negative_zero": "x = -0.0",
    "overflow_float": "x = 1e309",
    "complex_constant": "x = 1j",
    "complex_expression": "x = 1 + 2j",
    "bytes": "x = b'\\x00\\xff'",
    "ellipsis": "x = ...",
    "tuple_display": "x = (1, 2)",
    "list_display": "x = [1, 2]",
    "dict_display": "x = {'a': 1}",
    "set_display": "x = {1, 2}",
    "folded_membership_set": "x = item in {1, 2}",
}


def literal_summary(value):
    kind = type(value)
    if value is None:
        return {"type": "NoneType"}
    if value is Ellipsis:
        return {"type": "ellipsis"}
    if kind is bool:
        return {"type": "bool", "value": value}
    if kind is int:
        return {"type": "int", "decimal": str(value), "bit_length": value.bit_length()}
    if kind is float:
        return {"type": "float", "finite": math.isfinite(value),
                "ieee754_be_hex": struct.pack(">d", value).hex()}
    if kind is complex:
        return {"type": "complex", "real_ieee754_be_hex": struct.pack(">d", value.real).hex(),
                "imag_ieee754_be_hex": struct.pack(">d", value.imag).hex()}
    if kind is str:
        return {"type": "str", "codepoints": [ord(ch) for ch in value]}
    if kind is bytes:
        return {"type": "bytes", "hex": value.hex()}
    if kind is tuple:
        return {"type": "tuple", "items": [literal_summary(item) for item in value]}
    if kind is frozenset:
        items = [literal_summary(item) for item in value]
        items.sort(key=lambda item: json.dumps(item, sort_keys=True))
        return {"type": "frozenset", "items": items}
    return {"type": kind.__name__}


def expression_summary(node):
    if isinstance(node, ast.Constant):
        return {"node": "Constant", "value": literal_summary(node.value), "kind": node.kind}
    if isinstance(node, ast.UnaryOp):
        return {"node": type(node).__name__, "operator": type(node.op).__name__,
                "operand": expression_summary(node.operand)}
    if isinstance(node, ast.BinOp):
        return {"node": type(node).__name__, "operator": type(node.op).__name__,
                "left": expression_summary(node.left), "right": expression_summary(node.right)}
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return {"node": type(node).__name__, "elts": [expression_summary(item) for item in node.elts]}
    if isinstance(node, ast.Dict):
        return {"node": "Dict", "keys": [expression_summary(item) for item in node.keys],
                "values": [expression_summary(item) for item in node.values]}
    if isinstance(node, ast.Compare):
        return {"node": "Compare", "left": expression_summary(node.left),
                "comparators": [expression_summary(item) for item in node.comparators]}
    if isinstance(node, ast.Name):
        return {"node": "Name", "id": node.id}
    return {"node": type(node).__name__}


result = {"python": platform.python_version(), "cases": {}}
for name, source in SOURCES.items():
    tree = ast.parse(source, mode="exec")
    rhs = tree.body[0].value
    code = compile(tree, f"<{name}>", "exec", dont_inherit=True, optimize=0)
    result["cases"][name] = {
        "source": source,
        "ast_value": expression_summary(rhs),
        "co_consts": [literal_summary(value) for value in code.co_consts],
        "instructions": [instruction.opname for instruction in dis.get_instructions(code)],
    }
print(json.dumps(result, sort_keys=True, separators=(",", ":")))
