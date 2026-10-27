"""Source-root driven static graph construction. Never executes target code.

The source catalog is an index over existing source/semantic/program IDs, not
a second program graph. Each file owns shared semantic, computational and CFG
fragments. Runtime collectors and captured-code admission are not used.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
import gzip
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time


SCHEMA = "scar.static-program"
VERSION = 1


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf8") + b"\n"


def _write(root, relative, value):
    payload = _json(value)
    data = gzip.compress(payload, compresslevel=3, mtime=0)
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    # Refinements may share unchanged fragments by hard link. Replace the
    # directory entry, never modify a shared inode belonging to the old model.
    if path.exists():
        path.unlink()
    path.write_bytes(data)
    return {"path": relative, "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data), "decoded_bytes": len(payload),
            "decoded_sha256": hashlib.sha256(payload).hexdigest()}


def _issue(stage, error):
    return {"stage": stage, "kind": type(error).__name__, "detail": str(error)}


def _artifacts(manifest):
    yield from manifest.get("artifacts", {}).values()
    yield from manifest.get("static_calls", {}).get("artifacts", ())
    for unit in manifest["units"]:
        yield from unit["artifacts"].values()
        for body in unit["bodies"]:
            if "artifact" in body:
                yield body["artifact"]


def _discard_static_calls(root, manifest):
    """Drop derived routes before replacing any original endpoint artifact."""
    calls = manifest.pop("static_calls", None)
    if calls is None:
        return
    for descriptor in calls.get("artifacts", ()):
        relative = Path(descriptor["path"])
        if relative.is_absolute() or ".." in relative.parts or relative.parts[:2] != ("indexes", "calls"):
            raise ValueError("static call artifact must remain in its owned index directory")
        (root / relative).unlink()
    directory = root / "indexes" / "calls"
    if directory.exists():
        if any(path.is_file() or path.is_symlink() for path in directory.rglob("*")):
            raise ValueError("static call index contains an unowned file")
        shutil.rmtree(directory)
    manifest["completion"]["static_call_links_present"] = False


def link_static_program(directory, *, budget=None):
    """Publish qualified static call relations alongside the original graphs."""
    from scar.analysis.static_calls import build_static_call_links
    from scar.analysis.static_body import _stamp, _producer
    def call_producer():
        analysis = Path(__file__).parent
        return {"shared": _producer(), "call_sources": {
            name: hashlib.sha256((analysis / name).read_bytes()).hexdigest()
            for name in ("static_calls.py", "function_binding.py", "function_interfaces.py", "source_layers.py")}}
    producer = call_producer()
    output = Path(directory).absolute()
    manifest = read_static_program(output, verify=False)
    original = (output / "manifest.json").read_bytes()
    if json.loads(original) != manifest:
        raise ValueError("current manifest changed during static call read")
    temporary = Path(tempfile.mkdtemp(prefix=".static-calls-", dir=output.parent))
    try:
        shutil.copytree(output, temporary, dirs_exist_ok=True, copy_function=os.link)
        _discard_static_calls(temporary, manifest)
        shared = {d["path"]: _stamp(temporary / d["path"]) for d in _artifacts(manifest)}
        (temporary / "manifest.json").unlink()
        (temporary / "manifest.json").write_bytes(_json(manifest))
        input_hash = hashlib.sha256((temporary / "manifest.json").read_bytes()).hexdigest()
        result = build_static_call_links(temporary, temporary / "indexes" / "calls",
            expected_manifest_sha256=input_hash, budget=budget, logical_root=output)
        # Each relation keeps its input namespaces and receipts. The immutable
        # source-basis receipt avoids making the manifest refer to its own SHA.
        if call_producer() != producer:
            raise ValueError("analyzer source changed during static call linking")
        manifest["static_calls"] = {**result, "producer": producer, "artifacts": [
            {**descriptor, "path": "indexes/calls/" + descriptor["path"]}
            for descriptor in result["artifacts"]]}
        if any(_stamp(temporary / path) != stamp for path, stamp in shared.items()):
            raise ValueError("an original source/body artifact changed during call linking")
        manifest["completion"]["static_call_links_present"] = True
        manifest["completion"]["whole_program_model_complete"] = False
        manifest["storage"] = {"files": len(list(temporary.rglob("*.gz"))),
            "compressed_bytes": sum(path.stat().st_size for path in temporary.rglob("*.gz"))}
        (temporary / "manifest.json").write_bytes(_json(manifest))
        read_static_program(temporary, verify=False)
        read_static_program(output, verify=False)
        if (output / "manifest.json").read_bytes() != original:
            raise ValueError("current model changed during static call linking")
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


def read_static_program(directory, *, verify=True):
    """Read an owned model and check its exact fragment set and byte receipts."""
    root = Path(directory).absolute()
    if root.is_symlink() or root.resolve() != root:
        raise ValueError("model directory must not traverse symlinks")
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest.get("schema") != SCHEMA or manifest.get("schema_version") != VERSION:
        raise ValueError("unsupported static model")
    expected = {"manifest.json"}
    for descriptor in _artifacts(manifest):
        relative = Path(descriptor["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("fragment escapes model")
        expected.add(relative.as_posix())
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise ValueError("missing or symlinked fragment: " + str(relative))
        if verify:
            payload = path.read_bytes()
            if (len(payload) != descriptor["bytes"] or
                    hashlib.sha256(payload).hexdigest() != descriptor["sha256"]):
                raise ValueError("fragment receipt differs: " + str(relative))
            decoded = gzip.decompress(payload)
            if (len(decoded) != descriptor["decoded_bytes"] or
                    hashlib.sha256(decoded).hexdigest() != descriptor["decoded_sha256"]):
                raise ValueError("decoded fragment receipt differs: " + str(relative))
            json.loads(decoded)
    actual = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError("symlinks are not permitted in model outputs")
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
    if actual != expected:
        raise ValueError("output contains unowned or missing files")
    return manifest


def _read_fragment(root, descriptor):
    data = (root / descriptor["path"]).read_bytes()
    if len(data) != descriptor["bytes"] or hashlib.sha256(data).hexdigest() != descriptor["sha256"]:
        raise ValueError("stored fragment changed")
    raw = gzip.decompress(data)
    if len(raw) != descriptor["decoded_bytes"] or hashlib.sha256(raw).hexdigest() != descriptor["decoded_sha256"]:
        raise ValueError("decoded fragment changed")
    return json.loads(raw)


def _lowering_route(entry):
    if entry["kind"] == "CLASS" and entry["source_ref"] is not None and len(entry.get("semantic_definition_ids") or ()) == 1:
        return {"status": "READY_TO_ATTEMPT", "body_supported": None,
                "adapter": "scar.analysis.source_class_lowering.lower_class_entry",
                "profile": "STATIC_CLASS_FRAME_WITH_REQUIRED_BODY_EXPANSION", "runtime_witness_required": False,
                "required_inputs": ["original_class_definition", "prepared_source_layers", "static_class_code_layout"],
                "qualification": "Class namespace/cell/frame boundary with required source expansion, not complete class-body modeling."}
    if entry["kind"] == "MODULE" and len(entry.get("semantic_definition_ids") or ()) == 1:
        return {"status": "READY_TO_ATTEMPT", "body_supported": None,
                "adapter": "scar.analysis.source_module_lowering.lower_module_entry",
                "profile": "STRUCTURED_MAPPING_BODY_314_V1", "runtime_witness_required": False,
                "required_inputs": ["original_module_initializer", "prepared_source_layers", "static_exec_compiler_root"],
                "qualification": "Static mapping prefix and exact residual source; not whole-body support."}
    if entry["kind"] == "FUNCTION" and entry["source_ref"] is not None and not entry.get("generator"):
        return {"status": "READY_TO_ATTEMPT", "body_supported": None,
                "adapter": "scar.analysis.program_lowering.PreparedSource.lower",
                "profile": "STRUCTURED_ENV_V1", "runtime_witness_required": False,
                "required_inputs": ["exact_source_reference", "prepared_source_layers"],
                "qualification": "An available entry route, not a claim that all body constructs are supported."}
    return {"status": "SOURCE_ENTRY_ADAPTER_NOT_CONNECTED", "body_supported": None,
            "runtime_witness_required": False,
            "reason": "The current source-only canonical driver has no complete entry route for this kind/phase."}


def refine_static_program(directory, *, refresh_lexical=True):
    """Refine lexical scopes/import relations using retained source snapshots.

    Source/semantic/CFG fragments remain byte-identical and are not rebuilt.
    Only new catalog facts and graph references are published in the same
    current directory. This operation executes no target and creates no calls.
    """
    from scar.analysis.static_lexical import inspect_lexical
    from scar.analysis.static_imports import build_import_index
    output = Path(directory).absolute()
    manifest = read_static_program(output, verify=False)
    prior = hashlib.sha256((output / "manifest.json").read_bytes()).hexdigest()
    started = time.monotonic()
    temporary = Path(tempfile.mkdtemp(prefix=".static-refining-", dir=output.parent))
    try:
        shutil.copytree(output, temporary, dirs_exist_ok=True, copy_function=os.link)
        _discard_static_calls(temporary, manifest)
        syntax, kinds, scope_counts, routes = Counter(), Counter(), Counter(), Counter()
        old_graphs = {d["path"]: d["sha256"] for u in manifest["units"]
                      for kind, d in u["artifacts"].items() if kind not in ("lexical", "source")}
        for unit in manifest["units"] if refresh_lexical else ():
            if "lexical" not in unit["artifacts"]:
                continue
            source = _read_fragment(temporary, unit["artifacts"]["source"])
            if hashlib.sha256(source["text"].encode()).hexdigest() != unit["decoded_sha256"]:
                raise ValueError("source snapshot differs from source unit")
            previous = _read_fragment(temporary, unit["artifacts"]["lexical"])
            old_entries = {e["entry_key"]: e for e in previous["entries"]}
            semantic=None
            if "semantic" in unit["artifacts"] and any(e["kind"]=="CLASS" for e in previous["entries"]):
                from scar.ir.v2.codec import semantic_from_dict
                semantic=semantic_from_dict(_read_fragment(temporary,unit["artifacts"]["semantic"]))
            catalog = inspect_lexical(ast.parse(source["text"], filename=unit["path"], type_comments=True),
                                      path=unit["path"], namespace_root=unit["namespace_root"],
                                      fingerprint="sha256:" + unit["decoded_sha256"],
                                      source_text=source["text"],semantic=semantic)
            for entry in catalog["entries"]:
                old = old_entries.get(entry["entry_key"])
                if semantic is None and old is not None and old["source_ref"] == entry["source_ref"]:
                    for field in ("semantic_definition_ids", "semantic_source_candidates", "catalog_status"):
                        entry[field] = old[field]
                entry["lowering_route"] = _lowering_route(entry)
                routes[entry["lowering_route"]["status"]] += 1
                kinds[entry["kind"]] += 1
            unit["module_initializer_ids"] = [identity for entry in catalog["entries"]
                                               if entry["kind"] == "MODULE"
                                               for identity in entry["semantic_definition_ids"] or ()]
            descriptor = unit["artifacts"]["lexical"]
            unit["artifacts"]["lexical"] = _write(temporary, descriptor["path"], catalog)
            unit["lexical_summary"] = catalog["summary"]
            unit["lexical_completion"] = catalog.get("completion", {})
            syntax.update(catalog["syntax"])
            scope_counts.update(table["kind"] for table in catalog["symbol_tables"])

        def load_lexical(unit):
            if "lexical" not in unit["artifacts"]:
                return {"imports": []}
            return _read_fragment(temporary, unit["artifacts"]["lexical"])

        imports = build_import_index(manifest["units"], load_lexical)
        manifest.setdefault("artifacts", {})["imports"] = _write(temporary, "indexes/imports.json.gz", imports)
        if refresh_lexical:
            ledger = {"schema": "scar.static-language-inventory", "schema_version": 1,
                      "syntax_occurrences": dict(sorted(syntax.items())), "entry_kinds": dict(kinds),
                      "compiler_scope_kinds": dict(scope_counts), "entry_routes": dict(routes),
                      "language_rules_complete": False,
                      "qualification": "Complete syntax inventory and explicit entry dispatch routes; full per-protocol canonical rule binding remains open."}
            manifest["artifacts"]["language"] = _write(temporary, "indexes/language.json.gz", ledger)
        else:
            ledger = _read_fragment(temporary, manifest["artifacts"]["language"])
            routes.update(ledger["entry_routes"])
            scope_counts.update(ledger["compiler_scope_kinds"])
        for property in ("explicit_ast_catalog_complete", "compiler_symbol_tables_cataloged"):
            manifest["completion"][property] = (
                len(manifest["units"]) == manifest["summary"]["files"] and
                all(u.get("lexical_completion", {}).get(property, False) for u in manifest["units"]))
        manifest["completion"].update(implicit_scope_semantics_complete=False,
                                       language_ledger_complete=False, body_expansion_complete=False)
        manifest["catalog_refinement"] = {"analyzer_seconds": time.monotonic() - started,
                                          "updated_stage": "lexical+imports" if refresh_lexical else "imports",
                                          "source_graphs_rebuilt": 0, "unchanged_graph_fragments": len(old_graphs),
                                          "entry_routes": dict(routes), "import_summary": imports.get("summary", imports.get("counts")),
                                          "compiler_scope_kinds": dict(scope_counts)}
        manifest["storage"] = {"files": len(list(temporary.rglob("*.gz"))),
                               "compressed_bytes": sum(p.stat().st_size for p in temporary.rglob("*.gz"))}
        (temporary / "manifest.json").unlink()
        (temporary / "manifest.json").write_bytes(_json(manifest))
        read_static_program(temporary, verify=False)
        # Protect an unrelated concurrent publisher/user edit.
        read_static_program(output, verify=False)
        if hashlib.sha256((output / "manifest.json").read_bytes()).hexdigest() != prior:
            raise ValueError("current model changed during static refinement")
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


def _build_file(source, output, phase, max_body_operations):
    """One process owns a source unit; no live target objects cross workers."""
    from scar.analysis.static_lexical import inspect_lexical
    from scar.ir.record_codec import encode
    from scar.ir.frontend_v2 import build_semantic_source_texts

    started = time.monotonic()
    key = hashlib.sha256(_json([source.namespace_root, source.path,
                                source.decoded_sha256])).hexdigest()[:24]
    root = Path(output)
    prefix = "units/" + key + "/"
    result = {"key": key, "path": source.path, "namespace_root": source.namespace_root,
              "module_names": list(source.module_names), "raw_sha256": source.raw_sha256,
              "module_mappings": [{"name": m.name, "source_root": m.source_root}
                                  for m in source.module_mappings],
              "decoded_sha256": source.decoded_sha256, "encoding": source.encoding,
              "source_bytes": source.size_bytes, "artifacts": {}, "issues": [],
              "counts": {}, "bodies": [], "status": "SOURCE_ONLY"}
    result["artifacts"]["source"] = _write(root, prefix + "source.json.gz", {
        "schema": "scar.static-source-text", "schema_version": 1,
        "path": source.path, "namespace_root": source.namespace_root,
        "raw_sha256": source.raw_sha256, "decoded_sha256": source.decoded_sha256,
        "encoding": source.encoding, "text": source.text})
    try:
        tree = ast.parse(source.text, filename=source.path, type_comments=True)
    except (SyntaxError, ValueError, RecursionError) as error:
        result["issues"].append(_issue("syntax", error))
        result["status"] = "SYNTAX_ERROR"
        result["analysis_seconds"] = time.monotonic() - started
        return result

    semantic = None
    if phase != "sources" and Path(source.path).suffix == ".py":
        try:
            front = build_semantic_source_texts(
                [source.path], source.namespace_root, sources={source.path: source.text},
                root_is_package=(Path(source.namespace_root) / "__init__.py").is_file())
            semantic = front.graph
            result["artifacts"]["semantic"] = _write(root, prefix + "semantic.json.gz", semantic.to_dict())
            result["counts"].update(source_atoms=len(semantic.source_atoms),
                                    operations=len(semantic.definitions),
                                    value_slots=len(semantic.slots),
                                    semantic_edges=len(semantic.edges),
                                    opaque_operations=front.coverage["opaque_operations"])
            result["status"] = "SEMANTIC_GRAPH"
        except (ValueError, TypeError, KeyError, SyntaxError, RecursionError) as error:
            result["issues"].append(_issue("semantic", error))

    catalog = inspect_lexical(tree, path=source.path, namespace_root=source.namespace_root,
                              fingerprint="sha256:" + source.decoded_sha256,
                              semantic=semantic, source_text=source.text)
    result["artifacts"]["lexical"] = _write(root, prefix + "lexical.json.gz", catalog)
    result["counts"]["lexical_entries"] = len(catalog["entries"])
    result["counts"]["ast_nodes"] = sum(1 for _ in ast.walk(tree))
    result["lexical_summary"] = catalog["summary"]
    result["bodies"] = [
        {"entry_key": entry["entry_key"], "kind": entry["kind"], "name": entry["qualname"],
         "definitions": entry["semantic_definition_ids"], "source": entry["source_ref"],
         "status": "NOT_ATTEMPTED" if phase != "bodies" else "UNEXPANDED_ENTRY",
         "reason": "Canonical body lowering not requested." if phase != "bodies" else
                   "Source-only canonical adapter for this entry kind is not yet connected."}
        for entry in catalog["entries"]]

    semantics = control = None
    if semantic is not None:
        try:
            from scar.analysis.source_semantics_v2 import extract_source_semantics
            semantics = extract_source_semantics(semantic, sources={source.path: source.text})
            result["artifacts"]["semantics"] = _write(root, prefix + "semantics.json.gz", semantics.to_dict())
            result["counts"].update(computational_operations=len(semantics.operations),
                                    static_values=len(semantics.values),
                                    binding_uses=len(semantics.uses),
                                    semantic_gaps=len(semantics.gaps))
        except (ValueError, TypeError, KeyError, SyntaxError, RecursionError) as error:
            result["issues"].append(_issue("semantics", error))
    if semantics is not None:
        try:
            # These layers were just constructed from this exact source in an
            # owned worker. Reuse the normal builder without a redundant AST
            # replay of an untrusted externally supplied semantics document.
            from scar.analysis.control_flow_v2 import _Builder
            from scar.ir.control_flow_v2 import ControlFlowBudget
            from scar.ir.v2.common import SourceVersion
            control = _Builder(semantic, semantics, {source.path: source.text},
                               {source.path: SourceVersion(source.path, "sha256:" + source.decoded_sha256)},
                               ControlFlowBudget()).build()
            result["artifacts"]["control"] = _write(root, prefix + "control.json.gz", control.to_dict())
            result["counts"].update(control_nodes=len(control.nodes), control_edges=len(control.edges),
                                    control_gaps=len(control.gaps))
        except (ValueError, TypeError, KeyError, SyntaxError, RecursionError) as error:
            result["issues"].append(_issue("control", error))
        try:
            from scar.analysis.constants_v2 import evaluate_constants
            constants = evaluate_constants(semantics)
            # Encode the actually produced records; to_dict() independently
            # re-evaluates the report and would repeat the entire analysis.
            facts = encode(constants._record())
            result["artifacts"]["constants"] = _write(root, prefix + "constants.json.gz", facts)
            result["counts"]["constant_facts"] = sum(f.status.value == "CONSTANT" for f in constants.facts.values())
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as error:
            result["issues"].append(_issue("constants", error))
    if semantic is not None and semantics is not None and control is not None:
        result["status"] = "SOURCE_LAYERS_WITH_GAPS"
    result["analysis_seconds"] = time.monotonic() - started
    return result


def _failed_file(source, output, error):
    key = hashlib.sha256(_json([source.namespace_root, source.path,
                                source.decoded_sha256])).hexdigest()[:24]
    fragment = Path(output) / "units" / key
    if fragment.exists():
        shutil.rmtree(fragment)
    descriptor = _write(Path(output), "units/" + key + "/source.json.gz", {
        "schema": "scar.static-source-text", "schema_version": 1,
        "path": source.path, "namespace_root": source.namespace_root,
        "raw_sha256": source.raw_sha256, "decoded_sha256": source.decoded_sha256,
        "encoding": source.encoding, "text": source.text})
    return {"key": key, **source.to_manifest_dict(), "source_bytes": source.size_bytes,
            "artifacts": {"source": descriptor}, "issues": [_issue("file", error)],
            "counts": {}, "bodies": [], "status": "ERROR"}


def _run_file(source, output, phase, max_body_operations):
    try:
        return _build_file(source, output, phase, max_body_operations)
    except Exception as error:
        return _failed_file(source, output, error)


def build_static_program(project_root, *, source_roots=(), out="artifacts/current/static",
                         jobs=4, phase="graph", max_files=4096, max_bytes=64_000_000,
                         max_directories=16384, max_body_operations=10000, progress=None):
    """Publish the current source model; replace only an owned prior output."""
    from scar.analysis.static_sources import collect_sources
    if type(jobs) is not int or not 1 <= jobs <= 32:
        raise ValueError("jobs must be in [1, 32]")
    if phase not in ("sources", "graph", "bodies"):
        raise ValueError("unsupported static phase")
    output = Path(out).absolute()
    if output.is_symlink() or output.resolve() != output:
        raise ValueError("output cannot traverse a symlink")
    for source_root in (project_root, *source_roots):
        if Path(source_root).resolve().is_relative_to(output):
            raise ValueError("output cannot contain or equal a source root")
    prior = None
    if output.exists():
        read_static_program(output)
        prior = hashlib.sha256((output / "manifest.json").read_bytes()).hexdigest()
    started = time.monotonic()
    sources = collect_sources(project_root, source_roots=tuple(source_roots), max_files=max_files,
                              max_bytes=max_bytes, max_directories=max_directories)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".static-building-", dir=output.parent))
    units, errors = [], []
    try:
        if jobs == 1:
            for source in sources.files:
                units.append(_run_file(source, str(temporary), phase, max_body_operations))
                if progress:
                    progress(len(units), len(sources.files), units[-1])
        else:
            # spawn avoids inheriting mutable graph state or accidental hooks.
            with ProcessPoolExecutor(max_workers=jobs, mp_context=multiprocessing.get_context("spawn")) as pool:
                futures = {pool.submit(_run_file, s, str(temporary), phase, max_body_operations): s
                           for s in sources.files}
                for future in as_completed(futures):
                    try:
                        units.append(future.result())
                    except Exception as error:
                        source = futures[future]
                        errors.append({"path": source.path, **_issue("worker", error)})
                        units.append(_failed_file(source, str(temporary), error))
                    if progress:
                        progress(len(units), len(sources.files), units[-1] if units else {})
        units.sort(key=lambda item: (item["namespace_root"], item["path"]))
        # Detect edits during processing without executing any source or loader.
        changed = []
        for source in sources.files:
            try:
                equal = hashlib.sha256(Path(source.path).read_bytes()).hexdigest() == source.raw_sha256
            except OSError:
                equal = False
            if not equal:
                changed.append(source.path)
        counts = Counter()
        for unit in units:
            counts.update(unit["counts"])
        result = {"schema": SCHEMA, "schema_version": VERSION, "phase": phase,
                  "project_root": sources.project_root, "source_roots": list(sources.source_roots),
                  "target_executed": False, "runtime_evidence_required": False,
                  "source_catalog_status": sources.status.value,
                  "source_issues": [asdict(x) for x in sources.issues],
                  "remaining": [asdict(x) for x in sources.remaining], "units": units, "worker_errors": errors,
                  "source_changed": changed,
                  "summary": {"files": len(sources.files), "processed_files": len(units),
                              "source_bytes": sum(s.size_bytes for s in sources.files),
                              **dict(counts), "statuses": dict(Counter(u["status"] for u in units)),
                              "body_statuses": dict(Counter(b["status"] for u in units for b in u["bodies"])),
                              "issues_by_stage": dict(Counter(i["stage"] for u in units for i in u["issues"]))},
                  "completion": {"source_scan_complete": sources.status.value == "COMPLETE" and not errors and not changed,
                                 "whole_program_model_complete": False,
                                 "reason": "Source layers retain open protocol/effect/call boundaries; interprocedural fixed point is pending."},
                  "analyzer_seconds": time.monotonic() - started,
                  "storage": {"files": len(list(temporary.rglob("*.gz"))),
                              "compressed_bytes": sum(p.stat().st_size for p in temporary.rglob("*.gz"))}}
        (temporary / "manifest.json").write_bytes(_json(result))
        read_static_program(temporary, verify=False)
        if output.exists():
            # Refuse changed/unlisted members instead of deleting arbitrary
            # data that appeared while workers were building the replacement.
            read_static_program(output)
            if hashlib.sha256((output / "manifest.json").read_bytes()).hexdigest() != prior:
                raise ValueError("current output changed during analysis")
            previous = Path(tempfile.mkdtemp(prefix=".static-replacing-", dir=output.parent))
            previous.rmdir()
            output.rename(previous)
            try:
                temporary.rename(output)
            except BaseException:
                previous.rename(output)
                raise
            shutil.rmtree(previous)
        else:
            if prior is not None:
                raise ValueError("current output disappeared during analysis")
            temporary.rename(output)
        return result
    except BaseException:
        shutil.rmtree(temporary)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(prog="scar static", description=__doc__)
    parser.add_argument("source", help="source directory, not a command to execute")
    parser.add_argument("--source-root", action="append", default=[], help="additional explicit dependency source root")
    parser.add_argument("--out", default="artifacts/current/static")
    parser.add_argument("--phase", choices=("sources", "graph", "bodies"), default="graph")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--max-files", type=int, default=4096)
    parser.add_argument("--max-bytes", type=int, default=64_000_000)
    parser.add_argument("--max-directories", type=int, default=16384)
    parser.add_argument("--max-body-operations", type=int, default=10000)
    parser.add_argument("--refine", action="store_true",
                        help="refine current retained source catalogs/imports without rebuilding source graphs")
    parser.add_argument("--imports-only", action="store_true",
                        help="with --refine: rebuild only import relations, retain lexical/source graphs")
    parser.add_argument("--expand", action="store_true", help="incrementally lower bodies using the current stored source graphs")
    parser.add_argument("--rules-only", action="store_true", help="publish full entry rule ledgers without lowering bodies")
    parser.add_argument("--max-bodies", type=int, help="limit this body dispatch, keeping the full lexical denominator")
    parser.add_argument("--link-calls", action="store_true", help="link saved canonical CALL ports to conditional source bodies, without rebuilding them")
    parser.add_argument("--max-call-bodies", type=int, help="limit call-linking body reads, retaining the uncovered frontier")
    parser.add_argument("--file", action="append", default=[], help="body dispatch file selector, exact path or component suffix")
    parser.add_argument("--entry", action="append", default=[], help="dispatch an original lexical entry key, preserving the whole catalog")
    args = parser.parse_args(argv)
    if args.imports_only and not args.refine:
        parser.error("--imports-only requires --refine")
    if args.expand and args.refine:
        parser.error("--expand and --refine are independent stages")
    if args.link_calls and (args.expand or args.refine or args.phase != "graph"):
        parser.error("--link-calls is an independent refinement of the current model")
    if args.max_call_bodies is not None and not args.link_calls:
        parser.error("--max-call-bodies requires --link-calls")
    if (args.rules_only or args.max_bodies is not None or args.file or args.entry) and not args.expand:
        parser.error("--rules-only, --max-bodies, --file and --entry require --expand")

    progress_calls = 0
    progress_stage = "bodies" if args.expand else "sources"
    def progress(done, total, unit):
        nonlocal progress_calls
        progress_calls += 1
        if (total > 0 and done == total) or progress_calls % 25 == 0:
            noun = "entries" if progress_stage == "bodies" else "files"
            print(json.dumps({"stage": progress_stage, noun + "_done": done, noun + "_total": total,
                              "last": unit.get("path")}), file=sys.stderr, flush=True)

    if args.link_calls:
        from scar.analysis.static_calls import StaticCallBudget
        existing = read_static_program(args.out, verify=False)
        if Path(existing["project_root"]).resolve() != Path(args.source).resolve():
            raise ValueError("call linking source root differs from the current model")
        budget = None if args.max_call_bodies is None else StaticCallBudget(max_bodies=args.max_call_bodies)
        result = link_static_program(args.out, budget=budget)
    elif args.expand:
        from scar.analysis.static_body import expand_static_bodies
        existing = read_static_program(args.out, verify=False)
        if Path(existing["project_root"]).resolve() != Path(args.source).resolve():
            raise ValueError("body expansion source root differs from the current model")
        result = expand_static_bodies(args.out, jobs=args.jobs, max_operations=args.max_body_operations,
                                       max_bodies=0 if args.rules_only else args.max_bodies,
                                       files=args.file, entries=args.entry, progress=progress)
    elif args.refine:
        existing = read_static_program(args.out, verify=False)
        if Path(existing["project_root"]).resolve() != Path(args.source).resolve():
            raise ValueError("refinement source root differs from the current model")
        result = refine_static_program(args.out, refresh_lexical=not args.imports_only)
    else:
        result = build_static_program(args.source, source_roots=args.source_root, out=args.out,
                                      jobs=args.jobs, phase=args.phase, max_files=args.max_files,
                                      max_bytes=args.max_bytes, max_directories=args.max_directories,
                                      max_body_operations=args.max_body_operations, progress=progress)
        result = refine_static_program(args.out)
        if args.phase == "bodies":
            from scar.analysis.static_body import expand_static_bodies
            progress_stage = "bodies"
            progress_calls = 0
            result = expand_static_bodies(args.out, jobs=args.jobs,
                                           max_operations=args.max_body_operations, progress=progress)
    print(json.dumps({"summary": result["summary"], "completion": result["completion"],
                      "analyzer_seconds": result["analyzer_seconds"], "storage": result["storage"],
                      "catalog_refinement": result.get("catalog_refinement"),
                      "body_expansion": result.get("body_expansion"),
                      "static_calls": {key: value for key, value in result.get("static_calls", {}).items()
                                       if key not in ("artifacts", "shards")},
                      "manifest": str(Path(args.out).absolute() / "manifest.json")}, ensure_ascii=False, indent=2))
    failed = (result["worker_errors"] or result["source_changed"] or
              not result["completion"]["source_scan_complete"] or
              any(u["status"] in ("ERROR", "SYNTAX_ERROR") or
                  any(body["status"] == "ERROR" for body in u["bodies"])
                  for u in result["units"]))
    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
