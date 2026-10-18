# R0：资源执行关系合同验收

2026-10-18；基线 `309fb359be8665fc90979f270a6d4e4d20c6eb85`。
**本门通过关系设计审查及六个有断言的真实 CPU/OS 见证；R1/R2 产品尚未实现。**

## 1. 收敛的模型关系

[关系合同](M1_RESOURCE_EXECUTION_CONTRACT.md) SHA256：
`74a606fca89ecb94ad9a04f77d8ad41706bcdacb10210352ccad185272993729`。
[实施与验收计划](M1_RESOURCE_EXECUTION_PLAN.md)规定 R1 身份/实例、R2 work/ready、
R3 全生命周期组合；exact records/wire 在相应实现门冻结。

- ProgramGraph 保持唯一静态 producer/Use/state；新 occurrence 层区分 activation、
  segment、block visit、operation/value/use/access，显式对应旧 EEG，不能靠 ID 改名。
- Run/process/thread incarnation、resource lifetime、native handle slot、event record、
  ticket 和 queue prefix 分开；window/clock/raw fd/address 不作为这些身份的替代。
  allocation/process/thread 已有身份由 tagged ResourceTarget 复用，不复制 registry。
- Resource requirement 的入口身份绑定与每次访问的当前条件分开。Object handle、
  native descriptor、隐式资源选择及未知关联各有端口，不伪造 ObjectID/ValueOccurrence。
- Work 与 host completion 分开；普通 Access 和 INVOKE 的真实 state input/completion
  分开引用。opaque call 内提交后再 RAISE 可保留工作及部分状态，不强移到 call after。
- Ready 可由完成可见或精确有序消费支持。多个必要贡献 AND、每贡献替代解释 OR，
  允许混合；known failure 缺内容不能仅靠 order 补出；retention/quiescence/free 另验。
- Storage/Endpoint/Unresolved placement、core consumer/外部观察根及 Host/Queue/Endpoint
  visibility 分开；文件不造假内存 allocation，region=None 不自动等于文件。

这些关系可以表达通用加载→物化→提交→消费→保存流程；不宣称已自动恢复该流程，
也不表示已有 resource generation、value denotation、native ready 或优化授权产品。

## 2. Observed：真实小程序结果

使用 `conda activate lewm`，CPython 3.14.7、Linux、本进程独占临时文件和线程。
六项全部带断言，统一脚本一次运行 exit 0：

| 见证 | 实际结果 |
| --- | --- |
| dup / 不同 open / close | 首 handle 读 `01`，dup 接着读 `23`，独立 open 读 `01`；关闭首 handle 后 dup 仍读 `45`。 |
| descriptor 数字再用 | 原 fd=3 已关闭；同整数的新 lifetime 读到另一个文件的 `new`。 |
| 同路径 replace | 已打开旧资源读 `012`，同路径新 open 读 `rep`；路径文字不变。 |
| buffered write / flush / fsync | write 返回3时独立读为空，flush 后可读3字节，fsync 正常返回。未测试掉电持久性。 |
| submit / 部分写后失败 | submit 正常返回 future；worker 已写但未结束，cancel-running 返回 false；之后 worker 失败、result 抛异常，写入保留。 |
| queued cancellation | 未执行的 queued future 可取消；done=true、cancelled=true，result 抛 CancelledError，没有执行目标函数。 |

这里**没有**实测 enqueue 调用自身提交后再 RAISE；该情景通过 core INVOKE 约束和
端口反审纳入模型。CPU future 见证也不是 GPU/stream/event 或 SCAR 产品验证。
所有独占临时文件已删除，没有修改共享数据或原 LeWM 环境。

## 3. 审查修正与证据强度

三位独立代理分别审查现身份、work/ready、代码复用边界，再对合同反审并绑定最终
SHA。原候选 SHA、问题与关闭说明保留。实质修正包括：INVOKE 无普通 StateAccess、
调用内提交点、跨线程恢复 segment、artifact 命名域、native descriptor/implicit
resource 端口、外部观察根与非内存物化。它们是设计缺口，没有虚报为产品运行失败。

官方协议与本机安装源/header 交叉核对：CUDA header 的 CUDART_VERSION=13020，
本机 torch 2.13.0+cu132。线上 stable PyTorch 页面已标2.14，不冒称本机版本；若干
固定版本页面访问 cache miss 已记录，使用本机源 SHA 作版本锚。没有 GPU 实验。

[归档](../artifacts/experiments/b1_call_operands/model_resource_execution_design/README.md)
保存精确命令、断言脚本、原输出、版本、源 SHA、审查和 root 决定。生产代码、现有
测试/gate 与已验收 D2.4 的451文件指纹相同；本轮没有重新跑全仓，也不把之前
4,050通过改称本门产品验收。

## 4. 下一步

按 R1 实现 execution bundle 的精确发生/Use/state 外键、资源 lifetime/realization、
requirement 与 handle/resource-access bindings；复用现严格 codec，不改变旧 core
和 v2 含义。先做通用双调用/循环、dup/open、复用 fd、隐式 queue、回调改状态等
正反图，再做 R2 work/order/ready 和 R3 保存流程组合。缺失对应保留准确义务。

完整 M0–M2 仍未完成，未增加 detector/backend、LeWM 变换或新的加速比。
