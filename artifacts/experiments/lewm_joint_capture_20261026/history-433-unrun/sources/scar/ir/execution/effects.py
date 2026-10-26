"""Resolve execution effects back to original program ports.

These views are derived on demand. They do not add a producer, state, work
membership, or runtime authority to the execution model.
"""
from __future__ import annotations

from scar.ir.program.model import (
    BlockArgument, CompletionResult, CompletionSuccessor, StateVersionValue,
    TerminatorKind,
)

from .common import Unresolved
from .coordinates import AccessRef
from .work import ActualCompletionState, InvokeBoundaryStateEffect


class _DiagnosticContext:
    """Forward a validation context while adapting only issue/gap reporting."""

    __slots__ = ("_ctx", "_issue", "_gap")

    def __init__(self, ctx, issue=None, gap=None):
        self._ctx = ctx
        self._issue = ctx.issue if issue is None else issue
        self._gap = ctx.gap if gap is None else gap

    def __getattr__(self, name):
        return getattr(self._ctx, name)

    def issue(self, code, path, message):
        self._issue(code, path, message)

    def gap(self, code, path, message):
        self._gap(code, path, message)


def effect_context(ctx, *, issue=None, gap=None):
    """Return a diagnostic adapter without copying the execution context."""
    return _DiagnosticContext(ctx, issue, gap)


def _run_for(ctx, occurrence):
    activation = ctx.activation_of(occurrence.id)
    activation_row = ctx.activations[activation]
    process = ctx.processes[activation_row.process]
    return activation, process.run


