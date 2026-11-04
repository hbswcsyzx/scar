# 当前状态

**第一阶段未完成。按形式阶段 F0→F1→F2→F3→F4→F5→F6 顺序推进；声明材料的 F0/F1/F2 已验收。**
下一层只做 F3 作用域与名字绑定。已有后层局部代码保留，验收前不新增 F4 及后层规则。
阶段契约见 [ARCHITECTURE](ARCHITECTURE.md)，入口见 [DEVELOPMENT](DEVELOPMENT.md)。

## 已验收的形式输入层

范围是当前声明的866份源码，不是依赖发现完整性证明。

| 层 | 已核材料 | 结果 |
|---|---:|---|
| F0 bytes/编码 | 12,655,117原始bytes | 原文、SHA、编码结果与错误可fresh还原 |
| F1 token | 1,961,177个 | 全字段/exact_type、换行映射、gap、真实EOF与官方流相等 |
| F2 AST | 1,511,372个occurrence | 866/866 PARSED，从存表还原并fresh逐字段核验 |

F2全量重验155.21秒，8个spawn进程；866个语法分片共33,269,423压缩bytes。
官方schema有113个具体constructor、196个字段、288个属性槽；真实源码观察101种constructor。
339种合成结构形态核codec规则，不冒充parser实际覆盖；独立逐字段检查presence、引用、精确标量及None空洞。
四种mode及错误/预算出口已验；只执行官方ONLY_AST，没有执行LeWM、symtable或目标bytecode。
F0/F1/F2与持久性相关的20项检查通过（7.08秒），包括独立DTO/字段核对及发布故障注入。
F2是语法输入表，尚未授权绑定、效果、计算复用或图化简。旧ast.walk ID保持原样，不混作F2局部ID。

证据：`artifacts/current/queries/formal-frontend-f2/{verification/result.json,recovery/,file/result.json}`。
F0/F1历史核验在各自`formal-frontend-f0/f1/`；F2此次fresh同时重新核了其全部源输入。
原F2采集报告在恢复后为空，完整采集耗时已丢失，不能补写；这里报告的是重验耗时。

## 中断恢复与当前存储

恢复后原manifest、F2报告及2个F2分片为空；后两片已从保存的F0/F1重新生成。
从原866-unit basis恢复核心清单：13,108个核心分片、2,310,613,691压缩bytes的长度/SHA全部匹配。
36,706个原lexical entry与36,706个body entry_key逐项一致；原端点、字段、顺序和8,829个body artifact引用保留。
原manifest的附加统计、计划和CALL/class发布元数据未精确恢复；7,117个相关材料保留为owned材料，未冒称原发布范围恢复。
原source-scan前沿摘要也未恢复，不能把缺失当成remaining为空。恢复摘要使用机械计数，原耗时不猜填。
F0/F1/F2发布已补文件/目录/manifest fsync、完整报告发布及故障边界检查；两次目录rename仍有可恢复窗口。

当前24,264个压缩分片、2,579,129,690 bytes，包含材料、诊断、局部图及保留关系，不能全部计为实现图。
核心body状态：局部图8,098；未尝试23,645；入口适配缺失4,200；不支持326；形状不支持437。
恢复后`eval.py`词法查询正常；独立还原其1,063个F2 occurrence与官方AST一致。
当前manifest与fresh核验时manifest的差异只涉及恢复显示元数据，源单位和分片收据完全相同；
`recovery/query-metadata-bridge.json`逐项限定差异，`run.json`记录当前与核验时的SHA。

## 下一层与整个第一阶段缺口

1. **F3绑定**：固定官方symtable/profile；按constructor×field识别每个名字来源和角色，
   保存完整scope/symbol/namespace链，再建立AST occurrence到scope的可验证对应；不能用(name,line)猜唯一身份。
2. **F4规范IR**：逐语法类别/上下文验收控制、状态、效果与完成端口；已有局部图不证明规则闭合。
3. **F5/F6**：补跨子图、native/runtime/kernel、资源和数据来源连接；恢复保留关系的发布范围，重新核查依赖发现前沿。

LeWM仍是外部testcase。先前CEM probe只有人工quadratic cost、2轮×4候选的局部运行证据；
它不证明完整episode、当前形式前端之后的层已通过，也没有LeWM加速比结论。
