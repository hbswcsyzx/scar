# C2D.0 引用生命周期与释放阶段：语言见证复审

2026-10-18；产品基线 `012db08`。只读产品/docs/tests，专属 ignored 目录四文件；
没有改产品、环境或共享文档，没有 import Torch/SCAR，没有 full/LeWM/GPU。
依据旧 `driver-field-contract.md`、`driver-root-review.md` 及已验收的 C2B 合同。

## 1. 对 FrameRelease 排序的回答

**对所测 CPython3.14.7 的终结 frame 清理，Detach/标记完成之后、host 返回之前
保留一个释放阶段是合理的；它不是所有引用释放的统一位置，也不保证对象在此最终化。**

已有源码支持这个次序：`clear_gen_frame` 先设置 cleared 状态并恢复 caller exception
chain，再处理 frame 引用；`RETURN_VALUE` 清理后才交回结果。它们是版本化实现
合同，不是 Python 全实现的时序保证。[ceval.c:1835–1846](https://github.com/python/cpython/blob/v3.14.7/Python/ceval.c#L1835)，
[bytecodes.c:1101–1114](https://github.com/python/cpython/blob/v3.14.7/Python/bytecodes.c#L1101)。

必须区别：

1. **body 中放弃一个引用**：覆盖、`del`、临时值/求值栈消费可在 Attached 时触发回调，
   不能统统后移到 FrameRelease；本轮第5组已观察并断言 body context/RUNNING。
2. **实例终结/清理 frame 所有权**：body 逻辑完成、context Detach、生命周期标记、
   最终 frame clear 是不同步骤。所测终结 finalizer 已看见 GEN_CLOSED，不能把完成
   标记延到 finalizer 之后，否则重入的 next 会错误地报“运行中”。
3. **对象实际最终化**：还取决于其他拥有者。第2组中 traceback 在 host except 内
   真实保留 local；gen 已 CLOSED，但目标仍活，到 handler 结束才运行 finalizer。
   Frame clear 可转移给存活 frame object，而非立即丢弃其 locals，见
   [frame.c:99–119](https://github.com/python/cpython/blob/v3.14.7/Python/frame.c#L99)。

因此旧提案“先 FINISH_BODY，再 FrameRelease”的**阶段分开可以保留**；需把
FrameRelease 合同收紧为放弃/转移当前 owner 的 frame 引用、保留所有当前效果，
不能授予“所有目标已 free/finalize、callback 已发生、资源 ready”。Created-close
还须无 body 入口而有绑定引用释放；源码单独处理该路径。
[genobject.c:358–365](https://github.com/python/cpython/blob/v3.14.7/Objects/genobject.c#L358)。

如果实际 collector 把 `next()` 整体当一个 opaque INVOKE，该 call 的 completion
已经包含其中 finalizer 的写。内部阶段应展开/关联这**同一个 call**；不能再执行
一个真实 FrameRelease 或在状态/性能里重复计算其 effects。此为接口映射要求，
不是本轮已实现 native expansion。

## 2. 实际命令和终态

```bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 python artifacts/experiments/b1_call_operands/model_driver_interfaces/review/lifecycle-witness.py
```

CPython `3.14.7 | packaged by conda-forge | (main, Sep 2 2026) [GCC 15.3.0]`。
**首次且仅一次运行：8组断言通过、0失败、exit 0**。JSON 的 attempts 保留真实
首跑，log 保留逐组原样输出；未反复试到通过。`torch_imported=0, scar_imported=0`。

事件字段仅 str/int；没有在结果中存对象、exception、traceback 或 frame，没有使用
`f_locals`/`get*locals`、profiling/monitoring、GC强制回收。被测对象的 harness 只留
weakref，creator 函数 scope 退出后才检查 Created-close；异常 case 仅依赖 Python
自己持有的 active exception/traceback，未额外存它们。临时 unraisablehook 在 finally
恢复，没有保留 hook args/object/exception。观察本身不是零开销：inspect 查询
某些状态会触及 frame 属性，但不保存其对象；结果只主张这个有界 harness。

## 3. 八组结果（Observed + 指定断言）

| 组 | 主要断言与真实事件 |
| --- | --- |
| normal_return | body Return 前处于 BodyContext/GEN_RUNNING；随后 `__del__`、weakref callback 都在 CallerContext/GEN_CLOSED；均早于 host 收到 exhaustion。 |
| exceptional_escape | host 捕获 BodyFailure 时 gen 已 CLOSED，目标仍活；handler 结束后才 del/weak；回调见 CallerContext。验证 frame 清理不等于所有局部对象已死。 |
| close_with_finally | body finally 见 GeneratorExit/GEN_RUNNING；终结 del/weak 见 CallerContext/GEN_CLOSED，早于 close 返回。 |
| created_close | 原 creator scope 已退出；未执行 body，close 仍释放已绑定参数，del 见 CallerContext/GEN_CLOSED。 |
| overwrite_and_delete | 两次放弃局部引用都在 BodyContext/GEN_RUNNING 立即触发 del/weak；覆盖时 finalizer 重入 next 被 ValueError 拒绝；随后 generator 仍正常 yield。 |
| terminal_reentry_allocation_unraisable | 终结 del 时 GEN_CLOSED/CallerContext；重入 next 得 StopIteration；新分配对象并再次最终化，world计数0→2；故意 FinalizerFailure 到 unraisablehook，外层返回值仍保留。 |
| coroutine_await_lifecycle | coroutine 与 await wrapper 创建不执行 body；await 中间暂停后 CORO_SUSPENDED；恢复最终返回及 del/weak 在 CallerContext，终态 CORO_CLOSED。 |
| asyncgen_request_vs_body | anext/aclose 请求对象构造不推进 body；anext 内 await 暂停；该请求完成产 item 后不可复用，而 body 仍 AGEN_SUSPENDED；随后独立 aclose 完成且回调见 CallerContext。 |

8组全部 PASS 不表示表里每个打印字段均单独有 assert。尤其 asyncgen 内部 await
暂停时 `owner_state=AGEN_RUNNING`、unraisablehook/child allocation 的具体 context
是已记录的额外观察；脚本明确断言了请求构造无执行、请求耗尽/对象未关闭、后续关闭
以及 normal/abnormal/close/覆盖的关键时序。原始 JSON 是断言与观察的准确分母。

## 4. 需改的 driver/lifecycle 合同

### A. 引用释放 helper 可复用机制，不能合并时点和完成语义

- 复用 canonical Operation/Use、当前 StateAccess、helper Region/INVOKE 表达真实
  retain/release/callback；同一个建图工具可用于 body rebind、终结 frame clear、
  traceback 最后引用消失，但必须标明**真实执行位置、owner、阶段**。
- body rebind/DEL 是 body 中 Attached 的实际操作；终结 frame 清理在所测版本先恢复
  caller。metadata FINISH_BODY 本身继续无回调；真实 release 不能藏进其无效果合同。
- ordinary `__del__` 错误进入 unraisable 通道，不能直接当 driver 的 host RAISE。
  overridden hook 仍是有外部效果的可回调区域；其写和分配要继续沿当前状态传递。
  显式 close/delegate 方法失败则有自己的正常/异常路径，不能共享“错误一律吞掉”。
- 不能把“callback 若返回则保留完成”升级为一定终止或一定释放；本轮未测试
  resurrection、循环垃圾、线程、interpreter shutdown、信号、trace hook 或OOM。

覆盖/删除的实现依据为
[STORE_FAST](https://github.com/python/cpython/blob/v3.14.7/Python/bytecodes.c#L326) /
[DELETE_FAST](https://github.com/python/cpython/blob/v3.14.7/Python/bytecodes.c#L1696)。
Python 总体合同允许延迟回收，外部观察可能保留引用；当前3.14文档已是3.14.8，
这里只作通用边界资料而非本机3.14.7具体时序证据。
[对象生命周期](https://docs.python.org/3.14/reference/datamodel.html#objects-values-and-types)，
[unraisablehook](https://docs.python.org/3.14/library/sys.html#sys.unraisablehook)。

### B. body suspend 不自动结束 async request/互斥 lease

本机 await 暂停时 inspect 给 AGEN_RUNNING；请求继续驱动后产 item，才变为
AGEN_SUSPENDED 且该 request 不可复用。不能把 body 每个 Suspend 都变成“可以由其他
请求抢占的空闲对象”，也不能以 request 完成代表 body Closed。需区分：本次物理
ingress/返回、body suspension generation、跨 await 持续的 request owner/排他 lease。
旧 PUBLISH_SUSPEND“结束本 drive”须明确结束的是哪层，不能无条件释放全部 owner。
其来源是两个实现字段的不同生命周期，而非新造两个静态数字：
[asend 驱动与独立状态](https://github.com/python/cpython/blob/v3.14.7/Objects/genobject.c#L1689)，
[async yield 解包](https://github.com/python/cpython/blob/v3.14.7/Objects/genobject.c#L1637)。
本机 `inspect.py:1868–1885` 首先读 ag_running，然后才读 ag_suspended/frame；这个
传感器结果也不能独自等同于 body 是否正在执行 Python 指令。

### C. 外部 API raw request、归一化与 body-delivered payload 继续分层

root/另一独立见证已发现 throw(ExceptionSubclass) 归一化可回调并嵌套驱动；本轮
没有重复该 probe，不能计入本轮8组 Observed。旧 DriveRequestDefinition.THROW
固定 EXCEPTION_PACKET 只适合**已归一化、实际交付 body 的内层请求**，不能覆盖
外部 raw (type/value/tb) 调用或直接 delegate.throw。准备/lookup/归一化可能在实际
permit/body gate 之前，并已改变同 owner 当前 generation/state。各 gate 的位置
须按具体版本路径连接，不能把 Python 方法调用次数当 body ingress permit。
源码的归一化→实际 send 次序可见
[genobject.c:516–547](https://github.com/python/cpython/blob/v3.14.7/Objects/genobject.c#L516)；
具体 nested callback 结论以另一 agent 的独立见证为准。

## 5. 状态与权限边界

Observed 是上述8个 CPython3.14.7 小程序；Inferred 是它们对阶段/owner/当前状态
接线的要求；Proposed 是对旧 driver 提案的收紧。没有实现或验证 SCAR driver，
没有测 LeWM、性能、对象地址版本、排他原子性或任意 native callback 的完整效果。
在版本、回收策略、frame/traceback 保留、可重入 callback 条件未对应时，只能保留
有类型的保守边界；不能从 GEN_CLOSED 推导“引用已释放且无后续副作用”。

证据 SHA-256：

```text
99f17d20e7a52f3c0b58ef4c2503e203b468190fd6ed8831c0857ba5104c6a05  lifecycle-witness.py
a363bdf0904b7108ece75b02a7d317262033cbddb4f9782e07686cbda3d07f85  lifecycle-witness.json
ebd5e657c82907d18a18b46df53d2113e23792a9efc2e9ca3452993379e66bae  lifecycle-witness.log
```
