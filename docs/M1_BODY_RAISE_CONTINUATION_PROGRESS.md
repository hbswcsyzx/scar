# 原主体异常、当前完成与消费者：连接进展

2026-10-19；基线 `753104593c67c0d0d1190288843eb0420ebcc072`。
[冻结计划与收据细化](M1_BODY_RAISE_CONTINUATION_PLAN.md)保留原字节；这是原 P4
的连接进展，完整 A–H、十六组、P5 和 M2 原113构造/196字段仍未完成。

## Implemented：把异常来源与当前完成分开

五类实体保持 Operation / Value / StateLocation / Region / Resource；不增加
Program23/Execution8 规范记录或改 codec，不另存第二套 producer、Use 或状态。

真实 BodyRaise 是提供的程序图中主体自己的 RAISE；它与获取失败、异常构造器
RAISE、提取 child 的 RAISE 不同。EXCEPTION 的原 key、DriveOutcomeRef 和
DriveResult 不变，conversion_legs 保空。同步 D 内显式 C1 可以保留原包，也可
Replace 成新 Raise/Return；根据当前终点接调用方自己的 kind/full result slot。
这些 BodyRaise 消费者不因此获得最终完成提取义务。

静态查询复用上一轮 continuation_rows/structured_completion，补 outcome 的
continuations/terminals 与 advance_legs alternatives。不是看见旧 root 不再复制
就将当前消费者排除；current=False 仍拒绝，未知仍保缺口。原包是否保留、当前
完成是否正确、当前状态是否交付是三个独立关系。

执行投影引用原 actual Drive、BodyDriveResult ordinal、landing formal 与准确
CallActivation，分开记录：

| 收据 | 证明的连接 |
| --- | --- |
| body_binding | 本次 B 终点 payload Use 的值→本次 DriveResult landing 值。 |
| root_binding | 该原 DriveResult 值→当前终点 payload。 |
| current_binding | 当前保留或替换来源→当前终点 payload。 |
| delivery_binding | 当前终点 payload→准确 parent 自己的结果端口。 |
| states | 当前 terminal State Uses→parent 同 location/full result slot。 |

W 仍与 B 不同，W getter、wrapper→D 调用和 B 的持续 activation 分开。缺关联、
缺 Use 或缺 dispatch 不借另一实例；源/native/runtime/value/transform authority
仍 False。上述是 supplied-model 的发生记录连接，不是自动恢复或 native capture。

## Observed：首红、修复与作者问题

证据目录：`artifacts/experiments/b1_call_operands/model_body_raise_continuations/`。
root 独占串行解释器执行；作者每次先冻结。失败、原命令、日志、JUnit 与前后
源码注册表分别保留，不覆盖历史结果。

- 首红0P/3F：三图均 core-valid。两个合法清理 Replace 被旧 BodyRaise
  protocol_copy 误拒；保留原包的旧消费者断言通过，仅缺新收据字段。
- 首次整合20P/2F：所有12个动态项目通过；两个 general 静态项目的新增测试
  只用 Drive/advance 选行，将 Get 与 qualification 两个原来源合并，错误要求
  唯一。该问题归新测试选择器，不为绿测去重产品库存。
- diagnostic-source-rows 实测两组零/两 cut：两行 source_operation、scope、
  branch choices 不同，独立声明的 details.source 各恰匹配一行。经独立审查，
  只允许新增 helper 补该精确 source 谓词，其他断言与两条库存都保留。

预算审查另发现：raw continuation 库存查完后，state/caller join 若截断，不能
把未查 parent 叫 NOT_APPLICABLE，也不能把已查前缀叫完整 leg。已实现对应的
PARTIAL/gap 传播。独立预算中段项目已实测：raw walker 完整但 caller join
未查完时，原键/cursor 保留，未查 parent 仍为 PARTIAL，不伪称不适用。

动态 DriveResult 的完整 slot 扫描也先按共享预算计费，不足时返回未知；该
计费修订发生在23P修复轮次之后，最终回归才对应其实际字节。三路独立复核的
发现、有限修复与冻结 SHA 见证据中的 `independent-review.md`。

## Verified：最终受影响回归

最终冻结运行 `verified-final`：**1716P/0F/0E/0skip**，pytest345.71s，
runner346.77130682300776s。837份源码在运行前后完全一致：

```text
fb1977d1991844de8738db6807d876e8d2d4e5c3939ddef4fe826c76996b28f3
```

其中1693项为上轮原 case identities，23项为本轮独立新增，不能用新计数
替代原验收分母。最终命令、stdout/stderr、JUnit 和源码前后清单均已单独归档；
旧失败/诊断未覆盖。11项静态检查与12项动态检查包括真实主体异常、同步清理
保留/替换、general/W 零/两 cut、两实例、精确来源、错包、opaque、缺采和预算。

归档验证器检查这些精确 identities、全部旧 tests/fixtures 字节、旧规范记录及
codec、前轮档案和两个受保护仓库的原 HEAD/status；不启动测试或 workload。
生成及封存后可在当前 worktree 的 lewm 环境重核：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python \
  artifacts/experiments/b1_call_operands/model_body_raise_continuations/checkpoint.py --check
```

这是 affected focused 回归，不是当前源码的全仓回归，不证明自动从 Python
恢复整张程序图、真实 native/GPU 采集、任何变换或性能收益。

## 原验收分母与下一步

完整例覆盖 self 实际两 cut BodyRaise 与 D 同步保留/新 Raise/新 Return，
general/W 的真实零/两 cut、明确来源、两实例和当前状态；另有错当前包、opaque、
缺采及预算边界。它们均为提供给 IR 的完整图/采集记录，不能称 LeWM 自动建图。

获取/lookup/资格失败、native/self direct-vs-await 的其余组合、共享 incoming、
重执行/刷新仍按原 A–H 推进，不以本轮例子关闭对应格。特别是 caller finally
Return 不会把原 acquisition RAISE 改成 acquisition NORMAL；资格拒绝控制源不
是 whole packet，后续必须连真实构造端口，不能按 TypeError 名称选包。

原十六组真齐后才组件/full、P5，再核 M2 原分母；完整 M0–M2 后先按用户要求
汇报模型。没有新增 detector/backend、LeWM 特例、重型 profiling 或加速结论。
归档与版本状态以同目录 `checkpoint.json` 及 Git 提交为准；原范围不因本轮
连接修复而缩小。下一完整单位先核获取/lookup/资格失败跨 caller C1 的当前
packet/state/consumer，再回原来源/共享 incoming/重执行组，不增加检测器。
