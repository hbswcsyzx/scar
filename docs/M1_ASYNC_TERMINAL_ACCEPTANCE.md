# 原 F18 条件性结构验收

2026-10-20。**最终同源 affected 回归通过；仅原 F18 supplied-model 条件性结构验收。**

## 验收边界

核心仍为 Operation / Value / StateLocation / Region / Resource；没有新枚举、
profile、codec或wire。Program26/Execution8保持；旧测试/fixture字节不变。
本门只核原 F18 的自然完成、主动终止异常、源级非法 return 及其真实消费者连接。
不授自动全程序恢复、native适用、值/对象身份、变换或性能结论。

## 原条款与证据

| 原义务 | 原操作和端口的连接 | 验证入口 |
| --- | --- | --- |
| 自然完成不同于主动 Stop* | 原 BodyReturn 的 None 来源、constructor own N/R、current state、host；可选 session consumer 不能隐藏非None return | 已有 async initial control 的 yielded-new-nonNone-resume 及新 inventory 单元 |
| 主动 StopIteration/StopAsyncIteration | body frame内 matcher bool/branch→constructor own N/R→cause/context 状态写→真实 BodyRaise→Drive→host | program/execution async terminal 四route |
| 普通异常与 constructor 自身失败 | 普通异常保原 wholepacket，构造失败保自身 packet/fullstate，不把旧包当新值 | ordinary、constructor-raise 正例与准确来源反例 |
| 后继 helper 异常优先 | 静态以原CFG选边、动态以actual visit取最后 own RAISE；独立于 SessionUpdate，旧包可用也不可冒当前包 | inventory 单/双 helper、反ID排序当前/旧包正反 |
| 源级语法不伪运行图 | snapshot hash/版本/编码/namespace；Return表达式库存；CPython只编译，不import/exec | source_compilation 22项；独立五source/四offset/三type-comment观察 |
| 缺采/删除/预算 | 保原source/consumer分母，准确instance/ports；缺兄弟不能借，预算只给未查/cursor | 静态删除/budget、动态四局部缺采/budget、源级budget |

native-probe22条调用和两编译观察只负责纠正建模前提；pinned源码哈希只锚声明，
不等于真实模型对应已经重放。所有 supplied-model 权限标志仍false。

## 实际失败与修复

[过程报告](M1_ASYNC_TERMINAL_PROGRESS.md)和档案保存首红、作者构图错误、compiler
定位错误、type-comment metadata与语言合法性差别、原body与later-helper来源
混淆、canonical ID顺序与实际CFG顺序混淆，以及静动候选集合不一致。
没有删除红记录或把未执行的检查写成通过。

最终 verified-current 实测 **2104 PASS，0 FAIL/ERROR/SKIP**：原2058精确身份全部
保留，新46 = 7库存/来源 + 8静态 + 22源编译 + 9动态。899源前后稳定指纹
`37dfff022d371ee43a66e24d481e09c4b6933a81230e51eb540c1fbabfd2faa8`。
pytest 962.891s，wrapper 963.982687s。
Program26/Execution8及所有旧test/fixture字节保持，无旧case身份迁移。
机器归档 original-acceptance/checkpoint 逐条核原要求、所有实际尝试和独立审查。

## 整体阶段

F18 最终同源验收通过，原九族条件性接受，F19及另六族仍开放；P4完整组件/
冻结full/P5/M2原113/196保持未完成。完整 M0–M2 与自动 LeWM 建模尚未完成，
无新 backend、LeWM 变换或加速比。[下一原门](M1_ASYNC_TERMINAL_NEXT_GATE.md)。

源编译 query 未执行所分析目标模块；native-probe 的22次自建fixture实际调用
单独归属。Observed 是本机返回/编译结果，Implemented 是本轮原端口连接，Verified
仅限上述同源结构用例。Rejected 的建模前提和所有首败均保留；未提出新的优化结论。
