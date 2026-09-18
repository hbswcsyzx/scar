"""Low overhead process-local recorder used by the injector."""
from __future__ import annotations

import json
import hashlib
import functools
import os
import platform
import struct
import sys
import threading
import time
import types
from pathlib import Path
from typing import Any

from scar.ir import (CodeID, Effect, Event, ObjectEntity, tensor_entity, Knowledge,
                     default_registry)


def _flatten(value):
    if isinstance(value, (tuple, list)):
        for item in value:
            yield from _flatten(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _flatten(item)
    else:
        yield value


_MODULE_INTERNAL_STATE = frozenset({
    "training", "_parameters", "_buffers", "_non_persistent_buffers_set",
    "_backward_pre_hooks", "_backward_hooks", "_is_full_backward_hook",
    "_forward_hooks", "_forward_hooks_with_kwargs", "_forward_hooks_always_called",
    "_forward_pre_hooks", "_forward_pre_hooks_with_kwargs", "_state_dict_hooks",
    "_state_dict_pre_hooks", "_load_state_dict_pre_hooks",
    "_load_state_dict_post_hooks", "_modules", "_compiled_call_impl",
})

_PYTHON_CALLABLE_TYPES = (
    types.FunctionType,
    types.BuiltinFunctionType,
    types.MethodType,
    types.BuiltinMethodType,
    functools.partial,
)

_C_IO_NAMES = frozenset({
    "open", "print", "read", "readline", "readlines", "write", "writelines",
    "flush", "close", "remove", "unlink", "rename", "replace", "mkdir", "makedirs",
    "system", "popen", "putenv", "getenv",
})
_C_ORDER_NAMES = frozenset({
    "sleep", "acquire", "release", "wait", "notify", "join", "flush",
})
_C_STATE_NAMES = frozenset({
    "setattr", "setdefault", "update", "append", "extend", "insert", "pop", "clear",
})


class TraceSession:
    def __init__(self, out: str | Path):
        self.out = Path(out)
        self.out.mkdir(parents=True, exist_ok=True)
        # Several ordinary PyTorch workloads spawn workers.  Append-only JSONL
        # records keep those processes from truncating each other's trace;
        # each process gets a separate metadata document below.
        self.process_id = os.getpid()
        self.package_root = str(Path(__file__).resolve().parents[1]) + os.sep
        self.events_fp = (self.out / "events.jsonl").open("a", buffering=1)
        self.entities_fp = (self.out / "entities.jsonl").open("a", buffering=1)
        self.meta_path = self.out / f"metadata.{self.process_id}.json"
        self.invocation = 0
        self.event_count = 0
        self.entity_ids: set[str] = set()
        self.call_stacks: dict[int, list[tuple[int, int, int, CodeID]]] = {}
        self.pending_exceptions: dict[tuple[int, int], str] = {}
        # Optional line tracing keeps a frame-local bytecode offset. A
        # backwards jump is runtime evidence of a loop back-edge; it is not
        # confused with source order or with a generic branch.
        self.line_offsets: dict[int, int] = {}
        self.loop_iterations: dict[tuple[int, int], int] = {}
        self.active_loops: dict[int, tuple[int, int]] = {}
        # Host transfer events are retained only as small references until
        # Kineto activities are available at shutdown. This lets the CUDA
        # importer attempt a conservative resource/state join without
        # changing the append-only event format.
        self.transfer_records: list[tuple[int, Event]] = []
        # These are SCAR-owned epochs.  They intentionally do not consult
        # Tensor._version, which misses writes through NumPy aliases and is
        # not a universal contract for inference tensors.
        # The backend and observer share this process-local registry so an
        # observed in-place write invalidates a cache key immediately.
        self.versions = default_registry()
        self.start_ns = time.perf_counter_ns()
        self.meta = {
            "python": sys.version,
            "platform": platform.platform(),
            "pid": os.getpid(),
            "started_ns": self.start_ns,
            "evidence": "Observed",
        }
        self.resource_sampler = None
        if os.environ.get("SCAR_RESOURCE_SAMPLER", "0") == "1":
            from .resources import ResourceSampler
            self.resource_sampler = ResourceSampler(
                self.out,
                interval_s=float(os.environ.get("SCAR_RESOURCE_INTERVAL", "0.1")),
            )
            self.resource_sampler.start()
        self.meta_path.write_text(json.dumps(self.meta, indent=2, default=str))

    def _ensure_process_context(self) -> None:
        """Switch inherited state to a child process namespace after ``fork``.

        A fork duplicates Python objects and open append-only descriptors. The
        child may therefore continue using this Session, but identities and
        invocation/index counters must not claim to belong to the parent.
        ``multiprocessing`` workers that start a fresh interpreter create a
        normal new Session and do not enter this branch.
        """
        current_pid = os.getpid()
        if current_pid == self.process_id:
            return
        parent_pid = self.process_id
        self.process_id = current_pid
        self.meta_path = self.out / f"metadata.{current_pid}.json"
        self.invocation = 0
        self.event_count = 0
        self.entity_ids = set()
        self.call_stacks = {}
        self.pending_exceptions = {}
        self.line_offsets = {}
        self.loop_iterations = {}
        self.active_loops = {}
        self.transfer_records = []
        self.versions = default_registry()
        # A sampler's background thread does not survive fork. Do not let the
        # child attempt to join a copied, non-running Thread object; the
        # parent continues sampling its own process context.
        self.resource_sampler = None
        self.meta = {
            "python": sys.version,
            "platform": platform.platform(),
            "pid": current_pid,
            "forked_from_pid": parent_pid,
            "started_ns": time.perf_counter_ns(),
            "evidence": "Observed",
        }
        self.meta_path.write_text(json.dumps(self.meta, indent=2, default=str))

    def _value(self, value) -> dict[str, Any]:
        self._ensure_process_context()
        if hasattr(value, "shape") and hasattr(value, "device"):
            try:
                _, storage_epoch, logical_epoch = self.versions.observe(value)
            except Exception:
                ptr, storage_epoch, logical_epoch = 0, 0, 0
            entity = tensor_entity(value, version=logical_epoch, storage_epoch=storage_epoch)
            # Python object and storage addresses are process-local.  Include
            # the process namespace before serializing them into a shared
            # trace so worker identities cannot alias accidentally.
            storage_name = f"storage:{self.process_id:x}:{entity.regions[0].storage.value.split(':', 1)[-1]}" if entity.regions else None
            logical_name = (f"{storage_name}@{entity.regions[0].storage.epoch}:v{logical_epoch}"
                            if storage_name and entity.regions else None)
            d = {"object_id": f"py:{self.process_id:x}:{id(value):x}", "type": entity.type_name,
                 "shape": list(value.shape), "dtype": str(value.dtype),
                 "device": str(value.device)}
            if entity.regions:
                region = entity.regions[0]
                d.update({"storage_id": storage_name, "logical_version": logical_name,
                          "offset": region.offset, "strides": list(region.strides)})
            if entity.object_id.value not in self.entity_ids:
                self.entities_fp.write(json.dumps({"kind": "object", "data": d}, default=str) + "\n")
                self.entity_ids.add(entity.object_id.value)
            return d
        return {"object_id": f"py:{self.process_id:x}:{id(value):x}", "type": type(value).__qualname__}

    def _literal_value(self, value, path: str, *, container: bool = False) -> dict[str, Any] | None:
        """Describe an exact built-in value without storing its user payload."""
        self._ensure_process_context()
        if container:
            payload = str(value).encode("utf-8", "surrogatepass")
            type_name = "container_structure"
        elif type(value) is float:
            payload = struct.pack("!d", value)
            type_name = "float"
        elif type(value) is bytes:
            payload = value
            type_name = "bytes"
        elif type(value) in (str, int, bool, type(None)):
            payload = repr((type(value).__qualname__, value)).encode(
                "utf-8", "surrogatepass")
            type_name = type(value).__qualname__
        else:
            return None
        digest = hashlib.sha256(type_name.encode() + b"\0" + payload).hexdigest()
        return {
            "object_id": f"py:{self.process_id:x}:{id(value):x}",
            "logical_version": f"literal:sha256:{digest}",
            "type": type_name,
            "representation": "python_immutable" if not container else "python_container_structure",
            "device": "python",
            "dtype": type_name,
            "shape": [],
            "strides": [],
            "offset": 0,
            "input_path": path,
            "content_fingerprint": f"sha256:{digest}",
        }

    @staticmethod
    def _callable_function(value):
        """Return the underlying Python function for a callable descriptor."""
        if isinstance(value, functools.partial):
            return value.func
        if isinstance(value, (types.MethodType, types.BuiltinMethodType)):
            return getattr(value, "__func__", value)
        return value

    def _callable_descriptor(self, value, path: str) -> tuple[dict[str, Any], bool]:
        """Describe a callback without claiming its globals are closed.

        A function's code identity and closure are observable, but its global
        module, default arguments, C implementation, and callback registry
        remain outside this local contract.  The returned completeness bit is
        therefore deliberately false; the descriptor is useful for graph
        structure and invalidation diagnostics, never as a purity proof.
        """
        self._ensure_process_context()
        function = self._callable_function(value)
        code = getattr(function, "__code__", None)
        code_id = CodeID.from_code(code).key() if code is not None else None
        if code_id is None:
            module = getattr(function, "__module__", None) or type(function).__module__
            qualname = getattr(function, "__qualname__", None) or type(function).__qualname__
            logical = f"callable:{module}.{qualname}"
        else:
            logical = f"callable:{code_id}"
        closure_names = list(getattr(code, "co_freevars", ()) or ())
        descriptor = {
            "object_id": f"py:{self.process_id:x}:{id(value):x}",
            "logical_version": logical,
            "type": type(value).__qualname__,
            "representation": "python_callable",
            "device": "python",
            "dtype": "callable",
            "shape": [],
            "strides": [],
            "offset": 0,
            "input_path": path,
            "state_role": "callable",
            "callable_code_id": code_id,
            "closure_names": closure_names,
            "callable_capture": "Observed identity; globals/registry UNKNOWN",
        }
        # See the docstring: even a function without a closure can read
        # globals or defaults, so it is never complete for exact reuse here.
        return descriptor, False

    @staticmethod
    def _is_python_callable(value) -> bool:
        return isinstance(value, _PYTHON_CALLABLE_TYPES)

    def _contract_inputs(self, value, path: str = "arguments") -> tuple[list[dict[str, Any]], bool]:
        """Capture the values required by an explicit pure-module contract.

        Tensor regions, exact built-in scalars, dictionary keys, and container
        structure are represented.  Opaque or cyclic values make the read set
        incomplete instead of being omitted from a supposedly complete
        contract.
        """
        result: list[dict[str, Any]] = []
        active_containers: set[int] = set()
        active_callables: set[int] = set()
        complete = True

        def visit(item, item_path: str) -> None:
            nonlocal complete
            if hasattr(item, "shape") and hasattr(item, "device"):
                observed = self._value(item)
                observed["input_path"] = item_path
                result.append(observed)
                return
            if self._is_python_callable(item):
                identity = id(item)
                if identity in active_callables:
                    complete = False
                    return
                active_callables.add(identity)
                try:
                    descriptor, callable_complete = self._callable_descriptor(item, item_path)
                    result.append(descriptor)
                    complete = complete and callable_complete
                    function = self._callable_function(item)
                    closure = getattr(function, "__closure__", None)
                    names = tuple(getattr(function, "__code__", None).co_freevars
                                  if getattr(function, "__code__", None) is not None else ())
                    if names and closure is None:
                        complete = False
                    for name, cell in zip(names, closure or ()):
                        try:
                            contents = cell.cell_contents
                        except ValueError:
                            complete = False
                            continue
                        start = len(result)
                        visit(contents, f"{item_path}.closure[{name}]")
                        for captured in result[start:]:
                            captured.setdefault("state_role", "closure_capture")
                finally:
                    active_callables.remove(identity)
                return
            literal = self._literal_value(item, item_path)
            if literal is not None:
                result.append(literal)
                return
            if type(item) not in (tuple, list, dict):
                complete = False
                return
            identity = id(item)
            if identity in active_containers:
                complete = False
                return
            active_containers.add(identity)
            try:
                descriptor = (type(item).__qualname__, len(item))
                marker = self._literal_value(descriptor, item_path, container=True)
                if marker is not None:
                    result.append(marker)
                if type(item) is dict:
                    for index, (key, child) in enumerate(item.items()):
                        visit(key, f"{item_path}.key[{index}]")
                        visit(child, f"{item_path}.value[{index}]")
                else:
                    for index, child in enumerate(item):
                        visit(child, f"{item_path}[{index}]")
            finally:
                active_containers.remove(identity)

        visit(value, path)
        return result, complete

    def _mark_write(self, value) -> None:
        """Advance SCAR's logical version for an observed tensor write."""
        if not hasattr(value, "shape") or not hasattr(value, "device"):
            return
        try:
            self.versions.mark_write(value)
        except Exception:
            return

    def mark_dispatch_write(self, args, op: str) -> list[str]:
        """Record conservative writes for in-place/functional mutation ops."""
        parts = str(op).split(".")
        name = parts[1] if len(parts) > 1 else parts[0]
        mutating = name.endswith("_") or name in {"aten::copy_", "aten::resize_"}
        if not mutating:
            return []
        written = []
        for value in _flatten(args):
            if hasattr(value, "shape"):
                self._mark_write(value)
                written.append(self._value(value).get("logical_version", "unknown"))
        return written

    def _emit(self, event: Event) -> int:
        self._ensure_process_context()
        event.metadata.setdefault("process_id", self.process_id)
        event.metadata.setdefault("thread_id", threading.get_ident())
        event.metadata.setdefault("clock_domain", "perf_counter")
        idx = self.event_count
        self.event_count += 1
        self.events_fp.write(json.dumps({"index": idx, **event.as_dict()}, default=str) + "\n")
        return idx

    def _parent_metadata(self) -> dict[str, Any]:
        stack = self.call_stacks.get(threading.get_ident(), ())
        metadata = {"parent_invocation_id": stack[-1][1] if stack else None,
                    "call_depth": len(stack)}
        # A nested module/operator callback may execute while an outer user
        # frame owns the active loop. Looking only at ``stack[-1]`` loses
        # that control fact when an intervening user frame has no back-edge.
        # Search from the innermost frame outward and retain the first
        # observed active loop; missing loop context remains UNKNOWN.
        for frame_id, invocation, _started, _code in reversed(stack):
            loop = self.active_loops.get(frame_id)
            if loop is not None:
                offset, iteration = loop
                metadata.update({"loop_target_offset": offset,
                                 "loop_iteration": iteration,
                                 "loop_instance": f"{invocation}:{offset}:{iteration}",
                                 "loop_parent_invocation_id": invocation})
                break
        return metadata

    def module_inputs(self, module, args, kwargs) -> tuple[list[dict[str, Any]], bool]:
        """Capture module reads before forward execution."""
        self._ensure_process_context()
        pure_contract = bool(getattr(module, "scar_pure", False))
        if pure_contract:
            inputs, reads_complete = self._contract_inputs((args, kwargs))
            # Module output also depends on parameters, buffers and per-module
            # training flags.  They are state inputs even when the Python
            # forward signature mentions only one Tensor.
            try:
                for name, value in module.named_parameters(recurse=True):
                    observed = self._value(value)
                    observed.update({"input_path": f"module.parameter:{name}",
                                     "state_role": "module_parameter"})
                    inputs.append(observed)
                for name, value in module.named_buffers(recurse=True):
                    observed = self._value(value)
                    observed.update({"input_path": f"module.buffer:{name}",
                                     "state_role": "module_buffer"})
                    inputs.append(observed)
                for name, child in module.named_modules():
                    flag = self._literal_value(bool(child.training),
                                               f"module.training:{name or '<root>'}")
                    if flag is None:
                        reads_complete = False
                    else:
                        flag["state_role"] = "module_training"
                        inputs.append(flag)
                    # Custom Python fields are State too. Built-in immutable
                    # values and containers receive content versions; opaque
                    # fields make the declared read set incomplete. PyTorch's
                    # registered state and hook dictionaries are handled by
                    # the dedicated parameter/buffer/training/hook contracts.
                    for attribute, state in sorted(child.__dict__.items()):
                        if attribute in _MODULE_INTERNAL_STATE:
                            continue
                        captured, captured_complete = self._contract_inputs(
                            state,
                            f"module.attribute:{name or '<root>'}.{attribute}")
                        for item in captured:
                            item["state_role"] = "module_attribute"
                        inputs.extend(captured)
                        reads_complete = reads_complete and captured_complete
            except (AttributeError, RuntimeError, TypeError):
                reads_complete = False
        else:
            inputs = [self._value(x) for x in _flatten((args, kwargs)) if hasattr(x, "shape")]
            reads_complete = False
        return inputs, reads_complete

    @staticmethod
    def _module_input_signature(inputs: list[dict[str, Any]]) -> tuple:
        return tuple((item.get("input_path"), item.get("logical_version"),
                      item.get("storage_id"), item.get("offset", 0),
                      tuple(item.get("shape", [])), tuple(item.get("strides", [])),
                      item.get("dtype"), item.get("device")) for item in inputs)

    def module_call(self, module, args, kwargs, result, duration_ns: int,
                    code_id: str | None = None,
                    captured_inputs: tuple[list[dict[str, Any]], bool] | None = None) -> int:
        self._ensure_process_context()
        self.invocation += 1
        pure_contract = bool(getattr(module, "scar_pure", False))
        inputs, reads_complete = (captured_inputs if captured_inputs is not None
                                  else self.module_inputs(module, args, kwargs))
        state_stable: bool | None = None
        changed_states: list[str] = []
        writes_complete = pure_contract
        if pure_contract and captured_inputs is not None:
            post_inputs, post_complete = self.module_inputs(module, args, kwargs)
            before = self._module_input_signature(inputs)
            after = self._module_input_signature(post_inputs)
            state_stable = before == after if post_complete else None
            writes_complete = post_complete
            if state_stable is False:
                before_by_path = {item.get("input_path"): item for item in inputs}
                for item in post_inputs:
                    prior = before_by_path.get(item.get("input_path"))
                    if prior is None or self._module_input_signature([prior]) != self._module_input_signature([item]):
                        changed_states.append(item.get("logical_version", item.get("object_id", "unknown")))
        outputs = [self._value(x) for x in _flatten(result) if hasattr(x, "shape")]
        labels = ["CTRL", "VAL"]
        if any(x.get("device", "cpu") != "cpu" for x in inputs + outputs):
            labels.append("XFER" if any(x.get("device") == "cpu" for x in inputs + outputs) else "VAL")
        # An uncontracted module is executable evidence, but its hidden
        # state, callbacks, RNG and external behavior are not explained by
        # the tensor input snapshot.  Keep that uncertainty in the Action
        # taxonomy instead of making ``VAL`` look like a complete semantic
        # classification.  A reviewed pure contract with a complete
        # pre/post state capture may omit OPAQUE.
        if (not pure_contract or not reads_complete or
                (pure_contract and captured_inputs is None)):
            labels.append("OPAQUE")
        effect = Effect(reads=[x.get("logical_version", x["object_id"]) for x in inputs],
                        writes=changed_states,
                        rng_effect=__import__("scar.ir", fromlist=["Knowledge"]).Knowledge.UNKNOWN,
                        may_raise=__import__("scar.ir", fromlist=["Knowledge"]).Knowledge.UNKNOWN,
                        external_effect=__import__("scar.ir", fromlist=["Knowledge"]).Knowledge.UNKNOWN,
                        ordering_effect=__import__("scar.ir", fromlist=["Knowledge"]).Knowledge.UNKNOWN)
        if pure_contract:
            from scar.ir import Knowledge
            effect.rng_effect = effect.may_raise = effect.external_effect = effect.ordering_effect = Knowledge.NONE
            effect.collection_knowledge = {
                name: (Knowledge.KNOWN if reads_complete else Knowledge.UNKNOWN)
                if name == "reads" else
                (Knowledge.KNOWN if writes_complete else Knowledge.UNKNOWN)
                if name == "writes" else Knowledge.NONE
                for name in ("reads", "writes", "allocates", "frees", "aliases", "escapes")}
            effect.notes.append(
                "scar_pure user contract; effect absence is declared, not inferred from eval; "
                f"read capture {'complete' if reads_complete else 'UNKNOWN'}")
        code = getattr(module.forward, "__code__", None)
        event = Event(kind="module_call", duration_ns=duration_ns, code_id=code_id,
                      invocation_id=self.invocation, labels=labels, inputs=inputs,
                      outputs=outputs, effect=effect,
                      resource={"device": str(getattr(module, "device", "unknown"))},
                      metadata={**self._parent_metadata(),
                                "pure_contract": pure_contract,
                                "contract_read_capture": ("complete" if reads_complete else "UNKNOWN"),
                                "contract_state_stable": state_stable,
                                "file": getattr(code, "co_filename", None),
                                "line": getattr(code, "co_firstlineno", None),
                                "qualname": getattr(code, "co_qualname", None)})
        return self._emit(event)

    def transfer(self, op: str, tensor, result, duration_ns: int) -> int:
        self._ensure_process_context()
        self.invocation += 1
        inp = self._value(tensor)
        out = self._value(result)
        source_device = inp.get("device", "unknown")
        destination_device = out.get("device", "unknown")
        # A Tensor.to/cpu/cuda call is only a physical transfer when runtime
        # values prove a device transition. Same-device .to() may return the
        # original object; dtype/layout changes are representation events.
        device_transition = source_device != destination_device
        same_object = inp.get("object_id") == out.get("object_id")
        empty = getattr(tensor, "numel", lambda: 1)() == 0
        # A changed device is runtime value evidence, but not a measured
        # PCIe/DMA operation. Only a Kineto gpu_memcpy activity establishes it.
        physical = False if same_object or empty else None
        # A copy creates a new storage representation of the same logical
        # value. Preserve the source logical version while retaining the new
        # destination StorageID, so residency analysis can join copies.
        if device_transition and inp.get("dtype") == out.get("dtype") and inp.get("logical_version"):
            out["logical_version"] = inp["logical_version"]
        labels = ["REP"] + (["XFER"] if device_transition else [])
        try:
            bytes_moved = int(tensor.numel()) * int(tensor.element_size())
        except (AttributeError, TypeError, ValueError, RuntimeError):
            bytes_moved = None
        event = Event(kind="transfer", duration_ns=duration_ns,
                      invocation_id=self.invocation, labels=labels,
                      inputs=[inp], outputs=[out],
                      effect=Effect(reads=[inp.get("logical_version", inp["object_id"])],
                                    ordering_effect=Knowledge.UNKNOWN),
                      resource={"operation": op, "source_device": source_device,
                                "destination_device": destination_device,
                                "bytes": bytes_moved},
                      metadata={"physical": physical,
                                **self._parent_metadata(),
                                "device_transition": device_transition,
                                "physical_evidence": "requires correlated gpu_memcpy" if physical is None else "no copy",
                                "same_object": same_object})
        index = self._emit(event)
        if device_transition and not same_object and bytes_moved is not None:
            self.transfer_records.append((index, event))
        return index

    def torch_dispatch(self, op: str, args, kwargs, result, duration_ns: int) -> int:
        self._ensure_process_context()
        self.invocation += 1
        # Capture reads before an in-place operation advances the SCAR-owned
        # logical epoch, then record post-call writes. This preserves the
        # transition ``v0 -> v1`` in the event rather than labeling both sides
        # with the post-call version.
        inputs = [self._value(x) for x in _flatten((args, kwargs)) if hasattr(x, "shape")]
        writes = self.mark_dispatch_write(args, op)
        outputs = [self._value(x) for x in _flatten(result) if hasattr(x, "shape")]
        return self._emit(Event(kind="torch_dispatch", code_id=op,
                                invocation_id=self.invocation, duration_ns=duration_ns,
                                labels=["VAL", "OPAQUE"], inputs=inputs, outputs=outputs,
                                effect=Effect(reads=[x.get("logical_version", x["object_id"]) for x in inputs],
                                               writes=writes),
                                resource={"device": ",".join(sorted({x.get("device", "unknown") for x in inputs + outputs}))},
                                metadata=self._parent_metadata()))

    def python_call(self, frame) -> int | None:
        self._ensure_process_context()
        filename = frame.f_code.co_filename
        if (filename.startswith("<") or filename.startswith(self.package_root) or filename.endswith("sitecustomize.py")
                or "/site-packages/" in filename or "/lib/python" in filename):
            return None
        self.invocation += 1
        code = CodeID.from_frame(frame)
        thread_id = threading.get_ident()
        stack = self.call_stacks.setdefault(thread_id, [])
        parent = stack[-1][1] if stack else None
        stack.append((id(frame), self.invocation, time.perf_counter_ns(), code))
        inputs: list[dict[str, Any]] = []
        input_names: list[str] = []
        seen_inputs: set[str] = set()
        seen_callables: set[str] = set()
        callable_inputs: list[dict[str, Any]] = []
        callable_capture_complete = True

        def capture(value, name: str) -> None:
            nonlocal callable_capture_complete
            for item in _flatten(value):
                if self._is_python_callable(item) and name not in {"self", "cls"}:
                    records, complete = self._contract_inputs(item, name)
                    callable_capture_complete = callable_capture_complete and complete
                    descriptor = next(
                        (record for record in records
                         if record.get("representation") == "python_callable"),
                        None,
                    )
                    if descriptor is not None:
                        identity = descriptor.get("object_id")
                        if identity in seen_callables:
                            continue
                        seen_callables.add(identity)
                        callable_inputs.append({
                            key: descriptor.get(key)
                            for key in ("object_id", "logical_version",
                                        "callable_code_id", "closure_names",
                                        "input_path", "callable_capture")
                        })
                    for observed in records:
                        identity = observed.get("object_id")
                        if identity in seen_inputs:
                            continue
                        seen_inputs.add(identity)
                        inputs.append(observed)
                    input_names.append(name)
                    continue
                if not (hasattr(item, "shape") and hasattr(item, "device")):
                    continue
                observed = self._value(item)
                identity = observed.get("object_id")
                if identity in seen_inputs:
                    continue
                seen_inputs.add(identity)
                inputs.append(observed)
                input_names.append(name)

        try:
            for name, value in frame.f_locals.items():
                capture(value, str(name))
            # A function can read a Tensor through a module global without
            # placing it in f_locals. Restrict this scan to names referenced
            # by the loaded code object; arbitrary globals are not inputs just
            # because they happen to exist in the module dictionary.
            globals_map = getattr(frame, "f_globals", None)
            if isinstance(globals_map, dict):
                for name in frame.f_code.co_names:
                    if name in globals_map:
                        capture(globals_map[name], f"global:{name}")
        except (AttributeError, RuntimeError, TypeError):
            # Keep values captured before an opaque or concurrently changed
            # object failed inspection. Their completeness remains UNKNOWN.
            pass
        line = frame.f_lineno if frame.f_lineno > 0 else (code.line or 0)
        self._emit(Event(kind="python_call", code_id=code.key(), invocation_id=self.invocation,
                         labels=["CTRL", "OPAQUE"], inputs=inputs,
                         effect=Effect(reads=[item.get("logical_version", item["object_id"])
                                             for item in inputs]),
                         metadata={**self._parent_metadata(),
                                   "function": frame.f_code.co_name, "file": filename,
                                   "line": line, "first_line": code.line,
                                   "input_names": input_names,
                                   "input_capture": "frame_locals+referenced_globals; completeness UNKNOWN",
                                   "callable_inputs": callable_inputs,
                                   "callable_capture": (
                                       "complete" if callable_capture_complete else "UNKNOWN"),
                                   "parent_invocation_id": parent,
                                   "call_depth": len(stack) - 1}))
        return self.invocation

    def python_exception(self, frame, arg) -> None:
        key = (threading.get_ident(), id(frame))
        if any(entry[0] == key[1] for entry in self.call_stacks.get(key[0], ())):
            if isinstance(arg, tuple) and arg:
                exception = arg[0]
                name = exception.__name__ if isinstance(exception, type) else type(exception).__name__
            else:
                name = type(arg).__name__
            self.pending_exceptions[key] = name

    def c_call(self, frame, callable_object) -> None:
        """Record a side-effect-sensitive C builtin called by user code.

        CPython profile hooks expose the callable but not its arguments or
        return value. The event is therefore an opaque action with conservative
        UNKNOWN effects. It prevents a source line containing ``open``/``print``
        or a synchronization primitive from being mistaken for pure work,
        while avoiding a high-volume record for every arithmetic C helper.
        """
        self._ensure_process_context()
        if not self._is_user_frame(frame):
            return
        name = str(getattr(callable_object, "__name__", "<c-call>"))
        if name not in (_C_IO_NAMES | _C_ORDER_NAMES | _C_STATE_NAMES):
            return
        module = getattr(callable_object, "__module__", None)
        qualname = getattr(callable_object, "__qualname__", name)
        labels = ["CTRL", "OPAQUE"]
        if name in _C_IO_NAMES:
            labels.append("IO")
        if name in _C_ORDER_NAMES:
            labels.append("ORDER")
        if name in _C_STATE_NAMES:
            labels.append("STATE")
        self.invocation += 1
        code = CodeID.from_code(frame.f_code)
        self._emit(Event(
            kind="python_c_call", code_id=code.key(), invocation_id=self.invocation,
            labels=list(dict.fromkeys(labels)),
            effect=Effect(
                rng_effect=Knowledge.UNKNOWN, may_raise=Knowledge.UNKNOWN,
                external_effect=Knowledge.UNKNOWN, ordering_effect=Knowledge.UNKNOWN,
            ),
            metadata={**self._parent_metadata(),
                      "function": frame.f_code.co_name,
                      "file": frame.f_code.co_filename,
                      "line": int(frame.f_lineno),
                      "c_function": name,
                      "c_module": module,
                      "c_qualname": qualname,
                      "argument_capture": "UNKNOWN",
                      "return_capture": "UNKNOWN",
                      "evidence": "Observed"},
        ))

    def _is_user_frame(self, frame) -> bool:
        filename = frame.f_code.co_filename
        return not (filename.startswith("<") or filename.startswith(self.package_root)
                    or filename.endswith("sitecustomize.py")
                    or "/site-packages/" in filename or "/lib/python" in filename)

    def python_line(self, frame) -> None:
        """Record an optional user line and conservative loop back-edge."""
        self._ensure_process_context()
        if not self._is_user_frame(frame):
            return
        thread_id = threading.get_ident()
        stack = self.call_stacks.get(thread_id, ())
        invocation = None
        depth = 0
        if stack:
            # A line event belongs to the current frame. Profile callbacks
            # normally establish this entry first; if a runtime omits that
            # callback, retain the line as an unparented observation.
            for frame_id, value, _started, _code in reversed(stack):
                if frame_id == id(frame):
                    invocation = value
                    depth = len(stack) - 1
                    break
        code = CodeID.from_code(frame.f_code)
        frame_id = id(frame)
        offset = int(getattr(frame, "f_lasti", -1))
        previous = self.line_offsets.get(frame_id)
        metadata = {"function": frame.f_code.co_name,
                    "file": frame.f_code.co_filename,
                    "line": int(frame.f_lineno),
                    "byte_offset": offset,
                    "previous_byte_offset": previous,
                    "call_depth": depth,
                    "parent_invocation_id": stack[-2][1] if len(stack) > 1 else None,
                    "line_evidence": "Observed"}
        self._emit(Event(kind="python_line", code_id=code.key(),
                         invocation_id=invocation, labels=["CTRL", "OPAQUE"],
                         effect=Effect(), metadata=metadata))
        if previous is not None and offset >= 0 and offset < previous:
            loop_key = (frame_id, offset)
            iteration = self.loop_iterations.get(loop_key, 0) + 1
            self.loop_iterations[loop_key] = iteration
            self.active_loops[frame_id] = (offset, iteration)
            self._emit(Event(kind="loop_iteration", code_id=code.key(),
                             invocation_id=invocation, labels=["CTRL"],
                             effect=Effect(), metadata={**metadata,
                                 "loop_target_offset": offset,
                                 "iteration": iteration,
                                 "loop_evidence": "Observed bytecode back-edge"}))
        self.line_offsets[frame_id] = offset

    def python_line_return(self, frame) -> None:
        self._ensure_process_context()
        frame_id = id(frame)
        self.line_offsets.pop(frame_id, None)
        self.active_loops.pop(frame_id, None)
        for key in [key for key in self.loop_iterations if key[0] == frame_id]:
            self.loop_iterations.pop(key, None)

    def python_return(self, frame, value=None) -> None:
        self._ensure_process_context()
        thread_id = threading.get_ident()
        stack = self.call_stacks.get(thread_id)
        if not stack:
            return
        frame_id = id(frame)
        position = next((i for i in range(len(stack) - 1, -1, -1)
                         if stack[i][0] == frame_id), None)
        if position is None:
            return
        _, invocation, started, code = stack.pop(position)
        if not stack:
            self.call_stacks.pop(thread_id, None)
        exception = self.pending_exceptions.pop((thread_id, frame_id), None)
        self.python_line_return(frame)
        outcome = "exception:" + exception if exception else "return"
        returned = [item for item in _flatten(value)
                    if hasattr(item, "shape") and hasattr(item, "device")]
        outputs = [self._value(item) for item in returned]
        escapes = [item.get("logical_version", item.get("object_id", "unknown"))
                   for item in outputs]
        returned_callables: list[dict[str, Any]] = []
        for item in _flatten(value):
            if self._is_python_callable(item):
                descriptor, _complete = self._callable_descriptor(
                    item, "return")
                returned_callables.append({
                    key: descriptor.get(key)
                    for key in ("object_id", "logical_version",
                                "callable_code_id", "closure_names",
                                "callable_capture")
                })
        opaque_return = value is not None and any(
            not (hasattr(item, "shape") and hasattr(item, "device"))
            for item in _flatten(value))
        escape_knowledge = Knowledge.UNKNOWN if opaque_return else Knowledge.KNOWN
        self._emit(Event(kind="python_return", code_id=code.key(), invocation_id=invocation,
                         duration_ns=time.perf_counter_ns() - started,
                         labels=["CTRL"] + (["OPAQUE"] if opaque_return else []),
                         outputs=outputs,
                         effect=Effect(escapes=escapes,
                                       collection_knowledge={"escapes": escape_knowledge}),
                         metadata={**self._parent_metadata(),
                             "paired_invocation_id": invocation,
                             "outcome": outcome, "function": code.qualname,
                             "parent_invocation_id": stack[-1][1] if stack else None,
                             "call_depth": len(stack),
                             "return_escape_evidence": "UNKNOWN" if opaque_return else "Observed",
                             "returned_callables": returned_callables}))

    def close(self, exit_code: int | None = None) -> None:
        self._ensure_process_context()
        if self.events_fp.closed:
            return
        if self.resource_sampler is not None:
            self.meta["resource_sampling"] = self.resource_sampler.stop()
        self.meta.update({"ended_ns": time.perf_counter_ns(), "event_count": self.event_count,
                          "entity_count": len(self.entity_ids), "exit_code": exit_code})
        self.events_fp.close(); self.entities_fp.close()
        self.meta_path.write_text(json.dumps(self.meta, indent=2, default=str))
