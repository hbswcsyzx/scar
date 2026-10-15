"""Compact seed schema checks; these fixtures are not raw/source proof evidence."""
from copy import deepcopy
from dataclasses import replace

import pytest

from scar.ir.program.call_edges import (
    CallEdgeBudget, CallEdgeIssue, CallEdgeIssueKind, CallLinkStatus,
    CallRecordAnchor, CallTraceFile, CapturedCode, CodeCapture, CodeSourceLink,
    InvocationKey,
)
from scar.ir.program.call_seeds import (
    CallSourceSeedModel, EnteredCodeGroup, SeedCollectionMetadata, SeedCollectorLimits,
)
from scar.ir.record_codec import decode, encode
from scar.ir.semantics_v2 import SourceSnapshot
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import OperationDefinitionID, SourceAtomID


KEY = "pycode-v2:" + "a" * 64
OTHER = "pycode-v2:" + "b" * 64
SHA = "c" * 64


def fixture(pid=1):
    directory, root = "/trace", "/project"
    files = tuple(CallTraceFile(f"{directory}/call-{family}.{pid}.{suffix}", family, pid, SHA, size, lines)
                  for family, suffix, size, lines in (("codes", "jsonl", 10, 1), ("events", "jsonl", 20, 4),
                                                      ("meta", "json", 30, 1)))
    code = CapturedCode(KEY, root + "/raw.py", "f", 1, 3, ("x",))
    capture = CodeCapture(code, CallRecordAnchor(files[0].path, 1, SHA), pid)
    group = EnteredCodeGroup(pid, KEY, 2, InvocationKey(pid, 10, 1), InvocationKey(pid, 20, 2),
                             CallRecordAnchor(files[1].path, 1, SHA, 1), CallRecordAnchor(files[1].path, 3, SHA, 3))
    metadata = SeedCollectionMetadata(pid, SeedCollectorLimits(20, 1000, 10, 10, 10, 10),
                                      4, 2, 1, 30, 0, 0, 0, 0, 0, 0,
                                      event_attempts=4, invocation_attempts=2, active_frames=0, path_gaps=0, io_failed=False)
    snapshot = SourceSnapshot(code.filename, "sha256:" + SHA)
    source = SourceReference(SourceAtomID("atom"), code.filename, snapshot.fingerprint, 1, 2, 0, 12)
    link = CodeSourceLink(KEY, CallLinkStatus.VERIFIED, snapshot, OperationDefinitionID("definition"), source, (0, 1, 2))
    return CallSourceSeedModel(directory, root, CallEdgeBudget(), files, (capture,), (group,), (link,), (metadata,), ())


def raw_metadata():
    item = fixture().collection_metadata[0]
    raw = item.to_dict()
    raw.pop("error_count")
    raw.update(schema="scar.call-edge-trace", schema_version=1, errors=[],
               reference_contents_observed=False, callable_environment_established=False,
               project_root="/project", python="test interpreter", wall_ns=100, scope="raw scope")
    return raw


def test_typed_model_roundtrip_is_structural_not_a_source_replay_claim():
    model = fixture()
    assert CallSourceSeedModel.from_dict(model.to_dict()) == model
    assert decode(CallSourceSeedModel, encode(model)) == model
    assert model.eligible_groups() == model.groups
    assert model.eligible_code_links() == model.code_links
    assert model.summary()["counts"]["entered_invocations"] == 2
    assert not any(model.authority_flags().values())
    assert "schema" not in model.to_dict()  # The public replaying report owns it.


@pytest.mark.parametrize("record", [fixture().groups[0], fixture().collection_metadata[0], fixture().collection_metadata[0].limits])
def test_each_compact_record_has_a_strict_decoder(record):
    assert type(record).from_dict(record.to_dict()) == record
    wire = record.to_dict()
    wire["references"] = []
    with pytest.raises(ValueError):
        type(record).from_dict(wire)


@pytest.mark.parametrize("field,value", [
    ("process_id", True), ("process_id", 0), ("count", False), ("count", 0), ("count", 4),
    ("code", "pycode-v2:" + "A" * 64), ("code", "code:name"),
    ("first_invocation", InvocationKey(2, 10, 1)),
    ("last_invocation", InvocationKey(1, 20, 1)),
    ("first_anchor", CallRecordAnchor("/trace/call-events.1.jsonl", 1, SHA)),
    ("last_anchor", CallRecordAnchor("/trace/call-events.1.jsonl", 1, SHA, 1)),
    ("last_anchor", CallRecordAnchor("/trace/other.jsonl", 3, SHA, 3)),
])
def test_group_rejects_invalid_identity_order_or_count(field, value):
    with pytest.raises(ValueError):
        replace(fixture().groups[0], **{field: value})


