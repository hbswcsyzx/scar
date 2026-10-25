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


class NativePortOrderError(ValueError):
    """This pinned adapter's ordered ABI disagrees with the original core."""


def _native_port_order_errors(program, model, interfaces, run):
    """Pure ABI interpretation, not ownership or runtime authority.

    Generic NativeBoundary permits arbitrary representation order. Only this
    closed adapter declares flat native i == core formal/completion i. Source
    evidence sessions pass independently replayed original native signatures;
    a caller invoking this helper alone obtains no owned evidence.
    """
    from scar.ir.program.model import (BlockArgument, CompletionResult, DataValue,
        ExitKind, ReferenceValue, StateVersionValue, TerminatorKind, UseRole)
    from scar.ir.program.ids import NativeBoundaryID, ProviderID, RegionID
    from scar.ir.program.providers import (ProviderArtifactKind, ProviderElementKind,
        ProviderPathIndex, ProviderPathKey, ProviderRegionRelation)
    from .coordinates import InitialEntry
    from .content import NativeInputRef, NativeOutputRef
    errors = []

    def check(ok, code, path, message):
        if not ok:
            errors.append((code, str(path), message))
        return bool(ok)

    regions = {r.id: r for r in program.regions}
    boundaries = {b.id: b for b in program.native_boundaries}
    core_values = {v.id: v for v in program.values}
    operations = {o.id: o for o in program.operations}
    unique = {}
    for item in interfaces:
        signature = item["signature"]
        sig = sha256(canonical(signature)).hexdigest()
        if not check(item["signature_id"] == sig, "signature", sig, "raw signature hash changed"):
            continue
        if sig in unique:
            check(unique[sig]["signature"] == signature, "signature", sig, "same signature ID has different native tree")
        unique[sig] = item
    # Independently reconstruct this provider profile's declared interface
    # document, rather than trusting a builder-produced mapping/boolean.
    definition_doc = {"schema": "scar.pinned-aten-protocol-interface", "schema_version": 1,
        "profile": PROFILE, "interfaces": {sig: item["signature"] for sig, item in unique.items()},
        "effect_contract": "UNKNOWN outside partial provider schema annotations", "content_version_claimed": False}
    definition_bytes = canonical(definition_doc)
    expected_provider = ProviderID("aten-schema:" + next(iter(unique.values()))["signature"]["provider_revision"]) if unique else None
    envelope = next((e for e in program.provider_envelopes if e.id == expected_provider), None)
    check(envelope is not None and envelope.kind is ProviderArtifactKind.DEFINITION_GRAPH
          and envelope.artifact.schema == definition_doc["schema"]
          and envelope.artifact.sha256 == sha256(definition_bytes).hexdigest()
          and envelope.artifact.size_bytes == len(definition_bytes),
          "definition_artifact", "provider", "definition owner differs from independently reconstructed schema interface")
    layouts = {}
    for sig, item in unique.items():
        path = "interface:" + sig
        region_id = RegionID("aten-interface:" + sig)
        region = regions.get(region_id)
        boundary = boundaries.get(NativeBoundaryID(region_id.value + ":boundary"))
        if not check(region is not None and boundary is not None and boundary.region == region_id,
                     "region", path, "original native interface/boundary is absent"):
            continue
        check(boundary.provider == expected_provider and envelope is not None
              and boundary.signature.artifact == envelope.artifact
              and boundary.signature.locator == "#/interfaces/" + sig
              and any(r.provider == expected_provider and r.region == region_id
                      and r.external_region == sig and r.relation is ProviderRegionRelation.DEFINES_REPRESENTATION
                      for r in program.provider_regions),
              "definition_owner", path, "native interface owner/signature does not preserve this source definition")
        entry = next((b for b in region.blocks if b.id == region.entry), None)
        invocations = ([] if entry is None else [operations[o] for o in entry.operations
            if o in operations and operations[o].terminator is not None
            and operations[o].terminator.kind is TerminatorKind.INVOKE])
        if not check(entry is not None and len(invocations) == 1, "invoke", path,
                     "flat adapter requires one original opaque invocation in its entry block"):
            continue
        invoke = invocations[0]
        normal_edges = [(i, e) for i, e in enumerate(invoke.terminator.successors) if e.kind is ExitKind.NORMAL]
        if not check(len(normal_edges) == 1, "normal_edge", path, "native invocation has no unique normal completion"):
            continue
        normal_index, edge = normal_edges[0]
        normal = next((b for b in region.blocks if b.id == edge.block), None)
        returned = (None if normal is None or not normal.operations else operations.get(normal.operations[-1]))
        if not check(returned is not None and returned.terminator is not None
                     and returned.terminator.kind is TerminatorKind.RETURN,
                     "return", path, "normal completion has no original Return"):
            continue
        counts = {d: len(item["signature"][d]) for d in ("inputs", "outputs")}
        if not check(len(entry.arguments) == counts["inputs"] + 1
                     and len(normal.arguments) == counts["outputs"] + 1
                     and len(boundary.inputs) == counts["inputs"] and len(boundary.outputs) == counts["outputs"]
                     and len(invoke.uses) == len(invoke.invoke_arguments) == len(entry.arguments)
                     and len(returned.uses) == len(returned.terminator.values) == len(normal.arguments)
                     and len(edge.arguments) == len(normal.arguments),
                     "arity", path, "scalar/reference/world native and core arities differ"):
            continue
        for direction, block, slots, op, records in (
                ("inputs", entry, boundary.inputs, invoke, entry.arguments),
                ("outputs", normal, boundary.outputs, returned, normal.arguments)):
            for i, formal in enumerate(records):
                port_path = path + ":" + direction + ":" + str(i)
                value = core_values.get(formal)
                check(value is not None and type(value.origin) is BlockArgument
                      and value.origin.block == block.id and value.origin.index == i,
                      "formal_order", port_path, "flat slot does not identify its original BlockArgument ordinal")
                original_use = op.uses[i]
                use_list = invoke.invoke_arguments if direction == "inputs" else returned.terminator.values
                check(use_list[i] == original_use.id and original_use.value == formal,
                      "use_order", port_path, "original invocation/Return Use has another ordered formal")
                if direction == "outputs":
                    check(type(edge.arguments[i]) is CompletionResult and edge.arguments[i].index == i,
                          "completion_order", port_path, "normal edge permutes original CompletionResult ordinal")
                if i == counts[direction]:
                    check(type(value) is StateVersionValue and original_use.role is UseRole.STATE_CONTENT,
                          "world_order", port_path, "opaque world tail changed position/category")
                    continue
                native = item["signature"][direction][i]
                check((type(value) is ReferenceValue and original_use.role is UseRole.REFERENCE) if native["tensor"] else
                      (type(value) is DataValue and value.data_type == "native.boxed:" + native["type"]
                       and original_use.role is UseRole.DATA),
                      "value_type", port_path, "ordered native leaf changed its declared core category/type")
                slot = slots[i]
                check(slot.position == i and slot.port.region == region_id and
                      (slot.port.value == formal if direction == "inputs" else
                       slot.port.exit_name == returned.terminator.exit and slot.port.index == i),
                      "native_core_order", port_path, "native slot selects another canonical formal/exit ordinal")
                expected_path = (ProviderPathKey(direction), ProviderPathIndex(i))
                kinds = ProviderElementKind.REFERENCE_VALUE if native["tensor"] else ProviderElementKind.DATA_VALUE
                targets = [(formal, kinds)]
                if direction == "inputs":
                    targets.append((original_use.id, ProviderElementKind.USE))
                for target, kind in targets:
                    matches = [b for b in program.provider_bindings if b.provider == expected_provider
                        and b.region == region_id and b.target == target]
                    check(len(matches) == 1 and matches[0].external.kind is kind
                          and matches[0].external.key == sig and matches[0].external.path == expected_path,
                          "provider_path_order", port_path, "provider binding path does not select this exact original ordered endpoint")
        before_world, after_world = core_values.get(entry.arguments[-1]), core_values.get(normal.arguments[-1])
        check(type(before_world) is type(after_world) is StateVersionValue and before_world.location == after_world.location,
              "world_location", path, "normal opaque world does not preserve the declared state domain")
        layouts[sig] = (region_id, boundary, entry, invoke, normal_index, normal, returned)
    # Actual coordinates are checked independently of denotation identity and
    # alongside the normal generic execution-flow validation, never instead.
    segments = {s.id: s for s in model.segments}
    visits = {v.id: v for v in model.visits}
    activations = {a.id: a for a in model.activations}
    actual_values = {}
    for value in model.values:
        actual_values.setdefault((value.origin, value.value), []).append(value)
    actual_uses = {}
    for use in model.uses:
        actual_uses.setdefault((use.operation, use.use), []).append(use)
    expected_activations = set()
    for item in interfaces:
        sig = item["signature_id"]
        if sig not in layouts:
            continue
        region_id, boundary, entry, invoke, normal_index, normal, returned = layouts[sig]
        expected_id = "native-port:" + run + ":" + str(item["sequence"])
        candidates = [a for a in model.activations if a.id.value == expected_id]
        if not check(len(candidates) == 1 and candidates[0].region == region_id,
                     "activation", expected_id, "source sequence has no unique exact native activation"):
            continue
        activation = candidates[0];expected_activations.add(activation.id)
        owned_segments = [s for s in model.segments if s.activation == activation.id]
        if not check(len(owned_segments) == 1 and type(owned_segments[0].ingress) is InitialEntry
                     and activation.entry.run.value == run,
                     "segment", expected_id, "normal native protocol activation/Run has no exact initial segment"):
            continue
        segment = owned_segments[0]
        entry_visits = [v for v in model.visits if v.segment == segment.id and v.block == entry.id]
        normal_visits = [v for v in model.visits if v.segment == segment.id and v.block == normal.id]
        if not check(len(entry_visits) == len(normal_visits) == 1,
                     "visit", expected_id, "normal native call has no unique entry/completion visits"):
            continue
        entry_visit, normal_visit = entry_visits[0], normal_visits[0]
        invoked = [o for o in model.operations if o.visit == entry_visit.id and o.operation == invoke.id]
        completed = [o for o in model.operations if o.visit == normal_visit.id and o.operation == returned.id]
        if not check(len(invoked) == len(completed) == 1, "occurrence", expected_id,
                     "native invocation/normal Return occurrence missing or ambiguous"):
            continue
        invoked, completed = invoked[0], completed[0]
        transfers = [t for t in model.transfers if t.operation == invoked.id]
        check(len(transfers) == 1 and transfers[0].successor_index == normal_index
              and transfers[0].target == normal_visit.id,
              "actual_completion", expected_id, "actual normal completion does not select its original normal result edge")
        for direction, block, visit, op, occurrence in (
                ("inputs", entry, entry_visit, invoke, invoked),
                ("outputs", normal, normal_visit, returned, completed)):
            for i, formal in enumerate(block.arguments):
                path = expected_id + ":" + direction + ":" + str(i)
                values = actual_values.get((visit.id, formal), [])
                uses = actual_uses.get((occurrence.id, op.uses[i].id), [])
                if not check(len(values) == len(uses) == 1 and uses[0].value == values[0].id,
                             "actual_use_order", path, "actual original Use does not read this exact formal ValueOccurrence"):
                    continue
                if i >= len(item["signature"][direction]) or not item["signature"][direction][i]["tensor"]:
                    continue
                denotations = [d for d in model.denotations if type(d.basis) is
                    (NativeInputRef if direction == "inputs" else NativeOutputRef)
                    and d.basis.boundary == boundary.id and d.basis.position == i
                    and (d.basis.entry == entry_visit.id if direction == "inputs" else d.basis.operation == completed.id)]
                check(len(denotations) == 1 and denotations[0].value == values[0].id,
                      "actual_native_order", path, "native slot/denotation does not preserve the actual original Use value ordinal")
    check(set(activations) == expected_activations, "activation_inventory", "model",
          "native window has missing or extra canonical activations")
    return tuple(errors)


def _require_native_port_order(program, model, interfaces, run):
    errors = _native_port_order_errors(program, model, interfaces, run)
    if errors:
        raise NativePortOrderError("native_port_order: " + "; ".join(
            code + " at " + path + ": " + message for code, path, message in errors))


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
        _require_native_port_order(program, model, json.loads(self._interfaces), owned.source()["run"])

    def require_scope(self, model, program):
        from scar.ir.program.codec import dumps as program_dumps
        from .codec import dumps
        need(self._program_sha == sha256(program_dumps(program).encode()).hexdigest()
             and self._model_sha == sha256(dumps(model).encode()).hexdigest(),
             "owned native port evidence does not apply to this exact program/execution/Run")
        _require_native_port_order(program, model, json.loads(self._interfaces), self._owned.source()["run"])

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
