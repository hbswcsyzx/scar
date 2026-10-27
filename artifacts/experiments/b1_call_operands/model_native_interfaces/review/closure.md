# B1 限定关闭复审

2026-10-16。仅复审 integration-review.md 的 **B1 / P2：合法 legacy ID 子类图被新端口索引拒绝**。本次只读代码和已保存结果，没有运行测试、新实验、Torch 或 LeWM，也没有修改产品。

## 结论：B1 CLOSED（限定范围）

1. `native_validation.region_port_keys` 直接保留原 RegionID / ValueID 对象组成坐标 tuple，不对所有旧图构造严格新端口记录，也不按 ID 文本归并身份。`port_key` 仅接受已经声明的 exact EntryPortRef / ExitPortRef。
2. `ProgramIndex` 的 entry/exit 索引沿用上述原 ID 坐标；所有 Return/Raise 的既有 UseSite 仍按出口位置收集。`boundary_unpaired_ports` 从已校验 NativeBoundary 的引用中按 canonical core 顺序返回，不重新构造无关旧图引用。
3. 新端口 records 的 exact ID 要求没有放松；native/core 完整分区、重复端口拒绝及私有嵌套篡改的 schema 拒绝路径保持。没有新增证明或变换授权。

## 依据与归属

- 已静态复核 `native_validation.py`、`queries.py`、严格端口 constructors 及 root 新增的四组合 regression：ValueID / RegionID 子类 × 纯旧 core / 含无关 native 子区。测试保留原 ID 对象身份，并检查无关 native 输出的多 Return 计数。root 报告相关定向测试 **45 PASS**；该套件不是本审查者执行。
- 已读取 root 实际运行保存的 [results.after-fix.json](results.after-fix.json)：原五项 probe 全部 PASS，原 legacy subtype 反例现在 validate/index 成功；重复值多出口计数仍为 `[2,2,1]`，auxiliary artifact 被接受，重叠分区及 bool 篡改仍被拒绝，`torch_imported=false`。
- 对比 [probe.py](probe.py) 与 [probe_after_fix.py](probe_after_fix.py)，唯一差异是结果输出文件名；没有修改反例逻辑来取得通过。
- 原 [integration-review.md](integration-review.md)、[results.json](results.json) 的真实回归及 [results.initial.json](results.initial.json) 的启动失败均保留，不回写原结论。

本次限定复审未发现第二项实质问题。关闭的是 B1 兼容性回归；不据此宣称 component-final、全仓、P1 全门、完整程序模型、artifact 真实性、边界等价证明或 LeWM 优化已经通过。
