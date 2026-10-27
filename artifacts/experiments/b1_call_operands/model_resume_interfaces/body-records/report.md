# C2B records 实施交接

仅新增 `scar/ir/program/resumption.py` 与 `tests/unit/test_resumption_records.py`；未修改 model/control/validation/codec 或其他测试，未 commit。
字段审查已冻结在 `review/body-contract-review.md`，SHA-256 为 `d9bc0cdc9f325a9ca61aaea5f22afa02ccb6feb2c6e84ce8a3c5db6ade1dbd68`。

- 四个 enums、四个 body/context records、saved/resume slots、ResumeSuccessor 与 SuspendTerminator 均按冻结合同；nested 新 records exact/frozen/slots 并递归复检。
- constructors 检查独立 UseID、唯一 FRAME_CONTEXT 槽、payload/state 槽形状、ResumeInput 完整且恰一次、saved 索引上界和独立 targets；SavedInput 同槽多 formal、未使用的 saved 槽均允许。
- `saved_actual_use` 只解析已有 canonical Use；普通 UseID 子类保持原对象，ResumeInput/CompletionResult/其他投影不产生来源。不按 `.value` 重建 ID。
- `resume_slot_type` 和 `term.kind` 延迟导入 model，模块没有顶层 model import；kind/values/condition/exit 都是视图，不另存字段。

唯一一次定向执行：`PYTHONPATH=. /home/zyf/miniconda3/envs/lewm/bin/python -m pytest -q tests/unit/test_resumption_records.py`。
结果：**87 passed in 0.40s**，exit 0；完整输出在 `records-pytest.log`。没有失败输出；没有运行其他测试、full、应用 LeWM、GPU、采集或安装。

这些结果只验收 constructors/投影视图/helper；body graph validation、codec/query 与 C1 集成由 root 负责，尚未据此验收；整体 C2/driver/source/runtime/generation 仍 OPEN。
