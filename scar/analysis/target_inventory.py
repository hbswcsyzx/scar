"""Read-only Linux/NVIDIA target inventory, independent of execution traces.

Only capacity and advertised topology are collected. Bandwidth and latency
are unmeasured; GPU memory technology is unspecified. Sources retain the exact
command output or explicitly selected static file lines, with SHA-256 digests.
No workload imports, user-file contents, utilization, or process state are read.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys


_TIMEOUT_SECONDS = 5
_FILE_BYTES = 2_000_000
_UNMEASURED = {"bandwidth_bytes_per_second": None, "latency_seconds": None}


class _Sources:
    def __init__(self):
        self.rows: list[dict] = []
        self.diagnostics: list[dict] = []

    def add(self, kind: str, text: str | None, **fields) -> str:
        source_id = "source:" + str(len(self.rows))
        row = {"id": source_id, "kind": kind, **fields, "text": text,
               "sha256": None if text is None else hashlib.sha256(text.encode("utf-8")).hexdigest()}
        self.rows.append(row)
        if row["status"] != "observed":
            self.diagnostics.append({"code": "source_unavailable", "source_id": source_id,
                                     "status": row["status"]})
        return source_id

    def file(self, path: str, selected_fields: tuple[str, ...] = ()) -> tuple[str | None, str]:
        try:
            with open(path, "rb") as stream:
                raw = stream.read(_FILE_BYTES + 1)
            if len(raw) > _FILE_BYTES:
                return None, self.add("file", None, path=path, status="too_large")
            text = raw.decode("utf-8")
            if selected_fields:
                # Keep paragraph boundaries for /proc/cpuinfo processor records.
                text = "".join(line for line in text.splitlines(keepends=True)
                               if not line.strip() or line.split(":", 1)[0].strip() in selected_fields
                               or any(re.fullmatch(r"Node \d+ " + re.escape(field),
                                                   line.split(":", 1)[0].strip())
                                      for field in selected_fields))
            source_id = self.add("file", text, path=path, status="observed",
                                 representation="selected_lines" if selected_fields else "utf8",
                                 selected_fields=list(selected_fields))
            return text, source_id
        except (OSError, UnicodeError) as error:
            return None, self.add("file", None, path=path, status="unavailable",
                                  error_type=type(error).__name__)

    def command(self, argv: list[str]) -> tuple[str | None, str]:
        try:
            result = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                                    errors="replace", timeout=_TIMEOUT_SECONDS, check=False,
                                    env={**os.environ, "LC_ALL": "C"})
            source_id = self.add("command", result.stdout, argv=argv,
                                 status="observed" if result.returncode == 0 else "failed",
                                 returncode=result.returncode, stderr=result.stderr)
            return (result.stdout if result.returncode == 0 else None), source_id
        except (OSError, subprocess.TimeoutExpired) as error:
            return None, self.add("command", None, argv=argv, status="unavailable",
                                  error_type=type(error).__name__)

    def malformed(self, source_id: str, detail: str) -> None:
        self.diagnostics.append({"code": "source_parse_error", "source_id": source_id,
                                 "detail": detail})


def _integer(value) -> int | None:
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _cpu_list(text: str | None) -> list[int] | None:
    if text is None:
        return None
    cpus: set[int] = set()
    for part in text.strip().split(","):
        if not re.fullmatch(r"\d+(?:-\d+)?", part):
            return None
        limits = [int(value) for value in part.split("-")]
        if limits[-1] < limits[0] or limits[-1] > 1_000_000:
            return None
        cpus.update(range(limits[0], limits[-1] + 1))
    return sorted(cpus)


def _memory_total(text: str | None) -> int | None:
    if text is None:
        return None
    match = re.search(r"^(?:Node \d+ )?MemTotal:\s*(\d+)\s+kB\s*$", text, re.MULTILINE)
    return int(match[1]) * 1024 if match else None


def _cpu_and_dram(sources: _Sources) -> tuple[dict, dict]:
    online_text, online_source = sources.file("/sys/devices/system/cpu/online")
    online = _cpu_list(online_text)
    cpuinfo, cpu_source = sources.file("/proc/cpuinfo", ("processor", "model name", "physical id", "core id"))
    processors = []
    model_names: set[str] = set()
    for paragraph in (cpuinfo or "").strip().split("\n\n"):
        fields = dict(line.split(":", 1) for line in paragraph.splitlines() if ":" in line)
        fields = {key.strip(): value.strip() for key, value in fields.items()}
        cpu_id = _integer(fields.get("processor"))
        if cpu_id is not None:
            processors.append({"cpu_id": cpu_id, "package_id": _integer(fields.get("physical id")),
                               "core_id": _integer(fields.get("core id"))})
        if fields.get("model name"):
            model_names.add(fields["model name"])
    nodes_text, nodes_source = sources.file("/sys/devices/system/node/online")
    nodes = []
    for node_id in _cpu_list(nodes_text) or []:
        base = "/sys/devices/system/node/node" + str(node_id)
        cpulist, cpu_list_source = sources.file(base + "/cpulist")
        meminfo, memory_source = sources.file(base + "/meminfo", ("MemTotal",))
        nodes.append({"node_id": node_id, "cpu_ids": _cpu_list(cpulist),
                      "memory_total_bytes": _memory_total(meminfo), **_UNMEASURED,
                      "source_ids": [nodes_source, cpu_list_source, memory_source]})
    meminfo, memory_source = sources.file("/proc/meminfo", ("MemTotal",))
    cpu = {"online_cpu_ids": online, "logical_cpu_count": None if online is None else len(online),
           "model_names": sorted(model_names), "processors": processors, "numa_nodes": nodes,
           "source_ids": [online_source, cpu_source, nodes_source]}
    dram = {"memory_total_bytes": _memory_total(meminfo), **_UNMEASURED, "source_ids": [memory_source]}
    return cpu, dram


def _pci_address(value: str) -> str | None:
    match = re.fullmatch(r"([0-9a-fA-F]{4,8}):([0-9a-fA-F]{2}):([0-9a-fA-F]{2})\.([0-7])", value)
    if match is None:
        return None
    return f"{int(match[1], 16):04x}:{match[2].lower()}:{match[3].lower()}.{match[4]}"


def _gpus(sources: _Sources) -> list[dict]:
    query = "index,uuid,name,pci.bus_id,memory.total,compute_cap"
    text, source_id = sources.command(["nvidia-smi", "--query-gpu=" + query,
                                       "--format=csv,noheader,nounits"])
    has_compute_cap = True
    if text is None:
        has_compute_cap = False
        query = query.rsplit(",", 1)[0]
        text, source_id = sources.command(["nvidia-smi", "--query-gpu=" + query,
                                           "--format=csv,noheader,nounits"])
    result = []
    for fields in csv.reader(io.StringIO(text or ""), skipinitialspace=True):
        if len(fields) != (6 if has_compute_cap else 5):
            sources.malformed(source_id, "unexpected NVIDIA CSV field count")
            continue
        fields = [field.strip() for field in fields]
        pci = _pci_address(fields[3])
        refs = [source_id]
        numa_node = max_width = max_speed = None
        if pci is not None:
            base = "/sys/bus/pci/devices/" + pci
            numa, ref = sources.file(base + "/numa_node")
            refs.append(ref)
            numa_node = _integer(numa)
            if numa_node is not None and numa_node < 0:
                numa_node = None
            speed, ref = sources.file(base + "/max_link_speed")
            refs.append(ref)
            max_speed = speed.strip() if speed is not None else None
            width, ref = sources.file(base + "/max_link_width")
            refs.append(ref)
            max_width = _integer(width)
        memory_mib = _integer(fields[4])
        compute_cap = fields[5] if has_compute_cap and re.fullmatch(r"\d+\.\d+", fields[5]) else None
        result.append({"index": _integer(fields[0]), "uuid": fields[1] or None,
                       "name": fields[2] or None, "pci_bus_id": pci,
                       "memory_total_bytes": memory_mib * 1024**2 if memory_mib is not None else None,
                       "compute_capability": compute_cap, "memory_technology": None,
                       "numa_node": numa_node, "max_link_speed": max_speed,
                       "max_link_width": max_width, **_UNMEASURED, "source_ids": refs})
    return result


def _json_object(text: str | None, source_id: str, sources: _Sources) -> dict:
    if text is None:
        return {}
    try:
        value = json.loads(text)
        if not isinstance(value, dict):
            raise ValueError("not an object")
        return value
    except ValueError:
        sources.malformed(source_id, "expected JSON object")
        return {}


def _storage(sources: _Sources) -> tuple[dict, dict, dict, str]:
    text, source_id = sources.command(["lsblk", "-J", "-b", "-o",
                                       "NAME,KNAME,TYPE,SIZE,ROTA,TRAN,MOUNTPOINTS"])
    tree = _json_object(text, source_id, sources).get("blockdevices", [])
    by_kname: dict[str, dict] = {}
    aliases: dict[str, set[str]] = {}
    backing: dict[str, set[str]] = {}

    def visit(rows: list, ancestors: tuple[str, ...] = ()) -> None:
        for row in rows:
            kname = row.get("kname")
            if not kname:
                continue
            by_kname[kname] = row
            disks = (kname,) if row.get("type") == "disk" else ancestors
            backing.setdefault(kname, set()).update(disks)
            for alias in (kname, row.get("name")):
                if alias:
                    aliases.setdefault(alias, set()).add(kname)
            visit(row.get("children", []), disks)

    visit(tree)
    disks = []
    for kname, row in sorted(by_kname.items()):
        if row.get("type") != "disk":
            continue
        rotational = row.get("rota")
        rotational = bool(rotational) if rotational in (True, False, 0, 1) else None
        transport = row.get("tran") or None
        media_kind = None
        if rotational is True:
            media_kind = "rotating"
        elif rotational is False and transport in {"sata", "nvme"}:
            media_kind = "non_rotating"
        disks.append({"name": row.get("name"), "kname": kname, "path": "/dev/" + kname,
                      "size_bytes": _integer(row.get("size")), "rotational": rotational,
                      "transport": transport, "protocol": transport,
                      "media_kind": media_kind,
                      "media_kind_basis": {"block_type": row.get("type"),
                                           "rotational": rotational, "transport": transport},
                      **_UNMEASURED, "source_ids": [source_id]})
    return {"block_devices": tree, "disks": disks, "source_ids": [source_id]}, aliases, backing, source_id


def _path_inventory(requested: str, sources: _Sources, aliases: dict, backing: dict,
                    storage_source: str) -> dict:
    absolute = os.path.abspath(os.path.expanduser(requested))
    ancestor = Path(absolute)
    while not ancestor.exists() and ancestor != ancestor.parent:
        ancestor = ancestor.parent
    resolved = str(ancestor.resolve())
    resolution = {"requested_path": requested, "absolute_path": absolute,
                  "existing_ancestor": str(ancestor), "resolved_path": resolved}
    refs = [sources.add("path_resolution", json.dumps(resolution, sort_keys=True),
                        status="observed", representation="metadata_only")]
    text, source_id = sources.command(["findmnt", "-J", "-T", resolved, "-o", "TARGET,SOURCE,FSTYPE"])
    refs += [source_id, storage_source]
    rows = _json_object(text, source_id, sources).get("filesystems", [])
    mount = None
    block_names: set[str] = set()
    if rows:
        mount = {field: rows[0].get(field) for field in ("target", "source", "fstype")}
        source = mount["source"]
        if isinstance(source, str) and source.startswith("/dev/"):
            # findmnt may append a filesystem subdirectory for bind mounts.
            device = source.split("[", 1)[0]
            block_names.update(aliases.get(Path(device).name, set()))
            device_resolved = os.path.realpath(device)
            refs.append(sources.add("device_resolution", device_resolved, status="observed", path=device))
            block_names.update(aliases.get(Path(device_resolved).name, set()))
    disks = sorted({disk for name in block_names for disk in backing.get(name, ())})
    if disks:
        status = "resolved"
    elif mount is None:
        status = "mount_unavailable"
    elif mount.get("fstype") in {"nfs", "nfs4", "cifs", "smb3", "9p", "ceph", "sshfs", "fuse.sshfs"}:
        status = "remote_backing_unavailable"
    elif block_names:
        status = "physical_backing_unavailable"
    else:
        status = "block_device_unavailable"
    return {**resolution, "mount": mount, "block_devices": sorted(block_names),
            "backing_disks": disks, "backing_status": status, "source_ids": refs}


def collect_inventory(paths: tuple[str, ...]) -> dict:
    """Collect static target facts and metadata for each path's nearest ancestor.

    This function does not write files. Device-mapper/LVM backing is taken from
    the retained lsblk tree; no claim about block extents or performance follows.
    Missing provider interfaces produce null values, empty discoveries, and
    explicit source statuses. All returned values are JSON serializable.
    """
    sources = _Sources()
    cpu, dram = _cpu_and_dram(sources)
    gpus = _gpus(sources)
    storage, aliases, backing, storage_source = _storage(sources)
    path_rows = [_path_inventory(path, sources, aliases, backing, storage_source) for path in paths]
    return {"schema": "scar.target-inventory", "schema_version": 1,
            "platform": {"system": sys.platform, "machine": os.uname().machine},
            "cpu": cpu, "dram": dram, "gpus": gpus, "storage": storage, "paths": path_rows,
            "sources": sources.rows, "diagnostics": sources.diagnostics}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="Paths whose mount backing should be inventoried")
    parser.add_argument("--json", action="store_true", help="Print full inventory including source material")
    args = parser.parse_args(argv)
    inventory = collect_inventory(tuple(args.paths))
    if args.json:
        output = inventory
    else:
        output = {key: inventory[key] for key in ("schema", "schema_version", "cpu", "dram", "gpus", "paths")}
        output["storage"] = {"disks": inventory["storage"]["disks"]}
        output["source_count"] = len(inventory["sources"])
        output["diagnostics"] = inventory["diagnostics"]
    print(json.dumps(output, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
