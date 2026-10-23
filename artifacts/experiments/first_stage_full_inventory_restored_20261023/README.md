# 全量 inventory 检查点恢复

状态：**Verified：分片归档恢复成功，exit0；完整程序模型仍OPEN。**
`result/manifest.json`已实际发布，63,577字节，SHA256
`1443fedcbd8882e86dee392339a5ea51fd29ea102068a65d9e51e06b347de09e`。
原实验33分49秒后仅因最终JSON超过256MB独立写上限退出2，
1627次真实返回已持久化，其中840次有原ProgramGraph。此处不重新构造body。

`run.sh` 保留原入口、最新272038 capture、environment profile、源发现、队列、
256文件/4096body/100000aggregate operations预算；在`to_dict()`前改用不可变分片
归档，单片采用独立大小限制，不构造巨型JSON。
恢复wrapper全核原1627文件的decoded SHA/size，逐请求核原顺序、源码、snapshot、
profile、entry和剩余操作预算，禁止缺失时回落lower。原源码prepare及调用队列重新
执行；原materialized LoweredSourceBody经公共完整ProgramGraph codec、structured
overlay和原inventory的signature/formal/interface校验后返回，不称fresh重lower。

**Implemented：分片路线**：`run.sh`启动`run_partitioned.py`，在原ProgramInventory
返回后、`to_dict()`之前归档；`result/manifest.json`只保存有序引用，per-source
metadata与global components独立分片，body graph/metadata/interface/structured
直接引用原检查点，不复制图。namespace采用artifact/representation/body/kind/localID，
不假设bareID全局唯一。保留原256MB单文件参数但不走其monolithic writer。

**Rejected / Superseded，未执行**：`run_restored.py`是最初1GB单JSON恢复方案，
因用户要求分片归档而暂停；从未启动该脚本或生成1GB单文件。

`producer.json` 保留原/当前实现版本及逐生产模块SHA；`progress.jsonl`逐条保留
恢复引用；`recovery.json`保存最终状态。原checkpoint保持不变。完整第一阶段仍OPEN：
局部body结果及源码inventory不等于完整数据/状态/资源依赖已闭合。

## 实际恢复结果

| 项目 | Observed / Verified |
| --- | --- |
| 原检查点 | 1627/1627 decoded SHA/size、请求顺序、entry、source、profile、剩余预算匹配 |
| 原图与接口 | 840个ProgramGraph通过完整公共codec、structured/source overlay及原inventory formal/interface检查 |
| 失败 / 未尝试 | 787 UNSUPPORTED；590 NOT_ATTEMPTED，原状态全部保留 |
| 源结构分母 | 151文件、2217定义、122323 source atoms、10235 source calls |
| 原规范图 | 66112 operations、105824 values、91 loops；不是actual occurrences |
| 原构造预算 | 100000 charged operations，含失败body已消耗的构造；未增加预算 |
| 本轮fresh body lowering | 0；恢复的是先前已物化返回，source/call准备重新执行 |
| 实际采集来源 | 最新272038 capture：855 captured codes、817 entered code groups、100438 entered invocations |
| source admissions | 74 CORE_LINKED、351 INDEXED_WITHOUT_BODY，不能改写为已闭合动态依赖 |
| 新归档大小 | 7.8MiB；原CP直接引用，不复制原49MiB检查点 |
| 新片最大decoded大小 | component 5,538,180字节；source 5,373,090字节 |
| 运行成本 | `/usr/bin/time` wall32:46.43，peak RSS1,087,064KiB；不宣称快速恢复或LeWM加速 |

`run.time.txt`包含进程整体时间；`recovery.json`内部计时1959.90秒不包含全部进程
import/startup。原模型构造与独立公共校验成本很大，此次按要求完整保留公共验证。
没有执行新的LeWM/GPU episode、backend、detector或测试套件。

### 剩余恢复缺口

590个NOT_ATTEMPTED中，581个需要class/lambda/comprehension等非普通函数接口，
9个是独立body/aggregate operation预算耗尽。最后`OnlineQueue.setup`在剩余230
operations处达到BUDGET，原null graph保留。全部原因在`body-frontiers.json`。

787个UNSUPPORTED仍是原whole-body rollback结果；典型last-gap包括heap/global/
destructuring写169、Call144、Subscript57、Try49、ImportFrom46、With31、
AugAssign23、Slice23、嵌套FunctionDef23、非scalar literal22、Import18、generator
lifecycle15。分片归档没有把这些缺口变成已实现。module initializer在原source图
中有身份，但没有伪造普通函数body。完整调用actual/formal、环境、state、alias/
provenance和软硬件资源连接仍未闭合；第一阶段未完成。

## 旧source archives实际复用条件

`source-archive-compatibility.json`已逐151文件比较新FileInventory与旧archive index：
**151/151 SourceSnapshot相等，151/151完整SourceContextDigest相等**（namespace_root、
semantic、semantics、control三个SHA均相等）。旧index SHA仍为
`5c68691c28273676a8262f24fe9891e03433f06b7d16758e8620050c160a97c4`。
因此可直接使用`../first_stage_source_context_20261022/result/source-layers`，不再
prepare151个文件。实际loader仍会校验被读取archive的字节和原三图，不借此称本轮
重新构建过旧archive。

## 最小真实reader验收

`reader-query.json`记录自动按最小body片选择的`ReplayBuffer.__enter__`（file94/body3，
原CP01013）：5 operations、11 values；public graph与source/structured overlay及
formal校验均通过，耗时6.52秒。没有源码重构或重lower。namespace实际包含原CP URI/
decodedSHA、`scar.program-graph/5`、`#/graph`、原body与kind/localID，未假设bareID
全局唯一。该查询不表示完整程序模型通过。

分片writer实际源码在`inventory_partitions.py.snapshot`和`archive-producer.json`。
运行结束后reader补强了独立读取上限、缓存副本、CP/header一致性及精确表示namespace；
查询记录单独保存最终reader模块SHA，不能用它替代本次writer执行源码哈希。

## 下一步兼容adapter（Proposed，尚未执行）

1. 保留原CompositionIndex正规类型；输入schema显式区分旧inventory和新partition
   manifest，增加file/body/component及真实artifact locator访问，不拼大JSON。
2. compose按source读取151原archive并按body校验原图一次；body状态引用source shard
   `#/file/bodies/j`，canonical graph引用原CP `#/graph`，metadata/缺口同样用原CP指针。
3. source_invocations通过上述正式访问器读取discovery/call_sources/scope和逐file/body；
   source定义按snapshot+ID限定，保留composition/CP namespace，继续全核本次raw capture。
4. 同272038 capture实际`same_capture`绑定为验收，不调用新的prepare/full episode或
   将源码见证混写成fresh lowering。现有CLI尚不接受新分片输入，不能直接给它该manifest。
