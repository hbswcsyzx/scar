# 条件调用报告到原图端点的限定查询

2026-10-23。**Implemented / Verified：旧272038及当前369749各自原档的27条参数、
27条completion查询均通过；两次分别绑定自己的Run与source/bindings。**

实现为`scar/analysis/call_endpoint_queries.py`。它补的是已有图/报告之间的查询连接，
不是detector、优化器、新producer/state图或完整ExecutionModel。

## 1. 输入与职责

```python
from scar.analysis.call_endpoint_queries import CallEndpointQueries
from scar.analysis.inventory_partitions import InventoryPartitions
from scar.store.graph_index import GraphIndex

with GraphIndex(index_path) as graph:
    queries = CallEndpointQueries(
        graph, InventoryPartitions(inventory_manifest), route_report_manifest,
        expected_run=original_execution_run,
        source_report=original_source_report_path,
        source_bindings=original_source_bindings_path,
    )
    actual_to_formal = queries.argument(0)
    returned_value = queries.completion(0)
    original_entity = queries.endpoint(qualified_reference)
```

`qualified_reference`复用GraphIndex的`{namespace, kind, local_id}`。支持原Region、
Block、Operation、Value、Use、StateLocation、ResourceDefinition和ResourceRequirement。
namespace必须属于该报告已选择的原body，不能省略artifact/representation/body。
这不是整个程序全部实体的枚举入口；未选择的namespace要通过相应原图/范围查询，
不能根据本接口拒绝就推断该实体不存在。

构造器核准确Run、source report/bindings的原SHA/bytes/path、composition SHA、
inventory receipt，以及查询库和原分片inventory的同一快照。输入路径显式提供；
report中的chunk/header只能在原report目录内取回。不跟随任意source URI读文件。
当前不提供保留档的隐式搬迁/重命名猜测。

## 2. 查询怎样保持原事实

1. 报告仍使用已经发布的`scar.partitioned-call-operand-links/1`格式。按所选table
   ordinal定位真实chunk/JSONL line；核stored/decoded SHA、bytes和完整行数，只保
   两个有限chunk。没有重构99MB单报告，也没有增加另一份序列化格式。
2. 用原typed ArgumentRoute/CompletionRoute严格解码，绑定同Run及原进程范围。
   每条原路由的条件完整返回，不以数据端点可解析消除guard。
3. 根据SourceBodyAccess的唯一namespace映射，使用原InventoryPartitions公共
   typed_body读取需要的body；核原definition、root、interface、namespace。只保两个
   body；不加载151/106份源码，不prepare/compile，不回放目标或源码构造。
4. 参数查询核原call/core来源、actual Use的owner/有序位置/value、formal slot/value
   为原声明参数，以及实际参数SourceReference。返回两端GraphIndex原实体receipt/
   pointer，不重写producer。
5. completion查询核原invoke正常payload、callee RETURN的payload Use/value和状态
   Use，返回`callee_post_world`及其限定StateLocation。它**不是已证caller post-world**。

局部公共ProgramGraph校验与原端点归属在这里重核；source overlays、原始frame事件、
dispatch、控制选择、function environment和内容/状态/alias等证明不在查询时重放。
这是已生产原档的查询适配器，不是抵御伪造report的签名服务；SHA证明字节对应，
不证明任意写了`verified=true`的报告具有可信runtime producer。

## 3. 输出与证明边界

每个回答带原route、完整route/source conditions、准确Run和report record locator，
以及各端点原namespace/typed ID/record type/receipt/pointer。
`original_endpoint_membership_verified=True`只表示已核原端点归属；以下均仍False：
runtime control、跨body状态域身份、world等价、内容/alias等价、完整程序及变换授权。
索引尚未覆盖的关系也仍明确保留。

相同StateLocation文本不会触发跨图合并；不同文本不会被视作disjoint证明。沿一条
现有条件边能够导航，不表示那条边的全部合法性义务已完成，更不表示可执行reuse。

## 4. 实际验收

实验`first_stage_call_endpoint_queries_20261023/attempt01`一次exit0：

- 旧Run全部27条argument、27条completion回到原typed body/SQLite实体，原条件保留。
- 裸ID、错误namespace、错误端点类型和另一Run被同一公开入口拒绝。
- 同时固定原report/source/bindings/coordinates/inventory与SQLite SHA、实际imported
  producers；当前活跃source gate的既有生产文件没有修改。
- wall2.98s、脚本2.87s、RSS62,052KiB；无prepare/compile/目标执行或测试套件。

随后同一入口对完成后的369749报告实际exit0：27+27全部回原端点，4种误用均拒绝，
脚本2.90s、RSS78,480KiB；它使用自己的coordinates/source/bindings与相同原inventory
索引。旧运行的27+27结果没有移入本次新运行。
完成端点导航后仍需真实state/world与逻辑来源关联；第一阶段S3/S4保持OPEN。
