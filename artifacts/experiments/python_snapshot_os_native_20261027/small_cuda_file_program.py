from pathlib import Path
import json, struct, tempfile
import torch

ROOT = Path(__file__).resolve().parent
if not torch.cuda.is_available():
    raise SystemExit("CUDA is unavailable")
with tempfile.TemporaryDirectory(prefix="io-", dir=ROOT / "data") as temp:
    source, target = Path(temp) / "input.f32", Path(temp) / "output.f32"
    source.write_bytes(struct.pack("<4f", 1, 2, 3, 4))
    values = struct.unpack("<4f", source.read_bytes())
    host = torch.tensor(values, dtype=torch.float32).reshape(2, 2)
    device = host.to("cuda:0")
    result = device @ device
    torch.cuda.synchronize()
    host_result = result.to("cpu")
    target.write_bytes(struct.pack("<4f", *host_result.reshape(-1).tolist()))
    actual = struct.unpack("<4f", target.read_bytes())
    expected = (7.0, 10.0, 15.0, 22.0)
    if actual != expected:
        raise AssertionError({"actual": actual, "expected": expected})
    print(json.dumps({"status": "PASS", "device": str(device.device),
                      "input_file": source.name, "output_file": target.name,
                      "result": actual}, sort_keys=True), flush=True)
