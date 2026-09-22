"""Source/code correspondence must reproduce loaded code, never execute it."""
import __future__
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import CodeType

from scar.analysis.correspondence_v2 import (
    CodeSourceWitness, CompileContext, JoinReason, JoinStatus, SourceJoinRequest,
    build_correspondence,
)
from scar.ir.frontend_v2 import build_semantic
from scar.ir.ids import CodeID
from scar.ir.record_codec import decode, encode
from scar.ir.v2 import OperationDefinitionID, OperationInstanceID, canonical_json
from scar.trace.normalize_v2 import normalize_records


def _codes(code):
    yield code
    for value in code.co_consts:
        if isinstance(value, CodeType):
            yield from _codes(value)


def _source(tmp_path, text, **compile_options):
    path = tmp_path / "program.py"
    path.write_text(text)
    graph = build_semantic(path).graph
    module = compile(text, str(path), "exec", dont_inherit=True, **compile_options)
    return path, graph, list(_codes(module))


def _runtime(codes):
    return normalize_records([
        {"kind": "module_call", "index": index, "ts_ns": index * 100 + 50,
         "duration_ns": 10, "invocation_id": index + 1,
         "code_id": CodeID.from_code(code).key(), "inputs": [], "outputs": [],
         "metadata": {"process_id": 1, "thread_id": 2, "clock_domain": "perf_counter"}}
        for index, code in enumerate(codes)
    ]).bundle


def test_exact_code_witness_preserves_runtime_stubs_and_one_to_many_invocations(tmp_path):
    _, source, codes = _source(tmp_path, "def compute(x):\n    return x + 1\n")
    runtime = _runtime([codes[1], codes[1], codes[1]])
    source_before, runtime_before = canonical_json(source), canonical_json(runtime)
    result = build_correspondence(source, runtime)
    assert result.report["status_counts"][JoinStatus.VERIFIED.value] == 1
    assert result.report["instance_status_counts"][JoinStatus.VERIFIED.value] == 3
    assert len(result.graph.records) == 3
    assert len({record.instance for record in result.graph.records.values()}) == 3
    assert all(record.definition in source.definitions for record in result.graph.records.values())
    assert canonical_json(source) == source_before
    assert canonical_json(runtime) == runtime_before
    row = result.report["rows"][0]
    assert row["source_fingerprint"] != row["witnesses"][0]["compiled_code_digest"]
    assert all(w["extent"] == "code_object_only" for w in row["witnesses"])


def test_source_edit_after_load_does_not_join_by_path(tmp_path):
    path, _, codes = _source(tmp_path, "def compute():\n    return 1\n")
    runtime = _runtime([codes[1]])
    path.write_text("def compute():\n    return 2\n")
    changed_source = build_semantic(path).graph
    result = build_correspondence(changed_source, runtime)
    assert not result.graph.records
    assert result.report["rows"][0]["reason"] == JoinReason.CODE_DIGEST_MISMATCH.value
    request = result.report["requests"][0]
    assert request["location"]["path"] == str(path)
    assert request["candidate_definitions"]
    assert "compile flags/optimize" in request["fields"]
    assert request["rerun"]["required_phase"]
    assert request["action"] == "CONTRACT"
    assert request["rerun"]["executable"] is False


def test_source_snapshot_must_match_the_selected_semantic_graph_version(tmp_path):
    path, graph, codes = _source(tmp_path, "def compute():\n    return 1\n")
    path.write_text("def compute():\n    return 2\n")
    result = build_correspondence(graph, _runtime([codes[1]]))
    assert result.report["rows"][0]["reason"] == JoinReason.SOURCE_FINGERPRINT_MISMATCH.value
    assert not result.graph.records


def test_nested_code_join_never_executes_module(tmp_path):
    sentinel = tmp_path / "executed"
    text = (f"open({str(sentinel)!r}, 'w').write('bad')\n"
            "def outer(x):\n"
            "    def inner(y):\n"
            "        return x + y\n"
            "    return inner\n"
            "raise RuntimeError('must not execute')\n")
    _, source, codes = _source(tmp_path, text)
    result = build_correspondence(source, _runtime(codes))
    assert not sentinel.exists()
    assert result.report["target_executed"] is False
    assert result.report["status_counts"]["VERIFIED"] == 3
    assert not result.report["requests"]


