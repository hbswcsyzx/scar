# Await完整单位：失败、终端结果与消费者

2026-10-19；基线 `2fc957192e710d1db1210c7b7a1073313f2e16d6`，已核工作树干净。
上一目标轮为PROGRESS：1437受影响定向通过、归档、commit/push及远端SHA已核。
本计划延续原D0/D1/D2的完整A–H，不将目标改为几个容易通过的helper。
原F12–F24/X25–X27十六组、P5及M2原113构造/196字段全部保留。

## 一、先核模型连接

五类实体仍为Operation / Value / StateLocation / Region / Resource。获取、
资格检查、推进、构造异常、提取结果都是原Operation；候选/iterator/B/W/whole
packet/最终值是原Value角色；依赖仍是owned Uses、state SSA和原控制边。
没有第二producer图、没有新可写phase/activation、没有检测器或优化backend。

当前公开await视图主要连到BodyDrive，尚未完整覆盖后半段：

```text
原source → acquisition/资格 → iterator → advance
  ├─ 中间Suspend → handoff/下一次resume
  ├─ BodyReturn → 原StopIteration适配NORMAL → whole packet
  │                                     → 本advance RAISE → 原最终提取/消费者
  └─ lookup/call/资格/构造/BodyRaise等异常 → 本次packet → 原传播/handler
```

构造自己的RAISE不是StopIteration完成；普通Reference异常对象不是whole packet。
合法失败不能因其值不合格而被整体误拒；不可达控制腿与实际发生相互区分。若
旧负例和原native检查的解释确有冲突，先记录真实证据并修改精确合同，不为了绿测
删除正常CFG、伪造producer或悄悄放宽旧断言。

## 二、四路工作与冻结执行

| 作者 | 当前任务与唯一写入范围 |
| --- | --- |
| root | 本计划/视图合同、公共IR查询与执行投影、串行测试、证据报告及版本管理。 |
| C | 新failure program/execution fixtures与两个tests；完整lookup/call/qualification失败，保所有原stage/slots/状态/正常CFG，先交真实首红。 |
| A | 先只读定义准确completion库存；合同冻结后写新outcome fixture/tests，不改旧resume图或产品。 |
| B | 独立对照原A–H审计已证/未证，反对性复核新合同、分母与真假异常；不执行。 |

子代理禁止Python/tests/probe/compile/commit。root执行前所有作者冻结；每次失败
保独立目录、命令、全日志、JUnit和前后源码指纹。复用上一1437，不拿历史5822
full归给当前字节；原16全齐后才组件/冻结全仓。不要重复native12/LeWM/GPU运行。

## 三、自主验收顺序

1. **R：真实语义缺口。** 原公开API+core有效失败路线，查各本次packet/state和
   消费者；新fixture/API错误与产品缺口分开。先查资格false腿目前是否漏掉。
2. **D：临时查询视图合同。** 原source/advance/BodyOutcome与consumer先派生库存，
   再左连接已有局部合同。删final adapter或consumer附件后key/count仍保留；不把
   任意RAISE强制解释为completion。只读审查后冻结，不新增wire/schema。
3. **P/X：完整后半链。** 真实零cut/多cut/持续B的BodyReturn、构造NORMAL与失败、
   原host/callee RAISE、准确caller packet/提取自己的N/R、state及最终consumer；
   再投影真实CallActivation/DriveExecution及selected transfers，缺采保持原库存。
4. **A–H：回到原整门。** 区分原三路、直接/await、多Create、W、whole tuple、
   全删stage/附件、fresh与预算1。预算不足不得把已查prefix叫原job总数；若实际
   暂不能枚举完整总数，必须明确未完成库存、pending与cursor，不能假装通过H。
5. **V/A：验收和版本。** 独立有限复审→作者冻结→所有受影响定向→保旧case和原
   fixtures/失败/合同/wire/保护目录→报告→commit/push与远端核对。所有原格未齐
   仍写OPEN，不把本门实现范围当作第一阶段完成定义。

证据根目录：`artifacts/experiments/b1_call_operands/model_await_outcomes/`。
保护 `/home/zyf/AAA/le-wm` 与 `/home/zyf/AAA/scar` 原HEAD/status；不改环境、
不写LeWM规则、不跑新profiling/benchmark，不产生新加速结论。
