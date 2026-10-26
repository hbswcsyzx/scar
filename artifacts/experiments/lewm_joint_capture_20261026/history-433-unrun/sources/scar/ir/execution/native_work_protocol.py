"""Independent source checks for existing single-activity work records.

This is not an ExecutionModel, a new IR vocabulary, or a ready protocol.  An
owned source is made only by the capture acquisition in native_work_bridge.
The original program-snapshot attachment deliberately remains unresolved.
"""
from __future__ import annotations

from hashlib import sha256
import json

from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.record_codec import encode
from scar.ir.v2.common import Completeness
from scar.ir.v2.ids import OperationInstanceID
from .common import EvidencePoint, Unresolved
from .content import WorkEvidenceBinding
from .ids import WorkEvidenceBindingID, WorkQuiescenceID, WorkTicketID
from .work import ExternalWorkSource, WorkQuiescence, WorkSubmission


def _need(test, message):
    if not test:
        raise ValueError(message)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _ticket(run, reference):
    return WorkTicketID("native-activity:" + sha256(
        _canonical([run.value, reference])).hexdigest())


def _id(cls, ticket):
    return cls(ticket.value)


def activity_actor(event):
    """Fixed Kineto normal/PtoP serializer fields, never a name heuristic."""
    args = event.get("args", {})
    if type(args) is not dict:
        return None
    normal = all(key in args for key in ("device", "context", "stream"))
    p2p = event.get("cat") == "gpu_memcpy" and all(key in args for key in (
        "fromDevice", "inDevice", "toDevice", "fromContext", "inContext", "toContext", "stream"))
    if not normal and not p2p:
        return None
    if p2p and any(type(args[key]) is not int or args[key] < 0 for key in (
            "fromDevice", "inDevice", "toDevice", "fromContext", "inContext", "toContext")):
        return None
    device = args["device"] if normal else args["inDevice"]
    context = args["context"] if normal else args["inContext"]
    stream = args["stream"]
    if any(type(value) is not int or value < 0 for value in (device, context, stream)):
        return None
    if normal and p2p:
        _need((device, context) == (args["inDevice"], args["inContext"]),
              "normal and PtoP GPU execution actors conflict")
    return device, context, stream


def make_records(run, process, artifact, index, instance, raw_fact):
    """Build only the existing records; the independent checker checks them."""
    reference = raw_fact["reference"]
    ticket = _ticket(run, reference)
    start = ProviderFactReference(artifact, f"#/instances/{index}/start_ns")
    end = ProviderFactReference(artifact, f"#/instances/{index}/end_ns")
    origin = EvidencePoint(run, process, start)
    terminal = EvidencePoint(run, process, end)
    source = ProviderFactReference(artifact, f"#/instances/{index}")
    gap = Unresolved("single activity does not establish executor or queue lifecycle", origin)
    submission = WorkSubmission(
        ticket, ExternalWorkSource(origin, start), gap, gap, (),
        Completeness.UNKNOWN, (), Completeness.UNKNOWN, (),
        Completeness.UNKNOWN,
        Unresolved("activity end does not enumerate all resource holders", origin),
        source, source)
    binding = WorkEvidenceBinding(_id(WorkEvidenceBindingID, ticket), ticket,
                                  artifact, OperationInstanceID(instance["id"]["value"]), source)
    quiescence = WorkQuiescence(_id(WorkQuiescenceID, ticket), ticket, terminal, end)
    return submission, binding, quiescence


_ACQUISITION_KEY = object()


