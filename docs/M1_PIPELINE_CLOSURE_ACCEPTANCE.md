# R3.3 验收：跨调用顺序、独立端点范围与完整 buffered 流水线

状态：**Implemented / Verified（以下限定范围）**。日期：2026-10-18。
[计划](M1_PIPELINE_CLOSURE_PLAN.md)、[接口](M1_PIPELINE_CLOSURE_API.md)。
基线 `bccefcfb65dcdba71c050cbbecadd3b2f30f3fa2`；冻结实现 `6947778571ac08fdaddd0259713b9c6b38b8823b`。
这关闭本计划 R3.3 的声明模型/OS 见证分母，不关闭完整 M0–M2。

## 1. 实际交付与模型关系

规范实体仍为 Operation、Value、StateLocation、Region、Resource；输入/输出是
端口角色，计算/读写/表示/搬运/等待是可组合行为。没有增加 ExecutionModel 表、
wire 版本、detector、backend、lowerer 或 LeWM 名称规则。

- 原 CallActivation 与实际 CFG 派生同步 host 入口/完成桥，保留 caller/child
  activation、首规范操作、RETURN/RAISE 和实际 taken EDGE。缺捕获不补 NORMAL，
  同 activation 仍走原快速路径；不连接 host return 到 WorkEnd。
- 固定、版本化、最多 4096-byte 的 endpoint byte profile 复用原 FactRef 和精确
  ExternalSnapshots。READ、WRITE_REQUEST、WRITE_ACTUAL 独立定义范围；读取8、
  请求8、实际4不能缩成读取4。未知协议、非零offset、非法/缺失payload有明确诊断。
- source 由 writer-owned 原 Data Use/ContentRead、denotation/version、storage Mat
  与 byte geometry 连接。Endpoint consumer 与 writer 必须准确同 target、同 Mat；
  同逻辑版本不允许混用另一个物化，RegionRef 与 endpoint区间不互送几何算法。
- 同一 ProgramGraph/ExecutionModel 内连接 root、workflow、load/prepare/run/save/
  close：7 Regions/activations、6 calls、68静态操作、39动态操作、10 reads、8 raw
  rows、8 writes、2真正异步work。静态未执行分支保留接口，动态不伪造其执行。
- buffered write先产出独立CPU buffer Mat，close读取buffer再经flush原Data Use/
  ContentRead建立file endpoint贡献。缺flush、提前观察和部分flush均有反例。
  未save路径使用empty版本/shape0/capacity8，不伪造requested8/actual0字节写。
- submit后RAISE真正跳过wait/consume；partial、pending、cleanup、close新异常
  替换旧完成沿原接口连接。host完成、work outcome、quiescence、borrow release、
  handle end、target retirement和persistence仍分别描述。

这些是可校验的声明连接；条件MATCHED/COVERED不证明runtime/native对应或许可变换。

## 2. 真实 OS 观测与限制

新脚本在专属临时目录/子进程内运行，父进程十秒总超时、等待worker退出后清理。
三个pytest cases及另外三次CLI原始JSON捕获分别保留；后者不是额外三个测试用例。

| 见证 | Observed | 未证明 |
| --- | --- | --- |
| file | BufferedWriter接收8，flush前同fd pread看到0，flush后看到8；fsync返回、close成功。 | 跨open/process可见性、断电耐久性、GPU或自动IR绑定。 |
| file_raise | save返回后外层HostFailure；finally close成功，最终8字节，未执行显式flush/fsync。 | close自身失败；close返回等于持久化。 |
| pending_raise | host抛异常时worker未完成且buffer仍0；随后显式放行，部分写4/8后失败，this memoryview release被观察到。 | syscall短写、全部alias释放、allocation空闲或GPU quiescence。 |

旧nonblocking-pipe真实短写见证继续纳入组件。新worker的4/8是memoryview assignment，
不能冒充write syscall返回短写。超时kill分支只做源码审查，正常退出的三个用例没有
实测超时分支。OS raw count/hash/journal与手工IR各有归属，未伪造automatic correspondence。
脚本仅保存小字节样例的hash/count，不记录每次Tensor全值。

## 3. 共同验收与版本

