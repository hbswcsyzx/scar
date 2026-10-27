"""Receipt-bound geometry joins for original native input/output ports.

This reads the retained ETO port-qualification table, then joins its exact
source locator to an already resolved native port. It does not read ETO tensor
contents, create logical values, or treat ETO pointer tokens as allocation IDs.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from math import prod
from pathlib import Path
import re
import time

from scar.analysis.native_completion import NativeCompletionPort, NativeNormalCompletion
from scar.ir.execution.content import NativeInputRef, NativeOutputRef
from scar.ir.execution.coordinates import ValueOccurrence
from scar.ir.execution.model import ExecutionModel
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.provenance import _WIDTHS
from scar.ir.record_codec import decode, encode
from scar.ir.v2._validation import record_errors
from scar.ir.v2.ids import StorageRegionID
from scar.ir.v2.values import StorageAllocation, StorageRegion
from scar.trace.native_import import _canonical_hash
from scar.trace.native_tensor_inputs import _json as _strict_json


_QUALIFICATION_SCHEMA = "scar.native-capture-table-chunks"
_QUALIFICATION_PROFILE = "PINNED_TORCH_NATIVE_PORT_HELD_SUBSET_V2"
_CHUNK_SCHEMA = "scar.native-capture-row-chunk"


def _need(value: bool, message: str) -> None:
    if not value:
        raise ValueError("native port geometry: " + message)


def _stamp(path: Path):
    row = path.stat()
    return row.st_dev, row.st_ino, row.st_size, row.st_mtime_ns, row.st_ctime_ns


def _read_artifact(artifact: ProviderArtifact, *, maximum: int, meter: dict,
                   stamps: list) -> bytes:
    _need(type(artifact) is ProviderArtifact, "typed artifact receipt required")
    artifact.__post_init__()
    path = Path(artifact.uri)
    _need(path.is_absolute() and path.resolve(strict=True) == path and not path.is_symlink(),
          "artifact URI must be an existing stable regular path")
    before = _stamp(path)
    _need(0 < before[2] == artifact.size_bytes <= maximum, "artifact size exceeds receipt/budget")
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    _need(len(raw) == artifact.size_bytes and sha256(raw).hexdigest() == artifact.sha256,
          "artifact stored receipt differs")
    _need(_stamp(path) == before, "artifact changed while being read")
    meter["stored_bytes"] += len(raw)
    stamps.append((path, before))
    return raw


def _source_artifact(row: dict) -> ProviderArtifact:
    _need(type(row) is dict and set(row) == {"artifact", "locator"},
          "port row source fields differ")
    return decode(ProviderArtifact, row["artifact"])


@dataclass(frozen=True, slots=True)
class NativeTensorPortGeometry:
    """Exact geometry from one original qualified ETO Tensor leaf."""

    reference: NativeInputRef | NativeOutputRef
    source: ProviderFactReference
    qualification_source: ProviderFactReference
    direction: str
    native_path: tuple[int, ...]
    native_type: str
    tensor_id: int
    storage_id: int
    storage_offset: int
    numel: int
    itemsize: int
    device: str
    shape: tuple[int, ...]
    strides: tuple[int, ...]

    def __post_init__(self) -> None:
        if type(self.reference) not in (NativeInputRef, NativeOutputRef):
            raise TypeError("geometry must reuse an original NativeInputRef/NativeOutputRef")
        self.reference.__post_init__()
        for name in ("source", "qualification_source"):
            value = getattr(self, name)
            if type(value) is not ProviderFactReference:
                raise TypeError(name + " must preserve its original ProviderFactReference")
            value.__post_init__()
        expected = "inputs" if type(self.reference) is NativeInputRef else "outputs"
        if self.direction != expected:
            raise ValueError("direction differs from original native port reference")
        if (type(self.native_path) is not tuple or not self.native_path
                or any(type(i) is not int or i < 0 for i in self.native_path)):
            raise ValueError("native path must be an ordered nonempty integer tuple")
        if type(self.native_type) is not str or not self.native_type.startswith("Tensor(") or not self.native_type.endswith(")"):
            raise ValueError("qualified native type is not a Tensor type")
        for name in ("tensor_id", "storage_id", "storage_offset", "numel", "itemsize"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise ValueError(name + " must be an exact nonnegative integer")
        if type(self.device) is not str:
            raise TypeError("device must preserve the ETO device string")
        if (type(self.shape) is not tuple or type(self.strides) is not tuple
                or len(self.shape) != len(self.strides)
                or any(type(i) is not int or i < 0 for i in self.shape)
                or any(type(i) is not int for i in self.strides)):
            raise ValueError("shape/stride geometry is malformed")
        no_storage_sentinel = (self.storage_id == 0 and self.numel == 0 and self.itemsize == 0
                               and self.device == "" and self.shape == () and self.strides == ())
        if self.itemsize == 0 and not no_storage_sentinel:
            raise ValueError("zero itemsize is only valid for the original no-storage metadata sentinel")
        if self.itemsize > 0 and prod(self.shape) != self.numel:
            raise ValueError("qualified numel contradicts shape")

    @property
    def has_storage(self) -> bool:
        return self.storage_id != 0 and self.itemsize > 0 and bool(self.device)


@dataclass(frozen=True, slots=True)
class NativePortGeometryRead:
    """Selected geometry plus explicit source ports with no Tensor row."""

    qualification_manifest: ProviderArtifact
    program_snapshot: ProviderArtifact
    eto_source: ProviderArtifact
    geometries: tuple[NativeTensorPortGeometry, ...]
    without_tensor_geometry: tuple[tuple[NativeInputRef | NativeOutputRef, ProviderFactReference | None], ...]
    measurements: dict

    def __post_init__(self) -> None:
        for name in ("qualification_manifest", "program_snapshot", "eto_source"):
            value = getattr(self, name)
            if type(value) is not ProviderArtifact:
                raise TypeError(name + " must be a retained ProviderArtifact")
            value.__post_init__()
        if type(self.geometries) is not tuple or any(type(r) is not NativeTensorPortGeometry for r in self.geometries):
            raise TypeError("geometries must be original typed Tensor port rows")
        if type(self.without_tensor_geometry) is not tuple:
            raise TypeError("missing geometry ports must remain an ordered tuple")


def _port_source(port: NativeCompletionPort) -> ProviderFactReference | None:
    _need(type(port) is NativeCompletionPort, "selected original native completion port required")
    if port.denotation is None:
        return None
    source = port.denotation.source
    _need(type(source) is ProviderFactReference and source.artifact.schema == "pytorch.execution-trace.v1",
          "selected port lacks an exact ETO SourceFact")
    return source


def _check_original_completion(completion: NativeNormalCompletion,
                               execution: ExecutionModel) -> None:
    _need(completion.invocation in execution.operations
          and completion.normal_return in execution.operations
          and completion.normal_transfer in execution.transfers,
          "normal completion endpoints are not exact records in the supplied ExecutionModel")
    _need(completion.invocation_evidence in execution.evidence_bindings
          and completion.completion_evidence in execution.evidence_bindings
          and completion.invocation_evidence.legacy == completion.completion_evidence.legacy
          and type(completion.completion_evidence.source) is ProviderFactReference
          and completion.invocation_evidence.source.artifact == completion.completion_evidence.source.artifact,
          "invoke/return evidence does not resolve to the same retained native instance")
    _need(type(completion.invocation_evidence.source) is ProviderFactReference,
          "invoke lacks the exact original ETO source fact")
    entry = completion.invocation_evidence.source.locator.rstrip("/")
    returned = completion.completion_evidence.source.locator.rstrip("/")
    for port in completion.input_ports + completion.output_ports:
        _need(port.reference.boundary == completion.boundary,
              "native port belongs to a different original boundary")
        if type(port.reference) is NativeInputRef:
            _need(port.reference.entry == completion.invocation.visit
                  and port.use.operation == completion.invocation.id,
                  "input port is not attached to the original invoke occurrence")
        else:
            _need(port.reference.operation == completion.normal_return.id
                  and port.use.operation == completion.normal_return.id,
                  "output port is not attached to the original normal return")
        _need(port.use in execution.uses, "port UseOccurrence is not an exact original record")
        if type(port.value) is not ValueOccurrence:
            _need(port.denotation is None, "unresolved port unexpectedly has an original denotation")
            continue
        _need(port.value in execution.values and port.use.value == port.value.id,
              "port ValueOccurrence is not an exact original record")
        if port.denotation is None:
            continue
        _need(port.denotation in execution.denotations
              and port.denotation.basis == port.reference
              and port.denotation.value == port.value.id,
              "port denotation is not an exact original ExecutionModel record")
        source = port.denotation.source
        _need(type(source) is ProviderFactReference
              and source.artifact == completion.invocation_evidence.source.artifact,
              "port denotation is outside the invocation ETO artifact")
        base = entry + "/inputs/" if type(port.reference) is NativeInputRef else returned + "/"
        _need(source.locator.startswith(base),
              "port denotation source is outside its original ETO boundary subtree")


def _pointer_path(locator: str, direction: str) -> tuple[int, ...]:
    match = re.fullmatch(r"#/nodes/(?:0|[1-9][0-9]*)/" + direction + r"/values((?:/(?:0|[1-9][0-9]*))+)" , locator)
    _need(match is not None, "ETO source locator is not a boxed Tensor value path")
    return tuple(int(part) for part in match.group(1).split("/")[1:])


def _geometry_row(row: dict, port: NativeCompletionPort, qualification_source: ProviderFactReference) -> NativeTensorPortGeometry:
    reference = port.reference
    direction = "inputs" if type(reference) is NativeInputRef else "outputs"
    source = _port_source(port)
    _need(type(row) is dict, "port qualification row must be an object")
    required = {"A", "B", "C", "D", "denotation", "direction", "native_path", "native_shape",
                "native_strides", "native_tensor_tuple", "native_type", "position", "sequence", "source"}
    _need(set(row) == required, "port qualification row fields differ")
    _need(row["A"] == "QUALIFIED_NATIVE_PORT" and row["direction"] == direction,
          "port qualification is for a different role/direction")
    _need(row["source"]["artifact"] == encode(source.artifact)
          and row["source"]["locator"] == source.locator,
          "port qualification does not name the exact original ETO locator")
    path = tuple(row["native_path"])
    _need(path == _pointer_path(source.locator, direction),
          "qualification path differs from the original ETO locator")
    _need(row["denotation"] == encode(port.denotation),
          "qualification row denotation differs from canonical port denotation")
    tensor = row["native_tensor_tuple"]
    _need(type(tensor) is list and len(tensor) == 6, "ETO Tensor tuple does not have six fields")
    _need(type(row["native_shape"]) is list and type(row["native_strides"]) is list,
          "ETO shape/strides are not arrays")
    _need(type(row["native_type"]) is str, "ETO Tensor type is absent")
    _need(type(tensor[0]) is int and type(tensor[1]) is int
          and type(tensor[2]) is int and type(tensor[3]) is int and type(tensor[4]) is int
          and type(tensor[5]) is str, "ETO Tensor tuple field types differ")
    return NativeTensorPortGeometry(
        reference, source, qualification_source, direction, path, row["native_type"],
        tensor[0], tensor[1], tensor[2], tensor[3], tensor[4], tensor[5],
        tuple(row["native_shape"]), tuple(row["native_strides"]))


def query_native_port_geometries(
    completion: NativeNormalCompletion,
    execution: ExecutionModel,
    qualification_manifest: ProviderArtifact,
    *,
    max_input_bytes: int = 32_000_000,
    max_seconds: int = 60,
) -> NativePortGeometryRead:
    """Read original geometry rows bound to one already qualified completion.

    The caller supplies the exact port-qualification manifest receipt belonging
    to the source shard. Only this bounded sidecar is read; ETO is not reopened.
    """
    _need(type(completion) is NativeNormalCompletion and type(execution) is ExecutionModel,
          "normal completion and original ExecutionModel required")
    _need(type(qualification_manifest) is ProviderArtifact
          and qualification_manifest.schema == _QUALIFICATION_SCHEMA,
          "original port-qualification manifest receipt required")
    _need(type(max_input_bytes) is int and max_input_bytes > 0
          and type(max_seconds) is int and max_seconds > 0, "positive bounded reader budget required")
    started = time.monotonic()
    meter = {"stored_bytes": 0, "decoded_bytes": 0}
    stamps = []
    raw = _read_artifact(qualification_manifest, maximum=min(max_input_bytes, 16_000_000),
                         meter=meter, stamps=stamps)
    meter["decoded_bytes"] += len(raw)
    manifest = _strict_json(raw)
    _need(type(manifest) is dict and manifest.get("schema") == _QUALIFICATION_SCHEMA
          and type(manifest.get("schema_version")) is int and manifest["schema_version"] == 1
          and manifest.get("role") == "native-port-qualifications"
          and type(manifest.get("row_schema_version")) is int and manifest["row_schema_version"] == 2
          and manifest.get("profile") == _QUALIFICATION_PROFILE,
          "unsupported port-qualification manifest profile/version")
    snapshot = decode(ProviderArtifact, manifest["program_snapshot"]["artifact"])
    _need(snapshot == execution.snapshot.artifact
          and manifest["program_snapshot"]["schema_version"] == execution.snapshot.schema_version,
          "qualification manifest belongs to a different program snapshot")
    _check_original_completion(completion, execution)
    all_ports = completion.input_ports + completion.output_ports
    sources = tuple(_port_source(port) for port in all_ports)
    eto_sources = {source.artifact for source in sources if source is not None}
    _need(len(eto_sources) == 1, "completion ports refer to multiple ETO artifacts")
    eto_source = next(iter(eto_sources))
    _need(all(source is None or source.artifact == eto_source for source in sources),
          "completion port denotations do not share one ETO namespace")
    expected: dict[tuple[str, str], NativeCompletionPort] = {}
    for port, source in zip(all_ports, sources):
        if source is None:
            continue
        key = (source.artifact.sha256, source.locator)
        _need(key not in expected, "canonical completion repeats an ETO port locator")
        expected[key] = port

    root = Path(qualification_manifest.uri).parent.resolve(strict=True)
    chunks = manifest.get("chunks")
    _need(type(chunks) is list, "qualification chunks must be an array")
    total_rows = 0
    geometries: dict[tuple[str, str], NativeTensorPortGeometry] = {}
    source_refs: dict[tuple[str, str], ProviderFactReference] = {}
    expected_ordinal = 0
    expected_chunk_bytes = manifest.get("max_chunk_bytes")
    _need(type(expected_chunk_bytes) is int and 0 < expected_chunk_bytes <= 8_000_000,
          "qualification chunk size ceiling differs")
    for chunk in chunks:
        _need(time.monotonic() - started <= max_seconds, "reader time budget exceeded")
        _need(type(chunk) is dict and set(chunk) == {"artifact", "first_row_ordinal", "first_sequence", "last_row_ordinal", "last_sequence", "rows"},
              "qualification chunk descriptor fields differ")
        artifact = decode(ProviderArtifact, chunk["artifact"])
        _need(artifact.schema == _CHUNK_SCHEMA and artifact.size_bytes <= expected_chunk_bytes,
              "qualification row chunk schema/size differs")
        relative = Path(artifact.uri)
        _need(relative.is_absolute() and relative.resolve(strict=True).is_relative_to(root),
              "qualification chunk escapes its manifest directory")
        before = _stamp(relative)
        _need(not relative.is_symlink() and before[2] == artifact.size_bytes,
              "qualification chunk is not the exact regular file")
        maximum = min(expected_chunk_bytes, max_input_bytes - meter["stored_bytes"] - meter["decoded_bytes"])
        _need(maximum > 0, "combined reader byte budget exhausted")
        stored = _read_artifact(artifact, maximum=maximum, meter=meter, stamps=stamps)
        meter["decoded_bytes"] += len(stored)
        _need(len(stored) <= expected_chunk_bytes, "qualification chunk exceeds declared ceiling")
        lines = stored.splitlines()
        _need(len(lines) == chunk["rows"] and len(lines) > 0, "qualification chunk row count differs")
        _need(type(chunk["first_row_ordinal"]) is int and chunk["first_row_ordinal"] == expected_ordinal,
              "qualification chunk ordinals are not contiguous")
        _need(type(chunk["last_row_ordinal"]) is int
              and chunk["last_row_ordinal"] == chunk["first_row_ordinal"] + len(lines) - 1,
              "qualification chunk final row ordinal differs")
        first_seq = last_seq = None
        for line_no, line in enumerate(lines, 1):
            if not line:
                raise ValueError("native port geometry: empty JSONL row")
            row = _strict_json(line)
            _need(type(row) is dict and type(row.get("sequence")) is int,
                  "qualification row has no exact sequence")
            first_seq = row["sequence"] if first_seq is None else first_seq
            last_seq = row["sequence"]
            src = row.get("source")
            _need(type(src) is dict and type(src.get("artifact")) is dict and type(src.get("locator")) is str,
                  "qualification row has no original ETO source locator")
            row_key = (src["artifact"].get("sha256"), src["locator"])
            port = expected.get(row_key)
            if port is not None:
                _need(src["artifact"] == encode(eto_source),
                      "qualification row source artifact differs from canonical ETO source")
                _need(row_key not in geometries, "duplicate qualified row for one original port")
                fact = ProviderFactReference(artifact, f"#/lines/{line_no}")
                geometries[row_key] = _geometry_row(row, port, fact)
                source_refs[row_key] = fact
        _need(first_seq == chunk["first_sequence"] and last_seq == chunk["last_sequence"],
              "qualification chunk sequence bounds differ")
        expected_ordinal += len(lines)
        total_rows += len(lines)
    _need(total_rows == manifest["rows"], "qualification manifest total row count differs")
    _need(meter["stored_bytes"] + meter["decoded_bytes"] <= max_input_bytes,
          "combined reader byte budget exceeded")
    for path, stamp in stamps:
        _need(_stamp(path) == stamp, "input artifact changed during normal query")
    missing = tuple((port.reference, source) for port, source in zip(all_ports, sources)
                    if source is None or (source.artifact.sha256, source.locator) not in geometries)
    return NativePortGeometryRead(
        qualification_manifest, snapshot, eto_source,
        tuple(geometries.values()), missing,
        {"stored_bytes": meter["stored_bytes"], "decoded_bytes": meter["decoded_bytes"],
         "total_bytes": meter["stored_bytes"] + meter["decoded_bytes"],
         "elapsed_seconds": time.monotonic() - started,
         "qualification_rows_verified": total_rows, "source_raw_eto_read": False})


@dataclass(frozen=True, slots=True)
class NativeObservedInputRegion:
    """A StorageRegion projected from exact input geometry and epoch evidence."""

    geometry: NativeTensorPortGeometry
    allocation: StorageAllocation
    allocation_source: ProviderFactReference
    provider_epoch_source: ProviderFactReference
    region: StorageRegion

    def __post_init__(self) -> None:
        if type(self.geometry) is not NativeTensorPortGeometry or self.geometry.direction != "inputs":
            raise TypeError("observed region requires an original input Tensor geometry")
        if type(self.allocation) is not StorageAllocation:
            raise TypeError("allocation must be the original typed StorageAllocation")
        for name in ("allocation_source", "provider_epoch_source"):
            value = getattr(self, name)
            if type(value) is not ProviderFactReference:
                raise TypeError(name + " must reference the original allocation evidence")
            value.__post_init__()
        if type(self.region) is not StorageRegion or self.region.allocation != self.allocation.id:
            raise ValueError("projected region must use the exact original allocation ID")


def connect_observed_input_region(
    geometry: NativeTensorPortGeometry,
    allocation_query: dict,
    execution_artifact: ProviderArtifact,
) -> NativeObservedInputRegion:
    """Join one exact ETO input leaf to its independently queried allocation.

    The caller must run the existing `query_native_input_allocation` with this
    geometry's exact `NativeInputRef` and pass that query's ExecutionModel
    receipt. This function checks the returned source
    locator, row/path, provider epoch, dtype/device/shape, and byte bounds before
    projecting the existing `StorageRegion` type. The output is derived; its
    component observations remain separately referenced.
    """
    _need(type(geometry) is NativeTensorPortGeometry and geometry.direction == "inputs"
          and type(geometry.reference) is NativeInputRef, "exact original native input geometry required")
    _need(type(allocation_query) is dict
          and allocation_query.get("schema") == "scar.native-input-allocation-query"
          and allocation_query.get("qualification") == "RETAINED_EXACT_NATIVE_INPUT_PROVIDER_EPOCH_ALLOCATION",
          "normal native input allocation query result required")
    _need(type(execution_artifact) is ProviderArtifact
          and execution_artifact.schema == "scar.execution-model",
          "exact original ExecutionModel artifact receipt required")
    execution_artifact.__post_init__()
    _need(allocation_query.get("native_input") == encode(geometry.reference)
          and allocation_query.get("original_input") == encode(geometry.source),
          "allocation query does not resolve the same NativeInputRef/ETO source locator")
    parent = allocation_query.get("canonical_parent")
    producer_source = allocation_query.get("native_operation", {}).get("producer", {}).get("source")
    _need(type(parent) is dict and parent.get("execution") == encode(execution_artifact),
          "allocation query was built from a different original ExecutionModel")
    _need(type(producer_source) is dict
          and producer_source.get("artifact") == encode(geometry.source.artifact)
          and type(producer_source.get("locator")) is str
          and geometry.source.locator.startswith(producer_source["locator"].rstrip("/") + "/inputs/values/"),
          "allocation query native producer does not name the same ETO node subtree")
    _need(allocation_query.get("selector", {}).get("path") == list(geometry.native_path),
          "allocation query path differs from the exact ETO Tensor leaf")
    _need(allocation_query.get("provider_epoch", {}).get("status") == "OBSERVED_PROVIDER_EPOCH_REFERENCE",
          "original native input has no observed provider epoch")
    observed = allocation_query.get("observed_metadata")
    _need(type(observed) is dict and observed.get("status") == "OBSERVED"
          and not observed.get("gaps"), "native input geometry/provider metadata has open gaps")
    _need(observed.get("sizes") == list(geometry.shape)
          and observed.get("strides") == list(geometry.strides)
          and observed.get("device", {}).get("text") == geometry.device,
          "ETO geometry differs from same-port profiler input metadata")
    _need(observed.get("layout") == "torch.strided" and geometry.has_storage,
          "port is not a stored strided Tensor")
    etotype = geometry.native_type[len("Tensor("):-1]
    eto_width = _WIDTHS.get(etotype)
    metadata_dtype = observed.get("dtype")
    metadata_width = (_WIDTHS.get(metadata_dtype.removeprefix("torch."))
                      if type(metadata_dtype) is str else None)
    _need(eto_width is not None and eto_width == geometry.itemsize == metadata_width,
          "ETO itemsize and same-port profiler dtype differ")
    allocation = decode(StorageAllocation, allocation_query["allocation"])
    allocation_source = decode(ProviderFactReference, allocation_query["allocation_source"])
    epoch_source = decode(ProviderFactReference, allocation_query["provider_epoch"]["source"])
    _need(allocation.id.wire == allocation_query["allocation_target"]["allocation"]["wire"]
          and allocation.device == geometry.device
          and allocation.nbytes == allocation_query["allocation"]["nbytes"]
          and allocation.metadata.get("address") == observed.get("storage_data_ptr"),
          "typed original allocation/address does not match same-port provider metadata")
    _need(type(allocation.nbytes) is int and allocation.nbytes >= 0,
          "allocation byte extent is unknown")
    width = geometry.itemsize
    if geometry.numel == 0:
        _need(geometry.storage_offset * width <= allocation.nbytes,
              "empty Tensor storage offset is outside allocation extent")
    else:
        minimum = geometry.storage_offset + sum(
            min(0, (size - 1) * stride)
            for size, stride in zip(geometry.shape, geometry.strides))
        maximum = geometry.storage_offset + sum(
            max(0, (size - 1) * stride)
            for size, stride in zip(geometry.shape, geometry.strides))
        _need(minimum >= 0 and (maximum + 1) * width <= allocation.nbytes,
              "observed ETO Tensor address range exceeds original allocation extent")
    identity_scope = {
        "native_input": encode(geometry.reference),
        "eto_source": encode(geometry.source),
        "qualification_row": encode(geometry.qualification_source),
        "allocation": encode(allocation.id),
        "allocation_source": encode(allocation_source),
        "region_basis": "EXACT_NATIVE_INPUT_ETO_GEOMETRY_JOINED_TO_PROVIDER_EPOCH_V1",
    }
    region = StorageRegion(
        StorageRegionID("native-input-observed-region:" + _canonical_hash(identity_scope)),
        allocation.id, geometry.storage_offset, geometry.shape, geometry.strides,
        metadata_dtype, geometry.device,
        metadata={"basis": "DERIVED_FROM_EXACT_ETO_INPUT_PORT_AND_PROVIDER_ALLOCATION",
                  "native_port_source": encode(geometry.source),
                  "qualification_source": encode(geometry.qualification_source),
                  "provider_epoch_source": encode(epoch_source),
                  "observed_storage_offset": geometry.storage_offset,
                  "eto_storage_id_is_not_allocation_id": True,
                  "contents_or_readiness_established": False})
    _need(not record_errors(region, StorageRegion, "observed native input StorageRegion"),
          "constructed region fails existing StorageRegion validation")
    return NativeObservedInputRegion(geometry, allocation, allocation_source, epoch_source, region)


__all__ = [
    "NativeTensorPortGeometry", "NativePortGeometryRead", "query_native_port_geometries",
    "NativeObservedInputRegion", "connect_observed_input_region",
]
