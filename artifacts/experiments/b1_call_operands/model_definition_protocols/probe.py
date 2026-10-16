"""Small language probes; no SCAR or LeWM code is imported or executed."""
import ast
import asyncio
import json
import platform
import sys
import types

out = {"python": sys.version, "implementation": platform.python_implementation(), "events": {}}
def capture(name, events):
    out["events"][name] = list(events)

events = []
def mark(label, value=None):
    events.append(label)
    return value
def decorator(label):
    events.append("decorator-eval:" + label)
    def apply(value):
        events.append("decorator-apply:" + label)
        return value
    return apply

@decorator("outer")
@decorator("inner")
def f(a=mark("default-a", []), b=mark("default-b", object())) -> mark("return-annotation", int):
    events.append("function-body")
capture("function-definition", events)
events.clear()
_ = f()
capture("function-call", events)
events.clear()
_ = f.__annotations__
capture("function-annotations-first", events)
events.clear()
_ = f.__annotations__
capture("function-annotations-second", events)

# Type parameter bounds/defaults and function annotations have separate lazy entrypoints.
events = []
def generic[T: mark("type-bound", int), U=mark("type-default", str)](x: mark("parameter-annotation", int)) -> mark("return-annotation", str):
    pass
capture("generic-definition", events)
events.clear()
_ = generic.__type_params__
capture("generic-type-params", events)
events.clear()
_ = generic.__type_params__[0].__bound__
capture("typevar-bound-first", events)
events.clear()
_ = generic.__type_params__[0].__bound__
capture("typevar-bound-second", events)
events.clear()
_ = generic.__type_params__[1].__default__
capture("typevar-default", events)
events.clear()
_ = generic.__annotations__
capture("generic-annotations", events)

events = []
type Alias[V: mark("alias-bound", int)] = mark("alias-value", list[V])
capture("type-alias-definition", events)
events.clear()
_ = Alias.__type_params__
capture("alias-type-params", events)
events.clear()
_ = Alias.__value__
capture("alias-value-first", events)
events.clear()
_ = Alias.__value__
capture("alias-value-second", events)
events.clear()
_ = Alias.__type_params__[0].__bound__
capture("alias-bound", events)

# Module/class annotations in an actual namespace; attribute-target annotation is not evaluated.
events = []
def ann(label):
    events.append(label)
    return int
module = types.ModuleType("probe_module")
ns = vars(module)
ns["ann"] = ann
ns["z"] = types.SimpleNamespace()
exec("x: ann('module-name')\ny: ann('module-assigned') = 1\nz.attr: ann('module-attribute')", ns, ns)
capture("module-after-exec", events)
events.clear()
module_annotations = module.__annotations__
capture("module-annotations-first", events)
events.clear()
_ = module.__annotations__
capture("module-annotations-second", events)
events = []
obj = types.SimpleNamespace()
class Annotated:
    x: ann("class-name")
    y: ann("class-assigned") = 1
    obj.attr: ann("class-attribute")
capture("class-annotation-body", events)
events.clear()
_ = Annotated.__annotations__
capture("class-annotations-access", events)
events = []
def local_annotation():
    x: ann("local-annotation")
    return locals()
local_values = local_annotation()
capture("function-local-annotation", events)
out["function_local_names_after_annotation"] = sorted(local_values)

# Class construction and decorator protocol order.
events = []
def class_decorator(label):
    events.append("class-decorator-eval:" + label)
    def apply(cls):
        events.append("class-decorator-apply:" + label)
        return cls
    return apply
class Base:
    def __init_subclass__(cls, **kwargs):
        events.append("base-init-subclass")
        super().__init_subclass__()
class Meta(type):
    @classmethod
    def __prepare__(mcls, name, bases, **kwargs):
        events.append("meta-prepare")
        return {}
    def __new__(mcls, name, bases, namespace, **kwargs):
        events.append("meta-new-before-type")
        value = super().__new__(mcls, name, bases, namespace, **kwargs)
        events.append("meta-new-after-type")
        return value
    def __init__(cls, name, bases, namespace, **kwargs):
        events.append("meta-init")
        super().__init__(name, bases, namespace)
class Descriptor:
    def __set_name__(self, owner, name):
        events.append("descriptor-set-name")
def base_expr():
    events.append("base-expression")
    return Base
def meta_expr():
    events.append("metaclass-expression")
    return Meta
def class_kw():
    events.append("class-keyword-expression")
    return 7
