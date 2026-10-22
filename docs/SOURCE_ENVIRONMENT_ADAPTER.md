# 自动函数环境接线：第一阶段 S3 子项

2026-10-22。状态：实施中；不构成完整程序验收。

## 问题与边界

同一份 function code 可对应不同 function object、globals、saved builtins、
defaults 和 closure cells。现有源 body 只接受显式形参和 world，遇 freevar
整段回滚；普通 global 读也缺少实际 namespace owner。不能删除拒绝条件后
把 freevar 当成 global，也不能根据同 code 合并闭包。

本项复用既有 EnvironmentInterface、FunctionEntryLayout、ReferenceValue、
StateVersionValue 和 StateAddressRefinement。没有新的环境图或 producer 表。

## 源码如何机械恢复

1. 固定源码 snapshot；AST 定位函数的完整来源和 qualified scope。
2. 只编译、不执行目标；由 compiler 得到准确的 co_freevars/co_cellvars 顺序，
   与 symtable 分类核对。保留可 pickle 的普通布局，不在 context 缓存 CodeType。
3. 新 profile STRUCTURED_ENV_V1 的入口依次为五个固定环境角色、captured cells、
   显式形参和 coarse world。新 SourceProgram4 / inventory8；旧 v3/v7 不改义。
4. 普通 local 仍用原绑定协议；free/nonlocal 使用入口 cell reference；本地
   cell 在每次调用中 MAKE_CELL，不能冒充 captured input。global/builtin 使用
   globals 优先、saved builtins 后备的明确协议；Global/Nonlocal 是编译期声明。
5. cell/namespace 访问连接本操作自己的 owner/key Use 和既有 world 的 PARTIAL
   地址细化；不宣称精确完整 effects、独立状态域或 alias 排除。LOOKUP_GLOBAL
   两个地址是可能读集，不能称每次真的读取了两个 namespace。
6. 查询、创建和存储保留正常/异常完成及各自后态。空 cell 不编码为 None；
   free cell 与 local cell 的空值错误不同。frame 协议保留环境和本地 cell 引用。

## 静态与动态不能混为一个验收

本项入口端口只声明源函数需要哪些环境，不证明真实 invocation 的 actual。
旧 CALL 原档不包含 globals/defaults/cell 身份，不能由 f_locals 追补。后续采集
应在 dispatch 观测 exact function 的环境，保留观测阶段，另核 entry 对应。
不弱引用的 cell/namespace 可由仍存活 function 的不可重绑 association 锚定；
可重绑 defaults 不能用 function 加裸地址证明跨时身份。不得强引用留住目标对象。
cell 身份连续也不证明 contents 不变，双次观测相等也不排除中间 ABA。

## 本项验收节点

| 节点 | 自动输入与交付 | 必须检查 |
| --- | --- | --- |
| E1 入口与源布局 | 普通 Python 源文件 → compiler layout/typed body | 顺序、formal/captured/own cell 分离；不执行目标 |
| E2 读写与失败 | local/free/global、共享捕获、写入、global/nonlocal 声明 | owner/key、正常/异常后态、frame 持有；错误接线必须拒绝 |
| E3 公共入口与历史兼容 | model-program/inventory-program environment；旧 frame/structured | v4/v8 精确版本；原始源码重建验证；旧产物不重释 |
| E4 真实回归 | 原 LeWM 入口/raw calls/151 文件/256 body 尝试/10000 op 预算 | 新旧分母一致；逐个旧环境失败的下一阻塞点，不能预期 +45 body |

E1–E4 的通过不等于真实环境 actual 已闭合，更不等于 S4 全程序通过。
运行身份、逻辑来源、OS/CUDA 资源、ready 与输出生命周期继续按第一阶段合同验收。
本项不新增 detector/backend，也不进行优化或性能 A/B。

## 实际断点后的扩展（2026-10-22）

同 scope 全量环境接线得到54个局部图。随后只针对新产物中实际失败的66个写入、
15个BoolOp、9个IfExp自动回查31个源码文件，不重复全仓测试。90个body中37个
成功展开、53个继续显式拒绝，无构造错误；这是诊断 cohort，不是新全量inventory。

Attribute/Subscript store 把 RHS、receiver、key 的求值/持有顺序和失败后态接入
原world；旧 computational overlay 没有目标子表达式时，只接受原SG中唯一来源
的Name/scalar leaf，不伪造旧StaticValue。复杂缺失子表达式和解构仍待补。

条件表达式使用原CFG的路径和有序Uses；值上下文返回选中对象，条件上下文直接
传bool，避免短路结果再次truth。普通frame/structured profile仍走原步骤；新ENV
实现的复现绑定产品commit，历史产物须用其记录的commit复建，不能把不同adapter
版本的exact-replay差异冒充源码变化或已证明等价。

再按原inventory自动选出8个AnnAssign、11个Raise、5个Assert：19文件/24body，
4个成功、20个继续拒绝、0错误，60.15秒。已补函数内注解的准确求值边界、异常/
cause归一化及assert失败分支；12个随后遇JoinedStr、6个遇Dict、2个遇其它写。
这仍是独立诊断范围，不作为全量程序或effects/资源闭包验收。


## 2026-10-22：实际dispatch环境sidecar

`trace --call-operands`同时采集function-environments.<pid>.jsonl及独立v1清单。
CALL记录exact function、globals、saved builtins、defaults/kwdefaults与有序cells；
ENTRY记录已有精确handshake下function/globals/builtins关联。非weak对象仅以仍活
只读function owner字段is核对续身份；owner全失效则新代次，不能用裸地址续接。
默认值只作事件内snapshot，不保存内容；原operand v1不重释、不改变其权威字段。
事件/字节/单行和live-anchor预算有界，累计重复引用计数不消耗live表容量。
见[一次实际CPU采集](../artifacts/experiments/first_stage_callable_environment_20261022/README.md)。
尚需真实LeWM采集及source interface实际对应；字段存在不等于完整环境已证明。


公共`link-operands --environments-out <fresh.json.gz>`可在同次source/call/operand分析
中导入实际环境；API `link_call_operands(..., include_environments=True)`返回独立
`report.environments`。原v1 operand wire不变，环境文件绑定原inventory digest与完整
原档manifests。新adapter不额外重建source或重读全部frame，保持原验证范围。
structured/ENV返回值使用真实FRAME_EXIT/RETURN配对；formal由显式slot/value
连接，环境前缀不会平移Python显式实参索引。defaults仍为dispatch snapshot，
细状态、完整环境和内容/效果权威均为False。