def test_decorated_async_callable_uses_decorator_first_line(tmp_path):
    _, source, codes = _source(tmp_path, "@unresolved_decorator\nasync def compute(x):\n    return x\n")
    assert codes[1].co_firstlineno == 1
    result = build_correspondence(source, _runtime([codes[1]]))
    assert result.report["status_counts"]["VERIFIED"] == 1
    record = next(iter(result.graph.records.values()))
    assert source.definitions[record.definition].source_start == 2


def test_ambiguous_lambda_locations_keep_all_candidates(tmp_path):
    _, source, codes = _source(tmp_path, "first, second = lambda x: x + 1, lambda x: x + 2\n")
    result = build_correspondence(source, _runtime([codes[1]]))
    assert result.report["status_counts"]["AMBIGUOUS"] == 1
    assert len(result.graph.records) == 2
    assert all(record.ambiguous for record in result.graph.records.values())
    assert result.report["requests"][0]["reason"] == JoinReason.AMBIGUOUS_SOURCE_DEFINITION.value


def test_duplicate_semantic_scopes_remain_explicit_candidates(tmp_path):
    _, source, codes = _source(tmp_path, "def compute(x):\n    return x\n")
    function = next(d for d in source.definitions.values() if d.metadata.get("phase") == "call_time")
    duplicate_id = OperationDefinitionID("alternative-source-scope")
    source.definitions[duplicate_id] = replace(deepcopy(function), id=duplicate_id,
                                               input_slots=(), output_slots=(), state_slots=())
    result = build_correspondence(source, _runtime([codes[1]]))
    assert result.report["status_counts"]["AMBIGUOUS"] == 1
    assert {r.definition for r in result.graph.records.values()} == {function.id, duplicate_id}


def test_optimize_trials_reproduce_exact_code_without_claiming_original_context(tmp_path):
    _, source, codes = _source(tmp_path, "def compute(x):\n    'docstring'\n    assert x\n    return x\n", optimize=2)
    runtime = _runtime([codes[1]])
    mismatch = build_correspondence(source, runtime, compile_contexts=(CompileContext(optimize=0),))
    assert mismatch.report["status_counts"]["MISMATCH"] == 1
    result = build_correspondence(source, runtime)
    assert result.report["status_counts"]["VERIFIED"] == 1
    witnesses = result.report["rows"][0]["witnesses"]
    assert {w["compile_context"]["optimize"] for w in witnesses} == {2}
    assert all(w["original_compile_context_attested"] is False for w in witnesses)


def test_explicit_future_compile_flags_require_exact_hash_reproduction(tmp_path):
    flags = __future__.annotations.compiler_flag
    _, source, codes = _source(tmp_path, "def compute(x):\n    return x\n", flags=flags)
    runtime = _runtime([codes[1]])
    mismatch = build_correspondence(source, runtime)
    assert mismatch.report["status_counts"]["MISMATCH"] == 1
    result = build_correspondence(source, runtime, compile_contexts=(CompileContext(flags=flags),))
    assert result.report["status_counts"]["VERIFIED"] == 1


def test_raw_filename_is_not_normalized_to_make_code_hashes_match(tmp_path):
    text = "def compute(x):\n    return x\n"
    path, source, _ = _source(tmp_path, text)
    raw_filename = str(path.parent) + "/./program.py"
    code = list(_codes(compile(text, raw_filename, "exec", dont_inherit=True)))[1]
    runtime = _runtime([code])
    assert CodeID.from_code(code).source == str(path)
    mismatch = build_correspondence(source, runtime)
    assert mismatch.report["status_counts"]["MISMATCH"] == 1
    result = build_correspondence(source, runtime, filename_candidates={str(path): (str(path), raw_filename)})
    assert result.report["status_counts"]["VERIFIED"] == 1
    assert {w["compile_filename"] for w in result.report["rows"][0]["witnesses"]} == {raw_filename}


def test_compile_context_mismatch_requests_witness(tmp_path):
    _, source, codes = _source(tmp_path, "def compute(x):\n    return x\n")
    result = build_correspondence(source, _runtime([codes[1]]),
                                  compile_contexts=(CompileContext(python_version="0.0.0"),))
    assert not result.graph.records
    assert result.report["requests"][0]["reason"] == JoinReason.COMPILE_CONTEXT_UNSUPPORTED.value


def test_explicit_immutable_source_snapshot_can_join_when_disk_file_is_gone(tmp_path):
    text = "def compute(x):\n    return x\n"
    path, source, codes = _source(tmp_path, text)
    path.unlink()
    runtime = _runtime([codes[1]])
    missing = build_correspondence(source, runtime)
    assert missing.report["status_counts"]["MISSING"] == 1
    result = build_correspondence(source, runtime, source_texts={str(path): text})
    assert result.report["status_counts"]["VERIFIED"] == 1


