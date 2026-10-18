# R3.3 同步调用 host HB：有限实施报告

状态：**IMPLEMENTED_WITH_FOCUSED_VALIDATION**；仅同步 host 边界，不授 source/runtime/native authority。
本门基线由 root 指定 `bccefcfb65dcdba71c050cbbecadd3b2f30f3fa2`。
未更改旧 fixtures、wire/model、OS witnesses 或其他 owner 模块；未启动 component/full/GPU/LeWM。

## 1. 原接口接线

新增 `host_order.py` 仅为原记录的可重建索引，HostOrderStep 不是 ExecutionModel/ProgramGraph 新记录或权威事实。

| 接口 | 含义 |
| --- | --- |
| `prepare_host_order(ctx)` | core/flow/call 全通过后准备静态 op 位置与原 CallActivation 派生桥。 |
| `local_point_precedes(ctx,left,right)` | 保留原同 activation True/False/None；同 visit 逆序 False，跨 visit 逆向或不连通 None。 |
| `host_steps(ctx,point,targets=(),*,budget=None)` | 原 call 桥与原 local CFG 到需要端点的路径；不是 producer/actual 转发。 |
| `host_path(ctx,left,right,*,budget=None)` | 有限可达路径，返回原 HostOrderStep tuple 或 None；P/V 必须传同一 budget。 |
| `ctx.point_precedes(...,budget=None)` | 保留 local 语义；不同 activation 只在准确同步桥组成路径时新增 True，否则 None。 |

`call_validation` 复用其已有 visit-chain 算法，保存一次 `host_visit_chains`，不按 query 重建。
`validation._analyze` 在 call_errors 通过后调用 prepare；外部 refresh 复用此 canonical foundation 并复制可变索引容器。
没有在早期空 map 上建立永久缓存；没有按静态 callee/EEG parent/name/value 猜动态 child。

### 只有两类跨 activation 桥

1. **entry**：caller BEFORE → 该 CallActivation.entry visit 的首个规范 Operation 已捕获 occurrence BEFORE。
   首规范 op 缺失时不改选更晚的已捕获 op；entry Unresolved 不补桥。
2. **completion**：准确 child RETURN/RAISE AFTER → 普通 CALL 的 caller AFTER，或 INVOKE 的实际 taken EDGE。
   INVOKE 缺 transfer 不默认 NORMAL，不使用 common AFTER；错误 successor 不能成为已知边。

两端 known host thread 必须准确相同；已知 process/run/thread 矛盾仍由原 call validator 拒绝。
未知 thread 的 CallActivation 仍保留原声明和 gap，但不产生对应 host 桥。
entry 与 completion 的独立已知事实分别处理：entry 未知不伪造入口，也不抹掉准确完成端。
missing completion 不根据同 child 恰有一个 RETURN 重新选择；实际已捕获的原 op 仍在 inventory。

## 2. 预算、收敛与边界

准备阶段按原 flow/occurrences/call rows 建立有限索引，其 record/FK/容器成本按原 API 另列。
同 activation 查询由 chain/component/rank 和静态位置 O(1) 比较，不重新逐前驱扫描。
跨调用 search 只遍历原 call 边界和需要的原 host 端点；previous 去重保证有限收敛。
`host_order_nodes/host_order_edges` 逐访问扣同一 ValidityBudget，包含 local 候选比较；无查询内新 4096 allowance。
`validity_order.point_order` 返回含原 CallActivation support 的条件路径；混合 resource/association 搜索沿相同预算接入 host_steps。
反向准确 host path 可判 CONTRADICTED；缺证据保留 UNRESOLVED，不从行序或时钟补边。

validator 不带 budget 的有限可达检查属于准备/FK 成本，不宣称所有 CPU 受 query 的 4096 限制。
这些桥只表达同步 host 调用：不接 WorkStart/WorkEnd，不从 host Return/RAISE 推 GPU/资源 terminal、quiet、borrow release、flush 或 persist。
所有源/runtime/identity/native 对应仍未证明；同 scope 的错误动态配对不保证从静态声明识别。

