"""Import supplied ETO/Kineto observations into the existing evidence IR.

Provider tokens are opaque references. No source definitions, logical contents,
allocation generations, canonical state transitions or device-ready facts are
recovered by this adapter. The two artifacts are supplied as one capture; their
hashes namespace every imported identity.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
import json
import math
from pathlib import Path

from scar.ir.v2 import (
    EvidenceClaim, EvidenceEndpoint, EvidenceGraph, EvidenceKind, EvidenceNodeKind,
    EvidenceRelation, IRBundle, OperationDefinition, OperationDefinitionID,
    OperationInstance, OperationInstanceID, OperationKind, ResourceID,
    ResourceKind, ResourceRequirement, SemanticGraph, ValueGraph,
)
from scar.ir.v2.evidence import ProviderReference, EvidenceEdge
from scar.trace.files import open_binary


_REVISION = "cf30153c4c131c8164ee7798e5022d810682e2cb"
_KINETO_REVISION = "094d3c1d072362d0a919a77299459eee94f97931"
_ETO_SCHEMA = "1.1.1-chakra.0.0.4"
_GPU = frozenset(("kernel", "gpu_memcpy", "gpu_memset"))
_RUNTIME = frozenset(("cuda_runtime", "cuda_driver"))
_CPU = frozenset(("cpu_op", "user_annotation"))


@dataclass(slots=True)
class NativeImportResult:
    bundle: IRBundle
    report: dict
    references: list[dict]
    resources: list[dict]


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate JSON key: " + key)
        result[key] = value
    return result


def _constant(value):
    raise ValueError("nonfinite JSON constant: " + value)


def _float(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("nonfinite JSON number")
    return result


def _canonical_hash(document):
    digest = sha256()
    encoder = json.JSONEncoder(sort_keys=True, ensure_ascii=False,
                               separators=(",", ":"), allow_nan=False)
    for part in encoder.iterencode(document):
        digest.update(part.encode("utf-8"))
    return digest.hexdigest()


def _read(path, remaining):
    with open_binary(path) as stream:
        payload = stream.read(remaining + 1)
    if len(payload) > remaining:
        raise ValueError("native evidence exceeds combined decompressed max_bytes")
    try:
        document = json.loads(payload, object_pairs_hook=_pairs,
                              parse_constant=_constant, parse_float=_float)
    except (UnicodeError, RecursionError, OverflowError) as error:
        raise ValueError("invalid native evidence JSON") from error
    if type(document) is not dict:
        raise ValueError("native evidence document must be a JSON object")
    artifact = {"path": str(Path(path).absolute()), "sha256": sha256(payload).hexdigest(),
                "size_bytes": len(payload), "hash_basis": "decompressed retained raw bytes"}
    return document, artifact


def _integer(value, *, positive=False):
    return type(value) is int and value >= (1 if positive else 0)


def _ns(value):
    if type(value) not in (int, float) or value < 0:
        return None
    try:
        scaled = value * 1000
        return round(scaled) if math.isfinite(scaled) else None
    except (OverflowError, ValueError):
        return None


def _attrs(node):
    raw = node.get("attrs", [])
    if type(raw) is not list:
        raise ValueError("ETO attrs must be an array")
    result = {}
    for item in raw:
        if type(item) is not dict or type(item.get("name")) is not str:
            raise ValueError("invalid ETO attribute")
        name = item["name"]
        if name in result:
            raise ValueError("duplicate ETO attribute: " + name)
        result[name] = item.get("value")
    return result


def _element_types(name):
    """Read provider container type structure, not Python/Tensor semantics."""
    for prefix in ("GenericList[", "GenericTuple[", "Tuple[", "List["):
        if name.startswith(prefix) and name.endswith("]"):
            text = name[len(prefix):-1]
            start, depth, parts = 0, 0, []
            for index, char in enumerate(text):
                if char in "[(":
                    depth += 1
                elif char in "])":
                    depth -= 1
                elif char == "," and depth == 0:
                    parts.append(text[start:index].strip())
                    start = index + 1
            parts.append(text[start:].strip())
            return parts
    return None


class _Importer:
    def __init__(self, eto, chrome, artifacts, maximum):
        self.eto, self.chrome, self.artifacts = eto, chrome, artifacts
        self.pid = eto["pid"]
        capture = _canonical_hash({"eto": artifacts["eto"]["sha256"],
                                   "kineto": artifacts["kineto"]["sha256"],
                                   "revision": _REVISION, "pid": self.pid})
        self.scope = "native:" + capture
        self.semantic, self.evidence = SemanticGraph(), EvidenceGraph()
        self.bundle = IRBundle(self.semantic, self.evidence, ValueGraph())
        self.definitions = {}
        self.nodes = {}
        self.parents = {}
        self.rf_nodes = {}
        self.node_attrs = {}
        self.gaps = {}
        self.reference_shapes = {}
        self.resources = []
        self.resource_index = {}
        self.runtime_instances = {}
        self.gpu_instances = []
        self.cpu_scopes = {}
        self.scope_requests = []
        self.scope_matches = Counter()
        self.retained = []
        self.categories = Counter()
        self.cpu_rf_matches = 0
        self.runtime_gpu_matches = 0
        self.maximum = maximum

    def pointer(self, artifact, pointer):
        return "sha256:" + self.artifacts[artifact]["sha256"] + pointer

    def gap(self, code, reference, message):
        row = self.gaps.setdefault(code, {"code": code, "message": message,
                                         "count": 0, "examples": []})
        row["count"] += 1
        if len(row["examples"]) < 8:
            row["examples"].append(reference)

    def claim(self, *references, inferred=False, assumptions=()):
        return EvidenceClaim(EvidenceKind.INFERRED if inferred else EvidenceKind.OBSERVED,
                             tuple(references), scope=self.scope,
                             assumptions=tuple(assumptions))

    def edge(self, relation, source, target, claim, *, kind=EvidenceNodeKind.OPERATION_INSTANCE):
        identifier = self.scope + ":edge:" + str(len(self.evidence.edges))
        self.evidence.add_edge(EvidenceEdge(
            identifier, relation, EvidenceEndpoint(EvidenceNodeKind.OPERATION_INSTANCE, source),
            EvidenceEndpoint(kind, target), claim))

    def definition(self, domain, name, schema=""):
        key = (domain, name, schema)
        if key not in self.definitions:
            identifier = OperationDefinitionID(self.scope + ":symbol:" + _canonical_hash(key))
            kind = (OperationKind.KERNEL if domain == "kernel" else
                    OperationKind.TRANSFER if domain == "gpu_memcpy" else
                    OperationKind.OPERATOR if domain in ("eto", "gpu_memset") else OperationKind.OPAQUE)
            self.semantic.add_definition(OperationDefinition(
                identifier, kind, name, metadata={
                    "provider": domain, "provider_revision": _REVISION, "op_schema": schema,
                    "definition_basis": "observed provider symbol, not original source",
                    "state_effects": "UNKNOWN", "source_correspondence": "UNRESOLVED"}))
            self.definitions[key] = identifier
        return self.definitions[key]

    def eto_nodes(self):
        for index, node in enumerate(self.eto["nodes"]):
            if type(node) is not dict:
                raise ValueError("ETO node must be an object")
            key, parent, name = node.get("id"), node.get("ctrl_deps"), node.get("name")
            if not _integer(key) or not _integer(parent) or type(name) is not str or not name:
                raise ValueError("invalid ETO node id/ctrl_deps/name")
            if key in self.nodes:
                raise ValueError("duplicate ETO node ID")
            attributes = _attrs(node)
            self.node_attrs[key] = attributes
            # Pinned provider finalizeExecutionTraceOutput emits kRootId as
            # its own parent. This is a structural sentinel, not containment.
            root_sentinel = (key == parent == 1
                             and name == "[pytorch|profiler|execution_trace|process]"
                             and attributes.get("rf_id") == 0
                             and attributes.get("tid") == 0
                             and attributes.get("scope") == 7)
            self.parents[key] = None if root_sentinel else parent
            reference = self.pointer("eto", f"#/nodes/{index}")
            identifier = OperationInstanceID(self.scope + ":eto:" + str(key))
            definition = self.definition("eto", name, str(attributes.get("op_schema", "")))
            tid = attributes.get("tid")
            instance = OperationInstance(identifier, definition, self.pid,
                "eto-thread:" + str(tid), metadata={
                    "provider": "ETO", "raw_reference": reference, "node_id": key,
                    "rf_id": attributes.get("rf_id"), "ctrl_deps": parent,
                    "thread_namespace": "ETO collector thread, not OS TID",
                    "raw_tid": tid, "clock_domain": "ETO; no per-node timestamps"})
            if root_sentinel:
                instance.metadata["structural_root_sentinel"] = True
            self.evidence.add_instance(instance)
            self.nodes[key] = instance
            rf = attributes.get("rf_id")
            if _integer(rf, positive=True):
                self.rf_nodes.setdefault(rf, []).append(key)
            for role in ("inputs", "outputs"):
                self.slots(instance, node.get(role), role, reference)
        # ETO is serialized in completion order. Resolve containment only after
        # all nodes exist, with a linear parent-chain cycle check.
        checked = set()
        for key in self.nodes:
            path, active, current = [], set(), key
            while current in self.nodes and current not in checked:
                if current in active:
                    raise ValueError("cycle in ETO ctrl_deps")
                path.append(current)
                active.add(current)
                current = self.parents[current]
                if current == 0 and current not in self.nodes:
                    break
            checked.update(path)
        for key, instance in self.nodes.items():
            parent = self.parents[key]
            if parent in self.nodes:
                instance.parent = self.nodes[parent].id
                instance.metadata["parent_basis"] = "ETO ctrl_deps collector stack only"
            elif parent not in (0, None):
                self.gap("eto_parent_missing", instance.metadata["raw_reference"],
                         "parent node is absent; no phantom parent was created")

    def slots(self, instance, record, role, reference):
        if type(record) is not dict:
            self.gap("eto_slots_missing", reference + "/" + role, "missing provider slot record")
            return
        values, types = record.get("values"), record.get("types")
        if type(values) is not list or type(types) is not list or len(values) != len(types):
            self.gap("eto_slots_incomplete", reference + "/" + role,
                     "value/type arrays do not define a complete ordered slot interface")
            return
        shapes, strides = record.get("shapes", []), record.get("strides", [])
        for ordinal, (value, name) in enumerate(zip(values, types)):
            shape = shapes[ordinal] if type(shapes) is list and ordinal < len(shapes) else None
            stride = strides[ordinal] if type(strides) is list and ordinal < len(strides) else None
            stack = [(value, name, shape, stride, (ordinal,))]
            while stack:
                item, item_type, item_shape, item_stride, path = stack.pop()
                pointer = reference + "/" + role + "/values/" + "/".join(map(str, path))
                if type(item_type) is not str:
                    self.gap("eto_slot_type_unknown", pointer, "provider leaf type is unavailable")
                    continue
                if item_type == "Tensor" or item_type.startswith("Tensor("):
                    if (type(item) is not list or len(item) != 6
                            or not all(_integer(part) for part in item[:5])
                            or type(item[5]) is not str or not item[5]):
                        self.gap("eto_tensor_descriptor_unknown", pointer,
                                 "Tensor slot lacks the pinned provider six-field descriptor")
                        continue
                    self.tensor(instance, role, item, item_type, item_shape, item_stride, path, pointer)
                    continue
                parts = _element_types(item_type)
                if parts is not None and type(item) is list:
                    if len(parts) == 1:
                        parts = parts * len(item)
                    if len(parts) != len(item):
                        self.gap("eto_container_types_unknown", pointer,
                                 "container type leaves do not match the actual ordered elements")
                        continue
                    for child in range(len(item) - 1, -1, -1):
                        shape = item_shape[child] if type(item_shape) is list and child < len(item_shape) else None
                        stride = item_stride[child] if type(item_stride) is list and child < len(item_stride) else None
                        stack.append((item[child], parts[child], shape, stride, (*path, child)))

    def tensor(self, instance, role, value, name, shape, strides, path, pointer):
        # One opaque provider symbol may occur in many ordered slots and writes.
        # Edges, not a repeated tuple copy, retain each exact observation locator.
        identifier = self.scope + ":tensor-token:" + str(value[0])
        descriptor = {"tensor_tuple": value, "type": name, "shape": shape, "strides": strides}
        signature = _canonical_hash(descriptor)
        descriptor["descriptor_id"] = signature
        if identifier not in self.evidence.provider_references:
            record = ProviderReference(identifier, "torch.eto", self.scope,
                "tensor_reference_token", value[0], (self.claim(pointer),), metadata={
                    "lifetime": "UNKNOWN", "logical_version": None,
                    "allocation_generation": None, "observations": 0, "descriptors": []})
            self.evidence.add_provider_reference(record)
            self.reference_shapes[identifier] = set()
        record = self.evidence.provider_references[identifier]
        record.metadata["observations"] += 1
        if signature not in self.reference_shapes[identifier]:
            self.reference_shapes[identifier].add(signature)
            record.metadata["descriptors"].append(descriptor)
        instance.metadata.setdefault("tensor_slots", []).append({
            "role": role, "ordered_path": list(path), "provider_reference": identifier,
            "descriptor_id": signature, "raw_reference": pointer})
        relation = EvidenceRelation.INPUT_REFERENCE if role == "inputs" else EvidenceRelation.OUTPUT_REFERENCE
        self.edge(relation, instance.id, identifier, self.claim(pointer, assumptions=(
            "ordered provider reference observation only; not logical contents or allocation identity",)),
            kind=EvidenceNodeKind.PROVIDER_REFERENCE)

    def chrome_events(self):
        events = self.chrome["traceEvents"]
        cpu_counts = Counter()
        for event in events:
            if type(event) is not dict:
                raise ValueError("Kineto event must be an object")
            category = event.get("cat", "")
            if type(category) is not str:
                raise ValueError("Kineto category must be a string")
            self.categories[category] += 1
            args = event.get("args", {})
            if type(args) is not dict:
                raise ValueError("Kineto args must be an object")
            rf = args.get("Record function id")
            if (event.get("ph") == "X" and category in _CPU and event.get("pid") == self.pid
                    and type(event.get("pid")) is int and _integer(rf, positive=True)):
                cpu_counts[rf] += 1
        for index, event in enumerate(events):
            reference = self.pointer("kineto", f"#/traceEvents/{index}")
            category, phase = event.get("cat", ""), event.get("ph")
            if phase != "X":
                self.retained.append({"index": index, "category": category, "phase": phase,
                                      "reference": reference, "disposition": "raw_non_duration_record"})
                continue
            name, args = event.get("name"), event.get("args", {})
            if type(name) is not str or not name:
                raise ValueError("duration event name must be a nonempty string")
            rf = args.get("Record function id")
            candidates = self.rf_nodes.get(rf, ()) if _integer(rf, positive=True) else ()
            matched = (category in _CPU and _integer(rf, positive=True) and type(event.get("pid")) is int
                       and event["pid"] == self.pid and cpu_counts[rf] == 1
                       and len(candidates) == 1
                       and self.semantic.definitions[self.nodes[candidates[0]].definition].label == name)
            if matched:
                instance = self.nodes[candidates[0]]
                instance.metadata["kineto_reference"] = reference
                instance.metadata["cpu_join_basis"] = "unique positive RF ID and exact name in supplied capture"
                instance.metadata["cpu_join_status"] = "Inferred"
                instance.metadata["cpu_join_assumptions"] = ["artifacts belong to the same supplied capture"]
                instance.metadata["eto_tid"] = instance.metadata["raw_tid"]
                self.cpu_rf_matches += 1
            else:
                identifier = OperationInstanceID(self.scope + ":kineto:" + str(index))
                raw_pid = event.get("pid")
                raw_tid = event.get("tid")
                process = self.pid if category in _GPU else (
                    raw_pid if type(raw_pid) in (int, str) else "kineto-process-unresolved")
                thread = ("kineto-device-lane:" + str(raw_pid) + ":" + str(raw_tid) if category in _GPU
                          else raw_tid if type(raw_tid) in (int, str) else "kineto-thread-unresolved")
                instance = OperationInstance(identifier, self.definition(category, name), process, thread,
                    metadata={"provider": "Kineto", "raw_reference": reference})
                self.evidence.add_instance(instance)
                if category in _CPU and _integer(rf, positive=True):
                    self.gap("cpu_rf_unmatched", reference,
                             "RF ID/name/PID is missing, conflicting or nonunique; observations kept separate")
            instance.metadata.update(category=category, raw_pid=event.get("pid"), raw_tid=event.get("tid"),
                clock_domain="kineto", correlation=args.get("correlation"), external_id=args.get("External id"),
                thread_namespace="device lane, not OS TID" if category in _GPU else "Kineto host thread",
                raw_resource={key: args[key] for key in ("device", "context", "stream", "bytes") if key in args})
            if matched:
                instance.thread_id = event.get("tid") if type(event.get("tid")) in (int, str) else "kineto-thread-unresolved"
            start, duration = _ns(event.get("ts")), _ns(event.get("dur"))
            if start is not None and duration is not None:
                instance.start_ns, instance.end_ns = start, start + duration
            else:
                self.gap("duration_clock_unknown", reference, "duration timestamp is not a valid finite nonnegative value")
            correlation = args.get("correlation")
            external = args.get("External id")
            # CUSTOM0 links native activities to ordinary CPU profiler scopes.
            # USER_SCOPE/CUSTOM1, RF ID and CUDA correlation are distinct keys.
            if (category == "cpu_op" and type(event.get("pid")) is int
                    and event["pid"] == self.pid and _integer(external, positive=True)):
                self.cpu_scopes.setdefault(external, []).append(instance)
            if category in _RUNTIME or category in _GPU:
                self.scope_requests.append((instance, external, reference, category))
            if category in _RUNTIME:
                if type(event.get("pid")) is int and event["pid"] == self.pid and _integer(correlation, positive=True):
                    self.runtime_instances.setdefault(correlation, []).append(instance)
            if category in _GPU:
                self.gpu_instances.append((instance, correlation, reference))
                self.gpu_resources(instance, args, reference)
        for instance, correlation, reference in self.gpu_instances:
            candidates = self.runtime_instances.get(correlation, ()) if _integer(correlation, positive=True) else ()
            if len(candidates) == 1:
                runtime = candidates[0]
                self.edge(EvidenceRelation.SUBMITS_WORK, runtime.id, instance.id,
                    self.claim(runtime.metadata["raw_reference"], reference, inferred=True, assumptions=(
                        "fixed provider revision and one supplied capture",
                        "unique positive runtime correlation; association is not happens-before")))
                self.runtime_gpu_matches += 1
            else:
                self.gap("gpu_runtime_unmatched", reference,
                         "runtime correlation is absent or nonunique; no submission edge inferred")
        self.scope_associations()

    def scope_associations(self):
        """Import linkedActivity, never a Python parent or execution ordering.

        Pinned Kineto output_json.cpp writes linked CPU correlationId as
        External id. Its CUSTOM0 map is separate from CUSTOM1 annotations.
        One CPU scope may link many activities; only CPU candidates must be
        unique. A worker's missing association is not borrowed from a parent.
        """
        for activity, external, reference, category in self.scope_requests:
            if not _integer(external, positive=True):
                self.gap("provider_scope_unreported", reference,
                         "provider did not report a positive linked CPU scope ID; no association invented")
                continue
            candidates = self.cpu_scopes.get(external, ())
            if len(candidates) != 1:
                self.gap("provider_scope_ambiguous" if candidates else "provider_scope_missing",
                         reference, "linked CPU scope is absent or nonunique in this capture/process")
                continue
            owner, = candidates
            owner_reference = owner.metadata.get("kineto_reference", owner.metadata["raw_reference"])
            self.edge(EvidenceRelation.PROVIDER_SCOPE_ASSOCIATION, owner.id, activity.id,
                      self.claim(owner_reference, reference, inferred=True, assumptions=(
                          "supplied artifacts belong to one process capture",
                          "installed provider implements the recorded Torch and Kineto source revisions",
                          "CUSTOM0 linkedActivity and unique CPU External id; not parent, submission or ordering")))
            self.scope_matches[category] += 1

    def gpu_resources(self, instance, args, reference):
        device = args.get("device")
        if type(device) not in (int, str):
            self.gap("gpu_resource_unknown", reference, "GPU device selector is missing")
            return
        selectors = [(ResourceKind.GPU, {"process": self.pid, "device": device})]
        context, stream = args.get("context"), args.get("stream")
        if type(context) in (int, str) and type(stream) in (int, str):
            selectors.append((ResourceKind.STREAM, {"process": self.pid, "device": device,
                                                    "context": context, "stream": stream}))
        else:
            self.gap("gpu_queue_unknown", reference, "context/stream identity is incomplete")
        for kind, selector in selectors:
            key = (kind.value, _canonical_hash(selector))
            if key not in self.resource_index:
                identifier = ResourceID(self.scope + ":resource-observation:" + key[0] + ":" + key[1])
                claim = self.claim(reference, assumptions=("provider resource selector; lifetime and physical identity unknown",))
                self.semantic.resources[identifier] = ResourceRequirement(
                    identifier, kind, json.dumps(selector, sort_keys=True, separators=(",", ":")), evidence=(claim,))
                self.evidence.register_external(EvidenceEndpoint(EvidenceNodeKind.RESOURCE, identifier))
                self.resource_index[key] = identifier
                self.resources.append({"id": identifier.wire, "kind": kind.value, "scope": self.scope,
                    "selector": selector, "source_reference": reference,
                    "lifetime": "UNKNOWN", "physical_identity_established": False})
            self.edge(EvidenceRelation.USES_RESOURCE, instance.id, self.resource_index[key], self.claim(reference),
                      kind=EvidenceNodeKind.RESOURCE)

    def finish(self):
        self.eto_nodes()
        self.chrome_events()
        # Do not serialize the bundle here: validation is linear in its existing
        # indexes; the public caller decides whether and how to persist it.
        self.bundle.assert_valid()
        report = {
            "schema": "scar.native-evidence-import", "schema_version": 1,
            "scope": self.scope, "provider_revision": _REVISION, "eto_schema": _ETO_SCHEMA,
            "pid": self.pid, "artifacts": self.artifacts,
            "cpu_rf_matches": self.cpu_rf_matches, "runtime_gpu_matches": self.runtime_gpu_matches,
            "provider_scope_matches": sum(self.scope_matches.values()),
            "provider_scope_matches_by_category": dict(sorted(self.scope_matches.items())),
            "provider_scope_contract": {
                "torch_revision": _REVISION, "kineto_revision": _KINETO_REVISION,
                "correlation_kind": "CUSTOM0", "cpu_category": "cpu_op",
                "relation": "provider linked CPU scope; no call/control/order/ready claim",
                "source": "https://github.com/pytorch/kineto/blob/" + _KINETO_REVISION
                          + "/libkineto/src/output_json.cpp#L786-L807"},
            "category_counts": dict(sorted(self.categories.items())),
            "inventory": {"eto_nodes": len(self.eto["nodes"]), "kineto_events": len(self.chrome["traceEvents"]),
                          "operation_instances": len(self.evidence.instances),
                          "provider_references": len(self.evidence.provider_references),
                          "resource_observations": len(self.resources),
                          "retained_non_duration_events": len(self.retained)},
            "retained_events": self.retained, "gaps": list(self.gaps.values()),
            "budget": {"max_bytes": self.maximum,
                       "decompressed_bytes": sum(item["size_bytes"] for item in self.artifacts.values())},
            "conditions": [
                "input artifacts are supplied as one capture, not independently proven to be one window",
                "provider symbols are observational definitions, not original source definitions",
                "ETO ctrl_deps is collector-stack containment, not CUDA ordering",
                "input/output references do not establish logical content or allocation generations",
                "resource selectors do not establish resource lifetimes or physical topology",
                "unknown state/effects are not represented as unchanged canonical state",
            ],
            "whole_model_established": False, "canonical_program_graph_imported": False,
            "definition_namespace": "capture-local provider symbols; not CodeID or stable source definitions",
            "full_operand_interface_established": False, "literal_slots_imported": False,
            "execution_model_imported": False, "logical_versions_established": False,
            "state_effects_established": False, "resource_readiness_established": False,
            "python_correspondence_established": False, "transformation_authorized": False,
        }
        references = [item.as_dict() for item in self.evidence.provider_references.values()]
        return NativeImportResult(self.bundle, report, references, self.resources)


def import_native_evidence(eto_path, kineto_path, *, max_bytes=512_000_000, provider_revision: str):
    """Normalize one supplied native capture without executing or importing Torch.

    max_bytes bounds combined decompressed source bytes, not Python object or
    native-buffer memory. Unsupported/ambiguous joins remain explicit gaps.
    """
    if type(max_bytes) is not int or max_bytes < 1:
        raise ValueError("max_bytes must be a positive exact integer")
    if type(provider_revision) is not str or provider_revision != _REVISION:
        raise ValueError("unsupported native provider revision")
    eto, eto_artifact = _read(eto_path, max_bytes)
    if eto.get("schema") != _ETO_SCHEMA:
        raise ValueError("unsupported ETO schema")
    if not _integer(eto.get("pid"), positive=True) or type(eto.get("nodes")) is not list:
        raise ValueError("ETO requires a positive exact PID and node array")
    chrome, chrome_artifact = _read(kineto_path, max_bytes - eto_artifact["size_bytes"])
    if ("schemaVersion" in chrome and
            (type(chrome["schemaVersion"]) is not int or chrome["schemaVersion"] != 1)):
        raise ValueError("unsupported Kineto schemaVersion")
    if type(chrome.get("traceEvents")) is not list:
        raise ValueError("Kineto traceEvents must be an array")
    return _Importer(eto, chrome, {"eto": eto_artifact, "kineto": chrome_artifact}, max_bytes).finish()


__all__ = ["NativeImportResult", "import_native_evidence"]
