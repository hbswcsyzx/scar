"""Independent CPython-only call-star order and failure witnesses."""
import hashlib
import json
from pathlib import Path
import sys

forms = {
    "single_star": "fn(*star('a'), named=kw())",
    "prefix_star": "fn(0, *star('a'), named=kw())",
    "post_position": "fn(*star('a'), 0, named=kw())",
    "multiple_stars": "fn(*star('a'), *star('b'), named=kw())",
}
results = []
for mode in ("normal", "iter_raises", "next_raises", "kw_raises"):
    for name, expression in forms.items():
        events = []
        class Iterator:
            def __init__(self, label):
                self.label, self.position = label, 0
            def __iter__(self):
                return self
            def __next__(self):
                events.append("next:" + self.label)
                if mode == "next_raises":
                    raise ValueError("next witness")
                if self.position:
                    raise StopIteration
                self.position += 1
                return 1
        class Iterable:
            def __init__(self, label):
                self.label = label
            def __iter__(self):
                events.append("iter:" + self.label)
                if mode == "iter_raises":
                    raise ValueError("iter witness")
                return Iterator(self.label)
        def star(label):
            events.append("star_expr:" + label)
            return Iterable(label)
        def kw():
            events.append("kw")
            if mode == "kw_raises":
                raise ValueError("kw witness")
            return 2
        def fn(*args, **kwargs):
            events.append("body")
            return len(args)
        error = None
        try:
            argument_count = eval(compile(expression, "<call-star-order-witness>", "eval"))
        except ValueError as failure:
            error = str(failure)
            argument_count = None
        results.append({"form": name, "mode": mode, "source": expression,
                        "events": list(events), "error": error, "argument_count": argument_count})
out = {"scope": "CPython language witnesses only; no SCAR/Torch/workload import",
       "python": sys.version, "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
       "results": results}
Path(__file__).with_suffix(".json").write_text(json.dumps(out, indent=2) + "\n")
print(json.dumps(out, indent=2))
