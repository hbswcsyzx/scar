"""Keep body diagnostics in their original artifacts and read them on demand.

Compaction changes only redundant manifest fields. Original source/body IDs,
artifact bytes, declaration positions and linker input projections stay fixed.
An unmatched diagnostic is retained; an invalid receipt aborts publication.
"""
from __future__ import annotations

from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import time


DIAGNOSTIC_FIELDS = ("gaps", "module_frontiers", "class_frontiers")


def _fields(fields):
    result = tuple(fields)
    if len(set(result)) != len(result) or any(field not in DIAGNOSTIC_FIELDS for field in result):
        raise ValueError("select unique original body diagnostic fields")
    return result


def _diagnostic_refs(document):
    refs = {}
    for field in DIAGNOSTIC_FIELDS:
        if field in document:
            if type(document[field]) is not list:
                raise ValueError("body diagnostics must be original ordered lists")
            refs[field] = {"count": len(document[field]), "pointer": "#/" + field}
    return refs


def _body_inputs(unit):
    return {name: unit["artifacts"].get(name) for name in ("source", "semantic", "semantics", "control")}


def _check_envelope(row, document, inputs=None):
    if (document.get("schema") != "scar.static-body" or document.get("schema_version") != 1
            or document.get("entry_key") != row["entry_key"]
            or document.get("cache_key") != row.get("cache_key")
            or document.get("status") != row["status"]):
        raise ValueError("body diagnostic artifact differs from its original body ledger")
    if inputs is not None and document.get("inputs") != inputs:
        raise ValueError("body diagnostic artifact uses different original source/context inputs")


def body_diagnostics(row, read_fragment, *, fields=DIAGNOSTIC_FIELDS, unit=None):
    """Return requested original lists from legacy inline rows or body refs.

    The reader callback must verify the original stored/decoded byte receipts.
    Passing ``unit`` also checks all shared source/context inputs. Missing
    fields stay absent; absent diagnostics are not interpreted as empty lists.
    """
    fields = _fields(fields)
    result, document = {}, None
    refs = row.get("diagnostics", {})
    if type(refs) is not dict:
        raise ValueError("body diagnostics references must be an object")
    for field in fields:
        if field in row:
            if field in refs:
                raise ValueError("body diagnostic has conflicting inline and referenced representations")
            if type(row[field]) is not list:
                raise ValueError("inline body diagnostic must be an ordered list")
            result[field] = row[field]
            continue
        if field not in refs:
            continue
        reference = refs[field]
        if (type(reference) is not dict or set(reference) != {"count", "pointer"}
                or type(reference["count"]) is not int or reference["count"] < 0
                or reference["pointer"] != "#/" + field or "artifact" not in row):
            raise ValueError("body diagnostic reference does not address its original artifact field")
        if document is None:
            document = read_fragment(row["artifact"])
            _check_envelope(row, document, _body_inputs(unit) if unit is not None else None)
        values = document.get(field)
        if type(values) is not list or len(values) != reference["count"]:
            raise ValueError("body diagnostic reference count/field differs from its original artifact")
        result[field] = values
    return result


def _json_equal(left, right):
    """Exact JSON types matter: a changed bool is not an original integer."""
    pending = [(left, right)]
    while pending:
        left, right = pending.pop()
        if type(left) is not type(right):
            return False
        if type(left) is dict:
            if left.keys() != right.keys():
                return False
            pending.extend((left[key], right[key]) for key in left)
        elif type(left) is list:
            if len(left) != len(right):
                return False
            pending.extend(zip(left, right))
        elif type(left) is float:
            if repr(left) != repr(right):
                return False
        elif left != right:
            return False
    return True


