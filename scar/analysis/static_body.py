"""Incremental source-only canonical bodies over a saved static program.

Source layers are shared unchanged. Each worker loads one source unit, owns
one sealed lowering session and publishes only body payloads and their ledger.
"""
from __future__ import annotations

import ast
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time


PROFILE = "SCAR_STATIC_BODY_V1"


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _producer():
    package = Path(__file__).resolve().parents[1]
    analysis = package / "analysis"
    # Body caches depend on the source frontend/lowerers, not on CLI/query or
    # unrelated trace/backend edits. Include the complete shared IR/codec basis.
    paths = set((package / "ir").rglob("*.py"))
    paths.update(analysis.glob("source_*lowering.py"))
    paths.update(analysis.glob("source_*validation.py"))
    paths.update(analysis / name for name in (
        "static_body.py", "static_program.py", "static_rules.py", "static_compilation.py",
        "program_lowering.py", "structured_lowering.py", "environment_lowering.py",
        "source_language.py", "source_environment_layout.py", "function_interfaces.py",
        "control_flow_v2.py", "source_semantics_v2.py", "constants_v2.py"))
    paths.add(package / "trace" / "code_snapshot.py")
    files = [(str(path.relative_to(package)), hashlib.sha256(path.read_bytes()).hexdigest())
             for path in sorted(paths)]
    return {"source_sha256": _digest(files), "source_files": len(files), "profile": PROFILE,
            "python": sys.version, "compiler": {"mode": "exec", "flags": 0, "dont_inherit": True, "optimize": 0}}


def _matches(path, selectors):
    return not selectors or any(path == selector if Path(selector).is_absolute()
                               else path.endswith("/" + Path(selector).as_posix()) for selector in selectors)


def _stamp(path):
    info = path.stat()
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _body_key(unit, entry, plan, producer, max_operations):
    return _digest({"producer": producer, "profile": PROFILE, "max_operations": max_operations,
                    "entry_key": entry["entry_key"], "source": entry["source_ref"], "plan": plan,
                    "inputs": {kind: unit["artifacts"].get(kind) for kind in
                               ("source", "lexical", "semantic", "semantics", "control")}})


def _plan_summary(plan):
    return {**{key: plan.get(key) for key in ("schema", "schema_version", "status", "selected_profile",
                                               "automatic_source_profile", "capabilities")},
            "sha256": _digest(plan)}


def _clean_body_files(root, unit):
    retained = {row["artifact"]["path"] for row in unit["bodies"] if "artifact" in row}
    for path in (root / "units" / unit["key"] / "bodies").glob("*.json.gz"):
        if path.relative_to(root).as_posix() not in retained:
            path.unlink()


