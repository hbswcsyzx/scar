"""Owned replay of pinned native reference ports, without content/ready proof.

Only trace.native_protocol's source-owning reader creates this session. Saved
reports, arbitrary provider tokens and callers' slot dictionaries cannot replace
it. The raw capture and projected catalogs retain distinct qualified identities.
"""
from __future__ import annotations

from hashlib import sha256
import json

from scar.ir.program.providers import ProviderArtifact
from .content import NativeInputRef, NativeOutputRef, ObjectIdentity

PROFILE = "PINNED_ATEN_HELD_REFERENCE_PORT_V1"
_OWNER = object()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


def need(condition, message):
    if not condition:
        raise ValueError("native reference protocol: " + message)


def attributes(node):
    rows = node.get("attrs")
    need(type(rows) is list and all(type(r) is dict for r in rows), "missing native attributes")
    result = {r["name"]: r["value"] for r in rows}
    need(len(result) == len(rows), "duplicate native attributes")
    return result


def flat_native(box):
    """Flatten the actual provider tree, retaining every scalar/container leaf."""
    from scar.trace.native_import import _element_types
    fields = ("values", "types", "shapes", "strides")
    need(type(box) is dict and all(type(box.get(k)) is list for k in fields), "invalid native boxed tree")
    need(len({len(box[k]) for k in fields}) == 1, "boxed arities differ")
    result = []

    def descend(value, type_name, shape, strides, path):
        need(len(path) <= 64 and type(type_name) is str, "native tree depth/type")
        children = _element_types(type_name)
        if children is not None:
            need(type(value) is list and type(shape) is list and type(strides) is list,
                 "container payload is not an ordered provider list")
            need(len(value) == len(shape) == len(strides), "container geometry arities differ")
            if value:
                if len(children) == 1:
                    children = children * len(value)
                need(len(children) == len(value), "container type/actual arities differ")
                for i, (v, t, s, z) in enumerate(zip(value, children, shape, strides, strict=True)):
                    descend(v, t, s, z, path + [i])
                return
        tensor = type_name == "Tensor" or type_name.startswith("Tensor(")
        if tensor:
            need(type(value) is list and len(value) == 6 and type(value[0]) is int
                 and type(value[2]) is int and value[2] >= 0
                 and type(shape) is list and type(strides) is list and len(shape) == len(strides),
                 "Tensor leaf lacks the pinned ordered tuple/geometry")
        result.append({"path": path, "type": type_name, "tensor": tensor,
                       "value": value, "shape": shape, "strides": strides})

    for i, (v, t, s, z) in enumerate(zip(*(box[k] for k in fields), strict=True)):
        descend(v, t, s, z, [i])
    return result


