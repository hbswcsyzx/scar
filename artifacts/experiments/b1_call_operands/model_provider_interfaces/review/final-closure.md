# P0 完成边来源：最终只读闭环

2026-10-16。**PASS，仅限下述两项修复的静态一致性审查。**
基线 HEAD 为 `35469f0cc608d46d21b75775c7ba69fe76619109`；本次读取的是该提交之后
尚待重新冻结的工作区补丁。未运行任何测试、新 probe、采集或目标程序。
没有修改产品、测试、gate 或 docs；仅新增本 ignored 报告。

## 修复确认

1. `provider_validation.py` 先遍历所有实际 CFG successor，将 `(operation.id, edge)`
   逐条加入目标 block 的 incoming 列表。它计数真实边，不合并相同源操作或目标，
   不假设未观测分支不可行。
2. 只有 `len(edges) == 1` 时，才按实际参数位置对 `CompletionResult` 或
   `PendingPayload` 派生来源操作。两个 dispatch 共用 landing、投影与 UseID
   转发合流、同操作多条边共用目标均不再被强制赋予单一 producer。
   因此上一版 `edge_producers[formal]` 的 last-wins/操作元组顺序依赖已消除。
3. INVOKE 原有私有完成目标符合唯一入边条件；其正常/异常结果及 post-state
   仍接受 operation key 和非空投影校验。不会为普通入口、UseID 转发或多入边
   phi 增造 producer，也没有另存一份 canonical 依赖关系。
4. docs §3 同步明确“唯一真实入边”的规范化映射规则，以及普通入口、Use 转发、
   多入边 phi 的例外。实现与这项限定一致；未发现本修复范围内的其他实质问题。

## 范围与证据边界

- 这是 P0 规范化来源声明的结构校验，不验证 native artifact locator、端口
  索引或 completion kind 的实际含义；外部原生 CFG 参数来源仍是 P1 缺口。
- 没有证明 artifact/hash 真实、guard 成立、动态对应、跨表示等价或变换合法。
- root/reuseagent 的新 order-invariance 用例及后续门测试由其负责；本报告不借用
  未读取的运行结果，也不把中止的全仓回归说成通过。
- 原 [review.md](review.md)、[closure.md](closure.md)、[probe.py](probe.py) 和
  [probe.result.json](probe.result.json) 原字节保留；旧四个错误接受结果没有覆盖。

## 本次核对 SHA256

| 文件 | SHA256 |
| --- | --- |
| `scar/ir/program/provider_validation.py` | `7f017cca1fa2779571173842c93a09bf966138ea73d7e16785a707fb0b195cac` |
| `docs/M1_PROVIDER_INTERFACES.md` | `22bc4ed70cfc5604045902fe788ed87a6099b9c75180848a0f6c862f172222a8` |
| `scar/ir/program/validation.py` | `16b96077b5eee8a15b134fa2d95e6117f2b21e7c70b102881cee863a47177d9c` |

两项已发现问题的只读闭环至此结束；不据此关闭全部 T1、M1/M2 或第一阶段。