def _run_unit(unit, catalog, selected, output, max_operations, producer):
    from scar.analysis.static_program import _read_fragment, _write
    from scar.analysis.static_rules import plan_static_entry
    from scar.ir.record_codec import encode, decode
    from scar.ir.v2.common import SourceReference
    from scar.ir.v2.ids import OperationDefinitionID
    from scar.ir.program.source_language import SourceLanguageCapability, encode_language_overlay
    from scar.ir.program.functions import BodyLoweringProfile
    from scar.analysis.source_language import SourceLanguageOptions

    started = time.monotonic()
    root = Path(output)
    entries = catalog["entries"]
    old_rows = {row["entry_key"]: row for row in unit["bodies"]}
    if len(old_rows) != len(unit["bodies"]) or set(old_rows) != {entry["entry_key"] for entry in entries}:
        raise ValueError("body ledger does not exactly cover lexical entries")
    unit["bodies"] = [dict(old_rows[entry["entry_key"]]) for entry in entries]
    selected = set(selected)
    attempted = reused = 0
    session = prepared = compiled = None
    preparation_error = compilation_error = None
    try:
        source = _read_fragment(root, unit["artifacts"]["source"])
        if (source.get("schema") != "scar.static-source-text" or source.get("schema_version") != 1
                or source["path"] != unit["path"] or source["namespace_root"] != unit["namespace_root"]
                or source["decoded_sha256"] != unit["decoded_sha256"]
                or source["raw_sha256"] != unit["raw_sha256"]
                or hashlib.sha256(source["text"].encode()).hexdigest() != unit["decoded_sha256"]):
            raise ValueError("saved source snapshot differs from source unit")
        tree = ast.parse(source["text"], filename=unit["path"])
        plans = [plan_static_entry(tree, entry, path=unit["path"], fingerprint="sha256:" + unit["decoded_sha256"])
                 for entry in entries]
        if any(plan.get("entry_key") != entry["entry_key"] for entry, plan in zip(entries, plans)):
            raise ValueError("static rule plan selected another entry")
        unit["artifacts"]["rules"] = _write(root, "units/" + unit["key"] + "/rules.json.gz", {
            "schema": "scar.static-rule-ledger", "schema_version": 1,
            "source": {"path": unit["path"], "namespace_root": unit["namespace_root"],
                       "fingerprint": "sha256:" + unit["decoded_sha256"],
                       "artifact": unit["artifacts"]["source"]},
            "entry_keys": [entry["entry_key"] for entry in entries], "plans": plans,
            "target_executed": False, "language_semantics_complete": False})
        documents = {}
        if selected:
            try:
                for name in ("semantic", "semantics", "control"):
                    if name not in unit["artifacts"]:
                        raise ValueError("required source fragment unavailable: " + name)
                    documents[name] = _read_fragment(root, unit["artifacts"][name])
            except Exception as error:
                preparation_error = type(error).__name__ + ": " + str(error)
        for entry, row, plan in zip(entries, unit["bodies"], plans):
            # Preserve previous canonical successes even outside this dispatch.
            row["plan"] = _plan_summary(plan)
            if entry["entry_key"] not in selected:
                if "artifact" not in row:
                    unavailable = plan["status"] not in ("READY", "NEEDS_STATIC_COMPILER")
                    row.update(status=plan["status"] if unavailable else "NOT_ATTEMPTED",
                               reason="Static entry adapter/rule unavailable." if unavailable else "Outside this dispatch window.")
                continue
            key = _body_key(unit, entry, plan, producer, max_operations)
            if row.get("cache_key") == key and row.get("status") == "LOWERED_WITH_GAPS" and "artifact" in row:
                if preparation_error is not None:
                    raise ValueError(preparation_error)
                payload = _read_fragment(root, row["artifact"])
                if (payload.get("schema") != "scar.static-body" or payload.get("schema_version") != 1
                        or payload.get("status") != "LOWERED_WITH_GAPS" or payload.get("graph") is None
                        or payload.get("cache_key") != key or payload.get("entry_key") != entry["entry_key"]):
                    raise ValueError("cached body payload differs from original entry/key")
                from scar.ir.program.codec import loads
                loads(json.dumps(payload["graph"]))
                row["reused"] = True
                reused += 1
                continue
            # A changed producer/input cannot retain stale body authority.
            row.pop("artifact", None)
            for name in ("metadata", "gaps", "issue", "construction_operations", "reason"):
                row.pop(name, None)
            row.update(cache_key=key, reused=False, status="NOT_ATTEMPTED")
            payload = {"schema": "scar.static-body", "schema_version": 1, "profile": PROFILE,
                       "entry_key": entry["entry_key"], "cache_key": key, "producer": producer,
                       "plan": plan, "graph": None, "metadata": None, "interface": None,
                       "structured": None, "language": None, "frame": None,
                       "inputs": {name: unit["artifacts"].get(name) for name in
                                  ("source", "semantic", "semantics", "control")},
                       "target_executed": False, "runtime_identity_established": False}
            relative = "units/" + unit["key"] + "/bodies/" + key[:32] + ".json.gz"
            if plan["status"] not in ("READY", "NEEDS_STATIC_COMPILER") or plan.get("selected_profile") is None:
                row.update(status=plan["status"], reason="Static entry rule or adapter is not available.")
                payload.update(status=row["status"], reason=row["reason"])
                row["artifact"] = _write(root, relative, payload)
                continue
            attempted += 1
            try:
                if session is None:
                    if preparation_error is not None:
                        raise ValueError("source-unit preparation failed: " + preparation_error)
                    from scar.ir.v2.codec import semantic_from_dict
                    from scar.ir.semantics_v2 import SourceSemanticsGraph
                    from scar.ir.control_flow_v2 import SourceControlFlowGraph
                    from scar.analysis.program_lowering import PreparedSource, _symbol_tables
                    try:
                        semantic = semantic_from_dict(documents.pop("semantic"))
                        semantics = SourceSemanticsGraph.from_dict(documents.pop("semantics"), semantic=semantic)
                        control = SourceControlFlowGraph.from_dict(documents.pop("control"))
                        prepared = PreparedSource(Path(unit["path"]), Path(unit["namespace_root"]), source["text"],
                                                  semantic, semantics, control, tree, _symbol_tables(source["text"], unit["path"]))
                        session = prepared.seal_for_lowering()
                    except Exception as error:
                        preparation_error = type(error).__name__ + ": " + str(error)
                        raise
                reference = decode(SourceReference, entry["source_ref"])
                ids = entry.get("semantic_definition_ids") or ()
                if len(ids) != 1:
                    raise ValueError("entry requires one exact original semantic definition")
                definition = decode(OperationDefinitionID, ids[0])
                from scar.analysis.static_compilation import compile_source_unit
                if compiled is None:
                    if compilation_error is not None:
                        raise ValueError("source-unit compilation failed: " + compilation_error)
                    try:
                        compiled = compile_source_unit(prepared)
                    except Exception as error:
                        compilation_error = type(error).__name__ + ": " + str(error)
                        raise
                evidence = compiled.for_definition(definition, reference)
                capabilities = tuple(SourceLanguageCapability(value) for value in plan["capabilities"])
                options = SourceLanguageOptions(capabilities=capabilities, code_evidence=evidence)
                lowered = session.lower(entry["name"], source=reference, max_operations=max_operations,
                                        expand_candidates=False, profile=BodyLoweringProfile.STRUCTURED_ENV,
                                        language_options=options)
                row.update(status="LOWERED_WITH_GAPS" if lowered.graph is not None else "UNSUPPORTED",
                           gaps=encode(lowered.metadata.gaps), construction_operations=lowered.operations_emitted)
                if lowered.graph is not None:
                    if lowered.interface is None or lowered.interface.definition != definition:
                        raise ValueError("lowered interface differs from original selected definition")
                    from scar.ir.program.codec import dumps
                    payload.update(graph=json.loads(dumps(lowered.graph)), metadata=encode(lowered.metadata),
                                   interface=encode(lowered.interface), structured=encode(lowered.structured),
                                   language=None if lowered.language is None else encode_language_overlay(lowered.language),
                                   frame=encode(lowered.frame), static_compilation=evidence.to_dict())
                else:
                    payload["metadata"] = encode(lowered.metadata)
            except Exception as error:
                row.update(status="ERROR", issue={"stage": "body", "kind": type(error).__name__, "detail": str(error)})
            payload.update({name: row[name] for name in ("status", "gaps", "construction_operations", "issue") if name in row})
            row["artifact"] = _write(root, relative, payload)
    except Exception as error:
        for row in unit["bodies"]:
            if row["entry_key"] in selected:
                row.update(status="ERROR", issue={"stage": "body-file", "kind": type(error).__name__, "detail": str(error)})
        unit.setdefault("issues", []).append({"stage": "body-file", "kind": type(error).__name__, "detail": str(error)})
    finally:
        # No live owner/graph session escapes this worker/file.
        session = prepared = compiled = None
        _clean_body_files(root, unit)
    unit["body_expansion"] = {"attempted": attempted, "reused": reused, "elapsed_seconds": time.monotonic()-started,
                              "profile": PROFILE, "producer": producer}
    return unit


