# 第一阶段：真实 LeWM native schema ports 验收

2026-10-23。**该桥验收 PASS；完整程序建模 OPEN。** 没有新采集、GPU 工作、forward
或测试套件。仅读取已保存的成功 LeWM 联合产物，运行一次接口恢复及全量核对。

## 输入与实现身份

输入来自 `first_stage_joined_dispatch_20261023/result/native/`：

- `evidence-bundle.json.gz`：stored SHA
  `1ac9553c3b981fa8fc50bcc7030fc7f2ed44517bc5d6d0b8670ec55770d32d65`，
  65,086,765 字节；原始 JSON 2,089,814,832 字节。
- `import-report.json.gz`：stored SHA
  `f658a2ed1b8c69a3d37e3ccc9d8d353d6a8b186fea4922b5d8d4a72cc7e033e9`。
- `native_schema.py` 实际源码 SHA
  `5b479e1ce898207fa88ec509f8cac4b1d19a2b78d9c4bba870ca4479d4f8e802`；
  启动 HEAD `0259a3f3e6fc5c01ade3b8a4c2498ef3ebbcface`。实现文件当时尚未提交，
  因而使用文件 SHA 标识实际运行版本。

完整 raw/stored 哈希、长度、脚本 SHA 保存在 `summary.json` 与 `stages.jsonl`。

## 实际路径

`IRBundle.from_dict` 公共读入原完整 bundle，构造
`NativeImportResult(bundle, report, [], [])`，调用 `recover_schema_contracts`。
加载得到 101,837 个已有定义与 461,242 个已有实例，未绕过公开 validator。

| 实际结果 | 数量 |
| --- | ---: |
| 解析的唯一 schema / 失败 | 100 / 0 |
| 更新的原定义 | 100 |
| 新增原 SG ValueSlot | 481 |
| 新增 PARTIAL EffectSummary | 100 |
| 新增原 SG edges | 593 |
| 实际 Tensor 槽总数 | 642,778 |
| 精确连接 formal slot | 467,756 |
| UNQUALIFIED | 175,022 |

UNQUALIFIED 的唯一原因是该 provider 观察没有可资格化的 op_schema，包括可能的
collector marker/包装观察；本轮没有按名称进一步盘点它们。没有容器类型、ordinal
或 schema 解析失败。这里的“资格化”只指参数端点对应，不是优化审批或可复用性。

## 全量核对范围

- 每个 schema binding 的 instance、definition、actual slot index、role、完整
  ordered_path、provider reference、原始 locator 都与原实际槽逐一相符。
- 每个合格 formal slot 确实存在，owner、输入/输出 ordinal、方向和 schema SHA
  与原定义接口一致；无资格化项也保留逐实例/逐槽原因。
- 新 slot/effect/edge 经过完整 bundle validator；新 EffectTarget 引用的 ValueSlot
  额外逐项核验。所有新增效果仍不完整。
- 原 instance IDs、ValueGraph 各目录 IDs 不变；642,778 个实际槽的 role/path/
  provider/descriptor/raw locator 的整体 SHA 前后相同。

`run.py` 保存这些核对；日志没有失败或重跑尝试。

## 输出与开销

- `report.json.gz`：完整桥报告，35,860,434 字节（34.2MiB）。
- `schema-graph-delta.json.gz`：110,910 字节（108.3KiB），仅新增 slots/effects/edges
  与更新 definitions；绑定原 stored SHA 和原有身份，**不是新 Program/ValueGraph**。
- 没有复制完整原 bundle。重放时重新读原 bundle、按记录的 API/源码版本执行即可
  重建接口；实际槽连接由完整报告保留。
- 阶段内完成 403.60 秒；含导入/退出的命令 wall 420.16 秒，peak RSS 9,269,584KiB。
  公共 reader 构造约263.34秒，schema桥含全验67.96秒，独立端点核对约11.18秒。
  这些是建模处理开销，不是 workload benchmark 或优化加速比。

仍未证明 canonical StateAccess 对应、完整 alias 生命周期、逻辑版本/同值、实际
mutation、physical copy、RNG/external 效果或 GPU ready。不得据本次验收宣布第一
阶段完整通过，更不能进入优化。