class NativeActivityWorkEvidence:
    """Immutable source bytes for one bounded fragment, never restored by JSON."""
    __slots__ = ("_run", "_process", "_artifact", "_projection", "_facts")

    def __init__(self, key, run, process, artifact, projection, facts):
        _need(key is _ACQUISITION_KEY, "native activity evidence requires fresh acquisition")
        _need(type(artifact) is ProviderArtifact and type(projection) is bytes,
              "native activity evidence requires exact typed source bytes")
        object.__setattr__(self, "_run", run)
        object.__setattr__(self, "_process", process)
        object.__setattr__(self, "_artifact", artifact)
        object.__setattr__(self, "_projection", projection)
        # Copies contain raw-byte-verified facts and original archive receipts.
        # A caller's mutable model/metadata is never the owned source.
        object.__setattr__(self, "_facts", tuple(_canonical(fact) for fact in facts))

    def __setattr__(self, name, value):
        raise AttributeError("native activity source evidence is immutable")

    def check_fragment(self, submissions, bindings, quiescences, projection):
        """Reconcile every source occurrence, including all endpoint fields.

        No program/ExecutionModel seal substitutes for these checks.  A wrong
        producer still reaches semantic checks against the immutable source.
        """
        _need(type(projection) is bytes and projection == self._projection,
              "native activity projection differs from the verified source")
        _need(len(projection) == self._artifact.size_bytes
              and sha256(projection).hexdigest() == self._artifact.sha256,
              "native activity projection artifact differs")
        _need(all(type(rows) is tuple for rows in (submissions, bindings, quiescences)),
              "native activity fragment tables must be exact tuples")
        n = len(self._facts)
        _need(len(submissions) == len(bindings) == len(quiescences) == n,
              "native activity source inventory has missing or extra records")
        document = json.loads(projection)
        _need(len(document["instances"]) == n, "native activity instance inventory differs")
        tickets, source_ids = set(), set()
        for index, (work, binding, quiet, frozen) in enumerate(zip(
                submissions, bindings, quiescences, self._facts)):
            fact = json.loads(frozen)
            record, raw = document["instances"][index], fact["raw"]
            _need(record == fact["record"], "projection rewrites an original EEG record")
            from scar.trace.native_import import _ns
            event = raw["event"]
            start_ns, duration_ns = _ns(event.get("ts")), _ns(event.get("dur"))
            _need(raw["category"] in ("kernel", "gpu_memcpy", "gpu_memset") and event.get("ph") == "X"
                  and start_ns is not None and duration_ns is not None
                  and start_ns > 0 and duration_ns > 0
                  and (record["start_ns"], record["end_ns"]) == (start_ns, start_ns + duration_ns)
                  and record["metadata"].get("raw_reference") == raw["reference"],
                  "native source does not establish a valid single-activity end")
            actor = activity_actor(event)
            _need(actor is not None and type(event.get("pid")) is int
                  and type(event.get("tid")) is int
                  and (event["pid"], event["tid"]) == (actor[0], actor[2])
                  and record["process_id"] == fact["host_pid"]
                  and record["thread_id"] == f"kineto-device-lane:{event['pid']}:{event['tid']}",
                  "native source execution actor differs")
            _need(type(work) is WorkSubmission and type(binding) is WorkEvidenceBinding
                  and type(quiet) is WorkQuiescence, "unexpected native work record type")
            work.__post_init__(); binding.__post_init__(); quiet.__post_init__()
            ticket = _ticket(self._run, raw["reference"])
            _need(work.id == ticket and ticket not in tickets,
                  "native work ticket is missing, repeated, or belongs to another source")
            tickets.add(ticket)
            instance = OperationInstanceID(record["id"]["value"])
            _need(instance not in source_ids, "native EEG producer is duplicated")
            source_ids.add(instance)
            source = ProviderFactReference(self._artifact, f"#/instances/{index}")
            start = ProviderFactReference(self._artifact, f"#/instances/{index}/start_ns")
            end = ProviderFactReference(self._artifact, f"#/instances/{index}/end_ns")
            before = EvidencePoint(self._run, self._process, start)
            after = EvidencePoint(self._run, self._process, end)
            _need(type(work.origin) is ExternalWorkSource
                  and work.origin.point == before and work.origin.source == start,
                  "native activity start endpoint/source/actor differs")
            _need(work.source == source and work.protocol == source,
                  "native activity submission protocol/source differs")
            for item in (work.executor, work.scheduling):
                _need(type(item) is Unresolved and item.point == before
                      and item.reason == "single activity does not establish executor or queue lifecycle",
                      "unknown native executor/queue was replaced or mis-sourced")
            _need(work.dependencies == work.effects == work.materializations == (),
                  "single activity evidence does not authorize dependency/effect/materialization claims")
            _need(work.dependencies_coverage is Completeness.UNKNOWN
                  and work.effects_coverage is Completeness.UNKNOWN
                  and work.materializations_coverage is Completeness.UNKNOWN,
                  "native work coverage was promoted")
            _need(type(work.retention) is Unresolved and work.retention.point == before
                  and work.retention.reason == "activity end does not enumerate all resource holders",
                  "native activity retention was promoted or mis-sourced")
            _need(binding.id == _id(WorkEvidenceBindingID, ticket)
                  and binding.ticket == ticket and binding.artifact == self._artifact
                  and binding.instance == instance and binding.source == source,
                  "native work binding producer/artifact/source differs")
            _need(quiet.id == _id(WorkQuiescenceID, ticket)
                  and quiet.ticket == ticket and quiet.observed_at == after
                  and quiet.source == end,
                  "native activity quiescence endpoint/source/actor differs")
            _need(before != after and record["start_ns"] < record["end_ns"],
                  "native activity start and end were merged")
        return {"status": "SINGLE_ACTIVITY_QUIESCENCE_WITH_OPEN", "records": n,
                "program_snapshot_attachment": "UNATTACHED_TO_PROGRAM_SNAPSHOT",
                "result_success_established": False, "child_completion_established": False,
                "resource_readiness_established": False, "whole_model_established": False}


def _make_evidence(run, process, artifact, projection, facts):
    return NativeActivityWorkEvidence(_ACQUISITION_KEY, run, process, artifact, projection, facts)


__all__ = ["NativeActivityWorkEvidence"]