def test_single_entry_requires_same_invocation_and_anchor():
    group = fixture().groups[0]
    with pytest.raises(ValueError):
        replace(group, count=1)
    single = replace(group, count=1, last_invocation=group.first_invocation, last_anchor=group.first_anchor)
    assert EnteredCodeGroup.from_dict(single.to_dict()) == single


@pytest.mark.parametrize("field,value", [
    ("process_id", True), ("events", True), ("codes", -1), ("events", 3), ("open_invocations", 3),
    ("unknown_exits", 3), ("suspended_exits", 3), ("event_attempts", 5),
    ("invocation_attempts", 3), ("active_frames", 1), ("path_gaps", 3),
    ("error_count", -1), ("io_failed", 1), ("limits", {"max_events": 20}),
])
def test_metadata_rejects_incoherent_counts_and_nonexact_types(field, value):
    with pytest.raises(ValueError):
        replace(fixture().collection_metadata[0], **{field: value})


@pytest.mark.parametrize("field", ["max_events", "max_bytes", "max_codes", "max_values", "max_path", "max_references"])
def test_limits_do_not_accept_bool_as_integer(field):
    with pytest.raises(ValueError):
        replace(fixture().collection_metadata[0].limits, **{field: True})


def test_compact_metadata_excludes_unknown_reference_arrays_and_preserves_absence():
    raw = raw_metadata()
    raw["future_extension"] = {"references": ["do not retain"] * 10000}
    raw["errors"] = ["TypeError", "ValueError"]
    for name in ("event_attempts", "invocation_attempts", "active_frames", "path_gaps", "io_failed"):
        del raw[name]
    del raw["limits"]["max_references"]
    compact = SeedCollectionMetadata.from_metadata(raw)
    assert compact.error_count == 2
    assert compact.event_attempts is compact.io_failed is compact.limits.max_references is None
    assert "future_extension" not in compact.to_dict() and "errors" not in compact.to_dict()
    assert len(str(compact.to_dict())) < 1000


@pytest.mark.parametrize("field,value", [
    ("schema_version", True), ("schema_version", 2), ("errors", [object()]),
    ("reference_contents_observed", True), ("callable_environment_established", True),
])
def test_raw_projection_cannot_launder_unsupported_schema_or_authority(field, value):
    raw = raw_metadata(); raw[field] = value
    with pytest.raises(ValueError):
        SeedCollectionMetadata.from_metadata(raw)


def test_same_code_across_processes_is_allowed_but_not_same_process_duplicate():
    left, right = fixture(1), fixture(2)
    model = replace(left, files=left.files + right.files, codes=left.codes + right.codes,
                    groups=left.groups + right.groups,
                    collection_metadata=left.collection_metadata + right.collection_metadata)
    assert len(model.eligible_groups()) == 2 and len(model.eligible_code_links()) == 1
    with pytest.raises(ValueError, match="duplicate"):
        replace(left, codes=left.codes * 2)
    with pytest.raises(ValueError, match="duplicate"):
        replace(left, groups=left.groups * 2)
    with pytest.raises(ValueError, match="conflicting"):
        replace(model, codes=(left.codes[0], replace(right.codes[0], code=replace(right.codes[0].code, qualname="other"))))


def test_missing_process_capture_cannot_borrow_another_process_descriptor():
    left, right = fixture(1), fixture(2)
    absent_file = replace(right.files[0], raw_bytes=0, lines=0)
    absent_meta = replace(right.collection_metadata[0], codes=0, bytes=20)
    gap = CallEdgeIssue(CallEdgeIssueKind.MISSING_CODE, "missing local code capture", right.groups[0].first_anchor)
    model = replace(left, files=left.files + (absent_file, *right.files[1:]),
                    groups=left.groups + right.groups,
                    collection_metadata=left.collection_metadata + (absent_meta,), issues=(gap,))
    assert model.eligible_groups() == left.groups
    with pytest.raises(ValueError, match="anchored gap"):
        replace(model, issues=())


def test_caller_only_descriptor_is_manifest_data_and_never_an_entered_seed():
    model = fixture()
    extra = replace(model.codes[0], code=replace(model.codes[0].code, key=OTHER, qualname="caller"),
                    anchor=replace(model.codes[0].anchor, line_number=2))
    result = replace(model, codes=(*model.codes, extra),
                     files=(replace(model.files[0], raw_bytes=20, lines=2), *model.files[1:]),
                     collection_metadata=(replace(model.collection_metadata[0], codes=2, bytes=40),))
    assert result.eligible_code_links() == model.code_links
    assert result.summary()["counts"]["entered_code_groups"] == 1
    with pytest.raises(ValueError, match="entered-code"):
        replace(result, code_links=(*result.code_links, replace(result.code_links[0], code=OTHER)))


