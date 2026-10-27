# 活动 session、竞争请求与状态保持：实际进度

2026-10-19。基线 `f22d64196d2f706c66e99f7acb4bcffa8373a98c`。
本门落实[冻结计划](M1_ASYNC_SESSION_OWNERSHIP_PLAN.md) O0–O5；
[版本测试迁移补充](M1_ASYNC_SESSION_OWNERSHIP_CODEC_MIGRATION.md)明确旧义务如何保留。

## 1. 建模含义

核心实体仍是 **Operation / Value / StateLocation / Region / Resource**。
图中边和端口分别传递值、状态版本、控制选择及资源关系，不由名字决定身份。
这次补足的是如下关系，而不是增加优化检测规则：

- B 是持续存在的 body，R1/R2 是指向它的独立请求；不同 CreateID 本身不是对象不相等的证明。
- body 的 frame phase、活动 session、request initial/complete 是三个不同的问题。
- `SessionOccupancyCondition(body_use, state_sites)` 只标记原 READ 的主体和依赖；
  不保存 truth、holder、额外可写状态，也不把占用塞进 frame phase。
- `HOLD(R1,B)` 可以支持 B 有活动 session。`COMPLETE(R2,B)` 不能推出 B 空闲、
  R1 完成或旧 HOLD 的内容始终未变。
- READ 的 own bool、BRANCH、实际 caller 选择、逻辑来源和状态保持各有独立证据。
  观察到 True 不会反向证明它读取了正确主体，也不单独授权拒绝所有请求。

本轮供图包含：CreateB → CreateR1/CreateR2 → R1 首次 AWAIT/HOLD →
R2 initial/occupancy 检查 → R2 自己 COMPLETE → 错误 helper own NORMAL/RAISE →
caller catch → R1 第二次 AWAIT/HOLD → R1 ASYNC_YIELD/COMPLETE。
每个实例只有一个持久 body activation、三个 body segments、四个 driver calls；
R2 没有虚构的 Drive 或 body segment。

## 2. Observed：原生行为

