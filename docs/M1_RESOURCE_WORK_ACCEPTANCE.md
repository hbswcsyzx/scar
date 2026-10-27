# R2.1 工作基础：自主验收

日期：2026-10-18。**R2.1 有限接口门通过；完整 R2、R3 和 M0–M2 未完成。**
原关系合同保持：[R0](M1_RESOURCE_EXECUTION_CONTRACT.md)。
字段、实施顺序及公开 API：[计划](M1_RESOURCE_WORK_PLAN.md)、
[工作接口](M1_RESOURCE_WORK_INTERFACES.md)。

## 1. Implemented

- WorkTicketID 区分每次工作；WithinOperation 保留内部提交归属，ExternalWorkSource
  不伪造 core 操作。队列坐标用持久前缀、实例和准确 ResourceAccessBinding。
- 普通效果回查原 StateAccess。INVOKE 状态效果沿本次实际 NORMAL/RAISE 边的
  CompletionResult 到准确 landing formal，不复制 producer/Use/state，不造 common AFTER。
- terminal observation、quiescence 和 ticket-holder retention 分开；失败/取消仍可
  留实际效果 frontier。端点、handle、allocation、物化继续引用已有身份。
- 索引查询给出原端口、host completion、全部终结 observation、quiescence 及借用。
  五张工作表使用 execution v2；原五表为空的 v1 输出、原 program v14 保持。

## 2. Observed failures、修正与限定复审

| 原证据 | 实际情况 | 最终处理 |
| --- | --- | --- |
| `records/attempt001` | 系统 python 不存在的 preflight；原时刻和省略的完整命令未保留。 | 明确标成事后恢复说明，不伪称原始时间戳；有效测试全部激活 lewm。 |
| `records/attempt002` | 10 PASS / 7 FAIL，测试 helper 漏导入 DirectExecution。 | 只补测试 import；`attempt003` 17 PASS，不冒称产品缺陷。 |
| `review/attempt001` 与 `queries/attempt002` | held HandleTarget 的 direct basis 可从 Reference Use 改成 native Data Use，或从其 referent 改成 queue access，仍被接受。后者 root 同时复现 empty queue prefix 跨 run 错接。root 共 11 PASS / 3 FAIL。 | 校验 direct handle 类型和解引用后的实际资源；同类不同 ValueID 可 alias，保留 denotation gap。空 prefix 即使无 ticket 也核对 realm。原反例保留，最终组件通过。 |
| `review/attempt003` | 同 run 另一 activation 观察 outcome 时缺少明确先后对应，没有具体 order gap；该探针后续试图构造非法静态 requirement 时由 core constructor 拒绝，退出 1。 | 只为未知先后增加具体 gap，不误拒合法跨函数观察；静态构造失败原样保留，不称产品 crash。 |
| `component/attempt001` | 首组件 406 PASS。 | 随最后一个 order-gap 反例修正，新增 1 case；最终组件单独保存为 407 PASS，未覆盖旧报告。 |

**Rejected：** host RAISE 即无工作、terminal kind 即 quiescence/free、取消即无写入、
内部提交/借用强置 BEFORE/AFTER、用 table/ID 顺序推设备完成、同类 ValueID 不同即
不是 alias，以及将旧 v2 producer 换前缀变成 core work。

两份最终独立静态 closure：`review/final-closure.md` 和
`review/composition-closure.md`。复审者没有执行最终组件或全仓；root 分开保留
这些运行证据。首 graph 38 PASS、codec 35 PASS 和 query 首轮 11 PASS 均有原命令。

## 3. Verified 范围及冻结回归

| 项目 | 实测结果 |
| --- | --- |
| 最终组件 | `gates/m1_resource_work.json`，**407 cases / 9 criteria / 6.282s PASS**。 |
| 冻结实现 | clean `bb1b402b498e9ce80a701658a59c1471e8ec32ce`。 |
| 唯一完整回归 | **4,297 PASS / 0 failed / 0 errors / 0 skipped**，3 warnings。 |
| 耗时与内存 | 461.7210992919281s 外部；459.81s pytest；peak RSS 1,029,332 KiB。是验收成本，不是 workload benchmark。 |
| 注册源 | 480 文件；前后 SHA `f26bb51ad783f85c43de3a8d75999d9943f915973c629411c0b27b264d57487c`。 |
| 历史保留 | 原 4,192 测试身份和 44 份 fixture 全保留；新增 105 work cases，总 fixture 47。原 472 注册源中 466 字节不变，6 个明确接口集成文件变更，新增 8 项。 |
| v1 独立样本 | 从 immutable `6fcac0f` 隔离生成，**88,521 bytes**，SHA `66ce59c3f04c7b92babaf320127dd9c696b3cc6ecaada76e1e1b50a63095e391`；当前相同 factory 输出字节完全一致。 |
| 环境 | conda lewm：Python 3.14.7、pytest 9.1.1、Torch 2.13.0+cu132、NumPy 2.5.2，未更换环境。 |
| 运行纪律 | 定向检查及复审后 clean 冻结，只跑一次全仓；期间源码/文档不改、没有另开测试；独占 basetemp 在子进程终止后删除。 |

6 个已存在文件的变更为 execution 的 ids/model/codec/validation/query，以及
`test_execution_codec.py` 的“最高 schema=2、旧默认 wire=1”两断言；原 case 身份、
v1 字节和全部旧验证保留。完整逐文件变化见归档 preservation.json。

归档：[model_resource_work](../artifacts/experiments/b1_call_operands/model_resource_work/README.md)。
只读 `check_archive.py` 核对全部 manifests、source/fixture hashes、独立 v1 来源和
所有历史 case 身份；它不重新运行 pytest、provider、GPU 或 LeWM。

LeWM checkout 仍 clean `f70fed80288462ca4d006cb3607ec6da6eaa851f`，SCAR 主目录
仍 clean `84f165fce1e2e37617c974ce9fee574ea816406b`。开发保存在独立分支/worktree。

## 4. Proposed，仍未 Implemented

R2.2 的 EventRecord 代次、跨/同队列 order 到准确消费者开始；R2.3 的 consumer
denotation、production membership/coverage、部分 produced 结果、AND/OR 支持和当前
content/materialization/allocation/domain 匹配；R3 的 load→consume→save/flush/close。
完整 R2 的设计报告保留这些义务，不能用本子门缩小 R2 的完成条件。

本门的结构一致性不等于 native/runtime 对应或协议适用。terminal frontier 不证明
整个输出已产生，声明 quiescence 不证明所有借用已释放；两个授权标志仍为 False。
完整 literal/selector/alias owner、logical provenance、剩余协议及 M2 守恒仍在总计划。
没有新 detector/backend、重型 LeWM profiling、TRANSFORM 或实测 A/B 加速比。
