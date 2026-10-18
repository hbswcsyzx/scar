# M1 S：状态地址接口验收

日期：2026-10-18。**限定门通过，完整第一阶段未完成。**
按 [计划](M1_STATE_ADDRESS_PLAN.md) 的 S0–S5 自主验收；
[接口](M1_STATE_ADDRESS_INTERFACES.md) 解释规范记录、原端口和预算。

## 1. 实际证据

| 项目 | Observed / Verified |
| --- | --- |
| 实现版本 | 干净 `805c670a12ea15cf12b32395180c8fcd954beda2` |
| 最终组件 | 25 criteria，1,317 个独立 case，全部通过，44.578s |
| 唯一冻结全仓 | 5,144 passed，0 failed/error/skipped，5 warnings |
| 全仓成本 | 外部 wall 516.7538779713213s；pytest 514.59s；peak RSS 1,026,572 KiB |
| 源指纹 | 590 files，`b0a340543b4015b903196f1cb5f0ffe202d864a57e56382ef674896310c95ef1`，前后相同 |
| 守恒 | 原 5,055 case 身份、72 fixtures 全部保留；新增 89 case，当前 74 fixtures |
| 旧源码 | 578 全保留，566 hash 不变，12 扩展，另新增 12 个登记文件 |
| 环境 | conda lewm；Python 3.14.7，pytest 9.1.1，Torch 2.13.0+cu132，NumPy 2.5.2 |
| 保护 | LeWM `f70fed8`、主 SCAR `84f165f` 均原 HEAD/干净；未修改环境 |

全仓只运行一次；所有代理提前停止写入，运行期间未修改源码、文档、报告或并行
运行 SCAR 测试/profiler。使用与前门同 SHA 的 full driver
`9a28d3b043e12484e099d9794478399ceccaf24e42dd6643c535e7cee2de9b28`。
子进程终止后仅移除这次 driver 独占 basetemp。测得时间是验收成本，不是 workload
benchmark；未测共享服务器外部负载。没有新增 LeWM trace 或加速比。

## 2. 自主节点结论

| 节点 | 交付及结论 |
| --- | --- |
| S0 | 三份原设计审查、既有工具/源码证据和明确合同；literal 保留为下一独立门。 |
| S1 | records/validator；owner/key 引用原 Uses，mode/envelope/carrier/current 与原图一致；15 定向通过。 |
| S2 | Program wire v15、v1–v14 守恒、静态原端口 query；45 定向通过。 |
| S3 | 确切 occurrence/activation/visit、实际 completion、独立 forward capture、资源绑定和预算；29 定向通过。 |
| S4 | 有限独立复审 PASS_WITH_SCOPE；1,317 组件通过；干净提交后唯一全仓 5,144 通过。 |
| S5 | 本报告、失败历史、保护、逐文件指纹和旧 case/fixture 守恒；归档 manifest 和只读 checker。 |

新增 89 case=15+45+29；不同定向 attempt 不累加为覆盖。联合组件含旧协议、六处
schema 常量更新与前门 17 条原标准，合计 25 条。本门没有用未携带新地址声明的
旧测试代替 branch/selector/ContentRead 新组合；独立报告 D01–D10 逐项映射了它们。

## 3. 保留的原失败、推断与修正

原始 attempt 日志全部留存，成功终态没有覆盖失败证据。

- S1 attempt001–002 的 fixture/import 构造问题及后续 mode/duplicate-carrier/
  resource-ancestor 校验修正，详见 `address_records/report.md` 与五次原日志。
- S2 attempt001 为 44P/1F：forwarded state 测试保留了未使用的 produced completion
  slot。原 validator 正确拒绝；只修测试 signature/结果索引。attempt003 最终 45P。
- S3 attempt001 为 15P/1F，同类测试构造错误；修正后 16P，加入 stale/missing-forward
  后 19P，补三项组合分母后 29P。未放宽旧 completion/ContentRead 守卫。
- 复审起初将原 reference 解释为多 owner 的 anchor；冻结合同确定它仍是 summary
  envelope，真正多 owner 用 reference=None。INVOKE ORDER 的设计假设被原
  STATE_CONTENT 规则反证，保持原规则。两项均保留修订历史。
- UseID 子类的完整动态 capture 兼容性推断已撤回：原 strict UseOccurrence 不接受
  这种完整构造。未把它写成已复现产品 bug；实际可达的 missing forwarded capture
  有独立 gap 和反例。canonical isinstance 检查保留原键，不新增子类采集适配器。
- cached diff check 记录两处新 unit 文件 EOF 空行提示；未为纯格式改动改变通过组件
  的源码或重新测试。实现源在冻结 full 前后完全相同。

旧六测试只机械调整当前最高 schema15；生命周期历史 proof/schema14 保留单独
断言。全部旧 golden bytes/hash 和 semantic 断言保留，不重生成旧 fixture。

## 4. 通过的范围与未完成范围

**Implemented / Verified：** owner/selector 地址声明连接原 StateAccess 或 INVOKE
state operand。多地址/模式/stage、六种 selector、分支 owner/key、粗细两向 current、
NORMAL/RAISE/forward completion、loop/call/resumption、resource access 与原
ContentRead guard 有真实模型组合。原状态 carrier 是唯一一致性链；新声明不造
before/after、Value、producer 或另一条 field SSA。查询保留原未知、部分及截断。

**未证明：** 地址路径的 Python/native 真实含义、共享 cell/外部 NumPy 写等完整
alias、与物理 Mat/字节的全部对应、完整源/运行捕获。call 正例是 DataUse 路由，
不是已经观察到真实共享 cell。原 alias 草案 20 机制不是 20 个新 runtime PASS。
DECLARED_COMPLETE 不升级 effects_complete、identity、pure、ready 或变换权限。
预算只覆盖动态 joins；准备/校验/快照和 copy 成本另列，不能声称整个查询有同一
严格 CPU 预算。

**下一阶段 Proposed：** 复用 PythonLiteral，补 complex/精确 bits/大小预算，接 core
wire 与明确来源阶段；payload 相等不证明 object identity。之后继续 C2/D3 与 M2
原构造分母。compile-only literal probe 编译 15 片段，没有执行样例或代替测试。
不新增 detector/backend；没有自动 LeWM 化简或新的性能结论。

## 5. 机器记录与重放

归档目录：
`artifacts/experiments/b1_call_operands/model_state_locations/`。
含原 design/probe、三实现方 reports/原 attempts、独立 review、component/final、
full 原 stdout/stderr/JUnit/逐 case/time-v/source/manifest、protected.before/after、
preservation、closure 和总 manifest。

归档只读校验，不启动任何测试/工作负载：

```bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python artifacts/experiments/b1_call_operands/model_state_locations/check_archive.py
```

原组件入口：`scripts/run_gate.py gates/m1_state_addresses.json --out <fresh-report>`。
full 原命令及唯一运行环境在 full/command.json；此验收不要求重复执行 full。
归档 commit 的父链包含上述冻结实现提交。第一阶段完成时先停下来向用户讲解的
边界保持；当前未到该点。
