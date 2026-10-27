# D2.3 最终 bounded review receipt

2026-10-18；状态：**BOUNDED_PASS，无剩余实质阻断。**
本 receipt 不修改已冻结 `session-implementation.md`（SHA256
`93daa10650e76a89bcdf14d8198df8974fc1b05a443d4f2cf12428096e417274`）。
范围为 root P/shape/analysis/query/CLI 的独立只读复核；自写 terminal flow 不冒充独立审计对象。

## 冻结来源

在 conda lewm 只调用 `scripts.run_gate.fingerprint`，未执行 gate main/pytest/probe/模型或改源码。
实际 **443** 文件完整指纹与 root freeze 相同：

`23e4c97fc75b7ea889c964fb77a5eada6b617ab94e9a3b308d617f16af340596`

完整 per-file SHA 及 matches_root_freeze=true 保存于 `receipt-fingerprint.json`，精确只读命令在
`receipt-fingerprint.command.txt`。这绑定实际源快照，不表示逐文件独立执行过测试。

| 被核对 module | 最终 SHA256 |
| --- | --- |
| session_flow.py | `13e90d83f74bd46281a678c778c559ad1d6d52d3d5722137be38848f853a7387` |
| session_release_validation.py | `b96e989a611a518630e2c33bbf61b5f69d4cc015b54166d27f78a6486482e0fc` |
| lifecycle_analysis.py | `153c309f0cd32a6b6b719f0266dbc68209a107c9746bb88c2463194d7d650dd7` |
| queries.py | `7f119421509b7a1237304e713fb6f52d461891b802395bb46e0326e556cd1aa6` |
| validation.py | `04ed471b6164b14e738ed0c22aee16f256f2a925038321a478834ef68aff7264` |
| scar/cli.py | `859fa00f44644303758c0a3a8a362704d4ba38befa23c21a6d73d6513e802135` |
| lifecycle_flow.py（实现交付背景） | `8adaa530a1801949a0706948c9aef2410148782fa95e49da18706ed5c794fae0` |

精确 reference 修正仍为 session `{None,Ruse,Buse}` / release `{None,owneruse}`，保留 core selector/targets/currentness 检查；
query NORMAL 字段现为真实 `CompletionSuccessor|None`。源审两项已闭合，没有制造旧失败日志。

## 既有 root 执行证据确实存在

均位于 `artifacts/experiments/b1_call_operands/model_session_release/`，本轮只读取原日志：

| 路径 | 读到的实际结果 | stdout SHA256 |
| --- | --- | --- |
| graph/attempt-001 | 18 passed in 0.69s | `f84e53b702947b19a49446a2677b5f5bfbc375118928e5eb405dca8637dbdf55` |
| graph/precision-002 | 2 passed in 0.39s | `df184e1384a1d41f53ef77ec2045c1c728488ca377dff284cad494d0d1091885` |
| queries/attempt-001 | 13 passed in 0.82s | `a0584ab9a9bf51d0dc9910e73f866b592027fd98b58d4fa09a10f6372b51b252` |
| composition/attempt-001 | 14 passed in 0.58s | `3d982959a6d0ad327e4c2ff7cfedf579823ee4d0c00b0aff1195763fb428a921` |

graph20 是两次实际执行 18+2，不虚构为一次20项独立运行或合并运行时间；query13/comp14亦为 root 证据。
已只读核对对应真实图断言和 R1/R2回归，未重跑，不拿数量当语义建模覆盖率。
统一 component/clean commit/唯一 full 由 root 随后完成；本 receipt 不声称这些后续门已经通过。

结论仅为当前声明级 current-post、ordered pair merge/失效、终结历史与窄 release 接线的 bounded review。
不证明 native/source/runtime、动态对象 identity/lifetime、guard/字段实现、完整 family 状态机、资源 held/free/ready 或变换权限。
