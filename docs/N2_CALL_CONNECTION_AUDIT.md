# 真实调用连接审计与下一门

2026-10-15。输入为原 LeWM 命令的新 calls-only 记录与已验收 v4 inventory；
分析实现 `bedcd2d`，API 严格重放状态 **REPLAYED**。目标程序未被分析器执行
或修改。新预算/索引实现 `677e10f` 的公共 CLI 完整重放亦为 **REPLAYED**，
exit 0、773.944s、峰RSS 5,348,072KiB；冻结源码前后SHA一致。

本报告根据 typed ID、代码指纹、调用记录和源码快照自动 join 得到。下面出现
的外部函数名仅用于解释观测结果，不是 SCAR 的识别或变换规则。

## 1. 实际覆盖

| 指标 | 结果 |
| --- | ---: |
| Python 入口/出口记录 | 84,319 / 84,319 |
| 代码描述 VERIFIED / INCOMPLETE / MISMATCH | 548 / 297 / 5 |
| VERIFIED 且有 source definition 的不同定义 | 421 |
| 源码调用位置观察 / 不同调用位置 | 22,548 / 483 |
| core CALL 观察 / 不同 core CALL | 1,119 / 9 |
| inventory 中不同 core CALL | 110 |
| 本次没有 Python 入口观察的 core CALL | 101 |
| 直接进入已有 target body 的 core CALL | 0 |
| 沿核验 runtime parent 链可到已有 body 的 core CALL | 1 |
| target body 观察 / 不同 body | 1,309 / 9 |
| 引用 occurrence / identity route | 422,349 / 1,808 |

“观察”是逐执行计数，“不同节点”按静态 ID 去重。不能把 1,119 写成 1,119 个
不同程序节点，更不能把它们写成优化机会或可替换区域。
未观察到的101个调用点不能据此删除；其中也可能有 native 调用、未执行路径
或本采集范围不覆盖的行为。该采集不包含 Torch profiler 的物理设备事件。

## 2. 九个已观察 core 调用点逐项

| caller | 源码行 | 观察数 | 实际进入的 Python code |
| --- | ---: | ---: | --- |
| register_fsdp2_strategy | fsdp2.py:397 | 1 | 外部 Lightning registry.available_strategies |
| register_fsdp2_strategy | fsdp2.py:399 | 1 | 外部 Lightning registry.register |
| _load_local_checkpoint | run_inference.py:60 | 1 | load_pretrained；code 核验通过，body 受旧调度预算推迟 |
| _load_local_checkpoint | run_inference.py:62 | 1 | 外部 pathlib.PurePath.__str__ |
| get_config | _config.py:346 | 1 | _GlobalConfig.__new__；code 核验通过，closure/cell 接口尚未支持 |
| Embedder.forward | module.py:206 | 31 | 外部 Torch Module._wrapped_call_impl |
| Embedder.forward | module.py:208 | 31 | 外部 Torch Module._wrapped_call_impl |
| FeedForward.forward | module.py:31 | 900 | 外部 Torch Module._wrapped_call_impl |
| MLP.forward | module.py:239 | 152 | 外部 Torch Module._wrapped_call_impl |

其中1,117次直接目标观察处于声明的项目源码范围之外；另2次源码核验通过，
分别暴露预算推迟与closure接口缺口。这些是连接边界，不是1,117次业务操作
被证明不可优化。

中间 wrapper 的存在不能靠“透明”名称猜测消除。原记录保留 immediate caller、
nearest tracked ancestor 和中间 site。审计沿已经核验的 parent/ancestor 链追踪，
得到1个 core 调用点可经中间层到达已有 body；每条路径均保留全部记录 frame
和中间 site。该结果只证明这次执行的控制嵌套，**不证明参数路由或中间效果**。

## 3. 引用连接的准确边界

1,808条route的组成：SOURCE_RETURN_LOCAL 1,804，RETURN_CALL 2，
OBSERVED_CALL_RETURN 2。没有自动确认的actual→formal来源边。
同weak引用不证明内容稳定，也不证明是某个显式参数、receiver或default的来源。

