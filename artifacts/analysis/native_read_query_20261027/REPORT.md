# 原生读取统一查询：局部连接验收

真实未修改 LeWM 的既有记录，公开 `query-native-read` 一次退出0。
11个节点、12条边，所有端点存在，作为无向图连通。CLI 4.731202秒；
普通reader累计stored+decoded 93,799,844字节。完整命令/原输入在RESULT.json。

Implemented：原input reference、Use、invocation、world support/use、normal state
interface、conditional read、本次读的symbolic ValueVersion与原allocation位于同一视图。
Verified：普通reader重核原canonical port/state/allocation/protocol和值图，连接端点存在。
Inferred/conditional：内容读取仍有协议/实际路径/状态足迹/期间稳定性/上游来源条件。
本结果不证明实际内存读取、内容等价、ready或整个LeWM图完成；不是加速比。

图采用与现有ProgramQuery一致的qualified-reference只读视图，原typed IDs/artifacts
保身份，不另立第二个权威图。保留原Run，未重跑episode，未修改LeWM。
