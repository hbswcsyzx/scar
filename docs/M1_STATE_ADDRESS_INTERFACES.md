# M1 S：状态地址接口

状态：实现后的接口说明，验收结果另见 `M1_STATE_ADDRESS_ACCEPTANCE.md`。
本门范围和原始验收分母见 [计划](M1_STATE_ADDRESS_PLAN.md)。

## 1. 它补充什么

原 `StateLocation` 和 `StateVersionValue` 继续承载状态一致性。新增地址声明回答
“这个原状态效果涉及哪个 owner、哪个字段/key/元素/范围”，不建立另一套版本链。
粗写之后的细读、细写之后的粗读，仍必须使用同一 carrier 的当前版本。
操作可以同时读 x、读 y、写 out；它们是一个原 summary 上的多个 `AddressEffect`。
节点、输入、before/after、producer 和控制边都来自原图。

```text
原 operation
  ├─ 原 owned Uses：owner / key / index / state input
  ├─ 原 StateAccess，或 INVOKE 的原 state argument
  │    └─ 原 carrier/current/before/after 与 NORMAL/RAISE 完成端口
  └─ StateAddressRefinement
       └─ AddressEffect(owner, selector path, mode, optional stage) × N
```

## 2. 声明与校验

`ProgramGraph.state_address_refinements` 是不可变声明表。

| 部分 | 类型和含义 |
| --- | --- |
| site | `ExistingAccess(operation,index)` 或 `InvokeStateOperand(operation,state_use)` |
| owner | `DomainOwner`、`ReferenceOwner(use)`、`ResourceOwner(requirement)`、`UnknownOwner(reason,operands)` |
| path | 非空 selector 序列：WholeOwner、NamespaceKey、ObjectField、DynamicField、CellContent、Element、Slice、StorageRange、UnknownSelection |
| mode | 原 `AccessMode`，唯一 enum 定义移至 state_modes，旧 model 导入保持可用 |
| coverage | PARTIAL 或 DECLARED_COMPLETE，仅表示地址列表声明的完整程度 |
| protocol | 可选原 scoped ProviderFactReference，不自动成为事实证明 |
| stage | 可选非负声明阶段；不推断实际执行顺序、异常部分完成或 kernel 完成 |

动态 owner、key、index、slice 和 range 均引用该操作原 owned Use。重复 Use 保留；
省略 bound 与实际传入 None 的 Use 不同。key/index 可以是 Data 或 Reference，
查询不执行 Python 比较、hash、索引转换或 descriptor。StorageRange 自带 BYTE、
ELEMENT 或 ABSTRACT 单位，不解释旧 Footprint 无单位 interval。

每个 operation 的派生 carrier 只允许一条精化。mode 不得超出原 summary；
DECLARED_COMPLETE 的 mode union 必须匹配，但不会升级原 effects_complete。
原 summary.reference 非 None 时，它是 owner envelope：ReferenceOwner 可使用
不同 owned Use，但必须指同一个 canonical ReferenceValue；ResourceOwner 同样
必须沿原 handle 对应。多 owner summary 使用原 reference=None。

带新声明的 full_overwrite 仅接受单一 DomainOwner/WholeOwner/WRITE/
DECLARED_COMPLETE 的 root 替换。局部 whole-owner 写不能取消粗状态内容依赖。
INVOKE 保持原 STATE_CONTENT 要求，不加入 STATE_ORDER 例外；实际参数和
NORMAL/RAISE 端口继续按原 validator 检查。

## 3. 读接口与预算

`ProgramIndex.state_address(site)` 返回原 carrier、access/before/after、各完成边、
owner/key 等 UseSite 和资源 Use。没有声明时 refinement=None；它不表示没有效果。
INVOKE 静态 after=None，各 completion 独立保留，不选择 NORMAL。

`ExecutionIndex.state_address(effect,budget=4096)` 接受原 `AccessRef` 或
`InvokeBoundaryStateEffect`。它使用原 canonical-effect resolver、确切 operation
occurrence、UseOccurrence、denotation 和 resource requirement binding；同一静态
Use 在不同 loop visit/call activation/resume segment 中不会合并。

结果的 before/after 保留 resolver 原结果。INVOKE 另在 completion 返回实际边的
landing formal 和原 forwarded Use；即使 formal 已捕获，也不把缺失的原 post
改写成已知。缺 owner/key capture、reference identity、resource access、forwarded
state 或 completion 时保留具体 gap。原 ContentRead single-reference guard 不放宽。

budget 只度量动态 effect/operand/resource/completion joins。原图校验、快照重放、
静态索引准备和最终 detached copy 独立计费，当前没有声称覆盖所有 CPU 时间。
截断保留完整 canonical 声明、cursor、pending 和未检查项，状态为 TRUNCATED；
PARTIAL/DECLARED 均不授优化许可。合法预算是正整数，bool 不接受。

所有结果保留 coarse_dependencies_retained=True，并明确：

```text
address_interpretation_verified = False
source_runtime_verified = False
value_identity_verified = False       # dynamic query
transformation_authorized = False
```

## 4. 序列化与兼容性

非空新声明选择 Program wire v15，variant 使用显式 kind tag。空表维持历史能力
选择，旧 v1–v14 字段、字节和 golden 不增加新标签；解码不为旧图补默认地址精度。
Execution wire 没有因这个派生查询升版。最高支持 schema 的六处旧测试机械更新，
历史 proof/schema14 断言和全部旧 fixture 保留。

## 5. 已连接与未完成

本门组合验证了 multi-owner、六种动态/静态 selector、stage、分支 owner/key 配对、
coarse/fine 两向 current、INVOKE 两完成边、forwarded state、loop、call、resume、
资源 binding 和旧 ContentRead 防护。它们是声明图与已有执行记录之间的接口验证。
普通 call 的 DataUse 路由正例不等于真实共享 Python cell 身份证明。

自动源码恢复、Python native 协议、通用 alias/partition 求解、地址到物理 Mat/字节的
完整映射以及运行时采集覆盖尚未完成；本门不将不同 owner 名称视为 disjoint。
新声明不能建立纯性、恒定、完整捕获、ready、dead、可删除 import 或可复用的结论。
后续继续 literal、C2/D3、M2 原分母。没有新增 detector/backend，没有新的 LeWM
性能实验，也未达到用户要求的全程序建模完成停止点。
