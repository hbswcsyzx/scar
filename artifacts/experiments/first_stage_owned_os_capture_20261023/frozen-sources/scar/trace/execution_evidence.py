"""Delayed, owner-process ETO/Kineto collection, without Python/Tensor hooks.

This is raw execution evidence, not a canonical graph importer.  The caller
owns shutdown (typically via atexit); install() never imports torch or registers
an atexit handler.  Provider buffers are not subject to a hard memory budget.
"""
from __future__ import annotations

import builtins
import json
import os
from pathlib import Path
import secrets
import sys
import threading
import time


# This revision returns True even when an existing ETO owns the global callback.
# Only creation of our previously absent nonce path is an ownership receipt.
_ETO_REVISION = "cf30153c4c131c8164ee7798e5022d810682e2cb"
_ETO_SOURCE_SHA256 = "c6ec2dac4140b28eea17c8c6054d42e084ab6014fa8f47e72282e7c4caba46db"
_ETO_SOURCE_URL = (
    "https://raw.githubusercontent.com/pytorch/pytorch/" + _ETO_REVISION
    + "/torch/csrc/profiler/standalone/execution_trace_observer.cpp"
)
_EXTRA_ENV = (
    "ENABLE_PYTORCH_EXECUTION_TRACE_EXTRAS",
    "ENABLE_PYTORCH_EXECUTION_TRACE_SAVE_INTEGRAL_TENSOR_RANGE",
    "ENABLE_PYTORCH_EXECUTION_TRACE_SAVE_INTEGRAL_TENSOR_DATA",
)