本机 `conda activate lewm`，Python 3.14.7；未安装或升级环境。
`native-probe.json` 保存命令、解释器、脚本和源码 SHA、12 条观察。
CPython 3.14 原实现仅作参考：[genobject.c](https://raw.githubusercontent.com/python/cpython/3.14/Objects/genobject.c)。

首次原生实验错误地断言 inspect 状态必为 SUSPENDED，真实失败脚本和错误记录保留。
该首次失败没有完整源码快照和事后指纹，档案明确这一限制，未补造。
修正实验分别读取 `ag_suspended`、`ag_running`、`ag_await` 与 inspect 结果：
await 期间 suspended 与 active-session 可以同时为 True；inspect 先检查 running，
不能作为两个概念的独立分类器。R2 竞争失败后关闭，R1 仍可继续到下一 await 和 item；
R1 完成后重新使用该 R2 仍失败。初始非 None ASEND 失败则 body 仍 Created。

这些是一次本机运行的事实，未证明自动源码恢复、所有 Python 实现或优化合法性。

## 3. Implemented：连接、查询与编码

1. 拆开普通 predicate shape 校验和主体校验。request 条件不再借 body proxy；
   原 wrong-request、bool、READ、普通操作限制仍保留。
2. 静态 occupancy view 从原 RequestCreate/association/own NORMAL 端口定位 B；
   原 marker 定义库存，删除可选声明不会删除待证义务。所有调用上下文共同核对，
   不把不同 caller 的路径选择强迫为同一路径。
3. `ExecutionIndex.session_occupancy_history(read, budget=4096)` 复用已有 post/current
   input/support/preservation 引擎。源 HOLD 的确切 occurrence、原 BEFORE 输入、
   完整 call ancestry 和 read state 都必须存在；不能借另一实例或未来 Drive。
4. request→body 投影使用独立条件性 receipt。普通 identity/copy 的 Unknown 原样保留，
   不合并 ObjectID，也不把来源相同当作状态内容不变。
5. Program 最大版本升为 24，新 tag 只允许新能力图；旧 1–23 无能力图保持原 wire。
   Execution8 schema 不变。15 个旧测试文件只允许已冻结的 18 处字面量迁移，
   1903 个旧精确节点和 4 个显式未来版本节点迁移共同保留原 1907 项义务。

## 4. 真实失败及处理

所有 pytest attempt 均保存命令、环境、JUnit、日志、前后源码图、相对旧基线的
准确源码字节。失败档案不被后续修复替换。

| attempt | 实际结果 | 原因与处理 |
| --- | --- | --- |
| first-authored | 41 fail / 7 pass | RAW 结果被错误建为普通 READ 新值；改为真实 native INVOKE 的 own NORMAL/RAISE，不假装 NEXT pack。新 codec header 测试补齐其真实升级字段 |
| corrected-native-getter | 4 fail / 44 pass | 2 个静态正例将三域 association tuple 接到只读一域的 READ；2 个负例在已验证非法后仍试图构造 ProgramIndex |
| slot-budget-counterexample | 1 fail | 共享预算已耗尽后，own NORMAL 仍线性扫描 result slots；复用已有计费 `_result`，耗尽返回 None |
| corrected-branch-and-r2-post | 49 pass，110.10 s | 上述修复及 R2 拒绝前真实 COMPLETE 全部通过；前后 878 源码指纹一致 |
| verified-final | 1956 pass，843.96 s | 冻结源码上的全部相关选择；原 1907 项义务和 49 新项由 checkpoint 按身份核对 |

完整 association state tuple 应核对原 BRANCH 的真实全部 D 端口；READ 的真实单域依赖
独立保留，另核 READ→BRANCH 连接。禁止裁掉另外两个域或伪造 READ state 输入。
非法图负例继续核对 exact validation code，并要求公开 ProgramIndex 构造同样拒绝。

## 5. 尚未解决的模型精度问题

主路径的来源关系可以条件性连接，但 HOLD→另一调用内部 READ 的完整内容保持
仍然 Unknown。当前 `state_preservation` 在进入/退出已知 callee 时还核对整个
parent INVOKE 的效果摘要：区间开始前的真实写入、终点之后的真实状态写入也会
阻断当前局部区间；真实 primitive getter 的未展开效果仍另有阻断。

同一调用内从 HOLD 之后到后续 READ 的完整小区间可作为正例；它不证明跨调用
主路径。不能把整个 caller 改成纯函数，不能删除 opaque 标签，不能用捕获的 bool
替代证明。下一门先审查效果摘要、边界效果和已展开 child prefix/suffix 的关系。

## 6. 验收边界

| 节点 | 当前验收依据 | 不能推出 |
| --- | --- | --- |
| O0 | 原合同审读、原生首次失败及修正后的 12 条观察、冻结计划 | 所有实现适用或自动 lowering |
| O1 | 新静态 6 项与 codec 27 项定向通过；原 READ/BRANCH/完整 tuple | native gate 自动成立 |
| O2 | 新竞争 7 项通过：R2 COMPLETE、own N/R/fullstate、R1 原体继续 | R2 完成后 B 空闲 |
| O3 | 新动态 9 项通过；local 区间 True、主路径 Unknown、缺输入/预算反例 | 来源投影等于状态保持 |
| O4 | 原 opaque 主路径仍未知；原 R3 四阻断未翻纯 | F16 整族验收或优化授权 |
| O5 | 1956 相关项全部通过，原身份/精确迁移/失败字节由 checkpoint 核对并版本存档 | component/full/P5/M2 已完成 |

**Verified：**1956 项相关测试通过，无 fail/error/skip；pytest 843.96 s，
wrapper 845.0898442976177 s。新增 49 项分布为静态 6、codec 27、竞争 7、动态 9。
保留原 1907 项义务：1903 个精确 testcase 身份未变，4 个 future-version 用例明确
从 `[24]` 迁到 `[25]`；不宣称全部旧精确身份都未变。

878 源码文件前后稳定，SHA：
`63a594d1f531658c5dda743ef87bfaf89973785c7e5c245ba9c1ae05fb17afc8`。
`verified-final` 保存命令、conda/Python、选择器、JUnit 和前后完整源码图；
`checkpoint.py --write/--check` 核对准确 18 处迁移、旧测试其余字节、旧档案、
所有失败时的源码快照、原生观察限制和受保护仓库 HEAD/status，不启动测试。

F16 整族仍 OPEN：原初始 ASEND 联合控制、跨调用精确效果和旧 R3 四个阻断未闭合。
原 16 族分母、已接受的七族、A–H、P4/P5/M2 原 113 构造/196 字段范围保持。
本门没有新增 backend/detector，没有自动恢复整个 LeWM，没有新 TRANSFORM 或加速比。

档案：`artifacts/experiments/b1_call_operands/model_async_session_ownership/`。
