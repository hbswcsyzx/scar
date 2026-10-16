# Native 接口复用边界复审

日期：2026-10-16。基线 `5ccc1d2`。**设计复审，不是产品实现/运行验收。**

本报告由根代理汇总独立审查消息并对照当前文档；独立审查代理在落盘前因
模型容量错误结束，因此不声称存在其完成的独立报告或新测试。
此前完整 P1 草案仍保留于模型实验目录，不能当已实施 API。

## 裁决

草案把通用 TreeSpec、全部 native 角色、各种完成投影及跨表示适配一并作为
首次导入前置，范围过宽。工具复用应缩减需要自制的东西，而不只是给新类型
增加来源字段。

| 必须先明确 | 优先保留/复用 | 不作为首次 provider-local 导入前置 |
| --- | --- | --- |
| artifact 版本、阶段、作用范围、归属 | 原始 FX graph / Export signature / call spec | 复制所有 Export 枚举与 pytree 解释器 |
| 有序 flat slot → canonical entry/exit | FX args/kwargs 与原生 pytree 规则 | 全部可能的嵌套 Python 容器协议 |
| 具体未知状态/异常/alias 边界 | 原生 constraints/guards 和捕获限制 | 证明导出图与原程序全部观察等价 |
| definition 与 occurrence 分开 | ETO/Profiler 实际执行及原始关联 | 将一次运行强造为全路径静态 SSA |

Entry 必须指区域实际参数。Exit 指逻辑出口槽，查询保留所有实际 Return/Raise
站点。native signature 的顺序不必等于 core 加入环境/state 后的参数顺序。
同一个值的重复位置不得去重。

原生 signature/call_spec 是权威 artifact；adapter 读取并校验，SCAR 只维护
需要跨边界查询的引用或可重算索引。不能在两张可独立修改的表里复制 producer、
actuals 或 state。custom pytree 不因反序列化便利而获得执行任意代码的权限。

## 三个必须保留的反例

1. `(y, y)` 对应两个输出位置；单条 unique-consumer 边不能替代这两个 occurrence。
2. 原 Python 只返回一个 opaque tuple 引用；原生 flatten 返回两 Tensor 时，树结构
   不能凭空产生两条已经证明的依赖。保留 adapter/projection 义务。
3. functionalized 图返回 buffer 新值，原程序还需具体 owner/current state 的写回。
   provider 自身图可先导入；没有写回和异常路径依据就不能说原程序等价。

## 实施顺序和阶段界限

1. 一份固定原生 artifact：逐项端口/重复 use/状态角色分母与来源。
2. 薄边界引用：验证错区域、错误出口、多 Return 和 native/core-only 参数分区。
3. 逐域未证关系：数值、state、alias、grad、RNG、异常、外部历史、resource-ready。
4. 完成第一阶段模型接口及组合规则后，先停下来向用户讲解。
5. 后续 T2 再交付实际公开导入和观察器成本/替代比较。

声明有效、artifact 真实可重放、依赖已导入、原程序可替代分别验收。
本报告没有新增 detector/backend，没有测试、额外采集或 LeWM 性能结论。
