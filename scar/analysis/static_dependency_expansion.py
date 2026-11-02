"""Feed selected dependency materials to the existing, source-only frontend.

This helper owns newly written unit fragments in a caller-owned staging
directory. It does not publish a manifest, scan package directories, select a
runtime import implementation, execute target callbacks, or claim a closure.
Normal units are produced by static_program._run_file, not another graph IR.
"""
from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
import gzip
import hashlib
import multiprocessing
import os
from pathlib import Path

from scar.analysis.static_sources import _ByteBudget, _Changed, _has_symlink_component, _read_source
from scar.ir.program.discovery import ModuleMapping
from scar.ir.program.providers import ProviderArtifact
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.program.static_dependencies import DependencyMaterialKind as Kind, StaticDependencyInventory
from scar.ir.program.static_sources import StaticSourceFile


@dataclass(frozen=True, slots=True)
class DependencyExpansionFrontier:
    material: int
    namespace_root: str | None
    kind: str
    detail: str


@dataclass(frozen=True, slots=True)
class DependencyUnitOrigin:
    material: int
    unit_key: str
    namespace_root: str
    mappings: tuple[ModuleMapping, ...]
    analyzed_file: ProviderArtifact
    module_queries: tuple[int, ...]
    import_relations: tuple[str, ...]
    reused: bool = False


@dataclass(frozen=True, slots=True)
class DependencyExpansion:
    """Normal frontend units and references to their conditional input basis."""

    import_index: SourceArtifactLocator
    output: str
    selected_materials: tuple[int, ...]
    unselected_materials: tuple[int, ...]
    units: tuple[dict, ...]
    origins: tuple[DependencyUnitOrigin, ...]
    frontiers: tuple[DependencyExpansionFrontier, ...]
    read_files: int
    source_bytes: int
    charged_bytes: int
    max_files: int
    max_bytes: int
    jobs: int

    def summary(self):
        from collections import Counter
        return {"selected_materials": len(self.selected_materials), "unselected_materials": len(self.unselected_materials),
                "source_files_read": self.read_files, "source_bytes": self.source_bytes,
                "source_read_budget_charged_bytes": self.charged_bytes,
                "units": len(self.units), "reused_units": sum(x.reused for x in self.origins),
                "statuses": dict(Counter(x["status"] for x in self.units)),
                "frontiers": dict(Counter(x.kind for x in self.frontiers)),
                "target_executed": False, "phase": "graph", "runtime_import_result_established": False,
                "dependency_closure_complete": False, "canonical_bodies_expanded": False}

    def to_dict(self):
        from scar.ir.record_codec import encode
        return {"schema": "scar.static-dependency-expansion", "schema_version": 1,
                **encode(self), "summary": self.summary(),
                "qualification": "Units are alternative source interpretations grouped by namespace root. "
                    "They do not select a runtime import implementation. Stub catalogs supply declarations, not bodies/effects. "
                    "Original import relation pointers apply to the exact input fragment receipt; a publisher rebuilding "
                    "that index must retain or mechanically relocate this proof basis. Native and unresolved selection "
                    "boundaries stay open; unselected material indices are continuation inputs, not dead work."}


def _existing_receipts_match(output, unit, source):
    """An existing unit may be reused, never overwritten or silently rebound."""
    from scar.analysis.static_program import _read_fragment
    if any(unit.get(name) != expected for name, expected in (
            ("path", source.path), ("namespace_root", source.namespace_root),
            ("raw_sha256", source.raw_sha256), ("decoded_sha256", source.decoded_sha256),
            ("encoding", source.encoding), ("source_bytes", source.size_bytes),
            ("module_names", list(source.module_names)),
            ("module_mappings", [{"name": x.name, "source_root": x.source_root} for x in source.module_mappings]))):
        return False
    descriptors = [*unit["artifacts"].values(), *(x["artifact"] for x in unit.get("bodies", ()) if "artifact" in x)]
    for descriptor in descriptors:
        relative = Path(descriptor["path"])
        if relative.is_absolute() or ".." in relative.parts:
            return False
        path = output / relative
        if _has_symlink_component(path) is not None:
            return False
        stored = path.read_bytes()
        if len(stored) != descriptor["bytes"] or hashlib.sha256(stored).hexdigest() != descriptor["sha256"]:
            return False
        raw = gzip.decompress(stored)
        if len(raw) != descriptor["decoded_bytes"] or hashlib.sha256(raw).hexdigest() != descriptor["decoded_sha256"]:
            return False
    snapshot = _read_fragment(output, unit["artifacts"]["source"])
    if (snapshot.get("text") != source.text or snapshot.get("path") != source.path
            or snapshot.get("namespace_root") != source.namespace_root
            or snapshot.get("raw_sha256") != source.raw_sha256
            or snapshot.get("decoded_sha256") != source.decoded_sha256):
        return False
    return True