@class_decorator("outer")
@class_decorator("inner")
class Made(base_expr(), metaclass=meta_expr(), marker=class_kw()):
    events.append("class-body")
    field = Descriptor()
capture("class-definition", events)

# Call evaluation / expansion order and pre-body argument-binding failure.
events = []
class MappingProbe:
    def keys(self):
        events.append("mapping-keys")
        return ["from_mapping"]
    def __getitem__(self, key):
        events.append("mapping-getitem")
        return 9
def target(*args, **kwargs):
    events.append("target-body")
    return args, kwargs
def callable_expr():
    events.append("callable-expression")
    return target
def star_expr():
    events.append("star-expression")
    return [mark("star-item", 2)]
def keyword_expr():
    events.append("keyword-expression")
    return 1
def mapping_expr():
    events.append("mapping-expression")
    return MappingProbe()
callable_expr()(named=keyword_expr(), *star_expr(), **mapping_expr())
capture("call-order", events)
events = []
def body_guard(a):
    events.append("body-entered")
try:
    body_guard(1, 2)
except TypeError:
    events.append("binding-TypeError")
capture("call-binding-error", events)

# RHS/target sequencing and augmented target single evaluation.
events = []
class ItemStore:
    def __setitem__(self, key, value):
        events.append("setitem")
def owner():
    events.append("owner")
    return ItemStore()
def key():
    events.append("key")
    return "k"
def rhs():
    events.append("rhs")
    return 3
owner()[key()] = rhs()
capture("subscript-assignment", events)
events = []
class AddProbe:
    def __iadd__(self, other):
        events.append("inplace-add")
        return self
class Attr:
    def __getattribute__(self, name):
        if name == "item":
            events.append("attribute-read")
        return object.__getattribute__(self, name)
    def __setattr__(self, name, value):
        if name == "item":
            events.append("attribute-write")
        object.__setattr__(self, name, value)
obj = Attr()
obj.item = AddProbe()
events.clear()
def attr_owner():
    events.append("attribute-primary")
    return obj
attr_owner().item += rhs()
capture("augmented-assignment", events)

# Function and generator bodies start at different protocol points.
events = []
async def async_body():
    events.append("async-body")
    return 1
def generator_body():
    events.append("generator-body")
    yield 1
coroutine = async_body()
events.append("after-async-call")
generator = generator_body()
events.append("after-generator-call")
next(generator)
events.append("after-generator-next")
asyncio.run(coroutine)
capture("async-and-generator", events)

# f-string conversion/formatting versus t-string retained interpolation.
events = []
class Formattable:
    def __repr__(self):
        events.append("repr")
        return "VALUE"
    def __format__(self, spec):
        events.append("format:" + spec)
        return "FORMATTED"
def formatted_value():
    events.append("value-expression")
    return Formattable()
def width():
    events.append("format-spec-expression")
    return 4
formatted = f"{formatted_value()!r:{width()}}"
capture("f-string", events)
events.clear()
template = t"{formatted_value()!r:{width()}}"
capture("t-string-construction", events)
interpolation = template.interpolations[0]
out["t_string"] = {
    "type": type(template).__name__,
    "interpolation_type": type(interpolation).__name__,
    "expression": interpolation.expression,
    "conversion": interpolation.conversion,
    "format_spec": interpolation.format_spec,
    "value_type": type(interpolation.value).__name__,
    "strings": template.strings,
}

# Root AST shapes are interpreter facts, not evaluation order.
classes = ["Module", "Interactive", "Expression", "FunctionType", "FunctionDef", "AsyncFunctionDef", "Lambda", "arguments", "arg", "ClassDef", "TypeAlias", "TypeVar", "ParamSpec", "TypeVarTuple", "Import", "ImportFrom", "alias", "Name", "Attribute", "Subscript", "Slice", "Assign", "AnnAssign", "AugAssign", "Delete", "NamedExpr", "Call", "keyword", "BinOp", "UnaryOp", "Dict", "Set", "List", "Tuple", "Constant", "FormattedValue", "JoinedStr", "Interpolation", "TemplateStr"]
out["ast_fields"] = {name: list(getattr(ast, name)._fields) for name in classes if hasattr(ast, name)}
out["ast_modes"] = {}
for mode, source in [("exec", "x=1"), ("single", "x=1"), ("eval", "x+1"), ("func_type", "(int, str) -> bool")]:
    root = ast.parse(source, mode=mode)
    out["ast_modes"][mode] = type(root).__name__
print(json.dumps(out, indent=2, sort_keys=True, default=str))
