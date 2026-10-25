"""Owned replay of pinned native reference ports, without content/ready proof.

Only trace.native_protocol's source-owning reader creates this session. Saved
reports, arbitrary provider tokens and callers' slot dictionaries cannot replace
it. The raw capture and projected catalogs retain distinct qualified identities.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from types import MappingProxyType
import json

from scar.ir.program.providers import ProviderArtifact
from .content import NativeInputRef, NativeOutputRef, ObjectIdentity

PROFILE = "PINNED_ATEN_HELD_REFERENCE_PORT_V1"
PROFILE_V2 = "PINNED_TORCH_NATIVE_PORT_HELD_SUBSET_V2"
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
            # The closed owned marker and exact ordered held slots supply the
            # bridge; tree correlation_id is not an ETO RecordFunction ID.
            need(physical_row is not None and not physical_row["gaps"]
                 and physical_row["binding_status"] == "PROVISIONAL_REQUIRES_FINAL_METADATA"
                 and physical_row["dispatch_source_line"] == row["index"]
                 and physical_row["sequence"] == seq
                 and physical_row["dispatch_native_tid"] == obs["native_tid"]
                 and physical_row["dispatch_python_ident"] == obs["python_ident"]
                 and physical_row["event"]["record_function_thread_token"] == attributes(marker_node)["tid"]
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


def _native_slot_fact(source, interface, direction, port):
    suffix = "/".join(str(i) for i in port["path"])
    return {"artifact": source["artifacts"]["eto"], "locator": "#/nodes/" +
        str(source["node_ordinals"][str(interface["node"]["id"])] ) + "/" + direction + "/values/" + suffix}


def _native_region_layout_view(region, *, point_layout, profile, provider_revision):
    """Check raw or explicitly normalized layout against its actual point.

    The receipt selects a representation rule, never a weaker geometry or
    identity check. Canonical spellings without their complete receipt reject.
    """
    from scar.trace.tensor_physical_import import canonical_tensor_layout
    need(type(region) is dict and type(region.get('metadata')) is dict,
         'native region layout view requires its original record metadata')
    metadata, layout = region['metadata'], region['layout']
    receipt = 'provider_layout' in metadata or 'layout_normalization_rule' in metadata
    if receipt:
        need(metadata.get('layout_normalization_rule') == 'PINNED_TORCH_LAYOUT_V1'
             and type(metadata.get('provider_layout')) is str and bool(metadata['provider_layout']),
             'native region layout normalization receipt is incomplete or unsupported')
        provider_layout = metadata['provider_layout']
        canonical_layout = canonical_tensor_layout(provider_layout, profile=profile, provider_revision=provider_revision)
        need(layout == canonical_layout, 'native region canonical layout contradicts its original provider receipt')
        view = 'ALREADY_CANONICAL_PINNED_TORCH_LAYOUT_V1'
    else:
        provider_layout = layout
        canonical_layout = canonical_tensor_layout(provider_layout, profile=profile, provider_revision=provider_revision)
        view = 'RAW_PROVIDER_LAYOUT'
    need(provider_layout == point_layout, 'native region provider layout contradicts exact physical point')
    return {'source_view': view, 'provider_layout': provider_layout, 'canonical_layout': canonical_layout,
            'rule': 'PINNED_TORCH_LAYOUT_V1'}


def _geometry_v2(source, port, marker, physical, ordinal):
    """Point geometry is independent of Python object identity qualification."""
    gap = lambda reason: {"status": "UNPROVED", "reason": reason}
    if physical is None:
        return gap("PHYSICAL_MARKER_UNAVAILABLE")
    if physical.get("gaps"):
        return gap("PHYSICAL_MARKER_GAPS")
    arguments = physical.get("arguments", [])
    if ordinal >= len(arguments):
        return gap("PHYSICAL_SLOT_UNAVAILABLE")
    arg = arguments[ordinal]
    need(arg.get("argument_ordinal") == arg.get("dispatch_reference_ordinal") == ordinal,
         "physical argument ordinal contradicts known held slot")
    meta = arg.get("metadata") or {}
    if meta.get("status") != "OBSERVED" or meta.get("gaps"):
        return gap("PHYSICAL_METADATA_UNAVAILABLE")
    if type(meta.get("provider_allocation_id")) is not int:
        return gap("PHYSICAL_EPOCH_UNAVAILABLE")
    need(meta.get("sizes") == port["shape"] and meta.get("strides") == port["strides"]
         and meta.get("device", {}).get("text") == port["value"][5],
         "qualified physical metadata contradicts native held marker")
    epoch = (meta["device"]["text"], meta["provider_allocation_id"])
    births = [r for r in source["physical"] if r.get("kind") == "ALLOCATION"
              and (r["device"]["text"], r["provider_allocation_id"]) == epoch and r["alloc_size"] > 0]
    need(len(births) <= 1, "contradictory duplicate original allocation births")
    if not births:
        return gap("ORIGINAL_ALLOCATION_BIRTH_UNAVAILABLE")
    key = str(physical["index"]) + ":" + str(ordinal)
    witness = source.get("geometry_records", {}).get(key)
    if witness is None or witness.get("region") is None or witness.get("allocation") is None:
        return gap("ORIGINAL_GEOMETRY_RECORD_UNAVAILABLE")
    region, allocation = witness["region"]["record"], witness["allocation"]["record"]
    layout_view = _native_region_layout_view(region, point_layout=meta['layout'],
        profile=source['physical_profile'], provider_revision=source['provider_revision'])
    physical_ref = "sha256:" + source["artifacts"]["physical"]["sha256"] + "#line/" + str(physical["index"]) + "/arguments/" + str(ordinal)
    native_ref = "sha256:" + source["artifacts"]["eto"]["sha256"] + "#/nodes/" + str(source["node_ordinals"][str(marker["id"])]) + "/inputs/values/" + str(ordinal)
    need(region["metadata"]["physical_observation"] == physical_ref
         and region["metadata"]["eto_reference"] == native_ref
         and region["metadata"]["marker_instance"] == "opinst:" + source["native_scope"] + ":eto:" + str(marker["id"])
         and region["metadata"]["impl_ptr"] == meta["impl_ptr"]
         and region["metadata"]["provider_tensor_id"] == meta["provider_tensor_id"]
         and region["offset"] == port["value"][2] and region["shape"] == port["shape"]
         and region["strides"] == port["strides"] and region["dtype"] == meta["dtype"]
         and region["device"] == meta["device"]["text"] and layout_view['provider_layout'] == meta["layout"],
         "original region contradicts qualified point geometry")
    need(region["allocation"] == allocation["id"] and allocation["device"] == region["device"]
         and allocation["metadata"]["provider_allocation_id"] == epoch[1]
         and allocation["metadata"]["address"] == meta["storage_data_ptr"]
         and allocation["lifetime_scope"] == source["physical_scope"] and allocation["nbytes"] == births[0]["alloc_size"],
         "original allocation contradicts qualified epoch/birth")
    return {"status": "QUALIFIED", "physical_line": physical["index"], "argument_ordinal": ordinal,
            "region": region["id"], "allocation": allocation["id"], "point": physical_ref}


def replay_batch_interfaces(source):
    """V2: native structure, held object identity and geometry are distinct.

    Native-only Tensor ports retain their actual native type/path. No wrapped
    origin, Python object, scalar contents or physical epoch is manufactured.
    """
    from scar.trace.native_schema import parse_schema_ports, _tensor_path, PROVIDER_REVISION
    need(source.get("reference_profile") == PROFILE_V2 and source["provider_revision"] == PROVIDER_REVISION,
         "V2 source owner/profile/provider differs")
    nodes = {n["id"]: n for n in source["nodes"]}
    need(len(nodes) == len(source["nodes"]), "duplicate original native node")
    names, groups = {}, {}
    for n in nodes.values():
        names.setdefault(n["name"], []).append(n)
    for row in source["dispatch"]:
        need(type(row.get("process_id")) is int and row["process_id"] == source["pid"], "dispatch process differs")
        groups.setdefault(row["sequence"], []).append(row)
    physical = {r["marker"]: r for r in source["physical"] if r.get("kind") == "MARKER"}
    need(len(physical) == sum(r.get("kind") == "MARKER" for r in source["physical"]), "duplicate physical marker")
    interfaces, frontiers = [], []
    for seq in range(source["first_sequence"], source["first_sequence"] + source["max_sequences"]):
        rows = groups.get(seq, [])
        if [r.get("kind") for r in rows] != ["DISPATCH_BEGIN", "DISPATCH_OUTPUT", "DISPATCH_END"]:
            frontiers.append({"sequence": seq, "reason": "NORMAL_DISPATCH_GROUP_NOT_AVAILABLE"}); continue
        begin, output, end = rows
        expected = {"DISPATCH_BEGIN": f"scar-dispatch:{source['nonce']}:{source['pid']}:{seq}:span",
                    "DISPATCH_OUTPUT": f"scar-dispatch:{source['nonce']}:{source['pid']}:{seq}:output"}
        for row in (begin, output):
            need(row.get("marker") == expected[row["kind"]], "dispatch marker nonce/process/sequence/phase differs")
            obs = row.get("observation", {})
            need(obs.get("process_id") == source["pid"] and obs.get("native_tid") == source["owner_native_tid"]
                 and obs.get("python_ident") == source["owner_python_ident"], "held observation belongs to another owner")
        if end.get("output_marker") is not None:
            need(end["output_marker"] == output["marker"] and end.get("outcome") == "RETURNED" and end.get("span_enter_returned") is True,
                 "END names another or unsuccessful output")
        if end.get("outcome") != "RETURNED" or end.get("span_enter_returned") is not True:
            frontiers.append({"sequence": seq, "reason": "NORMAL_COMPLETION_NOT_AVAILABLE"}); continue
        operator = begin.get("operator")
        if type(operator) is not str or not operator:
            frontiers.append({"sequence": seq, "reason": "REGISTERED_OPERATOR_IDENTITY_UNAVAILABLE", "operator": operator}); continue
        spans, results = names.get(begin["marker"], []), names.get(output["marker"], [])
        need(len(spans) <= 1 and len(results) <= 1, "duplicate original native dispatch marker")
        if not spans:
            frontiers.append({"sequence": seq, "reason": "ORIGINAL_ETO_SPAN_UNAVAILABLE"}); continue
        span, result = spans[0], results[0] if results else None
        if result is not None:
            need(result["ctrl_deps"] == span["id"] and attributes(result)["tid"] == attributes(span)["tid"], "output parent/thread differs")
        candidates = []
        unsupported_schema = None
        for node in nodes.values():
            raw = attributes(node).get("op_schema")
            if node["ctrl_deps"] == span["id"] and type(raw) is str and raw:
                try:
                    schema, args, rets = parse_schema_ports(raw)
                except RuntimeError as error:
                    unsupported_schema = {"node": node["id"], "detail": str(error)[:512]}
                    continue
                key = schema.name.replace("::", ".") + "." + (schema.overload_name or "default")
                if key == operator:
                    candidates.append((node, schema, args, rets, raw))
        need(len(candidates) <= 1, "ambiguous direct native schema child")
        if unsupported_schema is not None:
            frontiers.append({"sequence": seq, "reason": "SCHEMA_TYPE_RESOLUTION_UNAVAILABLE", **unsupported_schema}); continue
        if not candidates:
            frontiers.append({"sequence": seq, "reason": "DIRECT_SCHEMA_NATIVE_CHILD_UNAVAILABLE"}); continue
        node, schema, args, rets, raw_schema = candidates[0]
        need(node["name"] == schema.name and attributes(node)["tid"] == attributes(span)["tid"], "native child schema/thread differs")
        if len(node["inputs"]["values"]) != len(args) or len(node["outputs"]["values"]) != len(rets):
            frontiers.append({"sequence": seq, "reason": "NATIVE_SCHEMA_BOXED_ARITY_UNSUPPORTED", "node": node["id"]}); continue
        try:
            ports = {d: flat_native(node[d]) for d in ("inputs", "outputs")}
        except ValueError as error:
            frontiers.append({"sequence": seq, "reason": "NATIVE_BOXED_TREE_UNSUPPORTED", "node": node["id"], "detail": str(error)[:512]}); continue
        interface = {"sequence": seq, "operator": operator, "node": node, "span": span, "output_marker": result,
                     "ports": ports, "source_lines": [r["index"] for r in rows]}
        for direction, row, marker, formals in (("inputs", begin, span, schema.arguments), ("outputs", output, result, schema.returns)):
            tensor_ports = {tuple(p["path"]): p for p in ports[direction] if p["tensor"]}
            for p in tensor_ports.values():
                p["identity_reason"] = "NATIVE_TENSOR_WITHOUT_QUALIFIED_PYTHON_HELD_OBJECT"
                p["geometry"] = {"status": "UNPROVED", "reason": "NATIVE_ONLY_NO_HELD_PHYSICAL_SLOT"}
            refs = row["observation"].get("tensor_references")
            need(type(refs) is list, "held reference inventory missing")
            if marker is None:
                continue
            marker_ports = flat_native(marker["inputs"])
            need(len(marker_ports) == len(refs) and all(p["tensor"] for p in marker_ports), "held marker Tensor inventory differs")
            phys = physical.get(row["marker"])
            if phys is not None:
                if phys.get("expected_argument_count") is not None:
                    need(type(phys["expected_argument_count"]) is int and phys["expected_argument_count"] == len(refs),
                         "known physical marker expected slot inventory differs")
                need(len(phys.get("arguments", [])) <= len(refs), "physical marker has extra undeclared held arguments")
                for field, value in (("dispatch_source_line", row["index"]), ("sequence", seq),
                                     ("dispatch_native_tid", source["owner_native_tid"]), ("dispatch_python_ident", source["owner_python_ident"])):
                    if phys.get(field) is not None:
                        need(phys[field] == value, "known physical marker source identity differs")
                event = phys.get("event") or {}
                # Preserve the owned-marker/slot and RecordFunction-thread
                # checks without equating the independent correlation/RF IDs.
                if event.get("record_function_thread_token") is not None:
                    need(event["record_function_thread_token"] == attributes(marker)["tid"],
                         "known physical marker thread differs")
            matched = set()
            for ordinal, (ref, marker_port) in enumerate(zip(refs, marker_ports, strict=True)):
                path = ref.get("path")
                need(type(path) is list and ref.get("identity_qualified") is True
                     and type(ref.get("ref")) is str and ref["ref"].startswith(f"weak:{source['pid']}:"), "held slot identity unqualified")
                if direction == "inputs":
                    need(len(path) >= 2 and path[0] in (0, 1), "held input args/kwargs path missing")
                    if path[0] == 0:
                        target = path[1:]
                    else:
                        matches = [i for i, a in enumerate(schema.arguments) if a.name == path[1]]
                        need(len(matches) == 1, "held keyword selects no unique formal")
                        target = [matches[0], *path[2:]]
                else:
                    target = [0, *path] if len(rets) == 1 else path
                key = tuple(target)
                need(key in tensor_ports and key not in matched and type(target[0]) is int
                     and _tensor_path(formals[target[0]].type, target[1:])[0], "held Tensor path contradicts native/formal path")
                matched.add(key)
                port = tensor_ports[key]
                need(marker_port["path"] == [ordinal] and all(marker_port[k] == port[k] for k in ("value", "shape", "strides", "type")),
                     "known held marker and actual native Tensor differ")
                port["held"] = {"weak_token": ref["ref"], "dispatch_line": row["index"], "marker_node": marker["id"],
                                "marker_ordinal": ordinal, "physical_line": None if phys is None else phys["index"]}
                original = source.get("object_records", {}).get(ref["ref"])
                if original is not None:
                    need(original["metadata"]["weak_token"] == ref["ref"] and original["metadata"]["process_id"] == source["pid"],
                         "original held object record contradicts source")
                    port["object_record"] = original
                    port.pop("identity_reason")
                else:
                    port["identity_reason"] = "ORIGINAL_HELD_OBJECT_RECORD_UNAVAILABLE"
                port["geometry"] = _geometry_v2(source, port, marker, phys, ordinal)
        signature = {"provider_revision": PROVIDER_REVISION, "schema": raw_schema,
            **{d: [{"path": p["path"], "type": p["type"], "tensor": p["tensor"]} for p in ports[d]] for d in ports}}
        interface.update(signature=signature, signature_id=sha256(canonical(signature)).hexdigest())
        interfaces.append(interface)
    return interfaces, frontiers


class NativePortOrderError(ValueError):
    """This pinned adapter's ordered ABI disagrees with the original core."""


