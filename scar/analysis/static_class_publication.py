"""Atomically publish class interfaces beside original current-model graphs."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile


def _producer():
    from scar.analysis.static_body import _producer as shared_producer
    analysis = Path(__file__).parent
    return {"shared": shared_producer(), "class_sources": {
        name: hashlib.sha256((analysis / name).read_bytes()).hexdigest()
        for name in ("static_class_publication.py", "static_class_links.py", "static_class_builder.py",
                     "static_calls.py", "static_function_environment.py", "function_interfaces.py", "source_layers.py")}}


def link_static_class_program(directory, *, budget=None, progress=None):
    """Attach conditional parent/provider/suite interfaces, preserving calls.

    Only owned class-index files and the manifest change. Original source/body
    fragments are hard-linked, checked by their byte stamps, and never rebuilt.
    Missing declarations/interfaces remain exact scope frontiers. Bad original
    receipts or invalid graph records abort before current-model publication.
    """
    from scar.analysis.static_program import (_artifacts, _discard_static_classes,
        _json, read_static_program)
    from scar.analysis.static_body import _stamp
    from scar.analysis.static_calls import StaticCallBudget
    from scar.analysis.static_class_links import build_static_class_links
    from scar.analysis.static_jobs import StaticLinkTask

    producer = _producer()
    output = Path(directory).absolute()
    manifest = read_static_program(output, verify=False)
    original = (output / "manifest.json").read_bytes()
    if json.loads(original) != manifest:
        raise ValueError("current manifest changed during class publication read")
    budget = budget or StaticCallBudget()
    task = StaticLinkTask(output, input_manifest_sha256=hashlib.sha256(original).hexdigest(),
                          budget=budget, family="classes")

    def report(event):
        task.activity(event)
        if progress is not None:
            progress(event)

    temporary = Path(tempfile.mkdtemp(prefix=".static-classes-", dir=output.parent))
    try:
        task.activity({"stage": "STAGING", "directory": str(temporary)})
        shutil.copytree(output, temporary, dirs_exist_ok=True, copy_function=os.link)
        _discard_static_classes(temporary, manifest)
        shared = {descriptor["path"]: _stamp(temporary / descriptor["path"])
                  for descriptor in _artifacts(manifest)}
        (temporary / "manifest.json").unlink()
        (temporary / "manifest.json").write_bytes(_json(manifest))
        input_hash = hashlib.sha256((temporary / "manifest.json").read_bytes()).hexdigest()
        result = build_static_class_links(temporary, temporary / "indexes" / "classes",
            logical_root=output, expected_manifest_sha256=input_hash, budget=budget,
            progress=report, activity=task.activity)
        if _producer() != producer:
            raise ValueError("analyzer source changed during static class linking")
        manifest["static_classes"] = {**result, "producer": producer, "artifacts": [
            {**descriptor, "path": "indexes/classes/" + descriptor["path"]}
            for descriptor in result["artifacts"]]}
        if any(_stamp(temporary / path) != stamp for path, stamp in shared.items()):
            raise ValueError("an original graph/index artifact changed during class linking")
        manifest.setdefault("completion", {}).update(static_class_links_present=True,
            whole_program_model_complete=False)
        manifest["storage"] = {"files": len(list(temporary.rglob("*.gz"))),
            "compressed_bytes": sum(path.stat().st_size for path in temporary.rglob("*.gz"))}
        task.activity({"stage": "PUBLICATION", "counts": result["counts"],
                       "enumeration_complete": result["scope"]["enumeration_complete"]})
        (temporary / "manifest.json").write_bytes(_json(manifest))
        read_static_program(temporary, verify=False)
        read_static_program(output, verify=False)
        if (output / "manifest.json").read_bytes() != original:
            raise ValueError("current model changed during static class linking")
        previous = Path(tempfile.mkdtemp(prefix=".static-replacing-", dir=output.parent))
        previous.rmdir()
        output.rename(previous)
        try:
            temporary.rename(output)
        except BaseException:
            previous.rename(output)
            raise
        shutil.rmtree(previous)
        task.published(manifest, hashlib.sha256((output / "manifest.json").read_bytes()).hexdigest())
        return manifest
    except BaseException as error:
        shutil.rmtree(temporary, ignore_errors=True)
        task.failed(error)
        raise