def resolve_canonical_effect(ctx, effect, path):
    """Resolve an exact original AccessRef or INVOKE state boundary.

    The caller must apply any work-ticket, read/write, or visibility policy.
    Structural contradictions are reported through ``ctx.issue`` and return
    ``None``. Missing observations remain explicit in the returned view and
    are reported as gaps; no value or state is synthesized.
    """
    if type(effect) is AccessRef:
        effect.__post_init__()
        occurrence = ctx.occurrences.get(effect.operation)
        if occurrence is None:
            ctx.issue("effect_operation", path, "access references an unknown operation occurrence")
            return None
        operation = ctx.core_operations.get(occurrence.operation)
        if operation is None:
            ctx.issue("effect_operation", path, "access occurrence has no canonical operation")
            return None
        if effect.index >= len(operation.accesses):
            ctx.issue("effect_access", path, "effect does not select an original StateAccess")
            return None
        access = operation.accesses[effect.index]
        before = ctx.uses.get((occurrence.id, access.before))
        after = None if access.after is None else ctx.results.get((occurrence.id, access.after))
        reference_use = (None if access.reference is None
                         else ctx.uses.get((occurrence.id, access.reference)))
        activation, run = _run_for(ctx, occurrence)
        return {
            "kind": "access",
            "reference": effect,
            "operation": occurrence,
            "access": access,
            "mode": access.mode,
            "before": before,
            "after": after,
            "reference_use": reference_use,
            "activation": activation,
            "run": run,
        }

    if type(effect) is not InvokeBoundaryStateEffect:
        raise TypeError("canonical effect must be an exact AccessRef or InvokeBoundaryStateEffect")
    effect.__post_init__()
    identity = effect.invocation
    occurrence = ctx.occurrences.get(identity)
    if occurrence is None:
        ctx.issue("effect_operation", path, "boundary effect references an unknown invocation")
        return None
    operation = ctx.core_operations.get(occurrence.operation)
    if (operation is None or operation.terminator is None
            or operation.terminator.kind is not TerminatorKind.INVOKE):
        ctx.issue("invoke_kind", path, "boundary state effect requires an actual canonical INVOKE")
        return None

    original = ctx.core_uses.get(effect.state_input.use)
    if (effect.state_input.operation != identity or original is None
            or original[0].id != operation.id or effect.state_input.use not in operation.invoke_arguments):
        ctx.issue("invoke_input", path, "state input is not an exact original invoke argument Use")
        return None
    input_value = ctx.core_values.get(original[1].value)
    if type(input_value) is not StateVersionValue:
        ctx.issue("invoke_input", path, "boundary effect input must be a StateVersionValue Use")
        return None

    input_occurrence = ctx.uses.get((identity, effect.state_input.use))
    if input_occurrence is None or type(input_occurrence.value) is Unresolved:
        ctx.gap("invoke_input_unobserved", path, "actual state input occurrence is not established")

    transfer = ctx.outgoing.get(identity)
    actual_index = None if transfer is None else transfer.successor_index
    actual_successor = None
    if transfer is None:
        ctx.gap("invoke_completion_unobserved", path, "no actual completion transfer establishes the post")
    elif actual_index is None or actual_index >= len(operation.terminator.successors):
        ctx.issue("invoke_actual_edge", path, "actual transfer selects no canonical INVOKE successor")
        return None
    else:
        actual_successor = operation.terminator.successors[actual_index]
        if type(actual_successor) is not CompletionSuccessor:
            ctx.issue("invoke_actual_edge", path, "actual INVOKE successor is not a canonical CompletionSuccessor")
            return None

    post = effect.post
    declared_successor = declared_result = formal = None
    if type(post) is Unresolved:
        ctx.gap("invoke_post_unresolved", path, post.reason)
    elif type(post) is ActualCompletionState:
        if post.successor_index >= len(operation.terminator.successors):
            ctx.issue("invoke_successor", path, "post does not select a canonical completion successor")
            return None
        declared_successor = operation.terminator.successors[post.successor_index]
        if type(declared_successor) is not CompletionSuccessor:
            ctx.issue("invoke_successor", path, "declared INVOKE successor is not a canonical CompletionSuccessor")
            return None
        if transfer is not None and actual_index != post.successor_index:
            ctx.issue("invoke_actual_edge", path, "post selects a different outcome than this invocation actually took")

        formal = ctx.values.get(post.formal)
        core = None if formal is None else ctx.core_values.get(formal.value)
        if (type(core) is not StateVersionValue or type(core.origin) is not BlockArgument
                or core.origin.block != declared_successor.block
                or core.location != input_value.location):
            ctx.issue("invoke_formal", path, "post must reference the state formal of this exact completion and location")
            return None
        if core.origin.index >= len(declared_successor.arguments):
            ctx.issue("invoke_formal", path, "post state formal has no argument at its original completion edge")
            return None
        actual_argument = declared_successor.arguments[core.origin.index]
        if type(actual_argument) is not CompletionResult or actual_argument.index != post.result_index:
            ctx.issue("invoke_result", path, "post index is not the exact original CompletionResult at this formal")
        else:
            declared_result = actual_argument
        if transfer is not None and formal.origin != transfer.target:
            ctx.issue("invoke_formal_visit", path, "post formal comes from another landing traversal")
        activation, run = _run_for(ctx, occurrence)
        if ctx.value_activation(post.formal) != activation:
            ctx.issue("invoke_formal_scope", path, "post formal belongs to another body activation")
    else:
        raise TypeError("InvokeBoundaryStateEffect.post must be ActualCompletionState or Unresolved")

    activation, run = _run_for(ctx, occurrence)
    return {
        "kind": "invoke_boundary",
        "reference": effect,
        "operation": occurrence,
        "input": input_occurrence,
        "input_location": input_value.location,
        "declared_post": post,
        "declared_successor": declared_successor,
        "declared_result": declared_result,
        "actual_transfer": transfer,
        "actual_successor_index": actual_index,
        "actual_successor": actual_successor,
        "post": formal if formal is not None else post,
        # Preserve the historical query key: it denotes the actual successor
        # when observed, while declared_successor above retains the claimed port.
        "successor": actual_successor,
        "formal": formal,
        "activation": activation,
        "run": run,
    }


__all__ = ["effect_context", "resolve_canonical_effect"]