def _native_static_order(program, interfaces, *, definition_signatures=None, profile=PROFILE):
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
    from .content import NativeInputRef, NativeOutputRef
    need(profile in (PROFILE, PROFILE_V2), "unsupported native source profile")
    region_prefix = "torch-interface:" if profile == PROFILE_V2 else "aten-interface:"
    provider_prefix = "torch-schema:" if profile == PROFILE_V2 else "aten-schema:"
    interface_schema = "scar.pinned-torch-protocol-interface" if profile == PROFILE_V2 else "scar.pinned-aten-protocol-interface"
    errors = []

    def check(ok, code, path, message):
        if not ok:
            errors.append((code, str(path), message))
        return bool(ok)

    regions = {r.id: r for r in program.regions}
    binding_index = {}
    for binding in program.provider_bindings:
        binding_index.setdefault((binding.provider, binding.region, binding.target), []).append(binding)
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
    definitions = unique
    if definition_signatures is not None:
        need(type(definition_signatures) is dict, "owned definition catalog must be an exact dictionary")
        definitions = {}
        for sig, signature in definition_signatures.items():
            if check(type(sig) is str and sha256(canonical(signature)).hexdigest() == sig,
                     "signature", sig, "owned static signature hash changed"):
                definitions[sig] = {"signature": signature}
        for sig in unique:
            check(sig in definitions and definitions[sig]["signature"] == unique[sig]["signature"],
                  "signature_catalog", sig, "actual signature is absent from shared source catalog")
    # Independently reconstruct this provider profile's declared interface
    # document, rather than trusting a builder-produced mapping/boolean.
    definition_doc = {"schema": interface_schema, "schema_version": 1,
        "profile": profile, "interfaces": {sig: item["signature"] for sig, item in definitions.items()},
        "effect_contract": "UNKNOWN outside partial provider schema annotations", "content_version_claimed": False}
    definition_bytes = canonical(definition_doc)
    expected_provider = ProviderID(provider_prefix + next(iter(definitions.values()))["signature"]["provider_revision"]) if definitions else None
    envelope = next((e for e in program.provider_envelopes if e.id == expected_provider), None)
    check(envelope is not None and envelope.kind is ProviderArtifactKind.DEFINITION_GRAPH
          and envelope.artifact.schema == definition_doc["schema"]
          and envelope.artifact.sha256 == sha256(definition_bytes).hexdigest()
          and envelope.artifact.size_bytes == len(definition_bytes),
          "definition_artifact", "provider", "definition owner differs from independently reconstructed schema interface")
    layouts = {}
    if definition_signatures is not None:
        check(set(boundaries) == {NativeBoundaryID(region_prefix + sig + ":boundary") for sig in definitions},
              "definition_inventory", "program", "shared program boundary inventory differs from owned source catalog")
    for sig, item in definitions.items():
        path = "interface:" + sig
        region_id = RegionID(region_prefix + sig)
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
                    matches = binding_index.get((expected_provider, region_id, target), ())
                    check(len(matches) == 1 and matches[0].external.kind is kind
                          and matches[0].external.key == sig and matches[0].external.path == expected_path,
                          "provider_path_order", port_path, "provider binding path does not select this exact original ordered endpoint")
        before_world, after_world = core_values.get(entry.arguments[-1]), core_values.get(normal.arguments[-1])
        check(type(before_world) is type(after_world) is StateVersionValue and before_world.location == after_world.location,
              "world_location", path, "normal opaque world does not preserve the declared state domain")
        layouts[sig] = (region_id, boundary, entry, invoke, normal_index, normal, returned)
    return tuple(errors), layouts


