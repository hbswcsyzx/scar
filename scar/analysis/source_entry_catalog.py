"""Read-only entry lookup over original source owners, never a graph producer."""
from __future__ import annotations

import ast
from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import inspect
import json
from pathlib import Path

from scar.analysis.compiler_witness_archives import CompilerWitnessArchives
from scar.analysis.program_composition import CompositionIndex
from scar.analysis.program_lowering import PreparedSource, _symbol_tables
from scar.analysis.source_attachments import SourceAttachments
from scar.ir.program.call_edges import CapturedCode, CodeSourceLink, CallLinkStatus
from scar.ir.program.source_references import SourceDefinitionReference
from scar.ir.record_codec import decode, encode


def _bytes(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def _hash(value):
    return hashlib.sha256(_bytes(value)).hexdigest()


def _need(value, detail):
    if not value:
        raise ValueError("source entry catalog: " + detail)


@dataclass(frozen=True)
class ResolvedSourceEntry:
    key: str
    reference: SourceDefinitionReference
    captured: CapturedCode
    source_link: CodeSourceLink
    file_key: str
    origin_json: str = field(repr=False)
    store_json: str = field(repr=False)
    _owner: object = field(repr=False, compare=False)

    @property
    def origin(self):
        return json.loads(self.origin_json)

    @property
    def store_receipt(self):
        return json.loads(self.store_json)


class SourceEntryCatalog:
    """Explicit source owners and immutable archives; no fi/bi for dependencies.

    Catalog rows are metadata candidates. resolve() performs original graph
    membership validation before exposing an existing qualified definition.
    """
    def __init__(self, *, archives, admissions=(), projects=(), max_groups=100000,
                 max_candidates=100000, max_selected_decode_bytes=128_000_000):
        _need(type(archives) is CompilerWitnessArchives and type(admissions) is tuple
              and all(type(x) is SourceAttachments for x in admissions)
              and type(projects) is tuple and all(type(x) is CompositionIndex for x in projects),
              "exact original source owners and readonly archives required")
        _need(all(type(x) is int and x > 0 for x in (max_groups, max_candidates, max_selected_decode_bytes)),
              "positive independent catalog limits required")
        self.archives, self.admissions, self.projects = archives, admissions, projects
        self.max_selected_decode_bytes = max_selected_decode_bytes
        self._rows, self._owners, self._resolved = [], {}, {}
        self._group_index, self._capture_manifest = {}, None
        self._source_inputs = self._inputs()
        self._measurements = {"source_prepare_attempts": 0, "ast_parses": 0,
                              "symtable_parses": 0, "decoded_source_bytes": 0}
        candidates = {}
        for owner in admissions:
            self._require_capture_manifest(owner.capture_declaration()['trace_files'])
            for row in owner.catalog_rows():
                witness = owner.code_witness(row["process_id"], row["code"])
                item = self._group(row, witness["record_locator"], "DEPENDENCY_ADMISSION")
                if row["status"] == "SOURCE_VERIFIED":
                    self._candidate(candidates, item, owner, witness)
                self._register_group(item, candidates)
        for composition in projects:
            model = composition.inventory_component("call_sources")["model"]
            self._require_capture_manifest(model['files'])
            captures = {(x["process_id"], x["code"]["key"]): x for x in model["codes"]}
            links = {x["code"]: (i, x) for i, x in enumerate(model["code_links"])}
            for index, group in enumerate(model["groups"]):
                captured = captures.get((group["process_id"], group["code"]))
                linked = links.get(group["code"])
                row = {"process_id": group["process_id"], "code": group["code"],
                    "captured_code": captured["code"] if captured else None,
                    "descriptor_anchor": captured["anchor"] if captured else None,
                    "entered_invocations": group["count"], "first_anchor": group["first_anchor"],
                    "last_anchor": group["last_anchor"], "code_source_link": linked[1] if linked else None,
                    "status": "SOURCE_" + linked[1]["status"] if linked else "UNRESOLVED", "frontiers": []}
                locator = composition.inventory_component_locator("call_sources", f"/model/groups/{index}")
                item = self._group(row, locator, "PROJECT_INVENTORY")
                if row["status"] == "SOURCE_VERIFIED":
                    witness = {"record": row, "record_locator": locator,
                        "descriptor_locator": composition.inventory_component_locator("call_sources",
                            f"/model/codes/{model['codes'].index(captured)}/code"),
                        "code_source_locator": composition.inventory_component_locator("call_sources", f"/model/code_links/{linked[0]}")}
                    self._candidate(candidates, item, composition, witness)
                self._register_group(item, candidates)
        _need(len(self._rows) <= max_groups and len(candidates) <= max_candidates, "catalog denominator limit exceeded")
        self._candidates = tuple(sorted(candidates.values(), key=lambda x: (-x["calls"], x["entry_key"])))
        self._catalog_json = _bytes({"groups": self._rows, "candidates": self._candidates}).decode()

    def _require_capture_manifest(self, files):
        value = _bytes(files)
        _need(self._capture_manifest is None or self._capture_manifest == value,
              'source owners name different exact captured file manifests')
        self._capture_manifest = value

    def _register_group(self, item, candidates):
        key = item['process_id'], item['code']
        origin = {field: deepcopy(item[field]) for field in
                  ('origin_kind', 'record_locator', 'source_status', 'frontiers', 'entry_key')}
        if key not in self._group_index:
            item['source_origins'] = [origin]
            item['entry_keys'] = [item['entry_key']] if item['entry_key'] is not None else []
            self._group_index[key] = item
            self._rows.append(item)
            return
        previous = self._group_index[key]
        fields = ('process_id', 'code', 'captured_code', 'descriptor_anchor', 'entered_invocations', 'first_anchor', 'last_anchor')
        _need(_bytes({x: item[x] for x in fields}) == _bytes({x: previous[x] for x in fields}),
              'same captured group has contradictory descriptors/anchors/counts across owners')
        previous['source_origins'].append(origin)
        if item['entry_key'] is not None and item['entry_key'] not in previous['entry_keys']:
            previous['entry_keys'].append(item['entry_key'])
        if len(previous['entry_keys']) == 1:
            previous['entry_key'] = previous['entry_keys'][0]
        elif len(previous['entry_keys']) > 1:
            previous['entry_key'] = None
            previous['entry_frontier'] = 'AMBIGUOUS_ORIGINAL_SOURCE_OWNER'
            for entry_key in previous['entry_keys']:
                candidates[entry_key]['status'] = 'AMBIGUOUS_ORIGINAL_SOURCE_OWNER'

    def _group(self, row, locator, origin):
        return {"process_id": row["process_id"], "code": row["code"],
                "captured_code": deepcopy(row["captured_code"]), "descriptor_anchor": deepcopy(row["descriptor_anchor"]),
                "entered_invocations": row["entered_invocations"], "first_anchor": deepcopy(row["first_anchor"]),
                "last_anchor": deepcopy(row["last_anchor"]), "source_status": row["status"],
                "frontiers": deepcopy(row.get("frontiers", [])), "origin_kind": origin,
                "record_locator": encode(locator), "entry_key": None}

    def _candidate(self, candidates, group, owner, witness):
        row = witness["record"]
        link = decode(CodeSourceLink, row["code_source_link"])
        captured = decode(CapturedCode, row["captured_code"])
        if link.status is not CallLinkStatus.VERIFIED or link.definition is None or link.source is None:
            group["entry_frontier"] = "SOURCE_DEFINITION_INTERFACE_UNAVAILABLE"
            return
        _need(link.snapshot is not None and captured.filename == link.snapshot.path, "candidate snapshot/descriptor differs")
        basis = {"kind": group["origin_kind"], "source_snapshot": encode(link.snapshot),
                 "definition": encode(link.definition), "source": encode(link.source),
                 "captured": encode(captured), "record_locator": encode(witness["record_locator"])}
        key = _hash(basis)
        group["entry_key"] = key
        category = "CANDIDATE_SOURCE_GRAPH_UNVERIFIED"
        if captured.flags & (inspect.CO_GENERATOR | inspect.CO_COROUTINE | inspect.CO_ASYNC_GENERATOR | inspect.CO_ITERABLE_COROUTINE):
            category = "ENTRY_ADAPTER_MISSING:RESUMABLE_FUNCTION"
        variants = self.archives.metadata_variants(captured, link.snapshot, link.optimize_levels)
        if not variants:
            category = "CODE_WITNESS_UNAVAILABLE"
        candidates[key] = {"entry_key": key, "basis": basis, "calls": group["entered_invocations"],
            "status": category, "archive_variants": variants,
            "file_key": _hash({"owner": basis["record_locator"]["artifact"], "snapshot": encode(link.snapshot)})}
        self._owners[key] = owner, witness, captured, link

    def _inputs(self):
        for owner in self.admissions:
            owner.require_unchanged()
        return {"admissions": [x.receipts() for x in self.admissions],
                "projects": [x.source_inputs() for x in self.projects], "archives": self.archives.receipts()}

    def require_unchanged(self):
        _need(self._inputs() == self._source_inputs, "source owner/archive inputs changed")
        _need(_bytes({"groups": self._rows, "candidates": self._candidates}).decode() == self._catalog_json,
              "entry catalog mutated")

    def inputs(self):
        self.require_unchanged()
        return deepcopy(self._source_inputs)

    def metadata(self):
        self.require_unchanged()
        return {"schema": "scar.source-entry-catalog", "schema_version": 1,
                "groups": deepcopy(self._rows), "candidates": deepcopy(self._candidates),
                "entered_code_groups": len(self._rows),
                "entered_invocations": sum(x["entered_invocations"] for x in self._rows),
                "runtime_capture_verified_here": False, "canonical_bodies_established": False}

    def resolve(self, key):
        self.require_unchanged()
        if key in self._resolved:
            return self._resolved[key]
        owner, witness, captured, link = self._owners[key]
        candidate = next(x for x in self._candidates if x["entry_key"] == key)
        _need(candidate["status"] == "CANDIDATE_SOURCE_GRAPH_UNVERIFIED", "entry is not dispatchable")
        if type(owner) is SourceAttachments:
            reference = owner.definition_reference(witness["record"]["process_id"], captured.key)
            kind = "DEPENDENCY_ADMISSION"
        else:
            matching = [(fi, raw) for fi in range(owner.inventory_file_count)
                        if (raw := owner.inventory_file(fi))["snapshot"] == encode(link.snapshot)]
            _need(len(matching) == 1, "project entry has no exact original source file")
            reference = owner.definition_reference(matching[0][0], link.definition)
            kind = "PROJECT_INVENTORY"
        _need(type(reference) is SourceDefinitionReference and reference.snapshot == link.snapshot
              and reference.definition == link.definition and reference.source == link.source,
              "resolved original definition differs from captured source witness")
        owner.resolve_definition(reference)
        self._check_decode_budget()
        variants = self.archives.metadata_variants(captured, reference.snapshot, link.optimize_levels)
        _need(bool(variants), "entry lost its admitted compiler archive")
        origin = {"format": "scar.source-code-origin.v2", "kind": kind,
            "definition": encode(reference), "record_locator": encode(witness["record_locator"]),
            "captured_code_locator": encode(witness["descriptor_locator"]),
            "source_link_locator": encode(witness["code_source_locator"]),
            "compilation_profile": "RECORDED_FUTURE_FLAGS_V1"}
        result = ResolvedSourceEntry(key, reference, captured, link, candidate["file_key"],
                                    _bytes(origin).decode(), _bytes(variants[0]["store"]).decode(), self)
        self._resolved[key] = result
        return result

    def _check_decode_budget(self):
        total = sum(x.measurements()["unique_artifact_canonical_bytes"] for x in self.admissions)
        _need(total <= self.max_selected_decode_bytes, "selected source/provider decoded byte budget exceeded")

    def require_entry(self, entry):
        _need(type(entry) is ResolvedSourceEntry and entry._owner is self
              and self._resolved.get(entry.key) is entry, "resolved entry belongs to another catalog")
        self.require_unchanged()
        owner, _witness, captured, link = self._owners[entry.key]
        _need(entry.captured == captured and entry.source_link == link, "resolved compiler/source identity changed")
        return owner

    def store_for(self, entry):
        self.require_entry(entry)
        return self.archives.store_for(entry.store_receipt)

    def prepare(self, entry):
        owner = self.require_entry(entry)
        view = owner.source_view(entry.reference)
        _need(view.snapshot == entry.reference.snapshot and view.context == entry.reference.context,
              "resolved source view changed")
        store = self.store_for(entry)
        text = store.text(entry.reference.snapshot)
        _need("sha256:" + hashlib.sha256(text.encode()).hexdigest() == entry.reference.snapshot.fingerprint,
              "archived text differs from original snapshot")
        tree = ast.parse(text, filename=entry.reference.snapshot.path)
        tables = _symbol_tables(text, entry.reference.snapshot.path)
        self._measurements["ast_parses"] += 1
        self._measurements["symtable_parses"] += 1
        self._measurements["decoded_source_bytes"] += len(text.encode())
        self._check_decode_budget()
        return PreparedSource(Path(entry.reference.snapshot.path), Path(view.context.namespace_root), text,
                              view.semantic, view.semantics, view.control, tree, tables)

    def measurements(self):
        return {**self._measurements, "owners": [x.measurements() for x in self.admissions],
                "resolved_entries": len(self._resolved), "raw_read": False, "target_executed": False}


__all__ = ["ResolvedSourceEntry", "SourceEntryCatalog"]