def test_aggregate_profile_rows_do_not_create_source_invocations(tmp_path):
    _, source, _ = _source(tmp_path, "value = 1\n")
    runtime = normalize_records([{"kind": "torch_op", "metadata": {"aggregate": True},
                                  "duration_ns": 10, "resource": {"count": 25}}]).bundle
    result = build_correspondence(source, runtime)
    assert result.report["instances"] == result.report["definitions"] == 0
    assert not result.graph.records


def test_correspondence_reports_are_deterministic_and_leave_unselected_files_out_of_scope(tmp_path):
    _, source, codes = _source(tmp_path, "def compute(x):\n    return x\n")
    foreign = compile("foreign = 2\n", str(tmp_path / "unselected.py"), "exec", dont_inherit=True)
    runtime = _runtime([codes[1], foreign])
    first = build_correspondence(source, runtime)
    second = build_correspondence(source, runtime)
    assert first.report == second.report
    assert canonical_json(first.graph) == canonical_json(second.graph)
    assert first.report["status_counts"]["OUT_OF_SCOPE"] == 1


def test_witness_and_request_typed_roundtrip_preserves_context_and_ids():
    witness = CodeSourceWitness("/source.py", "sha256:" + "1" * 64,
                                "loaded-code-id", "pycode-sha256:" + "2" * 64,
                                "/./source.py", CompileContext(optimize=2), "compute", 4)
    assert decode(CodeSourceWitness, encode(witness)) == witness
    request = SourceJoinRequest(JoinReason.CODE_DIGEST_MISMATCH, "loaded source required",
                                 "/source.py", 4, OperationDefinitionID("runtime"),
                                 (OperationInstanceID("invocation"),),
                                 (OperationDefinitionID("candidate"),),
                                 ("events.jsonl:1",), ("raw co_filename",))
    assert decode(SourceJoinRequest, encode(request)) == request


def test_nested_class_and_method_scopes_remain_candidates_without_instantiation(tmp_path):
    _, source, codes = _source(tmp_path,
        "def outer():\n"
        "    class Inner:\n"
        "        def method(self):\n"
        "            return 3\n"
        "    return Inner\n")
    result = build_correspondence(source, _runtime(codes))
    # Legacy marshal flags can differ for class qualname constants. The child
    # method joins exactly; ancestor hashes stay closed rather than normalized.
    assert result.report["status_counts"]["VERIFIED"] >= 1
    assert all(row["candidates"] for row in result.report["rows"])
    assert all(row["reason"] in {JoinReason.EXACT_CODE_REPRODUCED.value,
                                  JoinReason.CODE_DIGEST_MISMATCH.value}
               for row in result.report["rows"])
    method_row = next(row for row in result.report["rows"]
                      if ":outer.<locals>.Inner.method:" in row["loaded_code_id"])
    assert method_row["status"] == "VERIFIED"


def test_missing_loaded_digest_requests_contract_instead_of_path_only_join(tmp_path):
    _, source, codes = _source(tmp_path, "def compute():\n    return 1\n")
    runtime = _runtime([codes[1]])
    runtime_definition = next(iter(runtime.evidence.instances.values())).definition
    definition = runtime.semantic.definitions[runtime_definition]
    parsed = CodeID.parse_key(definition.code_id)
    runtime.semantic.definitions[runtime_definition] = replace(
        definition, code_id=replace(parsed, version="unknown").key())
    result = build_correspondence(source, runtime)
    assert not result.graph.records
    assert result.report["rows"][0]["reason"] == JoinReason.CODE_DIGEST_MISSING.value
    assert result.report["requests"][0]["action"] == "CONTRACT"


def test_matching_function_code_does_not_certify_changed_global_bindings(tmp_path):
    path, _, codes = _source(tmp_path, "VALUE = 1\ndef compute():\n    return VALUE\n")
    runtime = _runtime([codes[1]])
    path.write_text("VALUE = 99\ndef compute():\n    return VALUE\n")
    result = build_correspondence(build_semantic(path).graph, runtime)
    assert result.report["status_counts"]["VERIFIED"] == 1
    assert all(w["extent"] == "code_object_only" for w in result.report["rows"][0]["witnesses"])
    assert "no slot-version/effect/value equality inferred" in result.report["scope"]
    record = next(iter(result.graph.records.values()))
    assert any("globals/closure/effects not certified" in text for text in record.evidence.assumptions)