def _native_port_order_errors(program, model, interfaces, run, *, definition_signatures=None,
                              profile=PROFILE, source=None, value_artifact=None, evidence_artifact=None,
                              _prepared=None):
    """Independent actual-port checking, with optional privately proved static ABI."""
    from .coordinates import InitialEntry
    need(profile in (PROFILE, PROFILE_V2), "unsupported native source profile")
    if _prepared is None:
        static_errors, layouts = _native_static_order(program, interfaces,
            definition_signatures=definition_signatures, profile=profile)
        errors = list(static_errors)
    else:
        need(profile == PROFILE_V2 and type(_prepared) is _PreparedNativeCatalog,
             "prepared native ABI must be the live V2 source-bound catalog")
        _prepared.require(program, source, definition_signatures)
        layouts, errors = _prepared._layouts, []
        for item in interfaces:
            signature = item["signature"]
            sig = sha256(canonical(signature)).hexdigest()
            if item["signature_id"] != sig or sig not in layouts or signature != definition_signatures.get(sig):
                errors.append(("signature_catalog", sig, "actual native signature differs from original prepared catalog"))

    def check(ok, code, path, message):
        if not ok:
            errors.append((code, str(path), message))
        return bool(ok)

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
    by_activation, by_visit_block, by_occurrence, by_binding, by_transfer, by_value = ({} for _ in range(6))
    for segment in model.segments:
        by_activation.setdefault(segment.activation, []).append(segment)
    for visit in model.visits:
        by_visit_block.setdefault((visit.segment, visit.block), []).append(visit)
    for occurrence in model.operations:
        by_occurrence.setdefault((occurrence.visit, occurrence.operation), []).append(occurrence)
    for binding in model.evidence_bindings:
        by_binding.setdefault(binding.operation, []).append(binding)
    for transfer in model.transfers:
        by_transfer.setdefault(transfer.operation, []).append(transfer)
    for denotation in model.denotations:
        by_value.setdefault(denotation.value, []).append(denotation)
    by_activation_name = {}
    for activation in model.activations:
        by_activation_name.setdefault(activation.id.value, []).append(activation)
    expected_activations = set()
    expected_denotations = set()
    expected_bindings = set()
    if profile == PROFILE_V2:
        need(type(source) is dict and source.get("reference_profile") == PROFILE_V2
             and source["run"] == run and type(value_artifact) is type(evidence_artifact) is ProviderArtifact,
             "V2 checker needs exact owned source and projection scope")
        target_processes = [p for p in model.processes if p.pid == source["pid"] and p.run.value == run]
        check(len(target_processes) == 1, "native_process", "model", "V2 source process is absent or ambiguous")
    for item in interfaces:
        sig = item["signature_id"]
        if sig not in layouts:
            continue
        region_id, boundary, entry, invoke, normal_index, normal, returned = layouts[sig]
        expected_id = "native-port:" + run + ":" + str(item["sequence"])
        candidates = by_activation_name.get(expected_id, ())
        if not check(len(candidates) == 1 and candidates[0].region == region_id,
                     "activation", expected_id, "source sequence has no unique exact native activation"):
            continue
        activation = candidates[0];expected_activations.add(activation.id)
        owned_segments = by_activation.get(activation.id, ())
        if not check(len(owned_segments) == 1 and type(owned_segments[0].ingress) is InitialEntry
                     and activation.entry.run.value == run,
                     "segment", expected_id, "normal native protocol activation/Run has no exact initial segment"):
            continue
        segment = owned_segments[0]
        entry_visits = by_visit_block.get((segment.id, entry.id), ())
        normal_visits = by_visit_block.get((segment.id, normal.id), ())
        if not check(len(entry_visits) == len(normal_visits) == 1,
                     "visit", expected_id, "normal native call has no unique entry/completion visits"):
            continue
        entry_visit, normal_visit = entry_visits[0], normal_visits[0]
        invoked = by_occurrence.get((entry_visit.id, invoke.id), ())
        completed = by_occurrence.get((normal_visit.id, returned.id), ())
        if not check(len(invoked) == len(completed) == 1, "occurrence", expected_id,
                     "native invocation/normal Return occurrence missing or ambiguous"):
            continue
        invoked, completed = invoked[0], completed[0]
        if profile == PROFILE_V2:
            from .model import LegacyOperationRef
            from scar.ir.record_codec import decode
            from scar.ir.program.providers import ProviderFactReference
            for occurrence, suffix in ((invoked, ""), (completed, "/outputs")):
                bindings = by_binding.get(occurrence.id, ())
                expected_bindings.add(occurrence.id)
                fact = decode(ProviderFactReference, {"artifact": source["artifacts"]["eto"],
                    "locator": "#/nodes/" + str(source["node_ordinals"][str(item["node"]["id"])]) + suffix})
                check(len(bindings) == 1 and type(bindings[0].legacy) is LegacyOperationRef
                      and bindings[0].legacy.artifact == evidence_artifact
                      and bindings[0].legacy.instance.value == source["native_scope"] + ":eto:" + str(item["node"]["id"])
                      and bindings[0].source == fact,
                      "native_producer_binding", occurrence.id.value,
                      "actual native invocation/completion lost its exact original producer/artifact/ordinal")
        transfers = by_transfer.get(invoked.id, ())
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
                if profile == PROFILE_V2:
                    from scar.ir.execution.common import Unresolved
                    from scar.ir.record_codec import decode
                    from scar.ir.program.providers import ProviderFactReference
                    candidates = by_value.get(values[0].id, ())
                    if not check(len(candidates) == 1, "actual_native_denotation", path,
                                 "each native Tensor occurrence requires exactly one denotation"):
                        continue
                    d = candidates[0]
                    expected_denotations.add(d.id)
                    expected_basis = (NativeInputRef(boundary.id, entry_visit.id, i) if direction == "inputs"
                                      else NativeOutputRef(boundary.id, completed.id, i))
                    check(type(d.basis) is type(expected_basis) and d.basis == expected_basis
                          and d.id.value == expected_id + ":" + direction + ":denotation:" + str(i),
                          "actual_native_order", path, "V2 basis/denotation ordinal differs from exact original port")
                    native = item["ports"][direction][i]
                    fact = decode(ProviderFactReference, _native_slot_fact(source, item, direction, native))
                    check(d.source == fact, "native_source", path, "denotation source differs from exact original native slot")
                    original = native.get("object_record")
                    if original is not None:
                        check(type(d.identity) is ObjectIdentity and d.identity.object.artifact == value_artifact
                              and d.identity.object.object.value == original["id"]["value"],
                              "native_object_identity", path, "known held object was replaced, erased or borrowed")
                    else:
                        ok = type(d.identity) is Unresolved
                        check(ok, "native_identity_unresolved", path, "native-only port cannot borrow an object/content identity")
                        if ok:
                            point = d.identity.point
                            check(d.identity.reason == native["identity_reason"] and point.run.value == run
                                  and len(target_processes) == 1 and point.process == target_processes[0].id
                                  and point.source == fact,
                                  "native_unresolved_source", path, "unresolved identity loses exact source/Run/process/port")
                    continue
                denotations = [d for d in model.denotations if type(d.basis) is
                    (NativeInputRef if direction == "inputs" else NativeOutputRef)
                    and d.basis.boundary == boundary.id and d.basis.position == i
                    and (d.basis.entry == entry_visit.id if direction == "inputs" else d.basis.operation == completed.id)]
                check(len(denotations) == 1 and denotations[0].value == values[0].id,
                      "actual_native_order", path, "native slot/denotation does not preserve the actual original Use value ordinal")
    check(set(activations) == expected_activations, "activation_inventory", "model",
          "native window has missing or extra canonical activations")
    if profile == PROFILE_V2:
        check(len(model.denotations) == len(expected_denotations) and {d.id for d in model.denotations} == expected_denotations,
              "native_denotation_inventory", "model", "missing, duplicate or extra V2 native Tensor denotation")
        check(len(model.evidence_bindings) == len(expected_bindings)
              and {b.operation for b in model.evidence_bindings} == expected_bindings,
              "native_producer_inventory", "model", "missing, duplicate or extra actual native producer binding")
    return tuple(errors)


