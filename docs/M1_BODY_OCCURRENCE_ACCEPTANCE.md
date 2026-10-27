# P3：持续执行实例与原端口关联验收

2026-10-18。结论：**PASS_WITH_SCOPE_P3_BODY_OCCURRENCE**。
关闭[父计划](M1_PROTOCOL_FAMILY_PLAN.md)中P3的声明发生关联门；P4/P5、D3、
原M2构造及完整M0–M2未完成。不是任意程序或LeWM已自动建图的声明。

## 1. 实际补齐的模型关系

规范实体仍为Operation、Value、StateLocation、Region、Resource。原producer/
ordered Uses、状态SSA与CFG不复制；两张自然键关联表引用原动态坐标：
`BodyDriveExecution`和`BodyActivationOrigin`。

```text
实际Create NORMAL handle / 明确外部来源
  → 原copy/call传递及本次owner
  → 同一持续body activation的多次Drive
  → 准确InitialEntry或旧Suspend→ResumeIngress→新segment
  → saved/capture与本次delivered/current-state分别绑定
  → 本次实际路径上的首Suspend/Return/Raise
  → 原Drive selected edge、输出/forward及host消费者
```

一个activation可跨多次Drive和线程片段；本次已知driver/entry/outcome仍分别
核线程、进程、region和代次。实际分支前缀不能被静态可达的其他出口替换。
entry和completion的conditional host桥独立建立，再与原CALL/局部链联合查
occurrence因果环，不对activation强制DAG。

身份检查逐原binding及相关中间copy边进行。Create H(A)→formal X(B)→owner
Y(A)不能因两端相同而通过。全部已捕获Create的真实NORMAL handle都进入
派生来源索引，不要求另有origin row。不同任意producer root则不推数值不等。
Data不同版本、跨artifact身份和缺采保准确缺口，不冒充native identity证明。

公开detached/fresh query与只读CLI保原recipe、缺口、共享预算和cursor；
截断返回未检查项，不伪装成功。Execution8只在新增能力出现时自动选择，旧
v1–v7及其字节保留；显式空v8可往返，不迫使旧图升级。

## 2. 观察、修复与拒绝

| 状态 | 实际结论 |
| --- | --- |
| Observed | 独立反例复现中间copy冲突漏检，以及无origin关联的已捕获Create来源冲突漏检；各自先失败后修复，原记录保留。 |
| Implemented | 一次准备的原copy索引与选中ancestor closure；全部实际NORMAL Create handle索引；fresh逐binding兼容及条件host桥。 |
| Observed | 首次冻结`61db593`为5,816通过/6失败，668源稳定。失败是遗漏的旧future8和最高Execution7断言；原full仍FAIL。 |
| Implemented | 修复只改三个测试文件和组件选择，产品零改动；89原case并入组件。旧自动v5/v7精确字节、显式v8及future9/bool/string分别验证。 |
| Verified | 独立只读复审无本轮阻断；255定向、606组件/18标准及修复冻结5,822全仓全部通过。 |
| Rejected | 同类型/同code当同实例、只看copy两端、缺关联就删除分母、缺采洗成成功、把原失败full改PASS或把声明相容当变换许可。 |
| Proposed | 按[P4详细计划](M1_REMAINING_PROTOCOL_PLAN.md)接await/coroutine、async request/session/cancel、委托/C1的原生产者—消费者。尚未实施。 |

精确类型、端口、复杂度、query及CLI见[API](M1_BODY_OCCURRENCE_API.md)，
逐项O01–O16见[计划](M1_BODY_OCCURRENCE_PLAN.md)，原失败与局部检查见
[实施记录](M1_BODY_OCCURRENCE_PROGRESS.md)和[修复门](M1_BODY_OCCURRENCE_REPAIR.md)。

## 3. 实测证据与版本

证据根：`artifacts/experiments/b1_call_operands/model_body_occurrence/`。
检查有重叠，不累加为模型覆盖率。耗时是验收成本，不是工作负载benchmark。

| 检查 | 实际结果 | 原记录 |
| --- | --- | --- |
| 首轮最终定向/组件 | 166通过；517通过/18标准 | `final-focused/attempt005`、`component/attempt003` |
| 首次冻结完整回归 | 5,816通过/6失败，562.467s，1,030,792 KiB | `full`，实现`61db593`；原FAIL不覆盖 |
| 修复受影响文件 | 89通过/3.03s | `repair/affected-codecs/attempt001` |
| 修复最终定向 | 255通过/17.29s | `repair/final-focused/attempt001` |
| 修复组件 | 606通过/18标准/23.852s | `repair/component/attempt001` |
| 修复冻结完整回归 | **5,822通过、0失败/error/skip，5 warnings** | `repair/full`；pytest561.54s，外部563.710s，峰值1,029,520 KiB |

修复冻结提交：`81389862ee3f1dfe88c59f74ca1bfeff732779ff`。
668注册源前后及最终定向/组件指纹一致：
`b16a1bac16f134c69133f2b0f88a1c291fa0029f9714e95693ae0bdec233f3d4`。
完整回归期间所有作者停写、无并行SCAR测试或工作负载；driver只清理自己
创建且子进程已结束的basetemp。两次完整回归有独立命令、环境、JUnit、case、
时间/RSS、源码前后快照与manifest。

归档核对原P2的5,676与首次full的5,822个case身份、92个旧/99个当前fixtures，
以及668个注册源。原`/home/zyf/AAA/le-wm`与`/home/zyf/AAA/scar`保持原HEAD和clean。
只读重放命令：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python \
  artifacts/experiments/b1_call_operands/model_body_occurrence/archive.py --check
```

它启动零测试/工作负载，核当前验收版本与归档守恒，不重复运行完整回归。

## 4. 仍未完成

1. P4原F12–F24/X25–X27组合和P5完整ledger/公共面，不能因已有enum/clause算完成。
2. 原113构造/196字段的M2规则及完整M0–M2总验收；满足后先向用户讲解模型。
3. 自动source/runtime/provider恢复及真实值、对象、物理资源对应仍属后续建图阶段。
4. 本轮未新增detector/backend、LeWM业务规则或重型profiling；**没有新的LeWM
   自动变换或可信clean A/B加速比**。source_runtime、value_identity及
   transformation_authorized仍为False。