| 节点 | 实际结果 |
| --- | --- |
| 独立审查 | 三项P0源审，host-order root审查、OS见证源审、端点有限审查和fixture交叉审查；初OPEN和窄关闭记录保留。 |
| 新用例 | host order15、endpoint15、同图pipeline11、真实OS3，共44个独立case；focused重跑不重复计数。 |
| 首轮共同组件 | **720P/2F**，原unsupported endpoint诊断丢失；报告原样保留于component/attempt001。 |
| 最终共同组件 | **722 cases /17 criteria /33.458s**，全部通过且源码指纹不变。 |
| 唯一冻结全仓 | **5,055P/0F/0ERROR/0SKIP，5 warnings**；pytest499.15s，外部501.338949418s。 |
| 资源与指纹 | 峰值RSS **1,028,008 KiB**；578 registered source前后相同，SHA `5505a09ae2327f792cc69e7695c052c23a9bad9c72627855e0d3c658065407e6`。 |
| 守恒 | 原5,011 case全部保留；原69 fixture哈希全部不变，当前72。原567 source全部保留，557未改、10扩展、11新增。 |
| 保护与清理 | LeWM原仓与SCAR主工作区HEAD/status前后相同且干净；只清理driver自己的basetemp，且在child退出之后。 |

所有Python均使用现有conda lewm（Python3.14.7、pytest9.1.1、Torch2.13.0+cu132、
NumPy2.5.2）；没有安装/升级环境。full之前先共同组件和干净实现提交；full期间无
源码/文档/报告编辑、无并行SCAR测试或profiler；本SCAR作业内仅原driver与测试
子进程，未测量服务器其它任务的负载。
这是验收耗时，不是工作负载性能数据。

## 4. 原失败、审查修正和实际限制

原始stdout/stderr/JUnit/source前后指纹保留在
`artifacts/experiments/b1_call_operands/model_pipeline_closure/`：

- call_order_compat首轮38P/1F，修为保留局部O(1)顺序快路；随后54项通过，
  默认4096未改；不是扩大默认预算让断言通过。
- fixture早期分类、外部资源scope、Reference read effect、预算期待错误分别保留。
  首完整矩阵为7个产品mixed-geometry异常、3个fixture错误、1通过，不隐藏成全模型有效。
- root审查使初版unbuffered改成buffer→flush→file、run晚抛异常改成submit后真实早分支、
  未save路径改成empty身份；早期成功结果不能代表后来的完整语义。
- endpoint负例先用了storage Mat，随后又跨artifact/误指Host结果；失败保留，最终只换
  同artifact/同逻辑版本内另一个合法EndpointMat。Work的实际selector另由原Outcome验证。
- 两项source-inferred阻断是Work actual_selector转接丢失、区间标签组合未计预算；
  均有最小修复和有限反例/旧正例。未知协议诊断回归由首共同组件真实复现并修复。

最终全仓JUnit的原property提取为`pipeline-budget.final.json`：正常完整查询使用
**115,996/131,072**，未截断；历史attempt002的115,848保持原样，不能当作最终成本。
主要成本仍为host_order_edges72,892、host_order_nodes13,475；这是明确的查询成本
限制，没有优化或声称加速。默认4096不变，完整程序/Q/source分母与截断游标仍保留。
准备/FK/snapshot/replay/detach成本另列，不能将derived budget当成总运行成本。

## 5. 未关闭的原分母与下一步

**第一阶段未完成，自动LeWM建图/化简未完成，没有新的实测加速比。**

1. 完善StateLocation owner/selector、namespace/object/cell/元素与粗细域冲突规则；
   coarse world可以保守表示，不能宣称精确字段/alias已经恢复。
2. 补全literal严格表示、identity/定义阶段与无损wire；继续C2.0/C2.4/D3原接口义务。
3. 按M2原113 AST构造/196字段分母逐条核对phase、依赖、效果、完成及反例，做组合
   守恒验收；测试总数不等于完整性百分比。
4. 完整M0–M2通过后按用户要求先停下讲解，再推进现成前端/运行工具的自动映射。
   Q facet目标/基数、native/coherence、source/runtime/physical身份、其它endpoint协议
   都保留准确边界，不因本门通过填成安全或transform许可。

[工具复用决定](MODELING_REUSE_DECISION.md)和[完整分母](FIRST_STAGE_COMPLETION_MATRIX.md)
继续约束后续工作，不新增detector/backend或以重型LeWM trace代替模型缺口。