@pytest.mark.parametrize("duplicate", ["invocation", "event_index"])
def test_distinct_groups_cannot_reuse_the_same_retained_endpoint(duplicate):
    model = fixture()
    group = model.groups[0]
    first = replace(group, count=1, last_invocation=group.first_invocation, last_anchor=group.first_anchor)
    second_invocation = group.first_invocation if duplicate == "invocation" else group.last_invocation
    second_anchor = replace(group.last_anchor, index=1) if duplicate == "event_index" else group.last_anchor
    second = EnteredCodeGroup(1, OTHER, 1, second_invocation, second_invocation, second_anchor, second_anchor)
    extra = replace(model.codes[0], code=replace(model.codes[0].code, key=OTHER, qualname="second"),
                    anchor=replace(model.codes[0].anchor, line_number=2))
    with pytest.raises(ValueError, match="endpoints share"):
        replace(model, groups=(first, second), codes=(*model.codes, extra),
                files=(replace(model.files[0], raw_bytes=20, lines=2), *model.files[1:]),
                collection_metadata=(replace(model.collection_metadata[0], codes=2, bytes=40),))


def test_verified_code_without_unique_definition_is_not_positive_source_seed():
    model = fixture()
    module_link = replace(model.code_links[0], definition=None, source=None)
    result = replace(model, code_links=(module_link,))
    assert result.eligible_groups() == result.eligible_code_links() == ()
    incomplete = CodeSourceLink(KEY, CallLinkStatus.INCOMPLETE)
    assert replace(model, code_links=(incomplete,)).eligible_groups() == ()


@pytest.mark.parametrize("mutation", [
    "extra_authority", "nested_extra", "missing_field", "bool_pid", "bool_thread", "bool_invocation",
    "invalid_hash", "wrong_id_namespace", "wrong_source_fingerprint", "unpaired_definition", "wrong_source_path",
    "false_verified", "code_anchor_event_index", "event_anchor_outside_manifest", "duplicate_link",
    "drop_group", "extra_metadata", "missing_process_file", "relative_trace", "raw_budget", "event_budget",
    "code_budget", "process_budget", "source_budget",
])
def test_model_decoder_rejects_structural_tampering(mutation):
    wire = deepcopy(fixture().to_dict())
    if mutation == "extra_authority":
        wire["transformation_authorized"] = True
    elif mutation == "nested_extra":
        wire["collection_metadata"][0]["references"] = []
    elif mutation == "missing_field":
        del wire["budget"]
    elif mutation == "bool_pid":
        wire["groups"][0]["process_id"] = True
    elif mutation == "bool_thread":
        wire["groups"][0]["first_invocation"]["thread_id"] = False
    elif mutation == "bool_invocation":
        wire["groups"][0]["first_invocation"]["invocation_id"] = True
    elif mutation == "invalid_hash":
        wire["files"][0]["raw_sha256"] = "bad"
    elif mutation == "wrong_id_namespace":
        wire["code_links"][0]["definition"]["kind"] = "source"
    elif mutation == "wrong_source_fingerprint":
        wire["code_links"][0]["source"]["fingerprint"] = "sha256:" + "d" * 64
    elif mutation == "unpaired_definition":
        wire["code_links"][0]["source"] = None
    elif mutation == "wrong_source_path":
        wire["code_links"][0]["snapshot"]["path"] = "/elsewhere/raw.py"
    elif mutation == "false_verified":
        wire["code_links"][0]["status"] = "INCOMPLETE"
    elif mutation == "code_anchor_event_index":
        wire["codes"][0]["anchor"]["index"] = 1
    elif mutation == "event_anchor_outside_manifest":
        wire["groups"][0]["last_anchor"]["line_number"] = 10
    elif mutation == "duplicate_link":
        wire["code_links"] *= 2
    elif mutation == "drop_group":
        wire["groups"] = []
    elif mutation == "extra_metadata":
        wire["collection_metadata"] *= 2
    elif mutation == "missing_process_file":
        wire["files"].pop()
    elif mutation == "relative_trace":
        wire["trace_directory"] = "trace"
    elif mutation == "raw_budget":
        wire["budget"]["max_raw_bytes"] = 1
    elif mutation == "event_budget":
        wire["budget"]["max_events"] = 1
    elif mutation == "code_budget":
        wire["budget"]["max_codes"] = 0
    elif mutation == "process_budget":
        wire["budget"]["max_processes"] = 0
    elif mutation == "source_budget":
        wire["budget"]["max_source_files"] = 0
    with pytest.raises(ValueError):
        CallSourceSeedModel.from_dict(wire)


def test_authority_is_computed_and_not_a_constructor_field():
    model = fixture()
    flags = model.authority_flags()
    assert len(flags) == 5 and all(value is False for value in flags.values())
    flags["transformation_authorized"] = True
    assert model.authority_flags()["transformation_authorized"] is False
    with pytest.raises(TypeError):
        replace(model, transformation_authorized=True)


def test_serialization_rechecks_records_modified_outside_frozen_constructor():
    model = fixture()
    object.__setattr__(model.groups[0], "count", True)
    with pytest.raises(ValueError):
        model.to_dict()
