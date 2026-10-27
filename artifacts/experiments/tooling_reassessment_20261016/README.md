# 工具复用与模型现状复审

2026-10-16；产品审查基线 `78c5fda`。

本目录归档三份只读审查、一份决策复审和文档一致性检查。它不包含新工具
安装、capture、自动 adapter、SCAR 模型整门验收、LeWM 运行或加速测量。
此前工具能力探针仍在 `../tooling_survey/`，保持各自原始版本和范围。

- `review/pytorch.md`：当前集成、本机源码、可复用 schema/Dynamo/AOT/ETO 接口。
- `review/graph_tools.md`：torchview、TorchLens、torchviz 的关系、精度和捕获边界。
- `review/status.md`：现有模型、自动恢复、跨表示连接与第一阶段缺口。
- `review/decision-review.md`：新决策文档的范围有限独立复审，通过不等于模型完成。
- `review_checks.json`：文档目标存在性、产品源指纹与 LeWM 干净状态。

检查命令（在开发 worktree 根目录）：

```bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python artifacts/experiments/tooling_reassessment_20261016/check_review.py
```

脚本只读文件、Git 和旧回归收据，不 import Torch 或跑测试。首次归档结果绑定
当时 revision/文档内容；将来重跑若发现不同内容，不应用其覆盖本次历史收据。
它检查本轮文档中的本地文件目标，不验证外网链接或 Markdown anchor。
既有 3,215 项冻结回归未重跑；相同 376 文件源指纹只表明产品/测试源未改变。
