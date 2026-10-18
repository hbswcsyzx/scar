# D2.2：只读检查、真实分支与无 body 完成

2026-10-18。合同：[D2.0](M1_DRIVER_LIFECYCLE_CONTRACT.md) §4。
本组件仍属 M1 类型与组合，不推进自动 source lowering 或优化。

## 1. 目标与规范连接

两个声明表引用现有 Operation/Use/Value/CFG，不创建第二套数据流。
`CreatedCloseTest` 是读取 L 每个域当前版本的只读普通操作，自有一个
`builtins.bool` 结果，紧邻使用这个结果的 BRANCH。core 既有约定：
edge 0 为 true，edge 1 为 false。

仅显式 `NoBodyFinish` 声明触发“真实 true edge → 私有 landing 首 mark”的
义务；只有检查、没有 mark 的图合法，也不产生完成事实。mark 的 owner
直接取仍支配该点的原 B，或从该 true edge 的独立实际 Use 精确复制。
mark 的实际写集必须非空且包含于 L，使用当前 before，结果恰是实际 after。
未写域、D 中非 L 的域沿原控制边保留当前版本。

BODY 固定 B/S，E 为同一个 S 的独立 Use。ASYNC_REQUEST 固定 R/S，B/E
有真实来源，true 合同包含当前关联及 step 检查；不强迫独立 AssociationRead，
也不把可能返回 false 的关联错配误报为图类型错误。真实 AssociationRead 的
NORMAL/RAISE 与结果投影仍按 D1 校验。最终准入 gate → 唯一 BodyDrive 的
私有 NORMAL 路径保持；新检查在 gate 之前，false 沿原 gate/Drive 执行。

## 2. 自主验收顺序

1. exact records/角色冲突、真实图正反例、query/codec/CLI 分别定向检查，保留失败。
2. 独立只读审查：精确 owner/role/current-state、分支连接及声明/运行时边界。
3. `gates/m1_no_body.json`：本组件四项标准及先前十七项标准，绑定全部源 hash。
4. 冻结 clean implementation commit，再启动一次全仓回归；期间不编辑或另跑测试。
5. 核对测试身份、历史 fixture、源/HEAD 前后相等及保护仓库；保存报告并推送。

v12 golden 从不可变 `e86563a` 的独立 git archive 生成，禁止用当前 v13 codec
生成历史期望。旧 schema 不接受两个新表，即使为空；新能力才使用 v13。
fixture helper 如为组合 ASYNC 图抽出，单独列出其已授权字节变化，不能声称所有
旧 fixture 均未变；旧 JSON wire 必须保持字节完全相等。

## 3. 当前状态与边界

组件首次验收 **836 项 / 21 标准 / 12.709s PASS**，430 个源文件指纹前后一致。
图定向 43 项、wire/query/CLI 定向 45 项通过，record 定向 7 项通过；这些与组件
重叠，不能累加为独立测试。旧 v12 样本 69,273 bytes，来自不可变 `e86563a`。
冻结实现 `006a0e06a1f5739cec4948c690a382fc191f1af8` 的唯一全仓回归
**3,871 PASS / 0 FAIL / 0 ERROR / 0 SKIP**；外部用时 463.982s，pytest 462.05s，
峰值 RSS 1,028,088 KiB，三条警告。运行前后 clean HEAD、全部 430 源 hash、
35 份 fixture hash 一致；保留全部旧 3,776 项身份，新增 95 项。
此前 32 份 fixture 中只有明确授权抽取 helper 的 `program_publication_graphs.py`
变化；所有旧 JSON wire 不变，当前原 factory 也与独立历史 v12 字节相等。
原 LeWM 及主 SCAR checkout 均未修改；本次独占 basetemp 已在子进程结束后删除。

最终独立有界源码复审与组件绑定同一个源指纹
`48c08626b5921f0adf08f57298738097c6d0ed0349f8efc08274813e63c93ebc`。
复审不是另一次测试；定向/组件/全仓不是可累加的独立测试集合。组件在 dirty
旧基线上采集，以逐文件 hash 与随后 clean 实现闭合，不伪报成同一 HEAD。
原始记录测试断言失败、fixture 缺 bool 定义失败及其源码快照、编辑命令缺 conda
的 shell 失败均保存。普通 UseID 子类与 branch unknown-effects 两处约束由源码
审查发现后修正，再由定向和冻结回归验证，没有虚构修改前的实测。

[完整证据及校验器](../artifacts/experiments/b1_call_operands/model_no_body/README.md)
保留命令、报告、JUnit、历史生成与每文件 SHA。以上时间均为验收成本。
native 真值、纯性、真实字段、no-reset、guard 执行和 source/runtime 对应仍未证；
通过声明校验不授权变换。SessionUpdate、TerminalFrameRelease、E/F/P 分析、
D3、完整 C2 和第一阶段 M0–M2 均未完成。本组件不产生 LeWM 加速比。
