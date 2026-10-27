#!/usr/bin/env python3
"""One archived CodeType check for the weak-identity code-key cache."""
from __future__ import annotations

import argparse
import hashlib
import json
import marshal
from pathlib import Path
import platform
import sys
from time import perf_counter
from types import CodeType

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scar.trace import code_snapshot


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--module-key", default=None)
    parser.add_argument("--iterations", type=int, default=5000)
    args = parser.parse_args()

    manifest_path = args.manifest.resolve(strict=True)
    manifest = json.loads(manifest_path.read_bytes())
    modules = manifest["modules"]
    module_key = args.module_key or sorted(modules)[0]
    entry = modules[module_key]
    artifact_path = (manifest_path.parent / entry["artifact"]["path"]).resolve(strict=True)
    raw = artifact_path.read_bytes()
    stored_sha256 = hashlib.sha256(raw).hexdigest()
    if len(raw) != entry["artifact"]["bytes"] or stored_sha256 != entry["artifact"]["sha256"]:
        raise RuntimeError("archived marshal receipt mismatch")
    code = marshal.loads(raw)
    if type(code) is not CodeType:
        raise RuntimeError("archived marshal root is not an exact CodeType")

    descriptor_first = code_snapshot.describe_code(code)
    descriptor_second = code_snapshot.describe_code(code)
    key = code_snapshot.code_key(code)
    expected_key = entry["module_descriptor"]["key"]
    if not (key == descriptor_first["key"] == descriptor_second["key"] == expected_key):
        raise RuntimeError("key-only and full descriptor keys differ")
    if descriptor_first is descriptor_second or descriptor_first["parameters"] is descriptor_second["parameters"]:
        raise RuntimeError("describe_code stopped returning fresh mutable containers")
    cached = code_snapshot._KEY_CACHE[id(code)]
    if cached.reference() is not code or type(cached.key) is not str:
        raise RuntimeError("key cache lacks weak identity or immutable key")

    changed_filename = code.replace(co_filename=code.co_filename + ".cache-probe")
    if id(changed_filename) == id(code):
        raise RuntimeError("CodeType.replace unexpectedly preserved object identity")
    changed_key = code_snapshot.code_key(changed_filename)
    if changed_key == key or code_snapshot._KEY_CACHE[id(changed_filename)].reference() is not changed_filename:
        raise RuntimeError("distinct filename CodeType did not get its own cached key")

    size_before_unsupported = len(code_snapshot._KEY_CACHE)
    unsupported = code.replace(co_consts=(object(),))
    try:
        code_snapshot.code_key(unsupported)
    except ValueError as error:
        unsupported_error = str(error)
    else:
        raise RuntimeError("unsupported constant was accepted")
    if id(unsupported) in code_snapshot._KEY_CACHE or len(code_snapshot._KEY_CACHE) != size_before_unsupported:
        raise RuntimeError("failed descriptor was added to the key cache")

    first_site = code_snapshot.site(code, 0)
    second_site = code_snapshot.site(code, 0)
    if first_site != second_site or first_site["code"] != expected_key:
        raise RuntimeError("site query changed across key-only lookup")

    iterations = args.iterations
    if type(iterations) is not int or iterations < 1:
        raise ValueError("iterations must be a positive integer")
    started = perf_counter()
    for _ in range(iterations):
        code_snapshot.code_key(code)
    key_lookup_seconds = perf_counter() - started
    started = perf_counter()
    for _ in range(iterations):
        code_snapshot.describe_code(code)["key"]
    descriptor_lookup_seconds = perf_counter() - started

    print(json.dumps({
        "status": "PASS",
        "runtime": sys.version,
        "platform": platform.platform(),
        "source_commit": "4f23a6d687919853d8c91f405859f473e6e0e6b9",
        "manifest": str(manifest_path),
        "manifest_module_key": module_key,
        "marshal_artifact": str(artifact_path),
        "marshal_bytes": len(raw),
        "marshal_sha256": stored_sha256,
        "descriptor_key": expected_key,
        "same_object_repeated_key": key,
        "distinct_filename_object_id": id(changed_filename),
        "distinct_filename_key": changed_key,
        "unsupported_constant_rejected": unsupported_error,
        "unsupported_constant_cached": False,
        "site_result": first_site,
        "iterations": iterations,
        "key_only_seconds": key_lookup_seconds,
        "full_descriptor_seconds": descriptor_lookup_seconds,
        "key_cache_entries_after_probe": len(code_snapshot._KEY_CACHE),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