def _inspect_body(task):
    from scar.analysis.static_program import _read_fragment
    directory, number, position, row, inputs = task
    root = Path(directory)
    relative = Path(row["artifact"]["path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("body diagnostic artifact escapes its original model")
    path = root / relative
    if path.resolve() != path or path.is_symlink() or not path.is_file():
        raise ValueError("body diagnostic artifact is absent or traverses symlinks")
    document = _read_fragment(root, row["artifact"])
    _check_envelope(row, document, inputs)
    matches, retained = {}, []
    for field in DIAGNOSTIC_FIELDS:
        if field not in row:
            continue
        if type(row[field]) is not list:
            retained.append((field, "INLINE_FIELD_NOT_LIST"))
        elif field in row.get("diagnostics", {}):
            retained.append((field, "INLINE_AND_REFERENCE_BOTH_PRESENT"))
        elif field not in document:
            retained.append((field, "ORIGINAL_ARTIFACT_FIELD_NOT_RECORDED"))
        elif type(document[field]) is not list or not _json_equal(row[field], document[field]):
            retained.append((field, "ORIGINAL_ARTIFACT_VALUE_DIFFERS"))
        else:
            matches[field] = {"count": len(document[field]), "pointer": "#/" + field}
    return number, position, matches, retained


def _verified_rows(tasks, jobs):
    if jobs == 1:
        yield from map(_inspect_body, tasks)
        return
    # Keep at most 2*jobs records in flight. Workers return only counts and
    # decisions, never parsed graphs or the large diagnostic arrays.
    iterator = iter(tasks)
    with ProcessPoolExecutor(max_workers=jobs, mp_context=multiprocessing.get_context("spawn")) as executor:
        pending = set()
        try:
            for _ in range(jobs * 2):
                task = next(iterator, None)
                if task is not None:
                    pending.add(executor.submit(_inspect_body, task))
            while pending:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    yield future.result()
                    task = next(iterator, None)
                    if task is not None:
                        pending.add(executor.submit(_inspect_body, task))
        except BaseException:
            for future in pending:
                future.cancel()
            raise


def compact_static_diagnostics(directory, *, jobs=8):
    """Verify every candidate and atomically replace only manifest.json.

    Bad receipts or inconsistent envelope ownership raise before publication.
    Nonduplicate/unbacked fields remain inline and are individually reported.
    The sole temporary file holds the new manifest and is removed on failure;
    there is no old-version checkout, graph rewrite or retained backup.
    """
    from scar.analysis.static_calls import input_basis_unit
    from scar.analysis.static_program import _json
    if type(jobs) is not int or not 1 <= jobs <= 32:
        raise ValueError("diagnostic workers must be in [1, 32]")
    started = time.monotonic()
    root = Path(directory).absolute()
    path = root / "manifest.json"
    if root.resolve() != root or path.resolve() != path or path.is_symlink():
        raise ValueError("diagnostic model must not traverse symlinks")
    before_stat = path.stat()
    original = path.read_bytes()
    manifest = json.loads(original)
    if (manifest.get("schema") != "scar.static-program" or manifest.get("schema_version") != 1
            or type(manifest.get("units")) is not list):
        raise ValueError("unsupported original static model")
    # Serialize the baseline projection once, so an accidental in-place
    # mutation cannot also change a shallowly shared comparison snapshot.
    basis = _json([input_basis_unit(unit) for unit in manifest["units"]])
    tasks, retained = [], []
    for number, unit in enumerate(manifest["units"]):
        for position, row in enumerate(unit["bodies"]):
            fields = [field for field in DIAGNOSTIC_FIELDS if field in row]
            if not fields:
                continue
            if "artifact" not in row:
                retained.extend({"unit": number, "body": position, "field": field,
                                 "reason": "ORIGINAL_BODY_ARTIFACT_UNAVAILABLE"} for field in fields)
                continue
            # Avoid pickling all the unrelated per-row compiler/source facts.
            selected = {name: row[name] for name in ("entry_key", "status", "cache_key", "artifact", "diagnostics", *fields) if name in row}
            tasks.append((str(root), number, position, selected, _body_inputs(unit)))
    compacted, occurrences, verified, changed_bodies = Counter(), Counter(), 0, 0
    for number, position, refs, unmatched in _verified_rows(tasks, jobs):
        row = manifest["units"][number]["bodies"][position]
        verified += 1
        if refs:
            row.setdefault("diagnostics", {}).update(refs)
            changed_bodies += 1
            for field, reference in refs.items():
                del row[field]
                compacted[field] += 1
                occurrences[field] += reference["count"]
        retained.extend({"unit": number, "body": position, "field": field, "reason": reason}
                        for field, reason in unmatched)
    after_basis = _json([input_basis_unit(unit) for unit in manifest["units"]])
    if basis != after_basis:
        raise ValueError("diagnostic compaction changed original linker inputs/body declarations")
    output = _json(manifest) if changed_bodies else original
    temporary = None
    try:
        if output != original:
            descriptor, temporary = tempfile.mkstemp(prefix=".scar-static-manifest-", dir=root.parent)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(output)
                stream.flush()
                os.fsync(stream.fileno())
                os.fchmod(stream.fileno(), before_stat.st_mode & 0o777)
            if path.read_bytes() != original:
                raise ValueError("current manifest changed while diagnostics were checked; no publication performed")
            os.replace(temporary, path)
            temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
    return {"schema": "scar.static-diagnostic-compaction", "schema_version": 1,
            "status": "COMPACTED" if output != original else "UNCHANGED",
            "bodies_verified": verified, "bodies_changed": changed_bodies,
            "fields_compacted": dict(compacted), "diagnostic_records_referenced": dict(occurrences),
            "retained": sorted(retained, key=lambda x: (x["unit"], x["body"], x["field"])),
            "before_bytes": len(original), "after_bytes": len(output), "bytes_saved": len(original) - len(output),
            "before_sha256": hashlib.sha256(original).hexdigest(), "after_sha256": hashlib.sha256(output).hexdigest(),
            "original_linker_inputs_unchanged": True, "original_artifact_declarations_unchanged": True,
            "original_input_basis_sha256": hashlib.sha256(basis).hexdigest(),
            "fragments_rewritten": 0, "target_executed": False, "jobs": jobs,
            "max_decoded_body_bytes": max((task[3]["artifact"]["decoded_bytes"] for task in tasks), default=0),
            "seconds": time.monotonic() - started}


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory")
    parser.add_argument("--jobs", type=int, default=8)
    args = parser.parse_args(argv)
    result = compact_static_diagnostics(args.directory, jobs=args.jobs)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
