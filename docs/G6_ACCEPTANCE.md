# G6 自行验收报告

状态：**Verified（本文限定范围）**，由开发代理自行验收。

## 验收对象

G6 构造带接口的复合优化区域，连接静态 operation、真实 invocation、值来源、
跨层依赖和效果证据。它保留 NO-OP，不选择或调用 backend。

实现提交 `8d9ab51`；大型边界复杂度修复 `2a29ed4`；公共 API 修复 `4451372`。
最终 G6 gate **160 项通过**；整仓回归 **685 项通过**，两项既有警告，无跳过。
报告分别绑定测试时的提交与
文件哈希，不把后续修改追溯成先前压力测试已验证的代码。

## 真实输入与结果

使用已有 LeWM trace 的 45,888 条原始记录。按默认策略选择一个观察范围内最大的
调用子树：21,874 个 invocation，一个顶层 composite region，133,477 个保守
接口端口。另两个观察范围含 23,000 和 360 个 invocation；没有合并时钟/线程范围。
`max_depth=0` 表示未物化子区域，顶层成员仍全部保留。

在 `2a29ed4` 上：分析 278.724 秒，含压缩报告写出 299.109 秒，峰值 RSS
1,385,388 KiB，gzip 报告 14,383,421 bytes。输入及实现哈希前后一致。
这是 SCAR 离线分析成本；不是 LeWM 执行时间或加速比，也不能称为轻量分析。

输出保留 data、control、alias、consumer、correspondence、effects 六类缺口、
一个原始 NO-OP，零 selected transformation。缺口不等于没有依赖；133,477 个
端口也不代表这么多优化机会。

机器证据：

- `artifacts/reports/gates/g6-lewm-regions.pressure.json`
- `artifacts/reports/gates/g6-lewm-regions.json.gz`
- `artifacts/reports/gates/g6-pressure-attempt1.json`

## 失败与修复

首次压力运行在 `8d9ab51` 上超过 333 秒仍未输出完整结果，由开发代理终止了
自己启动的 SCAR 分析进程。代码审查发现逐依赖/效果重复扫描整个端口集合，以及
逐子区域复制 sibling 前缀。修复使用一次调用内的索引与批量组装；计数回归测试
约束访问次数，避免用不稳定的秒数作为复杂度断言。

这证明原代码存在复杂度问题；没有性能采样证明它是首次耗时的唯一原因。重跑的
120 秒栈位于 JSON 处理，240 秒栈位于报告序列化前的全量重验。重复完整校验与
较大的保守接口仍有成本，不能通过跳过遗漏检查来掩盖。

独立复核另发现公共 API 的宽 direct-members 集合扫描、显式叶 root 的共同
祖先重复遍历，以及损坏的内存 scope 导致异常。`4451372` 已修复并增加八项
计数/损坏输入测试。它们不在上述默认顶层 root 路径中；压力证据仍明确属于
`2a29ed4`，没有虚构又做了一次压力运行。

最终 gate 与回归报告：`g6-verified.json` / `g6-verified.md`、
`g6-regression.json` / `g6-regression.xml`，均在 `artifacts/reports/gates/`。

## 正确性边界

静态 lexical containment 不证明执行；动态调用包含关系不证明所有路径。
八层→三层回溯使用明确 G4 binding 和 producer 见证，motion 仅列出跨界依赖
变化和待证义务。相同祖先不证明值相等、目标位置可用或可安全上移。

原图已知接口的遗漏会被重建检查拒绝。完整 consumer/alias/control closure
尚未成立；未归属 operation 的数据间 alias 边留在原图并成为明确缺口。
OIR schema 2 新增静态 slot/effect/operation 端口，未伪造动态版本。

LeWM 工作区检查仍干净。本阶段没有运行新的 LeWM episode，没有修改其代码，
没有新增 backend，没有可报告的 LeWM 优化加速比。

## 下一步

G6 自行验收通过，提交报告并推送后，自动进入
[G7 子验收计划](GRAPH_SIMPLIFICATION.md)。G7.1 先补可计算语义和 use binding，
再按实际变换差量构造证明，不能拿 schema 合法当语义合法。