def replay_interfaces(source):
    """Recompute direct-child/schema/tree/held-slot matches from original rows.

    A per-sequence frontier is not silently removed. Contradictory identities
    reject the evidence rather than changing the matching strategy.
    """
    from scar.trace.native_schema import parse_schema_ports, _tensor_path, PROVIDER_REVISION
    need(source["provider_revision"] == PROVIDER_REVISION, "provider revision differs")
    pid, nonce = source["pid"], source["nonce"]
    nodes = {n["id"]: n for n in source["nodes"]}
    need(len(nodes) == len(source["nodes"]), "duplicate ETO node IDs")
    names = {}
    for node in nodes.values():
        names.setdefault(node["name"], []).append(node)
    groups = {}
    for row in source["dispatch"]:
        need(row["process_id"] == pid, "dispatch process differs")
        groups.setdefault(row["sequence"], []).append(row)
    physical = {r["marker"]: r for r in source["physical"] if r["kind"] == "MARKER"}
    need(len(physical) == sum(r["kind"] == "MARKER" for r in source["physical"]), "duplicate physical marker")
    interfaces, frontiers = [], []
    for seq in range(source["first_sequence"], source["first_sequence"] + source["max_sequences"]):
        rows = groups.get(seq, [])
        if [r.get("kind") for r in rows] != ["DISPATCH_BEGIN", "DISPATCH_OUTPUT", "DISPATCH_END"]:
            frontiers.append({"sequence": seq, "reason": "NORMAL_DISPATCH_GROUP_NOT_AVAILABLE"}); continue
        begin, output, end = rows
        if not (end.get("outcome") == "RETURNED" and end.get("span_enter_returned") is True
                and not begin.get("slot_gaps") and not output.get("slot_gaps")):
            frontiers.append({"sequence": seq, "reason": "NORMAL_HELD_SLOTS_NOT_QUALIFIED"}); continue
        operator = begin.get("operator")
        if type(operator) is not str or not operator.startswith("aten."):
            frontiers.append({"sequence": seq, "reason": "OUTSIDE_PINNED_ATEN_SCHEMA_DOMAIN", "operator": operator}); continue
        span_name = f"scar-dispatch:{nonce}:{pid}:{seq}:span"
        out_name = f"scar-dispatch:{nonce}:{pid}:{seq}:output"
        need(begin.get("marker") == span_name and output.get("marker") == end.get("output_marker") == out_name,
             "normal dispatch group marker mismatch")
        need(len(names.get(span_name, [])) == len(names.get(out_name, [])) == 1, "owned marker lacks unique original node")
        span, marker = names[span_name][0], names[out_name][0]
        need(marker["ctrl_deps"] == span["id"] and attributes(marker)["tid"] == attributes(span)["tid"],
             "output marker is not in the exact native span/thread")
        candidates = []
        for node in nodes.values():
            raw = attributes(node).get("op_schema")
            if node.get("ctrl_deps") != span["id"] or type(raw) is not str or not raw:
                continue
            schema, args, rets = parse_schema_ports(raw)
            key = schema.name.replace("::", ".") + "." + (schema.overload_name or "default")
            if key == operator:
                candidates.append((node, schema, args, rets, raw))
        need(len(candidates) == 1, "schema/OpOverload has no unique direct native child")
        node, schema, args, rets, raw_schema = candidates[0]
        need(node["name"] == schema.name and attributes(node)["tid"] == attributes(span)["tid"],
             "direct native child label/thread differs from schema/span")
        need(len(node["inputs"]["values"]) == len(args) and len(node["outputs"]["values"]) == len(rets),
             "schema/native boxed arities differ")
        ports = {"inputs": flat_native(node["inputs"]), "outputs": flat_native(node["outputs"])}
        for direction, row, marker_node, formal in (
                ("inputs", begin, span, schema.arguments), ("outputs", output, marker, schema.returns)):
            obs = row["observation"]
            need(obs["process_id"] == pid and obs["native_tid"] == source["owner_native_tid"]
                 and obs["python_ident"] == source["owner_python_ident"], "held observation has another process/thread")
            refs = obs.get("tensor_references")
            need(type(refs) is list, "held reference inventory missing")
            tensor_ports = {tuple(p["path"]): p for p in ports[direction] if p["tensor"]}
            held_paths = set()
            marker_ports = flat_native(marker_node["inputs"])
            need(len(marker_ports) == len(refs) and all(p["tensor"] for p in marker_ports),
                 "marker/native held Tensor arities differ")
            physical_row = physical.get(row["marker"])
            need(physical_row is not None and not physical_row["gaps"]
                 and physical_row["binding_status"] == "PROVISIONAL_REQUIRES_FINAL_METADATA"
                 and physical_row["dispatch_source_line"] == row["index"]
                 and physical_row["sequence"] == seq
                 and physical_row["dispatch_native_tid"] == obs["native_tid"]
                 and physical_row["dispatch_python_ident"] == obs["python_ident"]
                 and physical_row["event"]["record_function_thread_token"] == attributes(marker_node)["tid"]
                 and physical_row["event"]["correlation_id"] == attributes(marker_node)["rf_id"]
                 and physical_row["expected_argument_count"] == len(refs)
                 and len(physical_row["arguments"]) == len(refs), "physical marker identity/slot inventory differs")
            for ordinal, (ref, marker_port, argument) in enumerate(zip(refs, marker_ports, physical_row["arguments"], strict=True)):
                path = ref["path"]
                need(type(path) is list and ref.get("identity_qualified") is True
                     and type(ref.get("ref")) is str and ref["ref"].startswith(f"weak:{pid}:"),
                     "held slot lacks the original WeakRef epoch")
                if direction == "inputs":
                    need(len(path) >= 2 and path[0] in (0, 1), "held input args/kwargs path is missing")
                    if path[0] == 0:
                        target = path[1:]
                    else:
                        matches = [i for i, a in enumerate(schema.arguments) if a.name == path[1]]
                        need(len(matches) == 1, "keyword does not select exactly one schema argument")
                        target = [matches[0], *path[2:]]
                else:
                    target = [0, *path] if len(rets) == 1 else path
                need(type(target[0]) is int and 0 <= target[0] < len(formal)
                     and _tensor_path(formal[target[0]].type, target[1:])[0], "held Tensor path conflicts with formal JIT type")
                key = tuple(target)
                need(key in tensor_ports and key not in held_paths, "held Tensor path is missing/duplicate")
                held_paths.add(key)
                port = tensor_ports[key]
                need(marker_port["path"] == [ordinal]
                     and all(marker_port[k] == port[k] for k in ("value", "shape", "strides", "type")),
                     "native child slot differs from actual held marker tuple/geometry")
                metadata = argument.get("metadata")
                need(argument.get("argument_ordinal") == argument.get("dispatch_reference_ordinal") == ordinal
                     and type(metadata) is dict and metadata.get("status") == "OBSERVED" and not metadata.get("gaps")
                     and metadata.get("sizes") == port["shape"] and metadata.get("strides") == port["strides"]
                     and metadata.get("device", {}).get("text") == port["value"][5]
                     and type(metadata.get("provider_allocation_id")) is int,
                     "physical Tensor metadata contradicts actual held native slot")
                port["held"] = {"weak_token": ref["ref"], "dispatch_line": row["index"],
                    "physical_line": physical_row["index"], "marker_node": marker_node["id"],
                    "marker_ordinal": ordinal, "metadata": metadata}
            need(held_paths == set(tensor_ports), "native Tensor leaf lacks held-reference correspondence")
        signature = {"provider_revision": PROVIDER_REVISION, "schema": raw_schema,
            **{d: [{"path": p["path"], "type": p["type"], "tensor": p["tensor"]} for p in ports[d]]
               for d in ("inputs", "outputs")}}
        interfaces.append({"sequence": seq, "node": node, "span": span, "output_marker": marker,
                           "signature": signature, "signature_id": sha256(canonical(signature)).hexdigest(),
                           "ports": ports, "source_lines": [r["index"] for r in rows]})
    return interfaces, frontiers


