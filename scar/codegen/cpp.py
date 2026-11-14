"""C++20 scalar-DAG lowering with an ABI-1 ctypes boundary.

Only exact native float64, rank-two ndarrays enter native execution. Array
operands must have identical shapes; scalar constants may broadcast. Slices
are unit-step views of inputs or other slices. Other cases raise GuardFailure
at invocation or ValueError at build, allowing the compiler caller to retain
the original function as its explicit compatibility path.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile

from scar.compiler.model import (
    ExecutionPlan, PROFILE, document, plan_from_dict, read_plan, write_plan,
)

ABI_VERSION = 1
COMPILER_OPTIONS = (
    "-std=c++20", "-O3", "-shared", "-fPIC", "-fvisibility=hidden",
    "-fno-fast-math", "-ffp-contract=off", "-frounding-math", "-ftrapping-math",
)
_DIRECTORY = Path(__file__).resolve().parent
_BINARY_OPS = {"add": "+", "sub": "-", "mul": "*", "div": "/"}
_ARITY = {"input": 0, "const": 0, "slice": 1, "neg": 1,
          **dict.fromkeys(_BINARY_OPS, 2)}


class GuardFailure(RuntimeError):
    """Native execution declined; invoke the original function once."""


class _Array(ctypes.Structure):
    _fields_ = [("data", ctypes.c_void_p), ("rank", ctypes.c_int64),
                ("shape", ctypes.c_int64 * 2), ("strides", ctypes.c_int64 * 2),
                ("lower_bound", ctypes.c_size_t), ("upper_bound", ctypes.c_size_t)]


_Run = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(_Array), ctypes.c_uint64,
                       ctypes.POINTER(_Array))


class _Table(ctypes.Structure):
    _fields_ = [("abi_version", ctypes.c_uint32), ("struct_size", ctypes.c_uint32),
                ("input_count", ctypes.c_uint64), ("run", _Run),
                ("plan_sha256", ctypes.c_char_p)]


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _plan_digest(plan: ExecutionPlan) -> str:
    return _digest(json.dumps(document(plan), sort_keys=True, allow_nan=False,
                              separators=(",", ":")).encode())


def _supported(plan: ExecutionPlan) -> dict[str, bool]:
    # Import at call time so the compiler/validation module remains the owner
    # of shared structural policy, including when backends load separately.
    from scar.compiler.validation import validate_plan
    validate_plan(plan)
    if (plan.schema_version != 1 or plan.operator_abi_version != ABI_VERSION or
            plan.profile != PROFILE or plan.device != "cpu" or
            plan.buffer_policy != "fresh_output"):
        raise ValueError("C++ backend requires CPU execution-plan/ABI version 1 and fresh output")
    if plan.region.frontiers:
        raise ValueError("C++ backend cannot cross unresolved execution frontiers")
    extents = [axis.extent for axis in plan.schedule]
    if sorted(extents) != ["output.shape[0]", "output.shape[1]"]:
        raise ValueError("C++ backend requires exactly the two output loop axes")
    parameters = plan.region.parameters
    if len(parameters) != len(set(parameters)):
        raise ValueError("duplicate region parameters")
    scalar: dict[str, bool] = {}
    nodes = {}
    for node in plan.region.nodes:
        if node.id in nodes or node.op not in _ARITY or len(node.inputs) != _ARITY[node.op]:
            raise ValueError(f"unsupported or malformed expression {node.id!r}")
        allowed = {"input": {"name", "index"}, "const": {"value"}, "slice": {"bounds"}}.get(node.op, set())
        if not isinstance(node.attrs, dict) or set(node.attrs) - allowed:
            raise ValueError(f"unsupported expression attributes for {node.op!r}")
        if any(source not in nodes for source in node.inputs):
            raise ValueError("expression DAG must be in topological order")
        if node.op == "input":
            if node.attrs.get("name") not in parameters:
                raise ValueError("input expression must name a region parameter")
            index = node.attrs.get("index", parameters.index(node.attrs["name"]))
            if type(index) is not int or index != parameters.index(node.attrs["name"]):
                raise ValueError("input ordinal does not match region parameters")
            scalar[node.id] = False
        elif node.op == "const":
            value = node.attrs.get("value")
            if (type(value) not in (int, float) or
                    (type(value) is int and abs(value) > 2**53) or not math.isfinite(value)):
                raise ValueError("constants must be finite, exactly representable float64 scalars")
            scalar[node.id] = True
        elif node.op == "slice":
            if nodes[node.inputs[0]].op not in ("input", "slice"):
                raise ValueError("C++ slices must refer to an input or another slice")
            bounds = node.attrs.get("bounds")
            if (not isinstance(bounds, (list, tuple)) or len(bounds) != 2 or
                    any(not isinstance(pair, (list, tuple)) or len(pair) != 2 or
                        any(v is not None and type(v) is not int for v in pair)
                        for pair in bounds)):
                raise ValueError("C++ slices require two [start, stop] unit-step bounds")
            scalar[node.id] = False
        else:
            scalar[node.id] = all(scalar[source] for source in node.inputs)
            if scalar[node.id]:
                raise ValueError("scalar-only operations must be folded before C++ lowering")
        nodes[node.id] = node
    if plan.region.output not in nodes or scalar[plan.region.output]:
        raise ValueError("C++ region output must be a rank-two array")
    live = set()
    pending = [plan.region.output]
    while pending:
        node_id = pending.pop()
        if node_id not in live:
            live.add(node_id)
            pending.extend(nodes[node_id].inputs)
    if any(node.id not in live and node.op in (*_BINARY_OPS, "neg")
           for node in plan.region.nodes):
        raise ValueError("unused arithmetic could change NumPy floating-point errors")
    budget = plan.cost.get("memory_budget_bytes")
    if budget is not None and (type(budget) is not int or budget < 0):
        raise ValueError("memory_budget_bytes must be a nonnegative integer")
    return scalar


def _bound(value, extent: str, *, stop: bool = False) -> str:
    if value is None:
        return extent if stop else "0"
    # Huge Python slice integers clamp to the same boundary as these limits.
    value = min(max(value, -(2**63)), 2**63 - 1)
    literal = "(-9223372036854775807LL - 1)" if value == -(2**63) else f"{value}LL"
    return f"slice_bound({literal}, {extent})"


def _source(plan: ExecutionPlan, scalar: dict[str, bool]) -> str:
    names = {node.id: f"s{i}" for i, node in enumerate(plan.region.nodes)}
    shape_lines = []
    views = {}
    scalar_values = {}
    for node in plan.region.nodes:
        name = names[node.id]
        if node.op == "input":
            index = plan.region.parameters.index(node.attrs["name"])
            shape_lines.append(f"    const Shape {name}{{false, inputs[{index}].shape[0], inputs[{index}].shape[1]}};")
            views[node.id] = (index, "0", "0")
        elif node.op == "const":
            shape_lines.append(f"    const Shape {name}{{true, 0, 0}};")
            scalar_values[node.id] = float(node.attrs["value"]).hex()
        elif node.op == "slice":
            parent = names[node.inputs[0]]
            starts = []
            lengths = []
            for axis, dim in enumerate(("rows", "cols")):
                start, stop = node.attrs["bounds"][axis]
                begin, end = f"{name}_begin{axis}", f"{name}_end{axis}"
                shape_lines.append(f"    const int64_t {begin} = {_bound(start, f'{parent}.{dim}')};")
                shape_lines.append(f"    const int64_t {end} = {_bound(stop, f'{parent}.{dim}', stop=True)};")
                starts.append(begin)
                lengths.append(f"({end} > {begin} ? {end} - {begin} : 0)")
            shape_lines.append(f"    const Shape {name}{{false, {lengths[0]}, {lengths[1]}}};")
            index, row, col = views[node.inputs[0]]
            views[node.id] = (index, f"({row} + {starts[0]})", f"({col} + {starts[1]})")
        else:
            sources = [names[source] for source in node.inputs]
            if len(sources) == 2 and not any(scalar[source] for source in node.inputs):
                shape_lines.append(f"    if (!same_shape({sources[0]}, {sources[1]})) return SCAR_SHAPE_GUARD_V1;")
            array_source = next(source for source in node.inputs if not scalar[source])
            shape_lines.append(f"    const Shape {name} = {names[array_source]};")
    # Resolve input views only at actual uses, so their unsliced coordinates
    # are never read speculatively. A scalar local preserves each DAG operation.
    needed = {plan.region.output}
    for node in plan.region.nodes:
        if node.op in (*_BINARY_OPS, "neg"):
            needed.add(node.id)
            needed.update(node.inputs)
    # valid_array has proved every input's full reachable offset interval in
    # 128-bit arithmetic. Derive each nonempty view once, then perform only
    # bounded ptrdiff_t row/column arithmetic in the hot loops.
    loads = [node for node in plan.region.nodes
             if node.id in needed and node.op in ("input", "slice")]
    prelude = ["    if (output->shape[0] != 0 && output->shape[1] != 0) {"]
    for index in sorted({views[node.id][0] for node in loads}):
        prelude.extend((
            f"        const ptrdiff_t row_stride{index} = static_cast<ptrdiff_t>(inputs[{index}].strides[0]);",
            f"        const ptrdiff_t col_stride{index} = static_cast<ptrdiff_t>(inputs[{index}].strides[1]);",
        ))
    row_setup = []
    for node in loads:
        index, row, col = views[node.id]
        name = names[node.id]
        prelude.append(
            f"        const auto view_{name} = static_cast<const unsigned char *>(inputs[{index}].data) + "
            f"static_cast<ptrdiff_t>(__int128({row}) * row_stride{index} + __int128({col}) * col_stride{index});")
        row_setup.append(f"            const auto row_{name} = view_{name} + row * row_stride{index};")
    prelude.append("        double *__restrict__ output_data = static_cast<double *>(output->data);")
    row_setup.append("            double *__restrict__ output_row = output_data + row * output->shape[1];")
    emitted = []
    value_names = {}
    for node in plan.region.nodes:
        if node.id not in needed:
            continue
        if node.op in ("input", "slice"):
            index, _, _ = views[node.id]
            expression = f"read_value(row_{names[node.id]} + col * col_stride{index}, nonfinite_input)"
        elif node.op == "const":
            expression = scalar_values[node.id]
        elif node.op == "neg":
            expression = f"-{value_names[node.inputs[0]]}"
        else:
            left, right = (value_names[source] for source in node.inputs)
            expression = f"{left} {_BINARY_OPS[node.op]} {right}"
        name = f"v{len(value_names)}"
        value_names[node.id] = name
        emitted.append(f"                const double {name} = {expression};")
    output_value = value_names[plan.region.output]
    emitted.append(f"                output_row[col] = {output_value};")
    row_loop = ["        for (int64_t row = 0; row < output->shape[0]; ++row) {",
                *row_setup,
                "            for (int64_t col = 0; col < output->shape[1]; ++col) {",
                *emitted, "            }", "        }"]
    if plan.cpu_threads == 1:
        loops = [*prelude, *row_loop, "    }"]
    else:
        # OpenMP workers may retain an environment from an earlier invocation.
        # Save each worker's state, mask traps and clear flags, then explicitly
        # copy the caller's rounding mode. No array computation happens in a
        # worker whose environment could not be prepared safely.
        worker_start = [
            "        const int caller_rounding = std::fegetround();",
            f"        #pragma omp parallel num_threads({plan.cpu_threads}) reduction(|:worker_guard)",
            "        {",
            "            fenv_t worker_saved, worker_held;",
            "            const bool worker_saved_ok = std::fegetenv(&worker_saved) == 0;",
            "            const bool worker_held_ok = worker_saved_ok && std::feholdexcept(&worker_held) == 0;",
            "            const bool worker_ready = worker_held_ok && caller_rounding >= 0 &&",
            "                                      std::fesetround(caller_rounding) == 0;",
            "            uint32_t nonfinite_input = 0;",
            "            #pragma omp for schedule(static)",
        ]
        parallel_rows = ["    " + line for line in row_loop]
        parallel_rows.insert(1, "                if (!worker_ready) continue;")
        worker_end = [
            "            const int worker_raised = worker_held_ok ?",
            "                std::fetestexcept(FE_DIVBYZERO | FE_INVALID | FE_OVERFLOW | FE_UNDERFLOW) : 0;",
            "            const int worker_restored = worker_saved_ok ? std::fesetenv(&worker_saved) : -1;",
            "            worker_guard |= static_cast<uint32_t>(",
            "                !worker_ready || worker_raised || worker_restored || nonfinite_input);",
            "        }",
        ]
        loops = [*prelude, *worker_start, *parallel_rows, *worker_end, "    }"]
    template = (_DIRECTORY / "kernel_v1.cpp.in").read_text()
    for key, value in {
        "INPUT_COUNT": str(len(plan.region.parameters)),
        "SHAPES": "\n".join(shape_lines),
        "OUTPUT_SHAPE": names[plan.region.output],
        "LOOPS": "\n".join(loops), "PLAN_SHA256": _plan_digest(plan),
        "OPENMP_INCLUDE": "#include <omp.h>" if plan.cpu_threads > 1 else "",
    }.items():
        template = template.replace(f"@{key}@", value)
    return template


def _descriptor(array) -> _Array:
    import numpy as np
    if type(array) is not np.ndarray:
        raise GuardFailure("C++ input requires an exact numpy.ndarray")
    if array.ndim != 2 or array.dtype != np.dtype("float64") or not array.dtype.isnative:
        raise GuardFailure("C++ input requires native float64 rank-two arrays")
    if not array.flags.aligned or any(stride % 8 for stride in array.strides):
        raise GuardFailure("C++ input requires float64-aligned data and byte strides")
    owner = array
    seen = set()
    while owner.base is not None:
        if id(owner) in seen or type(owner.base) is not np.ndarray:
            raise GuardFailure("C++ array backing allocation cannot be verified")
        seen.add(id(owner))
        owner = owner.base
    if not owner.flags.owndata or not (owner.flags.c_contiguous or owner.flags.f_contiguous):
        raise GuardFailure("C++ array requires a verifiable contiguous owning allocation")
    lower = int(owner.ctypes.data)
    upper = lower + owner.nbytes
    pointer = int(array.ctypes.data)
    if array.size:
        offsets = [(extent - 1) * stride for extent, stride in zip(array.shape, array.strides)]
        low = pointer + sum(min(0, offset) for offset in offsets)
        high = pointer + sum(max(0, offset) for offset in offsets) + 8
        if low < lower or high > upper:
            raise GuardFailure("C++ array strides exceed its backing allocation")
    return _Array(pointer, 2, (ctypes.c_int64 * 2)(*array.shape),
                  (ctypes.c_int64 * 2)(*array.strides), lower, upper)


def _output_shape(plan: ExecutionPlan, arrays) -> tuple[int, int]:
    shapes = {}
    for node in plan.region.nodes:
        if node.op == "input":
            shapes[node.id] = arrays[plan.region.parameters.index(node.attrs["name"])].shape
        elif node.op == "const":
            shapes[node.id] = None
        elif node.op == "slice":
            parent = shapes[node.inputs[0]]
            shapes[node.id] = tuple(max(0, stop - start) for start, stop, _ in
                                    (slice(*bounds).indices(extent) for bounds, extent in
                                     zip(node.attrs["bounds"], parent)))
        else:
            sources = [shapes[source] for source in node.inputs if shapes[source] is not None]
            if any(shape != sources[0] for shape in sources[1:]):
                raise GuardFailure("C++ array operands require identical shapes")
            shapes[node.id] = sources[0]
    return shapes[plan.region.output]


@dataclass
class CppArtifact:
    plan: ExecutionPlan
    directory: Path
    _metadata: dict
    _library: object
    _run: object

    @property
    def source_path(self) -> Path:
        return self.directory / self._metadata["files"]["source"]

    @property
    def library_path(self) -> Path:
        return self.directory / self._metadata["files"]["library"]

    @property
    def plan_path(self) -> Path:
        return self.directory / self._metadata["files"]["plan"]

    @property
    def abi_header_path(self) -> Path:
        return self.directory / self._metadata["files"]["abi_header"]

    @property
    def metadata_path(self) -> Path:
        return self.directory / "artifact.json"

    @property
    def compiler_options(self) -> tuple[str, ...]:
        return tuple(self._metadata["compiler_options"])

    @property
    def report(self) -> dict:
        return {**json.loads(json.dumps(self._metadata)), "artifact_directory": str(self.directory),
                "source_path": str(self.source_path), "library_path": str(self.library_path),
                "plan_path": str(self.plan_path), "metadata_path": str(self.metadata_path),
                "abi_header_path": str(self.abi_header_path)}

    def run(self, *arrays):
        import numpy as np
        if len(arrays) != len(self.plan.region.parameters):
            raise GuardFailure("C++ input count does not match region parameters")
        descriptors = [_descriptor(array) for array in arrays]
        shape = _output_shape(self.plan, arrays)
        output_bytes = shape[0] * shape[1] * 8
        budget = self.plan.cost.get("memory_budget_bytes")
        if output_bytes > sys.maxsize or (budget is not None and output_bytes > budget):
            raise GuardFailure("C++ fresh output exceeds memory_budget_bytes or platform size")
        try:
            output = np.empty(shape, dtype=np.float64)
        except (MemoryError, ValueError, OverflowError) as exc:
            raise GuardFailure("C++ fresh output cannot be allocated") from exc
        output_descriptor = _descriptor(output)
        inputs = (_Array * len(descriptors))(*descriptors)
        status = self._run(inputs, len(descriptors), ctypes.byref(output_descriptor))
        if status:
            reasons = {1: "native pointer/rank/bounds guard", 2: "native shape guard",
                       3: "native floating-point error or non-finite input; run original NumPy operation"}
            raise GuardFailure(reasons.get(status, f"unknown native guard status {status}"))
        return output


def build(plan: ExecutionPlan, out: Path) -> CppArtifact:
    """Validate, emit and compile a persistent host shared-library artifact."""
    # Freeze the caller's mutable nested attrs/proof dictionaries via its wire format.
    plan = plan_from_dict(document(plan))
    scalar = _supported(plan)
    source = _source(plan, scalar)
    compiler_options = (*COMPILER_OPTIONS, *(("-fopenmp",) if plan.cpu_threads > 1 else ()))
    compiler = shlex.split(os.environ.get("CXX", "g++"))
    if not compiler or shutil.which(compiler[0]) is None:
        raise RuntimeError("C++20 host compiler is unavailable (CXX or g++)")
    directory = Path(out).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    source_path = directory / "kernel.cpp"
    header_path = directory / "scar_abi_v1.h"
    plan_path = directory / "plan.json"
    header = (_DIRECTORY / "scar_abi_v1.h").read_bytes()
    source_path.write_text(source)
    header_path.write_bytes(header)
    write_plan(plan, plan_path)
    build_id = _digest(source.encode() + header + repr(compiler_options).encode())
    library_path = directory / f"kernel_{build_id[:20]}.so"
    fd, temporary = tempfile.mkstemp(prefix=".kernel-", suffix=".so", dir=directory)
    os.close(fd)
    command = [*compiler, *compiler_options, str(source_path), "-o", temporary, "-lm"]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode:
            raise RuntimeError(f"C++20 compilation failed:\n{result.stderr.strip()}")
        os.replace(temporary, library_path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    version = subprocess.run([*compiler, "--version"], capture_output=True, text=True,
                             check=False).stdout.splitlines()
    metadata = {
        "schema": "scar.native-artifact", "schema_version": 1, "backend": "cpp",
        "operator_abi_version": ABI_VERSION, "execution_plan_schema_version": 1,
        "cxx_standard": 20, "python_boundary": "ctypes", "build_id": build_id,
        "host_loop_lowering": "guarded_view_and_row_pointer_hoisting",
        "cpu_threads": plan.cpu_threads,
        "parallel_runtime": "openmp" if plan.cpu_threads > 1 else "serial",
        "floating_environment": "save_restore_per_worker_and_caller_rounding" if plan.cpu_threads > 1 else "save_restore_caller",
        "plan_sha256": _plan_digest(plan), "compiler": compiler,
        "compiler_version": version[0] if version else "unknown",
        "compiler_options": list(compiler_options),
        "compiler_command": [*compiler, *compiler_options, str(source_path),
                             "-o", str(library_path), "-lm"],
        "files": {"plan": plan_path.name, "source": source_path.name,
                  "abi_header": header_path.name, "library": library_path.name},
        "sha256": {"source": _digest(source.encode()), "abi_header": _digest(header),
                   "library": _digest(library_path.read_bytes())},
        "limitations": ["exact native float64 rank-two NumPy arrays",
                        "aligned data with byte strides divisible by eight",
                        "equal array shapes; scalar constants may broadcast",
                        "unit-step slices of input views only",
                        "verifiable ndarray-owned backing allocations",
                        "non-finite loaded inputs require original-function fallback",
                        "floating-point exceptions require original-function fallback"],
    }
    (directory / "artifact.json").write_text(json.dumps(metadata, indent=2, allow_nan=False) + "\n")
    return load(directory)


def load(out: Path) -> CppArtifact:
    """Load an existing artifact, checking its plan, file digests and ABI table."""
    path = Path(out).resolve()
    directory = path if path.is_dir() else path.parent
    metadata = json.loads((directory / "artifact.json").read_text())
    if (metadata.get("schema") != "scar.native-artifact" or metadata.get("schema_version") != 1 or
            metadata.get("backend") != "cpp" or metadata.get("operator_abi_version") != ABI_VERSION):
        raise ValueError("unsupported C++ artifact schema or ABI")
    for filename in metadata["files"].values():
        if Path(filename).name != filename:
            raise ValueError("artifact files must be local basenames")
    plan = read_plan(directory / metadata["files"]["plan"])
    _supported(plan)
    if _plan_digest(plan) != metadata["plan_sha256"]:
        raise ValueError("artifact plan digest mismatch")
    for kind, expected in metadata["sha256"].items():
        if _digest((directory / metadata["files"][kind]).read_bytes()) != expected:
            raise ValueError(f"artifact {kind} digest mismatch")
    library = ctypes.CDLL(str(directory / metadata["files"]["library"]))
    getter = library.scar_get_operator_table_v1
    getter.argtypes = []
    getter.restype = ctypes.POINTER(_Table)
    pointer = getter()
    if not pointer:
        raise ValueError("native operator table is null")
    table = pointer.contents
    if (table.abi_version != ABI_VERSION or table.struct_size < ctypes.sizeof(_Table) or
            table.input_count != len(plan.region.parameters) or not table.run or
            table.plan_sha256 != metadata["plan_sha256"].encode()):
        raise ValueError("native operator table does not match artifact plan/ABI")
    return CppArtifact(plan, directory, metadata, library, table.run)
