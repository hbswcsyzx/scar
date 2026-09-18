from types import SimpleNamespace

from scar.trace.session import TraceSession


def test_session_pairs_nested_user_frames_and_records_duration(tmp_path):
    session = TraceSession(tmp_path / "trace")
    outer = compile("pass", str(tmp_path / "outer.py"), "exec")
    inner = compile("pass", str(tmp_path / "inner.py"), "exec")
    outer_frame = SimpleNamespace(f_code=outer, f_lineno=1)
    inner_frame = SimpleNamespace(f_code=inner, f_lineno=1)
    try:
        outer_id = session.python_call(outer_frame)
        inner_id = session.python_call(inner_frame)
        session.python_return(inner_frame)
        session.python_return(outer_frame)
    finally:
        session.close()
    import json
    events = [json.loads(line) for line in (tmp_path / "trace" / "events.jsonl").read_text().splitlines()]
    calls = [event for event in events if event["kind"] == "python_call"]
    returns = [event for event in events if event["kind"] == "python_return"]
    assert (outer_id, inner_id) == (calls[0]["invocation_id"], calls[1]["invocation_id"])
    assert calls[1]["metadata"]["parent_invocation_id"] == outer_id
    assert {event["invocation_id"] for event in returns} == {outer_id, inner_id}
    assert all(event["duration_ns"] >= 0 for event in returns)


def test_nested_python_actions_retain_outer_loop_scope(tmp_path):
    """An outer loop remains visible across an intervening Python call."""
    import json

    session = TraceSession(tmp_path / "trace")
    outer = compile("pass", str(tmp_path / "outer_loop.py"), "exec")
    inner = compile("pass", str(tmp_path / "inner_call.py"), "exec")
    outer_frame = SimpleNamespace(
        f_code=outer, f_lineno=1, f_lasti=0, f_locals={}, f_globals={})
    inner_frame = SimpleNamespace(
        f_code=inner, f_lineno=1, f_lasti=0, f_locals={}, f_globals={})
    try:
        outer_id = session.python_call(outer_frame)
        session.active_loops[id(outer_frame)] = (24, 3)
        inner_id = session.python_call(inner_frame)
        session.python_return(inner_frame)
        session.python_return(outer_frame)
    finally:
        session.close()
    events = [json.loads(line) for line in
              (tmp_path / "trace" / "events.jsonl").read_text().splitlines()]
    inner_call = next(event for event in events
                      if event["kind"] == "python_call"
                      and event["invocation_id"] == inner_id)
    inner_return = next(event for event in events
                        if event["kind"] == "python_return"
                        and event["invocation_id"] == inner_id)
    assert inner_call["metadata"]["parent_invocation_id"] == outer_id
    assert inner_call["metadata"]["loop_parent_invocation_id"] == outer_id
    assert inner_call["metadata"]["loop_target_offset"] == 24
    assert inner_call["metadata"]["loop_iteration"] == 3
    assert inner_return["metadata"]["loop_parent_invocation_id"] == outer_id


def test_session_records_exception_outcome_and_clears_frame(tmp_path):
    session = TraceSession(tmp_path / "trace")
    frame = SimpleNamespace(f_code=compile("pass", str(tmp_path / "f.py"), "exec"), f_lineno=1)
    try:
        invocation = session.python_call(frame)
        session.python_exception(frame, (ValueError, ValueError("bad"), None))
        session.python_return(frame)
        assert not session.call_stacks
    finally:
        session.close()
    import json
    events = [json.loads(line) for line in (tmp_path / "trace" / "events.jsonl").read_text().splitlines()]
    returns = [event for event in events if event["kind"] == "python_return"]
    assert returns[-1]["invocation_id"] == invocation
    assert returns[-1]["metadata"]["outcome"] == "exception:ValueError"


def test_session_records_side_effect_sensitive_c_call(tmp_path):
    import builtins
    import inspect
    import json

    session = TraceSession(tmp_path / "trace")
    frame = inspect.currentframe()
    assert frame is not None
    try:
        session.c_call(frame, builtins.open)
    finally:
        session.close()
    events = [json.loads(line)
              for line in (tmp_path / "trace" / "events.jsonl").read_text().splitlines()]
    [event] = [item for item in events if item["kind"] == "python_c_call"]
    assert event["metadata"]["c_function"] == "open"
    assert {"CTRL", "IO", "OPAQUE"} <= set(event["labels"])
    assert event["effect"]["external_effect"] == "UNKNOWN"
    assert event["metadata"]["argument_capture"] == "UNKNOWN"