def expand_static_bodies(directory, *, jobs=4, max_operations=10000, max_bodies=None, files=(), progress=None):
    """Refine only saved source bodies, preserving the complete lexical ledger.

    max_bodies/files constrain this dispatch, never the published denominator.
    Sources, imports and code are not executed. One process owns each source.
    """
    from scar.analysis.static_program import read_static_program, _read_fragment, _json
    if type(jobs) is not int or not 1 <= jobs <= 32:
        raise ValueError("jobs must be in [1,32]")
    if type(max_operations) is not int or max_operations < 1:
        raise ValueError("max_operations must be positive")
    if max_bodies is not None and (type(max_bodies) is not int or max_bodies < 0):
        raise ValueError("max_bodies must be None or a nonnegative integer")
    if isinstance(files, (str, bytes, Path)):
        raise TypeError("files must be a sequence of original file selectors")
    files = tuple(files)
    if any(type(value) is not str or not value for value in files):
        raise ValueError("file selectors must be nonempty strings")
    output = Path(directory).absolute()
    manifest = read_static_program(output, verify=False)
    original = (output / "manifest.json").read_bytes()
    if json.loads(original) != manifest:
        raise ValueError("model manifest changed during read")
    started = time.monotonic()
    producer = _producer()
    temporary = Path(tempfile.mkdtemp(prefix=".static-bodies-", dir=output.parent))
    try:
        shutil.copytree(output, temporary, dirs_exist_ok=True, copy_function=os.link)
        inputs = {d["path"]: _stamp(temporary/d["path"]) for unit in manifest["units"]
                  for kind, d in unit["artifacts"].items()
                  if kind in ("source", "lexical", "semantic", "semantics", "control")}
        tasks = []
        allocated = 0
        for index in sorted(range(len(manifest["units"])), key=lambda i: (manifest["units"][i]["path"], manifest["units"][i]["key"])):
            unit = manifest["units"][index]
            if not _matches(unit["path"], files) or "lexical" not in unit["artifacts"]:
                continue
            catalog = _read_fragment(temporary, unit["artifacts"]["lexical"])
            # Dispatch needs entry records only, not the project's entire AST
            # occurrence/symbol tables retained in the parent's work queue.
            catalog = {"entries": catalog["entries"]}
            selected = []
            for entry in catalog["entries"]:
                if entry.get("lowering_route", {}).get("status") != "READY_TO_ATTEMPT":
                    continue
                if max_bodies is None or allocated < max_bodies:
                    selected.append(entry["entry_key"])
                    allocated += 1
            tasks.append((index, unit, catalog, selected))
        if files and not any(_matches(unit["path"], files) for unit in manifest["units"]):
            raise ValueError("no original source unit matches the file selectors")
        selected_counts = {index: len(selected) for index, _, _, selected in tasks}
        completed = 0
        def accept(index, unit):
            nonlocal completed
            manifest["units"][index] = unit
            completed += selected_counts[index]
            if progress is not None:
                progress(completed, allocated, unit)
        if jobs == 1:
            for index, unit, catalog, selected in tasks:
                accept(index, _run_unit(unit, catalog, selected, str(temporary), max_operations, producer))
        elif tasks:
            with ProcessPoolExecutor(max_workers=jobs, mp_context=multiprocessing.get_context("spawn")) as pool:
                futures = {pool.submit(_run_unit, unit, catalog, selected, str(temporary), max_operations, producer): (index, unit, selected)
                           for index, unit, catalog, selected in tasks}
                for future in as_completed(futures):
                    index, unit, selected = futures[future]
                    try:
                        unit = future.result()
                    except Exception as error:
                        # Do not lose either the source unit or its ledger on a
                        # process-level failure. Unreturned writes are removed.
                        old = {row["artifact"]["path"] for row in unit["bodies"] if "artifact" in row}
                        prefix = temporary / "units" / unit["key"] / "bodies"
                        for path in prefix.glob("*.gz") if prefix.exists() else ():
                            if str(path.relative_to(temporary)) not in old:
                                path.unlink()
                        for row in unit["bodies"]:
                            if "artifact" in row:
                                path = temporary / row["artifact"]["path"]
                                if not path.exists():
                                    os.link(output / row["artifact"]["path"], path)
                            if row["entry_key"] in selected:
                                row.update(status="ERROR", issue={"stage": "worker", "kind": type(error).__name__, "detail": str(error)})
                        unit.setdefault("issues", []).append({"stage": "body-worker", "kind": type(error).__name__, "detail": str(error)})
                    accept(index, unit)
        if any(_stamp(temporary/path) != stamp for path, stamp in inputs.items()):
            raise ValueError("shared source fragment changed during body expansion")
        if _producer() != producer:
            raise ValueError("analyzer source changed during body expansion")
        counts = Counter(row["status"] for unit in manifest["units"] for row in unit["bodies"])
        manifest["summary"]["body_statuses"] = dict(counts)
        manifest["summary"]["canonical_body_operations"] = sum(
            row.get("construction_operations", 0) for unit in manifest["units"]
            for row in unit["bodies"] if row["status"] == "LOWERED_WITH_GAPS")
        manifest["completion"].update(body_expansion_complete=False, whole_program_model_complete=False)
        manifest["completion"]["static_rule_ledgers_present"] = all("rules" in unit["artifacts"] for unit in manifest["units"])
        manifest["body_expansion"] = {"profile": PROFILE, "producer": producer, "allocated_bodies": allocated,
            "jobs": jobs, "max_operations": max_operations, "max_bodies": max_bodies, "files": list(files),
            "lexical_entries": sum(len(u["bodies"]) for u in manifest["units"]), "source_graphs_rebuilt": 0,
            "attempted_bodies": sum(manifest["units"][i].get("body_expansion", {}).get("attempted", 0) for i in selected_counts),
            "reused_bodies": sum(manifest["units"][i].get("body_expansion", {}).get("reused", 0) for i in selected_counts),
            "elapsed_seconds": time.monotonic()-started, "runtime_evidence_required": False,
            "qualification": "Static source construction only; failed/unsupported and undispatched entries remain in the full ledger."}
        manifest["storage"] = {"files": len(list(temporary.rglob("*.gz"))),
            "compressed_bytes": sum(path.stat().st_size for path in temporary.rglob("*.gz"))}
        (temporary/"manifest.json").unlink()
        (temporary/"manifest.json").write_bytes(_json(manifest))
        read_static_program(temporary, verify=False)
        read_static_program(output, verify=False)
        if (output/"manifest.json").read_bytes() != original:
            raise ValueError("current model changed during body expansion")
        previous = Path(tempfile.mkdtemp(prefix=".static-replacing-", dir=output.parent))
        previous.rmdir()
        output.rename(previous)
        try:
            temporary.rename(output)
        except BaseException:
            previous.rename(output)
            raise
        shutil.rmtree(previous)
        return manifest
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