class ExecutionEvidence:
    """One delayed capture. close() is idempotent and never stops a foreign ETO."""

    def __init__(self, out, *, recorder=None):
        self.pid = os.getpid()
        self.thread = threading.get_ident()
        self.status = "WAITING_FOR_TORCH"
        self._lock = threading.RLock()
        self._closed = False
        self._starting = False
        self._observer = None
        self._observer_owned = False
        self._profiler = None
        self._call_recorder = recorder
        self._dispatch_evidence = None
        self._physical_requested = os.environ.get("SCAR_TENSOR_PHYSICAL") == "1"
        self._enter_attempted = False
        self._recording = False
        self._previous_import = None
        self._hook = None
        self._manifest_owned = False
        self._manifest_path = None
        self._manifest_temp = None
        self._paths = {}
        self._failures = []
        self._gaps = [
            "only the installing process and provider capture window are observed",
            "forked/child processes and complete thread coverage are not established",
            "imports bypassing builtins.__import__ may not trigger delayed startup",
            "profiler startup/shutdown must run on the installing thread",
            "external provider mutation during capture cannot be globally excluded",
            "Python-to-Torch occurrence correspondence is not established",
            "host return does not establish GPU completion or materialization readiness",
            "provider buffers have no collector-enforced hard memory budget",
            "native observation can change reference lifetimes, allocation and timing",
        ]
        self._provider = {"torch_version": None, "torch_git_version": None}
        self._registration = {
            "owned": False,
            "rule": "previously_absent_nonce_path_created_by_registration",
            "source_revision": _ETO_REVISION,
            "source_sha256": _ETO_SOURCE_SHA256,
            "source_url": _ETO_SOURCE_URL,
            "source_lines": "322-327,904-961",
            "assumptions": [
                "installed provider implements the declared source revision",
                "no external actor creates the private random path concurrently",
            ],
        }
        self._window = {
            "clock": "time.perf_counter_ns",
            "start_requested_ns": None, "started_ns": None,
            "stop_requested_ns": None, "stopped_ns": None,
            "alignment": "one profiler lifecycle; provider start/stop calls are sequenced",
        }
        self._config = {
            "record_shapes": self._physical_requested, "profile_memory": True,
            "with_stack": False, "with_modules": False,
            "execution_trace_observer": True, "extra_resources": False,
            "extra_tensor_data": False, "activities": None,
            "memory_dataflow_graph": False,
            "experimental_config": None,
        }
        try:
            root = Path(out).absolute()
            root.mkdir(parents=True, exist_ok=True)
            nonce = secrets.token_hex(16)
            if any(os.environ.get(key) for key in (
                    'SCAR_OS_CAPTURE_NONCE','SCAR_OS_CAPTURE_INTENT','SCAR_OS_CAPTURE_INTENT_SHA256')):
                from scar.trace.os_capture_launch import native_intent
                self._config['os_capture_intent'] = native_intent(root, nonce)
            self._paths = {
                "execution_trace": root / f"execution-trace.{self.pid}.{nonce}.json",
                "kineto": root / f"kineto.{self.pid}.{nonce}.json",
            }
            if self._physical_requested:
                self._config["tensor_physical_observations"] = {
                    "profile": "scar.tensor-physical-event-tree-v1", "requested": True,
                    "events": str(root / f"tensor-physical.{self.pid}.{nonce}.jsonl"),
                    "metadata": str(root / f"tensor-physical-meta.{self.pid}.{nonce}.json"),
                    "failure": str(root / f"tensor-physical-failure.{self.pid}.{nonce}.json"),
                    "export_timing": "after final native manifest and dispatch metadata close",
                }
            self._manifest_path = root / f"execution-evidence.{self.pid}.json"
            self._manifest_temp = root / f".execution-evidence.{self.pid}.{nonce}.tmp"
            # A second manager must not overwrite a previous collection manifest.
            with self._manifest_path.open("x", encoding="utf-8") as stream:
                json.dump(self._document(), stream, indent=2)
                stream.write("\n")
            self._manifest_owned = True
            self._previous_import = builtins.__import__

            def importing(name, globals=None, locals=None, fromlist=(), level=0):
                result = self._previous_import(name, globals, locals, fromlist, level)
                # Original import exceptions and return values are untouched.
                try:
                    self._maybe_start()
                except Exception as error:
                    self._failure("import_notification", error)
                return result

            self._hook = importing
            builtins.__import__ = importing
            if hasattr(os, "register_at_fork"):
                os.register_at_fork(after_in_child=self._after_fork)
            self._maybe_start()
        except Exception as error:
            self.status = "FAILED"
            self._failure("install", error)
            self._restore_import()
            self._write_manifest()

    def _failure(self, stage, error):
        if len(self._failures) < 16:
            self._failures.append({"stage": stage, "type": type(error).__name__,
                                   "message": str(error)[:1024]})

    def _gap(self, message):
        if message not in self._gaps:
            self._gaps.append(message)

    def _document(self):
        artifacts = {}
        for name, path in self._paths.items():
            try:
                size = path.stat().st_size
            except OSError:
                size = None
            artifacts[name] = {"path": str(path), "size_bytes": size,
                               "exists": size is not None}
        return {
            "schema": "scar.execution-evidence-collection", "schema_version": 1,
            "pid": self.pid, "install_thread_id": self.thread,
            "python_version": sys.version, "status": self.status,
            "whole_model_established": False,
            "canonical_graph_imported": False, "raw_json_validated": False,
            "completeness": {"all_paths": False, "all_processes": False,
                             "all_threads": False, "state_effects": False,
                             "logical_value_identity": False, "resource_readiness": False},
            "window": dict(self._window), "provider": dict(self._provider),
            "configuration": dict(self._config), "registration": dict(self._registration),
            "artifacts": artifacts, "failures": list(self._failures), "gaps": list(self._gaps),
            "provider_schemas": {"execution_trace": "1.1.1-chakra.0.0.4",
                                 "execution_trace_basis": "pinned provider source, not JSON validation",
                                 "kineto": "provider Chrome trace; retained without schema conversion"},
        }

    def _write_manifest(self):
        if os.getpid() != self.pid or not self._manifest_owned:
            return
        try:
            with self._manifest_temp.open("w", encoding="utf-8") as stream:
                json.dump(self._document(), stream, indent=2)
                stream.write("\n")
            os.replace(self._manifest_temp, self._manifest_path)
        except Exception as error:
            self._failure("manifest", error)

    def _restore_import(self):
        if self._hook is not None and builtins.__import__ is self._hook:
            builtins.__import__ = self._previous_import

    def _after_fork(self):
        # These Python flags are private copies in the child. Do not call any
        # native stop/remove function against inherited parent capture state.
        self._closed = True
        self._restore_import()
        self._disarm_unowned_observer()
        self._observer_owned = False

    def _disarm_unowned_observer(self):
        if self._observer is not None:
            # The pinned class's __del__ calls unregister_callback() based on
            # this local flag, even if native registration returned a false
            # ownership success for an already registered external observer.
            self._observer._registered = False
            self._observer._execution_trace_running = False

    def _unsupported(self, reason):
        self.status = "UNSUPPORTED"
        self._gap(reason)
        self._restore_import()
        self._write_manifest()

    def _maybe_start(self):
        if os.getpid() != self.pid or self._closed or self.status != "WAITING_FOR_TORCH":
            return
        if threading.get_ident() != self.thread:
            return
        # Import callbacks on other threads must never wait for a provider
        # startup that might itself be waiting for their import to finish.
        if not self._lock.acquire(blocking=False):
            return
        try:
            if self._starting or self._closed or self.status != "WAITING_FOR_TORCH":
                return
            torch = sys.modules.get("torch")
            spec = getattr(torch, "__spec__", None)
            if torch is None or spec is None or getattr(spec, "_initializing", True):
                return
            self._starting = True
            self.status = "STARTING"
            try:
                self._start(torch)
            except Exception as error:
                self.status = "FAILED"
                self._failure("start", error)
                self._finish_owned()
            finally:
                self._restore_import()
                self._write_manifest()
        finally:
            self._lock.release()

    def _start(self, torch):
        version = getattr(torch, "version", None)
        self._provider.update(torch_version=str(getattr(torch, "__version__", "unknown")),
                              torch_git_version=getattr(version, "git_version", None))
        if self._provider["torch_git_version"] != _ETO_REVISION:
            self._unsupported("ETO registration ownership rule is unverified for this provider revision")
            return
        extra = {key: os.environ[key] for key in _EXTRA_ENV if key in os.environ}
        self._config["extra_collection_environment"] = extra
        if extra or os.environ.get("ENABLE_PYTORCH_EXECUTION_TRACE") == "1":
            self._unsupported("external ETO configuration or tensor-data/range environment is present")
            return
        autograd = getattr(torch, "autograd", None)
        enabled = getattr(autograd, "_profiler_enabled", None)
        python_profiler = getattr(autograd, "profiler", None)
        global_enabled = getattr(python_profiler, "_is_profiler_enabled", None)
        if not callable(enabled) or type(global_enabled) is not bool:
            self._unsupported("active profiler detection is unavailable")
            return
        active = enabled()
        if type(active) is not bool or active or global_enabled:
            self._unsupported("an external profiler is active or its state is unknown")
            return
        provider = getattr(torch, "profiler", None)
        observer_type = getattr(provider, "ExecutionTraceObserver", None)
        profile = getattr(provider, "profile", None)
        if not callable(observer_type) or not callable(profile):
            self._unsupported("ExecutionTraceObserver/profile APIs are unavailable")
            return
        path = self._paths["execution_trace"]
        if path.exists() or self._paths["kineto"].exists():
            self._unsupported("private provider artifact path already exists")
            return
        self._registration["path_absent_before_registration"] = True
        self._observer = observer_type()
        try:
            self._observer.register_callback(str(path))
        except Exception:
            # Without a successful receipt do not let __del__ remove a foreign
            # callback. A partial native failure remains explicitly unresolved.
            self._disarm_unowned_observer()
            raise
        created = path.is_file()
        registered = self._observer.is_registered
        self._registration.update(path_created_after_registration=created,
                                  observer_registered=registered)
        if not created or registered is not True:
            self._disarm_unowned_observer()
            self._unsupported("ETO registration is occupied or ownership could not be established")
            return
        self._observer_owned = True
        self._registration["owned"] = True
        self._observer.set_extra_resource_collection(False)
        options = {}
        experimental_type = getattr(getattr(torch._C, "_profiler", None), "_ExperimentalConfig", None)
        if callable(experimental_type):
            try:
                experimental = experimental_type(adjust_timestamps=False,
                    **({"trace_only": False} if self._physical_requested else {}))
            except TypeError:
                # Older providers retain their working profile path; absence
                # of this receipt never qualifies allocator event ordering.
                pass
            else:
                options["experimental_config"] = experimental
                self._config["experimental_config"] = {"adjust_timestamps": False}
                if self._physical_requested:
                    self._config["experimental_config"]["trace_only"] = False
        self._profiler = profile(record_shapes=self._physical_requested, profile_memory=True,
                                 with_stack=False, with_modules=False,
                                 execution_trace_observer=self._observer, **options)
        self._config["activities"] = sorted(str(item) for item in self._profiler.activities)
        self._window["start_requested_ns"] = time.perf_counter_ns()
        self._enter_attempted = True
        self._profiler.__enter__()
        self._window["started_ns"] = time.perf_counter_ns()
        self._recording = True
        self.status = "RECORDING"
        if self._call_recorder is not None:
            try:
                from scar.trace.dispatch_evidence import DispatchEvidence, PRODUCTION_PROFILE
                nonce = self._paths["kineto"].name.split(".")[2]
                self._dispatch_evidence = DispatchEvidence(
                    self._paths["kineto"].parent, self._call_recorder, nonce=nonce,
                    provider_revision=self._provider["torch_git_version"],
                    max_events=int(os.environ.get("SCAR_DISPATCH_MAX_EVENTS", "400000")),
                    max_bytes=int(os.environ.get("SCAR_DISPATCH_MAX_BYTES", "256000000")))
                started = self._dispatch_evidence.start(torch)
                self._config["dispatch_observations"] = {
                    "profile": PRODUCTION_PROFILE, "started": started,
                    "events": str(self._dispatch_evidence.event_path),
                    "metadata": str(self._dispatch_evidence.meta_path),
                    "owner_python_ident": self.thread,
                    "scope": "installing thread only; retained ancestor is not a direct caller"}
            except Exception as error:
                self._gap("dispatch observation bridge did not start")
                self._failure("dispatch_start", error)

    def _finish_owned(self):
        if os.getpid() != self.pid:
            return
        if self._dispatch_evidence is not None:
            try:
                self._dispatch_evidence.stop()
            except Exception as error:
                self._failure("dispatch_stop", error)
        if self._enter_attempted:
            self._enter_attempted = False
            self._window["stop_requested_ns"] = time.perf_counter_ns()
            try:
                self._profiler.__exit__(None, None, None)
                if self._recording:
                    self._profiler.export_chrome_trace(str(self._paths["kineto"]))
            except Exception as error:
                self._failure("stop_or_export", error)
            finally:
                self._window["stopped_ns"] = time.perf_counter_ns()
        if self._observer_owned:
            try:
                self._observer.unregister_callback()
            except Exception as error:
                self._failure("observer_cleanup", error)
            self._observer_owned = False

    def close(self):
        if os.getpid() != self.pid:
            self._after_fork()
            return
        with self._lock:
            if self._closed:
                return
            if threading.get_ident() != self.thread and self._enter_attempted:
                self.status = "FAILED"
                self._gap("close called on a different thread; native provider was not stopped")
                self._write_manifest()
                # Keep owner-thread shutdown available after this failed attempt.
                return
            self._closed = True
            self._restore_import()
            self._finish_owned()
            if self.status == "RECORDING":
                self.status = "FAILED" if self._failures else "CLOSED"
            elif self.status == "WAITING_FOR_TORCH":
                self.status = "NOT_COLLECTED"
                self._gap("torch was not fully observed on the installing thread before close")
            self._write_manifest()
            if self._dispatch_evidence is not None:
                try:
                    self._dispatch_evidence.close(native_manifest=self._manifest_path)
                except Exception as error:
                    # Keep the already-published native artifact unchanged:
                    # the dispatch sidecar may bind its exact final hash.
                    self._failure("dispatch_close", error)
            if self._physical_requested:
                self._export_physical()

    def _export_physical(self):
        """Publish a separate receipt without changing the closed hash chain."""
        if os.getpid() != self.pid:
            return
        config = self._config.get("tensor_physical_observations")
        if config is None:
            return
        try:
            from scar.trace.tensor_physical import export_tensor_physical
            if self._dispatch_evidence is None or self._profiler is None:
                raise ValueError("physical export requires owned dispatch and profiler results")
            nonce = self._paths["kineto"].name.split(".")[2]
            export_tensor_physical(self._profiler.profiler.kineto_results,
                self._paths["kineto"].parent, nonce=nonce,
                provider_revision=self._provider["torch_git_version"],
                dispatch_metadata_path=self._dispatch_evidence.meta_path,
                dispatch_observations_path=self._dispatch_evidence.event_path,
                native_manifest_path=self._manifest_path)
        except Exception as error:
            # The prior native manifest is already bound by dispatch metadata.
            # Export failure must not mutate either receipt or fail the target.
            failure = {"schema": "scar.tensor-physical-export-failure", "schema_version": 1,
                "pid": self.pid, "stage": "post_close_export", "status": "FAILED",
                "error": {"type": type(error).__name__, "message": str(error)[:1024]},
                "logical_versions_established": False, "whole_model_established": False}
            try:
                with Path(config["failure"]).open("x", encoding="utf-8") as stream:
                    json.dump(failure, stream, sort_keys=True, allow_nan=False)
                    stream.write("\n")
            except (OSError, ValueError):
                pass


def install(out, *, recorder=None):
    """Install delayed raw collection; the caller must arrange manager.close()."""
    return ExecutionEvidence(out, recorder=recorder)


__all__ = ["ExecutionEvidence", "install"]
