# 原生 Tensor 输入 metadata 保留

2026-10-25。Implemented；真实CPU采集及离线完整回读Verified。这里只保留观察，
没有完成ETO端口连接、普通CaptureCoordinates归属或整程序建模。

现有同一个owned profiler的同一次DFS可额外保存每个TorchOp的输入metadata。
设置`SCAR_NATIVE_TENSOR_INPUTS=1`，并对普通trace启用`--call-operands
--execution-evidence --tensor-physical`；默认V1输出合同保留。新profile
`scar.native-tensor-input-event-tree-v1`生成有界JSONL分块和小manifest，严格reader
核完整字节、行/槽顺序、闭合的native/dispatch/legacy metadata链。

直接Tensor和TensorList分别保原路径、dtype/device/layout/shape/strides及provider IDs；
zero-dimensional Tensor和空list不同。provider的None也可能表示unsupported/undefined，
保OPAQUE，不能重构成真实None。scalar仅存type tag，不存Tensor或scalar内容。
原生outputs未在固定API暴露，明确UNAVAILABLE；held output-marker是另一份输入见证。

真实CPU新feature实验生成43条TorchOp、22块/47007B。原probe在预期空list操作抛出
ValueError时因只catch RuntimeError退出1，finally已正常关闭；原失败保留。
后继离线strict回读exit0/0.100s、GNU0.17s/RSS23716KiB，无Torch导入或新采集。
40项Tensor metadata、6个TensorList（其中空list3）、47项OPAQUE和30项scalar type tag
均来自完整回读。此feature CPU采集一次，与此前collector来源CPU门分别计数。

三源码及完整小样例存档在`codex/native-scalar-model`的3b16c0d2；实际报告位于该分支
`artifacts/experiments/native_tensor_inputs_probe_20261025/RESULT.md`。
主树[应用收据](../artifacts/experiments/native_tensor_inputs_applied_20261025/receipt.json)
保留准确版本。原URI不因复制目录自动迁移；新记录尚未纳入普通owned archive/membership。
旧1901项未定Python身份未因此获资格；没有logical version、alias、内容或ready结论。
