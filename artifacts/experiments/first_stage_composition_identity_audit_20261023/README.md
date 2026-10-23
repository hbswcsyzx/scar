# 原命名空间与组合身份审计

2026-10-23。**Verified：只读SQL与两个原checkpoint核对通过。**

原数据库SHA重新核为5e9a7461b68268a630cf926d59ecfb1e7e498549d8500534f7d309fa81a32fbe，
481,460,224bytes；mode=ro/query_only及单读取事务，没有复制/重建数据库。
对437,228实体、840namespaces按kind+local_id分组：106组StateLocation重复、830次
出现，最大66个namespace。索引本来就用namespace+kind+local_id，未发现索引冲突。

最大组的两个实际原checkpoint分别回读#/graph/locations/0，decoded SHA准确匹配
原namespace：同local ID、相同coarse-world声明、不同原root/body。它们不是两次
运行的状态相等证据；不同local ID也不证明没有状态影响。

原stdout/result/time完整保留。脚本一次exit0，2.93s、peakRSS35,692KiB；未import
SCAR、prepare/compile/执行目标，不生成ProgramSnapshot或全局模型。SQL及原端点/
source namespace、两个checkpoint的stored/decoded receipts见result.json。

这是身份边界核查，不是整个数据库关系语义复验或新的完整程序验收。当前API和
下一连接顺序见docs/COMPOSITE_MODEL_CONNECTION.md；S3/S4仍OPEN。
