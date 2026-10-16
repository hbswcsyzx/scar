# Resource protocol witnesses

2026-10-16。只运行小型 CPU/stdlib 反例，未执行 LeWM、未改环境、未初始化 CUDA。

命令（cwd：当前 structured-model worktree）：

```bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
python artifacts/experiments/b1_call_operands/model_resource_protocols/probe.py
```

最终执行 exit 0；`probe.json` 保存环境版本、本机 PyTorch 相关源文件 hash 和结果。
JSON 中 `cuda_initialized_before/after` 均为 false。结果只证明列出的反例，不证明
自动模型提取、GPU 物理行为、全 API 的异常合同或任何化简权限。

`attempt-000-float-comparison/` 保留初始探针及结果：其“参数已写入”比较将 float32
写入值与 Python float64 的 `old + 1` 比较，出现假阴性。最终探针改为与实际输入
Tensor 使用 `torch.equal` 精确比较，确认 load 抛错时前项参数已写入。该修正只
涉及验证表达式，不修改被测 PyTorch 或模型协议。