def test_session_rekeys_forked_child_process_context(tmp_path):
    import json
    import os
    from types import SimpleNamespace

    session = TraceSession(tmp_path / "trace")
    code = compile("pass", str(tmp_path / "forked.py"), "exec")
    parent_pid = os.getpid()
    child_pid = os.fork()
    if child_pid == 0:
        try:
            frame = SimpleNamespace(f_code=code, f_lineno=1, f_lasti=0,
                                    f_locals={}, f_globals={})
            session.python_call(frame)
            session.python_return(frame)
            session.close()
        finally:
            os._exit(0)
    try:
        _, status = os.waitpid(child_pid, 0)
        assert os.waitstatus_to_exitcode(status) == 0
    finally:
        session.close()
    events = [json.loads(line)
              for line in (tmp_path / "trace" / "events.jsonl").read_text().splitlines()
              if line.strip()]
    process_ids = {event["metadata"]["process_id"] for event in events}
    assert parent_pid not in process_ids
    assert len(process_ids) == 1
    assert events[0]["invocation_id"] == 1
    metadata = list((tmp_path / "trace").glob("metadata.*.json"))
    assert len(metadata) == 2
    child_meta = next(json.loads(path.read_text()) for path in metadata
                      if json.loads(path.read_text()).get("pid") != parent_pid)
    assert child_meta["forked_from_pid"] == parent_pid


def test_session_records_lines_and_back_edges_when_requested(tmp_path):
    session = TraceSession(tmp_path / "trace")
    code = compile("pass", str(tmp_path / "loop_case.py"), "exec")
    frame = SimpleNamespace(f_code=code, f_lineno=1, f_lasti=10)
    try:
        invocation = session.python_call(frame)
        session.python_line(frame)
        frame.f_lineno = 2
        frame.f_lasti = 20
        session.python_line(frame)
        frame.f_lineno = 1
        frame.f_lasti = 5
        session.python_line(frame)
        session.python_line_return(frame)
        session.python_return(frame)
    finally:
        session.close()
    import json
    events = [json.loads(line) for line in (tmp_path / "trace" / "events.jsonl").read_text().splitlines()]
    lines = [event for event in events if event["kind"] == "python_line"]
    loops = [event for event in events if event["kind"] == "loop_iteration"]
    assert len(lines) == 3
    assert loops and loops[0]["invocation_id"] == invocation
    assert loops[0]["metadata"]["iteration"] == 1


def test_session_records_tensor_return_as_escape(tmp_path):
    import torch
    session = TraceSession(tmp_path / "trace")
    code = compile("pass", str(tmp_path / "return_case.py"), "exec")
    frame = SimpleNamespace(f_code=code, f_lineno=1, f_lasti=0)
    value = torch.ones(2)
    try:
        invocation = session.python_call(frame)
        session.python_return(frame, value)
    finally:
        session.close()
    import json
    events = [json.loads(line) for line in (tmp_path / "trace" / "events.jsonl").read_text().splitlines()]
    returned = [event for event in events if event["kind"] == "python_return"][-1]
    assert returned["invocation_id"] == invocation
    assert returned["outputs"][0]["logical_version"]
    assert returned["effect"]["escapes"] == [returned["outputs"][0]["logical_version"]]
    assert returned["effect"]["collection_knowledge"]["escapes"] == "KNOWN"


def test_session_captures_tensor_function_inputs_without_claiming_completeness(tmp_path):
    import torch
    session = TraceSession(tmp_path / "trace")
    code = compile("pass", str(tmp_path / "input_case.py"), "exec")
    value = torch.ones(2)
    frame = SimpleNamespace(f_code=code, f_lineno=1, f_lasti=0,
                            f_locals={"x": value, "opaque": object()})
    try:
        invocation = session.python_call(frame)
        session.python_return(frame)
    finally:
        session.close()
    import json
    events = [json.loads(line) for line in (tmp_path / "trace" / "events.jsonl").read_text().splitlines()]
    call = [event for event in events if event["kind"] == "python_call"][-1]
    assert call["invocation_id"] == invocation
    assert call["inputs"][0]["logical_version"]
    assert call["metadata"]["input_names"] == ["x"]
    assert call["metadata"]["input_capture"].endswith("UNKNOWN")
    assert call["effect"]["reads"] == [call["inputs"][0]["logical_version"]]