def _require_native_port_order(program, model, interfaces, run, *, definition_signatures=None,
                               profile=PROFILE, source=None, value_artifact=None, evidence_artifact=None, _prepared=None):
    errors = _native_port_order_errors(program, model, interfaces, run,
                                       definition_signatures=definition_signatures, profile=profile,
                                       source=source, value_artifact=value_artifact, evidence_artifact=evidence_artifact, _prepared=_prepared)
    if errors:
        raise NativePortOrderError("native_port_order: " + "; ".join(
            code + " at " + path + ": " + message for code, path, message in errors))


class _OwnedNativeCapture:
    __slots__ = ("_payload", "_definitions")

    def __init__(self, key, source):
        need(key is _OWNER, "native evidence can only originate in its owning reader")
        detached = dict(source)
        definitions = detached.pop("definition_signatures", None)
        self._definitions = None if definitions is None else canonical(definitions)
        self._payload = canonical(detached)

    def source(self):
        return json.loads(self._payload)

    def definitions(self):
        return None if self._definitions is None else json.loads(self._definitions)


def _own_capture(source):
    return _OwnedNativeCapture(_OWNER, source)


def _static_source_identity(source):
    return canonical({key: source.get(key) for key in (
        "reference_profile", "pid", "nonce", "provider_revision", "run", "coordinate_artifact",
        "owner_native_tid", "owner_python_ident", "native_scope", "physical_scope", "physical_profile",
        "artifacts", "source_manifest")})


