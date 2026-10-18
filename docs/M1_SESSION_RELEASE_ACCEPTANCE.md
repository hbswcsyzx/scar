# D2.3：会话后态与终态 frame 引用放弃

2026-10-18。计划及验收节点见 [M1_SESSION_RELEASE_PLAN.md](M1_SESSION_RELEASE_PLAN.md)，
规范为 [D2 冻结合同](M1_DRIVER_LIFECYCLE_CONTRACT.md) §5–6。

## 1. 实现范围

- 两种 SessionUpdate 绑定：callback-free 普通元数据 after 与真实未知 helper 最终
  NORMAL。RAISE 保留实际部分后态，不承诺 post 未发生，也不承诺它仍成立。
- 同一终态对象的引用 must-equality E、历史 F 与解释来源 T；先固定 E/F，再求 T。
  每条实际边同时改名后再 must 合流，结果定义忘记旧 incarnation；unknown callback
  不在固定 no-reset 合同内撤销终态历史。Suspend 不种 F。
- 当前有序 `(R,B,post)` 谓词 P、current L 支持及解释来源；同样先固定 Boolean P
  再求来源。COMPLETE 蕴含 ABANDON；缺一路支持就不派生对应谓词。普通未知效果/
  callback/body/gate 使 P 失效；body-only publication 仅重基已有 P。
- TerminalFrameRelease 以本点准确 owner 的 F 为前提，使用 D 每域当前状态并产生
  真实 after；固定 FrameRules，不承诺仍持有、释放成功、对象 free 或资源 ready。
  两次实际尝试不消费 F，不自动判冗余。宽 raising helper 保留原 INVOKE。
- 原 producer/Use/state/CFG 仍各一处规范来源。公开查询复用 validator 的派生结果，
  返回原端口及当前支持。新 capability 使用 v14；旧 v1–v13 保持字节及边界。

精确 R/B/owner reference 继续由既有 core 的 target/selector/alias 规则验证，
lifecycle 标签不补 alias 证明。早期审查附件的 coarse-only 建议没有进入最终主
合同；实现按主合同保留这些合法表示，原附件和源审修正记录不删除。

## 2. 已有实测与待验收

records 定向最终27项通过；wire40项首轮通过；terminal flow分批8项、14项、
4项 selected通过（重叠，不算26个独立用例，最终文件18项）。当前 P 定向6项通过，
图分批18项及2项 precision通过，query/CLI13项首轮通过，真实合流/loop/rebase
组合14项首轮通过。统一组件门 **974项 / 27标准 / 15.967s PASS**，443源文件hash
在运行前后不变；所有新增义务和旧D2.2/D1/core回归均已映射。冻结 clean 实现
`f67037d632b093e68f26eb0c2fab34767878651c` 的唯一全仓回归 **4,009 PASS /
0 FAIL / 0 ERROR / 0 SKIP**。外部 468.490s，pytest 466.57s，峰值 RSS
1,030,312 KiB，三条警告。HEAD、全部443源及38fixture运行前后一致；原35份fixture
全部未变，原3,871个测试身份全部保留，新增138个。独占basetemp在子进程结束后
删除，原LeWM和主SCAR checkout均未修改。

组件在dirty `817cc0b` 基线上采集，逐文件hash与后来clean实现完整一致，不伪报
成同一HEAD；所有定向、组件、全仓集合重叠，不累加为独立测试。最终源指纹
`23e4c97fc75b7ea889c964fb77a5eada6b617ab94e9a3b308d617f16af340596`
同时绑定独立交叉源码复审及冻结回归。复审不算另一次测试，也不算native证明。
[完整归档与只读校验器](../artifacts/experiments/b1_call_operands/model_session_release/README.md)
保留命令、版本、原输出、JUnit、失败/修正与每文件SHA。时间仅是验收成本。

原始失败保留：records破坏性测试共享default污染、P测试误用strict_subset参数；
均为测试隔离/假设错误，不能冒充产品拒绝或新模型发现。源码审查修复的 reference
限制和 CompletionSuccessor 注解均未伪报成修改前实测。root提出的跨region literal
假设已被既有 core 的 cross_region_use 反证，未据此改动模型。

v13 历史 golden 来自不可变 `817cc0b` 的独立 git archive，89,825 bytes，SHA
`b833f028476a379e4c178fcfc7ad33d5dfebf2f7423df51593c871589139e6b6`。
不是用当前 v14 codec 自制的期望。当前原 factory 与该 payload 也字节相等。

## 3. 未关闭范围

E/F/P 是声明合同内的机械派生，不是实际 native 条件、字段、guard/纯性、对象
generation 或 source/runtime 对应的证明。D2.4组合/公开范围复核、D3、完整C2及
整个第一阶段M0–M2仍未完成。没有新lowerer、detector/backend或LeWM性能实验，
没有新增可信变换或clean A/B加速比。
