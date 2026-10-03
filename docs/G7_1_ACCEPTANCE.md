# G7.1 自行验收报告

状态：**Verified，限于源码语义与条件性常量推导**。本子节点通过不代表 G7 总门通过。

实现版本：`d5fe9cb`。专项 gate **163 项通过**，整仓回归 **848 项通过**，两项
既有警告，无跳过。2026-10-03 归档时再次核对实现哈希与八份输入文件哈希，均与
报告一致，因此没有重复运行已充分完成的测试或把旧测量写成新测量。

## 模型与代码对应

`SourceSemanticsGraph` 引用原 SG operation/source atom，增加有序操作数、静态
表达式结果、独立的 binding definition 及每次读取的 reaching definition。
静态 ID 与 G4 动态逻辑版本独立。尚无计算规则的节点保留在明确的 unmodeled
registry 中；缺口不会被当作无效果，也不会被丢弃。

固定 builtin 求值器生成精确类型/内容事实与可重算证明链。源码重放验证 opcode、
顺序和绑定与实际文本相符；常量报告验证则重新计算固定规则。二者都要求对应的
版本，不能用类型合法或摘要相同替代真实来源检查。

## 外部 LeWM 源码压力

八份显式选择的源文件分别分析，覆盖入口、policy、CEM、模型实现与依赖数据层。
没有导入或执行目标，没有声称得到入口可达闭包或 whole-project 闭包。

| 项目 | 结果 |
| --- | ---: |
| SG operation | 9,340 |
| 已有计算语义的 operation / 静态值 | 6,636 |
| 保留具体缺口的 operation | 2,704 |
| 静态 binding definition | 478 |
| 条件性 CONSTANT 事实 | 1,116 |
| 其中非直接 literal 的派生 operation | 89 |
| NEEDS_CONTRACT 事实 | 1,169 |
| NOT_CONSTANT 事实 | 4,351 |
| 分析时间 | 22.955 秒 |
| 分析与压缩写出 | 25.961 秒 |
| 峰值 RSS | 116,568 KiB |
| 压缩记录 | 2,948,824 bytes |
| selected transformation | 0 |

常量数量包含直接 literal，不等于同样数量的优化机会；89 个派生结果也尚未成为
合法修改许可。上述时间是 SCAR 分析成本，没有 LeWM A/B 或加速比。

## 反例与修复

- 同一 slot 多次写入时，各个 use 绑定不同定义；跨分支、循环、deferred body
  和 opaque state boundary 不保留过期 exact binding。
- 赋值覆盖可能执行析构函数。opaque 代码还可能创建此前源码未写过的全局项，
  所以 write count 为零不构成旧 occupant 不存在的证明。
- 字典和 keyword mapping 展开的效果可先于后续值/参数求值；连接关系记录这些
  失效边界，而非把所有参数都视为调用前不变。
- source replay 拒绝被篡改的 opcode、左右顺序和重复输入；序列化 preserves
  bool/int、float 位模式、bytes、tuple、Unicode 与 lone surrogate。
- 外部报告的预算不能成为验证重算的上限。独立的调用方 verification budget
  在重算前检查；哨兵反例阻止超大分配，没有实际进行该分配。

## 适用条件与未完成项

普通新模块 namespace、标准函数局部绑定和没有未建模外部 namespace 修改都是
明确的 required execution preconditions，状态仍为 REQUIRED_CONTRACT。
目标 builtin/浮点环境的匹配也需要单独核对。不能把这些条件升级为 Observed。

本节点没有证明任意 module 的纯性、import 初始化可删除、mutable 输出可共享，
或 dynamic provenance 已与这些静态结果连接。class namespace 保持开放；
deferred method body 可以独立建模。目标源码、运行环境与 LeWM 工作区未修改。

## 归档与后续

机器记录位于 `artifacts/reports/gates/`：

- `g7-1-verified.json` / `.md`；
- `g7-1-regression.json` / `.xml`；
- `g7-1-lewm-semantics.pressure.json`；
- `g7-1-lewm-semantics.json.gz`。

下一步为 G7.2：静态替换进入 OIR，四类规则使用固定、差量相关的证明义务，
跨 import 值路径保留 loader/rebinding/初始化效果条件。随后 G7.3 生成详细修改
指导、G7.4 完成外部压力；G8 再负责收益和组合选择。每步由开发代理自行验收。