@dataclass(frozen=True, slots=True, init=False)
class _PreparedNativeCatalog:
    _key: object
    _snapshot: object
    _source_identity: bytes
    _definitions: bytes
    _layouts: object

    def __init__(self, key, owned, program, snapshot):
        from .validation import PreparedProgramSnapshot
        need(key is _OWNER and type(owned) is _OwnedNativeCapture
             and type(snapshot) is PreparedProgramSnapshot, "prepared catalog needs actual owned source and static proof")
        snapshot.canonical_bytes(program)
        source, definitions = owned.source(), owned.definitions()
        need(source.get("reference_profile") == PROFILE_V2 and type(definitions) is dict,
             "prepared catalog needs the complete V2 original definition inventory")
        interfaces = replay_batch_interfaces(source)[0]
        errors, layouts = _native_static_order(program, interfaces, definition_signatures=definitions, profile=PROFILE_V2)
        if errors:
            raise NativePortOrderError("native_port_order: " + "; ".join(code + " at " + path + ": " + message for code, path, message in errors))
        object.__setattr__(self, '_key', key)
        object.__setattr__(self, '_snapshot', snapshot)
        object.__setattr__(self, '_source_identity', _static_source_identity(source))
        object.__setattr__(self, '_definitions', canonical(definitions))
        object.__setattr__(self, '_layouts', MappingProxyType(layouts))

    def require(self, program, source, definitions):
        need(type(self) is _PreparedNativeCatalog and self._key is _OWNER,
             "prepared native catalog is not a live owned capability")
        self._snapshot.canonical_bytes(program)
        need(self._source_identity == _static_source_identity(source) and self._definitions == canonical(definitions),
             "prepared native catalog belongs to another source/Run/namespace/definition inventory")