def test_session_captures_referenced_global_tensor_without_claiming_completeness(tmp_path):
    import torch
    session = TraceSession(tmp_path / "trace")
    code = compile("y = GLOBAL_X", str(tmp_path / "global_case.py"), "exec")
    value = torch.ones(2)
    frame = SimpleNamespace(f_code=code, f_lineno=1, f_lasti=0,
                            f_locals={}, f_globals={"GLOBAL_X": value})
    try:
        invocation = session.python_call(frame)
        session.python_return(frame)
    finally:
        session.close()
    import json
    events = [json.loads(line) for line in (tmp_path / "trace" / "events.jsonl").read_text().splitlines()]
    call = [event for event in events if event["kind"] == "python_call"][-1]
    assert call["invocation_id"] == invocation
    assert call["metadata"]["input_names"] == ["global:GLOBAL_X"]
    assert call["metadata"]["input_capture"].endswith("UNKNOWN")
    assert call["effect"]["reads"] == [call["inputs"][0]["logical_version"]]


def test_session_records_callable_identity_and_closure_without_claiming_completeness(tmp_path):
    import torch
    from scar.trace.reader import load

    captured_tensor = torch.ones(2)

    def callback(value):
        return value + captured_tensor

    session = TraceSession(tmp_path / "trace")
    frame = SimpleNamespace(
        f_code=callback.__code__,
        f_lineno=callback.__code__.co_firstlineno,
        f_locals={"callback": callback},
        f_globals=callback.__globals__,
    )
    try:
        invocation = session.python_call(frame)
    finally:
        session.close()
    events = load(tmp_path / "trace").events
    call = next(event for event in events if event.kind == "python_call")
    assert call.invocation_id == invocation
    assert call.metadata["callable_capture"] == "UNKNOWN"
    assert len(call.metadata["callable_inputs"]) == 1
    descriptor = call.metadata["callable_inputs"][0]
    assert descriptor["callable_code_id"]
    assert descriptor["closure_names"] == ["captured_tensor"]
    assert any(item.get("state_role") == "callable" for item in call.inputs)
    assert any(item.get("state_role") == "closure_capture" for item in call.inputs)


def test_pure_module_contract_captures_scalars_structure_and_module_state(tmp_path):
    import torch
    from scar.analysis.repetition import repeated_regions
    from scar.trace.reader import load

    class Contracted(torch.nn.Module):
        scar_pure = True

        def __init__(self):
            super().__init__()
            self.weight = torch.nn.Parameter(torch.ones(2))
            self.register_buffer("offset", torch.zeros(2))

        def forward(self, value, scale=1):
            return value * self.weight * scale + self.offset

    module = Contracted().eval()
    value = torch.ones(2)
    session = TraceSession(tmp_path / "trace")
    try:
        for scale in (1, 2):
            captured = session.module_inputs(module, (value,), {"scale": scale})
            result = module(value, scale=scale)
            session.module_call(module, (value,), {"scale": scale}, result, 10,
                                code_id="user:contracted", captured_inputs=captured)
    finally:
        session.close()

    graph = load(tmp_path / "trace")
    calls = [event for event in graph.events if event.kind == "module_call"]
    assert len(calls) == 2
    first = calls[0]
    assert first.effect.safe_for_exact_reuse
    assert first.metadata["contract_read_capture"] == "complete"
    roles = {item.get("state_role") for item in first.inputs}
    assert {"module_parameter", "module_buffer", "module_training"} <= roles
    assert any(str(item.get("input_path", "")).endswith(".value[0]")
               and item.get("type") == "int" for item in first.inputs)
    # Tensor identity is unchanged, but the scalar differs. The complete
    # signature must therefore not emit a repeated-input candidate.
    assert repeated_regions(graph) == []


