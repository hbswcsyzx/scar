"""Read-only entry lookup over original source owners, never a graph producer."""
from __future__ import annotations

import ast
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass, field, replace
import hashlib
import inspect
import json
from pathlib import Path
from weakref import WeakKeyDictionary

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


_PRIVATE_READ_SESSIONS = WeakKeyDictionary()


class _EntryReadSession:
    """Private copies for one ordinary, callback-free reader interval.

    No public owner is put into fast mode. The existing normal guards bracket
    the whole session and every user callback; only copies unreachable by that
    callback reuse checked input receipts and PreparedSource. Returned entry
    queries are rebound to their still-checked original catalog, not restored
    lowering owners or JSON proof tokens.
    """
    def __init__(self, catalog, target, controls, share_source_context=False):
        _need(type(share_source_context) is bool, 'context reuse selection must be an exact bool')
        self.share_source_context, self.program_reader = share_source_context, None
        self.original, self.original_target = catalog, target
        self.controls, self.control_bytes = controls, _bytes(controls)
        self.catalog, self.target, self.base = catalog, target, None
        self.contexts = OrderedDict()
        self.catalog_counts = dict(catalog._measurements)
        self.owner_counts = [dict(x._measurements) for x in catalog.admissions]
        self.archive_counts = {k:dict(x.counts) for k,x in catalog.archives._stores.items()}
        self.index_receipts = [_bytes(x.index_receipt) for x in catalog.projects]

    def check(self):
        self.original.require_unchanged()
        _need([_bytes(x.index_receipt) for x in self.original.projects] == self.index_receipts,
              "original composition receipt changed in reader scope")
        if self.original_target not in self.original.projects:
            _need(self.original_target.source_inputs() == self.target_inputs, "publication target changed in reader scope")
        _need(_bytes(self.controls) == self.control_bytes, "publication requests/plan changed in reader scope")

    def __enter__(self):
        self.target_inputs = self.original_target.source_inputs()
        self.check()
        # Existing overlay/attachment variants keep their old normal path.
        # The common plain-base path can own a completely private copy.
        if (len(self.original.projects) != 1 or self.original_target is not self.original.projects[0]
                or self.original_target.has_source_attachments or self.original_target.has_source_entry_publication
                or self.original_target._static_source_proof is not None):
            return self
        try:
            self.base = self.original_target._private_read_snapshot()
            self.catalog = deepcopy(self.original, {id(self.original_target): self.base})
            self.target = self.base
            # Deepcopy preserves the genuine local catalog/entry cycle. It
            # does not execute a constructor from saved metadata or create a
            # CodeType. All mutable source/manifest documents are now owned.
            _need(self.catalog._catalog_json == self.original._catalog_json
                  and self.catalog._source_inputs == self.original._source_inputs,
                  "private reader catalog differs from its checked original")
            # Validate the actual copied rows, owner documents and archive
            # documents before registration, not just copied digest strings.
            self.catalog.require_unchanged()
            _PRIVATE_READ_SESSIONS[self.catalog] = self
            self.check()
            return self
        except BaseException:
            _PRIVATE_READ_SESSIONS.pop(self.catalog, None)
            if self.base is not None:
                self.base._end_private_read_snapshot()
            raise

    def progress(self, callback, row):
        self.check()
        try:
            callback(row)
        finally:
            self.check()

    def __exit__(self, kind, error, traceback):
        try:
            if self.program_reader is not None:
                self.program_reader.close()
            self.check()
            if self.catalog is not self.original:
                for key, entry in self.catalog._resolved.items():
                    previous = self.original._resolved.get(key)
                    exported = replace(entry, _owner=self.original)
                    _need(previous is None or previous == exported,
                          "original resolved entry changed during ordinary reading")
                    self.original._resolved[key] = previous or exported
                # Preserve ordinary source-reference caches, never lowered
                # bodies/owners. They came from normal readers in this same
                # scope and exact unchanged original artifact namespace.
                for original, private in zip(self.original.admissions, self.catalog.admissions):
                    for name in ('_definitions', '_resolved', '_file_graph_locators'):
                        target, values = getattr(original, name), getattr(private, name)
                        for key, value in values.items():
                            _need(key not in target or _bytes(encode(target[key])) == _bytes(encode(value)),
                                  'original source reference cache changed in reader scope')
                            target.setdefault(key, deepcopy(value))
        finally:
            # Always revoke the private fast path, including budget failures
            # while merging actual read accounting below.
            _PRIVATE_READ_SESSIONS.pop(self.catalog, None)
            if self.base is not None:
                self.base._end_private_read_snapshot()
            self.contexts.clear()
            if self.catalog is not self.original:
                for key, before in self.catalog_counts.items():
                    self.original._measurements[key] += self.catalog._measurements[key] - before
                for original, private, counts in zip(self.original.admissions, self.catalog.admissions, self.owner_counts):
                    for key, before in counts.items():
                        original._measurements[key] += private._measurements[key] - before
                    # Union new normal graph charges without double charging a
                    # file also read by the callback through its original API.
                    new = private._charged - original._charged
                    if new:
                        for row in private._files.values():
                            if row['source_graph_artifact'] is not None:
                                path, artifact = private._artifact_path(row['source_graph_artifact'], row['source_root'], 'graphs')
                                if (str(path), artifact['canonical_sha256']) in new:
                                    original._charge(path, artifact)
                for key, counts in self.archive_counts.items():
                    original, private = self.original.archives._stores[key], self.catalog.archives._stores[key]
                    for name, before in counts.items():
                        original.counts[name] += private.counts[name] - before
                    for name in ('modules', 'module_indexes', 'texts'):
                        destination = getattr(original, name)
                        for identity, value in getattr(private, name).items():
                            destination.setdefault(identity, value)
        return False

    def entry(self, entry):
        _need(entry.key in self.original._resolved, "reader did not export its genuine entry query")
        return self.original._resolved[entry.key]


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
        if self in _PRIVATE_READ_SESSIONS:
            return  # Only an unexposed, owned copy can enter this registry.
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
        session = _PRIVATE_READ_SESSIONS.get(self)
        if session is not None and entry.file_key in session.contexts:
            self.require_entry(entry)
            session.contexts.move_to_end(entry.file_key)
            return session.contexts[entry.file_key]
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
        result = PreparedSource(Path(entry.reference.snapshot.path), Path(view.context.namespace_root), text,
                                view.semantic, view.semantics, view.control, tree, tables)
        if session is not None:
            session.contexts[entry.file_key] = result
            while len(session.contexts) > 2:
                session.contexts.popitem(last=False)
        return result

    def _ordinary_read_session(self, target, *, controls=(), share_source_context=False):
        return _EntryReadSession(self, target, controls, share_source_context)

    def _shared_program_reader(self, max_record_bytes, max_operations):
        session = _PRIVATE_READ_SESSIONS.get(self)
        if session is None or not session.share_source_context:
            return None
        if session.program_reader is None:
            from scar.analysis.source_program_publication import _SharedEntryProgramReader
            session.program_reader = _SharedEntryProgramReader(session.controls[0], max_record_bytes, max_operations)
        return session.program_reader

    def _ordinary_read_active(self):
        return self in _PRIVATE_READ_SESSIONS

    def measurements(self):
        return {**self._measurements, "owners": [x.measurements() for x in self.admissions],
                "resolved_entries": len(self._resolved), "raw_read": False, "target_executed": False}


__all__ = ["ResolvedSourceEntry", "SourceEntryCatalog"]