def _prepare_native_catalog(owned, program, snapshot):
    return _PreparedNativeCatalog(_OWNER, owned, program, snapshot)


class NativePortEvidence:
    """Immutable source-owned port resolver, sealed to one exact native window.

    This grants reference/port correspondence only. It does not interpret
    logical contents, hidden effects, alias completeness, CUDA order or ready.
    """
    __slots__ = ("_owned", "_program_sha", "_model_sha", "_value_artifact", "_evidence_artifact",
                 "_interfaces", "_source", "_lookup", "_definitions", "_profile", "_prepared",
                 "_invoke_index", "_binding_index")

    def __init__(self, key, owned, program, model, value_artifact, evidence_artifact, *, _prepared=None):
        need(key is _OWNER and type(owned) is _OwnedNativeCapture, "owned source session is required")
        from scar.ir.program.codec import dumps as program_dumps
        from .codec import dumps
        self._owned = owned
        self._model_sha = sha256(dumps(model).encode()).hexdigest()
        need(type(value_artifact) is type(evidence_artifact) is ProviderArtifact, "projection artifacts are required")
        self._value_artifact, self._evidence_artifact = value_artifact, evidence_artifact
        self._source = owned.source()
        self._profile = self._source.get("reference_profile", PROFILE)
        need(self._profile in (PROFILE, PROFILE_V2), "unsupported owned native profile")
        interfaces = (replay_batch_interfaces(self._source) if self._profile == PROFILE_V2 else replay_interfaces(self._source))[0]
        self._interfaces = canonical(interfaces)
        self._lookup = {"native-port:" + self._source["run"] + ":" + str(i["sequence"]): i for i in interfaces}
        self._definitions = owned.definitions()
        self._prepared = None
        if _prepared is not None:
            need(type(_prepared) is _PreparedNativeCatalog and self._profile == PROFILE_V2,
                 "only a source-bound V2 prepared catalog can reuse static proof")
            # A fresh changed program still receives full independent ABI checks.
            # The old token cannot turn that constructor into a scope-hash refusal.
            if program is _prepared._snapshot._program:
                _prepared.require(program, self._source, self._definitions)
                self._prepared = _prepared
        self._program_sha = (self._prepared._snapshot.sha256 if self._prepared is not None else
                             sha256(program_dumps(program).encode()).hexdigest())
        self._invoke_index, self._binding_index = {}, {}
        if self._prepared is not None:
            from scar.ir.program.model import TerminatorKind
            visits = {v.id: v for v in model.visits}
            segments = {s.id: s for s in model.segments}
            operations = {o.id: o for o in program.operations}
            for occurrence in model.operations:
                original = operations.get(occurrence.operation)
                visit = visits.get(occurrence.visit)
                segment = None if visit is None else segments.get(visit.segment)
                if (original is not None and original.terminator is not None
                        and original.terminator.kind is TerminatorKind.INVOKE and segment is not None):
                    self._invoke_index.setdefault(segment.activation, []).append(occurrence)
            for binding in model.evidence_bindings:
                self._binding_index.setdefault(binding.operation, []).append(binding)
        _require_native_port_order(program, model, interfaces, self._source["run"],
                                   definition_signatures=self._definitions, profile=self._profile,
                                   source=self._source, value_artifact=self._value_artifact, evidence_artifact=self._evidence_artifact,
                                   _prepared=self._prepared)

    def require_scope(self, model, program):
        from scar.ir.program.codec import dumps as program_dumps
        from .codec import dumps
        if self._prepared is None:
            program_sha = sha256(program_dumps(program).encode()).hexdigest()
        else:
            self._prepared._snapshot.canonical_bytes(program)
            program_sha = self._prepared._snapshot.sha256
        need(self._program_sha == program_sha
             and self._model_sha == sha256(dumps(model).encode()).hexdigest(),
             "owned native port evidence does not apply to this exact program/execution/Run")
        _require_native_port_order(program, model, json.loads(self._interfaces), self._source["run"],
                                   definition_signatures=self._definitions, profile=self._profile,
                                   source=self._source, value_artifact=self._value_artifact, evidence_artifact=self._evidence_artifact,
                                   _prepared=self._prepared)

    def resolve(self, ctx, basis, resolved, identity, path):
        """Replay original ordered ports independently of builder declarations."""
        if resolved is None or resolved["value"] is None:
            return False
        # Scope checked once by normal _analyze. NativeInput/Output select the
        # canonical current visit/completion independently in content_validation.
        activation = (ctx.activations[ctx.segments[ctx.visits[basis.entry].segment].activation]
                      if type(basis) is NativeInputRef else ctx.activations[ctx.activation_of(basis.operation)])
        source = self._source
        interface = self._lookup.get(activation.id.value)
        if interface is None:
            ctx.issue("native_reference_activation", path, "activation has no exact owned native sequence"); return False
        direction = "inputs" if type(basis) is NativeInputRef else "outputs"
        boundary = resolved["boundary"]
        expected_boundary = ("torch-interface:" if self._profile == PROFILE_V2 else "aten-interface:") + interface["signature_id"] + ":boundary"
        if boundary.id.value != expected_boundary or basis.position >= len(interface["ports"][direction]):
            ctx.issue("native_reference_slot", path, "canonical boundary/ordered slot differs from actual native schema"); return False
        native = interface["ports"][direction][basis.position]
        if self._profile == PROFILE_V2 and native.get("geometry", {}).get("status") != "QUALIFIED":
            ctx.gap("native_port_geometry_unproved", path, native.get("geometry", {}).get("reason", "geometry unavailable"))
        if type(identity) is not ObjectIdentity:
            return False
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
        if self._prepared is None:
            occurrences = [o for o in ctx.model.operations if ctx.activation_of(o.id) == activation.id
                           and ctx.core_operations[o.operation].terminator.kind.value == "INVOKE"]
            bindings = [b for b in ctx.model.evidence_bindings if len(occurrences) == 1 and b.operation == occurrences[0].id]
        else:
            occurrences = self._invoke_index.get(activation.id, ())
            bindings = self._binding_index.get(occurrences[0].id, ()) if len(occurrences) == 1 else ()
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


def _make_evidence(owned, program, model, value_artifact, evidence_artifact, *, _prepared=None):
    return NativePortEvidence(_OWNER, owned, program, model, value_artifact, evidence_artifact, _prepared=_prepared)


__all__ = ["NativePortEvidence", "PROFILE", "PROFILE_V2"]
