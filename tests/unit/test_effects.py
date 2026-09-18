import json

from scar.analysis.repetition import repeated_regions
from scar.ir import Effect, Event, ExecutionGraph, Knowledge
from scar.trace.reader import load


def _complete_effect(**kwargs):
    return Effect(rng_effect=Knowledge.NONE, may_raise=Knowledge.NONE,
                  external_effect=Knowledge.NONE, ordering_effect=Knowledge.NONE,
                  collection_knowledge={name: Knowledge.KNOWN for name in
                      ("reads", "writes", "allocates", "frees", "aliases", "escapes")},
                  **kwargs)


def test_empty_lists_do_not_claim_effect_completeness():
    partial = Effect(rng_effect=Knowledge.NONE, may_raise=Knowledge.NONE,
                     external_effect=Knowledge.NONE, ordering_effect=Knowledge.NONE)
    assert partial.collection_knowledge["writes"] == Knowledge.UNKNOWN
    assert not partial.safe_for_exact_reuse
    assert _complete_effect().safe_for_exact_reuse
    assert not _complete_effect(escapes=["callback"]).safe_for_exact_reuse


def test_reuse_checks_every_invocation_effect():
    inputs = [{"logical_version": "s:v0", "storage_id": "s"}]
    events = [Event(kind="module_call", code_id="f:v1", inputs=inputs,
                    duration_ns=100, effect=_complete_effect()),
              Event(kind="module_call", code_id="f:v1", inputs=inputs,
                    duration_ns=100, effect=_complete_effect(writes=["hidden:counter"]))]
    candidate, = repeated_regions(ExecutionGraph(events))
    assert candidate.decision == "rejected"


def test_legacy_trace_effect_lists_remain_unknown(tmp_path):
    record = Event(kind="module_call", effect=_complete_effect()).as_dict()
    record["effect"].pop("collection_knowledge")
    trace = tmp_path / "events.jsonl"
    trace.write_text(json.dumps(record) + "\n")
    event, = load(trace).events
    assert event.effect.collection_knowledge["escapes"] == Knowledge.UNKNOWN
    assert not event.effect.safe_for_exact_reuse
