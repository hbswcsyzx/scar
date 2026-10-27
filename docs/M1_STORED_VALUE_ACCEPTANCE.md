# 原存储值关系：限定验收记录

2026-10-20。基线 `5fd5a7f0b246f72ff708f53ba000728817a8feca`。
[计划](M1_STORED_VALUE_PLAN.md) · [设计补充](M1_STORED_VALUE_DESIGN.md) ·
[API](M1_STORED_VALUE_API.md) · [迁移](M1_STORED_VALUE_MIGRATION.md) ·
[下一门](M1_STORED_VALUE_NEXT_GATE.md)。完整第一阶段尚未完成。

## 1. 实施及依据

**Observed：** 在基线907/b7a6ad…稳定源上，旧 state_preservation 可返回 True，
但原访问接口无 owned payload→state→load own-result 值关系。该诊断没有 native
target 或 LeWM 执行。未知来源并非未给足查询预算。

**Implemented：** 两个不可变原访问关系 StoredValueWrite/StoredValueRead、原端口
校验及 Program27 capability wire；新 stored_value_sources 派生查询把准确实际
payload、当前 state、选中完成、单槽地址及透明区间连在一起。核心五类实体保持。
既有 state_preservation 不负责解释写入值，普通 copy/identity 图没有新增 union。

**Verified（声明级相关选集）：** 最终961项全部通过。P→read、Q覆盖→read、原 N/R
重排、未声明 R 不能借 N、两相同 callee 实际 activation 和局部缺采均通过。
基线声明之外的 native/source/runtime/value 身份与 transformation 权限仍 False。
最终全选集结果见第2节，不能把局部复验当整个阶段完成。

**Rejected：** 字段名就是 raw slot；同对象就是数据未变；Create+时间顺序证明
字段不变；用不同 Location 当隔离；未选/未声明 R 当回滚；同完成多 post 按
stage/附件序任选；Reference key 当 builtin Data；缺捕获或预算用已检查前缀翻 True。

## 2. 实际执行与不可覆盖的首败

归档 `artifacts/experiments/b1_call_operands/model_stored_value_relations/` 保存每次
原命令、环境、源码前后指纹、变更源码原字节、stdout/stderr、JUnit及result。

| Attempt | 实际结果 | 含义 |
| --- | --- | --- |
| first-exact-store-read | 1 PASS，0.90秒 | 基础P/read及Q覆盖后的原payload来源通过。 |
| first-joint-stored-values | 94 PASS / 12 FAIL，20.10秒 | 8个NEW fixture canonical构造失败；4个旧codec最高/未来版本断言需显式迁移。 |
| corrected-original-ports | 100 PASS / 7 FAIL，21.93秒 | opaque真实状态/控制Use/产出Reference精度及codec已修；7例仍缺exception packet的lexical scope。 |
| corrected-packet-scopes | 7 PASS，1.14秒 | 补原Region lexical scopes；N/R与跨call原7断言全保，未制造packet constructor。 |
| verified-current | 961 PASS，379.59秒pytest / 380.5244640568271秒wrapper | 47模块，不计作全仓、整个原catalog或第一阶段验收。 |

前两次fixture首败均在 require_valid/snapshot 构造阶段，未到相应来源查询，不
包装成产品已经正确拒绝错误来源。scope修复只补原blocks真实所有权，旧25个执行
测试断言逐字节保持。审查另修静态同Data key post冲突和Reference selector崩溃。

当前冻结913文件指纹
`51ff19e5d0619404596f8ab96267b3eb7d9b83f8bd376ea188db31e9704adb7e`。
相对基线新增6个源文件，只改5个既有产品文件及16份旧codec测试；所有旧fixture
和其它旧test字节保持。16份迁移只改最高版本、未来版本和排除新空字段，
15+7+6行改动单列；旧wire版本与独立旧encoder保持，七个[27]→[28]义务映射保留。
新增40个测试节点；新纳入的既有codec测试不算新增实现能力。

最终全部961身份唯一、无failure/error/skip。原catalog2135义务保留；上批231项
按显式未来版本迁移复验，其余直接相关codec/state-preservation一并纳入。未重跑
整个2135目录或全仓，独立encoder以旧源码执行的Program26字节比较通过。
独立只读复审无未决阻塞；最终checkpoint绑定全部首败、源码及文档，核精确case
集合与16文件28行的受限迁移，不把“旧测试改绿”代替原wire兼容证明。

961项具体分为：原catalog复验792、此次新纳入的既有codec等case129、真正新增40。
合并并应用七个明确ID迁移后，本系列已知相关义务目录为2304（不是全仓收集）；
其中未在本轮重跑的1343项
只保留此前证据，不声称当前版本已重跑通过。机器可读case-catalog明确标此边界。

## 3. 明确的能力范围

直接槽pre/post声明与实际端口支持是条件，不是已自动从任意源代码或 native
实现提取的事实。当前查询支持 ReferenceOwner 的一个直接单槽及有依据的Data
key；未知 owner、Reference key、范围/聚合、多级解引用与未展开自定义访问保持
准确边界。其原记录不删除，不将语义附件存在当运行时对应已验证。

实际 branch/loop visit/caller 用各自当前版本与来源；任意可能WRITE/RW/opaque
阻旧值，新明确post可重新建立来源。same-object 与数据内容恒定仍是两个问题。
新 query 尚未自动变成全部旧消费者的 copy recipe；[后续](M1_STORED_VALUE_NEXT_GATE.md)
先接准确 load 结果的通用需求桥，不为 async request/LeWM 写特例。

九族接受/七族开放、P4 component/full、P5、M2 原113构造/196字段保持原分母。
F19第1项/整族及第一阶段均未关闭；无新 detector/backend、可信自动 TRANSFORM、
LeWM-specific规则、完整自动建图或新的LeWM加速比。受保护仓库保持原HEAD/clean。
