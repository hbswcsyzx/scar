"""One bounded check of the mutable-input / sealed-snapshot boundary."""
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from scar.analysis.program_lowering import prepare_source
from scar.analysis.structured_lowering import require_valid_structured_body
from scar.ir.program.codec import dumps
from scar.ir.program.functions import BodyLoweringProfile
from scar.ir.record_codec import encode


def fingerprint(body):
    doc = dict(graph=json.loads(dumps(body.graph)), metadata=encode(body.metadata),
               interface=encode(body.interface), structured=encode(body.structured))
    payload = json.dumps(doc, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


with TemporaryDirectory(prefix="scar-sealed-boundary-") as directory:
    root = Path(directory)
    path = root / "entry.py"
    path.write_text("def value(x):\n    return x\n")
    prepared = prepare_source(path, project_root=root)
    options = dict(expand_candidates=False, profile=BodyLoweringProfile.STRUCTURED_ENV)
    ordinary_before = prepared.lower("value", **options)
    session = prepared.seal_for_lowering()
    sealed_before = session.lower("value", **options)
    assert fingerprint(ordinary_before) == fingerprint(sealed_before)
    prepared.control.semantic_digest = "sha256:" + "0" * 64
    try:
        prepared.lower("value", **options)
    except ValueError as error:
        ordinary_rejection = str(error)
    else:
        raise AssertionError("ordinary lower reused a stale source proof")
    sealed_after = session.lower("value", **options)
    assert fingerprint(sealed_after) == fingerprint(sealed_before)
    try:
        require_valid_structured_body(sealed_after.structured, sealed_after.graph,
            sealed_after.interface, sealed_after.metadata,
            semantic=prepared.semantic, control=prepared.control)
    except ValueError as error:
        public_rejection = str(error)
    else:
        raise AssertionError("public validation reused the sealed source proof")
    try:
        prepared.seal_for_lowering()
    except ValueError as error:
        reseal_rejection = str(error)
    else:
        raise AssertionError("resealing accepted mismatched current source layers")
    result = dict(schema="scar.sealed-source-boundary", schema_version=1,
        ordinary_changed_source_rejected=True, ordinary_rejection=ordinary_rejection,
        explicit_snapshot_unchanged=True, public_validation_changed_source_rejected=True,
        public_rejection=public_rejection, changed_source_reseal_rejected=True,
        reseal_rejection=reseal_rejection,
        target_executed=False, whole_program_model_established=False)
    print(json.dumps(result, indent=2))
