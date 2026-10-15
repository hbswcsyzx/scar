"""Executable lifetime counterexamples, alongside untouched raw-source graphs.

Immediate finalization/clear_frames observations below are CPython-specific.
They test counterexamples to stronger claims, not portable timing guarantees or
evidence proving the frame model's NO_FRAME_INTERPOSITION precondition.
"""
import sys
import traceback
import weakref
from textwrap import dedent

import pytest

from scar.analysis.frame_queries import query_return_references
from scar.analysis.program_lowering import SourceProgram, lower_source
from scar.ir.program.frames import FrameExit, FrameRelease, FrameTermination
from scar.ir.program.functions import BodyLoweringProfile
from scar.ir.program.model import AccessMode, TerminatorKind
from scar.ir.v2.common import Completeness, ProofStatus


pytestmark = pytest.mark.skipif(
    sys.implementation.name != "cpython",
    reason="these runtime counterexamples inspect CPython frame/refcount timing",
)


def compiled_fixture(tmp_path, source):
    source = dedent(source).lstrip()
    path = tmp_path / "raw.py"
    path.write_text(source, encoding="utf-8")
    program = lower_source(path, "f", profile=BodyLoweringProfile.BOUND_FRAME)
    assert program.graph is not None, program.metadata.gaps
    document = program.to_dict()
    assert SourceProgram.from_dict(document).to_dict() == document
    query = query_return_references(document)
    assert query["status"] == "REPLAYED_CONDITIONAL_ROUTES"
    assert query["contents_or_effects_established"] is False
    assert query["transformation_authorized"] is False
    assert query["runtime_target_verified"] is False
    assert query["frame_rules"]["condition_status"] == "UNKNOWN"
    assert program.frame.rules.condition_status is ProofStatus.UNKNOWN
    assert program.frame.rules.effects is Completeness.UNKNOWN
    assert program.frame.rules.release is FrameRelease.NOT_GUARANTEED
    assert program.frame.rules.termination is FrameTermination.MAY_NOT_COMPLETE

    operations = {op.id: op for op in program.graph.operations}
    invocations = [op for op in operations.values()
                   if op.terminator and op.terminator.kind is TerminatorKind.INVOKE]
    raises = [op for op in operations.values()
              if op.terminator and op.terminator.kind is TerminatorKind.RAISE]
    # Each expression can fail; frame cleanup adds no replacement failure.
    assert len(raises) == len(invocations)
    for transition in program.frame.transitions:
        if not isinstance(transition, FrameExit):
            continue
        cleanup = operations[transition.operation]
        completion = operations[transition.completion]
        cleanup_uses = {use.id: use.value for use in cleanup.uses}
        completion_uses = {use.id: use.value for use in completion.uses}
        assert cleanup.terminator is None and not cleanup.completions
        assert cleanup.effects_complete is False
        assert cleanup.accesses[0].mode is AccessMode.READ_WRITE
        assert cleanup.accesses[0].full_overwrite is False
        assert completion_uses[completion.terminator.values[0]] == cleanup_uses[transition.payload]
        assert completion_uses[completion.terminator.values[1]] == cleanup.accesses[0].after
        assert cleanup.id.wire in query["incomplete_effect_operations"]

    namespace = {"__name__": "frame_runtime_fixture"}
    exec(compile(source, str(path), "exec"), namespace)
    return namespace["f"], program, query


def assert_return_routes_to_formal(program, query, name):
    slot, = [port.slot for port in program.interface.parameters
             if program.semantic.slots[port.slot].name == name]
    normal, = [completion for completion in query["completions"] if completion["kind"] == "RETURN"]
    origin, = normal["reference_origins"]
    assert origin["kind"] == "FORMAL_REFERENCE" and origin["slot"] == slot.wire


def test_local_finalizer_changes_returned_contents_without_changing_reference(tmp_path):
    function, program, query = compiled_fixture(tmp_path, """
        def f(make, x):
            local = make(x)
            return x
    """)
    finalized = []

    class ChangeReturnedObject:
        def __init__(self, target):
            self.target = target

        def __del__(self):
            self.target.append("changed during cleanup")
            finalized.append("local")

    x = ["before"]
    returned = function(ChangeReturnedObject, x)
    assert returned is x
    assert x == ["before", "changed during cleanup"]
    assert finalized == ["local"]
    assert_return_routes_to_formal(program, query, "x")
    # Reference routing stays valid even though an identity/purity rewrite would
    # omit an observed content mutation. The public query grants neither.
    assert query["contents_or_effects_established"] is False
    assert query["incomplete_effect_operations"]