def expand_static_dependency_materials(inventory, *, out, material_indices=None, max_files=16,
                                      max_bytes=8 * 1024 * 1024, jobs=1, existing_units=(), progress=None):
    """Build bounded external .py/.pyi units in ``out`` without publication.

    ``material_indices`` selects candidates for static analysis, not runtime
    implementations. Omitted indices select external source/stub candidates.
    Each namespace-root interpretation is a distinct normal frontend unit;
    mappings from different roots are never merged into one interpretation.
    Existing units are reusable only when explicitly supplied and every input
    identity and stored fragment receipt matches. Other existing paths remain
    untouched and generate a frontier.

    ``max_files`` bounds attempted physical file reads; ``max_bytes`` bounds
    reserved raw-source reads, including rejected versions. A failed read
    conservatively consumes its reserved allowance, not a claimed measurement
    of bytes read. Remaining indices/frontiers support later rounds.
    The caller publishes units and refreshes global indices atomically; this
    helper never modifies a current manifest. ``progress`` is an optional
    caller-owned SCAR observer, never a callback discovered in target source.
    """
    from scar.analysis.static_program import _json, _run_file
    if type(inventory) is not StaticDependencyInventory:
        raise TypeError("dependency expansion requires the typed original inventory")
    inventory.__post_init__()
    for name, value in (("max_files", max_files), ("max_bytes", max_bytes)):
        if type(value) is not int or value < 1:
            raise ValueError(name + " must be a positive exact integer")
    if type(jobs) is not int or not 1 <= jobs <= 32:
        raise ValueError("jobs must be in [1, 32]")
    output = Path(os.path.abspath(out))
    if _has_symlink_component(output) is not None:
        raise ValueError("dependency staging output must not traverse symlinks")
    if material_indices is None:
        selected = tuple(i for i, material in enumerate(inventory.materials)
                         if material.supplied_unit is None and material.kind in (Kind.SOURCE, Kind.STUB))
    else:
        selected = tuple(material_indices)
        if any(type(x) is not int or not 0 <= x < len(inventory.materials) for x in selected):
            raise ValueError("selected material index is outside the original inventory")
        if len(set(selected)) != len(selected):
            raise ValueError("selected material indices must be unique")
    unselected = tuple(i for i in range(len(inventory.materials)) if i not in set(selected))
    old = {}
    for unit in existing_units:
        if unit["key"] in old:
            raise ValueError("existing units contain a duplicate key")
        old[unit["key"]] = unit
    output.mkdir(parents=True, exist_ok=True)
    if _has_symlink_component(output / "units") is not None:
        raise ValueError("dependency unit directory must not traverse symlinks")
    query_indices = defaultdict(set)
    query_relations = defaultdict(set)
    for number, query in enumerate(inventory.module_queries):
        for index in query.materials:
            query_indices[index].add(number)
    for relation in inventory.relations:
        if relation.module_query is not None:
            query_relations[relation.module_query].add(relation.origin)

    frontiers, origins, units, prepared = [], [], {}, []
    read_files, source_bytes, charged_bytes = 0, 0, 0

    def frontier(index, root, kind, detail):
        frontiers.append(DependencyExpansionFrontier(index, root, kind, detail))

    for index in selected:
        material = inventory.materials[index]
        if material.supplied_unit is not None:
            frontier(index, None, "ALREADY_SUPPLIED_SNAPSHOT", "Material already names an original supplied unit; no disk reread was attempted.")
            continue
        if material.kind not in (Kind.SOURCE, Kind.STUB):
            frontier(index, None, "NON_SOURCE_MATERIAL", "Native implementation contracts and namespace selection are not source files.")
            continue
        if read_files >= max_files:
            frontier(index, None, "FILE_BUDGET", "Physical source read budget reached; this candidate was not read.")
            continue
        path = Path(material.path)
        if _has_symlink_component(path) is not None:
            frontier(index, None, "SOURCE_SYMLINK", "Candidate source traverses a symbolic link; no source was read.")
            continue
        expected_bytes = material.artifact.size_bytes if material.artifact is not None else (
            material.stat_stamp[3] if material.stat_stamp is not None else 0)
        if expected_bytes > max_bytes - charged_bytes:
            frontier(index, None, "BYTE_BUDGET", "Candidate exceeds remaining source-byte budget; it remains available for another round.")
            continue
        read_files += 1
        read_limit = min(expected_bytes or max_bytes - charged_bytes, max_bytes - charged_bytes)
        try:
            raw, text, encoding = _read_source(path, read_limit)
            charged_bytes += len(raw)
            raw_sha = hashlib.sha256(raw).hexdigest()
            if material.artifact is not None and (raw_sha != material.artifact.sha256 or len(raw) != material.artifact.size_bytes):
                frontier(index, None, "MATERIAL_VERSION_CHANGED", "Current stable source bytes differ from the material's original receipt.")
                continue
        except _ByteBudget as error:
            charged_bytes += read_limit
            frontier(index, None, "MATERIAL_VERSION_CHANGED" if material.artifact is not None else "SOURCE_SIZE_CHANGED",
                     "Current source size exceeds the inventoried/reserved read size; refresh this material before expansion.")
            continue
        except _Changed as error:
            charged_bytes += read_limit
            frontier(index, None, "SOURCE_CHANGED_DURING_READ", str(error))
            continue
        except (OSError, UnicodeError, LookupError, SyntaxError) as error:
            charged_bytes += read_limit
            frontier(index, None, "SOURCE_READ_FAILED", type(error).__name__ + ": " + str(error))
            continue
        source_bytes += len(raw)
        decoded_sha = hashlib.sha256(text.encode()).hexdigest()
        receipt = ProviderArtifact(material.path, raw_sha, len(raw), "scar.dependency-material-bytes")
        by_root = defaultdict(set)
        for mapping in material.mappings:
            by_root[mapping.source_root].add(mapping)
        for namespace, mapping_set in sorted(by_root.items()):
            mappings = tuple(sorted(mapping_set, key=lambda x: (x.source_root, x.name)))
            if not path.is_relative_to(namespace):
                frontier(index, namespace, "MATERIAL_MAPPING_OUTSIDE_ROOT", "Original mapping root does not contain this file.")
                continue
            source = StaticSourceFile(material.path, namespace, tuple(sorted(x.name for x in mappings)), text,
                                      raw_sha, decoded_sha, encoding, len(raw), mappings)
            key = hashlib.sha256(_json([namespace, source.path, decoded_sha])).hexdigest()[:24]
            if key in units:
                frontier(index, namespace, "DUPLICATE_UNIT_INTERPRETATION", "This identical source/root unit is already selected in this batch.")
                continue
            queries = tuple(sorted(query_indices[index]))
            pointers = tuple(sorted({p for q in queries for p in query_relations[q]}))
            origin = DependencyUnitOrigin(index, key, namespace, mappings, receipt, queries, pointers)
            destination = output / "units" / key
            if destination.exists() or key in old:
                try:
                    matched = key in old and _existing_receipts_match(output, old[key], source)
                except (OSError, ValueError, KeyError, TypeError):
                    matched = False
                if matched:
                    from dataclasses import replace
                    units[key] = old[key]
                    origins.append(replace(origin, reused=True))
                else:
                    frontier(index, namespace, "EXISTING_UNIT_NOT_EXACT", "Existing unit/path was not overwritten: its declaration or receipts do not match.")
                continue
            if destination.is_symlink():
                frontier(index, namespace, "EXISTING_UNIT_NOT_EXACT", "Existing symlink unit path was not overwritten.")
                continue
            # Mark scheduled keys, so parallel workers can never write the
            # same unit namespace even if a malformed inventory repeats it.
            units[key] = None
            prepared.append((source, origin))

    def completed(unit, origin):
        units[origin.unit_key] = unit
        origins.append(origin)
        if unit["status"] in ("ERROR", "SYNTAX_ERROR"):
            frontier(origin.material, origin.namespace_root, "FRONTEND_FAILED", "Normal source frontend reported " + unit["status"])
        elif unit["path"].endswith(".py") and not {"semantic", "semantics", "control"} <= unit["artifacts"].keys():
            frontier(origin.material, origin.namespace_root, "SOURCE_LAYERS_MISSING", "Normal source frontend retained explicit layer-construction issues.")
        if progress is not None:
            progress(len(origins), total_units, unit)

    total_units = len(prepared) + len(origins)
    if jobs == 1:
        for source, origin in prepared:
            completed(_run_file(source, str(output), "graph", 10000), origin)
    elif prepared:
        with ProcessPoolExecutor(max_workers=jobs, mp_context=multiprocessing.get_context("spawn")) as pool:
            futures = {pool.submit(_run_file, source, str(output), "graph", 10000): (source, origin)
                       for source, origin in prepared}
            for future in as_completed(futures):
                source, origin = futures[future]
                try:
                    unit = future.result()
                except Exception as error:
                    from scar.analysis.static_program import _failed_file
                    unit = _failed_file(source, str(output), error)
                completed(unit, origin)
    return DependencyExpansion(inventory.import_index, str(output), selected, unselected,
        tuple(units[key] for key in sorted(units) if units[key] is not None),
        tuple(sorted(origins, key=lambda x: (x.unit_key, x.material))), tuple(frontiers), read_files, source_bytes, charged_bytes,
        max_files, max_bytes, jobs)