## 3. 实际有限测试与原失败

全部命令前缀：

```bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python artifacts/experiments/b1_call_operands/model_pipeline_closure/focus.py ...
```

各 attempt 保留确切 Python 版本、完整 command、注册源码 before/after SHA、JUnit、stdout/stderr、退出码与临时目录清理 receipt。

- `call_order/attempt001`，selector `tests/unit/test_execution_call_order.py`：首个可执行版本 **6 PASS / 0.60s**。
- `call_order/attempt002`，同 selector：扩展矩阵 **15 PASS / 0.69s**。
  包含 siblings、nested、静态递归不同 activation、有真实规范 base block、N/R actual EDGE、缺 entry/首 op/completion/transfer、
  unknown/冲突 thread、跨 run 不借同 callee、逆向、local 旧语义、fresh 索引容器、低预算、host return 不补 WorkEnd。
- `call_order_compat/attempt001`，旧 V query/stability/call-boundary 三文件：**38 PASS / 1 FAIL / 3.37s**。
  真实回归为旧 `test_unused_other_version_candidate_does_not_poison_valid_covering_combination` 默认4096得到 TRUNCATED 而非 MATCHED。
  原因：首版把已有 O(1) local 关系也送 host BFS，增加无必要预算开销。原日志不覆盖。
- 修正仅恢复同 activation direct local 快路，跨 activation 保留预算 search，并去除自点重复扣费。
  没有提高预算、改旧断言、删除旧候选或放宽关系。
- `call_order_compat/attempt002`，以上三文件加 owned call_order：**54 PASS / 3.46s，exit 0**。
  即 **15 owned + 39 旧兼容**；与前两 attempt 的重复子集不累加成新增 case 数或建模覆盖率。

新增 `nested_call_order_execution(*,recursive=False)` 返回 program/model/details；details 有 calls/returns/entries/activations。
recursive=True 仍是类型与真实 CFG 声明：没有解释原 DataValue 真值或自动证明跨调用参数值对应、运行终止，不冒充真实 Python recursion witness。

## 4. 最后联调窄改与冻结 SHA

最后按 root 明确要求，只给 `refresh_external_context` 的 external-reset 集合追加 `_endpoint_profile_cache`。
该缓存已按 snapshots identity/scoped artifact 定 key；fresh 仍排除旧 cache，避免累积/旧验证结果跨 query 使用。
54 项受测 validation SHA 为 `4d1ac7a858ed6741a084abe06bd0be7a70fdbb6037bdd6970cd7c47049e956db`。
下面最终 validation 只多一个 reset 字段；**未把旧54P当此新SHA的重测**，由 A 的 fresh-profile 测试和 root 统一组件覆盖。

```text
a3dacaf57ec45fc1e57d3139a82675c5af6a1b3d19409cdec3b990edc2fabc02 scar/ir/execution/host_order.py
4b828b9a95b5d46b82c5fb3045d514b277dd586bfa3747376807e64f2a624896 scar/ir/execution/validation.py
c569e2b039e1f2c63760b02092e61a5d0e7799a50421f51598acd27f41c78368 scar/ir/execution/validity_order.py
9b9de07e1002e4f2c973dba2a48fac44e7ecfde546caf191a8b47c192adb09c2 scar/ir/execution/call_validation.py
9544b9abc87ba2993e536f3fbad1845cb81768d50490d580ca25155f1856fa6b tests/unit/test_execution_call_order.py
f188de3a620f35477f82e5de7ab7a2ada2a6a466e6bf7ddc09e4fee358bb9682 tests/fixtures/execution_call_order_graphs.py
```

owned 产品与测试现冻结，等待独立源审和统一组件。未新增 OS 实验、协议解析器、wire、backend 或优化授权。
