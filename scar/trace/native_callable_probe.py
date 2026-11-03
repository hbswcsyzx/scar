"""Explicit, isolated build/load of SCAR's optional CPython callable probe.

No import compiles code. The returned native addresses describe the current
process's loaded instance, never an identity across runs or an effect summary.
Unavailable C fields have no key; a present object field containing None is
the actual Py_None object and must still pass through the reference recorder.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import shlex
import struct
import subprocess
import sys
import sysconfig
from types import ModuleType


_MODULE = '_native_callable_probe'


def _check_abi() -> None:
    if (sys.implementation.name != 'cpython' or sys.version_info[:3] != (3, 14, 7)
            or sys.version_info.releaselevel != 'final' or sys.platform != 'linux'
            or platform.machine() != 'x86_64' or struct.calcsize('P') != 8
            or sysconfig.get_config_var('Py_GIL_DISABLED')
            or not sys._is_gil_enabled()):
        raise RuntimeError('native callable probe requires CPython 3.14.7 GIL Linux x86-64')


def build_probe(out_dir: str | Path) -> Path:
    """Compile into a new dedicated directory, preserving source/build receipt.

    Existing directories are rejected. No environment package is installed,
    changed or imported by the compiler invocation. A failed build retains its
    source, command, return code and compiler output for inspection.
    """
    _check_abi()
    output = Path(out_dir).absolute()
    source = Path(__file__).with_name('_native_callable_probe.c').read_bytes()
    suffix = sysconfig.get_config_var('EXT_SUFFIX')
    include = sysconfig.get_config_var('INCLUDEPY')
    linker = sysconfig.get_config_var('LDSHARED')
    if not all(type(value) is str and value for value in (suffix, include, linker)):
        raise RuntimeError('CPython extension build configuration is incomplete')
    output.mkdir(parents=True, exist_ok=False)
    copied = output / '_native_callable_probe.c'
    copied.write_bytes(source)
    binary = output / (_MODULE + suffix)
    command = [*shlex.split(linker), *shlex.split(sysconfig.get_config_var('CFLAGS') or ''),
        '-std=c11', '-Wextra', '-Werror=implicit-function-declaration', '-I', include,
        str(copied), '-o', str(binary)]
    receipt = {'schema': 'scar.native-callable-probe-build', 'version': 1,
        'python': sys.version, 'soabi': sysconfig.get_config_var('SOABI'),
        'source_sha256': hashlib.sha256(source).hexdigest(), 'source': copied.name,
        'binary': binary.name, 'command': command, 'address_scope': 'CURRENT_PROCESS_LOADED_INSTANCE'}
    receipt_path = output / 'build.json'
    receipt_path.write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    receipt.update(returncode=completed.returncode, stdout=completed.stdout, stderr=completed.stderr)
    if completed.returncode == 0:
        receipt['binary_sha256'] = hashlib.sha256(binary.read_bytes()).hexdigest()
    receipt_path.write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    if completed.returncode:
        raise RuntimeError('native callable probe compilation failed; see ' + str(receipt_path))
    return binary


def load_probe(path: str | Path) -> ModuleType:
    """Load an explicitly chosen binary without compiling or installing it."""
    _check_abi()
    binary = Path(path).absolute()
    if not binary.is_file() or not binary.name.endswith(sysconfig.get_config_var('EXT_SUFFIX')):
        raise ValueError('native callable probe requires an existing current-ABI extension file')
    spec = importlib.util.spec_from_file_location(_MODULE, binary)
    if spec is None or spec.loader is None:
        raise ImportError('cannot create native callable probe extension loader')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


__all__ = ['build_probe', 'load_probe']