def test_pure_module_contract_rejects_opaque_argument_capture(tmp_path):
    import torch
    from scar.trace.reader import load

    class Contracted(torch.nn.Module):
        scar_pure = True

        def forward(self, value, context=None):
            return value

    module = Contracted()
    value = torch.ones(2)
    opaque = object()
    session = TraceSession(tmp_path / "trace")
    try:
        captured = session.module_inputs(module, (value,), {"context": opaque})
        session.module_call(module, (value,), {"context": opaque}, value, 10,
                            code_id="user:opaque", captured_inputs=captured)
    finally:
        session.close()
    [call] = [event for event in load(tmp_path / "trace").events
              if event.kind == "module_call"]
    assert call.metadata["contract_read_capture"] == "UNKNOWN"
    assert call.effect.collection_knowledge["reads"].value == "UNKNOWN"
    assert call.effect.safe_for_exact_reuse is False


def test_uncontracted_module_action_is_explicitly_opaque(tmp_path):
    import torch
    from scar.trace.reader import load

    module = torch.nn.Identity()
    value = torch.ones(2)
    session = TraceSession(tmp_path / "trace")
    try:
        result = module(value)
        session.module_call(module, (value,), {}, result, 10,
                            code_id="user:identity")
    finally:
        session.close()
    [call] = [event for event in load(tmp_path / "trace").events
              if event.kind == "module_call"]
    assert {"CTRL", "VAL", "OPAQUE"} <= set(call.labels)


def test_python_return_with_opaque_value_is_explicitly_opaque(tmp_path):
    import json
    from types import SimpleNamespace

    session = TraceSession(tmp_path / "trace")
    frame = SimpleNamespace(
        f_code=compile("pass", str(tmp_path / "opaque_return.py"), "exec"),
        f_lineno=1, f_lasti=0, f_locals={}, f_globals={})
    try:
        session.python_call(frame)
        session.python_return(frame, object())
    finally:
        session.close()
    events = [json.loads(line) for line in
              (tmp_path / "trace" / "events.jsonl").read_text().splitlines()]
    returned = next(item for item in events if item["kind"] == "python_return")
    assert {"CTRL", "OPAQUE"} <= set(returned["labels"])
    assert returned["metadata"]["return_escape_evidence"] == "UNKNOWN"


def test_pure_module_complete_state_can_form_reuse_candidate(tmp_path):
    import torch
    from scar.analysis.repetition import repeated_regions
    from scar.trace.reader import load

    class Contracted(torch.nn.Module):
        scar_pure = True

        def __init__(self):
            super().__init__()
            self.register_buffer("bias", torch.ones(2))

        def forward(self, value, scale=1):
            return value * scale + self.bias

    module = Contracted().eval()
    value = torch.ones(2)
    session = TraceSession(tmp_path / "trace")
    try:
        for _ in range(2):
            captured = session.module_inputs(module, (value,), {"scale": 3})
            result = module(value, scale=3)
            session.module_call(module, (value,), {"scale": 3}, result, 100,
                                code_id="user:complete", captured_inputs=captured)
    finally:
        session.close()
    [candidate] = repeated_regions(load(tmp_path / "trace"))
    assert candidate.decision == "proposed"
    assert candidate.backend == "exact_reuse"
    assert all(item.status.value == "PROVEN"
               for item in candidate.proof_obligations)


def test_pure_module_hidden_state_changes_logical_input_signature(tmp_path):
    import torch
    from scar.analysis.repetition import repeated_regions
    from scar.trace.reader import load

    class Counter(torch.nn.Module):
        scar_pure = True

        def __init__(self):
            super().__init__()
            self.counter = 0

        def forward(self, value):
            self.counter += 1
            return value + self.counter

    module = Counter()
    value = torch.ones(1)
    session = TraceSession(tmp_path / "trace")
    try:
        for _ in range(2):
            captured = session.module_inputs(module, (value,), {})
            result = module(value)
            session.module_call(module, (value,), {}, result, 100,
                                code_id="user:counter", captured_inputs=captured)
    finally:
        session.close()
    graph = load(tmp_path / "trace")
    calls = [event for event in graph.events if event.kind == "module_call"]
    counters = [
        item["logical_version"] for call in calls for item in call.inputs
        if item.get("input_path") == "module.attribute:<root>.counter"
    ]
    assert len(counters) == 2 and counters[0] != counters[1]
    assert all(call.effect.writes for call in calls)
    assert all(call.metadata["contract_state_stable"] is False for call in calls)
    assert repeated_regions(graph) == []
