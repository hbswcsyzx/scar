"""Small tracing-cost probe, not a LeWM benchmark."""
import json
import os
from pathlib import Path
import time

started = time.perf_counter()
for _ in range(100_000):
    assert os.getpid() > 0
status = {line.split(":", 1)[0]: line.split(":", 1)[1].strip()
          for line in Path("/proc/self/status").read_text().splitlines() if ":" in line}
print(json.dumps({"getpid_calls": 100_000, "wall_s": time.perf_counter() - started,
                  "Seccomp": status.get("Seccomp"), "Seccomp_filters": status.get("Seccomp_filters")}))
