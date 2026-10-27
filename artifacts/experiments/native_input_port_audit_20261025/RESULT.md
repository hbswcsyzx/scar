# 原生输入路径有界审计

2026-10-25。Root session43964实际exit0，1.053096s；没有新采集、目标执行、OS读取、
Torch导入或旧LeWM raw/DB扫描。工具与prepared plan的原字节保存在本目录。

只读同一CPU capture的11个准确白名单文件，每个一次；stored632786B、
decoded7266168B，合计7898954B，低于64MB硬界。此处计费范围为证据payload，
不包含工具源码/plan自身的读取。

2332行中2330组通过同capture tree correlation→Kineto External id/Record function id
→ETO rf_id连接；没有用correlation数值等于RF替代桥接。3095项metadata都有准确原生
Tensor输入路径，2069项可比parent关系无矛盾。zero-dimensional metadata3084，
empty TensorList3。没有contradiction或重复join key。

782组缺schema text、2行缺ETO RF，261项parent位于导出边界之外；schema存在不等于
形式端口已经合法解析。provider的None/opaque、offset及其它未暴露字段保持缺口。
本门创建NativeInputRef/ObjectID/LogicalVersion均0；路径候选不授几何、内容、alias、
状态或resource ready资格。下一步复用G1的规范native bundle/schema及现有边界producer，
需要同snapshot的OccurrenceEvidenceBinding，不能伪造规范引用或再重复import。

完整逐行审计与设计已归档在`codex/native-scalar-model`的
`7946a40fd3e5f9b01f68f4fdf3423f3ff2cb7cd3`：
`analysis/native_input_port_adapter_20261025/PLAN.json`，post-plan SHA
`66c9b23e45e853034ab905c59d644d87289db3b87123eeb63969a36dd5c2e93d`。
本目录stdout与time保留实际结果；原URI和Run命名空间不因存档复制而迁移。
原LeWM source858/runtime843和第一阶段OPEN均不变。
