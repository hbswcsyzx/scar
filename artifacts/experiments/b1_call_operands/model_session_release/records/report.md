# D2.3 records / ProgramGraph 报告

## 已实现

`LifecyclePostBinding(AFTER_OPERATION, NORMAL_COMPLETION)` 与 `SessionPost(HOLD, COMPLETE, ABANDON)`；`SessionUpdate(operation, request, body, binding, post)`；`TerminalFrameRelease(operation, owner, rules=FrameRules())`。均 frozen/slots，exact IDs/enums；R/B 为独立 UseID，实际 Value 可 alias；FrameRules exact 类型与既有固定字段递归重验，不增加 verified/consumed/free 权限。

ProgramGraph 末尾追加 `session_updates` / `terminal_frame_releases`，严格 tuple/记录及嵌套复验，每表 operation 唯一；两新角色彼此及全部旧 lifecycle / D1 / context / cleanup 角色互斥。仅存 overlay，未增加 actual、producer 或状态表。公共 exports 已接。两个真实 release 尝试可共享 owner，记录层不把它们误判一次性权利或冗余。

## 测试与原始尝试

环境 conda `lewm` / CPython 3.14.7，命令：

```bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python -m pytest -q tests/unit/test_session_release_records.py
```

- 首次：10 passed / 17 failed / 0.60s，exit1，完整 `initial.log/json` 保留。原因是测试用 `object.__setattr__` 故意破坏默认共享的 frozen FrameRules，污染同一进程后续默认构造，不是产品合同缺陷。
- 补正：仅让该破坏性测试显式持有独占 `FrameRules()`；不放宽产品规则、不改断言。第二次：**27 passed / 0.35s**，exit0，`corrected.log/json` 保留准确命令/版本/耗时/源码 SHA。

## 边界

本报告只对 records 和 owned-tuple 构造检查作有限结论，未验收 runtime/source 适用、terminal 历史及 session 当前态数据流算法，未运行 LeWM/GPU/full 或新 capture；wire 等 root fixture/golden READY 后独立验收。未修改 validator / queries / CLI，不作加速结论。
