"""Real native-provider evidence must coexist with the Python recorder."""
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]


def trace(tmp_path, source, *options):
    project = tmp_path / "project"
    project.mkdir()
    program = project / "entry.py"
    program.write_text(source)
    output = tmp_path / "trace"
    env = {key: value for key, value in os.environ.items() if not key.startswith("SCAR_")}
    env.update(PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1", CUDA_VISIBLE_DEVICES="")
    command = [sys.executable, "-m", "scar.cli", "trace", "--out", str(output),
               "--project-root", str(project), *options, "--", sys.executable, str(program)]
    completed = subprocess.run(command, cwd=ROOT, env=env, text=True,
                               capture_output=True, timeout=120)
    return completed, output


def test_call_operands_and_native_providers_share_one_real_execution(tmp_path):
    completed, output = trace(tmp_path, """
import json
import sys
assert 'torch' not in sys.modules, 'collector imported Torch before the target'
profile = sys.getprofile()
import torch
assert sys.getprofile() is profile, 'native collector replaced the call hook'
counter = 0
def work(x):
    global counter
    counter += 1
    y = x.view(2, 2)
    result = y + y
    x.add_(1)
    return result
x = torch.arange(4, dtype=torch.float32)
for _ in range(3):
    result = work(x)
assert counter == 3, 'collector reran the target function'
assert result.sum().item() == 28
assert x.sum().item() == 18
print('TARGET_FINISHED')
""", "--call-operands", "--execution-evidence")
    assert completed.returncode == 0, completed.stderr
    assert "TARGET_FINISHED" in completed.stdout
    meta, = output.glob("call-meta.*.json")
    calls = json.loads(meta.read_text())
    assert calls["dropped_events"] == 0 and calls["errors"] == []
    operand_meta, = output.glob("call-operand-meta.*.json")
    operands = json.loads(operand_meta.read_text())
    assert operands["dropped_events"] == 0 and operands["errors"] == []
    operand_files = list(output.glob("call-operands.*.jsonl"))
    assert operand_files
    raw_operands = "\n".join(path.read_text() for path in operand_files)
    assert "VISIBLE_HOOK_OR_MONITORING_MUTATION" not in raw_operands
    native_file, = output.glob("execution-trace.*.json")
    native = json.loads(native_file.read_text())
    names = [node["name"] for node in native["nodes"]]
    assert names.count("aten::add") == 3
    assert names.count("aten::add_") == 3
    chrome_file, = output.glob("kineto.*.json")
    chrome = json.loads(chrome_file.read_text())
    assert any(event.get("name") == "aten::add" for event in chrome["traceEvents"])
    manifest, = output.glob("execution-evidence.*.json")
    assert json.loads(manifest.read_text())["whole_model_established"] is False


def test_enabling_evidence_does_not_force_torch_into_non_torch_program(tmp_path):
    completed, output = trace(tmp_path, "import sys\nassert 'torch' not in sys.modules\nprint('NO_TORCH')\n",
                              "--calls-only", "--execution-evidence")
    assert completed.returncode == 0, completed.stderr
    assert "NO_TORCH" in completed.stdout
    assert not list(output.glob("execution-trace.*.json"))
    assert not list(output.glob("kineto.*.json"))
    manifest, = output.glob("execution-evidence.*.json")
    assert json.loads(manifest.read_text())["whole_model_established"] is False


def test_evidence_without_call_recorder_rejects_before_target_execution(tmp_path):
    completed, _ = trace(tmp_path, "raise AssertionError('target must not run')\n", "--execution-evidence")
    assert completed.returncode != 0
    assert "requires --calls-only or --call-operands" in completed.stderr
    assert "target must not run" not in completed.stderr


def isolated_program(tmp_path, text):
    env = {key: value for key, value in os.environ.items() if not key.startswith("SCAR_")}
    env.update(PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1", CUDA_VISIBLE_DEVICES="")
    result = subprocess.run([sys.executable, "-c", text, str(tmp_path)], cwd=ROOT,
                            env=env, text=True, capture_output=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr


def test_existing_native_observer_is_not_unregistered(tmp_path):
    isolated_program(tmp_path, """
import json
from pathlib import Path
import sys
import torch
from scar.trace.execution_evidence import install
root = Path(sys.argv[1])
foreign_path = root / 'foreign.json'
foreign = torch.profiler.ExecutionTraceObserver().register_callback(str(foreign_path))
manager = install(root / 'scar')
manager.close()
foreign.start()
torch.ones(2).sin()
foreign.stop()
foreign.unregister_callback()
names = [row['name'] for row in json.loads(foreign_path.read_text())['nodes']]
assert names.count('aten::sin') == 1, 'foreign native observer was removed'
assert not list((root / 'scar').glob('kineto.*.json'))
""")


def test_existing_profiler_stays_active(tmp_path):
    isolated_program(tmp_path, """
from pathlib import Path
import sys
import torch
from scar.trace.execution_evidence import install
root = Path(sys.argv[1])
with torch.profiler.profile(activities=[torch.profiler.ProfilerActivity.CPU]) as foreign:
    manager = install(root / 'scar')
    manager.close()
    assert torch.autograd._profiler_enabled()
    torch.ones(2).cos()
assert any(row.key == 'aten::cos' for row in foreign.key_averages())
assert not list((root / 'scar').glob('kineto.*.json'))
""")
