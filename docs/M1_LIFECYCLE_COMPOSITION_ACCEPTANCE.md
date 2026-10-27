# D2.4：清理组合与条件查询范围验收

2026-10-18；计划见 [M1_LIFECYCLE_COMPOSITION_PLAN.md](M1_LIFECYCLE_COMPOSITION_PLAN.md)。
实现提交：`37baeaf5e8be24a88e6524cba1b99c84cfb41808`。

## 1. 已实现、已验证

本门保留 Operation / Value / StateLocation / Region / Resource 的规范分解。
没有新增 producer、可修改事实表、优化规则或 wire schema；v14 保持不变。

| 连接 | 实际验收 |
| --- | --- |
| body 内清理→终结→driver | 真实 C1/C2B suspend/cleanup/invoke body 的 Return/Raise frontier，各自私有首 commit 后接 session/release；helper 的两条实际完成边均保留各自当前后态。 |
| driver 自身 active cleanup | 两条 body 终结分别构造 pending、准确 owner 与请求转发到共享 entry；Enter、窄 release、Resume 或真实 helper RAISE→fresh pending→独立 Replace+JUMP，精确 scope 直接归属。 |
| E/F/P 与状态 | 两来源的 F/T 合流保留；Enter 前 HOLD 合流后被未知清理写失效；内部 post 或 helper 的最终 NORMAL 可重建，RAISE 不冒授 post；Release/Resume/Replace 不保留旧 P。 |
| 拒绝反例 | 错 owner、owner phi 一支未完成、挂起伪终结、callback 后旧 post、旧状态、pending/context 进入不透明 helper 参数、借未来完成提前 release。 |
| 公开查询 | 新 frozen LifecycleScope/Position；point 携带原声明、interface/rule、原操作、BEFORE/AFTER 或真实 successor index。publication 携带该 point；脱离 Index 仍保留范围。 |
| CLI 与旧图 | v11 不补造 scope；v12/v13 准确报告显式条件推导及实际表计数；session/release 能力只按真实表。所有 applicability 为 UNKNOWN，native/runtime/transform 标志仍为 false。 |

Scope/Point 是普通只读 view，不是不可伪造证书，也不是外部可写的优化许可。
查询只接受已校验 ProgramGraph，并复用 validator 派生结果。实际 native-owner /
no-reset 条件、source/runtime 对应、物理 free/ready 仍需各自证据。

## 2. 真实验收结果

- 组件：**1,015 个不同测试 / 32 条标准 / 18.022s PASS**。
- clean 实现提交的唯一全仓：**4,050 PASS，0 FAIL / ERROR / SKIP**；外部
  457.655s，pytest 455.61s，峰值 RSS 1,029,216 KiB，三条警告。
- HEAD、全部 **451** 源文件与 **42** 份 fixture 运行前后一致。源指纹为
  `e0683fad9eae6a34b0dd781a9823921aac3d969372246498ff1a236e9605ed5d`。
- 原 **4,009** 个测试身份及 **38** 份 fixture 全部保留且未变，新增 **41** 个
  测试身份、4 份 fixture。定向、组件和全仓集合重叠，不相加为独立覆盖。
- v14 历史 golden 从不可变 `fdf9d0d` 的独立 archive 生成，86,374 bytes，SHA
  `982db4c507344979c1498b443f5296a9f196d0e6f6ca116e69c8caa621b047b3`。
  旧 v1–v13 继续原门严格兼容，公开 view 不写入规范 wire。

组件是在 dirty `fdf9d0d` 基线上运行；逐文件 hash 与 clean 实现及冻结全仓相同，
不伪报同一 HEAD。全仓期间没有编辑源码/文档或启动其他测试；独占 basetemp 已在
子进程结束后删除。LeWM 和主 SCAR checkout 均保持原提交、干净状态。

原始失败保留：root A 首轮 4P/3F、第二轮 5P/2F，均为测试 API 字段错误
（cleanup_replacements、block 查找和 BodyOutcomeSite.operation），在最终组件前
修正，没有放宽产品。审计初稿误写当前 dirty 范围及强制静态 ResourceInstance
位置，已另存初稿并修正文案，不把错误描述当观察事实。

独立只读审查分别覆盖 body 组合、driver cleanup 组合及 public/CLI，均绑定最终
文件 SHA。完整命令、环境、输出、JUnit、历史生成器、失败和修正见
[归档及只读校验器](../artifacts/experiments/b1_call_operands/model_lifecycle_composition/README.md)。
本门时间是验收成本，没有新 LeWM profiling、可信变换或 clean A/B 加速比。

## 3. 下一批有限任务

第一阶段仍未完成；完整分母见 [完成矩阵](FIRST_STAGE_COMPLETION_MATRIX.md)。
下一批先补资源 instance/generation→work→outcome→ready/consumer visibility 的
类型与连接，明确静态 ProgramGraph 与动态 realization 的不同层次，复用已有
StateAccess、allocation/materialization，不另建状态机。通用读文件→物化→提交计算
→等待→写文件→flush/close fixture 验收 host return 与资源完成不可混同。

随后补 typed owner/selector、完整 literal、occurrence→denotation/provenance；
将 D3 family 接口义务及 Python 113 构造/196 字段逐项连接到规范类型或明确协议
边界。真实源码自动恢复和运行时对应留 M3/M4，不要求先实现完整 native 编译器。
所有 M0–M2 类型/组合通过后按用户约定先停下来讲解；当前不增加 detector/backend。
