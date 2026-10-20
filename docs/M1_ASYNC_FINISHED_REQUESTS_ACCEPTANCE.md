# F19第1批限定验收：原路径库存与finished请求子链

2026-10-20。**本批限定通过；F19第1项、F19整族和第一阶段均未完成。**
计划见[M1_ASYNC_CLOSE_CONTINUATIONS_PLAN.md](M1_ASYNC_CLOSE_CONTINUATIONS_PLAN.md)，
接口见[M1_ASYNC_FINISHED_REQUESTS_API.md](M1_ASYNC_FINISHED_REQUESTS_API.md)，
实际失败见[M1_ASYNC_FINISHED_REQUESTS_PROGRESS.md](M1_ASYNC_FINISHED_REQUESTS_PROGRESS.md)，
剩余任务见[M1_ASYNC_FINISHED_REQUESTS_NEXT_GATE.md](M1_ASYNC_FINISHED_REQUESTS_NEXT_GATE.md)。

## 实际改动

- 新增独立`ProgramIndex.request_no_drive_paths`：先准备原async接口/entry/R/S、
  操作、分支、INVOKE全部N/R槽、host及Drive库存，再按独立预算沿原CFG走到首
  host/Drive。cycle、预算或未展开控制不空成功；noDrive仅指所供本地Region。
- 原async报告只加廉价库存，不给旧共享预算增加CFG扫描。显式body角色投影
  不读取或追踪latent；已有StaticGap语义及整体关联PARTIAL保持。没有把字段
  名字、地址、类型或条件投影变成普通copy规则。
- 新所供片段复用真实async BodyReturn/BodyRaise和F，连接同B的新R、代表sameR
  retry、constructor own N/R、packet与host/caller全state。两处catch明确消费
  其本次packet并推进context；没有新B、实际Drive或body segment。
- 没有新核心实体、schema、detector/backend或LeWM特化；Program26/Execution8保留。

## 运行证据

root在`conda activate lewm`后独占串行执行；所有源码作者均FROZEN。
证据位于`artifacts/experiments/b1_call_operands/model_async_finished_requests/`：

| attempt | 实际结果 | 含义 |
| --- | --- | --- |
| original-inventory-counterexample | 4 FAIL | 新公开查询尚无入口；不是旧native推理误判。 |
| first-joint-authored | collection error 1，rc2 | pytest保留参数名request；没有执行联合case。 |
| initial-query-connected | 4 PASS | 同原图库存、N/R、当前全state、删附件、budget1。 |
| joint-current-context | 17 PASS，37.04秒 | 修复测试名及真实catch状态连接后的本批定向。 |
| verified-current | **196 PASS，156.50秒** | 19个直接受影响模块，179旧case及17新case。 |

最后两次同源：904文件指纹
`ec1969fbdbcd2d52029ada1005886ad01620a9e77812f637fa835756f71f1969`，
各次运行前后相同。wrapper最终157.3276秒；这些是测试耗时，不是程序性能数据。
所有命令、环境、stdout/stderr、JUnit、运行前后指纹和相对前一门的源码字节
差异都保留。独立只读复审核准最终源码及oracle，没有新结构阻断。

原899源文件中只修改两个production模块，新增一个production及四个fixture/test
文件。旧test/fixture字节不变，前一门2104身份目录保留；**本批没有重跑全部2104、
component或全仓**。新版独立预算不改变旧默认projection，直接消费者回归通过后
停止额外测试。

## Verified与不能扩大解释的结果

- own NORMAL异常对象→本packet、own RAISE wholepacket及全部state槽分别核验；
  错旧包由core-valid图的`source_binding=False`拒绝，错旧state由已有canonical
  `stale_state`拒绝。两者不是新增native语义证明。
- 真terminal/F、请求COMPLETE和body phase不同；新COMPLETE不种第二个F。
  本批没有新增release正例，不能称完整F19释放验收。
- 两实例的实际occurrences/CallActivation/segments互不借用；删一次call捕获只
  使本实例MISSING，原库存和完整兄弟保留。Program26已有codec roundtrip不造L。
- **Observed于所供capture查询**：分支True时`body_state_history.expected_bool`
  仍为None，并给`body_state_subject_unproved`；这验证了尚缺的同B/F历史桥，
  不能把观测True填成证明。非finished native支路未展开，native_cfg_complete=False。

## 下一步与原分母

Proposed：先消费现有原R/Create/association own B结果/当前state/实际occurrence，
补动态条件主体桥，再做graceful close的AWAIT/HOLD与两层回复、illegal yield后的
same/newR及finally续体。不得把桥实现为全局copy union或继续增加无关detector。

九族F12/F13/F14/F15/F16/F17/F18/F21/F23保持原条件性结构接受；七族
F19/F20/F22/F24/X25/X26/X27、P4 component/full、P5、M2原113/196继续开放。
本批是所供模型的结构与查询进展，不是自动拆解整个LeWM，不授source/native/
runtime身份或变换权限，没有新的LeWM A/B或加速比。两受保护仓库未修改。
