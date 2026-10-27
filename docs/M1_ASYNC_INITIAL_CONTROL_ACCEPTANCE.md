# 原 F16 条件性结构验收

2026-10-19。**PASS_WITH_SCOPE：原 F16 的条件性 M1 结构验收。**
最终相关回归 **2058 通过、0 失败/错误/跳过**，pytest 945.95 s；
892 文件前后稳定指纹为 `f8e32575b74ba5eec077c1f18f2da7fcbaf03f2443b1579c92a5e40e791bf990`。
原 2016 义务通过 2010 个精确身份和六项显式迁移保留，新增 42 项。
原始 JUnit、每次首败/差异源码和自动合账见
`artifacts/experiments/b1_call_operands/model_async_initial_control/checkpoint.json`；
该检查点的成功核验是本验收的边界。
原分母为 [family 计划](M1_PROTOCOL_FAMILY_PLAN.md) F16 和
[剩余计划](M1_REMAINING_PROTOCOL_PLAN.md) F16；不扩大为所有 async/native
实现已自动恢复。本门保原十六族、P5 与 M2 的 113 构造/196 字段。

## 原要求与证据入口

下列文件前缀为 `tests/unit/`；机器合账扩展实际参数身份，不能用一个函数名
代替该函数全部参数。已有项在最终相关回归中继续保留。

| 原 F16 条款 | 精确 selector / 关键条件 |
| --- | --- |
| 四种 request 来源和关联 | `test_program_async_connections.py::test_request_origin_projects_its_exact_create_body_and_latent_not_scheduler`：NEXT/SEND/THROW/CLOSE，原 Create/B/L，不混本次 S |
| 首次与后续交付 | 同文件 `test_first_request_uses_latent_normalization_normal_packet_and_keeps_failure_state`、`test_later_request_step_uses_current_scheduler_not_latent_payload`；`test_program_async_scheduler_packets.py::test_later_scheduler_packet_uses_s_normalization_own_normal_and_separate_raise_states`：准确 raw ordinal、normalizer own N/R 和全状态 |
| 首次 ASEND 联合控制 | `test_program_async_initial_control.py::test_initial_asend_joint_control_keeps_real_sources_targets_and_all_ports`：Created+None→Start，nonNone→无 Drive 的拒绝 own N/R，随后新 R 可启动同 B；ASYNC_YIELD 后新 R nonNone→Resume |
| 真实调用及当前端口 | `test_execution_async_initial_control.py::test_actual_initial_control_has_exact_request_body_current_states_and_continuation`：持续 B、独立 R、两实例、实际 bool/BRANCH、input/state、Start/Resume、own packet 和 host |
| S 覆盖 L、Unknown 不升级 | `test_program_async_initial_selection.py`：全部六项，含已知 S 覆盖 L、未知 S、association-state 失效、真实两 caller 已知/opaque RAW 库存完整而有效来源未知 |
| 完成后同 R 复用 | `test_program_async_completed_reuse.py::test_completed_request_reuses_exact_r_and_latest_states_then_rejects_without_a_second_drive`：最新全状态、同 R、第二调用无 Drive、独立 helper own N/R |
| 两 R 竞争同 B | `test_execution_async_competition.py::test_two_requests_reject_only_r2_then_resume_the_original_body_and_r1`：R2 完成自身不代表 B 空闲；R1 继续原 B；原缺采和预算反例保留 |
| 缺采/删除/错源/预算 | 本门新 control 静态/动态测试：错 B/ordinal/bool/有效输入、历史 callback、删附件仍保分母、本调用缺采不得借 sibling，budget1 不授已查前缀；自然 Return adapter 缺输入仍 UNPROVED |

## 结构身份和证明界线

五类实体仍为 Operation / Value / StateLocation / Region / Resource。
一个原操作、一次发生、Python 对象、逻辑值与物理副本不合并。
R.initial、B.Created、L、S、operand None、完整 current tuple 是不同依赖。
派生报告保存这些原依赖及同一 caller/CFG 的联合证明，不存新的可写真值。

普通 copy 查询与 Create/association 的意义不同。独立来源投影可支持一个
明确标注的条件性报告，普通 raw operand 报告仍为 None；不能从该报告推出
native 身份、纯性或缓存权限。未知有效 S、未知 caller、状态失效、预算截断
均不能因另一次已知报告变 True。

R3 原四项 opaque/write blockers 和主 HOLD→occupancy READ 的内容保持仍未知；
完整局部区间正例单独成立。原 F16 要求能表达并正确拒错，不要求把真实未知
翻成 preserved=True。详见 [原义务审查](M1_ASYNC_INITIAL_CONTROL_F16_AUDIT.md)。

## 范围与后续

本门验收依据实际 JUnit、稳定源码、六项精确旧 testcase 迁移、旧 fixture
字节和原义务守恒；源码独立审查不代替运行结果。Program26 只为已有 subject
的新 async 准入选择，原 1–25 wire 与 Execution8 保留。

本门按原 F16 接受后，累计八族条件性通过；不关闭 F18/F19/F20/F22/F24/X25/X26/X27、P4
component/full、P5、M2 或整个 M0–M2。手工供应图不是自动从 LeWM 恢复的图。
没有新 detector/backend、可信 LeWM 变换或加速比。
[下一门顺序](M1_ASYNC_INITIAL_CONTROL_NEXT_GATE.md) 保持先模型、再自动建图、
最后给具体化简指导；第一阶段完成后先停下向用户解释。