def test_unraisable_finalizer_does_not_replace_normal_return(tmp_path):
    function, program, query = compiled_fixture(tmp_path, """
        def f(make, x):
            local = make()
            return x
    """)
    reported = []

    class FinalizerError(Exception):
        pass

    class RaisesOnDeletion:
        def __del__(self):
            raise FinalizerError("cleanup failed")

    def record_unraisable(event):
        # Keeping exc_value/traceback/object could itself retain the finalizer's
        # frame or object. Record only exact scalar observations here.
        reported.append((event.exc_type.__name__, str(event.exc_value)))

    previous_hook = sys.unraisablehook
    x = object()
    try:
        sys.unraisablehook = record_unraisable
        returned = function(RaisesOnDeletion, x)
        assert returned is x
        assert reported == [("FinalizerError", "cleanup failed")]
    finally:
        sys.unraisablehook = previous_hook
    assert_return_routes_to_formal(program, query, "x")
    assert query["frame_rules"]["finalizer_errors"] == "UNRAISABLE"


def test_escaped_frame_keeps_local_alive_after_return(tmp_path):
    function, program, query = compiled_fixture(tmp_path, """
        def f(make, get_frame):
            local = make()
            return get_frame()
    """)
    finalized, references = [], []

    class Local:
        def __del__(self):
            finalized.append("released")

    def make():
        local = Local()
        references.append(weakref.ref(local))
        return local

    def get_frame():
        return sys._getframe(1)

    retained = function(make, get_frame)
    try:
        assert retained.f_code is function.__code__
        assert finalized == []
        assert references[0]() is retained.f_locals["local"]
        assert program.frame.rules.release is FrameRelease.NOT_GUARANTEED
        normal, = [item for item in query["completions"] if item["kind"] == "RETURN"]
        assert {origin["kind"] for origin in normal["reference_origins"]} == {"COMPLETION_RESULT_BOUNDARY"}
    finally:
        retained.clear()
    assert finalized == ["released"] and references[0]() is None


def test_original_exception_traceback_retains_local_and_later_finalizer_is_unraisable(tmp_path):
    function, program, query = compiled_fixture(tmp_path, """
        def f(make, fail):
            local = make()
            return fail()
    """)
    finalized, references, reported = [], [], []

    class OriginalError(Exception):
        pass

    class FinalizerError(Exception):
        pass

    class Local:
        def __del__(self):
            finalized.append("released")
            raise FinalizerError("deferred cleanup failed")

    def make():
        local = Local()
        references.append(weakref.ref(local))
        return local

    original = OriginalError("expression failed")

    def fail():
        raise original

    def record_unraisable(event):
        reported.append((event.exc_type.__name__, str(event.exc_value)))

    previous_hook = sys.unraisablehook
    try:
        sys.unraisablehook = record_unraisable
        try:
            function(make, fail)
        except OriginalError as caught:
            assert caught is original
        else:
            pytest.fail("the expression's original exception must propagate")
        tb = original.__traceback__
        source_frames = []
        while tb is not None:
            if tb.tb_frame.f_code is function.__code__:
                source_frames.append(tb.tb_frame)
            tb = tb.tb_next
        retained, = source_frames
        assert references[0]() is retained.f_locals["local"]
        assert finalized == [] and reported == []
        # Unwinding did not promise to clear this escaped traceback frame. Its
        # explicit later release can run a finalizer without replacing original.
        traceback.clear_frames(original.__traceback__)
        assert finalized == ["released"] and references[0]() is None
        assert reported == [("FinalizerError", "deferred cleanup failed")]
        assert original.args == ("expression failed",)
    finally:
        if original.__traceback__ is not None:
            traceback.clear_frames(original.__traceback__)
        original.__traceback__ = None
        sys.unraisablehook = previous_hook
    assert program.frame.rules.release is FrameRelease.NOT_GUARANTEED
    exceptional = [item for item in query["completions"] if item["kind"] == "RAISE"]
    assert len(exceptional) == 2  # make() or fail(), never a new cleanup raise.
    assert all({origin["kind"] for origin in item["reference_origins"]}
               == {"COMPLETION_RESULT_BOUNDARY"} for item in exceptional)
