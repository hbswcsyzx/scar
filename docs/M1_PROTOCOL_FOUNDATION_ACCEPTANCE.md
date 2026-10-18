# P2 协议连接基础验收

2026-10-18。[范围](M1_PROTOCOL_FOUNDATION.md)、[父计划](M1_PROTOCOL_FAMILY_PLAN.md)。
本门是 P2 内部的部分检查点；完整 16 格矩阵、P3–P5、D3 和 M0–M2 仍未完成。

## 已完成的定向与组件检查

- 统一定向：155 passed，pytest 5.78s，外部 6.468s。
- 组件：334 cases /11 criteria，10.178s，PASS，无空匹配或跳过。
- 两轮均绑定 617 个注册源码文件；测试前后哈希不变。
- 组件及本轮定向的源码指纹：
  `e3234d73e5025c13f41bc7a873a5a71387ad2fb22b16fc70f97414d47c60ec79`。
- 原 78 个 fixtures 将与冻结全仓结果逐个核对；当前 82 个，新增 v16 golden/
  proof 及两份通用 supplied-model fixture。

## 独立复核与修订

新检查覆盖 raw ordinal 的真正来源、本次 producer 的结果、显式 packet 组件、
准确 body payload、N/R adapter 输出到 host、无 body 路线及原 F/P/release。
发现并补强了遗漏已知 lifecycle domain、可能循环却只判断出口可达，以及用
无关 RAISE 节点冒充本次 adapter 输出的情况。旧 wire 最大能力断言升至17，
各历史图自身的 v10–v16 版本、golden 内容和 case identities 保持原要求。

首轮统一定向 153 passed /1 failed。root 新测试误把非 lifecycle 的 context
域当成必需 lifecycle 域；仅修测试，补正反例后第二轮通过。审计中相同归因已
撤回。已知未写域可沿原 state SSA 保持当前值，不强制每个域都写出新版本。
各早期 records/codec/连接/ledger 的测试构造失败和环境启动失败均保留原记录。

独立 path-safety 的早期 9 passed 未捕获完整源码哈希，只作为开发观察；当前
验收由统一定向及组件绑定。部分原始记录的来源限制不得因后来通过而删除。

## 冻结全仓与归档

实现提交后仅执行一次完整回归；当前尚未执行，不预先授予本门最终 PASS。
完成后在本节记录真实 revision、原 case/fixture 守恒、保护目录和只读归档核验。
证据位置：`artifacts/experiments/b1_call_operands/model_protocol_implementation/`。

## 权限与剩余范围

Program17 是声明接口能力；Execution 仍为7。source inventory、native/source
适用、实际实例与持续 body activation 仍未证明，也没有 transformation 授权。
模型能表示这些端口与缺口，不等于已经从任意程序自动恢复了它们。
下一步仍按父计划完成 P2 全矩阵，再进入 P3–P5，最后核 M2 原分母。
本门没有新增 backend、LeWM 特殊规则、重型 profiling 或加速比。