class _OwnedNativeCapture:
    __slots__ = ("_payload",)

    def __init__(self, key, source):
        need(key is _OWNER, "native evidence can only originate in its owning reader")
        self._payload = canonical(source)

    def source(self):
        return json.loads(self._payload)


def _own_capture(source):
    return _OwnedNativeCapture(_OWNER, source)


class NativePortEvidence:
    """Immutable source-owned port resolver, sealed to one exact native window.

    This grants reference/port correspondence only. It does not interpret
    logical contents, hidden effects, alias completeness, CUDA order or ready.
    """
    __slots__ = ("_owned", "_program_sha", "_model_sha", "_value_artifact", "_evidence_artifact", "_interfaces")

    def __init__(self, key, owned, program, model, value_artifact, evidence_artifact):
        need(key is _OWNER and type(owned) is _OwnedNativeCapture, "owned source session is required")
        from scar.ir.program.codec import dumps as program_dumps
        from .codec import dumps
        self._owned = owned
        self._program_sha = sha256(program_dumps(program).encode()).hexdigest()
        self._model_sha = sha256(dumps(model).encode()).hexdigest()
        need(type(value_artifact) is type(evidence_artifact) is ProviderArtifact, "projection artifacts are required")
        self._value_artifact, self._evidence_artifact = value_artifact, evidence_artifact
        self._interfaces = canonical(replay_interfaces(owned.source())[0])

    def require_scope(self, model, program):
        from scar.ir.program.codec import dumps as program_dumps
        from .codec import dumps
        need(self._program_sha == sha256(program_dumps(program).encode()).hexdigest()
             and self._model_sha == sha256(dumps(model).encode()).hexdigest(),
             "owned native port evidence does not apply to this exact program/execution/Run")

    def resolve(self, ctx, basis, resolved, identity, path):
        """Replay original ordered ports independently of builder declarations."""
        if resolved is None or resolved["value"] is None or type(identity) is not ObjectIdentity:
            return False
        # Scope checked once by normal _analyze. NativeInput/Output select the
        # canonical current visit/completion independently in content_validation.
        activation = (ctx.activations[ctx.segments[ctx.visits[basis.entry].segment].activation]
                      if type(basis) is NativeInputRef else ctx.activations[ctx.activation_of(basis.operation)])
        source = self._owned.source()
        candidates = [i for i in json.loads(self._interfaces)
                      if activation.id.value == "native-port:" + source["run"] + ":" + str(i["sequence"])]
        if len(candidates) != 1:
            ctx.issue("native_reference_activation", path, "activation has no exact owned native sequence"); return False
        interface = candidates[0]
        direction = "inputs" if type(basis) is NativeInputRef else "outputs"
        boundary = resolved["boundary"]
        expected_boundary = "aten-interface:" + interface["signature_id"] + ":boundary"
        if boundary.id.value != expected_boundary or basis.position >= len(interface["ports"][direction]):
            ctx.issue("native_reference_slot", path, "canonical boundary/ordered slot differs from actual native schema"); return False
        native = interface["ports"][direction][basis.position]
        if not native["tensor"] or "held" not in native:
            return False
        held = native["held"]
        original = source["object_records"].get(held["weak_token"])
        if original is None:
            ctx.issue("native_reference_source", path, "original held ObjectInstance is missing"); return False
        from scar.ir.record_codec import encode
        if (identity.object.artifact != self._value_artifact
                or encode(identity.object.object) != original["id"]):
            ctx.issue("native_reference_object", path, "denotation selects another original held object/projection"); return False
        # Actual invocation must retain the exact original instance, with the
        # new projection namespace rather than the whole-source graph identity.
        occurrences = [o for o in ctx.model.operations if ctx.activation_of(o.id) == activation.id
                       and ctx.core_operations[o.operation].terminator.kind.value == "INVOKE"]
        bindings = [b for b in ctx.model.evidence_bindings if len(occurrences) == 1 and b.operation == occurrences[0].id]
        expected_instance = source["native_scope"] + ":eto:" + str(interface["node"]["id"])
        if (len(bindings) != 1 or bindings[0].legacy.artifact != self._evidence_artifact
                or bindings[0].legacy.instance.value != expected_instance):
            ctx.issue("native_reference_occurrence", path, "canonical invocation lacks exact direct-child evidence"); return False
        # ExternalSnapshots verifies the projection canonical bytes and registry;
        # source correspondence was independently replayed from immutable raw rows.
        graph = ctx.external_values(self._value_artifact, path)
        if graph is None or identity.object.object not in graph.objects:
            ctx.issue("native_reference_projection", path, "held object is absent from exact projection"); return False
        if graph.objects[identity.object.object].as_dict() != original:
            ctx.issue("native_reference_record", path, "projected held object changed its complete original record"); return False
        return True


def _make_evidence(owned, program, model, value_artifact, evidence_artifact):
    return NativePortEvidence(_OWNER, owned, program, model, value_artifact, evidence_artifact)


__all__ = ["NativePortEvidence", "PROFILE"]
