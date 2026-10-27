# 下一门：先修清楚区间效果，再完成原 F16

本门之后仍以完成原 M0–M2 程序建模为目标。不得用局部 supplied graph 测试替代
整个程序自动拆解，不增加 backend、detector 或 LeWM 特例。

## 1. 已经有的连接应复用

- 原 request 创建、关联、same-R 三次真实 step、completed reuse 和 scheduler packets。
- 本门一 B 两 R 的真实竞争、own N/R/fullstate、caller catch、R1 两次 await 后 item。
- thin occupancy subject、原 READ/bool/BRANCH、源 HOLD 与条件性 request/body 投影。
- Program24/旧 wire 的能力隔离，Execution8 不变，来源/输入/预算缺失的反例。

不再重新造上述图或增加类似参数矩阵。以新 checkpoint 的原条款和实际 testcase
身份为起点，保护所有历史失败字节和原义务分母。

## 2. 优先审查：整个调用的摘要与局部执行区间

当前完整 parent INVOKE 摘要会阻断其内部一部分区间的保持证明。
这关系到跨多层调用查找输入来源和上移计算，须先把合同说清楚再改查询。

本门已只读核对现有接口，不能假定它们提供了尚不存在的保证：

| 现有接口 | 已表达 | 尚未表达 |
| --- | --- | --- |
| `state_preservation._Walk.scan/invoke_states` | 原 operation、整个 INVOKE 输入/选中完成状态、完整声明及读写效果 | 某个 effect 是整个调用的摘要，还是实现外单独发生的边界效果 |
| `_Walk.run/escape` | 进入 callee 和返回 caller 的真实路径；两处均检查 parent | source 之后的 suffix 与 target 之前的 prefix 应覆盖哪些额外效果 |
| `CallActivation` 与 execution `region_implementation` | 此次准确 entry/completion、实参、结果和完整 state slots | callee 对整个调用效果的完备实现覆盖；查询明确保留 native/effects gaps |
| `NativeBoundary` | native/core-only 输入输出的完整不交叠分区 | 状态或 mutation 语义，类文档明确不推导 |
| `ProviderRegion` / `ProviderCoverage` | representation/observation 关联、带证据的覆盖声明 | 完整可替换实现及无额外副作用；coverage 明确不是合法性证书 |

因此现阶段的保守阻断有依据。缺的是 **准确 callsite→callee 的效果完备覆盖**，
以及不包含在 callee 内的入口/退出剩余效果、其排序和各 N/R 的 state ports。
不能由 callee 存在、provider 覆盖、地址标签或已知 completion 猜出这些事实。

1. 列出原 CallActivation、region implementation、provider/native boundary 已有接口。
   明确调用入口/退出、实际 child body、未展开原生部分分别覆盖什么效果。
2. 明确 whole-call summary 是覆盖所有效果的上界，还是包含独立的边界副作用。
   不能因发现一个 child 就丢弃 parent 未展开的剩余部分。
3. 对 source 在 child 内、target 在另一个 child 内的区间，分别核对 suffix、
   中间 caller 和 prefix；保留选中 N/R、完整 state domains、实际端口与来源。
4. 对区间外真实写入、区间内真实写入、未展开 boundary、缺 child/transfer、
   地址别名不明和预算耗尽，先定义不同结果和理由，再实施最小查询修复。
5. 不添加任意 `preserves_post=True` 声明，不将旧 opaque getter/terminal 翻成纯，
   不以两个 StateLocationID 不同断言隔离。原 R3 四个阻断逐一保留或由真实展开消解。

先尝试在新供图中把真实入口/退出效果展开为独立原 Operation 和 state ports，
再判断原 IR 是否还需一个最小的完备覆盖关系。新增合同必须有明确引用、适用范围、
N/R 与缺失默认 Unknown；不能只是一个“允许跳过检查”的布尔开关。

验收必须有完整区间正例以及上述原阻断反例、准确源码/JUnit/报告。
仅当全部前提成立才能得到 preserved True；无法恢复的部分继续明确列出缺口。

## 3. 后续原 F16 联合控制

依据原 fixed profile 核对 request initial、body Created、首次 ASEND 的 latent SEND[0]
和 None 判断。联合条件及每条 actual poststate 必须沿原 bool/BRANCH/call 连接表达。
occupied True 不应拒绝 R1 的后续 step；R2 COMPLETE 不代表 B 空闲。
不把 callback 中的历史 bool 当作当前快照，不借未来 Drive 倒推历史主体。

## 4. 完成后仍需的原阶段

| 范围 | 真实交付 |
| --- | --- |
| F16 | 原竞争/状态内容/initial-ASEND 完整合同和逐条原义务审计 |
| F18/F19/F20/F22/F24/X25/X26/X27 | 各自原场景及实际 occurrence，复用已有基础连接 |
| P4 component / frozen full | 同一冻结源码的相应门，不能拿 affected focused 代替 |
| P5 / M2 | 原覆盖和字段分母验收：113 构造、196 字段，不改分母 |
| M0–M2 完成 | 停下向用户解释实体、连接和表达边界，再进入自动 lowering / 真实对应 |

所有门由开发者自行验收、写报告、版本管理；不要求用户逐门批准。