这解释了为何新记录和代码匹配大幅增加后，仍不能直接批准缓存：

1. 程序 body 覆盖和目标范围尚未闭合；
2. 实际 callable/adapter/default/cell 状态与参数绑定仍缺证据；
3. body 内的 return payload 与 frame 生命周期尚未正确分开；
4. 细粒度状态、循环、alias、环境及 GPU 完成依赖仍未闭合。

本轮没有新detector/backend、TRANSFORM或clean A/B加速比。

## 4. 分析成本与资源修复

| 阶段 | 单次用时 |
| --- | ---: |
| 严格核验已有 inventory | 455.430s |
| 调用连接 | 94.677s |
| 序列化 | 102.265s |
| API报告严格重放 | 329.328s |

峰值RSS 4,980,692KiB。这些是分析器成本，不是workload性能。
v1报告仍展开重复记录，raw 689,976,304字节、gzip 40,504,077字节；完整报告
在本机保存，Git归档摘要、覆盖、命令、测量和SHA。后续应将重复source/site/
anchor记录规范化为共享表，单独验收格式兼容和预算，不能因此放宽证明状态。

本轮先修复实际可用性：公共CLI暴露所有独立CallEdgeBudget字段，以及独立
report解压字节上限；默认report上限仍256MB。输出流式计数并原子替换，超限
不会损坏已有报告。source预算耗尽输出明确SOURCE_BOUNDARY的有限报告；
raw记录/引用/path等预算不满足则拒绝该输入，不伪造完整图。

冻结`677e10f`的自主验收：703项mapped tests、全仓1,738项通过（三项已记录
warning，无失败或skip），指纹
`9d5b8815b0c53c6e2f99a19679fd4bcb967b8d9b30a9decb5c61a17da5ac50c5`。
该有限组件验收不替代E4。完整公共重放命令为：

```bash
python -m scar.cli check-call-links \
  artifacts/experiments/n2_call_edges_lewm_retry_20261015/analysis/links.json.gz \
  --max-files 256 --max-call-report-bytes 800000000 \
  --max-call-trace-bytes 256000000 --max-call-trace-events 250000 \
  --max-call-references 2000000
```

公开入口实际结果及命令见
`artifacts/reports/gates/n2-call-connections-public.json` 与同名 `.time`。
其summary与API一致；这次耗时包含读取、inventory重放及report重放，不能与
上表单一阶段直接比较，更不是workload加速比。

源码索引修复消除每次返回重复遍历整个AST，正常LIFO退出也不再扫描栈。
索引与原文件级匹配规则的节点、顺序和歧义条件一致。没有实测热点占比或
clean分析器A/B，因此暂不声明实际提速。

重试trace已无损压缩：160,232,525原始字节缩至7,787,292字节，逐文件重算
解压SHA一致后才移除本轮生成的plain副本。原始LeWM数据、环境、源码均保留。

## 5. 下一阶段依赖顺序

1. **C0：返回引用与frame生命周期**。依据
   [Frame计划](N2_FRAME_LIFETIME_PLAN.md) 建立typed ENTER/BIND/DISCARD/EXIT，
   保留payload来源与coarse world后态、unraisable/可能不完成/逃逸义务。
2. **C1：实际调用与环境**。独立建模函数对象、receiver、partial、default和
   cell；先证明原始callee operand及参数位置，再生成来源边，禁止按同引用猜测。
3. **新运行证据驱动需求展开**。将已核验code、调用链及目标缺口接入自动
   body需求队列；库边界保留或由通用操作规则展开。源码范围、预算和不支持
   接口分别报告，不能要求手工函数名单或手工wrapper跳转。
4. **循环与细状态/provenance**。恢复携带值、状态、alias及完成依赖，再从
   观察根计算保守依赖闭包，产生具体替换、提升、复用或删除指导。

完整N2.call-edges的E4要求保留，未通过项不能由新的有限组件gate代替。
