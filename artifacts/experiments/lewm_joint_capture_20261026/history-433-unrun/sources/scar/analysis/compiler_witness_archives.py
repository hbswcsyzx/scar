"""Explicit immutable compiler archives and observed-only witness acquisition.

This module never executes or imports target code. A saved body's complete store
receipt selects its original explicitly admitted archive, not a union manifest.
Acquisition rederives observed descriptors/source links from CompositionIndex;
caller-selected definition references are not replacement compiler evidence.
Static unobserved-code acquisition is intentionally outside this API.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
import sys
import time

from scar.analysis.call_compilation import compile_cache_key, UnsupportedCompilationFlags
from scar.analysis.code_witness import CodeWitnessBudget, CodeWitnessStore, CodeWitnessUnavailable
from scar.analysis.program_composition import CompositionIndex
from scar.ir.program.call_edges import CapturedCode, CodeCapture, CodeSourceLink, CallLinkStatus
from scar.ir.program.compilation import CallCompilationProfile
from scar.ir.program.source_references import SourceDefinitionReference
from scar.ir.program.call_demand import EnteredCallCode
from scar.ir.record_codec import decode, encode
from scar.ir.semantics_v2 import SourceSnapshot


def _need(condition, detail):
    if not condition:
        raise ValueError("compiler witness archives: " + detail)


def _bytes(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class CompilerArchiveBudget:
    max_archives: int = 16
    max_total_modules: int = 1024
    max_total_sources: int = 1024
    max_declared_payload_bytes: int = 2_000_000_000

    def __post_init__(self):
        _need(all(type(value) is int and value > 0 for value in asdict(self).values()),
              "archive collection ceilings must be positive exact integers")


@dataclass(frozen=True)
class ObservedAcquisitionBudget:
    max_definitions: int = 1024
    max_requests: int = 4096
    max_attempts: int = 128
    max_elapsed_seconds: int = 900
    max_record_bytes: int = 16_000_000
    max_report_bytes: int = 64_000_000

    def __post_init__(self):
        _need(all(type(value) is int and value > 0 for value in asdict(self).values()),
              "acquisition ceilings must be positive exact integers")


class CompilerWitnessArchives:
    """Read-only archives admitted by explicit directory and manifest SHA tuples.

    Construction opens only these explicitly supplied paths. ``store_for``
    accepts a complete saved native CodeWitnessStore receipt; report-selected
    URIs cannot cause a new archive to be opened. Module presence queries are
    metadata only, distinct from resolve's complete nested descriptor check.
    """
    def __init__(self, archives, *, store_budget=CodeWitnessBudget(), budget=CompilerArchiveBudget()):
        _need(type(archives) is tuple and type(store_budget) is CodeWitnessBudget
              and type(budget) is CompilerArchiveBudget, "explicit archive tuples/typed ceilings required")
        store_budget.__post_init__(); budget.__post_init__()
        _need(len(archives) <= budget.max_archives, "archive collection count exceeded")
        self.budget, self.store_budget = budget, store_budget
        self._stores, self._receipts, self._documents = {}, {}, {}
        total_modules = total_sources = total_bytes = 0
        for declaration in archives:
            _need(type(declaration) is tuple and len(declaration) == 2,
                  "each admitted archive needs its directory and exact manifest SHA")
            directory, expected_sha = declaration
            _need(type(expected_sha) is str and re.fullmatch(r"[0-9a-f]{64}", expected_sha),
                  "archive manifest SHA must be exact lowercase SHA256")
            store = CodeWitnessStore(directory, budget=store_budget)
            receipt = store.receipt()
            _need(receipt["sha256"] == expected_sha, "explicit archive manifest SHA differs")
            key = _bytes(receipt)
            _need(key not in self._stores and all(row["path"] != receipt["path"] for row in self._receipts.values()),
                  "duplicate archive declaration")
            total_modules += len(store.document["modules"])
            total_sources += len(store.document["sources"])
            total_bytes += sum(row["artifact"]["bytes"] for section in ("sources", "modules")
                               for row in store.document[section].values())
            _need(total_modules <= budget.max_total_modules and total_sources <= budget.max_total_sources
                  and total_bytes <= budget.max_declared_payload_bytes,
                  "aggregate immutable archive ceiling exceeded")
            self._stores[key], self._receipts[key] = store, receipt
            self._documents[key] = _bytes(store.document)

    def _check(self, key):
        store = self._stores[key]
        _need(not store.writable and not store.compile_missing
              and store.receipt() == self._receipts[key]
              and _bytes(store.document) == self._documents[key],
              "admitted archive/loaded manifest changed after read-only admission")
        return store

    def store_for(self, saved_store_receipt):
        _need(type(saved_store_receipt) is dict, "saved native store receipt must be a complete object")
        key = _bytes(saved_store_receipt)
        _need(key in self._stores and self._receipts[key] == saved_store_receipt,
              "saved store receipt has no identical explicitly admitted archive")
        return self._check(key)

    def receipts(self):
        for key in self._stores:
            self._check(key)
        return [deepcopy(receipt) for receipt in self._receipts.values()]

    def metadata_variants(self, captured, snapshot, optimize_levels):
        """Enumerate exact key metadata; this is not proof of a nested CodeType."""
        _need(type(captured) is CapturedCode and type(snapshot) is SourceSnapshot
              and captured.filename == snapshot.path,
              "observed descriptor/snapshot filename differs")
        levels = tuple(sorted(set(optimize_levels)))
        _need(levels and all(type(level) is int and level in (0, 1, 2) for level in levels),
              "recorded matching optimization levels required")
        found, payloads = [], {}
        for level in levels:
            identity = compile_cache_key(snapshot.path, snapshot.fingerprint,
                CallCompilationProfile.RECORDED_FUTURE_FLAGS, captured.flags, level,
                compile_filename=captured.filename)
            encoded, module_key = encode(identity), _sha(_bytes(encode(identity)))
            for key in self._stores:
                store = self._check(key)
                row = store.document["modules"].get(module_key)
                if row is None:
                    continue
                _need(row["compile_key"] == encoded and row["snapshot"] == encode(snapshot)
                      and row["runtime"] == self._receipts[key]["runtime"],
                      "archive module key/context contradicts its original receipt")
                payload = (row["artifact"]["sha256"], row["artifact"]["bytes"], _bytes(row["module_descriptor"]))
                _need(module_key not in payloads or payloads[module_key] == payload,
                      "overlapping immutable archives contain conflicting complete module witnesses")
                payloads[module_key] = payload
                found.append({"module_key": module_key, "compile_key": encoded,
                    "store": deepcopy(self._receipts[key]), "nested_descriptor_verified": False})
        return found


def _requests(composition, definitions, archives, budget):
    _need(type(composition) is CompositionIndex and composition.partitioned
          and type(archives) is CompilerWitnessArchives and type(budget) is ObservedAcquisitionBudget,
          "regular composition, explicit immutable archives and independent budget required")
    budget.__post_init__()
    _need(type(definitions) is tuple and 0 < len(definitions) <= budget.max_definitions
          and all(type(ref) is SourceDefinitionReference for ref in definitions),
          "bounded original qualified definition selection required")
    _need(len({_bytes(encode(ref)) for ref in definitions}) == len(definitions), "duplicate selected definition")
    inputs = composition.source_inputs()
    seed = composition.inventory_component("call_sources")
    _need(seed.get("schema") == "scar.call-source-seeds" and seed.get("schema_version") == 2
          and seed.get("compilation_profile") == CallCompilationProfile.RECORDED_FUTURE_FLAGS.value
          and seed.get("target_executed_by_resolver") is False,
          "observed acquisition requires the original recorded-flags source correspondence")
    model = seed["model"]
    captures, locations = {}, {}
    for index, raw in enumerate(model["codes"]):
        capture = decode(CodeCapture, raw)
        code = capture.code
        _need(code.key not in captures or captures[code.key] == code, "conflicting original complete captured descriptors")
        captures[code.key] = code
        locations.setdefault(code.key, []).append(composition.inventory_component_locator("call_sources", f"/model/codes/{index}"))
    links = {}
    for index, raw in enumerate(model["code_links"]):
        link = decode(CodeSourceLink, raw)
        _need(link.code not in links, "duplicate original code/source link")
        links[link.code] = index, link
    requests, frontiers = [], []
    for reference in definitions:
        reference.__post_init__()
        matching = [(code, index, link) for key, (index, link) in links.items()
                    if link.status is CallLinkStatus.VERIFIED and link.definition == reference.definition
                    and link.snapshot == reference.snapshot and link.source == reference.source
                    and (code := captures.get(key)) is not None]
        if not matching:
            frontiers.append({"definition": encode(reference), "status": "NO_ORIGINAL_OBSERVED_CODE_SOURCE_WITNESS"})
            continue
        # Real original source graph membership; a caller's qualified record
        # alone is not sufficient. No canonical body/target execution is used.
        composition.resolve_definition(reference)
        for captured, link_index, link in matching:
            _need(captured.filename == reference.snapshot.path, "original descriptor/source filename differs")
            levels = tuple(sorted(set(link.optimize_levels)))
            _need(levels and all(type(level) is int and level in (0, 1, 2) for level in levels),
                  "original verified link lacks recorded matching compiler variants")
            try:
                variants = [encode(compile_cache_key(reference.snapshot.path, reference.snapshot.fingerprint,
                    CallCompilationProfile.RECORDED_FUTURE_FLAGS, captured.flags, level,
                    compile_filename=captured.filename)) for level in levels]
                available = archives.metadata_variants(captured, reference.snapshot, levels)
            except ValueError as error:
                frontiers.append({"definition": encode(reference), "captured": encode(captured),
                    "status": "COMPILER_CONTEXT_OR_ARCHIVE_FRONTIER",
                    "error": {"type": type(error).__name__, "detail": str(error)}})
                continue
            request = {"definition": encode(reference), "captured": encode(captured),
                "source_link": encode(link), "captured_code_locators": locations[captured.key],
                "code_source_locator": composition.inventory_component_locator("call_sources", f"/model/code_links/{link_index}"),
                "compiler_basis": composition.original_code_source_origin(),
                "preferred_compile_key": variants[0], "recorded_compile_keys": variants,
                "available_module_metadata": available,
                "scope": "ORIGINAL_OBSERVED_CODE_SOURCE_CORRESPONDENCE",
                "captured_python_build_asserted_here": False,
                "runtime_observation_created": False}
            request["request_id"] = _sha(_bytes(request))
            requests.append(request)
            _need(len(requests) <= budget.max_requests, "observed request count ceiling exceeded")
    _need(composition.source_inputs() == inputs, "composition inputs changed during observed request derivation")
    return {"schema": "scar.observed-compiler-acquisition-plan", "schema_version": 1,
        "composition_inputs": inputs, "archives": archives.receipts(),
        "selected_definitions": len(definitions), "requests": requests, "frontiers": frontiers,
        "budget": asdict(budget), "original_compiler_basis": composition.original_code_source_origin(),
        "target_executed": False, "new_captures_created": False,
        "module_metadata_is_nested_descriptor_proof": False}


def plan_observed_witness_acquisition(composition, definitions, archives, *, budget=ObservedAcquisitionBudget()):
    """Derive bounded requests from original observed evidence, without compiling."""
    return _requests(composition, definitions, archives, budget)


def _attachment_requests(owner, origins, archives, budget):
    from scar.analysis.source_attachments import SourceAttachments
    _need(type(owner) is SourceAttachments and type(archives) is CompilerWitnessArchives
          and type(budget) is ObservedAcquisitionBudget, "normal attachment owner/archive/budget required")
    budget.__post_init__(); owner.require_unchanged()
    rows = owner.catalog_rows()
    by_origin = {(row["process_id"], row["code"]): row for row in rows}
    eligible = {key for key, row in by_origin.items() if row["status"] == "SOURCE_VERIFIED"}
    if origins is None:
        selected = tuple(sorted(eligible))
    else:
        _need(type(origins) is tuple and all(type(x) is EnteredCallCode for x in origins),
              "selection requires original typed entered-code origins")
        selected = tuple((x.process_id, x.code) for x in origins)
        _need(len(set(selected)) == len(selected) and set(selected) <= eligible,
              "selection repeats or changes an original verified code/source origin")
    _need(0 < len(selected) <= budget.max_definitions, "attachment selection exceeds independent bound")
    inputs, old_archives = owner.receipts(), archives.receipts()
    builds = sorted({row["python"] for row in owner.capture_declaration()["collection_metadata"]})
    requests, frontiers, sources = [], [], {}
    groups = [{"origin": encode(EnteredCallCode(*key)), "entered_invocations": row["entered_invocations"],
               "source_status": row["status"], "selection": "SELECTED" if key in selected else "RETAINED_NOT_SELECTED"}
              for key, row in by_origin.items()]
    for key in selected:
        witness = owner.code_witness(*key); row = witness["record"]
        captured, link = decode(CapturedCode, row["captured_code"]), decode(CodeSourceLink, row["code_source_link"])
        _need(link.status is CallLinkStatus.VERIFIED and link.snapshot is not None
              and link.code == captured.key == key[1] and captured.filename == link.snapshot.path,
              "original attachment descriptor/source witness contradicts its origin")
        levels = tuple(sorted(set(link.optimize_levels)))
        _need(levels and all(type(x) is int and x in (0, 1, 2) for x in levels),
              "original source witness lacks recorded optimize levels")
        original = owner._files[link.snapshot.path]
        snapshot_declaration = encode(owner._declaration(link.snapshot.path, "snapshot_artifact"))
        sources[link.snapshot.path] = {"snapshot": encode(link.snapshot),
            "snapshot_artifact": deepcopy(original["snapshot_artifact"]),
            "declaration": snapshot_declaration, "raw_sha256": original["raw_sha256"],
            "raw_bytes": original["raw_bytes"], "source_root": original["source_root"]}
        if builds != [sys.version]:
            frontiers.append({"origin": encode(EnteredCallCode(*key)), "status": "CAPTURED_PYTHON_BUILD_MISMATCH"})
            continue
        if original["snapshot_artifact"] is None:
            frontiers.append({"origin": encode(EnteredCallCode(*key)), "status": "ARCHIVED_SOURCE_SNAPSHOT_UNAVAILABLE"})
            continue
        try:
            keys = [encode(compile_cache_key(link.snapshot.path, link.snapshot.fingerprint,
                CallCompilationProfile.RECORDED_FUTURE_FLAGS, captured.flags, level,
                compile_filename=captured.filename)) for level in levels]
        except UnsupportedCompilationFlags as error:
            frontiers.append({"origin": encode(EnteredCallCode(*key)),
                "status": "COMPILER_CONTEXT_OR_ARCHIVE_FRONTIER", "error": {"type": type(error).__name__, "detail": str(error)}})
            continue
        available = archives.metadata_variants(captured, link.snapshot, levels)
        request = {"origin": encode(EnteredCallCode(*key)), "captured": encode(captured),
            "source_link": encode(link), "captured_code_locators": [encode(witness["descriptor_locator"])],
            "code_source_locator": encode(witness["code_source_locator"]),
            "record_locator": encode(witness["record_locator"]), "compiler_basis": inputs,
            "snapshot_declaration": snapshot_declaration,
            "preferred_compile_key": keys[0], "recorded_compile_keys": keys,
            "available_module_metadata": available, "scope": "ORIGINAL_ATTACHMENT_OBSERVED_CODE_SOURCE",
            "captured_python_build_asserted_here": True, "definition_membership_checked": False,
            "runtime_observation_created": False}
        request["request_id"] = _sha(_bytes(request)); requests.append(request)
        _need(len(requests) <= budget.max_requests, "attachment compiler request ceiling exceeded")
    owner.require_unchanged()
    _need(owner.receipts() == inputs and archives.receipts() == old_archives,
          "original attachment/archive inputs changed during planning")
    return {"schema": "scar.attachment-compiler-acquisition-plan", "schema_version": 1,
        "source_attachment_inputs": inputs, "archives": old_archives,
        "selected_origins": len(selected), "original_groups": len(rows),
        "original_invocations": sum(x["entered_invocations"] for x in rows),
        "groups": groups, "source_text_inputs": list(sources.values()),
        "requests": requests, "frontiers": frontiers, "budget": asdict(budget),
        "target_executed": False, "new_captures_created": False,
        "captured_python_builds": builds, "compiler_python_build": sys.version,
        "captured_python_build_matches": builds == [sys.version],
        "definition_membership_checked": False, "module_metadata_is_nested_descriptor_proof": False}


def plan_attachment_witness_acquisition(owner, archives, *, origins=None, budget=ObservedAcquisitionBudget()):
    """Original complete observed descriptors/snapshots, without graph or compile."""
    return _attachment_requests(owner, origins, archives, budget)


def acquire_attachment_witnesses(owner, archives, out_dir, *, origins=None, producer,
                                 budget=ObservedAcquisitionBudget(), store_budget=CodeWitnessBudget(), progress=None):
    """New static compiler archive over original snapshots; no Run/body promotion."""
    return _acquire_witnesses(owner, origins, archives, out_dir, producer=producer,
        budget=budget, store_budget=store_budget, progress=progress, attachment=True)


def acquire_observed_witnesses(composition, definitions, archives, out_dir, *, producer,
                               budget=ObservedAcquisitionBudget(), store_budget=CodeWitnessBudget(), progress=None):
    """Existing composition-based acquisition; original defaults/report unchanged."""
    return _acquire_witnesses(composition, definitions, archives, out_dir, producer=producer,
        budget=budget, store_budget=store_budget, progress=progress)


def _acquire_witnesses(composition, definitions, archives, out_dir, *, producer,
                       budget, store_budget, progress, attachment=False):
    """Shared original writer/checkpoint/independent-readonly acquisition loop."""
    from scar.analysis.source_attachments import SourceAttachments, ArchivedSourceUnavailable
    _need(type(attachment) is bool and (not attachment or type(composition) is SourceAttachments),
          "attachment mode requires its normal original owner")
    _need(type(store_budget) is CodeWitnessBudget and type(budget) is ObservedAcquisitionBudget
          and type(producer) is dict and bool(producer)
          and (progress is None or callable(progress)), "explicit producer/typed writer budget/progress required")
    store_budget.__post_init__(); budget.__post_init__()
    output = Path(out_dir).absolute()
    _need(output == output.resolve() and not output.exists() and not output.is_symlink(),
          "acquisition output must be a fresh canonical directory")
    output.mkdir(mode=0o700)
    started = time.monotonic()
    attempts, verified_new, writer = [], [], None

    def publish(name, value, maximum):
        raw = _bytes(value)
        _need(len(raw) <= maximum, "acquisition record/report byte ceiling exceeded")
        temporary = output / ("." + name + ".tmp")
        with temporary.open("xb") as stream:
            stream.write(raw)
        temporary.replace(output / name)

    def checkpoint(status):
        publish("checkpoint.json", {"schema": "scar.attachment-compiler-acquisition-checkpoint" if attachment else "scar.observed-compiler-acquisition-checkpoint", "schema_version": 1,
            "status": status, "attempts": attempts, "elapsed_s": time.monotonic() - started,
            "writer_counts": dict(writer.counts) if writer is not None else None,
            "target_executed": False, "source_prepared": False,
            "transformation_authorized": False}, budget.max_report_bytes)

    try:
        plan = (_attachment_requests(composition, definitions, archives, budget) if attachment
                else _requests(composition, definitions, archives, budget))
        publish("plan.json", plan, budget.max_report_bytes)
        writer = CodeWitnessStore(output / "archive", budget=store_budget, create=True,
            compile_missing=True, producer={"kind": "ORIGINAL_ARCHIVED_SOURCE_COMPLETE_DESCRIPTOR_ACQUISITION_V1" if attachment else "OBSERVED_COMPLETE_DESCRIPTOR_ACQUISITION_V1",
                "caller": deepcopy(producer),
                ("source_attachment_inputs" if attachment else "composition_inputs"):
                    plan["source_attachment_inputs" if attachment else "composition_inputs"]}, progress=progress)
        ordered = sorted(plan["requests"], key=lambda row: (_bytes(row["preferred_compile_key"]), row["request_id"]))
        for index, request in enumerate(ordered):
            row = {"request_id": request["request_id"], "index": index, "status": "BUILDING",
                "preferred_compile_key": request["preferred_compile_key"]}
            attempts.append(row)
            if index >= budget.max_attempts or time.monotonic() - started >= budget.max_elapsed_seconds:
                row["status"] = "NOT_DISPATCHED_BUDGET"; checkpoint("RUNNING"); continue
            checkpoint("RUNNING")
            attempt_started = time.monotonic()
            captured = decode(CapturedCode, request["captured"])
            link = decode(CodeSourceLink, request["source_link"])
            before = dict(writer.counts)
            try:
                candidates = request["available_module_metadata"]
                if candidates:
                    candidate = candidates[0]
                    store = archives.store_for(candidate["store"])
                    _, result = store.resolve(captured, link.snapshot,
                        (candidate["compile_key"]["optimize"],), allow_compile=False)
                    row.update(status="EXISTING_WITNESS_VERIFIED", store=store.receipt(), witness=result)
                else:
                    preferred = request["preferred_compile_key"]
                    if attachment:
                        writer.admit_archived_source(link.snapshot, source_owner=composition)
                    _, result = writer.resolve(captured, link.snapshot, (preferred["optimize"],), allow_compile=True)
                    row.update(status="WRITTEN_PENDING_READ_ONLY_REPLAY", witness=result)
                    verified_new.append((row, captured, link, preferred["optimize"]))
            except (OSError, ValueError, LookupError, SyntaxError, TypeError, OverflowError, RecursionError) as error:
                if not attachment and isinstance(error, LookupError):
                    raise  # Preserve the existing composition API exception contract.
                if attachment and not isinstance(error, (CodeWitnessUnavailable, ArchivedSourceUnavailable)):
                    row.update(status="HARD_REJECTED", error={"type": type(error).__name__, "detail": str(error)},
                        elapsed_s=time.monotonic() - attempt_started,
                        writer_delta={key: writer.counts[key] - before[key] for key in before})
                    checkpoint("FAILED")
                    raise
                row.update(status="FRONTIER", error={"type": type(error).__name__, "detail": str(error)})
            row.update(elapsed_s=time.monotonic() - attempt_started,
                writer_delta={key: writer.counts[key] - before[key] for key in before})
            _need(len(_bytes(row)) <= budget.max_record_bytes, "individual acquisition attempt byte ceiling exceeded")
            checkpoint("RUNNING")
            if progress is not None:
                progress({"stage": "OBSERVED_COMPILER_ATTEMPT", "request_id": request["request_id"],
                          "status": row["status"], "writer_counts": dict(writer.counts)})
        writer_receipt = writer.receipt()
        readonly = CodeWitnessStore(output / "archive", budget=store_budget)
        _need(readonly.receipt() == writer_receipt, "fresh archive changed before read-only replay")
        for row, captured, link, level in verified_new:
            try:
                if attachment:
                    _need(readonly.text(link.snapshot) == writer.text(link.snapshot),
                          "read-only archived source text differs from the admitted original")
                _, result = readonly.resolve(captured, link.snapshot, (level,), allow_compile=False)
                _need(result == row["witness"], "read-only nested descriptor/module/constant path differs")
                row.update(status="ACQUIRED_VERIFIED", store=readonly.receipt())
            except (OSError, ValueError, TypeError, RecursionError) as error:
                if attachment:
                    row.update(status="READ_ONLY_REPLAY_FAILED", error={"type": type(error).__name__, "detail": str(error)})
                    checkpoint("FAILED")
                    raise
                row.update(status="READ_ONLY_REPLAY_FAILED", error={"type": type(error).__name__, "detail": str(error)})
            checkpoint("READ_ONLY_REPLAY")
        if attachment:
            composition.require_unchanged()
        _need(archives.receipts() == plan["archives"] and
              (composition.receipts() == plan["source_attachment_inputs"] if attachment
               else composition.source_inputs() == plan["composition_inputs"]),
              "historical archive/composition inputs changed during acquisition")
        successful = sum(row["status"] in ("EXISTING_WITNESS_VERIFIED", "ACQUIRED_VERIFIED") for row in attempts)
        report = {"schema": "scar.attachment-compiler-acquisition" if attachment else "scar.observed-compiler-acquisition", "schema_version": 1,
            "status": "COMPLETE" if successful == len(attempts) and not plan["frontiers"] else "COMPLETE_WITH_FRONTIERS",
            ("selected_origins" if attachment else "selected_definitions"):
                plan["selected_origins" if attachment else "selected_definitions"], "requests": len(plan["requests"]),
            "attempts": attempts, "frontiers": plan["frontiers"], "archive": readonly.receipt(),
            "old_archives": archives.receipts(), "store_budget": asdict(store_budget),
            "acquisition_budget": asdict(budget), "writer_counts": dict(writer.counts),
            "read_only_counts": dict(readonly.counts), "unique_published_compile_keys": len(readonly.document["modules"]),
            "published_source_bytes": sum(row["artifact"]["bytes"] for row in readonly.document["sources"].values()),
            "published_module_bytes": sum(row["artifact"]["bytes"] for row in readonly.document["modules"].values()),
            "preferred_requested_compile_keys": len({_sha(_bytes(row["preferred_compile_key"])) for row in plan["requests"]}),
            "unique_attempted_compile_keys": len({_sha(_bytes(row["preferred_compile_key"])) for row in attempts
                if row.get("writer_delta", {}).get("compile_attempts", 0)}),
            "elapsed_s": time.monotonic() - started, "original_static_source_proof_recompiled": False,
            "new_observed_descriptor_witnesses_compiled": writer.counts["compile_attempts"],
            "captured_python_build_asserted_here": bool(attachment),
            "target_executed": False, "source_prepared": False, "captures_or_invocations_created": False,
            "whole_program_established": False, "transformation_authorized": False}
        if attachment:
            report.update(source_attachment_inputs=plan["source_attachment_inputs"],
                original_groups=plan["original_groups"], original_invocations=plan["original_invocations"],
                retained_groups=plan["groups"], graph_membership_checked=False,
                original_snapshots_used=True, live_source_reads=writer.counts["source_bytes_read"],
                captured_python_build_asserted_here=plan["captured_python_build_matches"])
        publish("report.json", report, budget.max_report_bytes); checkpoint(report["status"])
        return report
    except BaseException as error:
        try:
            checkpoint("INTERRUPTED" if isinstance(error, (KeyboardInterrupt, SystemExit)) else "FAILED")
            publish("failure.json", {"type": type(error).__name__, "detail": str(error),
                "elapsed_s": time.monotonic() - started, "archive_retained": (output / "archive").exists()},
                budget.max_record_bytes)
        except (OSError, ValueError):
            pass  # Original exception and every already-published checkpoint remain.
        raise


__all__ = ["CompilerWitnessArchives", "CompilerArchiveBudget", "ObservedAcquisitionBudget",
           "plan_observed_witness_acquisition", "acquire_observed_witnesses",
           "plan_attachment_witness_acquisition", "acquire_attachment_witnesses"]
